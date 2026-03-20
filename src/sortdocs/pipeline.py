from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from sortdocs.ai_client import AIClientError, OpenAIClassificationClient, build_classification_signature
from sortdocs.config import SortdocsConfig
from sortdocs.executor import ExecutionProgressEvent, PlanExecutor
from sortdocs.extractors import OCRBackend, get_extractor
from sortdocs.memory import LocalMemoryStore
from sortdocs.state_store import ProcessingStateStore
from sortdocs.models import ClassificationResult, ExecutionReport, PlannedAction
from sortdocs.planner import Planner
from sortdocs.scanner import (
    DirectoryScanReport,
    DirectoryScanner,
    DiscoveredFile,
    ScannerOptions,
    SkippedDirectory,
)


LOGGER = logging.getLogger(__name__)
FALLBACK_CATEGORY = "uncategorized"
FALLBACK_SUBCATEGORY = "review"


@dataclass(frozen=True)
class PipelineOptions:
    dry_run: bool
    recursive: bool = False
    max_files: Optional[int] = None
    compute_sha256: bool = False
    allow_project_root: bool = False


@dataclass(frozen=True)
class PipelinePlan:
    discovered_files: list[DiscoveredFile]
    classifications: list[ClassificationResult]
    actions: list[PlannedAction]
    skipped_directories: list[SkippedDirectory] = field(default_factory=list)
    cache_hits: int = 0


@dataclass(frozen=True)
class PipelineProgressEvent:
    stage: str
    current: int = 0
    total: Optional[int] = None
    current_path: Optional[Path] = None
    cache_hits: int = 0


@dataclass(frozen=True)
class PipelineResult:
    discovered_files: list[DiscoveredFile]
    actions: list[PlannedAction]
    execution_report: ExecutionReport
    skipped_directories: list[SkippedDirectory] = field(default_factory=list)
    cache_hits: int = 0


class SortdocsPipeline:
    def __init__(
        self,
        config: SortdocsConfig,
        *,
        library_dir: Path,
        review_dir: Path,
        ai_client_factory: Optional[Callable[[SortdocsConfig], OpenAIClassificationClient]] = None,
        ocr_backend: Optional[OCRBackend] = None,
    ) -> None:
        self._config = config
        self._library_dir = library_dir.expanduser().resolve()
        self._review_dir = review_dir.expanduser().resolve()
        self._ai_client_factory = ai_client_factory or OpenAIClassificationClient
        self._ocr_backend = ocr_backend
        self._ai_client: Optional[OpenAIClassificationClient] = None
        self._memory_store = LocalMemoryStore.load(
            root_dir=self._library_dir,
            config=self._config.memory,
        )
        self._state_store = ProcessingStateStore.load(
            root_dir=self._library_dir,
            config=self._config.state,
            signature=build_classification_signature(self._config),
        )

    def run_directory(
        self,
        source_dir: Path,
        *,
        dry_run: bool,
        recursive: bool = False,
        max_files: Optional[int] = None,
        compute_sha256: bool = False,
        allow_project_root: bool = False,
        progress_callback: Optional[Callable[[PipelineProgressEvent], None]] = None,
    ) -> PipelineResult:
        plan = self.plan_directory(
            source_dir,
            recursive=recursive,
            max_files=max_files,
            compute_sha256=compute_sha256,
            allow_project_root=allow_project_root,
            progress_callback=progress_callback,
        )
        execution_report = self.execute_plan(plan, dry_run=dry_run)

        return PipelineResult(
            discovered_files=plan.discovered_files,
            actions=plan.actions,
            execution_report=execution_report,
            skipped_directories=plan.skipped_directories,
            cache_hits=plan.cache_hits,
        )

    def plan_directory(
        self,
        source_dir: Path,
        *,
        recursive: bool = False,
        max_files: Optional[int] = None,
        compute_sha256: bool = False,
        allow_project_root: bool = False,
        progress_callback: Optional[Callable[[PipelineProgressEvent], None]] = None,
    ) -> PipelinePlan:
        _emit_progress(progress_callback, PipelineProgressEvent(stage="scanning"))
        options = PipelineOptions(
            dry_run=True,
            recursive=recursive,
            max_files=max_files,
            compute_sha256=compute_sha256,
            allow_project_root=allow_project_root,
        )
        scan_report = self._scan_directory(source_dir, options=options)
        discovered_files = scan_report.discovered_files
        _emit_progress(
            progress_callback,
            PipelineProgressEvent(
                stage="scan_complete",
                total=len(discovered_files),
            ),
        )
        root_directory_context = _build_directory_context(source_dir)
        cache_hits = 0
        classifications: list[ClassificationResult] = []
        for index, discovered_file in enumerate(discovered_files, start=1):
            classification, used_cache = self._classify_discovered_file(
                discovered_file,
                directory_context=_merge_directory_context(
                    root_directory_context,
                    discovered_file=discovered_file,
                    memory_context=self._memory_store.build_context_for_file(
                        original_filename=discovered_file.absolute_path.name,
                    ),
                ),
            )
            classifications.append(classification)
            cache_hits += int(used_cache)
            _emit_progress(
                progress_callback,
                PipelineProgressEvent(
                    stage="classifying",
                    current=index,
                    total=len(discovered_files),
                    current_path=discovered_file.relative_path,
                    cache_hits=cache_hits,
                ),
            )
        planned_items = list(zip(discovered_files, classifications))

        planner = Planner(
            self._config,
            library_dir=self._library_dir,
            review_dir=self._review_dir,
        )
        plan = PipelinePlan(
            discovered_files=discovered_files,
            classifications=classifications,
            actions=planner.plan_files(planned_items),
            skipped_directories=scan_report.skipped_directories,
            cache_hits=cache_hits,
        )
        _emit_progress(
            progress_callback,
            PipelineProgressEvent(
                stage="planning_complete",
                current=len(discovered_files),
                total=len(discovered_files),
                cache_hits=cache_hits,
            ),
        )
        return plan

    def execute_actions(self, actions: list[PlannedAction], *, dry_run: bool) -> ExecutionReport:
        return PlanExecutor().execute(actions, dry_run=dry_run)

    def execute_plan(
        self,
        plan: PipelinePlan,
        *,
        dry_run: bool,
        progress_callback: Optional[Callable[[ExecutionProgressEvent], None]] = None,
    ) -> ExecutionReport:
        report = PlanExecutor().execute(
            plan.actions,
            dry_run=dry_run,
            progress_callback=progress_callback,
        )
        if not dry_run:
            self._update_memory(plan, report)
        return report

    def _scan_directory(self, source_dir: Path, *, options: PipelineOptions) -> DirectoryScanReport:
        excluded_patterns = _load_ignore_patterns(
            source_dir=source_dir,
            configured_patterns=self._config.scanner.exclude_patterns,
            ignore_filename=self._config.scanner.ignore_filename,
        )
        scanner = DirectoryScanner(
            ScannerOptions(
                recursive=options.recursive,
                max_files=options.max_files,
                compute_sha256=options.compute_sha256,
                include_unsupported=True,
                allow_project_root=options.allow_project_root,
                excluded_patterns=excluded_patterns,
            )
        )
        return scanner.scan_report(source_dir)

    def _classify_discovered_file(
        self,
        discovered_file: DiscoveredFile,
        *,
        directory_context: dict[str, object],
    ) -> tuple[ClassificationResult, bool]:
        cached = self._state_store.lookup(discovered_file)
        if cached is not None:
            return cached, True

        if not discovered_file.is_supported:
            return self._build_review_classification(
                discovered_file=discovered_file,
                reason=_build_reason(
                    prefix="File type was not safe to classify automatically.",
                    warnings=discovered_file.warnings,
                ),
                tags=["unsupported"],
            ), False

        extractor = get_extractor(
            discovered_file.absolute_path,
            max_chars=self._config.extraction.max_chars,
            ocr_backend=self._ocr_backend,
        )
        extracted_content = extractor.extract(discovered_file.absolute_path)

        try:
            classification = self._get_ai_client().classify_file(
                extracted_content=extracted_content,
                original_filename=discovered_file.absolute_path.name,
                relative_path=discovered_file.relative_path,
                directory_context=directory_context,
                absolute_path=discovered_file.absolute_path,
            )
        except AIClientError as exc:
            LOGGER.warning(
                "Classification failed for %s; routing file to review. Error: %s",
                discovered_file.relative_path,
                exc,
            )
            return self._build_review_classification(
                discovered_file=discovered_file,
                reason=_build_reason(
                    prefix="Automatic classification failed and the file was routed to review.",
                    warnings=[*discovered_file.warnings, *extracted_content.extraction_warnings],
                    detail=str(exc),
                ),
                tags=["review"],
            ), False

        return classification, False

    def _get_ai_client(self) -> OpenAIClassificationClient:
        if self._ai_client is None:
            self._ai_client = self._ai_client_factory(self._config)
        return self._ai_client

    def _build_review_classification(
        self,
        *,
        discovered_file: DiscoveredFile,
        reason: str,
        tags: list[str],
    ) -> ClassificationResult:
        return ClassificationResult(
            category=FALLBACK_CATEGORY,
            subcategory=FALLBACK_SUBCATEGORY,
            suggested_filename=discovered_file.absolute_path.name,
            confidence=0.0,
            reason=reason,
            tags=tags,
            needs_review=True,
        )

    def _update_memory(self, plan: PipelinePlan, report: ExecutionReport) -> None:
        should_update_state = self._config.state.enabled

        for discovered_file, classification, result in zip(
            plan.discovered_files,
            plan.classifications,
            report.results,
        ):
            if not result.success:
                continue
            if self._config.memory.enabled:
                self._memory_store.remember(
                    classification=classification,
                    action=result.action,
                    source_filename=discovered_file.absolute_path.name,
                )
            if should_update_state:
                self._state_store.forget(discovered_file.relative_path)
                final_path = result.final_destination or result.action.source_path
                self._state_store.remember(
                    file_path=final_path,
                    classification=classification,
                )
        if self._config.memory.enabled:
            self._memory_store.save()
        if should_update_state:
            self._state_store.save()


def _build_reason(*, prefix: str, warnings: list[str], detail: Optional[str] = None) -> str:
    parts = [prefix.strip()]
    if detail:
        parts.append(detail.strip())
    if warnings:
        parts.append(f"Warnings: {' | '.join(warnings[:3])}")
    return " ".join(part for part in parts if part)[:500]


def _build_directory_context(source_dir: Path) -> dict[str, object]:
    top_level_directories: list[str] = []
    nested_directories: list[str] = []

    try:
        top_level_entries = sorted(source_dir.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return {}

    for entry in top_level_entries:
        if not _is_context_directory(entry):
            continue
        top_level_directories.append(entry.name)
        try:
            child_entries = sorted(entry.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in child_entries:
            if _is_context_directory(child):
                nested_directories.append(str(child.relative_to(source_dir)))

    return {
        "managed_root_name": source_dir.name,
        "top_level_directories": top_level_directories[:40],
        "nested_directories": nested_directories[:120],
    }


def _merge_directory_context(
    root_context: dict[str, object],
    *,
    discovered_file: DiscoveredFile,
    memory_context: dict[str, object],
) -> dict[str, object]:
    current_parent = discovered_file.relative_path.parent
    sibling_directories: list[str] = []
    absolute_parent = discovered_file.absolute_path.parent
    try:
        entries = sorted(absolute_parent.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        entries = []

    for entry in entries:
        if _is_context_directory(entry):
            sibling_directories.append(entry.name)

    return {
        **root_context,
        "current_parent": None if str(current_parent) == "." else str(current_parent),
        "current_sibling_directories": sibling_directories[:40],
        "local_memory_hints": memory_context,
    }


def _is_context_directory(path: Path) -> bool:
    name = path.name
    if not path.is_dir():
        return False
    if name.startswith(".") or name.startswith("~$"):
        return False
    if path.is_symlink():
        return False
    return True


def _emit_progress(
    callback: Optional[Callable[[PipelineProgressEvent], None]],
    event: PipelineProgressEvent,
) -> None:
    if callback is None:
        return
    callback(event)


def _load_ignore_patterns(
    *,
    source_dir: Path,
    configured_patterns: list[str],
    ignore_filename: str,
) -> tuple[str, ...]:
    patterns: list[str] = list(configured_patterns)
    ignore_path = source_dir / ignore_filename
    if not ignore_path.exists() or not ignore_path.is_file():
        return tuple(patterns)

    try:
        lines = ignore_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        LOGGER.warning("Could not read ignore file %s: %s", ignore_path, exc)
        return tuple(patterns)

    seen = set(patterns)
    for line in lines:
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        normalized = cleaned.replace("\\", "/")
        if normalized in seen:
            continue
        seen.add(normalized)
        patterns.append(normalized)
    return tuple(patterns)

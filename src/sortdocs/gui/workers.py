from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, Signal

from sortdocs.config import SortdocsConfig, load_config
from sortdocs.pipeline import PipelinePlan, SortdocsPipeline


@dataclass(frozen=True)
class GuiRunContext:
    source_dir: Path
    config: SortdocsConfig
    config_path: Optional[Path]
    library_dir: Path
    review_dir: Path
    recursive: bool
    max_files: Optional[int]


@dataclass(frozen=True)
class AnalysisResultBundle:
    context: GuiRunContext
    plan: PipelinePlan


class WorkerSignals(QObject):
    progress = Signal(object)
    finished = Signal(object)
    error = Signal(str)


class AnalysisWorker(QRunnable):
    def __init__(self, *, source_dir: Path) -> None:
        super().__init__()
        self.source_dir = source_dir.expanduser().resolve()
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            config, config_path = load_config(base_dir=self.source_dir)
            context = GuiRunContext(
                source_dir=self.source_dir,
                config=config,
                config_path=config_path,
                library_dir=_resolve_output_dir(self.source_dir, config.cli.library_dir),
                review_dir=_resolve_output_dir(self.source_dir, config.cli.review_dir),
                recursive=config.cli.recursive,
                max_files=config.cli.max_files,
            )
            pipeline = SortdocsPipeline(
                config,
                library_dir=context.library_dir,
                review_dir=context.review_dir,
            )
            plan = pipeline.plan_directory(
                context.source_dir,
                recursive=context.recursive,
                max_files=context.max_files,
                progress_callback=self.signals.progress.emit,
            )
        except Exception as exc:  # pragma: no cover - Qt workers are easier to verify via integration
            self.signals.error.emit(str(exc))
            return

        self.signals.finished.emit(AnalysisResultBundle(context=context, plan=plan))


class ApplyWorker(QRunnable):
    def __init__(self, *, analysis_bundle: AnalysisResultBundle) -> None:
        super().__init__()
        self.analysis_bundle = analysis_bundle
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            context = self.analysis_bundle.context
            pipeline = SortdocsPipeline(
                context.config,
                library_dir=context.library_dir,
                review_dir=context.review_dir,
            )
            report = pipeline.execute_plan(
                self.analysis_bundle.plan,
                dry_run=False,
                progress_callback=self.signals.progress.emit,
            )
        except Exception as exc:  # pragma: no cover - Qt workers are easier to verify via integration
            self.signals.error.emit(str(exc))
            return

        self.signals.finished.emit(report)


def _resolve_output_dir(source_dir: Path, configured_path: Path) -> Path:
    expanded = configured_path.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (source_dir / expanded).resolve()

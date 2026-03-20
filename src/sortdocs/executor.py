from __future__ import annotations

import csv
import json
import logging
import shutil
import uuid
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

from sortdocs.guardrails import validate_planned_action
from sortdocs.models import (
    ActionType,
    ExecutionCounts,
    ExecutionIssue,
    ExecutionMetrics,
    ExecutionReport,
    ExecutionResult,
    PlannedAction,
)


LOGGER = logging.getLogger(__name__)


class ReportFormat(str, Enum):
    JSON = "json"
    CSV = "csv"


class FileOperationMode(str, Enum):
    MOVE = "move"
    COPY = "copy"


class PlanExecutor:
    def execute(
        self,
        actions: list[PlannedAction],
        *,
        dry_run: bool,
        operation_mode: FileOperationMode = FileOperationMode.MOVE,
    ) -> ExecutionReport:
        results: list[ExecutionResult] = []
        seen_sources: set[Path] = set()

        for action in actions:
            result = self._execute_action(
                action=action,
                dry_run=dry_run,
                operation_mode=operation_mode,
                seen_sources=seen_sources,
            )
            results.append(result)

        return ExecutionReport(
            dry_run=dry_run,
            copy_mode=operation_mode == FileOperationMode.COPY,
            results=results,
            counts=_build_counts(results),
            metrics=_build_metrics(results),
            errors=_build_errors(results),
        )

    def write_report(
        self,
        report: ExecutionReport,
        path: Path,
        *,
        report_format: Optional[ReportFormat] = None,
    ) -> Path:
        resolved_path = path.expanduser().resolve()
        final_format = report_format or infer_report_format(resolved_path)

        if resolved_path.exists():
            raise FileExistsError(f"Report file already exists: {resolved_path}")

        resolved_path.parent.mkdir(parents=True, exist_ok=True)

        if final_format == ReportFormat.JSON:
            payload = _serialize_report(report)
            resolved_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        elif final_format == ReportFormat.CSV:
            write_csv_report(report, resolved_path)
        else:  # pragma: no cover - defensive fallback
            raise ValueError(f"Unsupported report format: {final_format}")

        LOGGER.info("Wrote execution report to %s", resolved_path)
        return resolved_path

    def _execute_action(
        self,
        *,
        action: PlannedAction,
        dry_run: bool,
        operation_mode: FileOperationMode,
        seen_sources: set[Path],
    ) -> ExecutionResult:
        if action.action_type == ActionType.SKIP:
            LOGGER.info("Skipping %s; already in the desired location.", action.source_path)
            return ExecutionResult(
                action=action,
                final_destination=None,
                executed=False,
                success=True,
                operation=operation_mode.value,
                message="Skipped.",
                source_size_bytes=_safe_source_size(action.source_path),
            )

        source_path = action.source_path.resolve()
        target_path = action.target_path.resolve()
        source_size_bytes = _safe_source_size(source_path)

        if source_path in seen_sources:
            error = f"Source file was scheduled more than once in the same execution batch: {source_path}"
            LOGGER.error(error)
            return ExecutionResult(
                action=action,
                final_destination=target_path,
                executed=False,
                success=False,
                operation=operation_mode.value,
                message="Failed.",
                error=error,
                error_code="DUPLICATE_SOURCE_ACTION",
                guardrail_blocked=True,
                source_size_bytes=source_size_bytes,
            )
        seen_sources.add(source_path)

        validation = validate_planned_action(action)
        if validation.warnings:
            action.warnings.extend(validation.warnings)
        if not validation.is_valid:
            LOGGER.error("%s (%s)", validation.error_message, validation.error_code)
            return ExecutionResult(
                action=action,
                final_destination=target_path,
                executed=False,
                success=False,
                operation=operation_mode.value,
                message="Blocked by guardrail.",
                error=validation.error_message,
                error_code=validation.error_code,
                guardrail_blocked=validation.guardrail_blocked,
                source_size_bytes=source_size_bytes,
            )

        if not source_path.exists():
            error = f"Source file does not exist: {source_path}"
            LOGGER.error(error)
            return ExecutionResult(
                action=action,
                final_destination=target_path,
                executed=False,
                success=False,
                operation=operation_mode.value,
                message="Failed.",
                error=error,
                error_code="SOURCE_MISSING",
                source_size_bytes=source_size_bytes,
            )

        if target_path.exists() and target_path != source_path:
            error = f"Target path already exists: {target_path}"
            LOGGER.error(error)
            return ExecutionResult(
                action=action,
                final_destination=target_path,
                executed=False,
                success=False,
                operation=operation_mode.value,
                message="Failed.",
                error=error,
                error_code="TARGET_EXISTS",
                guardrail_blocked=True,
                source_size_bytes=source_size_bytes,
            )

        if dry_run:
            LOGGER.info("[dry-run] %s %s -> %s", operation_mode.value, source_path, target_path)
            return ExecutionResult(
                action=action,
                final_destination=target_path,
                executed=False,
                success=True,
                operation=operation_mode.value,
                message="Dry-run only.",
                source_size_bytes=source_size_bytes,
            )

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if operation_mode == FileOperationMode.COPY:
                _copy_via_staging(source_path, target_path)
                LOGGER.info("Copied %s -> %s", source_path, target_path)
                message = "Copied."
            else:
                _move_via_staging(source_path, target_path)
                _prune_empty_source_directories(source_path, cleanup_root=action.cleanup_root)
                LOGGER.info("Moved %s -> %s", source_path, target_path)
                message = "Moved."
        except Exception as exc:
            LOGGER.exception("Failed to %s %s -> %s", operation_mode.value, source_path, target_path)
            return ExecutionResult(
                action=action,
                final_destination=target_path,
                executed=False,
                success=False,
                operation=operation_mode.value,
                message="Failed.",
                error=str(exc),
                error_code="FILESYSTEM_OPERATION_FAILED",
                source_size_bytes=source_size_bytes,
            )

        return ExecutionResult(
            action=action,
            final_destination=target_path,
            executed=True,
            success=True,
            operation=operation_mode.value,
            message=message,
            source_size_bytes=source_size_bytes,
        )


def infer_report_format(path: Path) -> ReportFormat:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return ReportFormat.JSON
    if suffix == ".csv":
        return ReportFormat.CSV
    raise ValueError(f"Cannot infer report format from path: {path}")


def write_csv_report(report: ExecutionReport, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "source_path",
                "target_path",
                "action_type",
                "confidence",
                "success",
                "executed",
                "operation",
                "message",
                "error",
                "error_code",
                "guardrail_blocked",
                "warnings",
            ],
        )
        writer.writeheader()
        for result in report.results:
            writer.writerow(
                {
                    "source_path": str(result.action.source_path),
                    "target_path": str(result.final_destination or result.action.target_path),
                    "action_type": result.action.action_type.value,
                    "confidence": f"{result.action.confidence:.2f}",
                    "success": str(result.success).lower(),
                    "executed": str(result.executed).lower(),
                    "operation": result.operation,
                    "message": result.message,
                    "error": result.error or "",
                    "error_code": result.error_code or "",
                    "guardrail_blocked": str(result.guardrail_blocked).lower(),
                    "warnings": " | ".join(result.action.warnings),
                }
            )


def _build_counts(results: Iterable[ExecutionResult]) -> ExecutionCounts:
    counts = ExecutionCounts()

    for result in results:
        if not result.success:
            counts.failed += 1
            continue

        action_type = result.action.action_type
        if action_type == ActionType.SKIP:
            counts.skipped += 1
        elif action_type == ActionType.REVIEW:
            counts.reviewed += 1
            counts.moved += 1
        elif action_type == ActionType.MOVE:
            counts.moved += 1
        elif action_type == ActionType.RENAME:
            counts.renamed += 1
        elif action_type == ActionType.MOVE_AND_RENAME:
            counts.moved += 1
            counts.renamed += 1

    return counts


def _build_metrics(results: Iterable[ExecutionResult]) -> ExecutionMetrics:
    metrics = ExecutionMetrics()

    for result in results:
        metrics.total_actions += 1
        metrics.warnings_total += len(result.action.warnings)
        metrics.bytes_considered += result.source_size_bytes
        if result.message == "Dry-run only.":
            metrics.dry_run_actions += 1
        if result.guardrail_blocked:
            metrics.guardrail_failures += 1
        if result.executed and result.success:
            metrics.bytes_written += result.source_size_bytes

    return metrics


def _build_errors(results: Iterable[ExecutionResult]) -> list[ExecutionIssue]:
    issues: list[ExecutionIssue] = []
    for result in results:
        if result.success:
            continue
        issues.append(
            ExecutionIssue(
                source_path=result.action.source_path,
                code=result.error_code or "UNKNOWN_ERROR",
                message=result.error or result.message,
            )
        )
    return issues


def _serialize_report(report: ExecutionReport) -> dict[str, object]:
    return {
        "dry_run": report.dry_run,
        "copy_mode": report.copy_mode,
        "counts": asdict(report.counts),
        "metrics": asdict(report.metrics),
        "errors": [
            {
                "source_path": str(issue.source_path),
                "code": issue.code,
                "message": issue.message,
            }
            for issue in report.errors
        ],
        "results": [
            {
                "source_path": str(result.action.source_path),
                "target_directory": str(result.action.target_directory),
                "target_filename": result.action.target_filename,
                "target_path": str(result.action.target_path),
                "action_type": result.action.action_type.value,
                "confidence": result.action.confidence,
                "reason": result.action.reason,
                "warnings": list(result.action.warnings),
                "final_destination": str(result.final_destination) if result.final_destination else None,
                "executed": result.executed,
                "success": result.success,
                "operation": result.operation,
                "message": result.message,
                "error": result.error,
                "error_code": result.error_code,
                "guardrail_blocked": result.guardrail_blocked,
                "source_size_bytes": result.source_size_bytes,
            }
            for result in report.results
        ],
    }


def _copy_via_staging(source_path: Path, target_path: Path) -> None:
    staging_path = _build_staging_path(target_path)
    try:
        shutil.copy2(str(source_path), str(staging_path))
        staging_path.replace(target_path)
    except Exception:
        _cleanup_staging_file(staging_path)
        raise


def _move_via_staging(source_path: Path, target_path: Path) -> None:
    staging_path = _build_staging_path(target_path)
    try:
        # Copy-then-swap keeps the source intact until the target is fully materialized.
        shutil.copy2(str(source_path), str(staging_path))
        staging_path.replace(target_path)
        source_path.unlink()
    except Exception:
        _cleanup_staging_file(staging_path)
        raise


def _build_staging_path(target_path: Path) -> Path:
    return target_path.with_name(f".{target_path.name}.sortdocs-{uuid.uuid4().hex}.tmp")


def _cleanup_staging_file(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        LOGGER.warning("Failed to remove staging file %s after an aborted operation.", path)


def _safe_source_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _prune_empty_source_directories(source_path: Path, *, cleanup_root: Optional[Path]) -> None:
    if cleanup_root is None:
        return

    stop_at = cleanup_root.expanduser().resolve()
    current = source_path.parent.resolve()

    while current != stop_at:
        try:
            current.rmdir()
        except OSError:
            break
        LOGGER.info("Removed empty directory %s", current)
        current = current.parent

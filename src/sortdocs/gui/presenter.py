from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sortdocs.models import ExecutionReport, PlannedAction
from sortdocs.pipeline import PipelinePlan
from sortdocs.planner import display_path
from sortdocs.scanner import SkippedDirectory
from sortdocs.utils import limit_text


@dataclass(frozen=True)
class PlanSummary:
    discovered_files: int
    planned_actions: int
    moves: int
    renames: int
    reviews: int
    skips: int
    cache_hits: int
    skipped_directories: int


@dataclass(frozen=True)
class PlanRow:
    action_label: str
    confidence_label: str
    source_label: str
    target_label: str
    reason_label: str
    notes_label: str


def summarize_plan(plan: PipelinePlan) -> PlanSummary:
    counts = Counter(action.action_type.value for action in plan.actions)
    return PlanSummary(
        discovered_files=len(plan.discovered_files),
        planned_actions=len(plan.actions),
        moves=counts.get("move", 0) + counts.get("move_and_rename", 0),
        renames=counts.get("rename", 0) + counts.get("move_and_rename", 0),
        reviews=counts.get("review", 0),
        skips=counts.get("skip", 0),
        cache_hits=plan.cache_hits,
        skipped_directories=len(plan.skipped_directories),
    )


def build_plan_rows(plan: PipelinePlan, *, base_dir: Optional[Path] = None) -> list[PlanRow]:
    return [build_plan_row(action, base_dir=base_dir) for action in plan.actions]


def build_plan_row(action: PlannedAction, *, base_dir: Optional[Path] = None) -> PlanRow:
    reference_dir = base_dir or action.source_path.parent
    notes = " | ".join(action.warnings) if action.warnings else "-"
    return PlanRow(
        action_label=action.action_type.value,
        confidence_label=f"{action.confidence:.2f}",
        source_label=display_path(action.source_path, reference_dir),
        target_label=display_path(action.target_path, reference_dir),
        reason_label=limit_text(action.reason, 120),
        notes_label=limit_text(notes, 160),
    )


def format_action_details(action: PlannedAction) -> str:
    warnings = "\n".join(f"- {warning}" for warning in action.warnings) if action.warnings else "- none"
    tags = ", ".join(action.tags) if action.tags else "-"
    return "\n".join(
        [
            f"Action: {action.action_type.value}",
            f"Confidence: {action.confidence:.2f}",
            f"Source: {action.source_path}",
            f"Target: {action.target_path}",
            f"Category: {action.category or '-'}",
            f"Subcategory: {action.subcategory or '-'}",
            f"Suggested path: {action.suggested_path or '-'}",
            f"Tags: {tags}",
            "",
            "Reason:",
            action.reason,
            "",
            "Warnings:",
            warnings,
        ]
    )


def format_skipped_directories(skipped_directories: list[SkippedDirectory]) -> str:
    if not skipped_directories:
        return "No protected or ignored directories were skipped."
    return "\n".join(
        f"- {item.relative_path}: {item.reason}"
        for item in skipped_directories
    )


def format_execution_summary(report: ExecutionReport) -> str:
    return "\n".join(
        [
            f"Moved: {report.counts.moved}",
            f"Renamed: {report.counts.renamed}",
            f"Reviewed: {report.counts.reviewed}",
            f"Skipped: {report.counts.skipped}",
            f"Failed: {report.counts.failed}",
            f"Warnings: {report.metrics.warnings_total}",
            f"Guardrail hits: {report.metrics.guardrail_failures}",
        ]
    )

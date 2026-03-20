from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sortdocs.gui.presenter import (
    build_plan_rows,
    format_action_details,
    format_execution_summary,
    format_skipped_directories,
    summarize_plan,
)
from sortdocs.models import (
    ActionType,
    ExecutionCounts,
    ExecutionMetrics,
    ExecutionReport,
    PlannedAction,
)
from sortdocs.pipeline import PipelinePlan
from sortdocs.scanner import DiscoveredFile, SkippedDirectory


def make_discovered_file(path: Path, *, relative_path: str) -> DiscoveredFile:
    return DiscoveredFile(
        absolute_path=path,
        relative_path=Path(relative_path),
        extension=path.suffix.lower(),
        mime_type="text/plain",
        size_bytes=10,
        created_at=None,
        modified_at=datetime.now(timezone.utc),
        sha256=None,
        is_supported=True,
        warnings=[],
    )


def make_action(source: Path, target: Path, *, action_type: ActionType = ActionType.MOVE) -> PlannedAction:
    return PlannedAction(
        source_path=source,
        target_directory=target.parent,
        target_filename=target.name,
        target_path=target,
        action_type=action_type,
        confidence=0.91,
        reason="Looks correct.",
        category="finance",
        subcategory="invoices",
        tags=["invoice"],
        suggested_path="finance/invoices",
        warnings=["confidence reviewed"],
    )


def test_gui_presenter_builds_summary_and_rows(tmp_path: Path) -> None:
    source = tmp_path / "invoice.txt"
    target = tmp_path / "finance" / "invoices" / "invoice.txt"
    plan = PipelinePlan(
        discovered_files=[make_discovered_file(source, relative_path="invoice.txt")],
        classifications=[],
        actions=[make_action(source, target)],
        skipped_directories=[
            SkippedDirectory(
                absolute_path=tmp_path / "node_modules",
                relative_path=Path("node_modules"),
                reason="Protected project/build directory 'node_modules' was skipped.",
            )
        ],
        cache_hits=2,
    )

    summary = summarize_plan(plan)
    rows = build_plan_rows(plan, base_dir=tmp_path)

    assert summary.discovered_files == 1
    assert summary.planned_actions == 1
    assert summary.moves == 1
    assert summary.cache_hits == 2
    assert summary.skipped_directories == 1
    assert rows[0].action_label == "move"
    assert "invoice.txt" in rows[0].source_label
    assert "finance/invoices" in rows[0].target_label


def test_gui_presenter_formats_action_and_report_details(tmp_path: Path) -> None:
    source = tmp_path / "invoice.txt"
    target = tmp_path / "finance" / "invoices" / "invoice.txt"
    action = make_action(source, target, action_type=ActionType.MOVE_AND_RENAME)
    report = ExecutionReport(
        dry_run=False,
        copy_mode=False,
        counts=ExecutionCounts(moved=1, renamed=1, reviewed=0, skipped=0, failed=0),
        metrics=ExecutionMetrics(warnings_total=1, guardrail_failures=0),
    )

    action_details = format_action_details(action)
    report_details = format_execution_summary(report)
    skipped_details = format_skipped_directories([])

    assert "Action: move_and_rename" in action_details
    assert "Category: finance" in action_details
    assert "Moved: 1" in report_details
    assert "Renamed: 1" in report_details
    assert skipped_details == "No protected or ignored directories were skipped."

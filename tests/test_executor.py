from __future__ import annotations

import json
from pathlib import Path

from sortdocs.executor import FileOperationMode, PlanExecutor
from sortdocs.models import ActionType, PlannedAction


def make_action(
    *,
    source: Path,
    destination: Path,
    action_type: ActionType = ActionType.MOVE,
    approved_roots: tuple[Path, ...] = (),
    cleanup_root: Path | None = None,
) -> PlannedAction:
    return PlannedAction(
        source_path=source,
        target_directory=destination.parent,
        target_filename=destination.name,
        target_path=destination,
        action_type=action_type,
        confidence=0.95,
        reason="Safe action.",
        category=None,
        subcategory=None,
        tags=[],
        suggested_path=None,
        warnings=[],
        approved_roots=approved_roots,
        cleanup_root=cleanup_root,
    )


def test_executor_moves_file_on_apply_and_creates_directories(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    destination = tmp_path / "sorted" / "renamed.txt"

    report = PlanExecutor().execute([make_action(source=source, destination=destination)], dry_run=False)

    assert report.counts.moved == 1
    assert report.results[0].executed is True
    assert report.results[0].success is True
    assert destination.exists()
    assert not source.exists()


def test_executor_dry_run_does_not_mutate_filesystem(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    destination = tmp_path / "sorted" / "renamed.txt"

    report = PlanExecutor().execute([make_action(source=source, destination=destination)], dry_run=True)

    assert report.results[0].executed is False
    assert report.results[0].success is True
    assert source.exists()
    assert not destination.exists()
    assert not destination.parent.exists()


def test_executor_can_copy_without_removing_source(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    destination = tmp_path / "copy-target" / "source.txt"

    report = PlanExecutor().execute(
        [make_action(source=source, destination=destination)],
        dry_run=False,
        operation_mode=FileOperationMode.COPY,
    )

    assert report.copy_mode is True
    assert report.results[0].operation == "copy"
    assert source.exists()
    assert destination.exists()


def test_executor_never_overwrites_existing_target(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("new-content", encoding="utf-8")
    destination = tmp_path / "existing.txt"
    destination.write_text("old-content", encoding="utf-8")

    report = PlanExecutor().execute([make_action(source=source, destination=destination)], dry_run=False)

    assert report.counts.failed == 1
    assert report.results[0].success is False
    assert destination.read_text(encoding="utf-8") == "old-content"
    assert source.exists()


def test_executor_counts_review_skip_and_rename(tmp_path: Path) -> None:
    source_review = tmp_path / "review-me.txt"
    source_review.write_text("review", encoding="utf-8")
    source_rename = tmp_path / "rename-me.txt"
    source_rename.write_text("rename", encoding="utf-8")
    source_skip = tmp_path / "already.txt"
    source_skip.write_text("skip", encoding="utf-8")

    review_destination = tmp_path / "Review" / "review-me.txt"
    rename_destination = tmp_path / "renamed.txt"

    report = PlanExecutor().execute(
        [
            make_action(source=source_review, destination=review_destination, action_type=ActionType.REVIEW),
            make_action(source=source_rename, destination=rename_destination, action_type=ActionType.RENAME),
            make_action(source=source_skip, destination=source_skip, action_type=ActionType.SKIP),
        ],
        dry_run=False,
    )

    assert report.counts.reviewed == 1
    assert report.counts.renamed == 1
    assert report.counts.skipped == 1
    assert review_destination.exists()
    assert rename_destination.exists()
    assert source_skip.exists()


def test_executor_writes_json_report(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    destination = tmp_path / "sorted" / "renamed.txt"

    executor = PlanExecutor()
    report = executor.execute([make_action(source=source, destination=destination)], dry_run=True)
    report_path = tmp_path / "reports" / "execution.json"
    written_path = executor.write_report(report, report_path)

    payload = json.loads(written_path.read_text(encoding="utf-8"))
    assert payload["dry_run"] is True
    assert payload["counts"]["moved"] == 1
    assert payload["results"][0]["target_path"].endswith("sorted/renamed.txt")


def test_executor_writes_csv_report(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    destination = tmp_path / "sorted" / "renamed.txt"

    executor = PlanExecutor()
    report = executor.execute([make_action(source=source, destination=destination)], dry_run=True)
    report_path = tmp_path / "reports" / "execution.csv"
    written_path = executor.write_report(report, report_path)

    csv_content = written_path.read_text(encoding="utf-8")
    assert "source_path,target_path,action_type" in csv_content
    assert "move" in csv_content


def test_executor_blocks_path_traversal_outside_approved_roots(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    library_dir = tmp_path / "Library"
    review_dir = tmp_path / "Review"
    dangerous_target = tmp_path.parent / "escape.txt"

    report = PlanExecutor().execute(
        [
            make_action(
                source=source,
                destination=dangerous_target,
                approved_roots=(library_dir, review_dir),
            )
        ],
        dry_run=False,
    )

    # This guardrail prevents crafted actions from escaping the managed roots.
    assert report.counts.failed == 1
    assert report.metrics.guardrail_failures == 1
    assert report.errors[0].code == "TARGET_OUTSIDE_ALLOWED_ROOTS"
    assert source.exists()
    assert not dangerous_target.exists()


def test_executor_blocks_explicit_parent_directory_traversal(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    library_dir = tmp_path / "Library"
    review_dir = tmp_path / "Review"
    traversal_target = tmp_path / "Library" / ".." / "escape.txt"

    report = PlanExecutor().execute(
        [
            make_action(
                source=source,
                destination=traversal_target,
                approved_roots=(library_dir, review_dir),
            )
        ],
        dry_run=False,
    )

    assert report.counts.failed == 1
    assert report.results[0].error_code == "PATH_TRAVERSAL_BLOCKED"
    assert source.exists()


def test_executor_blocks_invalid_filenames_before_any_rename(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_text("content", encoding="utf-8")
    action = PlannedAction(
        source_path=source,
        target_directory=tmp_path / "Library",
        target_filename="bad:name.txt",
        target_path=(tmp_path / "Library" / "bad:name.txt"),
        action_type=ActionType.MOVE_AND_RENAME,
        confidence=0.9,
        reason="Unsafe.",
        category=None,
        subcategory=None,
        tags=[],
        suggested_path=None,
        warnings=[],
        approved_roots=(tmp_path / "Library", tmp_path / "Review"),
    )

    report = PlanExecutor().execute([action], dry_run=False)

    # These guardrails stop unsafe renames before any filesystem mutation.
    assert report.counts.failed == 1
    assert report.results[0].guardrail_blocked is True
    assert report.results[0].error_code == "INVALID_FILENAME"
    assert source.exists()


def test_executor_blocks_extension_mismatches(tmp_path: Path) -> None:
    source = tmp_path / "report.pdf"
    source.write_text("content", encoding="utf-8")

    report = PlanExecutor().execute(
        [
            make_action(
                source=source,
                destination=tmp_path / "Library" / "report.txt",
                approved_roots=(tmp_path / "Library", tmp_path / "Review"),
            )
        ],
        dry_run=False,
    )

    assert report.counts.failed == 1
    assert report.results[0].error_code == "EXTENSION_MISMATCH"
    assert source.exists()


def test_executor_continues_after_a_guardrail_failure_and_reports_both_outcomes(tmp_path: Path) -> None:
    blocked_source = tmp_path / "blocked.txt"
    blocked_source.write_text("blocked", encoding="utf-8")
    safe_source = tmp_path / "safe.txt"
    safe_source.write_text("safe", encoding="utf-8")
    library_dir = tmp_path / "Library"
    review_dir = tmp_path / "Review"

    unsafe_action = make_action(
        source=blocked_source,
        destination=tmp_path.parent / "escape.txt",
        approved_roots=(library_dir, review_dir),
    )
    safe_action = make_action(
        source=safe_source,
        destination=library_dir / "safe.txt",
        approved_roots=(library_dir, review_dir),
    )

    report = PlanExecutor().execute([unsafe_action, safe_action], dry_run=False)

    # A failed action must not crash the whole batch: later safe actions still run.
    assert report.counts.failed == 1
    assert report.counts.moved == 1
    assert len(report.errors) == 1
    assert report.errors[0].code == "TARGET_OUTSIDE_ALLOWED_ROOTS"
    assert (library_dir / "safe.txt").exists()
    assert safe_source.exists() is False
    assert blocked_source.exists() is True


def test_executor_prunes_empty_source_directories_after_move(tmp_path: Path) -> None:
    source_root = tmp_path / "Inbox"
    source_dir = source_root / "2026" / "march"
    source_dir.mkdir(parents=True)
    source = source_dir / "statement.txt"
    source.write_text("hello", encoding="utf-8")
    destination = tmp_path / "Library" / "finance" / "statements" / "statement.txt"

    report = PlanExecutor().execute(
        [
            make_action(
                source=source,
                destination=destination,
                cleanup_root=source_root,
            )
        ],
        dry_run=False,
    )

    assert report.results[0].success is True
    assert destination.exists()
    assert source_root.exists()
    assert not source_dir.exists()
    assert not (source_root / "2026").exists()


def test_executor_blocks_duplicate_source_actions_in_same_batch(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    library_dir = tmp_path / "Library"
    review_dir = tmp_path / "Review"

    report = PlanExecutor().execute(
        [
            make_action(
                source=source,
                destination=library_dir / "a.txt",
                approved_roots=(library_dir, review_dir),
            ),
            make_action(
                source=source,
                destination=library_dir / "b.txt",
                approved_roots=(library_dir, review_dir),
            ),
        ],
        dry_run=True,
    )

    # This guardrail avoids reprocessing loops or conflicting plans for the same file.
    assert report.counts.failed == 1
    assert report.metrics.guardrail_failures == 1
    assert report.results[1].error_code == "DUPLICATE_SOURCE_ACTION"

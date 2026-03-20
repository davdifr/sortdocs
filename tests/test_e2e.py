from __future__ import annotations

from pathlib import Path
from typing import Any

from sortdocs.ai_client import APIRequestError
from sortdocs.config import SortdocsConfig
from sortdocs.models import ActionType, ClassificationResult
from sortdocs.pipeline import PipelineResult, SortdocsPipeline


def make_config(**overrides: object) -> SortdocsConfig:
    payload: dict[str, object] = {
        "extraction": {"max_excerpt_chars": 500},
        "planner": {"confidence_threshold": 0.65},
    }
    payload.update(overrides)
    return SortdocsConfig.model_validate(payload)


def build_pipeline_run(
    *,
    tmp_path: Path,
    files: dict[str, str],
    classifications: dict[str, ClassificationResult | dict[str, Any]],
    dry_run: bool,
    source_subdir: str = "Inbox",
) -> tuple[PipelineResult, Path, Path, Path, list[dict[str, Any]]]:
    root_dir = tmp_path
    source_dir = root_dir / source_subdir
    source_dir.mkdir(parents=True, exist_ok=True)
    library_dir = root_dir / "Library"
    review_dir = root_dir / "Review"

    for relative_name, content in files.items():
        path = source_dir / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    client_calls: list[dict[str, Any]] = []

    class FakeOpenAIClassificationClient:
        def __init__(self, config: SortdocsConfig) -> None:
            self._config = config

        def classify_file(
            self,
            extracted_content,
            original_filename: str,
            relative_path: str | Path,
            directory_context=None,
            absolute_path=None,
        ) -> ClassificationResult:
            client_calls.append(
                {
                    "original_filename": original_filename,
                    "relative_path": str(relative_path),
                    "excerpt": extracted_content.plain_text_excerpt,
                    "directory_context": directory_context,
                }
            )
            payload = classifications[original_filename]
            if isinstance(payload, ClassificationResult):
                return payload
            return ClassificationResult.model_validate(payload)

    result = SortdocsPipeline(
        make_config(),
        library_dir=library_dir,
        review_dir=review_dir,
        ai_client_factory=FakeOpenAIClassificationClient,
    ).run_directory(
        source_dir,
        dry_run=dry_run,
        recursive=True,
    )
    return result, source_dir, library_dir, review_dir, client_calls


def test_e2e_dry_run_leaves_files_in_place_and_uses_mocked_ai_client(tmp_path: Path) -> None:
    run, source_dir, library_dir, review_dir, fake_calls = build_pipeline_run(
        tmp_path=tmp_path,
        files={"statement.txt": "Bank statement for March 2026\nEnding balance 1000"},
        classifications={
            "statement.txt": {
                "category": "Finance",
                "subcategory": "Statements",
                "suggested_path": "finance/statements",
                "suggested_filename": "statement",
                "confidence": 0.94,
                "reason": "Looks like a bank statement.",
                "tags": ["finance", "statement"],
                "needs_review": False,
            }
        },
        dry_run=True,
    )

    target_path = library_dir / "finance" / "statements" / "statement.txt"

    assert [item.relative_path for item in run.discovered_files] == [Path("statement.txt")]
    assert run.actions[0].action_type == ActionType.MOVE
    assert run.execution_report.results[0].success is True
    assert run.execution_report.results[0].executed is False
    assert (source_dir / "statement.txt").exists()
    assert not target_path.exists()
    assert not library_dir.exists()
    assert not review_dir.exists()
    assert fake_calls[0]["original_filename"] == "statement.txt"
    assert fake_calls[0]["relative_path"] == "statement.txt"
    assert "Bank statement" in fake_calls[0]["excerpt"]
    assert "top_level_directories" in fake_calls[0]["directory_context"]


def test_e2e_apply_moves_files_and_creates_target_directories(tmp_path: Path) -> None:
    run, source_dir, library_dir, _review_dir, _ = build_pipeline_run(
        tmp_path=tmp_path,
        files={"invoice.txt": "Invoice 2026-03 for consulting services"},
        classifications={
            "invoice.txt": {
                "category": "Finance",
                "subcategory": "Invoices",
                "suggested_path": "finance/invoices",
                "suggested_filename": "invoice",
                "confidence": 0.97,
                "reason": "Clearly an invoice.",
                "tags": ["invoice"],
                "needs_review": False,
            }
        },
        dry_run=False,
    )

    target_directory = library_dir / "finance" / "invoices"
    target_path = target_directory / "invoice.txt"

    assert run.actions[0].action_type == ActionType.MOVE
    assert run.execution_report.counts.moved == 1
    assert target_directory.is_dir()
    assert target_path.exists()
    assert target_path.read_text(encoding="utf-8") == "Invoice 2026-03 for consulting services"
    assert not (source_dir / "invoice.txt").exists()


def test_e2e_apply_routes_low_confidence_files_to_review(tmp_path: Path) -> None:
    run, source_dir, _library_dir, review_dir, _ = build_pipeline_run(
        tmp_path=tmp_path,
        files={"notes.txt": "Some unclear notes without enough context"},
        classifications={
            "notes.txt": {
                "category": "Admin",
                "subcategory": "Notes",
                "suggested_path": "review/notes",
                "suggested_filename": "misc_notes",
                "confidence": 0.31,
                "reason": "Not enough signal to classify safely.",
                "tags": ["notes"],
                "needs_review": True,
            }
        },
        dry_run=False,
    )

    review_path = review_dir / "misc_notes.txt"

    assert run.actions[0].action_type == ActionType.REVIEW
    assert run.execution_report.counts.reviewed == 1
    assert review_path.exists()
    assert review_path.read_text(encoding="utf-8") == "Some unclear notes without enough context"
    assert not (source_dir / "notes.txt").exists()


def test_e2e_apply_resolves_filename_collisions_with_incremental_suffixes(tmp_path: Path) -> None:
    run, source_dir, library_dir, _review_dir, _ = build_pipeline_run(
        tmp_path=tmp_path,
        files={
            "alpha.txt": "Alpha contract draft",
            "beta.txt": "Beta contract draft",
        },
        classifications={
            "alpha.txt": {
                "category": "Legal",
                "subcategory": "Contracts",
                "suggested_path": "legal/contracts",
                "suggested_filename": "contract",
                "confidence": 0.93,
                "reason": "Both files look like contracts.",
                "tags": ["contract"],
                "needs_review": False,
            },
            "beta.txt": {
                "category": "Legal",
                "subcategory": "Contracts",
                "suggested_path": "legal/contracts",
                "suggested_filename": "contract",
                "confidence": 0.92,
                "reason": "Both files look like contracts.",
                "tags": ["contract"],
                "needs_review": False,
            },
        },
        dry_run=False,
    )

    target_directory = library_dir / "legal" / "contracts"
    target_names = {action.target_filename for action in run.actions}
    final_contents = {
        (target_directory / "contract.txt").read_text(encoding="utf-8"),
        (target_directory / "contract__1.txt").read_text(encoding="utf-8"),
    }

    assert target_names == {"contract.txt", "contract__1.txt"}
    assert final_contents == {"Alpha contract draft", "Beta contract draft"}
    assert not any(source_dir.iterdir())


def test_e2e_apply_skips_file_that_is_already_in_the_right_place(tmp_path: Path) -> None:
    library_dir = tmp_path / "Library"
    review_dir = tmp_path / "Review"
    source_dir = library_dir
    existing_path = library_dir / "finance" / "invoices" / "march_invoice.txt"
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text("Already sorted", encoding="utf-8")

    class FakeOpenAIClassificationClient:
        def __init__(self, config: SortdocsConfig) -> None:
            self._config = config

        def classify_file(
            self,
            extracted_content,
            original_filename: str,
            relative_path: str | Path,
            directory_context=None,
            absolute_path=None,
        ):
            return ClassificationResult.model_validate(
                {
                    "category": "Finance",
                    "subcategory": "Invoices",
                    "suggested_path": "finance/invoices",
                    "suggested_filename": "march_invoice",
                    "confidence": 0.99,
                    "reason": "Already correct.",
                    "tags": ["invoice"],
                    "needs_review": False,
                }
            )

    run = SortdocsPipeline(
        make_config(),
        library_dir=library_dir,
        review_dir=review_dir,
        ai_client_factory=FakeOpenAIClassificationClient,
    ).run_directory(source_dir, dry_run=False, recursive=True)

    assert run.actions[0].action_type == ActionType.SKIP
    assert run.execution_report.counts.skipped == 1
    assert run.execution_report.results[0].executed is False
    assert existing_path.exists()
    assert existing_path.read_text(encoding="utf-8") == "Already sorted"


def test_e2e_routes_ai_failures_to_review_without_aborting_batch(tmp_path: Path) -> None:
    source_dir = tmp_path / "Inbox"
    source_dir.mkdir()
    (source_dir / "good.txt").write_text("Invoice for March", encoding="utf-8")
    (source_dir / "bad.txt").write_text("Unreadable document", encoding="utf-8")

    class FakeOpenAIClassificationClient:
        def __init__(self, config: SortdocsConfig) -> None:
            self._config = config

        def classify_file(
            self,
            extracted_content,
            original_filename: str,
            relative_path: str | Path,
            directory_context=None,
            absolute_path=None,
        ):
            if original_filename == "bad.txt":
                raise APIRequestError("temporary failure")
            return ClassificationResult.model_validate(
                {
                    "category": "Finance",
                    "subcategory": "Invoices",
                    "suggested_path": "finance/invoices",
                    "suggested_filename": "invoice",
                    "confidence": 0.91,
                    "reason": "Looks like an invoice.",
                    "tags": ["invoice"],
                    "needs_review": False,
                }
            )

    run = SortdocsPipeline(
        make_config(),
        library_dir=tmp_path / "Library",
        review_dir=tmp_path / "Review",
        ai_client_factory=FakeOpenAIClassificationClient,
    ).run_directory(source_dir, dry_run=False, recursive=True)

    assert run.execution_report.counts.moved == 2
    assert (tmp_path / "Library" / "finance" / "invoices" / "invoice.txt").exists()
    assert (tmp_path / "Review" / "bad.txt").exists()


def test_e2e_persists_local_memory_and_reuses_it_in_next_run(tmp_path: Path) -> None:
    documents_dir = tmp_path / "Documents"
    documents_dir.mkdir()
    first_file = documents_dir / "flight_ticket_alpha.txt"
    first_file.write_text("Flight ticket to Paris", encoding="utf-8")

    first_calls: list[dict[str, Any]] = []
    second_calls: list[dict[str, Any]] = []

    class FirstRunClient:
        def __init__(self, config: SortdocsConfig) -> None:
            self._config = config

        def classify_file(
            self,
            extracted_content,
            original_filename: str,
            relative_path: str | Path,
            directory_context=None,
            absolute_path=None,
        ) -> ClassificationResult:
            first_calls.append(directory_context or {})
            return ClassificationResult.model_validate(
                {
                    "category": "Travel",
                    "subcategory": "Flight Tickets",
                    "suggested_path": "travel_documents/flight_tickets",
                    "suggested_filename": "flight_ticket_alpha",
                    "confidence": 0.95,
                    "reason": "Looks like a flight ticket.",
                    "tags": ["flight", "ticket"],
                    "needs_review": False,
                }
            )

    SortdocsPipeline(
        make_config(),
        library_dir=documents_dir,
        review_dir=documents_dir,
        ai_client_factory=FirstRunClient,
    ).run_directory(documents_dir, dry_run=False, recursive=True)

    memory_file = documents_dir / ".sortdocs-memory.json"
    assert memory_file.exists()

    second_file = documents_dir / "flight_ticket_beta.txt"
    second_file.write_text("Another flight ticket", encoding="utf-8")

    class SecondRunClient:
        def __init__(self, config: SortdocsConfig) -> None:
            self._config = config

        def classify_file(
            self,
            extracted_content,
            original_filename: str,
            relative_path: str | Path,
            directory_context=None,
            absolute_path=None,
        ) -> ClassificationResult:
            second_calls.append(directory_context or {})
            return ClassificationResult.model_validate(
                {
                    "category": "Travel",
                    "subcategory": "Flight Tickets",
                    "suggested_path": "travel_documents/flight_tickets",
                    "suggested_filename": "flight_ticket_beta",
                    "confidence": 0.95,
                    "reason": "Looks like a flight ticket.",
                    "tags": ["flight", "ticket"],
                    "needs_review": False,
                }
            )

    SortdocsPipeline(
        make_config(),
        library_dir=documents_dir,
        review_dir=documents_dir,
        ai_client_factory=SecondRunClient,
    ).plan_directory(documents_dir, recursive=True)

    local_memory = second_calls[0]["local_memory_hints"]
    assert local_memory["memory_file"] == ".sortdocs-memory.json"
    assert local_memory["filename_token_hints"][0]["target_path"] == "travel_documents/flight_tickets"

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sortdocs.config import SortdocsConfig
from sortdocs.models import ActionType, ClassificationResult
from sortdocs.planner import Planner, render_plan_table, sanitize_filename
from sortdocs.scanner import DiscoveredFile


def make_discovered_file(
    path: Path,
    *,
    relative_path: Path | None = None,
    created_at: datetime | None = None,
    modified_at: datetime | None = None,
) -> DiscoveredFile:
    return DiscoveredFile(
        absolute_path=path.resolve(),
        relative_path=relative_path or Path(path.name),
        extension=path.suffix.lower(),
        mime_type=None,
        size_bytes=path.stat().st_size,
        created_at=created_at,
        modified_at=modified_at or datetime.now(timezone.utc),
        sha256=None,
        is_supported=True,
    )


def make_classification(**overrides: object) -> ClassificationResult:
    payload = {
        "category": "Finance",
        "subcategory": "Invoices",
        "suggested_path": None,
        "suggested_filename": "March Invoice",
        "confidence": 0.95,
        "reason": "Looks like an invoice.",
        "tags": ["invoice"],
        "needs_review": False,
    }
    payload.update(overrides)
    return ClassificationResult.model_validate(payload)


def test_planner_sanitizes_names_and_preserves_extension(tmp_path: Path) -> None:
    source = tmp_path / "Inbox" / "raw.pdf"
    source.parent.mkdir()
    source.write_text("content", encoding="utf-8")
    planner = Planner(
        SortdocsConfig.model_validate({"planner": {"max_filename_length": 24}}),
        library_dir=tmp_path / "Library",
        review_dir=tmp_path / "Review",
    )

    action = planner.plan_file(
        make_discovered_file(source, relative_path=Path("Inbox/raw.pdf")),
        make_classification(
            category="Finance & Bills",
            subcategory="2026:March",
            suggested_filename="Invoice: March FINAL.exe",
        ),
    )

    assert action.action_type == ActionType.MOVE_AND_RENAME
    assert action.target_directory == tmp_path / "Library" / "finance_bills" / "2026_march"
    assert action.target_filename == "invoice_march_final.pdf"
    assert action.target_path.suffix == ".pdf"
    assert action.warnings


def test_planner_routes_low_confidence_to_review(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("content", encoding="utf-8")
    planner = Planner(
        SortdocsConfig.model_validate({"planner": {"review_confidence_threshold": 0.7}}),
        library_dir=tmp_path / "Library",
        review_dir=tmp_path / "Review",
    )

    action = planner.plan_file(
        make_discovered_file(source),
        make_classification(confidence=0.42, reason="Unclear.", suggested_filename="Needs Review"),
    )

    assert action.action_type == ActionType.REVIEW
    assert action.target_directory == (tmp_path / "Review")
    assert action.target_path == tmp_path / "Review" / "needs_review.txt"
    assert any("file requires manual review" in warning for warning in action.warnings)


def test_planner_keeps_low_confidence_file_in_place_when_review_dir_is_source_root(tmp_path: Path) -> None:
    source = tmp_path / "Inbox" / "notes.txt"
    source.parent.mkdir(parents=True)
    source.write_text("content", encoding="utf-8")
    planner = Planner(
        SortdocsConfig.model_validate({"planner": {"review_confidence_threshold": 0.7}}),
        library_dir=tmp_path / "Inbox",
        review_dir=tmp_path / "Inbox",
    )

    action = planner.plan_file(
        make_discovered_file(source, relative_path=Path("notes.txt")),
        make_classification(confidence=0.42, reason="Unclear.", suggested_filename="Needs Review"),
    )

    assert action.action_type == ActionType.SKIP
    assert action.target_path == source.resolve()
    assert any("kept in its current folder" in warning for warning in action.warnings)


def test_planner_skips_when_file_is_already_in_place(tmp_path: Path) -> None:
    source = tmp_path / "Library" / "finance" / "invoices" / "march_invoice.pdf"
    source.parent.mkdir(parents=True)
    source.write_text("content", encoding="utf-8")
    planner = Planner(
        SortdocsConfig(),
        library_dir=tmp_path / "Library",
        review_dir=tmp_path / "Review",
    )

    action = planner.plan_file(
        make_discovered_file(source, relative_path=Path("Library/finance/invoices/march_invoice.pdf")),
        make_classification(
            category="Finance",
            subcategory="Invoices",
            suggested_filename="march_invoice",
        ),
    )

    assert action.action_type == ActionType.SKIP
    assert action.target_path == source.resolve()


def test_planner_adds_incremental_suffix_on_collision(tmp_path: Path) -> None:
    existing = tmp_path / "Library" / "finance" / "invoices" / "march_invoice.pdf"
    existing.parent.mkdir(parents=True)
    existing.write_text("existing", encoding="utf-8")

    source = tmp_path / "Inbox" / "incoming.pdf"
    source.parent.mkdir()
    source.write_text("incoming", encoding="utf-8")

    planner = Planner(
        SortdocsConfig(),
        library_dir=tmp_path / "Library",
        review_dir=tmp_path / "Review",
    )

    action = planner.plan_file(
        make_discovered_file(source, relative_path=Path("Inbox/incoming.pdf")),
        make_classification(
            category="Finance",
            subcategory="Invoices",
            suggested_filename="march_invoice",
        ),
    )

    assert action.target_filename == "march_invoice__1.pdf"
    assert action.action_type == ActionType.MOVE_AND_RENAME
    assert any("Name collision detected" in warning for warning in action.warnings)


def test_planner_reuses_equivalent_existing_directory_name(tmp_path: Path) -> None:
    existing_dir = tmp_path / "Documents" / "finance" / "invoices"
    existing_dir.mkdir(parents=True)
    source = tmp_path / "Documents" / "Inbox" / "invoice.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("content", encoding="utf-8")

    planner = Planner(
        SortdocsConfig(),
        library_dir=tmp_path / "Documents",
        review_dir=tmp_path / "Documents",
    )

    action = planner.plan_file(
        make_discovered_file(source, relative_path=Path("Inbox/invoice.pdf")),
        make_classification(category="Finance", subcategory="Invoice", suggested_filename="invoice"),
    )

    assert action.target_directory == existing_dir
    assert any("canonical folder name 'invoices'" in warning for warning in action.warnings)


def test_planner_normalizes_common_subcategory_to_canonical_plural(tmp_path: Path) -> None:
    source = tmp_path / "Documents" / "invoice.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("content", encoding="utf-8")

    planner = Planner(
        SortdocsConfig(),
        library_dir=tmp_path / "Documents",
        review_dir=tmp_path / "Documents",
    )

    action = planner.plan_file(
        make_discovered_file(source, relative_path=Path("invoice.pdf")),
        make_classification(category="Finance", subcategory="Invoice", suggested_filename="invoice"),
    )

    assert action.target_directory == tmp_path / "Documents" / "finance" / "invoices"
    assert any("canonical folder name 'invoices'" in warning for warning in action.warnings)


def test_planner_prefers_ai_suggested_path_when_available(tmp_path: Path) -> None:
    source = tmp_path / "Documents" / "ticket.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("content", encoding="utf-8")

    planner = Planner(
        SortdocsConfig(),
        library_dir=tmp_path / "Documents",
        review_dir=tmp_path / "Documents",
    )

    action = planner.plan_file(
        make_discovered_file(source, relative_path=Path("ticket.pdf")),
        make_classification(
            category="Travel",
            subcategory="Tickets",
            suggested_path="travel_documents/flight_tickets",
            suggested_filename="flight_ticket",
        ),
    )

    assert action.target_directory == tmp_path / "Documents" / "travel_documents" / "flight_tickets"


def test_planner_harmonizes_similar_ai_suggested_paths_within_same_run(tmp_path: Path) -> None:
    source_dir = tmp_path / "Documents" / "Inbox"
    source_dir.mkdir(parents=True)
    sources = [
        source_dir / "course_a.pdf",
        source_dir / "course_b.pdf",
        source_dir / "course_c.pdf",
        source_dir / "course_d.pdf",
    ]
    for source in sources:
        source.write_text("content", encoding="utf-8")

    planner = Planner(
        SortdocsConfig(),
        library_dir=tmp_path / "Documents",
        review_dir=tmp_path / "Documents",
    )

    items = [
        (
            make_discovered_file(sources[0], relative_path=Path("Inbox/course_a.pdf")),
            make_classification(
                category="Education",
                subcategory="Courses and Certifications",
                suggested_path="education/courses/programming",
                suggested_filename="responsive_web_design_certificate",
                tags=["certificate", "course", "web"],
            ),
        ),
        (
            make_discovered_file(sources[1], relative_path=Path("Inbox/course_b.pdf")),
            make_classification(
                category="Education",
                subcategory="Online Course Certificates",
                suggested_path="certificates/education/online_courses",
                suggested_filename="tailwind_css_certificate",
                tags=["certificate", "course", "tailwind"],
            ),
        ),
        (
            make_discovered_file(sources[2], relative_path=Path("Inbox/course_c.pdf")),
            make_classification(
                category="Education",
                subcategory="Certificates",
                suggested_path="education/certificates",
                suggested_filename="javascript_certificate",
                tags=["certificate", "course", "javascript"],
            ),
        ),
        (
            make_discovered_file(sources[3], relative_path=Path("Inbox/course_d.pdf")),
            make_classification(
                category="Education",
                subcategory="Course Certificates",
                suggested_path="education/course_certificates",
                suggested_filename="angular_certificate",
                tags=["certificate", "course", "angular"],
            ),
        ),
    ]

    actions = planner.plan_files(items)

    target_directories = {action.target_directory for action in actions}
    expected_directories = {
        tmp_path / "Documents" / "education" / "courses" / "programming",
        tmp_path / "Documents" / "certificates" / "education" / "online_courses",
        tmp_path / "Documents" / "education" / "certificates",
        tmp_path / "Documents" / "education" / "course_certificates",
    }

    assert len(target_directories) == 1
    assert next(iter(target_directories)) in expected_directories
    assert any("Aligned AI-suggested folder path" in warning for action in actions for warning in action.warnings)


def test_planner_prefers_existing_ai_directory_when_harmonizing_similar_paths(tmp_path: Path) -> None:
    existing_dir = tmp_path / "Documents" / "education" / "certificates"
    existing_dir.mkdir(parents=True)
    source_dir = tmp_path / "Documents" / "Inbox"
    source_dir.mkdir(parents=True)
    first = source_dir / "course_a.pdf"
    second = source_dir / "course_b.pdf"
    first.write_text("content", encoding="utf-8")
    second.write_text("content", encoding="utf-8")

    planner = Planner(
        SortdocsConfig(),
        library_dir=tmp_path / "Documents",
        review_dir=tmp_path / "Documents",
    )

    actions = planner.plan_files(
        [
            (
                make_discovered_file(first, relative_path=Path("Inbox/course_a.pdf")),
                make_classification(
                    category="Education",
                    subcategory="Course Certificates",
                    suggested_path="education/course_certificates",
                    suggested_filename="course_a_certificate",
                    tags=["certificate", "course"],
                ),
            ),
            (
                make_discovered_file(second, relative_path=Path("Inbox/course_b.pdf")),
                make_classification(
                    category="Education",
                    subcategory="Certificates",
                    suggested_path="education/certificates",
                    suggested_filename="course_b_certificate",
                    tags=["certificate", "course"],
                ),
            ),
        ]
    )

    assert {action.target_directory for action in actions} == {existing_dir}


def test_planner_reuses_existing_bills_paid_directory_for_bill_family(tmp_path: Path) -> None:
    existing_dir = tmp_path / "Documents" / "finance" / "bills_paid"
    existing_dir.mkdir(parents=True)
    source = tmp_path / "Documents" / "Inbox" / "bill.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("content", encoding="utf-8")

    planner = Planner(
        SortdocsConfig(),
        library_dir=tmp_path / "Documents",
        review_dir=tmp_path / "Documents",
    )

    action = planner.plan_file(
        make_discovered_file(source, relative_path=Path("Inbox/bill.pdf")),
        make_classification(category="Finance", subcategory="Bill", suggested_filename="bill"),
    )

    assert action.target_directory == existing_dir
    assert any("near-duplicate 'bills'" in warning for warning in action.warnings)


def test_planner_reuses_existing_utility_bills_directory_for_utilities(tmp_path: Path) -> None:
    existing_dir = tmp_path / "Documents" / "finance" / "utility_bills"
    existing_dir.mkdir(parents=True)
    source = tmp_path / "Documents" / "Inbox" / "utility.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("content", encoding="utf-8")

    planner = Planner(
        SortdocsConfig(),
        library_dir=tmp_path / "Documents",
        review_dir=tmp_path / "Documents",
    )

    action = planner.plan_file(
        make_discovered_file(source, relative_path=Path("Inbox/utility.pdf")),
        make_classification(category="Finance", subcategory="Utilities", suggested_filename="utility_bill"),
    )

    assert action.target_directory == existing_dir
    assert any("near-duplicate 'utility_bills'" in warning or "canonical folder name 'utility_bills'" in warning for warning in action.warnings)


def test_planner_does_not_force_reuse_when_multiple_specific_contexts_exist(tmp_path: Path) -> None:
    (tmp_path / "Documents" / "finance" / "travel_receipts").mkdir(parents=True)
    (tmp_path / "Documents" / "finance" / "medical_receipts").mkdir(parents=True)
    source = tmp_path / "Documents" / "Inbox" / "receipt.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("content", encoding="utf-8")

    planner = Planner(
        SortdocsConfig(),
        library_dir=tmp_path / "Documents",
        review_dir=tmp_path / "Documents",
    )

    action = planner.plan_file(
        make_discovered_file(source, relative_path=Path("Inbox/receipt.pdf")),
        make_classification(category="Finance", subcategory="Receipt", suggested_filename="receipt"),
    )

    assert action.target_directory == tmp_path / "Documents" / "finance" / "receipts"


def test_planner_does_not_harmonize_distinct_ai_suggested_paths_with_weak_similarity(tmp_path: Path) -> None:
    source_dir = tmp_path / "Documents" / "Inbox"
    source_dir.mkdir(parents=True)
    travel = source_dir / "travel_receipt.pdf"
    medical = source_dir / "medical_receipt.pdf"
    travel.write_text("content", encoding="utf-8")
    medical.write_text("content", encoding="utf-8")

    planner = Planner(
        SortdocsConfig(),
        library_dir=tmp_path / "Documents",
        review_dir=tmp_path / "Documents",
    )

    actions = planner.plan_files(
        [
            (
                make_discovered_file(travel, relative_path=Path("Inbox/travel_receipt.pdf")),
                make_classification(
                    category="Finance",
                    subcategory="Receipts",
                    suggested_path="finance/travel_receipts",
                    suggested_filename="travel_receipt",
                    tags=["travel", "receipt"],
                ),
            ),
            (
                make_discovered_file(medical, relative_path=Path("Inbox/medical_receipt.pdf")),
                make_classification(
                    category="Finance",
                    subcategory="Receipts",
                    suggested_path="finance/medical_receipts",
                    suggested_filename="medical_receipt",
                    tags=["medical", "receipt"],
                ),
            ),
        ]
    )

    assert {action.target_directory for action in actions} == {
        tmp_path / "Documents" / "finance" / "travel_receipts",
        tmp_path / "Documents" / "finance" / "medical_receipts",
    }


def test_render_plan_table_outputs_readable_rows(tmp_path: Path) -> None:
    source = tmp_path / "Inbox" / "invoice.pdf"
    source.parent.mkdir()
    source.write_text("content", encoding="utf-8")
    planner = Planner(
        SortdocsConfig(),
        library_dir=tmp_path / "Library",
        review_dir=tmp_path / "Review",
    )
    action = planner.plan_file(
        make_discovered_file(source, relative_path=Path("Inbox/invoice.pdf")),
        make_classification(),
    )

    table = render_plan_table([action], base_dir=tmp_path)

    assert "action" in table
    assert "source" in table
    assert "target" in table
    assert "move_and_rename" in table
    assert "Inbox/invoice.pdf" in table


def test_planner_uses_configured_folder_pattern(tmp_path: Path) -> None:
    source = tmp_path / "Inbox" / "statement.pdf"
    source.parent.mkdir()
    source.write_text("content", encoding="utf-8")
    planner = Planner(
        SortdocsConfig.model_validate({"planner": {"folder_pattern": "{year}/{category}"}}),
        library_dir=tmp_path / "Library",
        review_dir=tmp_path / "Review",
    )

    action = planner.plan_file(
        make_discovered_file(
            source,
            relative_path=Path("Inbox/statement.pdf"),
            modified_at=datetime(2025, 4, 10, tzinfo=timezone.utc),
        ),
        make_classification(category="Finance", subcategory="Statements"),
    )

    assert action.target_directory == tmp_path / "Library" / "2025" / "finance"


def test_planner_routes_disallowed_categories_to_review(tmp_path: Path) -> None:
    source = tmp_path / "Inbox" / "health.txt"
    source.parent.mkdir()
    source.write_text("content", encoding="utf-8")
    planner = Planner(
        SortdocsConfig.model_validate({"planner": {"allowed_categories": ["finance"]}}),
        library_dir=tmp_path / "Library",
        review_dir=tmp_path / "Review",
    )

    action = planner.plan_file(
        make_discovered_file(source, relative_path=Path("Inbox/health.txt")),
        make_classification(category="Health", subcategory="Visits"),
    )

    assert action.action_type == ActionType.REVIEW
    assert action.target_directory == tmp_path / "Review"
    assert any("allow-list" in warning for warning in action.warnings)


def test_sanitize_filename_handles_empty_and_long_names() -> None:
    warnings: list[str] = []
    filename = sanitize_filename(
        "   ",
        original_extension=".txt",
        max_length=18,
        warnings=warnings,
    )

    assert filename == "document.txt"
    assert warnings


def test_planner_normalizes_hyphens_spaces_and_underscores_to_one_style(tmp_path: Path) -> None:
    source = tmp_path / "Inbox" / "raw-note.txt"
    source.parent.mkdir()
    source.write_text("content", encoding="utf-8")
    planner = Planner(
        SortdocsConfig(),
        library_dir=tmp_path / "Library",
        review_dir=tmp_path / "Review",
    )

    action = planner.plan_file(
        make_discovered_file(source, relative_path=Path("Inbox/raw-note.txt")),
        make_classification(
            category="Personal-Admin",
            subcategory="Bills Paid",
            suggested_filename="March-Bill_Final Copy",
        ),
    )

    assert action.target_directory == tmp_path / "Library" / "personal_admin" / "bills_paid"
    assert action.target_filename == "march_bill_final_copy.txt"

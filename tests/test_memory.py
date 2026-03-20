from __future__ import annotations

from pathlib import Path

from sortdocs.config import MemorySettings
from sortdocs.memory import LocalMemoryStore
from sortdocs.models import ActionType, ClassificationResult, PlannedAction


def make_action(root_dir: Path, target_directory: Path) -> PlannedAction:
    target_path = target_directory / "file.pdf"
    return PlannedAction(
        source_path=root_dir / "incoming" / "file.pdf",
        target_directory=target_directory,
        target_filename=target_path.name,
        target_path=target_path,
        action_type=ActionType.MOVE,
        confidence=0.95,
        reason="Looks correct.",
        category="travel",
        subcategory="flight_tickets",
        tags=["flight", "ticket"],
        suggested_path="travel_documents/flight_tickets",
        warnings=[],
        approved_roots=(root_dir,),
        cleanup_root=root_dir,
    )


def make_classification() -> ClassificationResult:
    return ClassificationResult.model_validate(
        {
            "category": "travel",
            "subcategory": "flight_tickets",
            "suggested_path": "travel_documents/flight_tickets",
            "suggested_filename": "flight_ticket",
            "confidence": 0.95,
            "reason": "Clear ticket document.",
            "tags": ["flight", "ticket"],
            "needs_review": False,
        }
    )


def test_local_memory_store_persists_and_builds_filename_token_hints(tmp_path: Path) -> None:
    root_dir = tmp_path / "Documents"
    root_dir.mkdir()
    store = LocalMemoryStore.load(root_dir=root_dir, config=MemorySettings())

    classification = make_classification()
    action = make_action(root_dir, root_dir / "travel_documents" / "flight_tickets")
    store.remember(
        classification=classification,
        action=action,
        source_filename="air_france_flight_ticket.pdf",
    )
    written_path = store.save()

    reloaded = LocalMemoryStore.load(root_dir=root_dir, config=MemorySettings())
    context = reloaded.build_context_for_file(original_filename="flight_ticket_paris.pdf")

    assert written_path == root_dir / ".sortdocs-memory.json"
    assert context["memory_file"] == ".sortdocs-memory.json"
    token_hints = context["filename_token_hints"]
    assert token_hints[0]["target_path"] == "travel_documents/flight_tickets"
    assert "flight" in token_hints[0]["matched_tokens"]
    assert "air_france_flight_ticket.pdf" in token_hints[0]["example_filenames"]

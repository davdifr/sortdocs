from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sortdocs.config import StateSettings
from sortdocs.models import ClassificationResult
from sortdocs.scanner import DiscoveredFile
from sortdocs.state_store import ProcessingStateStore

STATE_SIGNATURE = "sig-v1"


def make_discovered_file(path: Path, *, root: Path) -> DiscoveredFile:
    stat_info = path.stat()
    return DiscoveredFile(
        absolute_path=path.resolve(),
        relative_path=path.resolve().relative_to(root.resolve()),
        extension=path.suffix.lower(),
        mime_type="text/plain",
        size_bytes=stat_info.st_size,
        created_at=None,
        modified_at=datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc),
        sha256=None,
        is_supported=True,
    )


def make_classification() -> ClassificationResult:
    return ClassificationResult.model_validate(
        {
            "category": "finance",
            "subcategory": "invoices",
            "suggested_path": "finance/invoices",
            "suggested_filename": "invoice.txt",
            "confidence": 0.92,
            "reason": "Looks like an invoice.",
            "tags": ["invoice"],
            "needs_review": False,
        }
    )


def test_state_store_persists_and_reloads_entries(tmp_path: Path) -> None:
    file_path = tmp_path / "invoice.txt"
    file_path.write_text("invoice", encoding="utf-8")

    store = ProcessingStateStore.load(root_dir=tmp_path, config=StateSettings(), signature=STATE_SIGNATURE)
    store.remember(file_path=file_path, classification=make_classification())
    saved_path = store.save()

    assert saved_path == tmp_path / ".sortdocs-state.json"
    assert saved_path.exists()

    reloaded = ProcessingStateStore.load(root_dir=tmp_path, config=StateSettings(), signature=STATE_SIGNATURE)
    cached = reloaded.lookup(make_discovered_file(file_path, root=tmp_path))

    assert cached is not None
    assert cached.category == "finance"
    assert cached.subcategory == "invoices"


def test_state_store_invalidates_entry_when_file_changes(tmp_path: Path) -> None:
    file_path = tmp_path / "invoice.txt"
    file_path.write_text("invoice", encoding="utf-8")

    store = ProcessingStateStore.load(root_dir=tmp_path, config=StateSettings(), signature=STATE_SIGNATURE)
    store.remember(file_path=file_path, classification=make_classification())
    store.save()

    file_path.write_text("invoice changed", encoding="utf-8")

    reloaded = ProcessingStateStore.load(root_dir=tmp_path, config=StateSettings(), signature=STATE_SIGNATURE)
    cached = reloaded.lookup(make_discovered_file(file_path, root=tmp_path))

    assert cached is None


def test_state_store_forget_removes_existing_entry(tmp_path: Path) -> None:
    file_path = tmp_path / "invoice.txt"
    file_path.write_text("invoice", encoding="utf-8")

    store = ProcessingStateStore.load(root_dir=tmp_path, config=StateSettings(), signature=STATE_SIGNATURE)
    store.remember(file_path=file_path, classification=make_classification())
    store.save()

    store.forget(Path("invoice.txt"))
    store.save()

    reloaded = ProcessingStateStore.load(root_dir=tmp_path, config=StateSettings(), signature=STATE_SIGNATURE)

    assert reloaded.lookup(make_discovered_file(file_path, root=tmp_path)) is None


def test_state_store_ignores_entries_when_signature_changes(tmp_path: Path) -> None:
    file_path = tmp_path / "invoice.txt"
    file_path.write_text("invoice", encoding="utf-8")

    store = ProcessingStateStore.load(root_dir=tmp_path, config=StateSettings(), signature="sig-a")
    store.remember(file_path=file_path, classification=make_classification())
    store.save()

    reloaded = ProcessingStateStore.load(root_dir=tmp_path, config=StateSettings(), signature="sig-b")

    assert reloaded.lookup(make_discovered_file(file_path, root=tmp_path)) is None

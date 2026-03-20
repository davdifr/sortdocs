from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sortdocs.scanner import DirectoryScanner, ScannerOptions


def test_scanner_base_scan_returns_discovered_file_metadata(tmp_path: Path) -> None:
    sample = tmp_path / "note.txt"
    sample.write_text("hello sortdocs", encoding="utf-8")

    scanner = DirectoryScanner()
    discovered = scanner.scan(tmp_path)

    assert len(discovered) == 1
    item = discovered[0]
    assert item.absolute_path == sample.resolve()
    assert item.relative_path == Path("note.txt")
    assert item.extension == ".txt"
    assert item.mime_type == "text/plain"
    assert item.size_bytes == 14
    assert item.sha256 is None
    assert item.is_supported is True
    assert isinstance(item.modified_at, datetime)
    assert item.created_at is None or isinstance(item.created_at, datetime)


def test_scanner_skips_hidden_temp_files_and_symlinks(tmp_path: Path) -> None:
    visible = tmp_path / "keep.txt"
    hidden_file = tmp_path / ".hidden.txt"
    temp_file = tmp_path / "draft.tmp"
    lock_file = tmp_path / "~$locked.docx"
    hidden_dir = tmp_path / ".secret"
    hidden_dir.mkdir()
    nested_hidden = hidden_dir / "nested.txt"

    visible.write_text("keep", encoding="utf-8")
    hidden_file.write_text("skip", encoding="utf-8")
    temp_file.write_text("skip", encoding="utf-8")
    lock_file.write_text("skip", encoding="utf-8")
    nested_hidden.write_text("skip", encoding="utf-8")

    symlink_path = tmp_path / "link.txt"
    symlink_path.symlink_to(visible)

    scanner = DirectoryScanner(ScannerOptions(recursive=True, include_unsupported=True))
    discovered = scanner.scan(tmp_path)

    assert [item.relative_path for item in discovered] == [Path("keep.txt")]


def test_scanner_filters_unsupported_by_default(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "archive.bin").write_text("binary-ish", encoding="utf-8")

    default_results = DirectoryScanner().scan(tmp_path)
    all_results = DirectoryScanner(ScannerOptions(include_unsupported=True)).scan(tmp_path)

    assert [item.relative_path for item in default_results] == [Path("note.txt")]
    assert [item.relative_path for item in all_results] == [Path("archive.bin"), Path("note.txt")]
    assert all_results[0].is_supported is False
    assert all_results[1].is_supported is True


def test_scanner_recursive_on_off(tmp_path: Path) -> None:
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    (tmp_path / "top.txt").write_text("top", encoding="utf-8")
    (nested_dir / "child.txt").write_text("child", encoding="utf-8")

    non_recursive = DirectoryScanner(ScannerOptions(recursive=False)).scan(tmp_path)
    recursive = DirectoryScanner(ScannerOptions(recursive=True)).scan(tmp_path)

    assert [item.relative_path for item in non_recursive] == [Path("top.txt")]
    assert [item.relative_path for item in recursive] == [Path("nested/child.txt"), Path("top.txt")]


def test_scanner_respects_max_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "c.txt").write_text("c", encoding="utf-8")

    scanner = DirectoryScanner(ScannerOptions(max_files=2))
    discovered = scanner.scan(tmp_path)

    assert len(discovered) == 2
    assert [item.relative_path for item in discovered] == [Path("a.txt"), Path("b.txt")]


def test_scanner_marks_oversized_files_as_unsupported_for_safety(tmp_path: Path) -> None:
    large_file = tmp_path / "large.txt"
    large_file.write_text("x" * 32, encoding="utf-8")

    scanner = DirectoryScanner(ScannerOptions(max_file_size_bytes=16, include_unsupported=True))
    discovered = scanner.scan(tmp_path)

    assert len(discovered) == 1
    assert discovered[0].is_supported is False
    assert any("safe size limit" in warning for warning in discovered[0].warnings)


def test_scanner_blocks_binary_payloads_disguised_as_text(tmp_path: Path) -> None:
    disguised_binary = tmp_path / "payload.txt"
    disguised_binary.write_bytes(b"\x00\x01\x02\x03binary")

    scanner = DirectoryScanner(ScannerOptions(include_unsupported=True))
    discovered = scanner.scan(tmp_path)

    assert len(discovered) == 1
    assert discovered[0].is_supported is False
    assert any("appears binary" in warning for warning in discovered[0].warnings)


def test_scanner_skips_managed_output_directories_by_default(tmp_path: Path) -> None:
    inbox_file = tmp_path / "Inbox.txt"
    library_file = tmp_path / "Library" / "sorted.txt"
    review_file = tmp_path / "Review" / "needs-review.txt"

    inbox_file.write_text("keep", encoding="utf-8")
    library_file.parent.mkdir()
    review_file.parent.mkdir()
    library_file.write_text("skip", encoding="utf-8")
    review_file.write_text("skip", encoding="utf-8")

    discovered = DirectoryScanner(ScannerOptions(recursive=True, include_unsupported=True)).scan(tmp_path)

    assert [item.relative_path for item in discovered] == [Path("Inbox.txt")]

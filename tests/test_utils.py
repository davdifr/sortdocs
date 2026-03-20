from __future__ import annotations

from pathlib import Path

from sortdocs.utils import build_output_filename, reserve_unique_path, sanitize_path_component


def test_sanitize_path_component_normalizes_input() -> None:
    assert sanitize_path_component("Fàttura Enel 03/2026", default="x") == "fattura_enel_03_2026"


def test_build_output_filename_strips_extension_and_applies_limit() -> None:
    result = build_output_filename("My Report.pdf", ".pdf", 18)
    assert result.endswith(".pdf")
    assert result == "my_report.pdf"


def test_reserve_unique_path_handles_collision(tmp_path: Path) -> None:
    original = tmp_path / "document.pdf"
    original.write_text("existing", encoding="utf-8")
    reserved = reserve_unique_path(original, set())
    assert reserved.name == "document__1.pdf"


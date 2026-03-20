from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sortdocs.config import SortdocsConfig
from sortdocs.models import ClassificationResult
from sortdocs.cli import app


runner = CliRunner()


def test_cli_dry_run_smoke(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "inbox"
    source.mkdir()
    (source / "invoice.txt").write_text("Invoice for March", encoding="utf-8")

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
                    "suggested_filename": "invoice",
                    "confidence": 0.91,
                    "reason": "Looks like an invoice.",
                    "tags": ["invoice"],
                    "needs_review": False,
                }
            )

    monkeypatch.setattr("sortdocs.pipeline.OpenAIClassificationClient", FakeOpenAIClassificationClient)

    result = runner.invoke(app, [str(source), "--dry-run"])

    assert result.exit_code == 0
    assert "Analyzing files..." in result.stdout
    assert "sortdocs DRY-RUN" in result.stdout
    assert "Plan Overview" in result.stdout
    assert "Planned Actions" in result.stdout
    assert "Run Summary" in result.stdout


def test_cli_default_flow_prompts_and_aborts_without_changes(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "inbox"
    source.mkdir()
    original_file = source / "invoice.txt"
    original_file.write_text("Invoice for March", encoding="utf-8")

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
                    "suggested_filename": "invoice-final",
                    "confidence": 0.91,
                    "reason": "Looks like an invoice.",
                    "tags": ["invoice"],
                    "needs_review": False,
                }
            )

    monkeypatch.setattr("sortdocs.pipeline.OpenAIClassificationClient", FakeOpenAIClassificationClient)

    result = runner.invoke(app, [str(source)], input="n\n")

    assert result.exit_code == 0
    assert "Analyzing files..." in result.stdout
    assert "sortdocs PLAN + CONFIRM" in result.stdout
    assert "Proceed with these actions?" in result.stdout
    assert "Aborted. No changes were made." in result.stdout
    assert original_file.exists()
    assert not (source / "Library").exists()

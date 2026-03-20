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
    assert "Analysis complete:" in result.stdout
    assert "sortdocs DRY-RUN" in result.stdout
    assert "Plan Overview" in result.stdout
    assert "Planned Actions" in result.stdout
    assert "Preview complete." in result.stdout
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
    assert "Analysis complete:" in result.stdout
    assert "sortdocs PLAN + CONFIRM" in result.stdout
    assert "Ready to apply." in result.stdout
    assert "Proceed with these actions?" in result.stdout
    assert "Aborted. No changes were made." in result.stdout
    assert original_file.exists()
    assert not (source / "Library").exists()


def test_cli_refuses_project_like_root_by_default(tmp_path: Path) -> None:
    project_dir = tmp_path / "my-app"
    project_dir.mkdir()
    (project_dir / ".git").mkdir()
    (project_dir / "README.md").write_text("project", encoding="utf-8")

    result = runner.invoke(app, [str(project_dir), "--dry-run"])

    assert result.exit_code == 2
    assert "Refusing to scan project-like root" in result.stdout
    assert "--allow-project-root" in result.stdout


def test_cli_can_override_project_root_protection(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "my-app"
    project_dir.mkdir()
    (project_dir / ".git").mkdir()
    (project_dir / "README.md").write_text("project", encoding="utf-8")

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
                    "category": "Reference",
                    "subcategory": "Docs",
                    "suggested_path": "reference/docs",
                    "suggested_filename": "readme",
                    "confidence": 0.88,
                    "reason": "Looks like documentation.",
                    "tags": ["docs"],
                    "needs_review": False,
                }
            )

    monkeypatch.setattr("sortdocs.pipeline.OpenAIClassificationClient", FakeOpenAIClassificationClient)

    result = runner.invoke(app, [str(project_dir), "--dry-run", "--allow-project-root"])

    assert result.exit_code == 0
    assert "Project root" in result.stdout
    assert "allowed" in result.stdout

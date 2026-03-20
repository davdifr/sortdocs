from __future__ import annotations

import os
from pathlib import Path

import pytest
from rich.console import Console

from sortdocs.onboarding import (
    OnboardingError,
    OnboardingPaths,
    load_saved_environment,
    maybe_run_first_run_onboarding,
)


def make_paths(tmp_path: Path) -> OnboardingPaths:
    config_dir = tmp_path / ".config" / "sortdocs"
    return OnboardingPaths(
        config_dir=config_dir,
        env_path=config_dir / ".env",
        state_path=config_dir / "onboarding.json",
    )


def test_load_saved_environment_reads_global_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = make_paths(tmp_path)
    paths.config_dir.mkdir(parents=True)
    paths.env_path.write_text("OPENAI_API_KEY='saved-key'\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    loaded_path = load_saved_environment(paths=paths)

    assert loaded_path == paths.env_path
    assert os.environ["OPENAI_API_KEY"] == "saved-key"


def test_first_run_onboarding_saves_api_key_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = make_paths(tmp_path)
    console = Console(record=True)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("sortdocs.onboarding.get_onboarding_paths", lambda: paths)
    monkeypatch.setattr("sortdocs.onboarding.is_interactive_terminal", lambda: True)
    monkeypatch.setattr("sortdocs.onboarding.typer.prompt", lambda *args, **kwargs: "sk-test-key")
    monkeypatch.setattr("sortdocs.onboarding.typer.confirm", lambda *args, **kwargs: True)

    saved_path = maybe_run_first_run_onboarding(console)

    assert saved_path == paths.env_path
    assert paths.env_path.exists()
    assert "OPENAI_API_KEY" in paths.env_path.read_text(encoding="utf-8")
    assert os.environ["OPENAI_API_KEY"] == "sk-test-key"
    assert paths.state_path.exists()
    output = console.export_text()
    assert "Welcome To sortdocs" in output
    assert "OpenAI API Key Setup" in output


def test_first_run_onboarding_errors_cleanly_when_missing_key_non_interactive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = make_paths(tmp_path)
    console = Console(record=True)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("sortdocs.onboarding.get_onboarding_paths", lambda: paths)
    monkeypatch.setattr("sortdocs.onboarding.is_interactive_terminal", lambda: False)

    with pytest.raises(OnboardingError, match="OPENAI_API_KEY is not set"):
        maybe_run_first_run_onboarding(console)

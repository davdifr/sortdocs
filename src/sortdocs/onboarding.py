from __future__ import annotations

import json
import os
import shlex
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_API_KEYS_URL = "https://platform.openai.com/settings/organization/api-keys"
OPENAI_API_QUICKSTART_URL = "https://platform.openai.com/docs/quickstart/step-2-setup-your-api-key"
OPENAI_API_BILLING_URL = "https://help.openai.com/en/articles/8156019-how-can-i-move-my-chatgpt-subscription-to-the-api"
CONFIG_DIR_NAME = "sortdocs"
GLOBAL_ENV_FILENAME = ".env"
STATE_FILENAME = "onboarding.json"


class OnboardingError(RuntimeError):
    pass


@dataclass(frozen=True)
class OnboardingPaths:
    config_dir: Path
    env_path: Path
    state_path: Path


def get_onboarding_paths() -> OnboardingPaths:
    config_dir = (Path.home() / ".config" / CONFIG_DIR_NAME).resolve()
    return OnboardingPaths(
        config_dir=config_dir,
        env_path=config_dir / GLOBAL_ENV_FILENAME,
        state_path=config_dir / STATE_FILENAME,
    )


def load_saved_environment(*, paths: Optional[OnboardingPaths] = None) -> Optional[Path]:
    resolved_paths = paths or get_onboarding_paths()
    if not resolved_paths.env_path.exists():
        return None

    for key, value in _read_env_file(resolved_paths.env_path).items():
        if not os.getenv(key, "").strip():
            os.environ[key] = value
    return resolved_paths.env_path


def maybe_run_first_run_onboarding(console: Console) -> Optional[Path]:
    paths = get_onboarding_paths()
    loaded_env_path = load_saved_environment(paths=paths)
    state = load_onboarding_state(paths=paths)

    if not state.get("welcome_shown", False):
        render_welcome(console)
        save_onboarding_state(paths=paths, welcome_shown=True)

    if os.getenv(OPENAI_API_KEY_ENV, "").strip():
        return loaded_env_path

    if not is_interactive_terminal():
        raise OnboardingError(
            "OPENAI_API_KEY is not set. Create one at "
            f"{OPENAI_API_KEYS_URL} and try again."
        )

    render_api_key_setup(console, paths=paths)
    api_key = prompt_for_api_key()
    os.environ[OPENAI_API_KEY_ENV] = api_key

    should_save = typer.confirm(
        f"Save this key for future runs in {paths.env_path}?",
        default=True,
    )
    if not should_save:
        console.print("[dim]The API key will be used only for this run.[/dim]")
        return None

    try:
        save_api_key(paths=paths, api_key=api_key)
    except OSError as exc:
        console.print(
            f"[yellow]Could not save the API key to {paths.env_path}: {exc}. "
            "The key will still be used for this run.[/yellow]"
        )
        return None

    console.print(f"[green]Saved OPENAI_API_KEY to {paths.env_path}[/green]")
    return paths.env_path


def is_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def prompt_for_api_key() -> str:
    while True:
        value = typer.prompt("Paste your OpenAI API key", hide_input=True).strip()
        if value:
            return value
        typer.echo("The API key cannot be blank.")


def save_api_key(*, paths: OnboardingPaths, api_key: str) -> Path:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    temp_path = paths.env_path.with_name(f".{paths.env_path.name}.tmp")
    content = f'{OPENAI_API_KEY_ENV}={shlex.quote(api_key)}\n'
    temp_path.write_text(content, encoding="utf-8")
    os.chmod(temp_path, 0o600)
    temp_path.replace(paths.env_path)
    return paths.env_path


def load_onboarding_state(*, paths: Optional[OnboardingPaths] = None) -> dict[str, object]:
    resolved_paths = paths or get_onboarding_paths()
    if not resolved_paths.state_path.exists():
        return {}

    try:
        payload = json.loads(resolved_paths.state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def save_onboarding_state(*, paths: OnboardingPaths, welcome_shown: bool) -> Path:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "welcome_shown": welcome_shown,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    temp_path = paths.state_path.with_name(f".{paths.state_path.name}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(paths.state_path)
    return paths.state_path


def render_welcome(console: Console) -> None:
    table = Table.grid(padding=(0, 1))
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row("Welcome", "sortdocs organizes documents with a safe plan-first flow.")
    table.add_row("Default flow", "Scan recursively, show a plan, ask before applying.")
    table.add_row("Safety", "Project folders, ignored paths, collisions, and risky moves are guarded.")
    console.print(Panel(table, title="Welcome To sortdocs", border_style="cyan"))
    console.print()


def render_api_key_setup(console: Console, *, paths: OnboardingPaths) -> None:
    table = Table.grid(padding=(0, 1))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Why", "sortdocs uses the OpenAI API to classify files from their content and context.")
    table.add_row("Create key", OPENAI_API_KEYS_URL)
    table.add_row("Setup guide", OPENAI_API_QUICKSTART_URL)
    table.add_row("Billing note", "ChatGPT and API usage are billed separately.")
    table.add_row("Learn more", OPENAI_API_BILLING_URL)
    table.add_row("Saved location", str(paths.env_path))
    console.print(Panel(table, title="OpenAI API Key Setup", border_style="yellow"))
    console.print()


def _read_env_file(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return parsed

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]
        parsed[key] = value
    return parsed

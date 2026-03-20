from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path
from typing import Sequence

APP_DISPLAY_NAME = "sortdocs"
BUNDLE_IDENTIFIER = "com.sortdocs.app"
MIN_PYTHON = (3, 11)
GUI_ENTRYPOINT_RELATIVE_PATH = Path("src/sortdocs/gui_launcher.py")
BUNDLE_SPEC_RELATIVE_PATH = Path("packaging/sortdocs-gui.spec")
BUNDLE_OUTPUT_RELATIVE_PATH = Path("dist/sortdocs.app")
PYINSTALLER_HIDDEN_IMPORTS = [
    "sortdocs.gui.app",
    "sortdocs.gui.api_key_dialog",
    "sortdocs.gui.main_window",
    "sortdocs.gui.presenter",
    "sortdocs.gui.workers",
]


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def validate_bundle_environment(
    *,
    platform_name: str | None = None,
    python_version: tuple[int, int, int] | None = None,
) -> None:
    current_platform = platform_name or platform.system()
    current_version = python_version or sys.version_info[:3]

    if current_platform != "Darwin":
        raise RuntimeError("Standalone GUI bundling is currently supported only on macOS.")
    if current_version < MIN_PYTHON:
        major, minor = MIN_PYTHON
        raise RuntimeError(
            f"sortdocs bundling requires Python {major}.{minor}+; "
            f"current interpreter is {current_version[0]}.{current_version[1]}.{current_version[2]}."
        )


def build_pyinstaller_command(
    project_root: Path,
    *,
    python_executable: str | None = None,
) -> list[str]:
    interpreter = python_executable or sys.executable
    spec_path = project_root / BUNDLE_SPEC_RELATIVE_PATH
    return [interpreter, "-m", "PyInstaller", "--noconfirm", "--clean", str(spec_path)]


def expected_bundle_path(project_root: Path) -> Path:
    return project_root / BUNDLE_OUTPUT_RELATIVE_PATH


def _ensure_build_dependencies() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "PyInstaller is not installed. Install bundle dependencies with "
            "`pip install -e '.[bundle]'` or `uv sync --extra bundle`."
        ) from exc

    try:
        import PySide6  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "PySide6 is not installed. Install bundle dependencies with "
            "`pip install -e '.[bundle]'` or `uv sync --extra bundle`."
        ) from exc


def build_standalone_app(
    *,
    project_root: Path | None = None,
    python_executable: str | None = None,
) -> Path:
    validate_bundle_environment()
    _ensure_build_dependencies()

    resolved_root = (project_root or default_project_root()).resolve()
    spec_path = resolved_root / BUNDLE_SPEC_RELATIVE_PATH
    if not spec_path.exists():
        raise RuntimeError(f"PyInstaller spec file was not found: {spec_path}")

    command = build_pyinstaller_command(resolved_root, python_executable=python_executable)
    subprocess.run(command, cwd=resolved_root, check=True)

    bundle_path = expected_bundle_path(resolved_root)
    if not bundle_path.exists():
        raise RuntimeError(f"Expected standalone bundle was not created: {bundle_path}")
    return bundle_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the standalone macOS sortdocs GUI bundle.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=default_project_root(),
        help="Project root containing pyproject.toml and packaging/sortdocs-gui.spec",
    )
    parser.add_argument(
        "--python-executable",
        default=sys.executable,
        help="Python interpreter that has PyInstaller and PySide6 installed.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    bundle_path = build_standalone_app(
        project_root=args.project_root,
        python_executable=args.python_executable,
    )
    print(f"Standalone app bundle created at {bundle_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

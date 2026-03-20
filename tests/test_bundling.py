from __future__ import annotations

from pathlib import Path

import pytest

from sortdocs import bundling


def test_validate_bundle_environment_rejects_non_macos() -> None:
    with pytest.raises(RuntimeError, match="macOS"):
        bundling.validate_bundle_environment(platform_name="Linux", python_version=(3, 11, 9))


def test_validate_bundle_environment_rejects_old_python() -> None:
    with pytest.raises(RuntimeError, match="requires Python 3.11\\+"):
        bundling.validate_bundle_environment(platform_name="Darwin", python_version=(3, 10, 14))


def test_build_pyinstaller_command_targets_project_spec_file(tmp_path: Path) -> None:
    command = bundling.build_pyinstaller_command(
        tmp_path,
        python_executable="/tmp/venv/bin/python",
    )

    assert command[:3] == ["/tmp/venv/bin/python", "-m", "PyInstaller"]
    assert command[-1] == str(tmp_path / "packaging" / "sortdocs-gui.spec")


def test_expected_bundle_path_points_to_dist_app(tmp_path: Path) -> None:
    assert bundling.expected_bundle_path(tmp_path) == tmp_path / "dist" / "sortdocs.app"

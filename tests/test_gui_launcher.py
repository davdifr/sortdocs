from __future__ import annotations

import builtins

import pytest

from sortdocs import gui_launcher


def test_gui_launcher_exits_cleanly_when_gui_dependency_is_missing(
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sortdocs.gui.app":
            raise ImportError("PySide6 missing")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(SystemExit, match="1"):
        gui_launcher.main()

    captured = capsys.readouterr()
    assert "sortdocs GUI requires PySide6" in captured.err

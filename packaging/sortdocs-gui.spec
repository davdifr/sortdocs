# -*- mode: python ; coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(project_root / "src"))

from sortdocs.bundling import (
    APP_DISPLAY_NAME,
    BUNDLE_IDENTIFIER,
    GUI_ENTRYPOINT_RELATIVE_PATH,
    PYINSTALLER_HIDDEN_IMPORTS,
)

hiddenimports = list(PYINSTALLER_HIDDEN_IMPORTS)
hiddenimports += collect_submodules("sortdocs.extractors")

a = Analysis(
    [str(project_root / GUI_ENTRYPOINT_RELATIVE_PATH)],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_DISPLAY_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_DISPLAY_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_DISPLAY_NAME}.app",
    icon=None,
    bundle_identifier=BUNDLE_IDENTIFIER,
    info_plist={
        "CFBundleDisplayName": APP_DISPLAY_NAME,
        "CFBundleName": APP_DISPLAY_NAME,
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    },
)

# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

import PyInstaller.config

BACKEND_DIR = Path(os.path.abspath(SPEC)).parent.resolve()
ROOT_DIR = BACKEND_DIR.parent

block_cipher = None

a = Analysis(
    [str(BACKEND_DIR / "run.py")],
    pathex=[str(BACKEND_DIR)],
    binaries=[],
    datas=[
        (str(ROOT_DIR / "data"), "data"),
        (str(BACKEND_DIR / ".env.example"), "."),
    ],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "pygame",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="novatts-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon=None,
)

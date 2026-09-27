# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

import PyInstaller.config

BACKEND_DIR = Path(os.path.abspath(SPEC)).parent.resolve()
ROOT_DIR = BACKEND_DIR.parent

# Only the shared defaults belong in the bundle. Anything describing the local
# audio library or a local game is left out on purpose: emotion_sound_map.json,
# emotion_aliases.json, perfect_cut.json and games/*/speakers.json are personal
# runtime data, gitignored, and the app recreates them on first run. Bundling
# data/ wholesale would bake the build machine's library into the release.
DATA_DEFAULTS = [
    "active_game.json",
    "blacklist.json",
    "emotion_patterns.json",
    "speakers.json",
    "emotion_sound_map.json.example",
    "emotion_aliases.json.example",
    "README.md",
]
data_datas = [
    (str(ROOT_DIR / "data" / name), "data")
    for name in DATA_DEFAULTS
    if (ROOT_DIR / "data" / name).is_file()
]

block_cipher = None

a = Analysis(
    [str(BACKEND_DIR / "run.py")],
    pathex=[str(BACKEND_DIR)],
    binaries=[],
    datas=data_datas + [(str(BACKEND_DIR / ".env.example"), ".")],
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

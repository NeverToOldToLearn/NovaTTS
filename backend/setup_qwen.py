"""Download Qwen3-TTS GGUF models and start the tts-server.

Requires: pip install huggingface_hub  (or use hf download via HF CLI)

The target directory is derived from the configured engine (``NOVATTS_QWEN_BIN``
/ ``NOVATTS_QWEN_MODEL``) or, when nothing is configured yet, from the AI-tools
install location (``%LOCALAPPDATA%\\NovaTTS\\AI-Tools\\qwentts.cpp``). Override
with ``--qwentts-dir`` / ``--models-dir``.

Usage:
  .\\.venv\\Scripts\\python.exe setup_qwen.py --variant 1.7b-customvoice
  .\\.venv\\Scripts\\python.exe setup_qwen.py --variant 0.6b-customvoice   # lighter, less VRAM
  .\\.venv\\Scripts\\python.exe setup_qwen.py --check                      # only check what's present
  .\\.venv\\Scripts\\python.exe setup_qwen.py --models-dir "D:\\models"
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPOS = {
    "tokenizer": "Serveurperso/Qwen3-TTS-GGUF",
    "0.6b-base": "Serveurperso/Qwen3-TTS-GGUF",
    "0.6b-customvoice": "Serveurperso/Qwen3-TTS-GGUF",
    "1.7b-base": "Serveurperso/Qwen3-TTS-GGUF",
    "1.7b-customvoice": "Serveurperso/Qwen3-TTS-GGUF",
}

NEEDED = {
    "0.6b-customvoice": [
        "qwen-talker-0.6b-customvoice-Q8_0.gguf",
        "qwen-tokenizer-12hz-Q8_0.gguf",
    ],
    "1.7b-customvoice": [
        "qwen-talker-1.7b-customvoice-Q8_0.gguf",
        "qwen-tokenizer-12hz-Q8_0.gguf",
    ],
    "0.6b-base": ["qwen-talker-0.6b-base-Q8_0.gguf", "qwen-tokenizer-12hz-Q8_0.gguf"],
    "1.7b-base": ["qwen-talker-1.7b-base-Q8_0.gguf", "qwen-tokenizer-12hz-Q8_0.gguf"],
}


def _configured() -> tuple[str, str]:
    """Current engine/model paths from the backend config, if available."""
    try:
        from novatts.config import settings
    except Exception:
        return "", ""
    return settings.qwen_bin or "", settings.qwen_model or ""


def default_qwentts_dir() -> Path:
    """Engine checkout: <dir>\\build\\Release\\tts-server.exe lives under it."""
    qwen_bin, _ = _configured()
    if qwen_bin:
        exe = Path(qwen_bin)
        # ...\qwentts.cpp\build\Release\tts-server.exe -> ...\qwentts.cpp
        if exe.parent.name.lower() == "release" and exe.parent.parent.name.lower() == "build":
            return exe.parent.parent.parent
        return exe.parent
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return Path(local) / "NovaTTS" / "AI-Tools" / "qwentts.cpp"
    return Path.cwd() / "qwentts.cpp"


def default_models_dir(qwentts: Path) -> Path:
    _, model = _configured()
    if model:
        return Path(model).parent
    return qwentts / "models"


def check(models: Path, variant: str) -> bool:
    need = NEEDED.get(variant, [])
    ok = True
    for name in need:
        p = models / name
        print(f"  {'OK' if p.exists() else 'MISSING'} {name} ({p})")
        if not p.exists():
            ok = False
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="1.7b-customvoice", choices=list(NEEDED))
    ap.add_argument("--qwentts-dir", default="", help="qwentts.cpp checkout (default: configured/installed)")
    ap.add_argument("--models-dir", default="", help="Model directory (default: <qwentts>/models)")
    ap.add_argument("--check", action="store_true", help="Only check")
    args = ap.parse_args()

    qwentts = Path(args.qwentts_dir) if args.qwentts_dir else default_qwentts_dir()
    models = Path(args.models_dir) if args.models_dir else default_models_dir(qwentts)

    models.mkdir(parents=True, exist_ok=True)
    print(f"Qwen root: {qwentts}")
    print(f"Models dir: {models}")
    if check(models, args.variant):
        print("All required GGUFs present.")
    else:
        print(f"Missing files for {args.variant}. Download with one of:")
        print(f"  hf download Serveurperso/Qwen3-TTS-GGUF --local-dir {models}")
        print(f"  python -m huggingface_hub.cli download Serveurperso/Qwen3-TTS-GGUF --local-dir {models}")
        print("Or run checkpoints.sh/convert.py per qwentts.cpp README.")
        if args.check:
            return 1
        try:
            import huggingface_hub  # noqa: F401
        except ImportError:
            print("Installing huggingface_hub ...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "huggingface_hub"])
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id="Serveurperso/Qwen3-TTS-GGUF",
            local_dir=str(models),
            local_dir_use_symlinks=False,
        )
        check(models, args.variant)

    print("\nStart the engine:")
    need = NEEDED[args.variant]
    print(f'  {qwentts / "build" / "Release" / "tts-server.exe"} --model {models / need[0]} --codec {models / need[1]} --port 8081')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

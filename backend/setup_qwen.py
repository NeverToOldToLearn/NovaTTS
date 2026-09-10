"""Download Qwen3-TTS GGUF models and start the tts-server.

Requires: pip install huggingface_hub  (or use hf download via HF CLI)
Downloads to D:\\Projects\\qwentts.cpp\\models  (pre-converted GGUFs).

Usage:
  .\\.venv\\Scripts\\python.exe setup_qwen.py --variant 1.7b-customvoice
  .\\.venv\\Scripts\\python.exe setup_qwen.py --variant 0.6b-customvoice   # lighter, less VRAM
  .\\.venv\\Scripts\\python.exe setup_qwen.py --check                      # only check what's present
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

QWENTTS = Path(r"D:\Projects\qwentts.cpp")
MODELS = QWENTTS / "models"

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


def check(variant: str) -> bool:
    need = NEEDED.get(variant, [])
    ok = True
    for name in need:
        p = MODELS / name
        print(f"  {'OK' if p.exists() else 'MISSING'} {name} ({p})")
        if not p.exists():
            ok = False
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="1.7b-customvoice", choices=list(NEEDED))
    ap.add_argument("--check", action="store_true", help="Only check")
    args = ap.parse_args()

    if not MODELS.exists():
        MODELS.mkdir(parents=True, exist_ok=True)

    print(f"Models dir: {MODELS}")
    if check(args.variant):
        print("All required GGUFs present.")
    else:
        print(f"Missing files for {args.variant}. Download with one of:")
        print(f"  hf download Serveurperso/Qwen3-TTS-GGUF --local-dir {MODELS}")
        print(f"  python -m huggingface_hub.cli download Serveurperso/Qwen3-TTS-GGUF --local-dir {MODELS}")
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
            local_dir=str(MODELS),
            local_dir_use_symlinks=False,
        )
        check(args.variant)

    print("\nStart the engine:")
    need = NEEDED[args.variant]
    print(f'  {QWENTTS / "build" / "Release" / "tts-server.exe"} --model {MODELS / need[0]} --codec {MODELS / need[1]} --port 8081')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

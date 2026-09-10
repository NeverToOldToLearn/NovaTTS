"""Batch-import WAV voices from Samples_Clone into the qwentts.cpp engine.

Uses the NovaTTS backend HTTP API in-process: pairs each .wav with its
optional sibling .txt (ref_text). Ignores subdirectories and non-file
entries. Skips files > 60s at 24kHz mono 16-bit (~3MB).

Run:
  .\\.venv\\Scripts\\python.exe import_voices.py
  .\\.venv\\Scripts\\python.exe import_voices.py --dir "D:\\!!Scripts!!\\Samples_Clone" --limit 20
  .\\.venv\\Scripts\\python.exe import_voices.py --dry-run
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

import requests

DEFAULT_SRC = r"D:\!!Scripts!!\Samples_Clone"
DEFAULT_QWEN = "http://127.0.0.1:8080"
SKIP_DIRS = {"2ndBatch", "Clean", "Rework", "Temp", "Temp2", "Bleh", "Alone", "Brooke"}

EXCLUDE_WAV = {"output_quick_test.wav"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Import cloned voices into qwentts engine")
    p.add_argument("--dir", default=DEFAULT_SRC, help="Samples_Clone directory")
    p.add_argument("--qwen-url", default=DEFAULT_QWEN)
    p.add_argument("--limit", type=int, default=0, help="Max voices to import (0=all)")
    p.add_argument("--force", action="store_true", help="Re-register even if voice exists")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--include-subdirs", action="store_true", help="Also scan subdirectories")
    return p


def list_existing(qwen_url: str) -> set[str]:
    try:
        r = requests.get(f"{qwen_url.rstrip('/')}/v1/audio/voices", timeout=5)
        r.raise_for_status()
        raw = r.json().get("voices", [])
        out: set[str] = set()
        for entry in raw:
            if isinstance(entry, dict):
                n = entry.get("name")
                if isinstance(n, str):
                    out.add(n)
            elif isinstance(entry, str):
                out.add(entry)
        return out
    except Exception:
        return set()


def main() -> int:
    args = build_parser().parse_args()
    src = Path(args.dir)
    if not src.exists():
        print(f"Source dir not found: {src}", file=sys.stderr)
        return 2

    qwen_url = args.qwen_url.rstrip("/")
    try:
        h = requests.get(f"{qwen_url}/health", timeout=3).json()
        print(f"Qwen {qwen_url} -> {h}")
    except Exception as exc:
        print(f"Qwen not reachable at {qwen_url}: {exc}", file=sys.stderr)
        print("Start it: tts-server.exe -m <model.gguf> --port 8081", file=sys.stderr)
        return 2
    if h.get("status") != "ok":
        print(f"Qwen health not ok: {h}", file=sys.stderr)
        return 2

    existing = list_existing(qwen_url)
    print(f"Existing voices on engine: {len(existing)}")

    pattern = "**/*.wav" if args.include_subdirs else "*.wav"
    wavs = sorted(src.glob(pattern), key=lambda p: p.name.lower())
    wavs = [p for p in wavs if p.is_file() and p.name not in EXCLUDE_WAV]
    if not args.include_subdirs:
        wavs = [p for p in wavs if p.parent == src]
    else:
        wavs = [p for p in wavs if not any(part in SKIP_DIRS for part in p.parts)]

    if args.limit:
        wavs = wavs[: args.limit]

    print(f"Found {len(wavs)} wav files to consider")
    if args.dry_run:
        for p in wavs[:20]:
            txt = p.with_suffix(".txt")
            ref = txt.read_text(encoding="utf-8", errors="replace").strip()[:60] if txt.exists() else "(no txt)"
            print(f"  would import: {p.name}  ref={ref!r}")
        if len(wavs) > 20:
            print(f"  ... and {len(wavs) - 20} more")
        return 0

    ok = 0
    skipped = 0
    failed: list[str] = []
    for wav in wavs:
        voice_name = wav.stem
        if voice_name in existing and not args.force:
            skipped += 1
            continue
        txt = wav.with_suffix(".txt")
        ref_text = ""
        if txt.exists():
            try:
                ref_text = txt.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                pass

        raw = wav.read_bytes()
        if len(raw) > 5_000_000:
            print(f"  skip {voice_name}: too large ({len(raw)} bytes)")
            skipped += 1
            continue

        payload: dict[str, object] = {
            "name": voice_name,
            "wav_b64": base64.b64encode(raw).decode("ascii"),
        }
        if ref_text:
            payload["ref_text"] = ref_text

        try:
            r = requests.post(f"{qwen_url}/v1/audio/voices", json=payload, timeout=60)
            if r.status_code != 200:
                failed.append(f"{voice_name}: {r.status_code} {r.text[:120]}")
                print(f"  FAIL {voice_name}: {r.status_code} {r.text[:120]}")
            else:
                ok += 1
                if ok % 20 == 0:
                    print(f"  ... {ok} imported")
        except Exception as exc:
            failed.append(f"{voice_name}: {exc}")
            print(f"  ERR {voice_name}: {exc}")

    print(f"Done: imported={ok} skipped={skipped} failed={len(failed)}")
    for f in failed[:10]:
        print(f"  failed: {f}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

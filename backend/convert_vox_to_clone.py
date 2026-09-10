"""Convert voxceleb raw (16k) -> Samples_Clone (24k mono pcm16) for Qwen.

Writes to D:\\!!Scripts!!\\Samples_Clone\\idXXXXX.wav (+ .txt if present).
Skips existing unless --force. Picks 1 best wav per id (median size, 50k-5M).

Run:
  .\\.venv\\Scripts\\python.exe convert_vox_to_clone.py --dry-run
  .\\.venv\\Scripts\\python.exe convert_vox_to_clone.py --limit 50
  .\\.venv\\Scripts\\python.exe convert_vox_to_clone.py
  .\\.venv\\Scripts\\python.exe convert_vox_to_clone.py --force
Requires ffmpeg on PATH.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

IN_DIR = Path(r"D:\Temp\voxceleb\wav")
OUT_DIR = Path(r"D:\!!Scripts!!\Samples_Clone")
FFMPEG = shutil.which("ffmpeg") or r"C:\Users\BoBo\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"

def pick_best(id_dir: Path) -> Path | None:
    wavs = [p for p in id_dir.rglob("*.wav") if p.is_file() and p.name != "output_quick_test.wav"]
    wavs = [p for p in wavs if 50_000 < p.stat().st_size < 5_000_000]
    if not wavs: return None
    wavs.sort(key=lambda p: p.stat().st_size, reverse=True)
    return wavs[len(wavs)//3] if len(wavs) > 3 else wavs[0]

def convert(src: Path, dst: Path) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(src), "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", "-t", "15", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ffmpeg fail {src.name}: {r.stderr[:200]}", file=sys.stderr)
        return False
    return True

def main() -> int:
    p = argparse.ArgumentParser(description="voxceleb -> Samples_Clone normalize 24k mono")
    p.add_argument("--in", dest="indir", default=str(IN_DIR))
    p.add_argument("--out", dest="outdir", default=str(OUT_DIR))
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    in_dir, out_dir = Path(args.indir), Path(args.outdir)
    if not in_dir.exists():
        print(f"in not found: {in_dir}", file=sys.stderr); return 2
    if not Path(FFMPEG).exists() and not shutil.which("ffmpeg"):
        print("ffmpeg not found", file=sys.stderr); return 2
    ids = sorted([d for d in in_dir.iterdir() if d.is_dir() and d.name.startswith("id")], key=lambda p: p.name)
    if args.limit: ids = ids[:args.limit]
    todo: list[tuple[Path, Path]] = []
    for id_dir in ids:
        dst = out_dir / f"{id_dir.name}.wav"
        if dst.exists() and not args.force: continue
        best = pick_best(id_dir)
        if best is None: continue
        todo.append((best, dst))
    print(f"ids total {len(ids)}  to-convert {len(todo)}  out {out_dir}")
    if args.dry_run:
        for s,d in todo[:20]: print(f"  {s.parent.name}/{s.name} -> {d.name} ({s.stat().st_size} -> 24k)")
        if len(todo) > 20: print(f"  ... +{len(todo)-20}")
        return 0
    ok = skip = fail = 0
    for src, dst in todo:
        txt_src = src.with_suffix(".txt")
        txt_dst = dst.with_suffix(".txt")
        if convert(src, dst):
            ok += 1
            if txt_src.exists() and txt_src.stat().st_size > 0:
                try: txt_dst.write_text(txt_src.read_text(encoding="utf-8", errors="replace").strip(), encoding="utf-8")
                except: pass
            elif not txt_dst.exists():
                txt_dst.write_text("", encoding="utf-8")
            if ok % 100 == 0: print(f"  ... {ok}/{len(todo)}")
        else:
            fail += 1
    print(f"Done: ok={ok} fail={fail} skipped={len(ids)-len(todo)}  Samples_Clone now has {len(list(out_dir.glob('*.wav')))} wav")
    return 1 if fail else 0

if __name__ == "__main__":
    raise SystemExit(main())

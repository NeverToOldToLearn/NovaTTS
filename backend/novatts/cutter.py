"""Perfect Cut — WAV cutter backend (ffmpeg resolution, config, export).

Backs the standalone "Perfect Cut" tool window (``gui/src/lib/cutter/``).
The window is a Tauri webview, so everything that needs a real filesystem
path or a subprocess lives here. What stays in the frontend: WAV decoding,
waveform/loudness rendering, playback and silence detection — all of which
the Web Audio API already does without a single extra dependency.

Config is persisted to ``data/perfect_cut.json`` — the same convention as
the rest of the app's domain state (``speakers.json``, ``blacklist.json``).
"""

from __future__ import annotations

import array
import json
import logging
import shutil
import subprocess
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import settings

log = logging.getLogger(__name__)

# --- external tool resolution -------------------------------------------------
# Same candidate-list + exists() + `shutil.which` fallback idiom as
# qwen_manager: an explicit setting always wins, then well-known install
# locations, then PATH.

FFMPEG_CANDIDATES = [
    r"C:\Users\BoBo\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe",
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
]

WHISPER_EXE_CANDIDATES = [
    r"C:\whisper.cpp\build\bin\Release\whisper-cli.exe",
    r"C:\whisper.cpp\build\bin\Release\main.exe",
    r"C:\whisper.cpp\main.exe",
]

WHISPER_MODEL_CANDIDATES = [
    r"C:\whisper.cpp\models\ggml-large-v3-turbo.bin",
    r"C:\whisper.cpp\models\ggml-large-v3.bin",
]

WHISPER_MODEL_DEFAULT = WHISPER_MODEL_CANDIDATES[0]

# Qwen3TTS reference format: 24 kHz mono PCM16, loudness-normalised.
QWEN_SAMPLE_RATE = 24000
LOUDNORM_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"

# silenceremove/loudnorm recipe for the batch cleaner (from VoiceClonePrep).
BATCH_CLEAN_FILTER = "silenceremove=start_periods=1:start_silence=0.05:start_threshold=-40dB,loudnorm"


def _first_existing(candidates: list[str], name: str) -> str:
    """First candidate that exists on disk, else the PATH lookup, else the last."""
    for p in candidates:
        if p and Path(p).is_file():
            return p
    found = shutil.which(name)
    return found if found else candidates[-1]


def resolve_ffmpeg() -> str:
    return _first_existing(FFMPEG_CANDIDATES, "ffmpeg")


def resolve_whisper_exe() -> str:
    return _first_existing(WHISPER_EXE_CANDIDATES, "whisper-cli")


def resolve_whisper_model() -> str:
    return _first_existing(WHISPER_MODEL_CANDIDATES, "ggml-large-v3-turbo.bin")


def probe_tool(path: str, version_args: list[str]) -> tuple[bool, str]:
    """Run ``path`` with a version flag. Returns (ok, one-line message)."""
    if not path or not Path(path).is_file():
        return False, f"not found: {path or '(empty)'}"
    try:
        proc = subprocess.run(
            [path, *version_args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"failed to run: {exc}"
    first = (proc.stdout or proc.stderr or "").strip().splitlines()
    return proc.returncode == 0, (first[0] if first else f"exit {proc.returncode}")


# --- config -------------------------------------------------------------------


@dataclass
class CutterConfig:
    """Persisted tool settings. Mirrors the old ``cutter_config.json``."""

    input_dir: str = ""
    output_dir: str = ""
    whisper_exe: str = ""
    whisper_model: str = ""
    ffmpeg: str = ""
    lang: str = "en"
    qwen_preset: bool = True
    keep_sr: bool = False
    snap: bool = False
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls) -> CutterConfig:
        """Read the config file, filling anything missing with auto-detected paths."""
        raw: dict[str, Any] = {}
        try:
            path = Path(settings.perfect_cut_config)
            if path.is_file():
                parsed = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    raw = parsed
        except (OSError, ValueError) as exc:
            log.warning("Perfect Cut config unreadable, using defaults: %s", exc)

        known = {f for f in cls.__dataclass_fields__ if f != "extras"}
        kwargs = {k: v for k, v in raw.items() if k in known}
        extras = {k: v for k, v in raw.items() if k not in known}
        cfg = cls(**kwargs)
        cfg.extras = extras
        if not cfg.ffmpeg:
            cfg.ffmpeg = resolve_ffmpeg()
        if not cfg.whisper_exe:
            cfg.whisper_exe = resolve_whisper_exe()
        if not cfg.whisper_model:
            cfg.whisper_model = resolve_whisper_model()
        return cfg

    def save(self) -> None:
        path = Path(settings.perfect_cut_config)
        payload = asdict(self)
        extras = payload.pop("extras", {})
        payload.update(extras if isinstance(extras, dict) else {})
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            log.warning("Perfect Cut config not saved: %s", exc)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("extras", None)
        return data


# --- export -------------------------------------------------------------------

EXPORT_MODES = ("qwen", "native", "keep")


def _ffmpeg_cmd(
    ffmpeg: str,
    src: Path,
    out: Path,
    start: float,
    end: float,
    mode: str,
) -> list[str]:
    """Build the ffmpeg argv.

    ``-ss``/``-to`` deliberately come *after* ``-i``: output seeking decodes
    from the start, which is slower but sample-accurate — the whole point of
    this tool.
    """
    cmd = [ffmpeg, "-y", "-i", str(src), "-ss", f"{start:.6f}", "-to", f"{end:.6f}"]
    if mode == "qwen":
        cmd += ["-af", LOUDNORM_FILTER, "-ar", str(QWEN_SAMPLE_RATE), "-ac", "1"]
    elif mode == "native":
        cmd += ["-ar", str(QWEN_SAMPLE_RATE), "-ac", "1"]
    cmd += ["-c:a", "pcm_s16le", str(out)]
    return cmd


def _wav_fallback_cut(src: Path, out: Path, start: float, end: float, mode: str) -> None:
    """Dependency-free PCM cut for when ffmpeg is unavailable.

    ``wave`` is stdlib, so this keeps the tool usable on a machine without
    ffmpeg. Sample-accurate, but no loudness normalisation and no resampling
    above the stdlib's linear interp — fine for the short selections a cut is.
    """
    target_rate = 0 if mode == "keep" else QWEN_SAMPLE_RATE
    with wave.open(str(src), "rb") as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        total = w.getnframes()
        first = max(0, min(total, int(start * rate)))
        last = max(first, min(total, int(end * rate)))
        w.setpos(first)
        frames = w.readframes(last - first)
        out_rate = rate
        out_channels = channels

    if width != 2:
        raise RuntimeError(f"fallback cut needs 16-bit PCM, got {width * 8}-bit")

    samples = array.array("h")
    samples.frombytes(frames)

    if mode != "keep" and channels > 1:
        samples = _downmix_mono(samples, channels)
        out_channels = 1

    if target_rate and target_rate != out_rate:
        samples = _linear_resample(samples, out_rate, target_rate)
        out_rate = target_rate

    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(out_channels)
        w.setsampwidth(2)
        w.setframerate(out_rate)
        w.writeframes(samples.tobytes())


def _downmix_mono(samples: array.array[int], channels: int) -> array.array[int]:
    """Average interleaved channels down to one (16-bit, wrapping on overflow)."""
    frames = len(samples) // channels
    out = array.array("h", bytes(2 * frames))
    for f in range(frames):
        base = f * channels
        total = sum(samples[base : base + channels])
        out[f] = max(-32768, min(32767, total // channels))
    return out


def _linear_resample(samples: array.array[int], src_rate: int, dst_rate: int) -> array.array[int]:
    """Linear-interpolate resample of 16-bit mono samples."""
    n = len(samples)
    if n == 0 or src_rate == dst_rate:
        return samples
    out_len = max(1, int(n * dst_rate / src_rate))
    step = (n - 1) / (out_len - 1) if out_len > 1 else 0.0
    out = array.array("h", bytes(2 * out_len))
    for i in range(out_len):
        pos = i * step
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        val = samples[lo] * (1.0 - frac) + samples[hi] * frac
        out[i] = max(-32768, min(32767, int(round(val))))
    return out


def export_cut(
    *,
    src: str,
    out: str,
    start: float,
    end: float,
    mode: str = "qwen",
    ffmpeg: str | None = None,
) -> dict[str, Any]:
    """Cut ``[start, end)`` out of ``src`` and write a WAV to ``out``.

    ``mode``: ``qwen`` (24 kHz mono PCM16 + loudnorm), ``native`` (24 kHz mono
    PCM16, no normalisation) or ``keep`` (original rate/channels).
    """
    if mode not in EXPORT_MODES:
        raise ValueError(f"unknown export mode {mode!r}")
    src_path = Path(src).expanduser()
    out_path = Path(out).expanduser()
    if not src_path.is_file():
        raise FileNotFoundError(f"source not found: {src_path}")
    if end <= start:
        raise ValueError("end must be greater than start")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    exe = ffmpeg or resolve_ffmpeg()
    used = "ffmpeg"
    cmd: list[str] = []
    if exe and Path(exe).is_file():
        cmd = _ffmpeg_cmd(exe, src_path, out_path, start, end, mode)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                if mode == "qwen":
                    # loudnorm rejects some inputs (e.g. already-normalised or
                    # mono-corrupt files) — retry without the filter rather
                    # than losing the cut.
                    log.warning("loudnorm failed, retrying without it: %s", (proc.stderr or "")[-300:])
                    cmd = _ffmpeg_cmd(exe, src_path, out_path, start, end, "native")
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if proc.returncode != 0:
                    raise RuntimeError((proc.stderr or "ffmpeg failed")[-800:])
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("ffmpeg unusable (%s) — falling back to the stdlib cutter", exc)
            cmd = []
    else:
        log.warning("ffmpeg not found at %r — using the stdlib WAV cutter", exe)

    if not cmd:
        used = "stdlib"
        _wav_fallback_cut(src_path, out_path, start, end, mode)

    if not out_path.is_file():
        raise RuntimeError(f"output not written: {out_path}")

    with wave.open(str(out_path), "rb") as w:
        info = {
            "rate": w.getframerate(),
            "channels": w.getnchannels(),
            "duration": w.getnframes() / float(w.getframerate()),
        }
    log.info("Perfect Cut export: %s -> %s (%s, %.2fs)", src_path.name, out_path.name, used, info["duration"])
    return {"out": str(out_path), "via": used, "cmd": cmd, **info}

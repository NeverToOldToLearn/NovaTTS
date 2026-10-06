"""Voice-design synthesis via the standalone ``qwen-tts`` CLI.

The voice-design checkpoint (``qwen-talker-1.7b-voicedesign-*.gguf``, 1.7B
only) creates a voice from a free-text attribute instruction (``--instruct``)
instead of a reference sample. This deliberately bypasses the running
``tts-server`` (which serves the base model): each design job spawns
``qwen-tts.exe`` once, writes one WAV, and exits — so the base engine keeps
running untouched.

Output lands in ``settings.voice_design_dir`` and can be auditioned from the
GUI, then promoted into the clone samples dir (``POST /voice-design/promote``)
to become a regular cloneable voice.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)

LANGUAGES = [
    "auto",
    "Chinese",
    "English",
    "Japanese",
    "Korean",
    "German",
    "French",
    "Russian",
    "Portuguese",
    "Spanish",
    "Italian",
]

_lock = threading.Lock()
_running = False


def resolve_tts_bin() -> Path:
    """qwen-tts CLI binary: explicit setting or sibling of tts-server."""
    if settings.qwen_tts_bin.strip():
        return Path(settings.qwen_tts_bin)
    qwen_bin = Path(settings.qwen_bin) if settings.qwen_bin else Path()
    sibling = qwen_bin.parent / "qwen-tts.exe"
    if sibling.is_file():
        return sibling
    # Same stem, other extension/layouts (unix build next to a windows path).
    for cand in (
        qwen_bin.parent / "qwen-tts",
        qwen_bin.parent / "qwen-tts.exe",
        Path(r"D:\Projects\qwentts.cpp\build\Release\qwen-tts.exe"),
    ):
        if cand.is_file():
            return cand
    return sibling


def resolve_design_model() -> Path:
    """Voicedesign GGUF: explicit setting or same dir as the base model."""
    if settings.qwen_voicedesign_model.strip():
        p = Path(settings.qwen_voicedesign_model)
        if p.is_file():
            return p
        # Fall through to sibling guess so status can report both candidates.
    base = Path(settings.qwen_model) if settings.qwen_model else Path()
    for cand in (
        base.parent / "qwen-talker-1.7b-voicedesign-Q8_0.gguf",
        Path(r"E:\LLM's\Qwen3TTS\qwen-talker-1.7b-voicedesign-Q8_0.gguf"),
    ):
        if cand.is_file():
            return cand
    return Path(settings.qwen_voicedesign_model) if settings.qwen_voicedesign_model else base.parent


def out_dir() -> Path:
    d = Path(settings.voice_design_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def status() -> dict[str, object]:
    tts = resolve_tts_bin()
    model = resolve_design_model()
    codec = Path(settings.qwen_codec) if settings.qwen_codec else Path()
    d = Path(settings.voice_design_dir)
    return {
        "enabled": settings.voice_design_enabled,
        "tts_bin": str(tts),
        "model": str(model),
        "codec": str(codec),
        "out_dir": str(d),
        "tts_exists": tts.is_file(),
        "model_exists": model.is_file(),
        "codec_exists": codec.is_file(),
        "out_exists": d.exists(),
        "busy": _running,
        "languages": LANGUAGES,
    }


def _safe_stem(name: str, fallback: str = "voice") -> str:
    stem = re.sub(r"[^A-Za-z0-9.@_-]+", "_", (name or "").strip()).strip("._")[:80]
    return stem or fallback


def list_files() -> list[dict[str, object]]:
    d = Path(settings.voice_design_dir)
    if not d.exists():
        return []
    rows: list[dict[str, object]] = []
    for p in sorted(d.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            st = p.stat()
        except OSError:
            continue
        rows.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime})
    return rows


def is_busy() -> bool:
    return _running


def generate(
    *,
    text: str,
    instruct: str,
    language: str = "auto",
    seed: int = -1,
    temperature: float = 0.9,
    top_k: int = 50,
    top_p: float = 1.0,
    save_name: str = "",
    timeout: float = 600.0,
) -> Path:
    """Run one voice-design synthesis, return the WAV path. Raises on failure."""
    global _running
    text = (text or "").strip()
    instruct = (instruct or "").strip()
    if not text:
        raise ValueError("Text is leeg — vul de te spreken zin in.")
    if not instruct:
        raise ValueError("Stem-beschrijving (instruct) is leeg — beschrijf de stem.")
    lang = (language or "auto").strip() or "auto"
    if lang not in LANGUAGES:
        raise ValueError(f"Onbekende taal: {lang!r} (kies uit {', '.join(LANGUAGES)})")

    tts = resolve_tts_bin()
    model = resolve_design_model()
    codec = Path(settings.qwen_codec) if settings.qwen_codec else Path()
    if not tts.is_file():
        raise FileNotFoundError(f"qwen-tts binary niet gevonden: {tts}")
    if not model.is_file():
        raise FileNotFoundError(f"voicedesign-model niet gevonden: {model}")
    if not codec.is_file():
        raise FileNotFoundError(f"codec niet gevonden: {codec}")

    with _lock:
        if _running:
            raise RuntimeError("Er loopt al een voice-design job — wacht tot die klaar is.")
        _running = True
    try:
        d = out_dir()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        stem = _safe_stem(save_name, f"design-{stamp}")
        target = d / f"{stem}.wav"
        if target.exists():
            target = d / f"{stem}-{stamp}.wav"

        cmd = [
            str(tts),
            "--model", str(model),
            "--codec", str(codec),
            "--instruct", instruct,
            "--lang", lang,
            "--seed", str(int(seed)),
            "--temp", str(float(temperature)),
            "--top-k", str(int(top_k)),
            "--top-p", str(float(top_p)),
            "-o", str(target),
        ]
        log.info("Voice-design: %s", " ".join(cmd[:8]) + " ...")
        try:
            proc = subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Voice-design time-out na {timeout:.0f}s") from exc
        if proc.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()[-800:]
            if target.is_file() and target.stat().st_size == 0:
                target.unlink(missing_ok=True)
            raise RuntimeError(f"qwen-tts faalde (code {proc.returncode}): {err or 'geen stderr'}")
        log.info("Voice-design klaar: %s (%d bytes)", target.name, target.stat().st_size)
        return target
    finally:
        with _lock:
            _running = False


def delete_file(name: str) -> bool:
    p = out_dir() / _safe_stem(name)
    if p.suffix.lower() != ".wav":
        p = p.with_suffix(".wav")
    if not p.is_file():
        return False
    # Never allow path escape.
    if p.resolve().parent != out_dir().resolve():
        raise ValueError("Ongeldige bestandsnaam")
    p.unlink()
    return True


def promote_to_samples(src_name: str, voice_name: str) -> dict[str, object]:
    """Copy a design WAV into the clone samples dir as <voice_name>.wav."""
    from .tts.qwen import Qwen3Backend

    src = out_dir() / _safe_stem(src_name)
    if src.suffix.lower() != ".wav":
        src = src.with_suffix(".wav")
    if src.resolve().parent != out_dir().resolve() or not src.is_file():
        raise FileNotFoundError(f"Design-bestand niet gevonden: {src_name}")
    stem = _safe_stem(voice_name)
    if not stem:
        raise ValueError("Geef een stem-naam op om te promoten.")
    dest_dir = Path(settings.qwen_samples_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{stem}.wav"
    if dest.exists():
        raise FileExistsError(f"{dest.name} bestaat al in de samples-map — kies een andere naam.")
    dest.write_bytes(src.read_bytes())
    registered: bool | None = None
    try:
        qb = Qwen3Backend()
        if qb.is_available():
            from .tts.spk_rvq import register_sample

            register_sample(qb, dest)
            registered = True
        else:
            registered = False
    except Exception as exc:
        log.warning("Promoted sample kon niet direct geregistreerd worden: %s", exc)
        registered = False
    return {"src": src.name, "dest": str(dest), "voice": stem, "registered": registered}


def render_speed(src_name: str, speed: float) -> Path:
    """Bewaar een design-WAV op gehoorde afspeelsnelheid als nieuw bestand.

    Doet exact wat de browser-``playbackRate`` doet bij het afluisteren:
    sneller/langzamer mét meeschuivende toonhoogte (tape-gedrag), via
    lineaire-interpolatie resampling in de stdlib — geen ffmpeg nodig.
    ``speed > 1`` = sneller/hoger, ``< 1`` = langzamer/lager.
    """
    import array
    import wave

    if not 0.25 <= float(speed) <= 2.0:
        raise ValueError(f"Snelheid moet tussen 0.25 en 2.0 liggen (kreeg {speed})")
    speed = float(speed)

    src = out_dir() / _safe_stem(src_name)
    if src.suffix.lower() != ".wav":
        src = src.with_suffix(".wav")
    if src.resolve().parent != out_dir().resolve() or not src.is_file():
        raise FileNotFoundError(f"Design-bestand niet gevonden: {src_name}")

    with wave.open(str(src), "rb") as w:
        n = w.getnframes()
        params = w.getparams()
        raw = w.readframes(n)
    if params.sampwidth != 2:
        raise ValueError(f"Alleen 16-bit WAV ondersteund (kreeg {params.sampwidth * 8}-bit)")
    if n < 16:
        raise ValueError("Bestand is te kort om te resamplen.")

    channels = params.nchannels
    total = n * channels
    samples = array.array("h", raw)
    if len(samples) < total:
        samples.extend([0] * (total - len(samples)))
    new_n = max(1, round(n / speed))
    out = array.array("h")
    for i in range(new_n):
        pos = i * speed
        i0 = int(pos)
        frac = pos - i0
        i1 = i0 + 1 if i0 + 1 < n else i0
        for ch in range(channels):
            a = samples[i0 * channels + ch]
            b = samples[i1 * channels + ch]
            out.append(int(a + (b - a) * frac))

    stem = src.stem
    tag = f"{speed:g}x".replace(".", "p")
    target = out_dir() / f"{stem}@{tag}.wav"
    if target.exists():
        target = out_dir() / f"{stem}@{tag}-{time.strftime('%H%M%S')}.wav"
    with wave.open(str(target), "wb") as w:
        w.setparams(params)
        w.setnframes(new_n)
        w.writeframes(out.tobytes())
    log.info("Voice-design snelheid: %s @%gx -> %s", src.name, speed, target.name)
    return target

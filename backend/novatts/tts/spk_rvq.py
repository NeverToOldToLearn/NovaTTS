"""Pre-extracted .spk/.rvq voice references for the qwentts.cpp engine.

``qwen-codec.exe`` can extract a speaker embedding (``.spk``) and the
packed speech tokens (``.rvq``) once, ahead of time, from a sample WAV.
The tts-server then accepts these latents verbatim via
``{name, spk_b64, rvq_b64}`` — no GPU work at registration time, so
importing a large samples dir at server start is just a batch of base64
uploads instead of one extraction per voice.

NovaTTS prefers such pairs when importing the samples dir and falls back
to ``wav_b64`` (server-side extraction) for samples that were never
pre-converted. The converter mirrors Convert-WavToSpkRvq.ps1.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import settings

log = logging.getLogger(__name__)

SPK_EXT = ".spk"
RVQ_EXT = ".rvq"

# Same filter as the sample import: skip the on-the-fly quick-test file
# and oversized captures.
MAX_SAMPLE_BYTES = 5_000_000


def codec_bin_path() -> Path:
    """Resolve qwen-codec.exe (explicit setting, else sibling of tts-server.exe)."""
    if settings.qwen_codec_bin.strip():
        return Path(settings.qwen_codec_bin)
    return Path(settings.qwen_bin).with_name("qwen-codec.exe")


@dataclass(frozen=True)
class VoiceRef:
    """A pre-extracted .spk/.rvq pair with its optional reference transcript."""

    wav: Path
    spk: Path
    rvq: Path
    txt: Path | None

    @property
    def name(self) -> str:
        return self.wav.stem

    def ref_text(self) -> str:
        if self.txt is None or not self.txt.exists():
            return ""
        try:
            return self.txt.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""


def voice_ref_for(wav: Path) -> VoiceRef | None:
    """Return the pair next to ``wav``, or None when either file is missing."""
    spk = wav.with_suffix(SPK_EXT)
    rvq = wav.with_suffix(RVQ_EXT)
    if not (spk.is_file() and rvq.is_file()):
        return None
    txt = wav.with_suffix(".txt")
    return VoiceRef(wav, spk, rvq, txt if txt.is_file() else None)


def collect_wavs(src: Path) -> list[Path]:
    """All candidate sample WAVs in ``src`` (top level, same filter as import)."""
    out: list[Path] = []
    for w in sorted(src.glob("*.wav"), key=lambda p: p.name.lower()):
        if w.is_file() and w.name != "output_quick_test.wav" and w.stat().st_size < MAX_SAMPLE_BYTES:
            out.append(w)
    return out


def unpaired_wavs(src: Path, wavs: list[Path] | None = None) -> list[Path]:
    """WAVs without a complete .spk+.rvq pair yet."""
    return [w for w in (wavs if wavs is not None else collect_wavs(src)) if voice_ref_for(w) is None]


def convert_pair(wav: Path) -> None:
    """Run qwen-codec.exe to extract .spk/.rvq next to ``wav``.

    Requires the codec + talker GGUF files — the same models tts-server
    loads, so the latents match what the server would extract itself.
    Raises on missing binaries/models or a non-zero exit.
    """
    bin_path = codec_bin_path()
    if not bin_path.exists():
        raise FileNotFoundError(f"qwen-codec.exe not found: {bin_path}")
    codec_model = settings.qwen_codec
    talker_model = settings.qwen_model
    if not codec_model or not Path(codec_model).exists():
        raise FileNotFoundError(f"codec model not found: {codec_model}")
    if not talker_model or not Path(talker_model).exists():
        raise FileNotFoundError(f"talker model not found: {talker_model}")

    cmd = [str(bin_path), "--model", codec_model, "--talker", talker_model, "-i", str(wav)]
    log.info("qwen-codec: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"qwen-codec timed out for {wav.name}") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-400:]
        raise RuntimeError(f"qwen-codec exit {proc.returncode}: {tail}")
    if voice_ref_for(wav) is None:
        raise RuntimeError(f"qwen-codec produced no .spk/.rvq for {wav.name}")


def convert_samples_dir(src: Path, *, force: bool = False) -> dict[str, object]:
    """Pre-extract .spk/.rvq for wavs that lack a pair (or all, with force)."""
    wavs = collect_wavs(src)
    todo = wavs if force else unpaired_wavs(src, wavs)
    skipped = len(wavs) - len(todo)
    converted = 0
    errors: list[str] = []
    for wav in todo:
        try:
            convert_pair(wav)
            converted += 1
        except Exception as exc:
            errors.append(f"{wav.name}: {exc}")
            log.warning("Pre-extract failed for %s: %s", wav.name, exc)
    return {
        "converted": converted,
        "skipped": skipped,
        "failed": len(errors),
        "total": len(wavs),
        "errors": errors[:20],
    }


def register_sample(backend: Any, wav: Path) -> None:
    """Register one sample, preferring its pre-extracted .spk/.rvq pair.

    Falls back to sending the raw WAV (server-side extraction) when no
    pair exists yet, so a never-converted sample still works.
    """
    ref = voice_ref_for(wav)
    if ref is not None:
        backend.register_voice(
            ref.name,
            ref_text=ref.ref_text(),
            spk_bytes=ref.spk.read_bytes(),
            rvq_bytes=ref.rvq.read_bytes(),
        )
        return
    txt = wav.with_suffix(".txt")
    ref_text = txt.read_text(encoding="utf-8", errors="replace").strip() if txt.exists() else ""
    backend.register_voice(wav.stem, wav.read_bytes(), ref_text=ref_text)

"""Pre-extracted .spk/.rvq voice references for the qwentts.cpp engine.

``qwen-codec.exe`` can extract a speaker embedding (``.spk``) and the
packed speech tokens (``.rvq``) once, ahead of time, from a sample WAV.
The tts-server then accepts these latents verbatim via
``{name, spk_b64, rvq_b64}`` — no GPU work at registration time, so
importing a large samples dir at server start is just a batch of base64
uploads instead of one extraction per voice.

Pairs are discovered from the ``.spk`` files themselves — a pair stays
importable even after the source ``.wav`` is deleted. WAVs without a
pair fall back to ``wav_b64`` (server-side extraction). The converter
mirrors Convert-WavToSpkRvq.ps1.
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
TXT_EXT = ".txt"

# Same filter as the sample import: skip the on-the-fly quick-test file
# and oversized captures.
MAX_SAMPLE_BYTES = 5_000_000
QUICK_TEST_STEM = "output_quick_test"


def codec_bin_path() -> Path:
    """Resolve qwen-codec.exe (explicit setting, else sibling of tts-server.exe)."""
    if settings.qwen_codec_bin.strip():
        return Path(settings.qwen_codec_bin)
    return Path(settings.qwen_bin).with_name("qwen-codec.exe")


@dataclass(frozen=True)
class VoiceRef:
    """A pre-extracted .spk/.rvq pair with its optional reference transcript."""

    spk: Path
    rvq: Path
    txt: Path | None

    @property
    def name(self) -> str:
        return self.spk.stem

    def ref_text(self) -> str:
        if self.txt is None or not self.txt.exists():
            return ""
        try:
            return self.txt.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""


def _voice_ref(spk: Path, rvq: Path) -> VoiceRef | None:
    """Build a VoiceRef when both latent files exist."""
    if not (spk.is_file() and rvq.is_file()):
        return None
    txt = spk.with_suffix(TXT_EXT)
    return VoiceRef(spk, rvq, txt if txt.is_file() else None)


def voice_ref_for(wav: Path) -> VoiceRef | None:
    """Pair normally generated for a wav: <base>.spk + <base>.rvq."""
    return _voice_ref(wav.with_suffix(SPK_EXT), wav.with_suffix(RVQ_EXT))


def collect_pairs(src: Path) -> list[VoiceRef]:
    """All complete .spk+.rvq pairs — independent of whether the source
    .wav still exists. A pair with either latent missing is skipped."""
    out: list[VoiceRef] = []
    for spk in sorted(src.glob(f"*{SPK_EXT}"), key=lambda p: p.name.lower()):
        if spk.stem == QUICK_TEST_STEM:
            continue
        ref = _voice_ref(spk, spk.with_suffix(RVQ_EXT))
        if ref is not None:
            out.append(ref)
    return out


def collect_wavs(src: Path, *, include_paired: bool = False) -> list[Path]:
    """Candidate sample WAVs left to handle in ``src``.

    By default only wavs WITHOUT a complete pair are returned (those are
    the ones that still need server-side extraction). Pass
    ``include_paired=True`` for the full list (e.g. force re-extract).
    """
    out: list[Path] = []
    for w in sorted(src.glob("*.wav"), key=lambda p: p.name.lower()):
        if not (w.is_file() and w.name != f"{QUICK_TEST_STEM}.wav" and w.stat().st_size < MAX_SAMPLE_BYTES):
            continue
        if include_paired or voice_ref_for(w) is None:
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
    all_wavs = collect_wavs(src, include_paired=True)
    todo = all_wavs if force else unpaired_wavs(src, all_wavs)
    skipped = len(all_wavs) - len(todo)
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
        "total": len(all_wavs),
        "errors": errors[:20],
    }


def register_pair(backend: Any, ref: VoiceRef) -> None:
    """Register a pre-extracted pair verbatim — no GPU work server side."""
    backend.register_voice(
        ref.name,
        ref_text=ref.ref_text(),
        spk_bytes=ref.spk.read_bytes(),
        rvq_bytes=ref.rvq.read_bytes(),
    )


def register_sample(backend: Any, wav: Path) -> None:
    """Register a wav that has NO pair, via server-side extraction."""
    txt = wav.with_suffix(TXT_EXT)
    ref_text = txt.read_text(encoding="utf-8", errors="replace").strip() if txt.exists() else ""
    backend.register_voice(wav.stem, wav.read_bytes(), ref_text=ref_text)

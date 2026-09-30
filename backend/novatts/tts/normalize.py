"""Peak-normalize synthesized WAVs so every voice plays at one level.

Qwen's output level varies per voice and per line -- measured F19 on the live
cache: 13 files, peaks 0.16-0.65, median 0.39 -- while the game mix stays put.
So a timid line is a quiet *file*, not a quiet player, and there is no volume
knob anywhere in the backend (measured: no ``set_volume`` call exists) that
could fix per-line differences anyway. Each file is levelled to a target peak
right after synthesis, and on cache hits too, so old quiet files do not
survive behind their hash.

Only PCM WAVs the stdlib understands are touched. The bytes come straight
from the tts-server HTTP response, so anything else -- a future server format
included -- is left alone instead of raising: a loudness fix must never break
playback.
"""

from __future__ import annotations

import array
import logging
import wave
from pathlib import Path

log = logging.getLogger(__name__)

# Full-scale divisor per sample width. 8-bit PCM is unsigned, the rest signed.
_WIDTHS: dict[int, tuple[float, int]] = {1: (128.0, 128), 2: (32768.0, 0), 4: (2147483648.0, 0)}


def _peak(samples: array.array[int], divisor: float, offset: int) -> float:
    peak = 0.0
    for value in samples:
        magnitude = abs(value - offset) / divisor
        if magnitude > peak:
            peak = magnitude
    return peak


def _read_24bit(raw: bytes) -> array.array[int]:
    out = array.array("i")
    for i in range(0, len(raw) - 2, 3):
        chunk = raw[i : i + 3]
        signed = int.from_bytes(chunk, "little", signed=False)
        if signed & 0x800000:
            signed -= 0x1000000
        out.append(signed)
    return out


def normalize_wav(
    path: str | Path,
    *,
    target_peak: float = 0.89,
    max_gain: float = 10.0,
    floor: float = 0.02,
) -> float:
    """Scale ``path`` in place so its peak hits ``target_peak``.

    Returns the applied gain; 1.0 means untouched. Never raises: silence,
    loud-enough files, missing files and non-PCM formats all return 1.0.
    ``max_gain`` caps amplification of near-silence (a lone "." blip must
    not become a loud bang); ``floor`` is the peak below which a file counts
    as silence.
    """
    wav_path = Path(path)
    try:
        with wave.open(str(wav_path), "rb") as wav:
            params = wav.getparams()
            raw = wav.readframes(wav.getnframes())
    except Exception:
        log.debug("normalize: unreadable file left alone: %s", wav_path.name)
        return 1.0
    if params.comptype != "NONE" or not raw:
        return 1.0

    width = params.sampwidth
    try:
        if width == 1:
            samples: array.array[int] = array.array("B", raw)
            divisor, offset = _WIDTHS[1]
        elif width == 2:
            samples = array.array("h", raw)
            divisor, offset = _WIDTHS[2]
        elif width == 3:
            samples = _read_24bit(raw)
            divisor, offset = 8388608.0, 0
        elif width == 4:
            samples = array.array("i", raw)
            divisor, offset = _WIDTHS[4]
        else:
            return 1.0
    except Exception:
        return 1.0

    peak = _peak(samples, divisor, offset)
    if peak < floor or peak >= target_peak:
        return 1.0
    gain = min(target_peak / peak, max_gain)
    if abs(gain - 1.0) < 0.01:
        return 1.0

    if width == 1:
        scaled = array.array("B", [max(0, min(255, round((v - offset) * gain) + offset)) for v in samples])
    elif width == 2:
        scaled = array.array("h", [max(-32768, min(32767, round(v * gain))) for v in samples])
    elif width == 3:
        scaled_ints = [max(-8388608, min(8388607, round(v * gain))) for v in samples]
        out = bytearray()
        for value in scaled_ints:
            out += (value & 0xFFFFFF).to_bytes(3, "little")
        try:
            with wave.open(str(wav_path), "wb") as wav:
                wav.setparams(params)
                wav.writeframes(bytes(out))
        except Exception:
            log.debug("normalize: rewrite failed, file left alone: %s", wav_path.name)
            return 1.0
        return gain
    else:
        scaled = array.array("i", [max(-2147483648, min(2147483647, round(v * gain))) for v in samples])
    try:
        with wave.open(str(wav_path), "wb") as wav:
            wav.setparams(params)
            wav.writeframes(scaled.tobytes())
    except Exception:
        log.debug("normalize: rewrite failed, file left alone: %s", wav_path.name)
        return 1.0
    # Channels ride along untouched: scaling is per-sample, so balance stays.
    return gain

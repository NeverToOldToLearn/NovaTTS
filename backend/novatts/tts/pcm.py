"""PCM helpers for the streaming path.

The live stream speaks s16le 24 kHz mono -- exactly what tts-server emits
for ``response_format`` pcm -- so engine chunks can be fed to the output
verbatim (up to the gain lift below). Emotion sounds live on disk as files
of any rate/width/channels and are converted here into the same shape so a
streamed line keeps its sound-then-words order without a file round trip.

Only the stdlib is used (``wave``, ``array``); numpy is deliberately not a
dependency for a few decimeters of resampling.
"""

from __future__ import annotations

import array
import logging
import math
import wave
from pathlib import Path

log = logging.getLogger(__name__)

STREAM_RATE = 24000
"""Sample rate of the live stream: tts-server pcm output, mono s16le."""


def apply_stream_gain(pcm: bytes, gain: float) -> bytes:
    """Lift raw s16le mono ``pcm`` by ``gain`` with a tanh soft limiter.

    Peak-normalize needs the whole file, so the live stream gets this
    constant lift instead (see ``settings.stream_gain``). ``gain == 1.0``
    returns the input untouched. Never raises; on corrupt input the input
    is returned as-is -- a loudness fix must not break playback.
    """
    if gain == 1.0 or not pcm:
        return pcm
    if len(pcm) & 1:
        return pcm
    try:
        src = array.array("h")
        src.frombytes(pcm)
    except Exception:
        return pcm
    try:
        out = array.array(
            "h",
            (
                max(-32768, min(32767, int(round(math.tanh((v / 32768.0) * gain) * 32767.0))))
                for v in src
            ),
        )
    except Exception:
        return pcm
    return out.tobytes()


def resample_mono_int16(samples: array.array[int], src_rate: int, dst_rate: int = STREAM_RATE) -> array.array[int]:
    """Linear-interpolated resample of mono s16 ``samples`` (stdlib only)."""
    if src_rate == dst_rate or not samples:
        return array.array("h", samples)
    n_out = max(1, int(round(len(samples) * dst_rate / src_rate)))
    if len(samples) == 1:
        return array.array("h", [samples[0]]) * n_out
    out = array.array("h")
    scale = (len(samples) - 1) / (n_out - 1) if n_out > 1 else 0.0
    for i in range(n_out):
        pos = i * scale
        lo = int(pos)
        frac = pos - lo
        hi = lo + 1 if lo + 1 < len(samples) else lo
        out.append(int(round(samples[lo] * (1.0 - frac) + samples[hi] * frac)))
    return out


def _wav_to_mono_int16(path: Path) -> tuple[array.array[int], int] | None:
    """Decode a PCM WAV file to (mono s16 samples, rate). None if unreadable."""
    try:
        with wave.open(str(path), "rb") as wav:
            params = wav.getparams()
            raw = wav.readframes(wav.getnframes())
    except Exception:
        return None
    if params.comptype != "NONE" or not raw:
        return None
    width = params.sampwidth
    nch = params.nchannels
    try:
        if width == 1:
            ints = [v - 128 for v in array.array("B", raw)]
            samples = array.array("h", [max(-32768, min(32767, v * 256)) for v in ints])
        elif width == 2:
            samples = array.array("h", raw)
            # frombytes-equivalent: array("h", raw) already decodes native
            # little-endian, which matches WAV on every platform we ship.
        elif width == 3:
            samples = array.array("h")
            for i in range(0, len(raw) - 2, 3):
                signed = int.from_bytes(raw[i : i + 3], "little", signed=False)
                if signed & 0x800000:
                    signed -= 0x1000000
                samples.append(max(-32768, min(32767, signed // 256)))
        elif width == 4:
            src = array.array("i", raw)
            samples = array.array("h", [max(-32768, min(32767, v // 65536)) for v in src])
        else:
            return None
    except Exception:
        return None
    if nch > 1:
        # Downmix strided channels to mono.
        mono = array.array("h")
        nframes = len(samples) // nch
        for f in range(nframes):
            mono.append(sum(samples[f * nch : (f + 1) * nch]) // nch)
        samples = mono
    return samples, params.framerate


def _pygame_to_mono_int16(path: Path) -> tuple[array.array[int], int] | None:
    """Decode a non-WAV file via pygame's mixer into (mono s16, rate)."""
    try:
        import pygame
    except Exception:
        return None
    try:
        init = pygame.mixer.get_init()
        if init is None:
            return None
        freq, size, ch = init
        raw = pygame.mixer.Sound(str(path)).get_raw()
    except Exception:
        return None
    try:
        if size == 8:
            ints = [v - 128 for v in array.array("B", raw)]
            samples = array.array("h", [max(-32768, min(32767, v * 256)) for v in ints])
        elif size == -16:
            samples = array.array("h", raw)
        else:
            return None
    except Exception:
        return None
    if ch > 1:
        mono = array.array("h")
        nframes = len(samples) // ch
        for f in range(nframes):
            mono.append(sum(samples[f * ch : (f + 1) * ch]) // ch)
        samples = mono
    return samples, freq


def file_to_pcm24(path: str | Path) -> bytes | None:
    """Decode an audio file to s16le 24 kHz mono bytes for stream feeding.

    WAV goes through the stdlib; anything else (ogg/mp3/opus) through the
    already-running pygame mixer. Returns None when the file cannot be
    decoded -- the caller then skips the sound instead of breaking the line.
    """
    p = Path(path)
    decoded = _wav_to_mono_int16(p) if p.suffix.lower() == ".wav" else None
    if decoded is None and p.suffix.lower() != ".wav":
        decoded = _pygame_to_mono_int16(p)
    if decoded is None:
        # Last resort: a mislabeled extension either way.
        decoded = _wav_to_mono_int16(p) or _pygame_to_mono_int16(p)
    if decoded is None:
        log.debug("stream: undecodable sound skipped: %s", p.name)
        return None
    samples, rate = decoded
    return resample_mono_int16(samples, rate).tobytes()

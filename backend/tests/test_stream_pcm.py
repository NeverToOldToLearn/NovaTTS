"""Tests for the streaming PCM helpers (no audio device needed)."""

import array
import math
import tempfile
import wave
from pathlib import Path

from novatts.player.audio import _LiveStream
from novatts.tts.pcm import STREAM_RATE, apply_stream_gain, file_to_pcm24, resample_mono_int16


def _s16(samples: list[int]) -> bytes:
    return array.array("h", samples).tobytes()


def test_gain_passthrough_at_1():
    pcm = _s16([0, 1000, -2000, 32767, -32768])
    assert apply_stream_gain(pcm, 1.0) == pcm


def test_gain_lifts_small_signal_linearly():
    # tanh(x) ~= x for small x: 0.1 * 2.0 -> tanh(0.2) of full scale.
    pcm = _s16([3277])
    out = array.array("h")
    out.frombytes(apply_stream_gain(pcm, 2.0))
    assert abs(out[0] - 6467) < 5


def test_gain_limiter_never_clips():
    pcm = _s16([32767, -32768, 30000])
    out = array.array("h")
    out.frombytes(apply_stream_gain(pcm, 10.0))
    assert all(-32768 <= v <= 32767 for v in out)
    # tanh saturates: full-scale in maps to ~full-scale out, not wrapped.
    assert out[0] > 32000
    assert out[1] < -32000


def test_gain_odd_bytes_returned_untouched():
    assert apply_stream_gain(b"\x01\x02\x03", 2.0) == b"\x01\x02\x03"


def test_resample_same_rate_passthrough():
    src = array.array("h", [1, 2, 3])
    assert resample_mono_int16(src, STREAM_RATE) == src
    assert resample_mono_int16(src, STREAM_RATE) is not src


def test_resample_constant_stays_constant():
    src = array.array("h", [1000] * 100)
    out = resample_mono_int16(src, 22050, 24000)
    assert len(out) == round(100 * 24000 / 22050)
    assert all(v == 1000 for v in out)


def _write_wav(path: Path, *, rate: int, channels: int, samples: list[int]) -> None:
    interleaved: list[int] = []
    for s in samples:
        interleaved.extend([s] * channels)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(array.array("h", interleaved).tobytes())


def test_file_to_pcm24_converts_rate_and_channels():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "snd.wav"
        _write_wav(p, rate=22050, channels=2, samples=[2000] * 2205)
        pcm = file_to_pcm24(p)
        assert pcm is not None
        out = array.array("h")
        out.frombytes(pcm)
        # 0.1s at 22050 Hz stereo -> 0.1s at 24000 Hz mono.
        assert len(out) == 2400
        assert all(v == 2000 for v in out)


def test_file_to_pcm24_missing_returns_none():
    assert file_to_pcm24(Path("does-not-exist.wav")) is None


def test_live_stream_take_splits_head():
    session = _LiveStream(prebuffer_samples=10, gain=1.0)
    session.chunks.append(_s16([1, 2, 3, 4, 5]))
    session.buffered = 5
    arr, count = session._take_locked(3)
    assert count == 3
    assert list(arr) == [1, 2, 3]
    assert session.buffered == 2
    arr, count = session._take_locked(10)
    assert count == 2
    assert list(arr) == [4, 5]
    assert session.buffered == 0
    arr, count = session._take_locked(10)
    assert count == 0


def test_live_stream_take_empty_when_aborted():
    session = _LiveStream(prebuffer_samples=10, gain=1.0)
    session.chunks.append(_s16([1, 2]))
    session.buffered = 2
    session.aborted = True
    _, count = session._take_locked(2)
    assert count == 0


def test_gain_bound_matches_config_default():
    # stream_gain=2.0 on the measured median raw peak (~0.39) lands near
    # the 0.89 normalize target without hard clipping.
    peak_in = int(0.39 * 32768)
    out = array.array("h")
    out.frombytes(apply_stream_gain(_s16([peak_in]), 2.0))
    peak_out = out[0] / 32768.0
    assert 0.6 < peak_out < 0.9
    _ = math.tanh  # keep math import honest (used inside pcm module)

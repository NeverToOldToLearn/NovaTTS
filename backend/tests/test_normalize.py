"""Tests for tts/normalize.py (F19).

Qwen's output level varies per voice and per line -- measured on the live
cache: 13 files, peaks 0.16-0.65, median 0.39. The tests below pin the fix
with synthetic wavs so no model is needed: a quiet line comes up to the
target peak, everything else is left alone, and a second pass changes nothing
(which is what makes normalizing on cache hits safe).
"""

from __future__ import annotations

import array
import wave
from pathlib import Path

import pytest

from novatts.tts.normalize import normalize_wav

TARGET = 0.89


def _write_wav(path: Path, samples: array.array[int], *, channels: int = 1,
               sampwidth: int = 2, rate: int = 24000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return path


def _sine(peak: float, n: int = 2400) -> array.array[int]:
    import math
    return array.array("h", [int(peak * 32767 * math.sin(2 * math.pi * i / 100)) for i in range(n)])


def _peak_of(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    a = array.array("h", raw)
    return max(abs(x) for x in a) / 32768.0


def test_quiet_line_comes_up_to_target(tmp_path: Path) -> None:
    p = _write_wav(tmp_path / "quiet.wav", _sine(0.20))
    gain = normalize_wav(p)
    assert gain == pytest.approx(TARGET / 0.20, rel=0.02)
    assert _peak_of(p) == pytest.approx(TARGET, rel=0.02)


def test_loud_line_is_left_alone(tmp_path: Path) -> None:
    p = _write_wav(tmp_path / "loud.wav", _sine(0.95))
    assert normalize_wav(p) == 1.0
    assert _peak_of(p) == pytest.approx(0.95, rel=0.02)


def test_silence_is_left_alone(tmp_path: Path) -> None:
    p = _write_wav(tmp_path / "silent.wav", array.array("h", [0] * 2400))
    assert normalize_wav(p) == 1.0


def test_stereo_is_normalized_as_one(tmp_path: Path) -> None:
    import math
    left = [int(0.20 * 32767 * math.sin(2 * math.pi * i / 100)) for i in range(2400)]
    right = [int(0.10 * 32767 * math.sin(2 * math.pi * i / 100)) for i in range(2400)]
    interleaved = array.array("h", [x for pair in zip(left, right, strict=True) for x in pair])
    p = _write_wav(tmp_path / "stereo.wav", interleaved, channels=2)
    normalize_wav(p)
    assert _peak_of(p) == pytest.approx(TARGET, rel=0.02)


def test_second_pass_is_a_no_op(tmp_path: Path) -> None:
    p = _write_wav(tmp_path / "twice.wav", _sine(0.20))
    normalize_wav(p)
    before = p.read_bytes()
    assert normalize_wav(p) == 1.0
    assert p.read_bytes() == before, "a file already at target must not be rewritten"


def test_garbage_file_is_left_alone(tmp_path: Path) -> None:
    p = tmp_path / "junk.wav"
    p.write_bytes(b"dit is geen wav")
    assert normalize_wav(p) == 1.0
    assert p.read_bytes() == b"dit is geen wav"


def test_missing_file_is_left_alone(tmp_path: Path) -> None:
    assert normalize_wav(tmp_path / "bestaat-niet.wav") == 1.0

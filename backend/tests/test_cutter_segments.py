"""Tests for Perfect Cut utterance segmentation (edgelock port for Dataset Prep)."""

import array
import math
import wave
from pathlib import Path

import pytest

from novatts.cutter_segments import (
    compute_rms,
    detect_utterances,
    plan_segments,
    read_mono_float,
)


def make_bursts_wav(path: Path, bursts: list[tuple[float, float]], rate: int = 24000) -> Path:
    """Mono 16-bit WAV: (tone_seconds, silence_after) bursts of 440 Hz at -6 dB."""
    samples = array.array("h")
    for tone, gap in bursts:
        n = int(rate * tone)
        for i in range(n):
            samples.append(int(16000 * math.sin(2 * math.pi * 440 * i / rate)))
        samples.extend([0] * int(rate * gap))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return path


def spans(path: Path, **kw) -> list[tuple[float, float]]:
    y, sr = read_mono_float(path)
    return plan_segments(y, sr, **kw)


def test_two_utterances_detected(tmp_path):
    wav = make_bursts_wav(tmp_path / "two.wav", [(3.0, 1.0), (3.0, 0.5)])
    segs = spans(wav, min_seg=0.5, max_seg=30.0)
    assert len(segs) == 2
    (a0, b0), (a1, b1) = segs
    assert a0 == pytest.approx(0.0, abs=0.35)
    assert b0 == pytest.approx(3.0, abs=0.6)
    assert a1 == pytest.approx(4.0, abs=0.6)
    assert b1 == pytest.approx(7.0, abs=0.6)


def test_short_fragments_merged(tmp_path):
    """Two 1 s fragments with a short gap become one segment (min_seg=3)."""
    wav = make_bursts_wav(tmp_path / "short.wav", [(1.0, 0.5), (1.0, 0.5)])
    segs = spans(wav, min_seg=3.0, max_seg=30.0)
    assert len(segs) == 1
    s, e = segs[0]
    assert s == pytest.approx(0.0, abs=0.35)
    assert e - s == pytest.approx(2.5, abs=0.6)


def test_trailing_short_tail_merges_backwards(tmp_path):
    wav = make_bursts_wav(tmp_path / "tail.wav", [(4.0, 0.8), (1.0, 0.5)])
    segs = spans(wav, min_seg=3.0, max_seg=30.0)
    assert len(segs) == 1
    assert segs[0][1] - segs[0][0] == pytest.approx(5.8, abs=0.8)


def test_long_utterance_split_at_silence(tmp_path):
    """A 14 s utterance (no interior silence) splits near its midpoint."""
    wav = make_bursts_wav(tmp_path / "long.wav", [(14.0, 1.0), (2.0, 0.5)])
    segs = spans(wav, min_seg=1.0, max_seg=12.0)
    assert len(segs) == 3
    assert all(e - s <= 12.5 for s, e in segs)
    assert all(e - s >= 1.0 for s, e in segs)
    # Coverage: first sample to last speech, no big holes.
    assert segs[0][0] == pytest.approx(0.0, abs=0.35)
    assert segs[-1][1] == pytest.approx(17.0, abs=0.8)


def test_silence_only_falls_back_to_whole_file(tmp_path):
    wav = make_bursts_wav(tmp_path / "sil.wav", [(0.0, 5.0)])
    assert spans(wav) == [(0.0, pytest.approx(5.0))]


def test_tiny_file_does_not_crash(tmp_path):
    wav = make_bursts_wav(tmp_path / "tiny.wav", [(0.1, 0.0)])
    segs = spans(wav)
    assert segs == [(0.0, pytest.approx(0.1))]


def test_detection_is_rate_independent(tmp_path):
    wav = make_bursts_wav(tmp_path / "hi.wav", [(3.0, 1.0), (3.0, 0.5)], rate=44100)
    segs = spans(wav, min_seg=0.5, max_seg=30.0)
    assert len(segs) == 2
    assert segs[0][0] == pytest.approx(0.0, abs=0.35)
    assert segs[1][1] == pytest.approx(7.0, abs=0.6)


def test_detection_finds_speech_not_tone_deaf(tmp_path):
    wav = make_bursts_wav(tmp_path / "one.wav", [(5.0, 1.0)])
    y, sr = read_mono_float(wav)
    utts = detect_utterances(compute_rms(y, sr))
    assert len(utts) == 1
    assert utts[0].start == pytest.approx(0.0, abs=0.2)
    assert utts[0].end == pytest.approx(5.0, abs=0.5)


def _bursts_24k_mono(path: Path, bursts: list[tuple[float, float]]) -> Path:
    """Same bursts, already in batch-clean format (24 kHz mono PCM16)."""
    return make_bursts_wav(path, bursts, rate=24000)


def test_plan_file_splits_when_enabled(tmp_path):
    from novatts.cutter_batch import BatchJob

    job = BatchJob()
    wav = _bursts_24k_mono(tmp_path / "two.wav", [(3.0, 1.0), (3.0, 0.5)])
    segs = job._plan_file(wav, "two", split=True, min_seg=0.5, max_seg=30.0)
    assert len(segs) == 2


def test_plan_file_whole_when_split_off(tmp_path):
    """Split off = the old whole-file behaviour, byte for byte."""
    from novatts.cutter_batch import BatchJob

    job = BatchJob()
    wav = _bursts_24k_mono(tmp_path / "two.wav", [(3.0, 1.0), (3.0, 0.5)])
    segs = job._plan_file(wav, "two", split=False, min_seg=0.5, max_seg=30.0)
    assert len(segs) == 1
    assert segs[0][0] == pytest.approx(0.0, abs=0.01)
    assert segs[0][1] == pytest.approx(7.5, abs=0.05)

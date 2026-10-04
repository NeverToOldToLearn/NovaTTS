"""Perfect Cut — utterance segmentation for Dataset Prep (edgelock port).

Tab 1 (Sample Cutter) detects utterances in the browser via
``gui/src/lib/cutter/edgelock.ts`` — itself a port of the tkinter tool's
``edgelock_snap.py``. Dataset Prep never had that: it cleaned + transcribed
whole files, so a 27 s recording became one 27 s sample and any sub-3 s
fragment stayed sub-3 s.

This module brings the same detection server-side (stdlib only: ``wave`` +
``array`` + ``math``) so the batch can split long files into utterances and
merge fragments that are too short to be useful samples:

1. RMS framing + Otsu-adaptive threshold + hangover + snap-to-silence,
   exactly like the frontend,
2. merge pass: anything shorter than ``min_seg`` joins its neighbour,
3. split pass: anything longer than ``max_seg`` is cut at its deepest
   interior silence (midpoint + zero-cross as fallback),
4. no usable boundaries at all: whole-file fallback (the old behaviour —
   never lose audio).

Thresholds are carried over 1:1 from ``edgelock.ts`` — if you retune one
side, retune the other (both files say so).
"""

from __future__ import annotations

import array
import logging
import math
import wave
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# --- thresholds (mirror gui/src/lib/cutter/edgelock.ts) ----------------------

SILENCE_DB = -38.0
RMS_WIN = 0.05
RMS_HOP = 0.025
START_SILENCE_RUN = 0.08
END_SILENCE_RUN = 0.1
START_PAD = 0.08
END_PAD = 0.13
HANGOVER_MAX = 0.28
FRICATIVE_DB = -28.0
NOISE_DB = -48.0
MIN_GAP_BOUNDARY = 0.1
MERGE_GAP = 0.22
MIN_UTT = 0.18
ZERO_CROSS_MS = 8.0

# Batch planning on top of the detection.
DEFAULT_MIN_SEG = 3.0
DEFAULT_MAX_SEG = 12.0
# Splinters below this are dropped, never transcribed (a 0.1 s blip is no
# voice sample; anything real survives the merge pass instead).
MIN_KEEP = 0.25


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


@dataclass
class Rms:
    """One 50 ms / 25 ms-hop RMS pass over a mono file."""

    t: list[float]
    """Frame start times in seconds. The last frame is anchored at the file end."""
    db: list[float]
    """Windowed RMS per frame in dBFS, clamped to [-60, 0]."""
    hop: float
    """Frame spacing in seconds (constant)."""
    duration: float


@dataclass
class Utterance:
    start: float
    end: float
    hangover: float


def read_mono_float(path: str | Path) -> tuple[list[float], int]:
    """Read a WAV as mono floats in [-1, 1] (multi-channel is averaged).

    The batch always feeds this 24 kHz mono PCM16 (its own ffmpeg output),
    but 8/24-bit PCM is handled too. Compressed or float-32 files raise a
    clear error — convert them first.
    """
    p = Path(path)
    with wave.open(str(p), "rb") as w:
        channels = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        total = w.getnframes()
        raw = w.readframes(total)
    if w.getcomptype() != "NONE":
        raise ValueError(f"{p.name}: compressed WAV ({w.getcomptype()}) not supported")

    if width == 1:
        samples = [(b - 128) / 128.0 for b in raw]
    elif width == 2:
        ints = array.array("h")
        ints.frombytes(raw)
        samples = [v / 32768.0 for v in ints]
    elif width == 3:
        samples = []
        for i in range(0, len(raw) - 2, 3):
            v = int.from_bytes(raw[i : i + 3], "little", signed=True)
            samples.append(v / 8388608.0)
    else:
        raise ValueError(f"{p.name}: {width * 8}-bit samples not supported (use 8/16/24-bit PCM)")

    if channels > 1:
        frames = len(samples) // channels
        samples = [
            sum(samples[f * channels : (f + 1) * channels]) / channels for f in range(frames)
        ]
    return samples, rate


def compute_rms(y: list[float], sr: int, win_sec: float = RMS_WIN, hop_sec: float = RMS_HOP) -> Rms:
    """Windowed RMS in dBFS, matching the tool's 50 ms / 25 ms framing."""
    win = max(1, round(sr * win_sec))
    hop = max(1, round(sr * hop_sec))
    n = len(y)
    n_frames = 1 + (n - win) // hop if n > win else 1

    total = sum(v * v for v in y[: min(win, n)])
    db: list[float] = []
    t: list[float] = []
    for f in range(n_frames):
        if f > 0:
            drop = (f - 1) * hop
            for i in range(drop, min(drop + hop, n)):
                total -= y[i] * y[i]
            enter = (f - 1) * hop + win
            for i in range(enter, min(enter + hop, n)):
                total += y[i] * y[i]
        # A file shorter than one window only ever produces a single, partial
        # frame — average over what is actually there, like the original.
        length = max(1, min(win, n - f * hop))
        rms = math.sqrt(max(total, 0.0) / length + 1e-12)
        db.append(_clamp(20 * math.log10(max(rms, 1e-6)), -60.0, 0.0))
        t.append((f * hop) / sr)
    # Anchor the last frame at the file end so a tail utterance is not cut short.
    if n_frames > 0:
        t[n_frames - 1] = n / sr
    return Rms(t=t, db=db, hop=hop / sr, duration=n / sr)


def _frame_index(t: list[float], sec: float) -> int:
    best, best_d = 0, math.inf
    for i, v in enumerate(t):
        d = abs(v - sec)
        if d < best_d:
            best_d, best = d, i
    return best


def silence_runs(
    t: list[float], db: list[float], thresh: float = SILENCE_DB
) -> list[tuple[float, float]]:
    """Contiguous runs below `thresh` dBFS."""
    runs: list[tuple[float, float]] = []
    i = 0
    n = len(db)
    while i < n:
        if db[i] < thresh:
            s = i
            while i < n and db[i] < thresh:
                i += 1
            runs.append((t[s], t[min(i, n - 1)]))
        else:
            i += 1
    return runs


def _otsu(values: list[float]) -> float:
    """Otsu's method over the dB histogram — the adaptive speech/noise split."""
    if len(values) < 10:
        return SILENCE_DB
    lo, hi = min(values), max(values)
    if hi <= lo:
        return SILENCE_DB
    bins = 64
    hist = [0] * bins
    for v in values:
        hist[_clamp(int((v - lo) / (hi - lo) * bins), 0, bins - 1)] += 1
    centers = [lo + (i + 0.5) * (hi - lo) / bins for i in range(bins)]
    total = len(values)
    sum_total = sum(h * c for h, c in zip(hist, centers))
    w_b = 0
    sum_b = 0.0
    max_var = 0.0
    thr = centers[bins >> 1]
    for i in range(bins):
        w_b += hist[i]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += hist[i] * centers[i]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        between = w_b * w_f * (m_b - m_f) ** 2
        if between > max_var:
            max_var, thr = between, centers[i]
    return thr


def _apply_hangover(rms: Rms, offset_sec: float) -> float:
    """Walk past the VAD end through decay/fricatives; stop on a rising onset."""
    t, db, hop = rms.t, rms.db, rms.hop
    if not t:
        return offset_sec
    i0 = _frame_index(t, offset_sec)
    max_f = max(1, round(HANGOVER_MAX / hop))
    end = i0
    silent_run = 0.0
    for j in range(i0 + 1, min(len(db), i0 + max_f + 1)):
        prev, cur = db[j - 1], db[j]
        if cur > prev + 3.0 and cur > FRICATIVE_DB:
            break
        if cur > FRICATIVE_DB and j - i0 > 3:
            break
        end = j
        if cur < NOISE_DB + 4:
            silent_run += hop
            if silent_run >= 0.08:
                break
        else:
            silent_run = 0.0
    return t[end]


def detect_utterances(rms: Rms) -> list[Utterance]:
    """Speech regions after thresholding, gap-closing and short-region removal."""
    t, db, hop = rms.t, rms.db, rms.hop
    if not db:
        return []
    thr = min(-28.0, max(-50.0, _otsu(db)))
    speech = [1 if v > thr else 0 for v in db]

    close_frames = max(1, round(MERGE_GAP / hop))
    min_frames = max(1, round(MIN_UTT / hop))

    # Close short gaps between two speech regions.
    i = 0
    while i < len(speech):
        if speech[i]:
            i += 1
            continue
        a = i
        while i < len(speech) and not speech[i]:
            i += 1
        if a > 0 and speech[a - 1] and i < len(speech) and i - a < close_frames:
            for k in range(a, i):
                speech[k] = 1

    # Drop speech regions that are too short to be a real utterance.
    i = 0
    while i < len(speech):
        if not speech[i]:
            i += 1
            continue
        a = i
        while i < len(speech) and speech[i]:
            i += 1
        if i - a < min_frames:
            for k in range(a, i):
                speech[k] = 0

    out: list[Utterance] = []
    i = 0
    while i < len(speech):
        if not speech[i]:
            i += 1
            continue
        a = i
        while i < len(speech) and speech[i]:
            i += 1
        end = t[min(i, len(speech) - 1)]
        out.append(Utterance(start=t[a], end=end, hangover=_apply_hangover(rms, end)))
    return out


def _retreat_if_rising(rms: Rms, cut: float, floor: float) -> float:
    """Nudge a cut backwards off a rising onset so it lands inside the pause."""
    t, db, hop = rms.t, rms.db, rms.hop
    i = _frame_index(t, cut)
    max_back = round(0.18 / hop)
    j = i
    for _ in range(max_back):
        if j <= 1 or t[j] <= floor:
            break
        rising = db[j] > db[j - 1] + 2.0 and db[j] > SILENCE_DB
        if not rising and db[j] < SILENCE_DB:
            return t[j]
        j -= 1
    lo = max(0, i - max_back)
    window = db[lo : i + 1]
    if not window:
        return cut
    best = 0
    for k in range(1, len(window)):
        if window[k] < window[best]:
            best = k
    return t[lo + best]


def snap_start(rms: Rms, onset: float) -> tuple[float, str]:
    """Snap an onset backwards into the pre-speech silence."""
    t, db, duration = rms.t, rms.db, rms.duration
    runs = [r for r in silence_runs(t, db) if r[1] - r[0] >= START_SILENCE_RUN]
    covering = next((r for r in runs if r[0] <= onset <= r[1]), None)
    if covering is not None:
        return _clamp(onset - START_PAD, covering[0], covering[1]), "start in pre-speech silence"
    before = None
    for r in runs:
        if r[1] <= onset + 0.02:
            before = r
    if before is not None and onset - before[1] <= 0.35:
        return _clamp(onset - START_PAD, before[0], before[1]), "start snapped back to silence run"
    return max(0.0, min(duration, onset - 0.02)), "start at onset (no silence)"


def snap_end(rms: Rms, offset: float, next_onset: float | None) -> tuple[float, str] | None:
    """Snap an offset forward into the sustained pause that follows.

    Returns None when there is no sentence boundary — the caller should drop
    the utterance rather than cut mid-word.
    """
    t, db, hop, duration = rms.t, rms.db, rms.hop, rms.duration
    if next_onset is not None and next_onset - offset < MIN_GAP_BOUNDARY:
        return None

    runs = [r for r in silence_runs(t, db) if r[1] - r[0] >= END_SILENCE_RUN]
    after = None
    for r in runs:
        if r[1] >= offset and r[0] <= offset + 0.85:
            after = r
            break
        if r[0] > offset and r[0] - offset <= 0.85:
            after = r
            break

    hard = next_onset - 0.04 if next_onset is not None else duration
    if after is not None:
        run_s = max(after[0], offset)
        run_e = min(after[1], hard)
        if run_e - run_s >= MIN_GAP_BOUNDARY * 0.7:
            cut = min(run_s + END_PAD, run_e)
            cut = _retreat_if_rising(rms, cut, offset)
            return max(offset, min(hard, cut)), "end in sustained pause"

    if next_onset is not None:
        gap = next_onset - offset
        if gap >= MIN_GAP_BOUNDARY:
            cut = offset + min(END_PAD, gap * 0.55)
            cut = min(cut, next_onset - 0.05)
            cut = _retreat_if_rising(rms, cut, offset)
            return max(offset, min(next_onset - 0.04, cut)), "end mid-gap before next onset"
        return None

    i0 = _frame_index(t, offset)
    need = max(2, round(END_SILENCE_RUN / hop))
    run = 0
    cut_idx = i0
    for j in range(i0, len(db)):
        if db[j] < SILENCE_DB:
            run += 1
            if run >= need:
                cut_idx = j - run + 1 + round(END_PAD / hop)
                break
        else:
            run = 0
            cut_idx = j
    return max(offset, min(duration, t[min(cut_idx, len(t) - 1)])), "end at file tail"


def zero_cross(y: list[float], sr: int, sec: float, toward_interior: int) -> float:
    """Nudge a cut to the nearest zero crossing within 8 ms, avoiding clicks."""
    max_s = round((ZERO_CROSS_MS / 1000) * sr)
    i = _clamp(round(sec * sr), 1, len(y) - 2)
    for n in range(max_s):
        j = i + toward_interior * n
        if j <= 0 or j >= len(y) - 1:
            break
        if y[j] == 0 or y[j] * y[j + toward_interior] <= 0:
            return j / sr
    return sec


def utterance_window(
    y: list[float],
    sr: int,
    rms: Rms,
    utterances: list[Utterance],
    i: int,
    j: int | None = None,
) -> tuple[float, float] | None:
    """Snapped [start, end) for utterance i (or i..j); None without boundary."""
    j = i if j is None else j
    if i < 0 or j >= len(utterances):
        return None
    first, last = utterances[i], utterances[j]
    next_onset = utterances[j + 1].start if j + 1 < len(utterances) else None
    s, _ = snap_start(rms, first.start)
    e = snap_end(rms, last.hangover, next_onset)
    if e is None:
        return None
    a = _clamp(zero_cross(y, sr, s, 1), 0.0, rms.duration)
    b = _clamp(zero_cross(y, sr, e[0], -1), a, rms.duration)
    return (a, b) if b > a else None


def _merge_short(windows: list[tuple[float, float]], min_seg: float) -> list[tuple[float, float]]:
    """Fold every window shorter than `min_seg` into a neighbour.

    Short fragments join the *next* window (speech flows forward); a trailing
    short tail joins the previous one. A lone short file keeps its single
    window — across files there is nothing sensible to merge with.
    """
    ws = sorted(windows)
    i = 0
    while i < len(ws):
        s, e = ws[i]
        if e - s >= min_seg or len(ws) == 1:
            i += 1
            continue
        if i + 1 < len(ws):
            ns, ne = ws[i + 1]
            ws[i + 1] = (min(s, ns), max(e, ne))
            del ws[i]
        else:
            ps, pe = ws[i - 1]
            ws[i - 1] = (min(ps, s), max(pe, e))
            del ws[i]
            i = max(0, i - 1)
    return ws


def _split_long(
    start: float,
    end: float,
    runs: list[tuple[float, float]],
    y: list[float],
    sr: int,
    min_seg: float,
    max_seg: float,
) -> list[tuple[float, float]]:
    """Cut a span over `max_seg` at its deepest interior silence (else midpoint)."""
    if end - start <= max_seg:
        return [(start, end)]
    inner = [
        r for r in runs
        if r[0] > start + min_seg / 2 and r[1] < end - min_seg / 2 and r[1] - r[0] >= 0.1
    ]
    if inner:
        # Longest run wins (a real pause, not a breath); ties break toward middle.
        mid = (start + end) / 2
        run = max(inner, key=lambda r: (r[1] - r[0], -abs((r[0] + r[1]) / 2 - mid)))
        cut = zero_cross(y, sr, (run[0] + run[1]) / 2, 1)
        cut = _clamp(cut, start + 0.2, end - 0.2)
    else:
        cut = zero_cross(y, sr, (start + end) / 2, 1)
        cut = _clamp(cut, start + 0.2, end - 0.2)
    left = _split_long(start, cut, runs, y, sr, min_seg, max_seg)
    right = _split_long(cut, end, runs, y, sr, min_seg, max_seg)
    return left + right


def plan_segments(
    samples: list[float],
    sr: int,
    *,
    min_seg: float = DEFAULT_MIN_SEG,
    max_seg: float = DEFAULT_MAX_SEG,
) -> list[tuple[float, float]]:
    """Split a cleaned file into transcribe-ready spans.

    Returns ``[(start, end), ...]`` in seconds, sorted and non-overlapping.
    Falls back to the whole file when detection finds no usable boundary —
    the batch then behaves exactly like before (never lose audio).
    """
    duration = len(samples) / sr if sr > 0 else 0.0
    if duration <= 0:
        return []
    rms = compute_rms(samples, sr)
    utterances = detect_utterances(rms)

    windows: list[tuple[float, float]] = []
    for i in range(len(utterances)):
        w = utterance_window(samples, sr, rms, utterances, i)
        if w is not None:
            windows.append(w)
    if not windows:
        return [(0.0, duration)]

    merged = _merge_short(windows, min_seg)
    runs = silence_runs(rms.t, rms.db)
    out: list[tuple[float, float]] = []
    for s, e in merged:
        out.extend(_split_long(s, e, runs, samples, sr, min_seg, max_seg))

    cleaned: list[tuple[float, float]] = []
    for s, e in sorted(out):
        s = _clamp(s, 0.0, duration)
        e = _clamp(e, 0.0, duration)
        if e - s >= MIN_KEEP:
            if cleaned and s < cleaned[-1][1]:
                s = cleaned[-1][1]
                if e - s < MIN_KEEP:
                    continue
            cleaned.append((s, e))
    if not cleaned:
        return [(0.0, duration)]
    return cleaned

// TypeScript port of `Perfect Cut v2/edgelock_snap.py`.
//
// That file was dead code in the tkinter tool — its `find_best_window` was a
// drop-in for a `Vox1_SampleCreator` that does not exist in this repo, and the
// GUI never imported it. The UI in `CutterApp.svelte` uses the primitives here
// to shade detected silences and to snap a selection to a whole utterance,
// which is what the constants were tuned for.
//
// Every threshold below is carried over unchanged. The one deliberate
// difference: `computeRms` uses a running sum of squares instead of
// re-reducing each 50 ms window, which is the same value in O(n) rather than
// O(n x window).
//
// The frame series is computed once per loaded file and then handed to every
// stage, so a click on "auto-select" never re-walks the samples.
//
// Kept byte-compatible in behaviour with the Python original, but the two now
// drift independently — if you retune the Python, retune this too.

import type { Detection, Span, Utterance } from "./types";

export const SILENCE_DB = -38.0;
export const RMS_WIN = 0.05;
export const RMS_HOP = 0.025;
export const START_SILENCE_RUN = 0.08;
export const END_SILENCE_RUN = 0.1;
export const START_PAD = 0.08;
export const END_PAD = 0.13;
export const HANGOVER_MAX = 0.28;
export const FRICATIVE_DB = -28.0;
export const NOISE_DB = -48.0;
export const MIN_GAP_BOUNDARY = 0.1;
export const MERGE_GAP = 0.22;
export const MIN_UTT = 0.18;
export const ZERO_CROSS_MS = 8.0;

const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);

/** One 50 ms / 25 ms hop RMS pass over a mono file. */
export interface Rms {
  /** Frame start times in seconds. The last frame is anchored at the file end. */
  t: Float64Array;
  /** Windowed RMS per frame in dBFS, clamped to [-60, 0]. */
  db: Float64Array;
  /** Frame spacing in seconds (constant). */
  hop: number;
  /** File duration in seconds. */
  duration: number;
}

/** Windowed RMS in dBFS, matching the tool's 50 ms / 25 ms framing. */
export function computeRms(
  y: Float32Array,
  sr: number,
  winSec = RMS_WIN,
  hopSec = RMS_HOP,
): Rms {
  const win = Math.max(1, Math.round(sr * winSec));
  const hop = Math.max(1, Math.round(sr * hopSec));
  const nFrames = y.length > win ? 1 + Math.floor((y.length - win) / hop) : 1;

  const db = new Float64Array(nFrames);
  const t = new Float64Array(nFrames);

  // Running sum of squares over the window: slide by one hop each frame,
  // dropping the `hop` samples that leave and adding the `hop` that enter.
  let sum = 0;
  for (let i = 0; i < Math.min(win, y.length); i++) sum += y[i]! * y[i]!;

  for (let f = 0; f < nFrames; f++) {
    if (f > 0) {
      const drop = (f - 1) * hop;
      for (let i = drop; i < drop + hop && i < y.length; i++) sum -= y[i]! * y[i]!;
      const enter = (f - 1) * hop + win;
      for (let i = enter; i < enter + hop && i < y.length; i++) sum += y[i]! * y[i]!;
    }
    // A file shorter than one window only ever produces a single, partial
    // frame — average over what is actually there, like the Python original.
    const len = Math.max(1, Math.min(win, y.length - f * hop));
    const rms = Math.sqrt(Math.max(sum, 0) / len + 1e-12);
    db[f] = clamp(20 * Math.log10(Math.max(rms, 1e-6)), -60, 0);
    t[f] = (f * hop) / sr;
  }
  // Anchor the last frame at the file end so a tail utterance is not cut short.
  if (nFrames > 0) t[nFrames - 1] = y.length / sr;
  return { t, db, hop: hop / sr, duration: y.length / sr };
}

const frameIndex = (t: Float64Array, sec: number): number => {
  if (t.length === 0) return 0;
  let best = 0;
  let bestD = Infinity;
  for (let i = 0; i < t.length; i++) {
    const d = Math.abs(t[i]! - sec);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
};

/** Contiguous runs below `thresh` dBFS. */
export function silenceRuns(t: Float64Array, db: Float64Array, thresh = SILENCE_DB): Span[] {
  const runs: Span[] = [];
  let i = 0;
  while (i < db.length) {
    if (db[i]! < thresh) {
      const s = i;
      while (i < db.length && db[i]! < thresh) i++;
      runs.push({ start: t[s]!, end: t[Math.min(i, db.length - 1)]! });
    } else {
      i++;
    }
  }
  return runs;
}

/** Otsu's method over the dB histogram — the adaptive speech/noise split. */
function otsu(values: Float64Array): number {
  if (values.length < 10) return SILENCE_DB;
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (hi <= lo) return SILENCE_DB;

  const bins = 64;
  const hist = new Float64Array(bins);
  for (const v of values) hist[clamp(Math.floor(((v - lo) / (hi - lo)) * bins), 0, bins - 1)]! += 1;

  const centers = new Float64Array(bins);
  for (let i = 0; i < bins; i++) centers[i] = lo + ((i + 0.5) * (hi - lo)) / bins;

  const total = values.length;
  let sumTotal = 0;
  for (let i = 0; i < bins; i++) sumTotal += hist[i]! * centers[i]!;

  let wB = 0;
  let sumB = 0;
  let maxVar = 0;
  let thr = centers[bins >> 1]!;
  for (let i = 0; i < bins; i++) {
    wB += hist[i]!;
    if (wB === 0) continue;
    const wF = total - wB;
    if (wF === 0) break;
    sumB += hist[i]! * centers[i]!;
    const mB = sumB / wB;
    const mF = (sumTotal - sumB) / wF;
    const between = wB * wF * (mB - mF) ** 2;
    if (between > maxVar) {
      maxVar = between;
      thr = centers[i]!;
    }
  }
  return thr;
}

/**
 * Walk past the VAD end through decay/fricatives; stop on a rising onset.
 * Returns the hangover-extended end of an utterance.
 */
function applyHangover(rms: Rms, offsetSec: number): number {
  const { t, db, hop } = rms;
  if (t.length === 0) return offsetSec;
  const i0 = frameIndex(t, offsetSec);
  const maxF = Math.max(1, Math.round(HANGOVER_MAX / hop));
  let end = i0;
  let silentRun = 0;
  for (let j = i0 + 1; j < Math.min(db.length, i0 + maxF + 1); j++) {
    const prev = db[j - 1]!;
    const cur = db[j]!;
    if (cur > prev + 3.0 && cur > FRICATIVE_DB) break;
    if (cur > FRICATIVE_DB && j - i0 > 3) break;
    end = j;
    if (cur < NOISE_DB + 4) {
      silentRun += hop;
      if (silentRun >= 0.08) break;
    } else {
      silentRun = 0;
    }
  }
  return t[end]!;
}

/** Speech regions after thresholding, gap-closing and short-region removal. */
export function detectUtterances(rms: Rms): Utterance[] {
  const { t, db, hop } = rms;
  if (db.length === 0) return [];
  const thr = Math.min(-28.0, Math.max(-50.0, otsu(db)));
  const speech = new Uint8Array(db.length);
  for (let i = 0; i < db.length; i++) speech[i] = db[i]! > thr ? 1 : 0;

  const closeFrames = Math.max(1, Math.round(MERGE_GAP / hop));
  const minFrames = Math.max(1, Math.round(MIN_UTT / hop));

  // Close short gaps between two speech regions.
  for (let i = 0; i < speech.length; ) {
    if (speech[i]) {
      i++;
      continue;
    }
    const a = i;
    while (i < speech.length && !speech[i]) i++;
    if (a > 0 && speech[a - 1] && i < speech.length && i - a < closeFrames) {
      for (let k = a; k < i; k++) speech[k] = 1;
    }
  }

  // Drop speech regions that are too short to be a real utterance.
  for (let i = 0; i < speech.length; ) {
    if (!speech[i]) {
      i++;
      continue;
    }
    const a = i;
    while (i < speech.length && speech[i]) i++;
    if (i - a < minFrames) for (let k = a; k < i; k++) speech[k] = 0;
  }

  const out: Utterance[] = [];
  for (let i = 0; i < speech.length; ) {
    if (!speech[i]) {
      i++;
      continue;
    }
    const a = i;
    while (i < speech.length && speech[i]) i++;
    out.push({
      start: t[a]!,
      end: t[Math.min(i, speech.length - 1)]!,
      hangover: applyHangover(rms, t[Math.min(i, speech.length - 1)]!),
    });
  }
  return out;
}

/** Nudge a cut backwards off a rising onset so it lands inside the pause. */
function retreatIfRising(rms: Rms, cut: number, floor: number): number {
  const { t, db, hop } = rms;
  const i = frameIndex(t, cut);
  const maxBack = Math.round(0.18 / hop);
  let j = i;
  for (let n = 0; n < maxBack; n++) {
    if (j <= 1 || t[j]! <= floor) break;
    const rising = db[j]! > db[j - 1]! + 2.0 && db[j]! > SILENCE_DB;
    if (!rising && db[j]! < SILENCE_DB) return t[j]!;
    j--;
  }
  const lo = Math.max(0, i - maxBack);
  const window = db.subarray(lo, i + 1);
  if (window.length === 0) return cut;
  let best = 0;
  for (let k = 1; k < window.length; k++) if (window[k]! < window[best]!) best = k;
  return t[lo + best]!;
}

/** Snap an onset backwards into the pre-speech silence. */
export function snapStart(rms: Rms, onset: number): { cut: number; reason: string } {
  const { t, db, duration } = rms;
  const runs = silenceRuns(t, db).filter((r) => r.end - r.start >= START_SILENCE_RUN);
  const covering = runs.find((r) => r.start <= onset && onset <= r.end);
  if (covering) {
    return {
      cut: clamp(onset - START_PAD, covering.start, covering.end),
      reason: "start in pre-speech silence",
    };
  }
  let before: Span | null = null;
  for (const r of runs) if (r.end <= onset + 0.02) before = r;
  if (before && onset - before.end <= 0.35) {
    return {
      cut: clamp(onset - START_PAD, before.start, before.end),
      reason: "start snapped back to silence run",
    };
  }
  return { cut: Math.max(0, Math.min(duration, onset - 0.02)), reason: "start at onset (no silence)" };
}

/**
 * Snap an offset forward into the sustained pause that follows.
 * Returns `null` when there is no sentence boundary — the caller should drop
 * the utterance rather than cut mid-word.
 */
export function snapEnd(
  rms: Rms,
  offset: number,
  nextOnset: number | null,
): { cut: number; reason: string } | null {
  const { t, db, hop, duration } = rms;
  if (nextOnset !== null && nextOnset - offset < MIN_GAP_BOUNDARY) return null;

  const runs = silenceRuns(t, db).filter((r) => r.end - r.start >= END_SILENCE_RUN);
  let after: Span | null = null;
  for (const r of runs) {
    if (r.end >= offset && r.start <= offset + 0.85) {
      after = r;
      break;
    }
    if (r.start > offset && r.start - offset <= 0.85) {
      after = r;
      break;
    }
  }

  const hard = nextOnset !== null ? nextOnset - 0.04 : duration;
  if (after) {
    const runS = Math.max(after.start, offset);
    const runE = Math.min(after.end, hard);
    if (runE - runS >= MIN_GAP_BOUNDARY * 0.7) {
      let cut = Math.min(runS + END_PAD, runE);
      cut = retreatIfRising(rms, cut, offset);
      return { cut: Math.max(offset, Math.min(hard, cut)), reason: "end in sustained pause" };
    }
  }

  if (nextOnset !== null) {
    const gap = nextOnset - offset;
    if (gap >= MIN_GAP_BOUNDARY) {
      let cut = offset + Math.min(END_PAD, gap * 0.55);
      cut = Math.min(cut, nextOnset - 0.05);
      cut = retreatIfRising(rms, cut, offset);
      return {
        cut: Math.max(offset, Math.min(nextOnset - 0.04, cut)),
        reason: "end mid-gap before next onset",
      };
    }
    return null;
  }

  const i0 = frameIndex(t, offset);
  const need = Math.max(2, Math.round(END_SILENCE_RUN / hop));
  let run = 0;
  let cutIdx = i0;
  for (let j = i0; j < db.length; j++) {
    if (db[j]! < SILENCE_DB) {
      run++;
      if (run >= need) {
        cutIdx = j - run + 1 + Math.round(END_PAD / hop);
        break;
      }
    } else {
      run = 0;
      cutIdx = j;
    }
  }
  return {
    cut: Math.max(offset, Math.min(duration, t[Math.min(cutIdx, t.length - 1)]!)),
    reason: "end at file tail",
  };
}

/** Nudge a cut to the nearest zero crossing within 8 ms, avoiding clicks. */
export function zeroCross(y: Float32Array, sr: number, sec: number, towardInterior: 1 | -1): number {
  const maxS = Math.round((ZERO_CROSS_MS / 1000) * sr);
  const i = clamp(Math.round(sec * sr), 1, y.length - 2);
  for (let n = 0; n < maxS; n++) {
    const j = i + towardInterior * n;
    if (j <= 0 || j >= y.length - 1) break;
    if (y[j] === 0 || y[j]! * y[j + towardInterior]! <= 0) return j / sr;
  }
  return sec;
}

/** Utterances, silences and the adaptive threshold, from one RMS pass. */
export function analyzeDetection(rms: Rms): Detection {
  const { t, db } = rms;
  return {
    utterances: detectUtterances(rms),
    silences: silenceRuns(t, db),
    threshold: Math.min(-28.0, Math.max(-50.0, otsu(db))),
  };
}

/**
 * The selection for utterance `i` (or a run of up to 6 consecutive ones),
 * snapped to the surrounding silences and zero-crossed. `null` when the group
 * has no usable sentence boundary.
 */
export function utteranceWindow(
  y: Float32Array,
  sr: number,
  rms: Rms,
  detection: Detection,
  i: number,
  j = i,
): { start: number; end: number; reason: string; reasonEnd: string } | null {
  const first = detection.utterances[i];
  const last = detection.utterances[j];
  if (!first || !last) return null;
  const next = detection.utterances[j + 1]?.start ?? null;

  const s = snapStart(rms, first.start);
  const e = snapEnd(rms, last.hangover, next);
  if (!e) return null;

  // Zero-cross both edges so the cut does not land on a non-zero sample and
  // tick. The actual export runs through ffmpeg on the file, so this only
  // affects what the preview plays back.
  const a = clamp(zeroCross(y, sr, s.cut, 1), 0, rms.duration);
  const b = clamp(zeroCross(y, sr, e.cut, -1), a, rms.duration);
  return {
    start: a,
    end: b,
    reason: s.reason,
    reasonEnd: e.reason,
  };
}

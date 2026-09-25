// Selection helpers built on the edgelock detector.
//
// `nearestSilence` is the tkinter tool's original "Autosnap stilte" behaviour,
// preserved verbatim so the port stays a faithful 1:1: find the quietest
// 25 ms frame within a small window, and only accept it if the window really
// contains silence. The utterance-based snapping below is the edgelock version.

import { SILENCE_DB, utteranceWindow } from "./edgelock";
import type { AudioAnalysis, Utterance } from "./types";

/** The quietest frame within ±`window` seconds of `t`, if that window is silent. */
export function nearestSilence(analysis: AudioAnalysis, t: number, window = 0.8): number {
  const { db, hop, duration } = analysis.rms;
  if (db.length === 0) return t;
  const centre = Math.max(0, Math.min(t, duration));
  const idx = Math.round(centre / hop);
  const half = Math.max(1, Math.round(window / hop));
  const lo = Math.max(0, idx - half);
  const hi = Math.min(db.length, idx + half);
  let best = lo;
  for (let i = lo; i < hi; i++) if (db[i]! < db[best]!) best = i;
  // Reject if the window never actually got quiet — the original's guard.
  let anySilent = false;
  for (let i = lo; i < hi; i++) if (db[i]! < SILENCE_DB) anySilent = true;
  if (!anySilent) return t;
  return Math.min(duration, best * hop);
}

export type Window = { start: number; end: number; reason: string; reasonEnd: string };

/** The snapped window for utterance `index` (+ `group` more), or null. */
export function windowFor(analysis: AudioAnalysis, index: number, group = 0): Window | null {
  if (index < 0 || index >= analysis.detection.utterances.length) return null;
  const last = Math.min(analysis.detection.utterances.length - 1, index + group);
  return utteranceWindow(
    analysis.mono,
    analysis.sampleRate,
    analysis.rms,
    analysis.detection,
    index,
    last,
  );
}

/** First utterance starting at/after `t`, else null. */
export function nextUtterance(analysis: AudioAnalysis, t: number): number {
  const list = analysis.detection.utterances;
  for (let i = 0; i < list.length; i++) if (list[i]!.end > t + 0.01) return i;
  return -1;
}

/** Last utterance ending at/before `t`, else null. */
export function prevUtterance(analysis: AudioAnalysis, t: number): number {
  const list = analysis.detection.utterances;
  for (let i = list.length - 1; i >= 0; i--) if (list[i]!.start < t - 0.01) return i;
  return -1;
}

/** Index of the utterance containing `t`, else -1. */
export function utteranceIndexAt(analysis: AudioAnalysis, t: number): number {
  const list = analysis.detection.utterances;
  for (let i = 0; i < list.length; i++) {
    const u = list[i]!;
    if (t >= u.start && t <= u.end) return i;
  }
  return -1;
}

/** Grow a selection to cover `count` consecutive utterances. */
export function expandToUtterances(analysis: AudioAnalysis, index: number, count: number): Window | null {
  return windowFor(analysis, index, Math.max(0, count - 1));
}

/** "3 utterances · 12.4 s total" for the status bar. */
export function summarise(list: Utterance[], duration: number): string {
  if (list.length === 0) return "no speech detected";
  const speech = list.reduce((acc, u) => acc + (u.end - u.start), 0);
  const pct = duration > 0 ? Math.round((speech / duration) * 100) : 0;
  return `${list.length} utterance${list.length === 1 ? "" : "s"} · ${speech.toFixed(1)}s speech (${pct}%)`;
}

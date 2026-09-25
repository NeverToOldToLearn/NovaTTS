// Web Audio helpers: decode, waveform/loudness pre-computation, playback.
//
// This replaces the tkinter tool's numpy + soundfile + pygame + matplotlib
// stack entirely — the browser already ships a WAV decoder, an RMS-capable
// audio graph and a resampler, so the tool now needs no Python-side audio
// dependencies at all.

import { analyzeDetection, computeRms } from "./edgelock";
import type { AudioAnalysis } from "./types";

/** Guard against handing a 500 MB file to decodeAudioData. */
export const MAX_DECODE_BYTES = 200 * 1024 * 1024;

let ctx: AudioContext | null = null;

/** Shared AudioContext. Created lazily — browsers require a user gesture. */
export function audioContext(): AudioContext {
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

function toMono(buffer: AudioBuffer): Float32Array {
  const n = buffer.length;
  if (buffer.numberOfChannels === 1) return buffer.getChannelData(0).slice();
  const out = new Float32Array(n);
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const data = buffer.getChannelData(c);
    for (let i = 0; i < n; i++) out[i] = out[i]! + data[i]!;
  }
  const scale = 1 / buffer.numberOfChannels;
  for (let i = 0; i < n; i++) out[i] = out[i]! * scale;
  return out;
}

/** min/max envelope with ~`buckets` columns, so drawing stays cheap at any zoom. */
function envelope(mono: Float32Array, buckets: number): { min: Float32Array; max: Float32Array } {
  const n = mono.length;
  const count = Math.max(1, Math.min(buckets, n));
  const min = new Float32Array(count);
  const max = new Float32Array(count);
  const per = n / count;
  for (let b = 0; b < count; b++) {
    const s = Math.floor(b * per);
    const e = Math.min(n, Math.max(s + 1, Math.floor((b + 1) * per)));
    let lo = Infinity;
    let hi = -Infinity;
    for (let i = s; i < e; i++) {
      const v = mono[i]!;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    min[b] = lo === Infinity ? 0 : lo;
    max[b] = hi === -Infinity ? 0 : hi;
  }
  return { min, max };
}

/**
 * Sample rate stored in a RIFF/WAVE header, or null when the bytes are not a
 * plain WAV (the picker only offers .wav, but a mislabelled file would
 * otherwise report the AudioContext's rate as if it were the file's).
 */
function wavSampleRate(bytes: ArrayBuffer): number | null {
  const view = new DataView(bytes);
  if (view.byteLength < 12 + 24) return null;
  const tag = (off: number) =>
    String.fromCharCode(
      view.getUint8(off),
      view.getUint8(off + 1),
      view.getUint8(off + 2),
      view.getUint8(off + 3),
    );
  if (tag(0) !== "RIFF" || tag(8) !== "WAVE") return null;
  // Walk the chunk list; the rate lives in the first `fmt ` chunk.
  let off = 12;
  while (off + 8 <= view.byteLength) {
    const id = tag(off);
    const size = view.getUint32(off + 4, true);
    if (id === "fmt ") {
      if (off + 8 + 16 > view.byteLength) return null;
      const rate = view.getUint32(off + 12, true);
      return rate > 0 ? rate : null;
    }
    off += 8 + size + (size % 2);
  }
  return null;
}

/** Decode raw WAV bytes and pre-compute everything the UI draws. */
export async function analyzeBytes(
  bytes: ArrayBuffer,
  buckets = 4000,
): Promise<{ buffer: AudioBuffer; analysis: AudioAnalysis }> {
  const context = audioContext();
  const fileRate = wavSampleRate(bytes);
  // decodeAudioData detaches the buffer, so hand it a copy.
  const buffer = await context.decodeAudioData(bytes.slice(0));
  const mono = toMono(buffer);
  const sampleRate = buffer.sampleRate;
  const rms = computeRms(mono, sampleRate);
  const { min, max } = envelope(mono, buckets);
  return {
    buffer,
    analysis: {
      sampleRate,
      fileRate: fileRate ?? sampleRate,
      duration: buffer.duration,
      channels: buffer.numberOfChannels,
      mono,
      envMin: min,
      envMax: max,
      rms,
      detection: analyzeDetection(rms),
    },
  };
}

// --- playback ---------------------------------------------------------------

export interface PlayHandle {
  /** Call to stop early. */
  stop: () => void;
}

export interface PlayOptions {
  offsetSec?: number;
  durationSec?: number;
  onEnded?: () => void;
}

/**
 * Play a slice of the analysis. Returns null when the slice is too short to be
 * audible. The caller drives the playhead from `Player.time()`.
 */
export function playSlice(
  buffer: AudioBuffer,
  analysis: AudioAnalysis,
  opts: PlayOptions = {},
): PlayHandle | null {
  const start = Math.max(0, opts.offsetSec ?? 0);
  const end = Math.min(analysis.duration, start + (opts.durationSec ?? analysis.duration - start));
  if (end - start < 0.01) return null;

  const context = audioContext();
  const source = context.createBufferSource();
  source.buffer = buffer;
  source.connect(context.destination);

  const when = context.currentTime;
  const duration = end - start;
  let stopped = false;
  const finish = () => {
    if (!stopped) {
      stopped = true;
      opts.onEnded?.();
    }
  };
  source.onended = finish;
  source.start(when, start, duration);
  return {
    stop: () => {
      if (stopped) return;
      stopped = true;
      try {
        source.stop();
      } catch {
        /* already stopped */
      }
      opts.onEnded?.();
    },
  };
}

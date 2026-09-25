// Types for the Perfect Cut tool API (/cutter/*) and the tool's own state.

import type { Rms } from "./edgelock";

export type { Rms };

export interface CutterConfig {
  input_dir: string;
  output_dir: string;
  whisper_exe: string;
  whisper_model: string;
  ffmpeg: string;
  lang: string;
  qwen_preset: boolean;
  keep_sr: boolean;
  snap: boolean;
}

export interface CutterTools {
  ffmpeg: string;
  whisper_exe: string;
  whisper_model: string;
  ffmpeg_exists: boolean;
  whisper_exe_exists: boolean;
  whisper_model_exists: boolean;
}

export interface ExportResult {
  out: string;
  via: "ffmpeg" | "stdlib";
  cmd: string[];
  rate: number;
  channels: number;
  duration: number;
}

/** Silences/utterances found by the edgelock detector, in seconds. */
export interface Span {
  start: number;
  end: number;
}

export interface Utterance extends Span {
  /** Hangover-extended end (what snap_end cuts from). */
  hangover: number;
}

export interface Detection {
  utterances: Utterance[];
  silences: Span[];
  /** Adaptive speech threshold in dBFS (Otsu, clamped). */
  threshold: number;
}

export interface BatchStatus {
  total: number;
  index: number;
  name: string;
  ok: number;
  fail: number;
  pct: number;
  running: boolean;
  stop_requested: boolean;
  finished: boolean;
  lines: string[];
}

/** Analysis of a loaded file, in the shapes the waveform component wants. */
export interface AudioAnalysis {
  /**
   * Rate the audio was decoded at. `decodeAudioData` resamples to the
   * AudioContext's rate, so this is what the analysis math must use — it is
   * NOT necessarily the file's rate.
   */
  sampleRate: number;
  /** The rate stored in the file's WAV header, for display only. */
  fileRate: number;
  duration: number;
  channels: number;
  /** Decoded mono Float32Array, normalised to [-1, 1]. */
  mono: Float32Array;
  /** min/max envelope per bucket, for the waveform view. */
  envMin: Float32Array;
  envMax: Float32Array;
  /** The 50 ms / 25 ms RMS series, shared by the dB view and the detector. */
  rms: Rms;
  detection: Detection;
}

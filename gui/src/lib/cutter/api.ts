// HTTP client for the Perfect Cut endpoints. Mirrors gui/src/lib/api.ts.

import type { BatchStatus, CutterConfig, CutterTools, ExportResult } from "./types";

const BASE = "http://127.0.0.1:8765";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export interface BatchInput {
  input_dir: string;
  output_dir: string;
  whisper_exe: string;
  whisper_model: string;
  lang: string;
}

export const cutterApi = {
  config: () => req<{ config: CutterConfig }>("/cutter/config"),
  saveConfig: (patch: Partial<CutterConfig>) =>
    post<{ config: CutterConfig }>("/cutter/config", patch),

  tools: () => req<CutterTools>("/cutter/tools"),
  autoTools: () => post<CutterTools>("/cutter/tools/auto"),
  testTool: (tool: "ffmpeg" | "whisper_exe") =>
    post<{ ok: boolean; tool: string; path: string; message: string }>(
      `/cutter/tools/test?tool=${tool}`,
    ),

  exportCut: (body: {
    src: string;
    out: string;
    start: number;
    end: number;
    mode: "qwen" | "native" | "keep";
  }) => post<ExportResult>("/cutter/export", body),

  batchPreflight: (body: BatchInput) => post<{ ok: boolean; lines: string[] }>("/cutter/batch/preflight", body),
  batchStart: (body: BatchInput) => post<{ status: string }>("/cutter/batch/start", body),
  batchStatus: () => req<BatchStatus>("/cutter/batch/status"),
  batchStop: () => post<{ stopping: boolean }>("/cutter/batch/stop"),
};

/** Pick the export mode from the two checkboxes the tool has always had. */
export const exportMode = (qwenPreset: boolean, keepSr: boolean): "qwen" | "native" | "keep" =>
  keepSr ? "keep" : qwenPreset ? "qwen" : "native";

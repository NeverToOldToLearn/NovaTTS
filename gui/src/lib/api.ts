import type { EventEntry, Health, ImportStatus, ServerStatus, SettingsResponse, Speaker, SpeakBody } from "./types";

const BASE = "http://127.0.0.1:8765";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
  return (await res.json()) as T;
}

function toB64(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]!);
  return btoa(bin);
}

export type QwenStatus = {
  qwen_url: string;
  managed_running: boolean;
  external_running: boolean;
  online: boolean;
  pid: number | null;
  bin: string;
  model: string;
  codec: string;
  bin_exists: boolean;
  model_exists: boolean;
  codec_exists: boolean;
  last_error: string | null;
};

export const api = {
  health: () => req<Health>("/health"),
  status: () => req<ServerStatus>("/status"),
  events: (limit = 100) => req<EventEntry[]>(`/events?limit=${limit}`),
  speak: (body: SpeakBody) =>
    req<{ status: string; file: string }>("/speak", { method: "POST", body: JSON.stringify(body) }),

  speakers: () => req<Record<string, Speaker> & { versions: number; fallback: string }>("/speakers"),
  createSpeaker: (name: string) =>
    req<Speaker>("/speakers", { method: "POST", body: JSON.stringify({ name }) }),
  updateSpeaker: (name: string, patch: Partial<Pick<Speaker, "voice">>) =>
    req<Speaker>(`/speakers/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteSpeaker: (name: string) =>
    req<{ deleted: string }>(`/speakers/${encodeURIComponent(name)}`, { method: "DELETE" }),
  renameSpeaker: (name: string, newName: string) =>
    req<Speaker>(`/speakers/${encodeURIComponent(name)}/rename`, {
      method: "POST",
      body: JSON.stringify({ new_name: newName }),
    }),
  aliasSpeaker: (name: string, alias: string) =>
    req<Speaker>(`/speakers/${encodeURIComponent(name)}/alias`, {
      method: "POST",
      body: JSON.stringify({ alias }),
    }),

  qwenStatus: () => req<QwenStatus>("/qwen/status"),
  qwenStart: () => req<{ status: string; pid?: number }>("/qwen/start", { method: "POST" }),
  qwenStop: () => req<{ status: string }>("/qwen/stop", { method: "POST" }),
  convertSamples: (force = false) =>
    req<{
      converted: number;
      skipped: number;
      failed: number;
      total: number;
      errors: string[];
      import_status?: ImportStatus;
    }>(`/qwen/convert-samples${force ? "?force=1" : ""}`, { method: "POST" }),

  voices: () => req<{ voices: string[]; qwen_online: boolean }>("/voices"),
  cloneVoice: (name: string, wavB64: string, refText = "") =>
    req<{ status: string; voice: string; bytes: number }>("/voices", {
      method: "POST",
      body: JSON.stringify({ name, wav_b64: wavB64, ref_text: refText }),
    }),
  cloneVoiceFromBytes: async (name: string, bytes: Uint8Array, refText = "") =>
    api.cloneVoice(name, toB64(bytes), refText),
  deleteVoice: (name: string) =>
    req<{ status: string; deleted: string }>(`/voices/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  previewVoice: (name: string, text: string) =>
    req<{ status: string; voice: string; file: string; size: number }>(
      `/voices/${encodeURIComponent(name)}/preview`,
      { method: "POST", body: JSON.stringify({ text }) },
    ),

  games: () => req<{ active: string; games: string[] }>("/games"),
  createGame: (name: string) => req<{ game: string; games: string[] }>("/games", { method: "POST", body: JSON.stringify({ name }) }),
  setActiveGame: (name: string) => req<{ game: string; speakers: unknown; path: string }>("/games/active", { method: "POST", body: JSON.stringify({ name }) }),
  blacklist: () => req<{ custom_words: string[]; enabled_presets: string[]; presets: string[] }>("/blacklist"),
  setBlacklist: (custom_words: string[] | null, enabled_presets: string[] | null) =>
    req<{ custom_words: string[]; enabled_presets: string[] }>("/blacklist", { method: "POST", body: JSON.stringify({ custom_words, enabled_presets }) }),
  emotions: () => req<{ dir: string; sounds: number; map: Record<string, string>; aliases: Record<string, string>; patterns: number }>("/emotions"),
  reloadEmotions: () => req<{ dir: string; sounds: number; map: Record<string, string> }>("/emotions/reload", { method: "POST" }),
  addEmotionAlias: (expr: string, tag: string) => req<unknown>("/emotions/alias", { method: "POST", body: JSON.stringify({ expr, tag }) }),
  deleteEmotionAlias: (expr: string) => req<unknown>(`/emotions/alias/${encodeURIComponent(expr)}`, { method: "DELETE" }),

  settings: () => req<SettingsResponse>("/settings"),
  updateSettings: (body: Record<string, unknown>) =>
    req<{ status: string; settings: SettingsResponse["settings"]; path_status: SettingsResponse["path_status"] }>("/settings", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  testTts: () => req<{ status: string; file: string; size: number }>("/test-tts", { method: "POST" }),
  openClipboardLog: () =>
    req<{ status: string; path: string }>("/clipboard-log/open", { method: "POST" }),
  clearClipboardLog: () =>
    req<{ status: string }>("/clipboard-log/clear", { method: "POST" }),
};

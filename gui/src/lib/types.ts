// Shared types for the NovaTTS API surface.

export interface Health {
  status: string;
  qwen: boolean;
}

export interface ImportStatus {
  found: number;
  loaded: number;
  total: number;
  active: boolean;
  error: string | null;
  dir: string;
  /** Wavs with a complete pre-extracted .spk/.rvq pair. */
  pairs?: number;
  /** Wavs without a pair yet (need server-side extraction). */
  unpaired?: number;
}
/**
 * Which raw_text sources the app started, from `settings.hook_mode`.
 *
 * A union rather than `string` so a typo in a component is a type error.
 * The backend validates the value too and falls back to "both", so this
 * guards the GUI's own comparisons, not the wire.
 */
export type HookMode = "clipboard" | "websocket" | "both";

export interface ServerStatus {
  server: string;
  qwen: boolean;
  voices: string[];
  stale_mappings: { speaker: string; voice: string }[];
  voice_used_by?: Record<string, string[]>;
  import_status?: ImportStatus;
  game?: string;
  games?: string[];
  clipboard: boolean;
  queue_size: number;
  current: string | null;
  speaker_count: number;
  qwen_mgr?: QwenMgr;
  hook_mode?: HookMode;
  hook_host?: string;
  hook_port?: number;
  hook_clients?: number;
  hook_dropped?: number;
  hook_last_raw?: string;
  file_watch?: boolean;
  file_watch_path?: string;
  file_running?: boolean;
  file_last_raw?: string;
}

export interface QwenMgr {
  managed_running: boolean;
  external_running: boolean;
  online: boolean;
  pid: number | null;
  bin: string;
  bin_exists: boolean;
  model_exists: boolean;
  codec_exists: boolean;
  last_error: string | null;
  import_status?: ImportStatus;
}

export interface Speaker {
  name: string;
  voice: string;
  instruct?: string;
  emotion?: string;
}

export interface SpeakersResponse {
  versions: number;
  speakers: Record<string, Speaker>;
  fallback: string;
}

export interface EventEntry {
  type: string;
  payload: Record<string, unknown>;
}

export interface SpeakBody {
  text: string;
  speaker?: string | null;
  instruct?: string;
  emotion?: string;
  voice?: string | null;
}

export interface PathStatus {
  path: string;
  exists: boolean;
}

export interface SettingsData {
  qwen_bin: string;
  qwen_model: string;
  qwen_codec: string;
  qwen_codec_bin: string;
  qwen_url: string;
  qwen_default_voice: string;
  qwen_samples_dir: string;
  qwen_samples_dirs_extra: string;
  emotion_sounds_dir: string;
  qwen_timeout: number;
  qwen_extra_args: string;
  poll_interval: number;
  qwen_autostart: boolean;
  qwen_auto_import_samples: boolean;
  // Hook input (LunaHook/Textractor). hook_host is read-only on purpose:
  // it is the websocket bind address and cannot change without a restart,
  // so the Settings endpoint does not accept it.
  hook_mode: HookMode;
  hook_host: string;
  hook_port: number;
  hook_space_form: boolean;
  hook_dual_hook: boolean;
  luna_ws_url: string;
  file_watch: boolean;
  file_watch_path: string;
  dedup_window_ms: number;
}

export interface SettingsResponse {
  settings: SettingsData;
  path_status: Record<string, PathStatus>;
  env_file: string;
}

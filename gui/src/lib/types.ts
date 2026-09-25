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
}

export interface SettingsResponse {
  settings: SettingsData;
  path_status: Record<string, PathStatus>;
  env_file: string;
}
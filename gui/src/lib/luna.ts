// Luna-Hook connection points (stubs).
//
// The full Luna-Hook integration lives on a separate branch and is currently
// on hold. The backend in this build does not serve the hook routes yet, so
// every helper here is written to be safe *today*: a missing route, a 404 or a
// network error resolves to a neutral value instead of throwing. That lets the
// Dashboard carry the UI connection points now and light them up unchanged once
// the backend catches up.

const BASE = "http://127.0.0.1:8765";

export type HookMode = "clipboard" | "websocket" | "both";

export interface LunaStatus {
  /** True when the backend actually exposes the hook fields. */
  available: boolean;
  mode: HookMode;
  host: string;
  port: number;
  clients: number;
  dropped: number;
  lastRaw: string;
}

/** A name the hook delivered that may not be registered as a speaker yet. */
export interface HookName {
  name: string;
  count?: number;
  last_seen?: number;
  registered: boolean;
}

export const LUNA_UNAVAILABLE: LunaStatus = {
  available: false,
  mode: "clipboard",
  host: "127.0.0.1",
  port: 6677,
  clients: 0,
  dropped: 0,
  lastRaw: "",
};

const MODES: HookMode[] = ["clipboard", "websocket", "both"];

const asMode = (value: unknown): HookMode =>
  MODES.includes(value as HookMode) ? (value as HookMode) : "clipboard";

/** GET that returns null for any non-2xx response or transport error. */
async function getJson<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

type StatusLike = {
  hook_mode?: unknown;
  hook_host?: unknown;
  hook_port?: unknown;
  hook_clients?: unknown;
  hook_dropped?: unknown;
  hook_last_raw?: unknown;
};

export const luna = {
  /**
   * Hook state, read from the hook fields on `/status`. A backend without those
   * fields reports `available: false` — never an exception.
   */
  async status(): Promise<LunaStatus> {
    const s = await getJson<StatusLike>("/status");
    if (!s || typeof s.hook_mode !== "string") return { ...LUNA_UNAVAILABLE };
    return {
      available: true,
      mode: asMode(s.hook_mode),
      host: typeof s.hook_host === "string" ? s.hook_host : LUNA_UNAVAILABLE.host,
      port: typeof s.hook_port === "number" ? s.hook_port : LUNA_UNAVAILABLE.port,
      clients: typeof s.hook_clients === "number" ? s.hook_clients : 0,
      dropped: typeof s.hook_dropped === "number" ? s.hook_dropped : 0,
      lastRaw: typeof s.hook_last_raw === "string" ? s.hook_last_raw : "",
    };
  },

  /** Names the hook has seen. Empty list when `/hook/names` is not there yet. */
  async names(): Promise<HookName[]> {
    const r = await getJson<{ names?: HookName[] }>("/hook/names");
    return Array.isArray(r?.names) ? r.names : [];
  },
};

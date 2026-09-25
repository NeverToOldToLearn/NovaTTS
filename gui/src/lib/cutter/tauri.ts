// Thin bridge to the Rust side of the app.
//
// Everything that needs a real filesystem path or a native dialog goes
// through Tauri commands here rather than a plugin's JS API. That keeps the
// permission surface at zero (no capabilities file, no fs scope) and means
// the tool also works when the webview is opened outside the desktop shell
// (plain `npm run dev`) — each call reports a clear error instead of
// throwing an opaque "not a Tauri app" exception.

type Invoke = <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;

let cached: Invoke | null = null;

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (!cached) {
    const mod = await import("@tauri-apps/api/core");
    cached = mod.invoke as Invoke;
  }
  if (!("__TAURI_INTERNALS__" in window)) {
    throw new Error("Desktop-only action — open Perfect Cut from the NovaTTS app.");
  }
  return cached<T>(cmd, args);
}

/** True when running inside the Tauri shell (vs. a plain browser tab). */
export const isDesktop = (): boolean => "__TAURI_INTERNALS__" in window;

/** Read a local file as raw bytes. Used to feed the Web Audio decoder. */
export const readAudioFile = (path: string): Promise<ArrayBuffer> =>
  invoke<ArrayBuffer>("read_audio_file", { path });

export const pickWav = (): Promise<string | null> => invoke<string | null>("pick_wav");
export const pickDir = (title: string, start: string): Promise<string | null> =>
  invoke<string | null>("pick_dir", { title, start });
export const pickSaveWav = (suggested: string, start: string): Promise<string | null> =>
  invoke<string | null>("pick_save_wav", { suggested, start });
export const pickExe = (title: string, start: string): Promise<string | null> =>
  invoke<string | null>("pick_exe", { title, start });
export const pickModel = (title: string, start: string): Promise<string | null> =>
  invoke<string | null>("pick_model", { title, start });

/** Reveal a file or folder in Explorer. */
export const openPath = (path: string): Promise<string | null> => invoke<string | null>("open_path", { path });

/** Show/focus the Perfect Cut window. Resolves true if it was already on screen. */
export const openCutter = (): Promise<boolean> => invoke<boolean>("open_cutter");

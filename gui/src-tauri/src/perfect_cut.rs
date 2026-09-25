//! Tauri commands backing the Perfect Cut tool window.
//!
//! Two rules shaped this file:
//!
//! 1. **No plugin JS APIs.** File/folder pickers are exposed as app commands
//!    that call `tauri_plugin_dialog` from Rust, so the app needs no
//!    capability file and no `fs` scope. `tauri::generate_handler!` makes
//!    these callable from any window by default.
//! 2. **Bytes cross the bridge raw.** `read_audio_file` returns
//!    `tauri::ipc::Response` so the WAV is a binary blob rather than a JSON
//!    array of numbers, then `decodeAudioData` handles it in the webview.

use std::path::PathBuf;

use tauri::{AppHandle, Manager, WebviewUrl};
use tauri_plugin_dialog::DialogExt;

/// Must match the `label` of the cutter window in tauri.conf.json.
const CUTTER_WINDOW: &str = "cutter";

/// Title/size the cutter window is created with when it is not already
/// declared in tauri.conf.json. Keep the two in sync.
const CUTTER_TITLE: &str = "Perfect Cut — NovaTTS Sample Cutter";
const CUTTER_URL: &str = "index.html#/cutter";

/// Reject anything absurd before reading it into memory. Mirrored by
/// `MAX_DECODE_BYTES` in `gui/src/lib/cutter/audio.ts` — keep the two equal.
const MAX_AUDIO_BYTES: u64 = 200 * 1024 * 1024;
const MAX_AUDIO_MB: u64 = MAX_AUDIO_BYTES / 1_048_576;

fn basename_of(path: &std::path::Path) -> String {
    path.file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| path.to_string_lossy().into_owned())
}

/// Best-effort starting directory for a native dialog: the path itself if it
/// is a directory, otherwise its parent. Returns `None` when neither exists,
/// in which case the dialog opens wherever the OS decides.
fn start_dir(start: &str) -> Option<PathBuf> {    if start.is_empty() {
        return None;
    }
    let p = PathBuf::from(start);
    if p.is_dir() {
        Some(p)
    } else {
        p.parent().filter(|d| d.is_dir()).map(|d| d.to_path_buf())
    }
}

/// The dialogs hand back a `FilePath` that may be a URL rather than a local
/// path; we only ever deal in local paths, so anything else is a cancel.
fn into_path(value: tauri_plugin_dialog::FilePath) -> Option<PathBuf> {
    value.into_path().ok()
}

fn pick_file(
    app: &AppHandle,
    title: &str,
    start: &str,
    filters: &[(&str, &[&str])],
) -> Option<PathBuf> {
    // NOTE: the builder methods take `self` by value and the `blocking_*`
    // method *consumes* the builder — so it has to come last, after every
    // filter/directory is set, or the dialog opens unconfigured.
    let mut dialog = app.dialog().file().set_title(title);
    if let Some(dir) = start_dir(start) {
        dialog = dialog.set_directory(dir);
    }
    for (label, exts) in filters {
        dialog = dialog.add_filter(*label, exts);
    }
    dialog.blocking_pick_file().and_then(into_path)
}

/// Show (or focus) the Perfect Cut window. Returns whether it was *already on
/// screen* before this call.
///
/// The window is also declared in tauri.conf.json (hidden) so it exists from
/// startup; this command is the only thing that reveals it. If it was closed,
/// it is rebuilt from scratch.
#[tauri::command]
pub fn open_cutter(app: AppHandle) -> Result<bool, String> {
    if let Some(win) = app.get_webview_window(CUTTER_WINDOW) {
        // "Existed" is not the same as "visible": the window is created hidden
        // at startup, so reporting `true` here would always claim the tool was
        // already open. Ask the OS instead.
        let was_visible = win.is_visible().unwrap_or(false);
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
        return Ok(was_visible);
    }
    tauri::WebviewWindowBuilder::new(
        &app,
        CUTTER_WINDOW,
        WebviewUrl::App(CUTTER_URL.into()),
    )
    .title(CUTTER_TITLE)
    .inner_size(1180.0, 820.0)
    .min_inner_size(900.0, 620.0)
    .center()
    .build()
    .map_err(|e| e.to_string())?;
    Ok(false)
}

/// Read a local audio file as raw bytes for `decodeAudioData`.
#[tauri::command]
pub fn read_audio_file(path: String) -> Result<tauri::ipc::Response, String> {
    let p = PathBuf::from(&path);
    if !p.is_file() {
        return Err(format!("not a file: {path}"));
    }
    let size = std::fs::metadata(&p).map(|m| m.len()).unwrap_or(0);
    if size > MAX_AUDIO_BYTES {
        return Err(format!(
            "{} is {:.0} MB, over the {MAX_AUDIO_MB} MB limit",
            basename_of(&p),
            size as f64 / 1_048_576.0
        ));
    }
    let bytes = std::fs::read(&p).map_err(|e| format!("{path}: {e}"))?;
    Ok(tauri::ipc::Response::new(bytes))
}

#[tauri::command]
pub fn pick_wav(app: AppHandle) -> Option<String> {
    pick_file(
        &app,
        "Select a WAV file",
        "",
        &[("WAV audio", &["wav"]), ("All files", &["*"])],
    )
    .map(|p| p.to_string_lossy().into_owned())
}

#[tauri::command]
pub fn pick_dir(app: AppHandle, title: String, start: String) -> Option<String> {
    let dir = start_dir(&start).or_else(|| start_dir("."))?;
    app.dialog()
        .file()
        .set_title(title)
        .set_directory(dir)
        .blocking_pick_folder()
        .and_then(into_path)
        .map(|p| p.to_string_lossy().into_owned())
}

#[tauri::command]
pub fn pick_save_wav(app: AppHandle, suggested: String, start: String) -> Option<String> {
    let name = PathBuf::from(&suggested)
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .filter(|n| !n.is_empty())
        .unwrap_or_else(|| "cut.wav".to_string());
    // Guarantee the extension before the dialog opens — the save dialog will
    // not append one, and ffmpeg picks its muxer from the suffix.
    let name = if name.to_ascii_lowercase().ends_with(".wav") {
        name
    } else {
        format!("{name}.wav")
    };
    app.dialog()
        .file()
        .set_title("Export selection to")
        .set_file_name(name)
        .add_filter("WAV audio", &["wav"])
        .set_directory(start_dir(&start).unwrap_or_else(|| PathBuf::from(".")))
        .blocking_save_file()
        .and_then(into_path)
        .map(|p| p.to_string_lossy().into_owned())
}

#[tauri::command]
pub fn pick_exe(app: AppHandle, title: String, start: String) -> Option<String> {
    pick_file(
        &app,
        &title,
        &start,
        &[("Executables", &["exe"]), ("All files", &["*"])],
    )
    .map(|p| p.to_string_lossy().into_owned())
}

#[tauri::command]
pub fn pick_model(app: AppHandle, title: String, start: String) -> Option<String> {
    pick_file(
        &app,
        &title,
        &start,
        &[("Whisper models", &["bin", "gguf"]), ("All files", &["*"])],
    )
    .map(|p| p.to_string_lossy().into_owned())
}

/// Reveal a file or folder in the OS file manager.
///
/// Uses `explorer` directly rather than `tauri-plugin-shell` so the app
/// needs no capability file for this command. On Windows a file is revealed
/// with `/select,` so it is highlighted; on other platforms the containing
/// directory is opened.
#[tauri::command]
pub fn open_path(path: String) -> Result<String, String> {
    let p = PathBuf::from(&path);
    if !p.exists() {
        return Err(format!("path does not exist: {path}"));
    }

    #[cfg(windows)]
    let mut cmd = {
        let mut c = std::process::Command::new("explorer");
        if p.is_dir() {
            c.arg(&p);
        } else {
            c.arg(format!("/select,{}", p.display()));
        }
        c
    };
    #[cfg(not(windows))]
    let mut cmd = {
        let dir = if p.is_dir() {
            p.clone()
        } else {
            p.parent().unwrap_or(&p).to_path_buf()
        };
        let mut c = std::process::Command::new("xdg-open");
        c.arg(dir);
        c
    };

    // explorer.exe always exits 1 even on success, so only the spawn matters.
    cmd.spawn()
        .map_err(|e| format!("could not open file manager: {e}"))?;
    Ok(path)
}

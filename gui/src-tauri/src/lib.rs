use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::{Arc, Mutex, Once};
use std::time::{Duration, Instant};

use tauri::Manager;

mod perfect_cut;

type BackendHandle = Arc<Mutex<Option<Child>>>;

/// Managed tauri state wrappers — distinct types so both can be registered.
struct BackendState(BackendHandle);
struct FrontendState(BackendHandle);

/// Label of the main window. Must match `tauri.conf.json`.
const MAIN_WINDOW: &str = "main";

/// Cleanup runs once per process; both the main-window close handler and the
/// Tauri exit hook call it.
static SHUTDOWN_ONCE: Once = Once::new();

fn app_base_dir(handle: &tauri::AppHandle) -> PathBuf {
    if let Ok(d) = handle.path().resource_dir() {
        if d.join("data").exists() || d.join("resources").join(BACKEND_BIN).exists() {
            return d;
        }
        if let Some(parent) = d.parent() {
            if parent.join("data").exists() {
                return parent.to_path_buf();
            }
        }
        return d;
    }
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."))
}

/// Where user-writable state (`.env`, `data/`) lives.
///
/// Portable builds and dev checkouts keep everything next to the app, like on
/// Windows. A Linux package installs under `/usr/lib` (and an AppImage mounts
/// a read-only squashfs), so writing there fails. In that case use the XDG
/// data dir: `$XDG_DATA_HOME/novatts` or `~/.local/share/novatts`.
#[cfg(target_os = "linux")]
fn linux_state_dir(handle: &tauri::AppHandle) -> Option<PathBuf> {
    let bundled = app_base_dir(handle);
    if dir_is_writable(&bundled) {
        return None;
    }
    let data_home = std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .filter(|p| !p.as_os_str().is_empty())
        .or_else(|| {
            std::env::var_os("HOME")
                .map(|h| PathBuf::from(h).join(".local").join("share"))
        })
        .unwrap_or_else(|| PathBuf::from("."));
    Some(data_home.join("novatts"))
}

#[cfg(not(target_os = "linux"))]
fn linux_state_dir(_handle: &tauri::AppHandle) -> Option<PathBuf> {
    None
}

fn state_base_dir(handle: &tauri::AppHandle) -> PathBuf {
    linux_state_dir(handle).unwrap_or_else(|| app_base_dir(handle))
}

fn dir_is_writable(dir: &Path) -> bool {
    if std::fs::create_dir_all(dir).is_err() {
        return false;
    }
    let probe = dir.join(".novatts-write-test");
    let ok = std::fs::write(&probe, b"").is_ok();
    let _ = std::fs::remove_file(&probe);
    ok
}

/// First run of an installed Linux build: copy the bundled default `data/`
/// into the user data dir. Existing files are never overwritten.
fn seed_data_dir(handle: &tauri::AppHandle, target: &Path) {
    let source = app_base_dir(handle).join("data");
    let dest = target.join("data");
    if dest.exists() || !source.is_dir() {
        return;
    }
    match copy_dir_all(&source, &dest) {
        Ok(()) => eprintln!("[NovaTTS] seeded {} from {}", dest.display(), source.display()),
        Err(e) => eprintln!("[NovaTTS] could not seed {}: {e}", dest.display()),
    }
}

fn copy_dir_all(src: &Path, dst: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(dst)?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let file_type = entry.file_type()?;
        let to = dst.join(entry.file_name());
        if file_type.is_dir() {
            copy_dir_all(&entry.path(), &to)?;
        } else if !to.exists() {
            std::fs::copy(entry.path(), &to)?;
        }
    }
    Ok(())
}

fn ensure_env(handle: &tauri::AppHandle) {
    let base = state_base_dir(handle);
    let _ = std::fs::create_dir_all(&base);
    let env_path = base.join(".env");

    // Never overwrite an existing .env. The installer and the Settings panel
    // write the real paths there (tts-server, model, samples dir); recreating
    // it from .env.example on every GUI start wiped those settings and sent
    // Qwen back to the compiled-in defaults.
    if !env_path.exists() {
        let candidates = [
            base.join("resources").join(".env.example"),
            base.join(".env.example"),
            handle
                .path()
                .resource_dir()
                .ok()
                .map(|d| d.join(".env.example"))
                .unwrap_or_default(),
            handle
                .path()
                .resource_dir()
                .ok()
                .map(|d| d.join("resources").join(".env.example"))
                .unwrap_or_default(),
        ];
        let mut created = false;
        for cand in candidates {
            if cand.exists() {
                match std::fs::copy(&cand, &env_path) {
                    Ok(_) => {
                        eprintln!("[NovaTTS] created {}", env_path.display());
                        created = true;
                        break;
                    }
                    Err(e) => eprintln!("[NovaTTS] copy .env.example failed: {e}"),
                }
            }
        }
        if !created {
            let fallback = "NOVATTS_HOST=127.0.0.1\nNOVATTS_PORT=8765\nNOVATTS_QWEN_URL=http://127.0.0.1:8080\nNOVATTS_QWEN_AUTOSTART=1\nNOVATTS_QWEN_AUTO_IMPORT_SAMPLES=1\n";
            let _ = std::fs::write(&env_path, fallback);
            eprintln!("[NovaTTS] wrote minimal {}", env_path.display());
        }
    }

    // Add only keys that are missing; existing values and comments stay
    // untouched, so a user-configured port or path is never reset.
    let content = std::fs::read_to_string(&env_path).unwrap_or_default();
    let mut additions = String::new();
    for (key, value) in [
        ("NOVATTS_HOST", "127.0.0.1"),
        ("NOVATTS_PORT", "8765"),
        ("NOVATTS_QWEN_URL", "http://127.0.0.1:8080"),
        ("NOVATTS_QWEN_AUTOSTART", "1"),
        ("NOVATTS_QWEN_AUTO_IMPORT_SAMPLES", "1"),
    ] {
        let present = content.lines().any(|line| {
            let line = line.trim_start();
            match line.strip_prefix(key) {
                Some(rest) => {
                    let trimmed = rest.trim_start();
                    trimmed.starts_with('=') || rest.starts_with(' ')
                }
                None => false,
            }
        });
        if !present {
            additions.push_str(&format!("{key}={value}\n"));
        }
    }
    if !additions.is_empty() {
        let mut out = content;
        if !out.is_empty() && !out.ends_with('\n') {
            out.push('\n');
        }
        out.push_str(&additions);
        match std::fs::write(&env_path, out) {
            Ok(_) => eprintln!("[NovaTTS] added missing keys to {}", env_path.display()),
            Err(e) => eprintln!("[NovaTTS] could not add defaults to {}: {e}", env_path.display()),
        }
    }
}

/// Platform-specific backend binary name.
const BACKEND_BIN: &str = if cfg!(windows) {
    "novatts-backend.exe"
} else {
    "novatts-backend"
};

fn resource_backend_path(handle: &tauri::AppHandle) -> Option<PathBuf> {
    let candidates = [
        handle
            .path()
            .resource_dir()
            .ok()
            .map(|d| d.join(BACKEND_BIN)),
        handle
            .path()
            .resource_dir()
            .ok()
            .map(|d| d.join("resources").join(BACKEND_BIN)),
        handle
            .path()
            .resource_dir()
            .ok()
            .map(|d| d.join("bin").join(BACKEND_BIN)),
        Some(app_base_dir(handle).join("resources").join(BACKEND_BIN)),
        Some(app_base_dir(handle).join(BACKEND_BIN)),
    ];
    for c in candidates.into_iter().flatten() {
        if c.exists() {
            return Some(c);
        }
    }
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()));
    if let Some(dir) = exe_dir {
        let rel_candidates = [
            format!("resources/{BACKEND_BIN}"),
            BACKEND_BIN.to_string(),
            format!("../resources/{BACKEND_BIN}"),
        ];
        for rel in &rel_candidates {
            let p = dir.join(rel);
            if p.exists() {
                return Some(p);
            }
        }
    }
    None
}

fn dev_backend_path() -> Option<PathBuf> {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let candidates: Vec<PathBuf> = vec![
        // Portable/installer-layout: de exe als naastgelegen resource.
        manifest
            .join("..")
            .join("..")
            .join("resources")
            .join(BACKEND_BIN),
        // Dev: alleen aanwezig na `npm run backend:exe` (PyInstaller). Ontbreekt
        // hij, dan is dat geen fout: start_all.cmd draait de backend al uit de
        // venv en spawn_backend skipt als :8765 al gezond antwoordt.
        manifest
            .join("..")
            .join("..")
            .join("backend")
            .join("dist")
            .join(BACKEND_BIN),
    ];
    for c in candidates {
        if c.exists() {
            return Some(c);
        }
    }
    None
}

/// Is a NovaTTS backend answering on `port`?
///
/// A bare `200` is not enough to identify it: qwentts.cpp's `tts-server`
/// also listens on 8081 and answers `/health` with `{"status":"ok"}`. Only
/// the NovaTTS backend reports the `qwen` field, so require that marker —
/// otherwise a stray (or still-running) tts-server makes us believe the
/// backend is up and we never spawn one, leaving the whole API — including
/// the Perfect Cut window — unreachable.
fn backend_healthy(port: u16) -> bool {
    let url = format!("http://127.0.0.1:{port}/health");
    ureq::get(&url)
        .timeout(Duration::from_millis(600))
        .call()
        .ok()
        .filter(|r| r.status() == 200)
        .and_then(|r| r.into_string().ok())
        .is_some_and(|body| body.contains("\"qwen\""))
}

fn backend_running() -> bool {
    // Dev builds and some configurations historically used 8765,
    // but the backend .env defaults in this repo are 8081.
    // Check both so we don't spawn a second backend instance.
    [8765u16, 8081u16].into_iter().any(backend_healthy)
}

const DEV_FRONTEND_URL: &str = "http://localhost:1420";

fn dev_frontend_up() -> bool {
    ureq::get(DEV_FRONTEND_URL)
        .timeout(Duration::from_millis(700))
        .call()
        .map(|r| r.status() == 200)
        .unwrap_or(false)
}

/// Plain `cargo build`/`cargo run` compiles in Tauri dev mode, which loads
/// `devUrl` (the Vite dev server) from tauri.conf.json. When that server is
/// not running — the common case for `cargo run` without `npx tauri dev` —
/// WebView2 shows a "This page cannot be reached" error and the GUI stays
/// empty. This starts the Vite dev server (npm run dev in ../gui) and then
/// points the window at it, so `cargo run` works standalone. Under
/// `npx tauri dev` / `start_all.cmd` the dev server is already up and this
/// is a no-op.
fn ensure_frontend(handle: &tauri::AppHandle, state: BackendHandle) {
    let handle = handle.clone();
    std::thread::spawn(move || {
        // Grace period: let a dev server started by `tauri dev` come up
        // before we take over anything.
        for _ in 0..6 {
            std::thread::sleep(Duration::from_millis(2000));
            if dev_frontend_up() {
                return;
            }
        }

        let gui_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
        eprintln!(
            "[NovaTTS] frontend dev server not found on {DEV_FRONTEND_URL} — starting it in {}",
            gui_dir.display()
        );

        let mut cmd = if cfg!(windows) {
            let mut c = Command::new("cmd");
            c.arg("/C");
            c.arg("npm run dev");
            c
        } else {
            let mut c = Command::new("sh");
            c.arg("-c");
            c.arg("npm run dev");
            c
        };
        cmd.current_dir(&gui_dir);
        // A release build has no console of its own (see main.rs), so a plain
        // `cmd` here pops a stray CMD window next to the GUI. Suppress it —
        // `eprintln!` is only visible in debug anyway, and the app shows its
        // own state in the dashboard.
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }

        let Ok(child) = cmd.spawn() else {
            eprintln!("[NovaTTS] failed to start `npm run dev`");
            return;
        };
        // Track it so the exit handler can kill it again when the app closes.
        *state.lock().unwrap() = Some(child);

        let deadline = Instant::now() + Duration::from_secs(45);
        while Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(1000));
            if dev_frontend_up() {
                eprintln!("[NovaTTS] frontend dev server ready on {DEV_FRONTEND_URL}");
                if let Some(win) = handle.get_webview_window("main") {
                    if let Ok(url) = DEV_FRONTEND_URL.parse() {
                        let _ = win.navigate(url);
                    }
                }
                return;
            }
            let exited = state
                .lock()
                .unwrap()
                .as_mut()
                .map(|c| c.try_wait().ok().flatten().is_some())
                .unwrap_or(false);
            if exited {
                eprintln!("[NovaTTS] `npm run dev` exited before becoming ready");
                return;
            }
        }
        eprintln!("[NovaTTS] frontend dev server did not become ready in time");
    });
}

fn wait_for_backend(timeout: Duration) -> bool {
    let start = std::time::Instant::now();
    while start.elapsed() < timeout {
        if backend_running() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    backend_running()
}

fn spawn_backend(handle: &tauri::AppHandle, state: BackendHandle) {
    ensure_env(handle);
    if backend_running() {
        eprintln!("[NovaTTS] backend already running on :8765 — skip spawn");
        return;
    }
    // In dev, `target/debug/resources` can hold a sidecar copied by an older
    // build. Prefer the freshly built backend/dist binary there, so
    // `npm run dev:tauri` never silently serves an ancient backend. Release
    // builds always use the bundled resource.
    let bin = if cfg!(debug_assertions) {
        dev_backend_path().or_else(|| resource_backend_path(handle))
    } else {
        resource_backend_path(handle).or_else(dev_backend_path)
    };
    let Some(bin) = bin else {
        eprintln!("[NovaTTS] {BACKEND_BIN} not found (resources/ + dev fallback) — run dev via start_all or build backend");
        return;
    };
    if !bin.exists() {
        eprintln!("[NovaTTS] backend binary missing: {}", bin.display());
        return;
    }
    eprintln!("[NovaTTS] starting backend: {}", bin.display());
    let mut cmd = std::process::Command::new(&bin);
    cmd.current_dir(
        bin.parent()
            .and_then(|p| p.parent())
            .unwrap_or(bin.parent().unwrap()),
    );
    // Installed Linux builds keep user state outside the read-only bundle.
    // Tell the bundled backend where that is, so it does not fall back to
    // `/usr/lib/NovaTTS/data` (deb) or the AppImage mount.
    #[cfg(target_os = "linux")]
    if let Some(base) = linux_state_dir(handle) {
        seed_data_dir(handle, &base);
        let _ = std::fs::create_dir_all(&base);
        cmd.env("NOVATTS_BASE_DIR", &base);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000);
    }
    match cmd.spawn() {
        Ok(child) => {
            eprintln!("[NovaTTS] backend pid {}", child.id());
            *state.lock().unwrap() = Some(child);
            if wait_for_backend(Duration::from_secs(12)) {
                eprintln!("[NovaTTS] backend ready");
            } else {
                eprintln!("[NovaTTS] backend did not become ready in time");
            }
        }
        Err(e) => eprintln!("[NovaTTS] failed to spawn backend: {e}"),
    }
}

fn shutdown_backend() -> Result<(), String> {
    let url = "http://127.0.0.1:8765/shutdown";
    ureq::post(url)
        .timeout(Duration::from_secs(2))
        .call()
        .map(|_| ())
        .map_err(|e| format!("shutdown request failed: {e}"))
}

/// Kill a PID and its whole child tree. On Windows this uses `taskkill /T /F`;
/// on Unix it sends SIGTERM to the process group (negative PID). PyInstaller
/// onefile runs the real code in a child process, so killing just the parent
/// PID can leave the listening process behind.
fn kill_tree(pid: u32) -> bool {
    #[cfg(windows)]
    {
        std::process::Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    }
    #[cfg(unix)]
    {
        // Try the negative-PID kill (process group) first; if that fails, fall
        // back to killing just the PID.
        let pgid_ok = std::process::Command::new("kill")
            .args(["-TERM", &format!("-{pid}")])
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false);
        if pgid_ok {
            return true;
        }
        std::process::Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    }
}

/// PID of the process currently listening on 127.0.0.1:8765, if any.
fn backend_listener_pid() -> Option<u32> {
    #[cfg(windows)]
    {
        let out = std::process::Command::new("netstat")
            .args(["-ano", "-p", "tcp"])
            .output()
            .ok()?;
        let text = String::from_utf8_lossy(&out.stdout);
        for line in text.lines() {
            if line.contains("127.0.0.1:8765") && line.contains("LISTENING") {
                if let Some(pid) = line.split_whitespace().last().and_then(|s| s.parse::<u32>().ok()) {
                    return Some(pid);
                }
            }
        }
        None
    }
    #[cfg(unix)]
    {
        // `ss -ltnp` is available on modern Linux distros. Output format:
        //   LISTEN  0  128  127.0.0.1:8765  ...  users:(("novatts-backend",pid=1234,fd=5))
        let out = std::process::Command::new("ss")
            .args(["-ltnp"])
            .output()
            .ok()?;
        let text = String::from_utf8_lossy(&out.stdout);
        for line in text.lines() {
            if line.contains("127.0.0.1:8765") || line.contains("*:8765") {
                // Extract pid=NNNNN from the users:(...) field.
                if let Some(pos) = line.find("pid=") {
                    let rest = &line[pos + 4..];
                    let num: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
                    if let Ok(pid) = num.parse::<u32>() {
                        return Some(pid);
                    }
                }
            }
        }
        None
    }
}

fn kill_managed(state: &BackendHandle) {
    let managed = {
        let mut guard = state.lock().unwrap();
        guard.take()
    };

    // 1) Graceful: ask the backend to stop itself (it clears caches first).
    let _ = shutdown_backend();

    // 2) App-spawned backend: give it ~2s to exit cleanly, otherwise kill the
    //    whole process tree (covers the PyInstaller child process too).
    if let Some(mut child) = managed {
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            match child.try_wait() {
                Ok(Some(_)) => break,
                Ok(None) if Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(100));
                }
                _ => {
                    let _ = kill_tree(child.id());
                    let _ = child.wait();
                    break;
                }
            }
        }
    }

    // 3) Fallback: if anything still listens on :8765 (e.g. a backend that was
    //    started outside this app, or a PyInstaller sub-tree), force-kill it.
    for _ in 0..3 {
        match backend_listener_pid() {
            Some(pid) => {
                let _ = kill_tree(pid);
                std::thread::sleep(Duration::from_millis(300));
                if backend_listener_pid() == Some(pid) {
                    break; // could not force it down; don't loop forever
                }
            }
            None => break,
        }
    }
}

/// Kill the Vite dev server this app started itself (sh -c / cmd /C npm run
/// dev → node) when it was launched standalone via `cargo run`. It must not
/// survive the app, otherwise node/vite linger after closing the window.
fn kill_frontend(state: &BackendHandle) {
    if let Some(mut child) = state.lock().unwrap().take() {
        let _ = kill_tree(child.id());
        let _ = child.wait();
    }
}

/// Stop the backend and the Vite dev server, at most once per process.
///
/// `tauri.conf.json` declares a second, permanently hidden `cutter` window,
/// and Tauri only emits `ExitRequested`/`Exit` once *every* window is gone.
/// So closing the visible `main` window used to leave this process alive
/// with no window on screen and no cleanup: the backend kept polling the
/// clipboard and Qwen kept holding the GPU. The close handler calls this
/// directly, and the exit hook calls it as a safety net — hence the `Once`.
fn shutdown_all(app: &tauri::AppHandle) {
    SHUTDOWN_ONCE.call_once(|| {
        if let Some(state) = app.try_state::<BackendState>() {
            kill_managed(&state.0);
        }
        if let Some(state) = app.try_state::<FrontendState>() {
            kill_frontend(&state.0);
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend_state: BackendHandle = Arc::new(Mutex::new(None));
    let frontend_state: BackendHandle = Arc::new(Mutex::new(None));
    let backend_state_setup = backend_state.clone();
    let frontend_state_setup = frontend_state.clone();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendState(backend_state))
        .manage(FrontendState(frontend_state))
        .invoke_handler(tauri::generate_handler![
            perfect_cut::open_cutter,
            perfect_cut::read_audio_file,
            perfect_cut::pick_wav,
            perfect_cut::pick_dir,
            perfect_cut::pick_save_wav,
            perfect_cut::pick_exe,
            perfect_cut::pick_model,
            perfect_cut::open_path,
        ])
        .on_window_event(|window, event| {
            // Closing the main window means "quit the app". The hidden
            // `cutter` window keeps the process alive otherwise, and the
            // exit hook that stops the backend never fires.
            //
            // Note: `api.prevent_close()` is deliberately NOT called. Doing
            // so and then closing the window again is what caused the
            // close-hang fixed on 21-26 sep; `app.exit(0)` terminates
            // cleanly without re-entering the handler.
            if window.label() == MAIN_WINDOW
                && matches!(event, tauri::WindowEvent::CloseRequested { .. })
            {
                let app = window.app_handle();
                shutdown_all(app);
                app.exit(0);
            }
        })
        .setup(move |app| {
            // Linux: the native <select> popup is a GTK menu, so it ignores
            // the dark page CSS and follows the GTK theme. Prefer the theme's
            // dark variant for this process only (no system-wide change).
            #[cfg(target_os = "linux")]
            {
                use gtk::prelude::*;
                if let Some(settings) = gtk::Settings::default() {
                    settings.set_gtk_application_prefer_dark_theme(true);
                    eprintln!(
                        "[NovaTTS] GTK dark variant: {}",
                        settings.is_gtk_application_prefer_dark_theme()
                    );
                }
            }

            // Perfect Cut hides on X instead of being destroyed (see
            // perfect_cut::arm_hide_on_close): reopening is then always
            // show()+focus() on the same live webview, never a rebuilt
            // blank surface that no longer answers to close. Main-window
            // close already quits via the on_window_event handler above.
            if let Some(cutter) = app.get_webview_window("cutter") {
                perfect_cut::arm_hide_on_close(&cutter);
            }
            let handle = app.handle().clone();
            let backend_handle = handle.clone();
            let state = backend_state_setup.clone();
            std::thread::spawn(move || spawn_backend(&backend_handle, state));
            // Only dev builds load from the Vite server. In a release bundle
            // the frontend is embedded; probing/starting `npm run dev` there
            // just delays startup and can spawn node on a dev machine.
            if cfg!(debug_assertions) {
                ensure_frontend(&handle, frontend_state_setup);
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(move |app_handle, event| match event {
        // Safety net for the paths that bypass the close handler (taskbar
        // "close all windows", `app.exit(0)`, dev reload). `shutdown_all`
        // is a no-op when the close handler already ran.
        tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => shutdown_all(app_handle),
        _ => {}
    });
}

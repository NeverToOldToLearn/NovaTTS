use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::Manager;

mod perfect_cut;

type BackendHandle = Arc<Mutex<Option<Child>>>;

/// Managed tauri state wrappers — distinct types so both can be registered.
struct BackendState(BackendHandle);
struct FrontendState(BackendHandle);

fn app_base_dir(handle: &tauri::AppHandle) -> PathBuf {
    if let Ok(d) = handle.path().resource_dir() {
        if d.join("data").exists() || d.join("resources").join("novatts-backend.exe").exists() {
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

fn ensure_env(handle: &tauri::AppHandle) {
    let base = app_base_dir(handle);
    let env_path = base.join(".env");

    // Dev runs must be deterministic.
    // If a stale .env exists from a previous run, it may point to ports
    // that collide with qwentts.cpp (usually 8081), causing backend bind
    // failures and the GUI to get stuck.
    //
    // So: always (re)write the dev .env.
    let _ = std::fs::remove_file(&env_path);

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
    for cand in candidates {
        if cand.exists() {
            match std::fs::copy(&cand, &env_path) {
                Ok(_) => {
                    eprintln!("[NovaTTS] created {}", env_path.display());
                    return;
                }
                Err(e) => eprintln!("[NovaTTS] copy .env.example failed: {e}"),
            }
        }
    }
    let fallback = format!(
        "NOVATTS_HOST=127.0.0.1\nNOVATTS_PORT=8765\nNOVATTS_QWEN_URL=http://127.0.0.1:8080\nNOVATTS_QWEN_AUTOSTART=1\nNOVATTS_QWEN_AUTO_IMPORT_SAMPLES=1\n"
    );
    let _ = std::fs::write(&env_path, fallback);
    eprintln!("[NovaTTS] wrote minimal {}", env_path.display());
}

fn resource_backend_path(handle: &tauri::AppHandle) -> Option<PathBuf> {
    let candidates = [
        handle
            .path()
            .resource_dir()
            .ok()
            .map(|d| d.join("novatts-backend.exe")),
        handle
            .path()
            .resource_dir()
            .ok()
            .map(|d| d.join("resources").join("novatts-backend.exe")),
        handle
            .path()
            .resource_dir()
            .ok()
            .map(|d| d.join("bin").join("novatts-backend.exe")),
        Some(app_base_dir(handle).join("resources").join("novatts-backend.exe")),
        Some(app_base_dir(handle).join("novatts-backend.exe")),
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
        for rel in [
            "resources/novatts-backend.exe",
            "novatts-backend.exe",
            "../resources/novatts-backend.exe",
        ] {
            let p = dir.join(rel);
            if p.exists() {
                return Some(p);
            }
        }
    }
    None
}

fn dev_backend_path() -> Option<PathBuf> {
    let candidates: Vec<PathBuf> = vec![
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("backend")
            .join("dist")
            .join("novatts-backend.exe"),
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("backend")
            .join("dist")
            .join("novatts-backend.exe"),
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

        let mut cmd = Command::new("cmd");
        cmd.arg("/C");
        cmd.arg("npm run dev");
        cmd.current_dir(&gui_dir);

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
    let bin = resource_backend_path(handle).or_else(dev_backend_path);
    let Some(bin) = bin else {
        eprintln!("[NovaTTS] novatts-backend.exe not found (resources/ + dev fallback) — run dev via start_all.cmd or build backend");
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

/// Kill a PID and its whole child tree (taskkill /T /F). PyInstaller onefile
/// runs the real code in a child process, so killing just the parent PID can
/// leave the listening process behind.
fn taskkill_tree(pid: u32) -> bool {
    std::process::Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

/// PID of the process currently listening on 127.0.0.1:8765, if any.
fn backend_listener_pid() -> Option<u32> {
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
                    let _ = taskkill_tree(child.id());
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
                let _ = taskkill_tree(pid);
                std::thread::sleep(Duration::from_millis(300));
                if backend_listener_pid() == Some(pid) {
                    break; // could not force it down; don't loop forever
                }
            }
            None => break,
        }
    }
}

/// Kill the Vite dev server this app started itself (cmd /C npm run dev →
/// node) when it was launched standalone via `cargo run`. It must not
/// survive the app, otherwise node/vite linger after closing the window.
fn kill_frontend(state: &BackendHandle) {
    if let Some(mut child) = state.lock().unwrap().take() {
        let _ = taskkill_tree(child.id());
        let _ = child.wait();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend_state: BackendHandle = Arc::new(Mutex::new(None));
    let frontend_state: BackendHandle = Arc::new(Mutex::new(None));
    let backend_state_setup = backend_state.clone();
    let backend_state_events = backend_state.clone();
    let frontend_state_setup = frontend_state.clone();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendState(backend_state.clone()))
        .manage(FrontendState(frontend_state.clone()))
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
        .setup(move |app| {
            let handle = app.handle().clone();
            let backend_handle = handle.clone();
            let state = backend_state_setup.clone();
            std::thread::spawn(move || spawn_backend(&backend_handle, state));
            ensure_frontend(&handle, frontend_state_setup);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(move |app_handle, event| match event {
        tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => {
            let backend = app_handle
                .try_state::<BackendState>()
                .map(|s| s.0.clone())
                .unwrap_or_else(|| backend_state_events.clone());
            kill_managed(&backend);
            if let Some(fs) = app_handle.try_state::<FrontendState>() {
                kill_frontend(&fs.0);
            }
        }
        _ => {}
    });
}

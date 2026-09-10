use std::path::PathBuf;
use std::process::Child;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::Manager;

type BackendHandle = Arc<Mutex<Option<Child>>>;

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
    if env_path.exists() {
        return;
    }
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

fn backend_running() -> bool {
    ureq::get("http://127.0.0.1:8765/health")
        .timeout(Duration::from_millis(600))
        .call()
        .map(|r| r.status() == 200)
        .unwrap_or(false)
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

fn kill_managed(state: &BackendHandle) {
    let mut guard = state.lock().unwrap();
    if let Some(mut child) = guard.take() {
        let _ = shutdown_backend();
        std::thread::sleep(Duration::from_millis(400));
        match child.try_wait() {
            Ok(Some(_)) => {}
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
            }
            Err(_) => {}
        }
    } else {
        let _ = shutdown_backend();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend_state: BackendHandle = Arc::new(Mutex::new(None));
    let backend_state_setup = backend_state.clone();
    let backend_state_events = backend_state.clone();

    let app = tauri::Builder::default()
        .manage(backend_state.clone())
        .setup(move |app| {
            let handle = app.handle().clone();
            let state = backend_state_setup.clone();
            std::thread::spawn(move || spawn_backend(&handle, state));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(move |app_handle, event| match event {
        tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => {
            if let Some(state) = app_handle.try_state::<BackendHandle>() {
                kill_managed(&state);
            } else {
                kill_managed(&backend_state_events);
            }
        }
        _ => {}
    });
}

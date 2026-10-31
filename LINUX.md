# NovaTTS on Linux

Cross-platform support for NovaTTS on Linux (X11, partial Wayland).

## Quick start (development / portable)

```bash
# 1 — Clone the repo
git clone https://github.com/<you>/NovaTTS.git && cd NovaTTS

# 2 — Install everything + build
./installer/install.sh

# 3 — Copy and edit .env
cp backend/.env.example backend/.env
nano backend/.env          # set paths — see "Configuration" below

# 4 — Run
venv/bin/python backend/run.py          # backend on :8765
npm run dev --workspace=gui             # Tauri dev GUI on :1420
```

Or run both at once in the installed Tauri binary (it launches the backend
automatically, same as on Windows).

## System requirements

Tested on Ubuntu 22.04+ / Fedora 38+. The install script handles the apt
packages; on non-Debian distros install the equivalents manually:

| Category | Packages |
|---|---|
| Build | `python3 python3-venv nodejs npm cargo rustc build-essential cmake` |
| Tauri | `libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libayatana-appindicator3-dev patchelf` |
| Runtime | `libportaudio2 ffmpeg` |
| Clipboard | `xclip` (X11) or `wl-clipboard` (Wayland) |
| Auto-forward | `xdotool` (X11 only — see below) |
| GPU engine | `libvulkan-dev vulkan-tools mesa-vulkan-drivers` (for qwentts.cpp Vulkan build) |

## Configuration

The `.env.example` ships with Windows paths. On Linux, typical values:

```ini
# Engine binary (build qwentts.cpp yourself or use a prebuilt)
NOVATTS_QWEN_BIN=~/AI-Tools/qwentts.cpp/build/tts-server
NOVATTS_QWEN_MODEL=~/AI-Tools/qwentts.cpp/models/qwen-talker-1.7b-base-Q8_0.gguf
NOVATTS_QWEN_CODEC=~/AI-Tools/qwentts.cpp/models/qwen-tokenizer-12hz-Q8_0.gguf
NOVATTS_QWEN_CODEC_BIN=~/AI-Tools/qwentts.cpp/build/qwen-codec
NOVATTS_QWEN_SAMPLES_DIR=~/Samples_Clone

# Everything else is the same (URLs, port, audio, etc.)
```

When running as a frozen AppImage or `.deb`, the data directory
(`speakers.json`, cache, logs) lives in `~/.local/share/novatts/` instead of
next to the binary. `NOVATTS_BASE_DIR` in `.env` overrides that.

## Building a release bundle

```bash
./installer/install.sh
# Output in gui/src-tauri/target/release/bundle/:
#   appimage/NovaTTS_2.0.0_amd64.AppImage
#   deb/novatts_2.0.0_amd64.deb
```

`tauri.linux.conf.json` sets the bundle targets to AppImage + deb
automatically — no extra flags needed. The base `tauri.conf.json` stays on
NSIS for Windows, so both platforms build from the same repo.

### What goes into a Linux release

Since you develop on Windows: the easiest Linux release is a **source
bundle** (tarball or zip of the repo + `install.sh`). Linux users are used
to building from source; the script handles all dependencies.

For pre-built binaries, a **GitHub Actions workflow** is included at
`.github/workflows/build.yml`. It builds both Windows (NSIS) and Linux
(AppImage + deb) in parallel on GitHub runners — no Linux machine needed.

Trigger options:
- **Manual**: Actions tab → "Build & Release" → Run workflow
- **Automatic**: push a version tag (`git tag v2.1.0 && git push --tags`)
  — builds both platforms and creates a GitHub Release with all artifacts

The PyInstaller step and Tauri build both run natively on their respective
runners. Cross-compilation is not needed.

## Auto-forward

Auto-forward sends a keystroke to the game window after each spoken line, so
the visual novel advances automatically.

| Platform | How it works |
|---|---|
| Windows | `RegisterHotKey` + `SendInput` via ctypes — full hotkey toggle (F12) |
| Linux X11 | `xdotool key --window <wid> space` — toggle via GUI / API only (no global hotkey) |
| Linux Wayland | Not supported — compositors block synthetic keyboard input by design |

Install `xdotool` for X11 support. On Wayland a single log line is printed at
startup and the feature is disabled.

## Known limitations

- **Wayland auto-forward**: compositors (GNOME, Sway, etc.) reject
  `xdotool`'s `XSendEvent`. There is no stable workaround; run under X11 or
  Xwayland for auto-forward.
- **Global hotkey on Linux**: `RegisterHotKey` has no direct equivalent;
  auto-forward is toggled through the GUI or `POST /auto-forward/toggle`.
- **PyInstaller**: the `.spec` file must be built on a Linux machine (no
  cross-compilation from Windows). CI or a VM is the way to go.
- **Clipboard on Wayland**: `pyperclip` works via `wl-paste`/`wl-copy`
  (install `wl-clipboard`). Some Wayland compositors restrict background
  clipboard access — the app may need focus or a portal.

## Files changed for Linux support

| File | What |
|---|---|
| `gui/src-tauri/src/lib.rs` | Platform-aware backend binary name, `kill_tree` (SIGTERM), `ss` for port detection, `sh -c` for dev frontend |
| `gui/src-tauri/src/perfect_cut.rs` | File picker shows all files on Linux (no `.exe` filter) |
| `gui/src-tauri/tauri.linux.conf.json` | Tauri platform override: AppImage + deb targets, Linux resource paths |
| `backend/novatts/auto_forward.py` | X11 support via xdotool, Wayland detection |
| `backend/novatts/cutter.py` | Bug fix: missing `import os` |
| `backend/novatts/voice_design.py` | Removed hardcoded Windows fallback path |
| `backend/novatts/tts/spk_rvq.py` | Platform-neutral error messages |
| `installer/install.sh` | Build script aligned with `tauri.linux.conf.json` |

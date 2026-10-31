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
| GPU engine | `libvulkan-dev glslc spirv-headers vulkan-tools mesa-vulkan-drivers` (for the qwentts.cpp Vulkan build) |

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

When running as a frozen AppImage or `.deb`, the app cannot write next to the
binary (`/usr/lib/NovaTTS` and the AppImage mount are read-only). User state
then lives in `~/.local/share/novatts/` (or `$XDG_DATA_HOME/novatts/`):

```ini
~/.local/share/novatts/.env      # settings written by the GUI
~/.local/share/novatts/data/     # speakers.json, cache, logs, games
```

On first run the bundled default `data/` is copied there; existing files are
never overwritten. A portable build (unpacked, writable directory) still keeps
everything next to the app, like on Windows. `NOVATTS_BASE_DIR` in the
environment overrides the location for both the GUI and the backend.

## Building qwentts.cpp with Vulkan

NovaTTS needs a running `tts-server` from
[qwentts.cpp](https://github.com/ServeurpersoCom/qwentts.cpp). On Ubuntu/Debian:

```bash
sudo apt install libvulkan-dev glslc spirv-headers vulkan-tools mesa-vulkan-drivers
cd /path/to/qwentts.cpp
./models.sh                                  # downloads both GGUF files (~2.3 GB)
cmake -B build -DGGML_VULKAN=1 -DGGML_AVX512=OFF
cmake --build build -j$(nproc)
```

Check the GPU is visible before starting NovaTTS:

```bash
vulkaninfo --summary | grep deviceName
./build/tts-server --model models/qwen-talker-1.7b-base-Q8_0.gguf \
                   --codec models/qwen-tokenizer-12hz-Q8_0.gguf
# log must say: Talker backend: Vulkan0
```

If `glslc`/`libvulkan-dev`/`spirv-headers` cannot be installed system-wide (no
root), extract the `.deb`s into a prefix and point CMake at it. `glslc` also
needs `libshaderc1`, so wrap it to set `LD_LIBRARY_PATH`:

```bash
PREFIX=~/.local/opt/vulkan-dev
mkdir -p "$PREFIX" /tmp/vkpkgs && cd /tmp/vkpkgs
apt-get download libvulkan-dev glslc libshaderc1 spirv-headers
for d in *.deb; do dpkg-deb -x "$d" "$PREFIX"; done
ln -sf /usr/lib/x86_64-linux-gnu/libvulkan.so.1 "$PREFIX/usr/lib/x86_64-linux-gnu/libvulkan.so.1"
mkdir -p "$PREFIX/wrappers"
printf '#!/bin/sh\nexport LD_LIBRARY_PATH=%s/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}\nexec %s/usr/bin/glslc "$@"\n' "$PREFIX" "$PREFIX" > "$PREFIX/wrappers/glslc"
chmod +x "$PREFIX/wrappers/glslc"

cd /path/to/qwentts.cpp
cmake -B build -DGGML_VULKAN=1 -DGGML_AVX512=OFF \
  -DCMAKE_PREFIX_PATH="$PREFIX/usr;$PREFIX/usr/share/cmake" \
  -DVulkan_INCLUDE_DIR="$PREFIX/usr/include" \
  -DVulkan_LIBRARY="$PREFIX/usr/lib/x86_64-linux-gnu/libvulkan.so" \
  -DVulkan_GLSLC_EXECUTABLE="$PREFIX/wrappers/glslc"
cmake --build build -j$(nproc)
```

Then set `NOVATTS_QWEN_BIN`, `NOVATTS_QWEN_MODEL`, `NOVATTS_QWEN_CODEC` and
`NOVATTS_QWEN_CODEC_BIN` in `.env` (see above); NovaTTS starts and stops
`tts-server` itself.

## Building a release bundle

```bash
./installer/install.sh
# Output in gui/src-tauri/target/release/bundle/:
#   appimage/NovaTTS_2.0.0_amd64.AppImage
#   deb/NovaTTS_2.0.0_amd64.deb
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
| Linux X11 | `xdotool windowactivate` + XTEST Space (XSendEvent fallback) — toggle via GUI / API only (no global hotkey) |
| Linux Wayland | X11/Xwayland windows only (set a target window in the GUI); native Wayland clients cannot receive synthetic input |

Install `xdotool` for X11 support. `xdotool` is detected when the backend
starts, so restart NovaTTS after installing it. In a Wayland session the
backend logs that only X11/Xwayland windows are reachable.

Configure it in **Settings → Auto-forward (RenPy)**: enable the toggle, set a
target window title (type it, use **Capture** after focusing the game, or pick
one from **List windows**), and optionally tune the delay. **Send test Space**
verifies the target before you rely on it. The same controls are available over
HTTP:

| Endpoint | Purpose |
|---|---|
| `GET /auto-forward` | current state, platform, xdotool/display availability |
| `POST /auto-forward` | `{enabled?, target?, delay?}` — apply and persist to `.env` |
| `POST /auto-forward/toggle` | flip enabled |
| `POST /auto-forward/capture` | capture the foreground X11 window title |
| `GET /auto-forward/windows` | list visible X11/Xwayland window titles |
| `POST /auto-forward/test` | send one test Space to the configured target |

Auto-forward runs off the clipboard pipeline only (not `/speak` or the OpenAI
endpoint), and only fires when a line played to its end: a newer clipboard line
interrupts playback and suppresses the keystroke.

## Known limitations

- **Wayland auto-forward**: most games run as X11 clients under Xwayland, so
  activating their window and sending XTEST Space works when you set a target
  window. Native Wayland clients are invisible to `xdotool` and cannot receive
  synthetic input; the backend logs that no window matched.
- **Global hotkey on Linux**: `RegisterHotKey` has no direct equivalent;
  auto-forward is toggled through the GUI or `POST /auto-forward/toggle`.
- **PyInstaller**: the `.spec` file must be built on a Linux machine (no
  cross-compilation from Windows). CI or a VM is the way to go.
- **Clipboard on Wayland**: `pyperclip` works via `wl-paste`/`wl-copy`
  (install `wl-clipboard`). Some Wayland compositors restrict background
  clipboard access — the app may need focus or a portal.

## Troubleshooting

- **Moved the checkout?** Cargo remembers absolute paths and Python venvs
  are not relocatable. A release build can then fail with
  `failed to read plugin permissions` pointing at the old directory. Fix:
  `cargo clean --release` inside `gui/src-tauri` (or delete
  `gui/src-tauri/target`). `install.sh` detects a relocated venv from
  `pyvenv.cfg` and recreates it, and always calls `python -m PyInstaller
  --clean`, so stale console scripts or analysis caches cannot break the
  backend build.
- **Settings do not stick / speakers disappear** on an installed build:
  user state must be writable. Check `~/.local/share/novatts/.env` and
  `~/.local/share/novatts/data/`, or point `NOVATTS_BASE_DIR` at a writable
  directory in the environment.
- **App starts but auto-forward does nothing**: under a Wayland session only
  X11/Xwayland game windows can receive input; capture a target window in the
  GUI first. For native Wayland games there is no workaround — run the game
  with `SDL_VIDEODRIVER=x11` (Xwayland). `xdotool` must be installed.

## Files changed for Linux support

| File | What |
|---|---|
| `gui/src-tauri/src/lib.rs` | Platform-aware backend binary name, XDG data dir for read-only installs, `kill_tree` (SIGTERM), `ss` for port detection, `sh -c` for dev frontend |
| `gui/src-tauri/src/perfect_cut.rs` | File picker shows all files on Linux (no `.exe` filter) |
| `gui/src-tauri/tauri.linux.conf.json` | Tauri platform override: AppImage + deb targets, Linux resource paths |
| `backend/novatts/config.py` | Frozen Linux builds fall back to `$XDG_DATA_HOME/novatts` when the bundle is read-only |
| `backend/novatts/main.py` | `/settings` reports the same `.env` it writes; auto-forward wired into the clipboard pipeline + HTTP endpoints |
| `backend/novatts/auto_forward.py` | X11 support via xdotool, Wayland detection, status/window-list helpers |
| `backend/novatts/cutter.py` | Bug fix: missing `import os`; Linux ffmpeg/whisper paths |
| `backend/novatts/voice_design.py` | Removed hardcoded Windows fallback path |
| `backend/novatts/tts/spk_rvq.py` | Platform-neutral `.exe` handling and error messages |
| `installer/install.sh` | Build script aligned with `tauri.linux.conf.json` |

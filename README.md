# NovaTTS

Local Visual Novel Text-to-Speech server. Reads RenPy `copy_voice_to_clipboard`
output from the clipboard (`Name: Text`), resolves the speaker from a JSON
registry, synthesizes speech with a local Qwen3-TTS (qwentts.cpp) engine, and
plays it — all on-device.

## Installer (schoon systeem)

> **Download → dubbelklik → klaar.** Geen Python/Node nodig op het doelsysteem.

Gebouwd met **Tauri NSIS** (GUI + backend in één `.exe`):

```powershell
# Bouwen (vereist Rust + Node, één keer op dev machine):
cd backend && .\.venv\Scripts\pyinstaller Novabackend.spec --noconfirm
cd ..\gui && npm run tauri build
# Output: gui\src-tauri\target\release\bundle\nsis\NovaTTS_2.0.0_x64-setup.exe  (~25 MB)

# Of via npm:
npm run installer        # ZIP + Inno Setup (als Inno geïnstalleerd)
npm run installer:zip    # alleen portable ZIP
```

De Tauri GUI **start `resources/novatts-backend.exe` automatisch** (geen `start_all.cmd`
nodig) en maakt `.env` uit `.env.example` aan bij eerste run. Sluiten → backend
wordt netjes afgesloten (`POST /shutdown`). Op een schoon systeem hoeft alleen
`backend\.env` (Qwen paden) aangepast te worden als modellen/samples elders staan
— default `NOVATTS_QWEN_URL=http://127.0.0.1:8080`.

Vervanging voor `D:\Projects\NovaTemp\...NovaTTS_2.0.0_x64-setup.exe` staat al klaar
in `gui\src-tauri\target\release\bundle\nsis\` (ook gekopieerd naar `NovaTemp`).

## Development / portable (zonder installer)

```powershell
# One-click (bouwt venv+npm, shortcuts):
.\Install.cmd            # of .\setup.ps1 -Shortcuts
.\start_all.cmd          # default --min (backend + GUI)

# Na verhuizing / cloud-sync (fix kapotte venv):
.\start_all.cmd --repair  # of .\setup.ps1 -Force

# Handmatig:
.\setup.cmd              # of npm run setup
backend\.venv\Scripts\python.exe backend\run.py   # http://127.0.0.1:8765
npm run dev --workspace=gui                        # http://localhost:1420
```

## Qwen3-TTS (extern, optioneel)

Default `http://127.0.0.1:8080` (qwentts.cpp). Modellen worden **niet** meegebundeld
(GBs) — extern via `backend\.env`:

```ini
NOVATTS_QWEN_BIN=D:\Projects\qwentts.cpp\build\Release\tts-server.exe
NOVATTS_QWEN_MODEL=E:\LLM's\Qwen3TTS\qwen-talker-1.7b-base-Q8_0.gguf
NOVATTS_QWEN_CODEC=E:\LLM's\Qwen3TTS\qwen-tokenizer-12hz-Q8_0.gguf
NOVATTS_QWEN_SAMPLES_DIR=D:\!!Scripts!!\Samples_Clone
```

Zonder Qwen draait de server gewoon; `/health` geeft `"qwen": false`.

## Build checks

```powershell
npm run build
backend\.venv\Scripts\python -m ruff check backend
backend\.venv\Scripts\python -m mypy --strict backend/novatts
```

## Layout

```
backend/   Python 3.11 + FastAPI → dist/novatts-backend.exe (PyInstaller)
gui/       Svelte 5 + Vite + Tauri 2 (bundle met backend + data)
data/      speakers.json, games/, blacklist, emotions, cache
installer/ Inno Setup fallback + Build-Installer.ps1 (ZIP)
```

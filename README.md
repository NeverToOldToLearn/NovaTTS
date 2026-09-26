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
# qwen-codec.exe voor pre-extractie van .spk/.rvq stemrefs (leeg = naast tts-server.exe)
NOVATTS_QWEN_CODEC_BIN=D:\Projects\qwentts.cpp\build\Release\qwen-codec.exe
```

Zonder Qwen draait de server gewoon; `/health` geeft `"qwen": false`.

## .spk/.rvq pre-extractie (snelle stemimport)

NovaTTS importeert de samples-map bij elke Qwen-start. Stemmen met een
pre-geëxtraheerd `.spk`+`.rvq` paar worden via `spk_b64`/`rvq_b64` verbatim
geregistreerd — **geen GPU-extractie per stem**, enkel base64 upload. Paren
worden op `.spk`/`.rvq` zelf gevonden, dus de bron-`.wav` mag verwijderd
worden zodra het paar bestaat. Wavs zónder paar vallen terug op `wav_b64`
(server-side extractie), dus alles blijft werken.

Via GUI **Settings → Voice Samples → "Pre-extract .spk/.rvq"** (of
`POST /qwen/convert-samples`, `?force=1` voor her-extractie) draait de app
zelf `qwen-codec.exe` voor de overige wavs — dezelfde output als
`Convert-WavToSpkRvq.ps1`. `import_status.pairs` / `.unpaired` tonen de
vooruitgang.

## Perfect Cut (sample cutter)

GUI → **Settings → Tools → "Open Perfect Cut"**. De tkinter/matplotlib tool is
vervangen door een eigen Tauri-venster (`index.html#/cutter`) in dezelfde
Svelte-app, zodat thema, fonts en controls identiek zijn. **Geen sidebar-item**:
het is een tool die je openzet als je samples klaarzet, geen permanently view.

Twee tabs:

- **Sample Cutter** — waveform + dBFS-weergave met selectie, sleep-to-select,
  playhead, keyboard-transport, en export via ffmpeg naar WAV.
  Uitvoermodi: `qwen` (24 kHz mono PCM16 + loudnorm), `native` (24 kHz mono),
  `keep` (originele sample rate). Zonder ffmpeg valt de export terug op een
  stdlib `wave`-cutter.
- **Dataset Prep** — de oude VoiceClonePrep-TTS: batch `silenceremove+loudnorm`
  over een map wavs, daarna `whisper-cli` per bestand, plus het transcript.
  Draait server-side op een daemon thread, dus de voortgang overleeft het
  sluiten van het venster (`GET /cutter/batch/status`).

**Auto-select utterance** is een port van `edgelock_snap.py` (in de tkinter
versie dood code). De detector (50 ms/25 ms windowed RMS, Otsu-drempel,
gap-merge, hangover, zero-cross + stilte-align) draait nu in TypeScript in
`gui/src/lib/cutter/edgelock.ts` — geen extra Python-dependencies, geen
bestandsupload, en de `← Previous` / `Auto-select next utterance` /
`Snap to quiet frame` knoppen werken direct op de gedetecteerde utterances.
De Whisper/Qwen-zware stappen blijven server-side.

Instellingen staan in `data/perfect_cut.json` (gescheiden van `.env`), met
auto-detectie voor `ffmpeg`, `whisper-cli` en het model. Backend-routes:
`/cutter/*` in `backend/novatts/cutter_api.py`.

> De Python `Perfect Cut v2/`-map is de oude tkinter-versie en wordt nergens
> meer geïmporteerd; de backend leest de oude `cutter_config.json` **niet** en
> migreert die niet.

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

# NovaTTS

Local Visual Novel Text-to-Speech server. Reads RenPy `copy_voice_to_clipboard`
output from the clipboard (`Name: Text`) — or, preferably, the live game text
straight from LunaTranslator/Textractor over a websocket (`Name Text`) — resolves
the speaker from a JSON registry, synthesizes speech with a local Qwen3-TTS
(qwentts.cpp) engine, and plays it — all on-device.

## Pipeline

```
   game window
        │
        ├─ Textractor ─ws─► LunaAdapter ──► HookTextProcessor ──┐   ← primary
        │  (LunaTranslator)   127.0.0.1:6677   (parse+dedup)      │     since F8
        │                                                        │
        ├─ output file ──────► FileMonitorAdapter ──────────────┤
        │                                                        ├─► parse ──► gate ──► dialogue-worker
        └─ RenPy copy_voice_to_clipboard ──► ClipboardAdapter ──┘       (luna)     (trust,     │   (Qwen3-TTS,
                                                                     renpy)     dedup,      │    thread)
                                                                                   blacklist) ▼
                                                                        speaker registry ──► voice
```

Four things about that picture are load-bearing, not incidental:

- **Every source goes through the same parser.** The websocket and file routes
  share one `HookTextProcessor`, so a line cannot be read two different ways
  depending on which hook delivered it. The clipboard route keeps the RenPy
  parser, because RenPy really does send `Name: Text`.
- **Nothing synthesises inside the websocket handler.** The handler's only job
  is to hand a dialogue to the single dialogue-worker thread. Synthesis inside
  the async handler would block the event loop for up to the Qwen timeout (300 s)
  and every other client would simply stop being served.
- **The gate is shared too.** `DialogueGate` decides speaker trust, dedup and
  blacklisting once, so a line cannot be admitted on one route and rejected on
  another.
- **The clipboard route is last, not gone.** It is the fallback for a game with
  no hook at all — see [Migrating from RenPy](#migrating-from-renpy).

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

## Hook input (LunaTranslator / Textractor)

NovaTTS can take its raw text from three sources. Which one is active is set
with `NOVATTS_HOOK_MODE` in `backend/.env`:

| Value | Route | Notes |
|---|---|---|
| `websocket` | LunaHook / Textractor | **the default since F8** — live text, a speaker per turn |
| `clipboard` | RenPy `copy_voice_to_clipboard` | the legacy route — kept deliberately, still fully supported, still tested |
| `both` | both side by side, first yield wins | useful while checking the hook against a route you already trust |

An unrecognised value falls back to `both` with a logged warning rather than
refusing to start, so a typo cannot lock you out of the app. That fallback is
deliberately *not* the default: the default answers "what should a fresh
install use" (the better route), the fallback answers "what should happen when
this setting is unreadable" (the route that breaks least). Syncing the two would
mean a typo silently removing the source you were relying on.

The dashboard's **Hook** card tells you which of three situations you are in,
because they need different fixes and none of them looks like "not connected":

| Card says | What it means | Do this |
|---|---|---|
| `waiting` · *LunaTranslator not connected* | nobody is attached to the socket | start LunaTranslator, add `textractor_websocket_x64.xdll`, point it at the address shown |
| `N clients` · *connected, no line yet* | the socket is fine, the game is not | attach the hook to the **game window**; the card turns into a warning as long as nothing arrives |
| `N clients` · *N dropped* | lines are arriving but synthesis cannot keep up | pause the game, or lower the voice latency |

`hook_mode` and `hook_port` are read once at start, so changing either needs a
restart of the backend — the same rule that already applied to `hook_host`. The
settings view says so next to the field.

### Setting up LunaHook

1. Start NovaTTS. It **serves** the websocket on `127.0.0.1:6677`.
2. In LunaTranslator: `Extensions` → `Add` → `textractor_websocket_x64.xdll`.
3. Point it at `ws://127.0.0.1:6677` and start Textractor on your game.
4. Leave **translation off** — NovaTTS only wants the raw text.

If the connection fails, a WinHTTP proxy on Windows will intercept even
loopback traffic. Check with `netsh winhttp show proxy`; the fix is
`netsh winhttp reset proxy` (admin).

### Hook settings

| Variable | Default | Meaning |
|---|---|---|
| `NOVATTS_HOOK_MODE` | `websocket` | `clipboard` / `websocket` / `both` |
| `NOVATTS_HOOK_HOST` | `127.0.0.1` | websocket bind address — keep on loopback |
| `NOVATTS_HOOK_PORT` | `6677` | websocket port |
| `NOVATTS_HOOK_SPACE_FORM` | `1` | Textractor sends `Rick It's 2 parts.` (space form). Set to `0` only for `Rick:`-style games — the RenPy parser is tried first regardless. |
| `NOVATTS_HOOK_DUAL_HOOK` | `0` | attach the hook twice; some games need it, but it doubles traffic |
| `NOVATTS_LUNA_WS_URL` | *(empty)* | empty = serve; non-empty (e.g. `ws://127.0.0.1:6678`) = connect to that instead |
| `NOVATTS_FILE_WATCH` | `0` | tertiary route: tail a Textractor output file. Independent of `hook_mode`; off means no file is ever read |
| `NOVATTS_FILE_WATCH_PATH` | `textractor_output.txt` | path for that file route |
| `NOVATTS_DEDUP_WINDOW_MS` | `500` | drop an identical line repeated within this window (Textractor re-emits on window change and re-focus) |

> `hook_host` is shown in the settings view but is **not** editable there:
> it is the websocket bind address, and changing it live would need the
> server restarted to take effect.

### Qwen may start before anything arrives

`qwen_autostart` is deliberately **not** hook-aware: the Qwen server starts with
the backend regardless of `hook_mode`, so with `websocket` and nobody attached
you are paying for a model that has no line to speak yet. That is on purpose.
Qwen is also started by the dashboard's **Test TTS** button, by Perfect Cut and
by `POST /v1/audio/speech` — making autostart wait for a hook client would break
all three, or would mean the same rule in three places.

If that trade is wrong for your machine, set `NOVATTS_QWEN_AUTOSTART=0` in
`backend/.env` and start Qwen yourself (`start_qwen.cmd`).

### The file route in one paragraph

`NOVATTS_FILE_WATCH=1` makes NovaTTS poll `NOVATTS_FILE_WATCH_PATH` and
parse every **new line** with exactly the same parser the websocket route
uses. Both writers that occur in practice work: a scratch file overwritten
with the current line, and a log that only grows. The one shape it does not
recover on its own is a writer that puts a name and its text on separate
lines — `"Rick"` then `"Answer the door."` is two lines, and the name has no
body to attach to. Set `NOVATTS_HOOK_DUAL_HOOK=1` and the two lines rejoin.

## Migrating from RenPy

If your game used `copy_voice_to_clipboard`, **nothing breaks.** The RenPy
route is still in the build, still tested, and one setting away. What changed
is which route is the default — so if you upgrade and hear nothing, you almost
certainly have no hook attached, and the fix is not a reinstall.

**Do you need to change anything?**

| Your situation | What to do |
|---|---|
| RenPy game, no hook, works today | nothing — but set `NOVATTS_HOOK_MODE=clipboard` in `backend/.env`, because the default is now `websocket` and a RenPy game sends nothing on the socket |
| willing to run LunaTranslator | set it to `websocket` (or leave the default) and add the `.xdll` — you get live text, a speaker per turn, and the multi-speaker split |
| want to check the new route before committing | `both`, then watch the Hook card: it tells you whether lines are arriving at all |
| Perfect Cut / `.spk` pipeline | unaffected; that reads files, not the clipboard |

**How to tell which one you are on:** the settings view shows the current
`hook_mode`, and the startup log names the adapter it started. Look for
`Clipboard adapter started (poll 0.25s) -- legacy RenPy route` or
`Hook server listening on ws://…`.

**What you gain on the hook:** a speaker per turn. The clipboard carries one
line, so `Anne Hallo! Rick Mooi.` arrives as narration with two names in it.
The hook splits it into two turns and can give each its own voice. The
clipboard format has already thrown that information away before NovaTTS sees
it, so no amount of parsing gets it back.

**What you lose:** nothing, as long as you set the mode explicitly. The one
real difference is that the clipboard route needs no extra process — which is
exactly why it stays in the build instead of being deleted.

## Build checks

```powershell
backend\.venv\Scripts\python -m pytest backend\tests\ -q
backend\.venv\Scripts\python -m ruff check backend
backend\.venv\Scripts\python -m mypy --strict backend/novatts
npm run check          # svelte-check — the GUI's type gate
npm run build
```

All five must be clean, and they are set up to fail: `make gate` runs lint
(which is ruff + mypy + svelte-check) and test without exit-code suppression,
and `npm run lint` chains the GUI and Python checks with `&&`, so a failure in
either language is a failure. A regression stops the build rather than
scrolling past in the output.

## Layout

```
backend/   Python 3.11 + FastAPI → dist/novatts-backend.exe (PyInstaller)
gui/       Svelte 5 + Vite + Tauri 2 (bundle met backend + data)
data/      speakers.json, games/, blacklist, emotions, cache — zie data/README.md
installer/ Inno Setup fallback + Build-Installer.ps1 (ZIP)
```

`data/` bevat geen audio. De emotion fragments lever je zelf aan: zet je eigen
bestanden in de map die je bij Instellingen → Emotion sounds instelt. Alles wat
jouw bibliotheek of jouw game beschrijft staat local-only en wordt niet meegebouwd;
de app maakt die bestanden zelf aan. De formaatvoorbeelden staan in
`data/*.json.example`.

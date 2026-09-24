# ULTIMATE PROMPT - NovaTTS: Universal Visual Novel TTS Server (Local)

## 0. BESLISSINGEN (VASTGELEGD)
- Projectnaam: **NovaTTS** → `D:\Projects\NovaTTS`
- TTS Engine: **Qwen3-TTS (GPU)** via qwentts.cpp HTTP server `http://127.0.0.1:8081`
  (default 8080 is taken by SearXNG docker; run `tts-server.exe ... --port 8081`)
- Input V1: **Alleen Clipboard (RenPy)**. Luna Hook/Textractor = V2 (adapter-ready).
- GUI: **Tauri + Svelte** (lichtgewicht, native).
- Backend: **Python 3.11 + FastAPI**.

## 1. VISIE
Lokale, universele, lichtgewicht VN Text-to-Speech server. Standaard blijft het 23-regel POC-principe:
*poll clipboard → parse → synth → play*. Maar dan modulair en schaalbaar. Een-op-een onderhoud door 1 persoon.
Geen 4588 regels spaghetti, geen 20 variant files.

## 2. CORE PRINCIPES (NIET ONDERHANDELBAAR)
- **KISS:** Max 500 regels per module. Geen god-script.
- **Maintainable:** Strikte indentatie (4 spaces), type hints, ruff (linter), ruff format. `flake8 --max-line-length=100` + `mypy --strict`.
- **Separation of Concerns:** `adapter → parser → registry → tts → player` zijn losse modules met enkel interfaces ertussen.
- **Fail-safe:** Foute speaker-detectie mag NOOIT een stem permanent op GPU koppelen. Unknown → `Narrator`, nooit nieuwe voice slot.
- **No pycache/venv in repo.** `.gitignore` verplicht.

## 3. PROJECTSTRUCTUUR (NOVA TTS)
```
D:\Projects\NovaTTS\
├── backend\
│   ├── novatts\
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app (entrypoint)
│   │   ├── config.py            # settings via pydantic-settings + .env
│   │   ├── models.py            # dataclasses: Dialogue, SpeakRequest
│   │   ├── adapters\
│   │   │   ├── __init__.py
│   │   │   ├── base.py          # InputAdapter (abstract)
│   │   │   ├── clipboard.py     # ClipboardAdapter (RenPy, V1)
│   │   │   └── luna.py          # LunaAdapter (V2 placeholder, ws://127.0.0.1:6677)
│   │   ├── parser\
│   │   │   ├── __init__.py
│   │   │   ├── renpy.py         # RenPyParser (Strict: "Name: Text")
│   │   │   └── luna.py          # LunaParser (V2 placeholder)
│   │   ├── registry\
│   │   │   ├── __init__.py
│   │   │   └── speakers.py      # SpeakerRegistry (JSON single source of truth)
│   │   ├── tts\
│   │   │   ├── __init__.py
│   │   │   ├── base.py          # TTSBackend (abstract)
│   │   │   ├── qwen.py          # Qwen3Backend (HTTP client 127.0.0.1:8080)
│   │   │   └── voice_manager.py # VoiceManager (per-request voice inject, no GPU leak)
│   │   ├── player\
│   │   │   ├── __init__.py
│   │   │   └── audio.py         # AudioPlayer (queue via pygame.mixer)
│   │   └── llm\                 # (optioneel) instruct suggestie
│   │       └── __init__.py
│   ├── requirements.txt
│   ├── pyproject.toml           # ruff + mypy config
│   └── .env.example
├── gui\                          # Tauri 2.0 + Svelte 5
│   ├── src\
│   │   ├── App.svelte
│   │   ├── lib\
│   │   │   ├── api.ts          # fetch wrapper naar FastAPI
│   │   │   ├── components\
│   │   │   │   ├── Dashboard.svelte
│   │   │   │   └── SpeakersPanel.svelte
│   │   │   └── types.ts
│   │   ├── vite-env.d.ts
│   │   └── main.ts
│   ├── src-tauri\
│   │   ├── Cargo.toml
│   │   ├── tauri.conf.json
│   │   ├── build.rs
│   │   └── src\main.rs         # sidecar: start/stop backend
│   ├── package.json
│   ├── svelte.config.js
│   └── vite.config.ts
└── data\
    ├── speakers.json            # SpeakerRegistry seed
    └── emotion_patterns.json    # port from D:\Projects\emotion_patterns.json
```
> **Bronnen voor port (bestaande, werkende code):**
> - `D:\Projects\QwenTTS\src\clipboard_monitor.py` → ClipboardAdapter + polling pattern (0.25s, dedup via last_clipboard, extract dialogue)
> - `D:\Projects\tts_engine.py` → TTSBackend (Qwen3Backend class is exact template)
> - `D:\Projects\QwenTTS\src\audio_player.py` → AudioPlayer (queue + pygame)
> - `D:\Projects\emotion_patterns.json` + `D:\Projects\emotion_sound_map.json` → emotion audio overlay
> - `D:\Projects\VisualNovelTTS.py` L140-199 → blacklist (is_blacklisted) logica (V2)

## 4. INPUT: CLIPBOARD ADAPTER (V1 - RENPY)
- Poll `pyperclip.paste().strip()` elke **0.25s** in daemon thread.
- Dedup: sla `last_clipboard` op; gelijk → skip.
- Output normalisatie: `Dialogue(speaker: str | None, text: str, source: "renpy")`.
- Filter: lege tekst, `len < 3`, of tekst die op `Traceback`/Ren'Py exception dump lijkt → skip.
- Errors in loop mogen de thread NOOIT killen (`except Exception: sleep; continue`).

### RenPyParser (strikt)
- Regex: `^\s*(?P<speaker>[^:]+)\s*:\s*(?P<line>.+?)\s*$`
- `speaker` moet hoofdletter starten (`[A-Z]`), anders → speaker=None (Narrator).
- Alles vóór de **eerste** `:` is naam; tekst = rest. GEEN split op midden-zin `:`.
- `(narrator)` parenthesized naam → ook Narrator.

## 5. SPEAKER REGISTRY (JSON single source of truth)
- `data/speakers.json` formaat:
```json
{
  "versions": 1,
  "speakers": {
    "Narrator": {"voice": "default", "instruct": "", "emotion": "neutral"},
    "Rick": {"voice": "rick", "instruct": "deep male voice, gruff", "emotion": "neutral"}
  }
}
```
- **Alleen RenPy mag auto-registreren**, en alleen via expliciete service-methode `register(name)`. Luna (V2) vraagt altijd om GUI-confirmatie.
- Onbekende naam → fallback `Narrator`, met log warning. **NOOIT** willekeurige voice-slot aanmaken.
- Mutaties alleen via `SpeakerRegistry` (thread-safe lock). Save pas na expliciete GUI-actie of auto-save interval (30s).

## 6. TTS ENGINE: QWEN3 (GPU) ZONDER LEAK
Probleem uit verleden: Qwen laadt stemmen op GPU en koppelt ze, override lekt na tijd → herstart nodig.
Oplossing:
- `Qwen3Backend` is STATELESS HTTP-client: elke `POST /v1/audio/speech` geeft `voice`, `seed`, `temperature` mee. Geen GPU-state in backend.
- `VoiceManager` doet per request: `speaker → voice_id` lookup in registry → inject in payload. Nooit hergebruiken van vorige bevriezende state.
- Signatuur: `synthesize(dialogue: Dialogue) -> Path`, met output als `<cache_dir>/<md5(text+voice+instruct)>.wav`.
- **md5 cache** (port uit `QwenTTS/src/tts_manager.py` L74): zelfde tekst+stem+instruct → zelfde audio, geen GPU-hit.
- Queue: audio player speelt 1 geluid tegelijk (deque), geen overlap (port uit audio_player.py).
- Health-check: `GET /health` van qwentts.cpp. Is Qwen down → status endpoint meldt "Qwen offline", geen crash.

## 7. FASTAPI SERVER (main.py)
Endpoints:
- `GET  /health` → `{"status": "ok", "qwen": true|false}`
- `GET  /status` → server status, actieve speakers, queuesize, qwen health, current audio
- `POST /speak`  → body `{"speaker": "Rick", "text": "Hi all.", "instruct": ""}` → synthesize + play, returns `{"status": "queued"}`. Ontbrekende speaker → Narrator.
- `GET  /speakers` → registry dump (redacted: voice ids ok, geen instruct om privacy?)* → Nee: gewoon full.
- `POST /speakers` → register speaker ([renpy-auto] allowed)
- `PATCH /speakers/{name}` → update `instruct` / `emotion`
- `WS   /ws` → events (dialogue received, queued, playing, done, error). Voor GUI real-time log. (V1.1 optioneel)

Startup: init registry, init Qwen3Backend health-check (non-blocking), start ClipboardAdapter thread. Shutdown: stop thread, stop player.

## 8. GUI: TAURI 2 + SVELTE 5 — 2 TABS MAX
### Tab 1: Dashboard
- Status balk: server status, Qwen online/offline dot, poll-loop actief
- Live log (scrollback, gekleurd per level)
- Test TTS: inputbox text + dropdown speaker + "Speak" button
- Input source selector (V1: Clipboard vast aan; V2: Clipboard/Luna/Both)

### Tab 2: Speakers & Voices
- Tabel: naam, voice dropdown (uit Qwen `GET /v1/audio/voices`), instruct textarea, emotion slider, [verwijder]
- Toon welke speakers auto-geregistreerd zijn vandaag (nieuwe → highlight)
- Geen 3e tab. Emotion is een kolom/slider, geen los tabblad.

Layout: `flex` sidebar (navigatie) + main content, mobile-responsive. Donker theme consistent met oude GUI-stijl maar proper.

## 9. ANTI-PATTERNS (VERBODEN)
- Geen god-script > 500 regels per module.
- Geen `:` splitsen op Luna/Hook tekst (V2). Luna krijgt EIGEN parser (whitelist, nooit midden-zin split).
- Geen auto-aanmaak speakers op willekeurige hoofdletter of `:` in tekst.
- Geen dynamische voice-loading op GPU zonder expliciete registry-mutatie.
- Geen GUI-tabs die half leeg zijn. Wat niet af is → weglaten (YAGNI).
- Geen 20 variant files. Eén codebase, git, semver.
- Geen absolute paden hardcoded behalve in `.env`.

## 10. DEFINITION OF DONE (V1)
- [ ] RenPy game zet `Rick: Hi all.` op clipboard → NovaTTS speelt Qwen-stem voor Rick via `127.0.0.1:8080`, correct sample.
- [ ] `Rick: ...` onbekend in registry → Narrator, géén nieuwe slot. Registry onaangetast.
- [ ] Clipboard poll loopt 1 uur zonder crash/leak (thread-safe, exceptions swallowed).
- [ ] Zelfde zin + zelfde stem + zelfde instruct → 1x GPU, daarna cache-hit (<100ms).
- [ ] Speaker wijzigen in GUI → nieuwe stem vanaf volgende zin, zonder server-restart, zonder voice-leak naar andere speakers.
- [ ] Totaal backend < 1500 regels. Elke module < 500.
- [ ] `ruff check` + `mypy --strict` passen.
- [ ] GUI start in <2s, 2 tabs, responsive.

## 11. V2 ROADMAP (NIET NU BOUWEN)
- LunaAdapter + LunaParser via WebSocket `ws://127.0.0.1:6677` (port uit `VN_Suite.py::handle_hook_text` L3664, `hook_space_form` L1822).
- Hook modes: `clipboard|websocket|both`, auto-assign met GUI-bevestiging.
- Blacklist (port `VisualNovelTTS.py` L140-199) + UI-presets.
- Emotion overlay: `emotion_patterns.json` + `emotion_sound_map.json` → wav overlay.
- File-monitor mode (vn_tts.py `textractor_output.txt` + mtime watch) als tertiary fallback.

---
**prompt voor AI agent:** "Bouw dit project exact volgens deze spec. Port de aangegeven logica uit de genoemde bestanden, maar schrijf elke module opnieuw (clean slate, geen copy-paste blobs). Begin met backend: config → models → registry → tts → parser → adapter → main.py. Daarna GUI. Loop de Definition of Done af. Houd het simpel."
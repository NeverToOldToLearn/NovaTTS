# NovaTTS — Luna Edition: verslag & plan van aanpak

> **Dit bestand is vanaf nu het referentiepunt voor de Luna-edition.**
> Elk nieuw onderzoek, elke wijziging en elke beslissing wordt hierin bijgewerkt.
> Eén document, driehoofdig: *wat is klaar → wat ontbreekt → wat doen we, in welke volgorde*.
>
> **Status van dit document:** opgesteld 2026-09-28, op basis van drie inspecties:
> Main-branch `e48c8ef` (commit `Luna-Hook` == `main` == `origin/main`),
> `D:\Projects\NovaTTSLuna` (conceptbuild, **géén git-historie**, alle bestanden untracked),
> en `D:\Projects\Sample-Creator-Qwen3TTS\VN_Suite.py` (werkelijke hook-referentie).
>
> **Update-protocol:** bij elke fase-afronding de ✅-status van die fase aanpassen
> en §9 (Open beslissingen) inkorten. Geen nieuwe status-bestanden maken — dit blijft het enige.

---

## 1. TL;DR — de kern van het advies

| | Oordeel |
|---|---|
| **Main (NovaTTS)** | Functioneel compleet en kwalitatief veel hoger dan het Luna-concept. Perfect Cut, Qwen-beheer, OpenAI-compat-endpoint, per-game speakers, 36 routes, 7 testsuites. |
| **NovaTTSLuna (concept)** | Alleen de *Luna-inputkant* gebouwd. Dat deel is bruikbaar, maar het is een **aftakking van een oudere V1**, niet van Main. Alles wat niet met input te maken heeft is er *ouder of ontbreekt*. |
| **Aanpak** | **Selectieve port, geen wholesale vervanging.** Alleen `parser/luna.py`, `adapters/luna.py`, `adapters/file_monitor.py` en ~12 config-sleutels overnemen. **Alles overig in Main laten staan.** |
| **Kernrisico** | B's `app.py` doet synthese **inline in de websocket-handler**. Dat blokkeert de event loop tijdens de TTS-call (tot 300 s). **Mag nooit worden overgenomen.** Main heeft al de juiste worker-thread-oplossing. |
| **Vervanging RenPy** | Clipboard blijft als *fallback* bestaan (`hook_mode`), maar wordt **niet de primary**. See §9 beslissing D1. |

---

## 2. Bronnen & hun rol

| Bron | Pad | Rol |
|---|---|---|
| **Main** | `D:\Projects\NovaTTS\.worktrees\luna-hook` (branch `Luna-Hook` @ `e48c8ef`) | **Doelbuild.** Alles wat hier staat is af & werkt. Hier wordt de Luna-hook in geïntegreerd. |
| **Luna-concept** | `D:\Projects\NovaTTSLuna` — **gearchiveerd: commit `34562fb`, tag `donor`** | **Donorbron voor de Luna-inputmodules + de V2-specificatie** (`V2_ROADMAP.md`, 229 regels). |
| **Hook-referentie** | `D:\Projects\Sample-Creator-Qwen3TTS\VN_Suite.py` (310 KB) | **Grond waarheid voor hook-semantiek.** Bevat de werkende ws-server, de space-form split, dual-hook, proxy-detectie. NovaTTS-Luna is een vereenvoudiging *hiervan*. |
| **CRLF-handover** | `docs/COLLEGA_RAPPORT_CRLF.md` §5 | Bevat al een opsomming van wat de Luna-edition moet overnemen. Cross-check in §8 F7. |

> ⚠️ `NovaTTSLuna` had oorspronkelijk **geen enkele git-commit** — het was een losse schaduwkop.
> **Opgelost in D7:** gearchiveerd als commit `34562fb` met tag `donor`, en de `.gitignore` is aangevuld
> (`.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`). De donorbron is nu een vast, diffbaar snapshot.
> **Behandel het als een leesbron, niet als een upstream.**

---

## 3. VERSLAG A — Wat Main al heeft (de voltooide basis)

### 3.1 Repository

`e48c8ef` op `Luna-Hook` == `main` == `origin/main`. Working tree clean.
19 commits; de laatste 8 zijn feature-/fix-commits op de kern (emotion, spk/rvq, Perfect Cut, GUI-poort).
`main` is dus **klaar** en is het integratiepunt.

### 3.2 Architectuur (bevroren — zie `ULTIMATE_PROMPT.md` §2)

```
adapter (Clipboard | Luna WS | FileMonitor)   ← 2 van 3 zijn placeholders
  → parser (RenPy | Luna)                      ← 1 van 2 is placeholder
  → blacklist → emotion extract
  → registry (per-game) → voice_manager (stateless Qwen) → player (queue)
```

### 3.3 Backend — wat af is

| Module | Regels | Status |
|---|---|---|
| `main.py` | 1029 | ✅ 36 routes, `NovaApp` + FastAPI in één bestand, lifespan, CORS, OpenAI-compat |
| `parser/renpy.py` | 144 | ✅ `RenPyParser` — strict `Name: Text`, 38-woord narratie-stoplist, `known_names` whitelist |
| `adapters/clipboard.py` | 96 | ✅ poll 0.25 s, `last_clipboard` dedup, `set_known_speakers` |
| `adapters/rawclipboard.py` | 58 | ✅ `RawClipboardLogger` — pre-filter logging, wist zichzelf op shutdown |
| `blacklist.py` | 88 | ✅ `PRESETS` (togglebaar) + `custom_words`, `is_renpy_exception` altijd-aan |
| `emotions.py` | 231 | ✅ auto-discovery `C:\Piper\emotion_sounds`, 67 patterns, aliases, map-validatie |
| `text_clean.py` | 105 | ✅ `clean_emotion_text` — *geen equivalent in B, behouden* |
| `registry/speakers.py` | 177 | ✅ thread-safe, `Speaker` dataclass, `lookup_voice`, `instruct`+`emotion`, `maybe_autosave` |
| `games.py` | 64 | ✅ `GameManager`, sanitisatie, `data/games/<Game>/speakers.json` |
| `tts/qwen.py` | 146 | ✅ stateless HTTP, `register_voice` met spk/rvq, unknown-voice retry |
| `tts/spk_rvq.py` | 144 | ✅ pre-extractie, `collect_pairs`, `convert_samples_dir` |
| `tts/voice_manager.py` | 155 | ✅ `synthesize(Dialogue, *, voice_override)`, md5-cache incl. `engine`+`emotion` |
| `qwen_manager.py` | 243 | ✅ proces-beheer, autostart, import-status, managed/external |
| `player/audio.py` | 120 | ✅ queue, `enqueue`/`enqueue_interrupt`/`stop_current`, `on_finished` |
| `cutter.py` + `cutter_api.py` + `cutter_batch.py` | 665 | ✅ **Perfect Cut** — waveform, ffmpeg-export, batch `silenceremove+loudnorm`+whisper |
| `audio_convert.py` | 69 | ✅ mp3/opus/aac/flac/wav/pcm conversie |
| `config.py` | 103 | ✅ frozen-aware `_base_dir()`, pydantic-settings, `NOVATTS_`-prefix |

### 3.4 GUI — 5 tabs + Perfect Cut

Tauri 2 + Svelte 5. `App.svelte` sidebar (230 px), tabs: **Dashboard · Characters · Blacklist · Emotions · Settings**.
Perfect Cut is een **tweede Tauri-venster** op `index.html#/cutter` (bewust géén sidebar-item) met
`SampleCutter` (543) + `DatasetPrep` (325) + `Waveform` (408) + `edgelock.ts`.
`src-tauri/src/lib.rs` (435) doet env-bootstrap, dev-frontend-autostart, `taskkill_tree` fallback.
`api.ts` heeft 25 methodes; `types.ts` is 100 regels.

### 3.5 Build & lifecycle — af

`setup.ps1` (207) · `start_all.cmd` (133, `--min/--visible/--hidden/--repair`, venv self-heal) ·
`stop_all.cmd` (14, **⚠ bug — zie F7**) · `Makefile` (154, 16 targets) · root `package.json` (11 scripts) ·
`Build-Installer.ps1` + `installer/NovaTTS.iss` + `backend/Novabackend.spec` (PyInstaller) ·
`start_qwen.cmd` · `Convert-WavToSpkRvq.ps1` · `setup.sh` (macOS/Linux) · `Install.cmd` / `INSTALL.md` (248).

### 3.6 Tests & gates — af

7 testsuites (`test_renpy_parser` 17 tests, `test_speaker_registry` 13, `test_voice_manager` 9,
`test_spk_rvq` 14, `test_cutter` ~40, `test_openai_speech` 3, `test_rawclipboard` 3).
Gates: `ruff check` + `mypy --strict` + `npm run build`.

### 3.7 Data — af

`speakers.json` (`"versions"`-schema) · `active_game.json` (`{"active":"where_the_heart_is"}`) ·
`blacklist.json` · `emotion_patterns.json` (67 patterns, **byte-identiek aan B**) ·
`emotion_aliases.json.example` + `emotion_sound_map.json.example` (echte bestanden bewust uitgehaald,
zie commit `e48c8ef` "Keep the personal emotion mapping out of the repo and the release") · `data/README.md`.

### 3.8 Dood gewicht in Main

- `backend/vntts/` (~1.400 regels Rust/WASM) — **Tauri+Sycamore `tauri init`-template, nooit gebouwd**
  (geen `Cargo.lock`, geen `target/`), nul verwijzingen buiten zichzelf om, `description = "A Tauri App"`,
  `Trunk.toml` claimt poort 1420 (botsing met Vite). **Veilig te verwijderen** —zie F9.
- `backend/.mypy_cache` / `.ruff_cache` — op schijf aanwezig, correct ge-gitignored.

---

## 4. VERSLAG B — Wat NovaTTSLuna (concept) al heeft

### 4.1 Status

Geen git-historie. Alles `??` untracked. `node_modules`, `.venv`, `.mypy_cache`, `.ruff_cache`,
`.pytest_cache` staan op schijf. **Het is een werkboom, geen checkpoint.**

### 4.2 Wat het wél heeft (de donor-modules)

| Bestand | Regels | Inhoud |
|---|---|---|
| `parser/luna.py` | **434** | `parse_luna()`, `is_plausible_character_name()`, `reject_ui_line()`. 113 `_SPACE_FORM_STOPWORDS`, 128 `_NON_CHARACTER_NAME_TOKENS`, 40 `_SCENE_LABEL_WORDS` *(gedeclaireerd, nergens gebruikt)*, 43 `_MENTION_VERBS`, 15 `_VN_UI_BLACKLIST`-regexen. **Dit is het waardevolste stuk.** |
| `adapters/luna.py` | 205 | `LunaAdapter` — ws-**server** op `:6677` óf ws-**client** via `LUNA_WS_URL`, eigen asyncio-loop in een daemon thread, `client_count`, `_pending_name` dual-hook buffering (0.6 s), `_as_text()` JSON-unwrap. |
| `adapters/file_monitor.py` | 68 | `FileMonitorAdapter` — mtime-poll 0.3 s op `textractor_output.txt`. |
| `app.py` | 236 | `NovaApp` met hook_mode-selectie, dedup-window 500 ms, `is_plausible_character_name` als trust-gate voor auto-registratie. |
| `config.py` | 165 | De 9 `NOVATTS_HOOK_*` / `LUNA_WS_URL` / `FILE_WATCH*` / `DEDUP_WINDOW_MS` velden. |
| `tests/test_core.py` | 165 | 20 tests: `TestRenPyParser` (5), `TestLunaParser` (9), `TestBlacklist` (4), `TestEmotions` (2). |
| `V2_ROADMAP.md` | 229 | De volledige V2-specificatie + 9-puntige DoD. |

### 4.3 Wat het níét heeft (tegenover Main)

Geen Perfect Cut · geen `qwen_manager` · geen `spk_rvq` · geen `text_clean` · geen `audio_convert` ·
geen OpenAI-compat · geen `rawclipboard` · geen `alias` route · geen `clone_voice` · geen `preview_voice` ·
geen `test-tts` · geen `/cutter/*` · geen `/games/{name}/export|import` — kortom **~70% van Main ontbreekt**.

### 4.4 B is ouder dan Main (bewijs)

| Feature | Main | B |
|---|---|---|
| `VoiceManager.synthesize` | `(Dialogue, *, voice_override)` | `(text, speaker)` — de **V1-vorm** |
| `SpeakerRegistry` | `Speaker`-dataclass, `to_dict()`, `lookup_voice` | platte dict, `dump()` — de **V1-vorm** |
| `EmotionSounds` | `(player=…)`, `extract() -> (str, [(pos, tag)])` | 4 paden, `extract() -> (str, [(start, end, tag)])` — **V1-vorm** |
| `TTSBackend` | `abc.ABC` | `Protocol` — V1-vorm |
| `parser/renpy` | klasse, narratie-fallback | `parse_renpy() -> Dialogue | None` — V1-vorm |
| `main.py` | 36 routes, pydantic bodies | 22 routes, `body: dict` — V1-vorm |
| GUI | 5 tabs + Perfect Cut (1645 regels) | 5 tabs, 311 regels |

> **Conclusie:** B is een V1-fork waaraan de Luna-input is toegevoegd.
> **B is géén portdoel voor de infra.** B is wél het portdoel voor `parser/luna.py` + `adapters/luna.py` + `file_monitor.py` + de 9 config-sleutels. Meer niet.

---

## 5. VERIFICATIE — Placeholders (zoals gevraagd)

**Ze staan er nog, allebei, ongewijzigd.**

| Placeholder | Pad | Regels | Inhoud |
|---|---|---|---|
| `LunaAdapter` | `backend/novatts/adapters/luna.py` | 30 | `class LunaAdapter(InputAdapter)`, docstring *"Not implemented in V1"*, `start()` logt `warning("LunaAdapter is a V2 placeholder - not started")`, `is_running()` → `False`, `_handle_hook_text()` → `raise NotImplementedError("Luna pipeline lands in V2")` |
| `LunaParser` | `backend/novatts/parser/luna.py` | 11 | `class LunaParser`, docstring *"The V2 parser will use a registry whitelist instead of splitting on colons"*, `parse()` → `raise NotImplementedError("Luna pipeline lands in V2")` |
| `FileMonitorAdapter` | `backend/novatts/adapters/file_monitor.py` | — | **Bestaat niet.** Wordt nieuw aangemaakt (B heeft 'm, 68 regels). |
| `adapters/__init__.py` | regel 3-5 | 4 | Exporteert **alleen** `InputAdapter, ClipboardAdapter` — `LunaAdapter` moet erbij. |
| `parser/__init__.py` | regel 3-5 | 3 | Exporteert **alleen** `RenPyParser` — `LunaParser` moet erbij. |

`Dialogue.source` (models.py:18) kent de waarden `"renpy"`, `"luna"`, `"api"` al — de `source`-as bestaat dus.

---

## 6. GAP-ANALYSE — wat ontbreekt in Main

### G1 — Luna-inputkant (het echte werk)

| # | Gap | Omvang | Moeilijkheid |
|---|---|---|---|
| G1.1 | `parser/luna.py` → echte implementatie | 434 regels donor | ✅ laag — vrijwel 1:1 |
| G1.2 | `adapters/luna.py` → echte ws-server | 205 regels donor | ⚠️ midden — zie G4.1, G4.3 |
| G1.3 | `adapters/file_monitor.py` → nieuw | 68 regels donor | ✅ laag |
| G1.4 | 9 config-sleutels + `SettingsBody`/`_SETTINGS_ENV_MAP`/`_SETTINGS_FIELD_TYPES` | ~20 regels | ✅ laag |
| G1.5 | `Dialogue.raw: str = ""` veld | 1 regel | ✅ laag |
| G1.6 | `NovaApp`: hook_mode-bedrading, dedup-window, trust-gate | ~60 regels | ⚠️ midden |
| G1.7 | `status()` → `hook_mode` + `hook_clients` | 2 regels | ✅ laag |
| G1.8 | `websockets>=12.0` in `requirements.txt` + `pyproject.toml` | 2 regels | ✅ laag |
| G1.9 | `LunaAdapter`/`LunaParser` in de `__init__`-barrels | 2 regels | ✅ laag |
| G1.10 | GUI: `hook_mode`/`hook_port` in Settings, `hook_mode`/`hook_clients` in Dashboard, types.ts, brand-sub | ~40 regels | ✅ laag |

### G2 — Signature-conflicten (het risico dat de port stil faalt)

Deze zijn de **enige plekken waar een "1:1 kopieer"-port Main kapot maakt**:

| Conflict | Main | B | Impact |
|---|---|---|---|
| `Dialogue.raw` | **ontbreekt** | `raw: str = ""` | B maakt overal `raw=`; Main's dataclass accepteert dat niet |
| `Dialogue.instruct` | `instruct: str = ""` | **ontbreekt** | B's `Dialogue` vervangen zou instruct-propagatie uit de pijplijn halen |
| `EmotionSounds.extract` | `(str, [(pos, tag)])` — offsets in de **opgeschoonde** tekst | `(str, [(start, end, tag)])` — offsets in de **originele** tekst | B's `emotions.py` overnemen breekt `main.py:189-228` `_synth_emotion_aware` |
| `EmotionSounds.__init__` | `(player=None)` | 4 verplichte paden | B's ctor is onbruikbaar naast Main's `EmotionSounds(player=self.player)` |
| `VoiceManager.synthesize` | `(Dialogue, *, voice_override)` | `(text, speaker)` | **Volledig incompatible.** Main heeft 7 call sites + 9 tests |
| `SpeakerRegistry` | `Speaker`-dataclass | platte dict | Main's 9 call sites + 13 tests |
| `parser/renpy` | klasse, narratie-fallback | functie, `None` | Main's 17 tests + `ClipboardAdapter` |
| `TTSBackend` | `abc.ABC` | `Protocol` | Main's `FakeBackend` in tests |
| `Dialogue.source` | `str`, default `"renpy"` | `Literal`, **zonder `"renpy"`** | Main gebruikt `"renpy"` én `"openai-api"` → breekt mypy |
| `AudioPlayer.stop()` | `stop()` + `start()` + `current() -> Path` | `shutdown()`, geen `start()`, `current() -> str` | Main's lifecycle |
| `Blacklist` preset-keys | `"Hours (12h)"` / `"Hours (24h)"` | `"Hours 12h"` / `"Hours 24h"` | **Stille data-incompatibiliteit** — Main's `data/blacklist.json` zou 0 presets laden |
| `speakers.json` schema | `"versions"` + per-entry `"name"` | `"version"` zonder `"name"` | Main's `SpeakersPanel` doet `Object.values()` → zou lege rijen tonen |

> **Alle 12 conflicten worden opgelost door: Main behouden, B's Luna-modules *aanpassen* aan Main.**
> Ze worden **niet** opgelost door Main te vervangen — daar zou 95% van Main in kapotgaan.

### G3 — Gaps in B's Luna-implementatie zelf (t.o.v. `VN_Suite.py`)

Dit is belangrijk: **B is een vereenvoudiging van de werkelijke referentie.**
Als je B blind port, mis je functionaliteit die `VN_Suite.py` wél heeft:

| # | Ontbreekt in B | Wat `VN_Suite.py` doet | Referentie |
|---|---|---|---|
| G3.1 | **JSON `name`/`speaker`/`character` veld** | Herbouwt `f"{name}: {body}"`. B's `_as_text` kijkt alleen naar `text`/`sentence`/`message` → **de spreker gaat verloren bij JSON-hooks** | `VN_Suite.py:3850-3863` |
| G3.2 | **Multi-spreker split** (`"Anne Hallo! Rick Mooi."` → 2 turns) | `_split_speaker_turns()` met 5 guards | `VN_Suite.py:1876-1949` |
| G3.3 | **Nieuwe-regel-bare-name** (`"Rick\nAntwoord…"`) | `pending` in de newline-loop | `VN_Suite.py:1881-1897` |
| G3.4 | **`hook_dual_hook` werkt niet** | B declareert de setting maar geeft hem **nooit** door aan `LunaAdapter`; de merge draait altijd | `VN_Suite.py:3683-3715` |
| G3.5 | **Proxy-detectie** | `NO_PROXY`/`no_proxy` + `netsh winhttp show proxy`; anders onderschept een system proxy de lokale ws | `VN_Suite.py:3786-3814` |
| G3.6 | **Raw-TCP fallback** als `websockets` ontbreekt | `socket`-server die platte regels accepteert | `VN_Suite.py:3906-3925` |
| G3.7 | `content` / `data` JSON-keys | `text`/`sentence`/`content`/`message`, plus `data` | `VN_Suite.py:3854-3863` |
| G3.8 | Geen "salvage dialogue segment" | Als de filter alles wist, probeert `_extract_dialogue_segment()` | `VN_Suite.py:3727-3731` |

> **Aanbeveling:** G3.1 en G3.2–G3.3 **meenemen** — dat is de reden dat `VN_Suite.py` vermeld staat als bron in `V2_ROADMAP.md` §15.
> G3.5 meenemen want het is een 6-regels `if` en het verklaart een hele klasse "het werkt niet"-bugs.
> G3.4/G3.6/G3.8 als expliciete *out of scope*-beslissing vastleggen (D3, D4).

### G4 — Gevonden ontwerpfouten in B (niet overnemen)

| # | Fout | Waarom fataal |
|---|---|---|
| G4.1 | **B blokkeert de event loop.** `LunaAdapter._handle_text` → `on_dialogue` → `app.on_dialogue` doet `time.sleep(0.12)` **en** `self._synth_emotion_aware(...)` allebei **synchronously in de `async for msg in ws`-loop**. | Eén regel dialoog blokkeert de hele ws-server tot de TTS klaar is (`qwen_timeout` = 300 s). LunaHook's heartbeat en alle clients staan vast. **Main heeft de juiste oplossing al: `dialogue-worker` thread + `_wake` Event + `pending_dialogue`/`pending_seq`.** |
| G4.2 | B's `EmotionSounds.extract` doet géén `*multi word*`-behoud (A's `text_clean.py` wel: `*1 woord*` → weg, `*2+ woorden*` → binnentekst zonder asterisken). | Porten van B zou gevoelsregels regresseren. **`text_clean.py` behouden.** |
| G4.3 | B's `LunaAdapter` erft niet van `InputAdapter` en heeft geen `name`-property. Main's `InputAdapter` is een `abc.ABC` met abstract `name`. | Direct overnemen ⇒ `TypeError: Can't instantiate abstract class`. **Moet: `InputAdapter` implementeren incl. `name`.** |
| G4.4 | B's registry `remove()` beschermt `"Narrator"`; Main's niet. Main's `main.py:567` maakt dat gedrag kapot als de user Narrator verwijdert. | Bedoeld gedrag, maar **bewust een Main-wijziging** — niet per ongeluk overschrijven. |
| G4.5 | B's `_SCENE_LABEL_WORDS` (40 entries) is gedefinieerd maar **nergens gebruikt** — pure ballast. | Niet meenemen. (Zelfde voor Main's dode `backend/vntts/`.) |

### G5 — Gevonden fouten in Main (los op tijdens de port, mini-scope)

| # | Fout | Locatie |
|---|---|---|
| G5.1 | `stop_all.cmd` schiet op **poort 8081** (Qwen) terwijl de comment zegt *"kill anything on port 8765"* — en de backend draait op 8765. `POST /shutdown` gaat dus naar de verkeerde poort. | `stop_all.cmd:4` + `:7` |
| G5.2 | `2>nul` in PowerShell breekt de pipe; moet `2>&1 1>nul` of `2>&1 \| Out-Null`. | `stop_all.cmd:4,8,12,14` — precies de bug uit `V2_ROADMAP.md` §1.1 |
| G5.3 | `stop_all.cmd` doodt `novatts-gui.exe` nooit, terwijl `App.svelte` de sidebar de user *naar* `stop_all.cmd` verwijst. | `stop_all.cmd` |
| G5.4 | `_synth_emotion_aware` hardcodt `"source": "clipboard"` in de `Event("error", …)`-calls — wordt onjuist zodra de bron `luna`/`file` is. | `main.py:209, 221, 227, 261` |
| G5.5 | `SpeakerRegistry.update(…, instruct=…)` accepteert `instruct` maar **wijst het nooit toe**. Stille no-op. | `registry/speakers.py` |
| G5.6 | `registry.update()` is keyword-only; `registry.update(name, "voice")` (B-stijl) zou `TypeError` geven. Bij het toevoegen van Luna-code een afwijking voor beide moeten dragen. | idem |
| G5.7 | `main.py:451-453` losse regel tussen functie en import (ruff E303). | `main.py:451-453` |
| G5.8 | `.env.example` zegt `NOVATTS_QWEN_TIMEOUT=120.0`; `config.py:79` zegt `300.0`. | `backend/.env.example:11` |
| G5.9 | `pyproject.toml` mist `[build-system]` — `pip install -e backend` werkt niet. | `backend/pyproject.toml` |
| G5.10 | `pytest` ontbreekt in `requirements-dev.txt` terwijl er 7 testsuites zijn. | `backend/requirements-dev.txt` |

### G6 — Docs/data-drift

| # | Drift | Actie |
|---|---|---|
| G6.1 | `data/emotion_sound_map.json` + `emotion_aliases.json` bestaan **niet** in Main (bewust uitgehaald in `e48c8ef`) | `emotions.py` bouwt ze op uit de schijf. **Geen actie** — moet zo blijven. |
| G6.2 | `data/speakers.json` bevat game-lokale namen (`where_the_heart_is`, `Anna`, `Brenda`, `D`, `Lilya`) | Persoonlijke data in de repo. Net als `e48c8ef` voor de emotion-map: overwegen om naar `data/games/` te verplaatsen + `.gitignore` (zie D5). |
| G6.3 | `brand-sub` in de GUI zegt nog `"Qwen3 · RenPy clipboard"` | → `"Qwen3 · LunaHook + clipboard"`. |
| G6.4 | Geen `.env`-documentatie voor de 9 hook-sleutels | Toevoegen aan `README.md` + `backend/.env.example` + `INSTALL.md`. |

---

## 7. PLAN VAN AANPAK

**Regels die boven elke fase staan:**
1. **No regressie.** Na elke fase: `pytest` + `ruff check` + `mypy --strict` + `npm run build` groen. Een groene gate met rode tests is géén groene gate.
2. **Adoptie-geschiedenis.** Nieuwe test -> toevoegen aan de relevante testsuite, niet een nieuw bestand.
3. **Clean slate voor nieuwe modules, hergebruik voor gedeelde.** `parser/luna.py` en `adapters/luna.py` zijn nieuw → mag direct uit B worden overgenomen (na aanpassing). Allen wat Main al heeft → **nooit** vervangen.
4. **Commits zijn klein en reversibel.** Eén fase ≈ één serie commits op `Luna-Hook`, geen squashed megacommit.

---

### ✅ F0 — Baseline & veiligheidsnet *(voor de handhaving)*

Doel: een nulmeting zodat je later kunt bewijzen dat je niets hebt kapotgemaakt.

> ⚠️ **Deze worktree is nog niet gebouwd.** Geen `backend\.venv`, geen `gui\node_modules`,
> geen `gui\dist`. De nulmeting is dus nog niet vastgelegd en de gates kunnen nog niet draaien.
> Eerste stap is dus `.\setup.cmd` (of `setup.ps1 -Shortcuts`), en dat duurt enkele minuten
> (venv + deps + `npm install` + `vite build`).

- [ ] `git branch backup/pre-luna e48c8ef` (of tag `pre-luna`)
- [ ] `.\setup.cmd` — venv, deps, `node_modules`, `vite build` (eenmalig, vóór de meting)
- [ ] Baseline vastleggen: `pytest -q` (aantal tests + uitkomst), `ruff check backend`, `mypy --strict backend/novatts`, `npm run build` — **output in dit document zetten, onder §10**
- [ ] Handmatige functionele smoke: RenPy-game → `Name: Text` → stem, onbekende speaker → Narrator, `start_all.cmd --min` + `stop_all.cmd`
- [ ] `backend/vntts/` verwijderen (F9) — één commit, geen functionele impact
- [ ] G5.1–G5.3 (`stop_all.cmd`) fixen — **lost meteen de `App.svelte`-sidebarbelofte in**

---

### ⬜ F1 — Foundation (config, model, deps, barrels)

Doel: alles wat de Luna-laag nodig heeft bestaat, maar doet nog niets.

- [ ] `backend/requirements.txt`: `websockets>=12.0` (naast de bestaande regels)
- [ ] `backend/pyproject.toml`: `websockets` in `dependencies` + **`[build-system]`** toevoegen (G5.9) + `pytest` in dev-deps (G5.10)
- [ ] `models.py`: `Dialogue.raw: str = ""` toevoegen **zonder** `instruct` of `source` aan te raken
- [ ] `config.py`: 9 velden toevoegen, allemaal met de Main-conventie (pydantic `Settings`, `NOVATTS_`-prefix, `Path`-types voor paden, `backend/.env` + root `.env`):
  `hook_mode: Literal["clipboard","websocket","both"] = "both"` · `hook_host = "127.0.0.1"` · `hook_port = 6677` · `hook_space_form = True` · `hook_dual_hook = False` · `luna_ws_url = ""` · `file_watch = False` · `file_watch_path = "textractor_output.txt"` · `dedup_window_ms = 500`
- [ ] `main.py`: `SettingsBody` + `_SETTINGS_ENV_MAP` (`hook_mode→NOVATTS_HOOK_MODE`, `hook_port→NOVATTS_HOOK_PORT`, `hook_space_form→…`, `hook_dual_hook→…`, `luna_ws_url→…`, `file_watch→…`, `file_watch_path→…`, `dedup_window_ms→…`) + `_SETTINGS_FIELD_TYPES` (`hook_port: int`, `dedup_window_ms: int`)
- [ ] `backend/.env.example` + `README.md`: de 9 sleutels documenteren (G6.4)
- [ ] `logger`-regel: `logging.getLogger("websockets.server").setLevel(logging.CRITICAL)` (uit `VN_Suite.py:3813`)

**Gate:** alle 4 gates groen, geen gedragsverandering.

---

### ⬜ F2 — `parser/luna.py` (echte implementatie)

Doel: de ruimte-vorm parser draait en is getest. **Nog niets aangesloten.**

- [ ] `backend/novatts/parser/luna.py` herschrijven: `parse_luna()`, `is_plausible_character_name()`, `reject_ui_line()` uit B overnemen; **de 5 constantensets + 15 UI-regexen** overnemen
- [ ] **Niet** overnemen: `_SCENE_LABEL_WORDS` (dood, G4.5)
- [ ] Aanpassen aan Main: `Dialogue(..., source="luna", raw=text)` — beide velden bestaan nu (F1). `Dialogue.instruct` blijft staan.
- [ ] Uitbreiden met G3.2/G3.3: `split_speaker_turns()` voor multi-spreker + newline-bare-name, geschreven in Main-stijl (type hints, `re.Pattern[str]`, <500 regels)
- [ ] `parser/__init__.py`: `LunaParser`/de module-functies toevoegen aan `__all__`
- [ ] **Namen-unit-tests**: de 9 `TestLunaParser`-tests uit B's `test_core.py` overnemen, **plus** 6 nieuwe voor multi-spreker, newline-name, `*emotie*`-interactie en `raw`-propagatie

**Gate:** `ruff` + `mypy` + de nieuwe tests groen. **Nog steeds 0 runtime-impact.**

---

### ⬜ F3 — `adapters/luna.py` (ws-server)

Doel: LunaHook kan verbinden en een regel doorkomt als `Dialogue`.

- [ ] `backend/novatts/adapters/luna.py` **vervangen** (de placeholder is 30 regels `NotImplementedError`; dit is een overwrite, geen patch)
- [ ] `class LunaAdapter(InputAdapter)` **met** `name`-property → `"luna"` (G4.3)
- [ ] Eigen daemon thread + eigen `asyncio` event loop (B's patroon). `start()` / `stop()` / `is_running()` / `client_count`
- [ ] **Server-modus** (default): `websockets.serve(handler, host, port)`, meerdere clients, `client_count` met lock
- [ ] **Client-modus** alleen als `luna_ws_url` gezet is
- [ ] `_as_text()` uitbreiden met G3.1 (`name`/`speaker`/`character` → `f"{name}: {body}"`) en G3.7 (`content`/`data`-keys)
- [ ] Garbage-guard: `is_renpy_exception` (altijd-aan, vóór alles) + `min_text_length` + `_NAME_STOPWORDS`
- [ ] Dual-hook: `hook_dual_hook` **wel** doorgeven en het daadwerkelijk conditioneel maken (G3.4 — B doet dit niet)
- [ ] Proxy-guard (G3.5): zet `NO_PROXY=127.0.0.1,localhost` voor de loop + één `netsh winhttp show proxy`-check met `warning()` in het log
- [ ] `on_dialogue()` aanroepen via de **worker** (F6), nooit synchroon in de event loop (G4.1)
- [ ] `adapters/__init__.py`: `LunaAdapter` toevoegen
- [ ] Tests: 1 gesimuleerde ws-server + 1 client, `test_luna_adapter.py`, deels naast bestaande suites

**Gate:** alle 4 gates groen. Handmatig: `wscat`/`websocat` op `ws://127.0.0.1:6677` → regel komt binnen als event.

---

### ⬜ F4 — Bedrading in `NovaApp`

Doel: de hook-pipeline is live, zonder de RenPy-pipeline te raken.

- [ ] `NovaApp.__init__` / `start()`: adapter-keuze uit `settings.hook_mode` — `clipboard` / `websocket` / `both` (default `both`). **B's inline `app.py` NIET overnemen** (G4.1); Main's `dialogue-worker` + `_wake` + `_pending_seq` blijft de enige synthese-route
- [ ] Dedup: `_dedup: dict[tuple[str, str], float]` met `dedup_window_ms` (500), gedeeld door clipboard + luna + file (B's `_is_duplicate`, overgenomen)
- [ ] Trust-gate op auto-registratie: `source == "clipboard"` (RenPy `Name:` is expliciet → vertrouwd) **of** `is_plausible_character_name(name)`. Luna space-form is een gok → mag geen permanent stem koppelen (faalveilig-principe uit `ULTIMATE_PROMPT.md` §2)
- [ ] `is_blacklisted_name()` toevoegen aan `blacklist.py` (B heeft 'm, Main niet) — of expliciet afvinken als scope
- [ ] `status()` uitbreiden: `hook_mode`, `hook_clients`, `source` in het `dialogue`-event
- [ ] G5.4 fixen: `dialogue.source` i.p.v. de hardcode `"clipboard"`
- [ ] `stop()`: LunaAdapter netjes afsluiten (event loop stoppen, thread joinen) vóór `qwen_mgr.stop()`

**Gate:** `pytest` volledig groen **inclusief** alle 7 bestaande suites. Handmatig: RenPy-game werkt nog steeds op `hook_mode=clipboard`.

---

### ⬜ F5 — `adapters/file_monitor.py` (tertiair)

Doel: derde vangnet, achter een vlag.

- [ ] Nieuw bestand uit B (68 regels), aangepast aan `InputAdapter` + `name` + `Dialogue.raw`
- [ ] Alleen actief als `NOVATTS_FILE_WATCH=1`
- [ ] `source="file"`, zelfde parserketen, zelfde dedup
- [ ] 3 tests

**Gate:** 4 gates groen.

---

### ⬜ F6 — GUI

- [ ] `types.ts`: `hook_mode: string` + `hook_clients: number` op `ServerStatus`; `hook_mode` + `hook_port` op `SettingsData`
- [ ] `SettingsPanel.svelte`: Hook-mode-selector (3 opties) + hook-poort-veld + hint *"herstart vereist"*
- [ ] `Dashboard.svelte`: hook-status in een bestaande card (of één nieuwe card) — géén nieuwe tab
- [ ] `App.svelte`: `brand-sub` → `"Qwen3 · LunaHook + clipboard"` (G6.3)
- [ ] `api.ts`: niets nodig — `/settings` en `/status` bestaan al
- [ ] `npm run build` + `npm run check`

**Gate:** `vite build` + `svelte-check` groen.

---

### ⬜ F7 — Lifecycle, build & documentatie

- [ ] `start_all.cmd`: dood de ws-poort 6677 niet bij start; meld in de log wel of de hook wacht op LunaHook
- [ ] `stop_all.cmd`: **G5.1/G5.2/G5.3 fixen** (poort 8765, `2>&1`-redirects, `novatts-gui.exe` meedoden) — samen met F0
- [ ] `setup.ps1`: `NOVATTS_HOOK_PORT`-firewallcheck — **warn only**, nooit blokkeren
- [ ] `NovaTTS.iss`: `data\emotion_sound_map.json` / `emotion_aliases.json` / `data\games\*` / `data\perfect_cut.json` blijven uitgesloten (bestaand, behouden)
- [ ] `README.md`: pipeline-diagram, hook-sectie, LunaTranslator-installatie-stappen (`Extensions → Add → textractor_websocket_x64.xdll` → `ws://127.0.0.1:6677`), de 9 env-sleutels, `hook_mode`-tabel
- [ ] `INSTALL.md`: LunaHook-paragraaf
- [ ] `data/README.md`: hook-uitleg erbij
- [ ] `docs/COLLEGA_RAPPORT_CRLF.md` §5 afvinken (`.gitattributes`, CRLF-fix, `.gitignore`) — staat er nog open
- [ ] `Makefile`: `test` / `lint` / `type` blijven de gates; `install` moet nu ook `websockets` pakken

---

### ⬜ F8 — Cutover: RenPy → LunaHook

Doel: de *replace* uit de opdracht, expliciet en omkeerbaar. **Vorm vastgelegd in D1:**
de primaire route wisselen, de RenPy-code behouden als fallback. Geen verwijdering van
`ClipboardAdapter` / `parser/renpy` — die blijven als expliciete keuze bestaan totdat de
ws-route bewezen stabiel is.

- [ ] **Stap 1 — alles centraal aan.** Standaard blijft `hook_mode=both`; RenPy blijft aantoonbaar werkend. Dat is de veilige vorm van "vervangen": de primaire route wisselen, niet de code weggooien.
- [ ] **Stap 2 — default om.** `hook_mode` default → `"websocket"` in `config.py` + `.env.example` + GUI-default. Clipboard blijft als expliciete keuze + als `both`-fallback.
- [ ] **Stap 3 — RenPy naar legacy.** `ClipboardAdapter` verhuist naar `adapters/legacy_clipboard.py` met een `DEPRECATED`-docstring die naar de ws-route verwijst. `source="renpy"` blijft een geldige `Dialogue.source` voor gelezen logs — **dat schrijf je expliciet, anders breekt mypy op de Literal.**
- [ ] **Stap 4 — GUI.** Menu-item "RenPy clipboard (legacy)" met een "legacy"-badge, of uit de UI en alleen via `.env`.
- [ ] **Stap 5 — documenteer.** README krijgt een "Migratie vanaf RenPy"-sectie met de clipboard→ws-configmapping.

**Gate per stap:** `pytest` groen. Stap 5 vereist een handmatige `start_all.cmd --min` + echte LunaHook-sessie.

---

### ⬜ F9 — Opruimen (kan tussendoor of aan het einde)

- [ ] `backend/vntts/` verwijderen (1.400 regels dode Rust/WASM-template, nooit gebouwd, nul verwijzingen)
- [ ] G5.5 (`update(instruct=)` no-op), G5.6 (kw-only), G5.7 (ruff E303), G5.8 (`.env.example` timeout) fixen
- [ ] G6.2: persoonlijke speakers uit `data/speakers.json` naar `data/games/` verplaatsen + gitignore
- [ ] `[project] description` in `pyproject.toml` van `"…(RenPy/Qwen3)"` naar `"…(LunaHook/Qwen3)"`

---

## 8. Definition of Done

Overgenomen uit `V2_ROADMAP.md` §14, aangescherpt op Main. **Dit is de acceptatietest — geen checkbox is een vinkje waard.**

### Functioneel
- [ ] LunaTranslator + `textractor_websocket_x64.xdll` → `ws://127.0.0.1:6677` levert `Rick It's 2 parts.` → NovaTTS speelt **Ricks** gekloonde stem, geen leak naar andere speakers
- [ ] Zelfde regel als JSON `{"name": "Rick", "text": "..."}` → speaker **Rick** (G3.1)
- [ ] Multi-spreker `"Anne Hallo! Rick Mooi."` → 2 aparte turns met 2 stems, in volgorde (G3.2)
- [ ] Narratie (`You have your shower.`, `Good night babe!`, `Meanwhile, back at…`) wordt **nooit** een speaker
- [ ] RenPy-clipboard op `hook_mode=both` blijft 100% werken (geen regressie op Main)
- [ ] `NOVATTS_FILE_WATCH=1` levert tekst als de ws en clipboard stil zijn
- [ ] `GET /status` toont `hook_mode` + een correcte `hook_clients`
- [ ] Per-game switch behoudt Luna-geschiedenis per game
- [ ] `stop_all.cmd` doodt backend + GUI + tts-server, op **8765**

### Kwaliteit
- [ ] `pytest` groen — **7 bestaande suites + nieuwe Luna-suites**, 0 regressies
- [ ] `ruff check` + `mypy --strict` + `npm run build` + `npm run check` groen
- [ ] `main.py` blijft < 1100 regels; elk nieuw module < 500 regels (`ULTIMATE_PROMPT.md` §2)
- [ ] `adapters/luna.py` **dood de event loop niet** tijdens synthese (G4.1) — aantoonbaar: 2 gelijktijdig verzonden regels komen allebei door
- [ ] 1 uur ws-verbinding zonder crash, zonder thread-leak, zonder onbeperkte queue

### Documentatie
- [ ] README: pipeline, hook-config, LunaTranslator-setup, `hook_mode`, migratiepad
- [ ] `INSTALL.md` + `data/README.md` bijgewerkt
- [ ] `docs/COLLEGA_RAPPORT_CRLF.md` §5 afgevinkt
- [ ] **`LUNA_EDITION_REFERENCE.md` (dit bestand) bijgewerkt: ✅ per fase, §9 ingekort, §10 aangevuld**

---

## 9. Beslissingen

### 9.1 Vastgelegd (2026-09-28) — dit zijn de regels waar we tegenaan bouwen

| # | Besluit | Gevolg voor het plan |
|---|---|---|
| **D1** ✅ | **"Vervangen" = primaire route wisselen, RenPy-code behouden als fallback.** | F8 wordt 5 omkeerbare stappen (§F8 stap 1→5). `ClipboardAdapter` wordt **niet** verwijderd; hij verhuist naar `adapters/legacy_clipboard.py` met een `DEPRECATED`-docstring die naar de ws-route verwijst. `source="renpy"` blijft een geldige waarde — dat moet je expliciet schrijven, anders breekt de `Literal`. |
| **D2** ✅ | `hook_mode` default = `both` tot F8 bewezen is; daarna `websocket`. | F1 zet `both`, F8-stap 2 zet `websocket`. GUI-default volgt in dezelfde commit. |
| **D3** ✅ | `hook_dual_hook` wordt **echt conditioneel** gemaakt, niet weggegooid. | F3. B declareert de setting al, dus weggooien zou een gedragsregressie zijn t.o.v. het concept. |
| **D4** ✅ | **Geen** raw-TCP-fallback. | F3 gebruikt `websockets` uit `requirements.txt`; bij een ontbrekende import een duidelijke foutmelding, geen tweede transport. ~40 regels YAGNI vervallen. |
| **D5** ✅ | Persoonlijke `data/speakers.json` uit de repo, net als bij de emotion-map (`e48c8ef`). | F9. Verplaatsen naar `data/games/<Game>/` + `.gitignore`. |
| **D6** ✅ | `VN_Suite.py` blijft de gedocumenteerde grondreferentie; `V2_ROADMAP.md` blijft de historische spec en wordt als zodanig in de README gelinkt. | §2 is definitief. G3 blijft de brug tussen beide. |
| **D7** ✅ | **Uitgevoerd:** `NovaTTSLuna` is gearchiveerd — `git init`, commit `34562fb`, tag **`donor`**, working tree clean, `.gitignore` aangevuld met `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`. 90 bestanden. De commit-message legt vast welke 4 bestanden donor zijn en welke 2 defecten níét gekopieerd mogen worden. | §2 kan nu verwijzen naar een vast commit-id i.p.v. naar losse bestanden op schijf. |
| **D8** ✅ | Bouwen in **deze worktree** (`D:\Projects\NovaTTS\.worktrees\luna-hook`). | F0 draait hier. Eerste `setup.cmd` is eenmalig enkele minuten (venv + deps + `npm install` + `vite build`). |

### 9.2 Nog open

| # | Vraag | Wanneer het antwoord nodig is |
|---|---|---|
| **D9** | Krijgt de hook-route een eigen `/status`-veld voor de *laatste ontvangen raw_text* (handig om de ws-verbinding zonder game te debuggen)? | F3 — goed moment om het in te bouwen |
| **D10** | Moet `qwen_autostart` in de toekomst `both`-aware zijn? Met `hook_mode=websocket` start de Qwen-server soms terwijl er niets op de ws komt. | F7 — niet blokkerend voor de port |
| **D11** | Wordt `backend/vntts/` verwijderd in een eigen commit, of mee in F9? | F0 (eigen commit is netter: nul functionele impact, makkelijk terug te draaien) |

---

## 10. Baseline-logboek *(vullen tijdens F0 en daarna)*

| Datum | Fase | Commit(s) | `pytest` | `ruff` | `mypy` | `npm run build` | Opmerking |
|---|---|---|---|---|---|---|---|
| 2026-09-28 | inspectie | — | — | — | — | — | Beide repos gelezen, `VN_Suite.py` als referentie geverifieerd. Nog niets gewijzigd. |

---

## 11. Voortgang per fase

| Fase | Status | Bijzonderheden |
|---|---|---|
| F0 Baseline & veiligheid | ⬜ | |
| F1 Foundation | ⬜ | |
| F2 `parser/luna.py` | ⬜ | |
| F3 `adapters/luna.py` | ⬜ | |
| F4 `NovaApp`-bedrading | ⬜ | |
| F5 `file_monitor.py` | ⬜ | |
| F6 GUI | ⬜ | |
| F7 Lifecycle & docs | ⬜ | |
| F8 Cutover RenPy→LunaHook | ⬜ | |
| F9 Opruimen | ⬜ | |

---

## 12. Anti-regressie-regels (permanent)

1. **Nooit een Main-module vervangen door de B-variant.** `SpeakerRegistry`, `VoiceManager`, `EmotionSounds`, `Qwen3Backend`, `AudioPlayer`, `Blacklist`, `GameManager`, `parser/renpy`, `TTSBackend`, `text_clean`, `qwen_manager`, `cutter*` — allemaal blijven zoals ze zijn.
2. **Nooit de synthese uit de event loop halen.** Eén regel = één dialoog; de ws-handler geeft `on_dialogue` en *verder niets*. Main's `dialogue-worker` is de enige toegestane synthese-route (G4.1).
3. **Nooit een speaker op GPU binden zonder registry-mutatie.** Onbekende naam → `Narrator` of "wachten op GUI-bevestiging". Faalveilig is niet onderhandelbaar (`ULTIMATE_PROMPT.md` §2).
4. **Nooit `:` splitsen op Luna-tekst.** `RenPyParser` eerst (RenPy levert wél `Name:`), dan pas `LunaParser` space-form. Dat is de volgorde uit `V2_ROADMAP.md` §4.2.
5. **Nooit de clip-`:`-prefix in de TTS laten.** `blacklist.filter_text` spaart hem; daarna moet hij eraf vóór synthese (B doet dit met een regex in `app.py:157`; Main heeft `VoiceManager.clean_dialogue` niet meer — dus expliciet implementeren).
6. **Nooit `itertools`/`asyncio` mixen zonder de shutdown-volgorde te testen.** `NovaApp.stop()` moet altijd: adapters → worker → player → qwen → cache-clear → registry-autosave.
7. **Nooit een `.wav`/`.spk`/`.rvq`/persoonlijke mapping committen.** Zoals `e48c8ef` al besloot voor de emotion-map.

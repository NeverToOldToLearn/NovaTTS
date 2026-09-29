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

- `backend/vntts/` — **Tauri+Sycamore `tauri init`-template, nooit gebouwd**
  (geen `Cargo.lock`, geen `target/`), nul verwijzingen buiten zichzelf om, `description = "A Tauri App"`,
  `Trunk.toml` claimt poort 1420 (botsing met Vite). **Veilig te verwijderen** —zie F9.
  *Gecorrigeerd in F0:* de eerdere schatting "~1.400 regels" telde binaire iconen als tekst.
  Werkelijk: **35 bestanden, 171 KB, ~475 tekstregels** — waarvan 23 van de 35 bestanden icons/
  metadata zijn. `src/app.rs` (58) + `src-tauri/src/lib.rs` (13) is de enige echte code.
  **Verwijderd in F0.**
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
| G5.1 ✅ | `stop_all.cmd` schiet op **poort 8081** (Qwen) terwijl de comment zegt *"kill anything on port 8765"* — en de backend draait op 8765. `POST /shutdown` gaat dus naar de verkeerde poort. Bevestigd: `start_all.cmd:63` en `lib.rs:299` gebruiken allebei 8765; alleen `stop_all.cmd:4,7` wijkt af. **→ Opgelost in F0.** | `stop_all.cmd:4` + `:7` |
| ~~G5.2~~ | ~~`2>nul` breekt~~ **Ingetrokken na verificatie.** `2>nul` is geldige *cmd*-syntaxis en werkt hier. De `V2_ROADMAP.md` §1.1-waarschuwing geldt voor PowerShell-invocaties; de Rust-sidecar gebruikt helemaal geen PowerShell meer (`lib.rs:310 taskkill_tree`, `:320 netstat`). | — |
| G5.3 ✅ | `stop_all.cmd` doodt `novatts-gui.exe` nooit, terwijl `App.svelte` de sidebar de user *naar* `stop_all.cmd` verwijst. **→ Opgelost in F0.** | `stop_all.cmd` |
| G5.4 | `_synth_emotion_aware` hardcodt `"source": "clipboard"` in de `Event("error", …)`-calls — wordt onjuist zodra de bron `luna`/`file` is. | `main.py:209, 221, 227, 261` |
| G5.5 | `SpeakerRegistry.update(…, instruct=…)` accepteert `instruct` maar **wijst het nooit toe**. Stille no-op. | `registry/speakers.py` |
| G5.6 | `registry.update()` is keyword-only; `registry.update(name, "voice")` (B-stijl) zou `TypeError` geven. Bij het toevoegen van Luna-code een afwijking voor beide moeten dragen. | idem |
| G5.7 | `main.py:451-453` losse regel tussen functie en import (ruff E303). | `main.py:451-453` |
| G5.8 ✅ | `.env.example` zegt `NOVATTS_QWEN_TIMEOUT=120.0`; `config.py:79` zegt `300.0`. **→ Opgelost in F0.** | `backend/.env.example:11` |
| G5.9 ✅ | `pyproject.toml` mist `[build-system]` — `pip install -e backend` werkt niet. **→ Opgelost in F0** (setuptools + `packages.find`; `pip install -e .` geverifieerd). | `backend/pyproject.toml` |
| G5.10 | `requirements-dev.txt` is **onvolledig**: `pytest` ontbreekt (terwijl er 7 testsuites zijn), `httpx2` ontbreekt (zonder het faalt `starlette.testclient` → `test_cutter.py` + `test_openai_speech.py` breken tijdens collectie), `types-pyperclip` ontbreekt (de enige `import-untyped`-fout). **Gevolg: de testsuite is vanaf een schone `setup.cmd` nooit draaibaar geweest.** Bevestigd in de nulmeting. **→ Opgelost in F0.** | `backend/requirements-dev.txt` |
| G5.11 ✅ | **De Makefile-gates konden niet falen.** `lint` en `test` eindigden allebei op `|| true`, dus `make lint`/`make test` printten "✓" en exitten 0 bij 27 ruff-errors en 2 mypy-errors. **De ergste vondst van F0** — de hele vangnet-garantie uit het plan steunde op deze targets. **→ Opgelost in F0:** `|| true` verwijderd, nieuw `gate`-target, alle 29 fouten gerepareerd. | `Makefile:126, 128, 133` |

### G6 — Docs/data-drift

| # | Drift | Actie |
|---|---|---|
| G6.1 | `data/emotion_sound_map.json` + `emotion_aliases.json` bestaan **niet** in Main (bewust uitgehaald in `e48c8ef`) | `emotions.py` bouwt ze op uit de schijf. **Geen actie** — moet zo blijven. |
| G6.2 | `data/speakers.json` bevat game-lokale namen (`where_the_heart_is`, `Anna`, `Brenda`, `D`, `Lilya`) | Persoonlijke data in de repo. Net als `e48c8ef` voor de emotion-map: overwegen om naar `data/games/` te verplaatsen + `.gitignore` (zie D5). |
| G6.3 | `brand-sub` in de GUI zegt nog `"Qwen3 · RenPy clipboard"` | → `"Qwen3 · LunaHook + clipboard"`. |
| G6.4 ✅ | Geen `.env`-documentatie voor de 9 hook-sleutels | **→ Opgelost in F1**: tabel in `README.md` + volledige uitleg in `backend/.env.example`, inclusief de proxy-diagnose. |

---

## 7. PLAN VAN AANPAK

**Regels die boven elke fase staan:**
1. **No regressie.** Na elke fase: `pytest` + `ruff check` + `mypy --strict` + `npm run build` groen. Een groene gate met rode tests is géén groene gate.
2. **Adoptie-geschiedenis.** Nieuwe test -> toevoegen aan de relevante testsuite, niet een nieuw bestand.
3. **Clean slate voor nieuwe modules, hergebruik voor gedeelde.** `parser/luna.py` en `adapters/luna.py` zijn nieuw → mag direct uit B worden overgenomen (na aanpassing). Allen wat Main al heeft → **nooit** vervangen.
4. **Commits zijn klein en reversibel.** Eén fase ≈ één serie commits op `Luna-Hook`, geen squashed megacommit.

---

### ✅ F0 — Baseline & veiligheidsnet *(gereed 2026-09-29)*

Doel: vóór er één regel Luna-code bijkomt, vaststellen *hoe* de huidige build er nou voor staat
en de gates echt laten falen als er iets mis is.

- [x] Vangnet: tag `pre-luna` op `e48c8ef`, branch `Luna-Hook` schoon.
- [x] `setup.cmd` gedraaid: venv 3.11.9, deps, `npm install` (50 pkg), `vite build` OK.
- [x] **Nulmeting** (§10.1) — en de nulmeting was slechter dan dit verslag suggereerde.
- [x] **G5.11 — de gates konden niet falen.** `|| true` weg uit `Makefile` `lint` + `test`; nieuw
  `gate`-target draait beide. Dit was de belangrijkste vondst van F0: het hele plan steunde op
  targets die per definitie groen waren.
- [x] **G5.10 — dev-deps incompleet.** `pytest`, `httpx2` (starlette 1.7 `TestClient`) en
  `types-pyperclip` toegevoegd aan `requirements-dev.txt`. De suite was vanaf een schone setup
  nog nooit draaibaar geweest.
- [x] **27 ruff-errors → 0.** 7 in `novatts/` (`SIM105`/`SIM108` → `contextlib.suppress`/ternary),
  4 in `tests/`, 14 in `convert_vox_to_clone.py`, 1 in `import_voices.py`. De echte fouten
  (`E722` bare except, `F841` dode `skip`) zijn gerepareerd, niet uitgehaald. Alleen de
  bewust compacte one-liner-stijl van `convert_vox_to_clone.py` is gedocumenteerd genegeerd
  (`per-file-ignores`, precies `E701`/`E702`, precies dat ene bestand).
- [x] **2 mypy-errors → 0.** `types-pyperclip` geïnstalleerd; `main.py:785` krijgt
  `# type: ignore[attr-defined, unused-ignore]` zodat de ignore zowel op Windows (stubs bekend)
  als elders correct is.
- [x] **G5.1 + G5.3 — `stop_all.cmd`.** Poort 8081 → 8765 (de backend draait op 8765; `start_all.cmd:63`
  en `lib.rs:299` bevestigden dat). `taskkill /T` + PID-0/4-guard toegevoegd. `novatts-gui.exe`
  wordt nu gedood — de sidebar verwijst de gebruiker hiernaar als "stop alles".
- [x] **G5.8** — `.env.example` timeout 120.0 → 300.0, gelijk aan `config.py:79`.
- [x] **G5.9** — `[build-system]` + setuptools-package-discovery toegevoegd aan `pyproject.toml`;
  `pip install -e .` werkt nu (geverifieerd).
- [x] **`backend/vntts/` verwijderd** — 35 bestanden, nul verwijzingen (D11: eigen commit).
- [x] **Eindmeting: `ruff` 0 · `mypy --strict` 0 · `pytest` 105 ✅ · `vite build` ✅.**

**Bewust niet gedaan:** de handmatige functionele smoke (echt RenPy-game → `Name: Text` → stem)
vereist een GPU, qwentts én een geïnstalleerd spel. Die hoort bij **F8**, waar de ws-route
daadwerkelijk naast RenPy wordt gezet — niet in F0, waar er nog niets te smoke-ten valt.

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

### ✅ F1 — Foundation (config, model, deps, barrels) *(gereed 2026-09-29)*

Doel: alles wat de Luna-laag nodig heeft bestaat, maar doet nog niets. **Geen gedragsverandering.**

- [x] `requirements.txt`: `websockets>=12.0` expliciet. Was er al als transitieve dep van
  `uvicorn[standard]` (geïnstalleerd: **17.1**), maar we importeren het zelf — dus een eigen
  regel is eerlijker dan leunen op andermans pin. *(Let op bij F3: de 13+ reeks liet de
  legacy `websockets.serve` shim vallen.)*
- [x] `pyproject.toml`: `[build-system]` + dev-deps — **al gedaan in F0**, dubbelde item geschrapt.
- [x] `models.py`: `Dialogue.raw: str = ""`. Alle 30 `Dialogue(...)`-calls in Main zijn
  keyword-based, dus plaatsing is veilig. `source` en `instruct` onaangeroerd.
- [x] `config.py`: 9 velden met Main-conventie (`NOVATTS_`-prefix, pydantic `Settings`).
- [x] `config.py`: **validator op `hook_mode`** die terugvalt op `both` i.p.v. te crashen.
  Zonder dit zou `NOVATTS_HOOK_MODE=websockets` een `ValidationError` geven *bij import* —
  de backend zou dan nooit opstarten. B deed dezelfde fallback met de hand.
- [x] `main.py`: `SettingsBody` (+8 velden), `_SETTINGS_ENV_MAP` (+8), `_SETTINGS_FIELD_TYPES`,
  `_settings_snapshot` (+9, inclusief de niet-schrijfbare `hook_host`).
- [x] **`_env_bool()`** — zie hieronder, dit was de echte valkuil van deze fase.
- [x] `.env.example` + `README.md`: de 9 sleutels gedocumenteerd (G6.4), inclusief de
  proxy-diagnose (`netsh winhttp show proxy`) uit `VN_Suite.py:3786-3814`.
- [x] `logconf.py`: `websockets.server` op `CRITICAL` (uit `VN_Suite.py:3813`). Hier i.p.v. in
  `adapters/luna.py` omdat het een logging-kwestie is die geldt voor élk entrypoint.
- [x] **`tests/test_hook_config.py`** — 48 nieuwe tests, 105 → **153**.

**De valkuil die deze fase onderweg vond:** `update_settings` deed `setattr(settings, f, str_val)`.
Voor een `bool`-veld wordt dat de *string* `"False"` — en `"False"` is **truthy**. Elke
boolean-toggle in de GUI zou de gebruiker negeren. Het bestaande veldset bevatte geen enkele
bool (de twee Qwen-bools staan niet in `_SETTINGS_ENV_MAP`), dus dit kon nog nooit kloppen.
`_env_bool()` lost het op: van 13 falsey-waarden leest de ingebouwde `bool()` er **5 verkeerd**.

**Bewijs dat de tests bijten (mutatiecheck, alle 3 gevangen):**

| Mutant | Uitkomst |
|---|---|
| `_env_bool` → `bool(value)` | `test_env_bool_reads_falsey_values[false]` faalt |
| `hook_mode`-fallback → `return value` | `test_bad_hook_mode_falls_back_to_both[websockets]` faalt |
| default `hook_mode` → `"websocket"` (D2 overtreden) | `test_hook_defaults_match_the_agreed_topology` faalt |

**Gate:** `ruff` 0 · `mypy --strict` 0 · `pytest` **153** ✅ · `vite build` ✅

---

### ✅ F2 — `parser/luna.py` (echte implementatie) *(gereed 2026-09-29)*

Doel bereikt: de ruimte-vorm parser draait en is getest. **Nog steeds niets aangesloten — 0 runtime-impact.**

- [x] `backend/novatts/parser/luna.py` herschreven (11 regels placeholder → 800 regels): `parse_luna()`, `is_plausible_character_name()`, `reject_ui_line()` uit B overgenomen, **5 constantensets + 16 UI-regexen** (het plan raadde 15; het zijn er 16 — zie onder)
- [x] **Niet** overgenomen: `_SCENE_LABEL_WORDS` (dood, G4.5)
- [x] Aangepast aan Main: `Dialogue(..., source="luna", raw=text)`, `instruct` wordt nu daadwerkelijk doorgegeven (B negeerde het)
- [x] Uitgebreid met G3.2/G3.3: `split_speaker_turns()` + `parse_luna_turns()` voor multi-spreker + newline-bare-name, Main-stijl (type hints, `re.Pattern[str]`)
- [x] `parser/__init__.py`: 6 Luna-symbolen in `__all__`
- [x] `LunaParser`-klasse toegevoegd, met hetzelfde register-contract als `RenPyParser` (geregistreerde naam wint van de heuristiek)
- [x] **Namen-unit-tests**: 9 `TestLunaParser`-tests uit B overgenomen, **plus 33 nieuwe** (`backend/tests/test_luna_parser.py`)

**Gate:** `ruff` schoon · `mypy --strict` schoon (31 bestanden) · `pytest` **153 → 195** · `npm run build` groen. 42 tests in de nieuwe suite, 0 runtime-impact.

#### F2 — vijf dingen die onderweg duidelijk werden

1. **16 UI-regexen, niet 15.** Het plan telde er 15. `test_all_ui_patterns_compiled` pint het exacte aantal, zodat een patroon dat stilletjes niet compileert niet meer onopgemerkt verdwijnt: de module slaat oncompileerbare patronen over i.p.v. de import te laten klappen — wat correct is voor een heuristie-lijst, maar fataal als een typefout drie maanden later pas opvalt.

2. **Dubbele spaties braken de multi-speaker-split.** De lookbehind `(?<=[.!?\u2026]\s)` eist precies één spatie, en `split_speaker_turns` normaliseerde whitespace niet — terwijl `parse_luna` dat wél doet. `"Anne Hallo!  Rick Mooi."` speelde dus volledig op Anne's stem. Opgelost door vóór de bounds-search te normaliseren. `test_split_survives_ragged_whitespace` is de regressie-reminder.

3. **Het register bereikte `parse_luna` niet.** De splitter deed wél registry-werk, maar de segmenten die hij opleverde werden daarna door een register-blinde functie teruggeparseerd. Gevolg: een geregistreerde `"Dr"` (een stopword!) werd correct afgesplitst en vervolgens meteen als niet-charakter afgewezen. `parse_luna` accepteert nu `known_names`, en de doorgegeven commentaar zegt waarom. **Dit was een onwaarheid in mijn eigen `LunaParser`-docstring, gevonden door een test die faalde.** Algemene regel: een docstring die een contract belooft is een test die het hoort te bewaken.

4. **Een gedocumenteerd gat is geen opgelost gat.** Drie plekken laten bewust afwijken van de referentie, elk met een test erbij die de beperking vastspeldt in plaats van haar te verbergen:
   - `test_known_gap_colon_form_multi_speaker_is_not_split` — `"Rick: Hoi. Anne: Doe!"` split niet; `VN_Suite.py` heeft dezelfde regex en hetzelfde gat. Een parserwijziging tegen een draaiende referentie is hoe een zeldzaam geval een niet-reproduceerbare stemfout wordt.
   - `test_known_gap_ui_patterns_only_match_the_whole_line` — de `Start|New|…`-patroon eindigt op `(?:\s|$)` maar is geankerst met `^…$`, dus alleen het kale woord matcht: `"Start"` wél, `"Start Game"` niet. Overgeërfd van B, dat het van `VN_Suite.py` overërfdde. Kandidaat voor een vervolgstap mét echte captures.
   - `test_known_gap_multi_word_names_cannot_open_a_space_form_turn` — `_NAME_TOKEN_SPACE` matcht één gekapitaliseerd woord, dus een geregistreerde `"Passenger 1"` kan nooit een space-form beurt openen. Wél werkend in de newline-vorm, waar de hele regel de naam is (nu ook voor meerwoords namen, dankzij fix 3).

5. **Mijn eerste twee testverwachtingen waren fout, niet de code.** `"Start Game"` en `"Passenger 1"` moeten wél falen. Dat is de richting die het moeilijkst is om zelf te zien: de test ziet er uit als een bug in de heuristiek, en de fix zou dan een gedrag veranderen dat de referentie al jaren stabiel houdt. Empirisch meten vóór een verwachting vastleggen — anders leg je de gewenste uitkomst vast in plaats van de werkelijke.

**Mutatiecheck** (5 mutanten, alle gevangen): mention-guard uit → 9 failures · `raw=text`→`raw=normalized` → 11 failures · normalisatie weg → 1 failure · register genegeerd → 1 failure · split-lookahead weg → 1 failure (die mutant overleefde de eerste ronde en kostte twee nieuwe tests, `test_trailing_sentence_stays_with_the_last_speaker` + `test_speaker_may_speak_twice`).

**Openstaande vraag D9** (`/status` met de laatste ruwe hook-regel) is niet in F3 maar in **F4** ingebouwd — daar wordt `LunaAdapter.last_raw` pas aangesloten.

---

### ✅ F3 — `adapters/luna.py` (ws-server) *(gereed 2026-09-29)*

Doel bereikt: een echte server, een echte client, een regel die binnenkomt als `Dialogue`. **Nog niet aangesloten op `NovaApp` — F4 doet dat.**

- [x] `backend/novatts/adapters/luna.py` **vervangen** (30 regels `NotImplementedError` → 590 regels; overwrite, geen patch)
- [x] `class LunaAdapter(InputAdapter)` met `name`-property → `"luna"` (G4.3)
- [x] Eigen daemon thread + eigen `asyncio` event loop. `start()` / `stop()` / `is_running()` / `client_count` (met lock)
- [x] **Server-modus** (default) op `websockets.asyncio.server.serve`, meerdere clients
- [x] **Client-modus** alleen als `luna_ws_url` gezet is, met reconnect
- [x] `decode_wire_message()` met G3.1 (`name`/`speaker`/`character` → `f"{name}: {body}"`) en G3.7 (`content`/`data`)
- [x] Garbage-guard: `is_renpy_exception` (altijd-aan, vóór alles) + `min_text_length` + het UI-gat uit de parser
- [x] Dual-hook: `hook_dual_hook` **wél** doorgeven en daadwerkelijk conditioneel (G3.4 — B deed dit niet)
- [x] Proxy-guard (G3.5): `NO_PROXY=127.0.0.1,localhost` voor het proces + één `netsh winhttp show proxy`-check met `warning()`
- [x] `on_dialogue()` via een **eigen dispatch-thread**, nooit synchroon in de event loop (G4.1)
- [x] `adapters/__init__.py`: `LunaAdapter`, `HookTextProcessor`, `decode_wire_message` in `__all__`
- [x] **68 tests** in `backend/tests/test_luna_adapter.py`, inclusief een echte ws-server + client op een echte socket

**Gate:** ruff schoon · mypy --strict schoon (31 bestanden) · pytest **195 → 263** · `npm run build` groen.

#### F3 — de ontwerpkeuze die het verschil maakt: drie lagen, één module

Het donor-bestand doet alles in één klasse: wire-decoding, naam-guards, parsing en de aanroep van `on_dialogue` zitten allemaal in `_handle_text`, en die wordt aangeroepen vanuit `async for msg in ws`. Daardoor draait **de volledige TTS-synthese op de event-loop-thread** — `qwen_timeout` is 300 seconden — en één trage synthese bevriest alle verbonden clients.

Hier is de module in drie lagen gesplitst, en de verdeling is niet willekeurig: **langzaam werk hoort zo ver mogelijk van de event loop af.**

| laag | wat | waarom apart |
|---|---|---|
| `decode_wire_message()`, `check_and_fix_proxy()` | pure functies over één bericht | testbaar zonder socket, thread of loop |
| `HookTextProcessor` | alle beslissingen + de enige mutable state (dual-hook-buffer) | `push()` in een lus aanroepen test het hele beslispad, geen server nodig |
| `LunaAdapter` | event loop, socket, dispatch-thread | verplaatst bytes en niets anders |

De event loop doet alleen: decoderen, filteren, in de wacht zetten, terug. Een aparte dispatch-thread doet `on_dialogue`. De wacht is begrensd (64) en **dropt** bij volle loop — blokkeren zou de event-loop-stall terugbrengen, onbeperkt groeien zou een weggelaten regel ruilen voor een out-of-memory uren later. `adapter.dropped` maakt dat zichtbaar.

**Waarom dit de juiste prioriteit was.** Het hele doel van de hoofdsom is onderhoudbaarheid, en dit is de plek waar de oorspronkelijke alles-in-eén-aanpak pijnlijk is: de ontwerpbeslissing is niet uit de code af te lezen, dus hij verdwijnt bij de eerste refactor en komt later terug als een sporadische "het hapert vast"-klacht. Hier is hij een type, een klassenaam en een test.

#### F3 — vier dingen die onderweg duidelijk werden

1. **Dual-hook at zijn eigen tekst op.** `is_name_only("Hello there")` was `True` — twee gekapitaliseerde woorden voldoen aan de naamvorm. Gevolg: de *body*-regel werd ook gebufferd, de merge vuurde nooit, en **elke regel verdween stilzwijgend** in plaats van verkeerd toegeschreven. De regel is nu *positief bewijs*: een colon is expliciet, een enkel plausibel woord is ambigu genoeg op zichzelf, en een kale meerwoords regel moet een geregistreerde naam zijn. "Miss Brooks" werkt daardoor nog (met colon, of na registratie) maar "Rick Hello" niet meer.

2. **Een bug in mijn eigen fix, gevonden door een test.** Ik strip de colon vóór ik ernaar test, dus `candidate.endswith(":")` was permanent `False` en de colon-tak van regel 1 deed niets. Dit is de derde keer in twee fasen dat een plausibele fix stilletjes dood was — de rode draad is niet voorzichtigheid maar **meten**: elke keer bleek de aanname waarop ik had gebouwd onjuist, en de test was het enige dat dat aan het licht bracht.

3. **Met dual-hook uit werd `"Rick:"` hardop voorgelezen.** De parser las het als narratie en zei het woord "Rick" hardop. Een naam zonder tekst is nu altijd een drop, ongeacht de merge-instelling: er valt niets te zeggen, en zonder dual-hook komt de body sowieso als aparte regel.

4. **B's parser-keten is vervangen, niet uitgebreid.** B deed `parse_renpy` eerst en `parse_luna` als terugval. De strikte RenPy-parser weigert ruimte-vorm, dus de terugval haalde die regels nooit in. `HookTextProcessor` roept `parse_turns` aan, één ingang die beide vormen en de multi-speker-regel aankan.

**Websockets 17.1** (F1 zette `>=12.0`): de legacy `websockets.serve`-shim bestaat nog maar is deprecated. Hier wordt `websockets.asyncio.server.serve` gebruikt, de nieuwe asyncio-implementatie. De vloer moet omhoog naar `>=14.0` — dat staat als todo in F7, waar de deps-explicitie hoort.

**Mutatiecheck** (11 mutanten, alle gevangen): synchroon in de loop (= B's ontwerp) → 1 failure · `name`-keys weg → 9 · `data`-key weg → 1 · dual-hook genegeerd → 1 · dual-hook altijd uit → 2 · TTL genegeerd → 1 · queue onbeperkt → 1 · registry-eis 2 woorden weg → 1 · min-length genegeerd → 1 · name-only valt door → 2.

Twee mutanten waren **no-ops en telden niet mee**: een `; _ = 0` die ik als "synchrone callback" introduceerde (niets veranderde) en het verwijderen van een `log.debug` vlak vóór een `return []`. Beide overleefden dus terecht. Een mutatiecheck die stille no-ops telt, is een controlesom die groen kleurt zonder iets te controleren — de eerste helft van elke mutatie moet gecontroleerd worden op of zij het gedrag werkelijk verandert.

**D9 is deels beantwoord.** `adapter.last_raw` bewaart de laatste ruwe regel vóór parsing, omdat "er komt niets aan" en "het komt aan en wordt verkeerd geparseerd" er van buitenaf identiek uitzien. F4 beslist of `/status` dit exposeert.

**Openstaand voor F4:** de trust-gate op auto-registratie. `source == "luna"` moet géén permanent stem koppelen, want de space-vorm is een gok.

---

### ✅ F4 — Bedrading in `NovaApp` *(gereed 2026-09-29)*

Doel bereikt: de hook-pipeline is live naast de RenPy-pipeline, en elke regel die spreekt is door één poort gegaan. **De RenPy-route houdt dezelfde adapter, dezelfde parser en dezelfde registratie** — `hook_mode=clipboard` gedraagt zich als vóór F4, met één bewuste toevoeging: de dedup van 500 ms geldt nu óók voor de clipboard (`A → B → A` binnen een halve seconde sprak vroeger twee keer `A`, want de adapter onderdrukt alleen een onveranderde herhaling).

- [x] `NovaApp._start_adapters()`: adapter-keuze uit `settings.hook_mode` — `clipboard` / `websocket` / `both` (default `both`). **B's inline `app.py` NIET overgenomen** (G4.1); Main's `dialogue-worker` + `_wake` + `_pending_seq` blijft de enige synthese-route
- [x] Dedup — maar niet als `dict` in `NovaApp`: ondergebracht in `novatts/gate.py`
- [x] Trust-gate op auto-registratie — **anders dan het plan voorschreef**; zie D15 en "wat onderweg duidelijk werd" punt 1. De geplande regel (`is_plausible_character_name`) is gemeten een **no-op**
- [x] `is_blacklisted_name()` **bewust niet toegevoegd** — zie D18
- [x] `status()` uitgebreid: `hook_mode`, `hook_clients`, `hook_dropped`, `hook_last_raw` (D9). Het `dialogue`-event heeft nu `source` + `guess`
- [x] G5.4 gefixt: alle vier de hardcoded `"source": "clipboard"` zijn nu `dialogue.source`
- [x] `stop()`: LunaAdapter eerst, dan clipboard, dan worker, dan player, dan qwen, dan `gate.forget()`, dan registry-autosave
- [x] **`novatts/gate.py`** (nieuw, ~230 regels): `DialogueGate.admit()` → `Admission(dialogue, reason, new_speaker, guess_only, accepted)`
- [x] **55 nieuwe tests**: `test_dialogue_gate.py` (27, inclusief de 2 naad-tests), `test_luna_parser.py` +10, `test_main_wiring.py` (13), `test_luna_adapter.py` +4, `test_voice_manager.py` +1. `NovaApp` had tot F4 **nul** tests

**Gate:** `ruff` schoon · `mypy --strict` schoon (32 bestanden) · `pytest` **263 → 318** · `npm run build` groen. **27 mutanten, 27 gevangen.** Handmatige RenPy-smoke: zie F8 (D14).

#### F4 — waarom er een `gate.py` is en niet een `dict` in `NovaApp`

Het plan zei: dedup als `self._dedup: dict[tuple[str, str], float]` in `NovaApp`. Dat is precies één van de redenen waarom `NovaApp` in het donor-project een ononderhoudbare prop werd: elke beslissing over "mag deze regel klinken" zat in één methode van 40 regels, en dus kon geen enkele beslissing apart getest worden.

De poort is daarom een eigen klasse met één publieke methode. Dat levert drie dingen op die `NovaApp` zelf niet kan geven:

1. **De beslissingen zijn testbaar zonder de app.** Geen `AudioPlayer`, geen `QwenManager`, geen pygame: `DialogueGate(registry, blacklist, dedup_window_ms, clock)` is genoeg. De `clock` is injecteerbaar, dus geen enkele test slaapt voor een venster van 500 ms.
2. **De volgorde van de checks is expliciet.** Exception → leeg → dedup → blacklist → vertrouwen. Die volgorde *is* de logica, en in een lange `if`-keten in `on_dialogue` was hij nergens vastgelegd.
3. **Er is één plek voor F5.** De file-watch-route voedt `on_dialogue`, dus hij erft alle regels automatisch. Zonder poort zou hij een tweede, licht afwijkende kopie van de checks krijgen — en dan is "dezelfde regel klinkt anders via een andere bron" een kwestie van tijd.

`on_dialogue` houdt wat écht over deze app gaat: events uitsturen en de regel aan de worker geven.

#### F4 — wat onderweg duidelijk werd

1. **De geplande trust-gate was een no-op — gemeten, niet vermoed.** Het plan wilde registreren toestaan als `is_plausible_character_name(name)`. Meting op echte hook-vormen: **élke** naam die de parser als spreker accepteert, slaagt ook voor die functie. De regel zou dus nooit iets tegenhouden. Wat de meting wél liet zien: `Speaker(name=X)` krijgt `voice=""`, niets in backend of GUI kent ooit een stem toe aan een nieuw geregistreerde naam, en een junk-naam (`"Kitchen"`) verandert de splits niet. **Conclusie: de gate gaat niet over verkeerd geluid maar over registerhygiëne** — een bestand dat de gebruiker met de hand onderhoudt mag niet vollopen met woorden die de heuristiek één keer zag. Nieuwe regel: registreer alleen als de naam **gesteld** was (`speaker_is_guess is False`); een gok spreekt op de modelstem maar wordt niet bewaard. Zie D15.

2. **De registry-docstring beloofde al wat de code niet deed.** `registry/speakers.py` (Main's eigen bestand, nooit van B overgenomen) zegt in zijn modulebeschrijving: *"Unknown speakers NEVER get a new voice slot; they fall back to `Narrator` at call sites and are never auto-registered from Luna."* Die belofte stond er al en `on_dialogue` deed het tegendeel. Dit is de variant van F2-punt 3 die je niet zelf schrijft: **een bestaand contract dat de code overtreedt.** De gate maakt de docstring waar voor gegokte namen — en de formulering "never auto-registered from Luna" was blijkbaar al geschreven door iemand die de juiste regel kende.

3. **`NovaApp` had nul tests, en dat is waarom twee echte bugs er jaren konden zitten.** Geen van de 9 bestaande suites raakt `on_dialogue`, `_synth_emotion_aware` of de adapters. Twee gevolgen, beide gemeten:
   - **`raw` ging verloren** in het `_synth_emotion_aware`-pad: segmenten werden met de hand opnieuw opgebouwd en alleen `speaker`/`text`/`source`/`instruct` doorgegeven. Het forensische record uit F1 verdween dus precies wanneer een emotie-tag in de tekst stond. Opgelost met `_segment_dialogue()`, dat ook `speaker_is_guess` meeneemt.
   - De hierboven genoemde **ontbrekende trust-gate** kon onopgemerkt blijven, want niemand controleerde `registry.names()` na een hook-regel.
   
   **Les:** de poort-tests zijn niet "extra" — ze zijn de eerste tests die deze code ooit heeft gehad.

4. **`_refresh_known_speakers()`: drie call sites, twee daarvan hadden het gat al.** Bij het schrijven van de mutant voor de start-volgorde bleek `set_known_speakers` op **drie** plekken te staan: `_start_adapters`, `switch_game` en `POST /speakers`. Alleen de eerste was in F4 aangepast aan de hook. De andere twee kenden `luna` niet — dus:
   - een **gamewissel** liet de hook de oude cast houden (de clipboard kreeg wel de nieuwe);
   - een **handmatige registratie** via de GUI bereikte de hook nooit.
   
   Dat tweede is niet theoretisch: de trust-gate vraagt de gebruiker letterlijk om een gegokte naam zelf te registreren. Als die registratie de hook niet bereikt, heeft de gebruiker het juiste gedaan en ziet hij niets veranderen — **de remedie die de gate aanwijst werkt dan niet.** Nu één helper voor alle drie de plekken, plus de invariant "namen vóór threads" (beide adapters parsen in een thread die pollt zodra `start()` terugkeert) vastgelegd in een test.
5. **De parser had een tweede coördinatenstelsel.** De multi-spreker-split voegde eerst overal een `:` in (waardoor de tekst langer werd) en sneed daarna met offsets die op de tekst *zonder* die `:` waren berekend. Elke ingevoegde `:` verschoof dus alle latere grenzen met één — zichtbaar als een beurt die zijn puntverlies verloor (`test_speaker_may_speak_twice` ving het). Omdat de herkomstvlag op **positie** wordt gezet, zou dezelfde fout ook de vlag van de verkeerde beurt hebben gezet: een stil fout antwoord in plaats van een zichtbare fout. Nu wordt er op de originele tekst gesneden en gaat de `:` er per segment achteraan.
6. **De dedup-sleutel is de ruwe vorm, en dat is een bewuste beperking.** De sleutel is `(speaker or "", raw or text)`, want de ruwe aanvoer is wat twee leveringen herkenbaar dezelfde uiting maakt. Gevolg: als de hook `"Rick Answer the door."` stuurt en de clipboard `"Rick: Answer the door."` bevat, zijn het voor de poort twee uitingen. Dat is vastgespeld in `test_differing_raw_text_defeats_dedup_today` in plaats van "opgelost" — de vergelijking zou de parser binnen een venster van 500 ms nodig hebben, en dat is de verkeerde laag. Kandidaat voor een latere stap **met echte captures**.
7. **Mijn meetinstrument vergiftigde zijn eigen proefstuk.** De mutatie-harness schreef de bron terug binnen dezelfde seconde en met dezelfde byte-lengte (`[0]` → `[1]`), en Python's `.pyc`-validatie is `(mtime in seconden, size)`. De **herstelde originele** bron kreeg dus de **gemuteerde** bytecode voorgeschoteld, en een volgende testrun leek een echte regressie te tonen die niet bestond. Gevolg: alle mutantmetingen zijn opnieuw gedaan met caching uit (`-B`) en een schone pycache per meting. Permanente regel §12.10.
8. **De `filtered`-payload is verbreed en dat is veilig.** De GUI roept `/events` wel aan in `api.ts`, maar verbruikt nergens in de codebase een `filtered`/`speaker_discovered`/`unassigned_speaker`-type; `EventEntry.payload` is `Record<string, unknown>` en wordt niet uitgelezen. De nieuwe `source`/`speaker`-keys zijn dus additief zonder consument.

9. **De gevaarlijkste bug zat tússen twee geteste lagen, niet erin.** De trust-gate las `speaker_is_guess`; de parsertests controleerden dat de parser de vlag zet; de gate-tests bouwden hun `Dialogue` met de hand en controleerden dat de gate hem respecteert. Alles groen — en toch was de gate op het echte hook-pad **inert**, want `HookTextProcessor.push()` bouwde elke `Dialogue` opnieuw op en gaf `speaker_is_guess` niet door. Geen enkele test voerde de uitvoer van de processor ooit aan de gate. Gemeten: `"Rick Hello there"` via `push()` gaf `speaker_is_guess=False`, dus élke space-vorm spreker werd geregistreerd — precies wat D15 verbiedt. De vlag was gemeten aan het ene uiteinde en vertrouwd aan het andere, en niemand liep de draad na. **Les:** twee lagen die elk groen zijn bewijzen niets over de verbinding ertussen; de nieuwe klasse `TestTheHookProcessorSeam` voert de echte processor in de echte gate.

10. **Daarna bleek "Dialogue met de hand herbouwen" de rode draad.** Dezelfde fout zat op drie plekken: de emotie-segmenten, de blacklist-rebuild in de poort, en `voice_manager.clean_dialogue`. `Dialogue` is een frozen dataclass, dus alle reconstructies zijn nu `dataclasses.replace(...)`: dat kopieert élk veld, dus een veld dat later aan `Dialogue` wordt toegevoegd kan niet meer stil verdwijnen. Zie §12.11. (De mutanten G2 en G7 uit de eerste ronde moesten worden herricht: ze muteerden de handmatige code die nu weg is.)

**Mutatiecheck** (27 mutanten, alle 27 gevangen — 10 in `gate.py`, 3 in `parser/luna.py`, 1 in `adapters/luna.py`, 12 in `main.py`, 1 in `voice_manager.py`): o.a. trust-gate uit · `raw`-behoud weg · dedup-prune weg · venstergrens `<` i.p.v. `<=` · dedup-uit-stand weg · herkomst in de filter-rebuild weg · dedup-sleutel op tekst alleen · `hook_mode`-takken verwisseld · stop-volgorde om · adapters niet bijgepraat · namen ná start i.p.v. ervoor · `POST /speakers` praat de hook niet bij · en de naad zelf: `push()` die de herkomst laat vallen · het emotie-segment dat de herkomst wist · `clean_dialogue` dat de herkomst wist.

**Openstaand:** D10 (`qwen_autostart` hook-aware) is F7.

**Gate-handtekening:** RenPy-handmatige smoke is bewust F8 (D14); de geautomatiseerde RenPy-dekking is `test_clipboard_mode_starts_only_the_clipboard` + de bestaande `test_renpy_parser.py`-suite, die ongewijzigd groen is.

---

### ✅ F5 — `adapters/file_monitor.py` (tertiair) *(gereed 2026-09-29)*

Doel bereikt: een derde vangnet dat iets toevoegt zonder een **tweede interpretatie** van "wat betekent deze regel" te introduceren.

**Dit is bewust géén port van B's bestand.** B's `file_monitor.py` (68 regels) wordt niet overgenomen maar doorgedronken tot een dunne laag **over** de in F3 gebouwde `HookTextProcessor` (D19). B's route heeft bovendien **geen referentiegedrag**: `VN_Suite.py` kent géén file-route, dus er viel niets te verifiëren — alleen te verzinnen, en dan zo dun mogelijk.

- [x] `new_file_text(previous, current) -> str` — pure functie, de enige *nieuwe* beslissing in de hele route, zonder filesystem te testen
- [x] `FileMonitorAdapter(InputAdapter)` — `name = "file"`, `source="file"`, `last_raw`, warn-eenmalig bij ontbrekend bestand
- [x] Alleen actief als `NOVATTS_FILE_WATCH=1`; **niet** onderdeel van `hook_mode` (zie keuze 3)
- [x] Zelfde processor, zelfde poort, zelfde dedup — F4 wordt geërfd, niet gekopieerd
- [x] **23 tests** in `tests/test_file_monitor.py` (incl. één die de échte poll-thread draait) + 4 in `test_main_wiring.py`
- [x] **`NovaApp._adapters()`**: één plek voor de adapterlijst, gebruikt door prime/start/stop

**Gate:** `ruff` schoon · `mypy --strict` schoon (33 bestanden) · `pytest` **318 → 345**, waarvan **6 omgevingsafhankelijk falen** (zie "de meting die niet groen kon zijn") · `npm run build` groen. **33 mutanten, 33 gevangen** (+6 nieuw voor F5, waarvan 2 op de `_adapters()`-tuple).

#### F5 — de meting die niet groen kon zijn, en wat dat wél was

De volledige suite gaf **339 passed, 6 failed**, alle zes in `tests/test_openai_speech.py`. Dat is geen F5-probleem, en dat is **gemeten** in plaats van geargumenteerd:

| meting | uitkomst |
|---|---|
| zelfde 6 tests op de **schone F4-boom** (`git stash -u`) | **6 failed, 6 passed** — identiek |
| `Get-NetTCPConnection -LocalPort 8080` | pid 7528, `python`, gestart 09:27 — **Open WebUI**, niet `tts-server.exe` |
| `GET http://127.0.0.1:8080/` | **200** + Open-WebUI-branding-HTML |
| `POST http://127.0.0.1:8080/v1/audio/speech` | **405** |

`NOVATTS_QWEN_URL=http://127.0.0.1:8080`, en die poort hoort inmiddels aan Open WebUI. `maybe_autostart()` weigert terecht een tweede server op een bezette poort (`.env` zegt er zelf bij: *"If that port is busy, start qwentts with --port 8081"*), waarna de request bij Open WebUI belandt en 405 krijgt.

Die zes tests zijn **integratietests zonder mock**: de fixture start een échte `NovaApp` en doet een échte HTTP-call. Zonder levende qwen-server kunnen ze niet groen zijn. Ze zijn dus niet onderdrukt en niet gemarkeerd — §12.8 is hier geen aanleiding voor een `skip`, want dan zou de gate een kapotte omgeving verbergen in plaats van hem benoemen. F5 zelf is groen: `pytest --ignore=tests/test_openai_speech.py` → **333 passed**.

#### F5 — de drie ontwerpkeuzes, alle drie gemeten

**1. Eén regel per delivery, niet de hele wijziging in één keer.** Gemeten voordat er code was:

| aanvoer | `parse_luna_turns()` | `HookTextProcessor.push()` |
|---|---|---|
| `"Rick Hello\nAnne Bye"` | `[("Rick", "Hello Anne Bye", True)]` | idem |
| `"Rick\nAnswer the door."` | `[("Rick", "Answer the door.", True)]` | idem |

De parser splitst **niet** op newlines; hij plakt ze aan elkaar. Dat is ontwerp uit F2 (de `Rick\n…`-vorm moet juist weer aan elkaar), maar het maakt "de hele wijziging als één regel sturen" ongeschikt voor een groeiend log: regel twee wordt dan de tekst van spreker één. **Fout geluid met de verkeerde stem** is erger dan een regel die als tekst inleest. Daarom per regel pushen — dezelfde eenheid als een socket-frame.

**2. Append herkennen mag alleen op een regeleinde.** De donor en de eerste opzet gebruikten simpelweg `current.startswith(previous)`. Dat is stuk bij een overschrijvend bestand: `"Rick"` gevolgd door `"Rick Hello"` levert dan `"Hello"` op — de naam wordt opgegeten en de regel komt als vertelstem binnen. De regel is nu dat er een `suffix` pas bij een regeleinde voor een append telt; anders is het een vervanging.

**3. `file_watch` staat buiten `hook_mode`.** `hook_mode` kiest tussen clipboard en websocket. De file-route is geen derde keuze in die rij, maar het vangnet voor wanneer **geen van beide** kan draaien — anders zou `hook_mode=websocket` de fallback uitschakelen, precies in de situatie waarvoor hij bedoeld is. Eigen vlag, eigen beslissing; vastgelegd in `test_the_file_route_is_independent_of_hook_mode`.

#### F5 — de gedocumenteerde limiet (vastgespeld, niet verzwegen)

Per regel leveren betekent dat een schrijver die naam en tekst op **aparte** regels zet de naam geen lichaam geeft:

| bestandsinhoud | zonder `hook_dual_hook` | met `hook_dual_hook` |
|---|---|---|
| `"Rick\nAnswer the door."` | `[("Answer", "the door.")]` | `[("Rick", "Answer the door.")]` |

Zonder dual-hook wordt `"Rick"` als kale naam weggegooid en wordt `"Answer"` — een plausibele karakternaam — tot spreker. Dat is exact de vorm waarvoor `hook_dual_hook` bestaat (die buffert een kale naam en plakt hem aan de volgende regel), dus de handleiding is niet "het werkt niet" maar "zet deze vlag". **Beide helften zijn tests** (`TestTheNameOnItsOwnLine`), zodat een volgende agent dit niet als ontbrekende functionaliteit gaat repareren.

#### F5 — de vier donorfouten die hier níét zijn overgenomen

| B's `file_monitor.py` | Waarom niet |
|---|---|
| `mtime != _last_mtime` als hek | Op een filesystem met grove timestamps wordt een herschrijving binnen dezelfde tick gemist — de valkuil is een **stil** dood vangnet. Nu: elke tick lezen en vergelijken; het bestandje is klein. |
| `except Exception: pass` | Stilzwijgen bij een fout in een vangnet is precies wat je niet wilt. Nu `log.exception`. |
| Handmatig `Dialogue(...)` herbouwen | Z §12.11, F4-punt 10. Er is hier helemaal geen rebuild: de processor geeft de regels door. |
| `parse_renpy` in de keten | De F3-beslissing: de file-route gebruikt **dezelfde** luna-processor als de ws-route, anders heeft NovaTTS twee interpretaties van dezelfde regel. |

#### F5 — wat onderweg duidelijk werd

1. **`InputAdapter` miste `set_known_speakers`; mypy ving het zodra de lus getypeerd werd.** `_refresh_known_speakers` riep de methode duck-typed aan. Zodra F5 `_adapters() -> tuple[InputAdapter, ...]` introduceerde, werd de aanname een typefout in plaats van een stil werkende aanname: *"InputAdapter has no attribute set_known_speakers"*. De methode staat nu **op de interface** (abstract, met contract-docstring). Dat is precies de winst van D16/F3's regel "maak invarianten tot typen": een bron die later wordt toegevoegd kan de priming niet meer overslaan, en de drie call sites hoeven niet meer elk te weten dát er geprimd moet worden.

2. **F4's "drie call sites, twee ervan hadden het gat"-bevinding had een derde call site verborgen.** F4 voegde `_refresh_known_speakers` toe om het gat in drie plekken te dichten. F5 voegt een route toe en daarmee een **tweede** plek waar de lijst met adapters nodig is — en de eerste was `_start_adapters`/`stop`, die de adapters tot nu toe individueel benoemden. Opgelost met één `_adapters()`-helper; de 4 nieuwe wiring-tests dekken flag-uit, flag-aan, onafhankelijkheid van `hook_mode` en de stop-volgorde.

3. **De vier tests van `test_main_wiring.py` kregen een autouse fixture.** Zonder die zou één test die `NOVATTS_FILE_WATCH` aanzet een latere adapter-selectietest een extra adapter kunnen laten zien en die op een andere plek laten falen. De hele file hanteert al "per test zelf beslissen" voor `hook_mode`; de vlag hoort daar net zo goed bij.

---

### ✅ F6 — GUI *(gereed 2026-09-29)*

- [x] `types.ts`: `HookMode` als **unie** (niet `string`); 10 hook-/file-velden op `ServerStatus`; 9 op `SettingsData`
- [x] `SettingsPanel.svelte`: nieuwe sectie **"Text hook"** met alle 9 instellingen (plan zei er 2 — zie D23)
- [x] `Dashboard.svelte`: Hook-kaart + twee voorwaardelijke banners — géén nieuwe tab
- [x] `App.svelte`: `brand-sub` → `"Qwen3 · LunaHook + clipboard"` (G6.3)
- [x] `main.py`: `status()` krijgt de **file-route** erbij — die miste nog, dus de kaart zou voor die route leeg zijn geweest
- [x] `tests/test_status_contract.py`: 9 tests. **`status()` had hiervoor nul tests** en is nu de plek waar de GUI aan hangt
- [x] `svelte-check` als gate: `npm run check` (gui) en `npm run lint` (root, nu beide talen)
- [x] `api.ts`: `api.speakers()` retourneert het **responsformaat** i.p.v. het bestandsformaat — daarmee 2 bestaande type-errors aan de bron gerepareerd

**Gate:** `vite build` ✅ · `svelte-check` **0 errors / 0 warnings** ✅ · `ruff check .` 0 ✅ · `mypy --strict novatts` 0 ✅ · `pytest` **354 ✅ / 0 ❌** (de 6 omgevingsfalen uit F5 zijn weg — poort 8080 gaf vrij; zie de F5-sectie).

#### F6 — de baseline moest eerst groen worden, en dat was een echte bug

De fase-gate is `svelte-check groen`, maar er was **nooit** een `check`-script. De eerste meting gaf:

```
SpeakersPanel.svelte:30  Error: Conversion of type 'Record<string, Speaker> & {versions…}'
SpeakersPanel.svelte:35  Error: Conversion of type 'Record<string, Speaker> & {versions…}'
svelte-check found 2 errors and 1 warning
```

Twee **bestaande** type-errors, niet door F6 veroorzaakt. De gebruikelijke uitweg was `as unknown as` — precies de verzwakking die de melding afraden. De ware oorzaak stond in `api.ts`:

```ts
// voor: het BESTANDSformaat, terwijl /speakers het RESPONSformaat teruggeeft
speakers: () => req<Record<string, Speaker> & { versions: number; fallback: string }>("/speakers"),
// na
speakers: () => req<SpeakersResponse>("/speakers"),
```

Het backend-antwoord is `{versions, speakers, fallback}` (zie `registry.to_dict()` plus de `fallback` in de route). De intersection `Record<string, Speaker> & {versions, fallback}` was bovendien zelf al onzin: `versions: number` botste met de index-signature. Door het type bij de bron te repareren vervielen **beide** casts in plaats van verzwakt te worden. Dat is het verschil tussen een patch en een fix: de volgende agent die `/speakers` aanroept krijgt nu het juiste type, en hoeft geen cast meer te gokken.

De derde melding was de `tsconfig.node.json`-waarschuwing (*"Referenced project may not disable emit"*). Opgelost door `emitDeclarationOnly` + `declarationDir: "./.tsbuild"` — een composite-project moet iets emitteren; de output wordt weggegooid en staat in `.gitignore`.

> **Waarom telt dit als F6-werk en niet als schoonmaak?** Omdat een gate die je pas ná je eigen wijzigingen introduceert een *nieuwe* rode baseline mag hebben — dan is zij niet meer afnemend en dus geen gate meer (Z §12.9). De grens is niet "is het mijn code" maar "is de gate hierna sterker dan hiervoor".

#### F6 — de kaart onderscheidt drie toestanden, niet één vlag

Het simpele recept is één getal (`hook_clients`) en een groen of rood puntje. Dat is onbruikbaar, want de drie situaties die een gebruiker tegenkomt hebben elk een **andere oplossing**, en geen van drie is zichtbaar in "niet verbonden":

| Toestand | Wat de gebruiker ziet | Wat hij moet doen |
|---|---|---|
| Niemand verbonden | `waiting` · *LunaTranslator not connected* | LunaTranslator starten en de `.xdll` op `ws://127.0.0.1:6677` zetten |
| Verbonden, nog geen regel | `1 client` · *connected, no line yet* + banner | De hook aan het **spelvenster** hangen (D9) |
| Regels komen binnen en worden gedropt | `1 client` · *N dropped — synthesis is behind* + banner | Spel pauzeren, of stemlatency omlaag |

De derde toestand is de reden dat `hook_dropped` in `/status` staat en niet alleen in de log. Zie D25.

#### F6 — de lint-gate had dezelfde ziekte als de Makefile, één laag hoger

F6 voerde `svelte-check` in aan `npm run lint`. Dat script was tot dan toe `npm run lint --workspaces --if-present & ruff check backend` — en `&` levert de exitcode van de **laatste** opdracht:

```
$ cmd /c "type C:\nietbestaand.txt & echo TWEEDE-DRAAIDE"
TWEEDE-DRAAIDE
Het systeem kan het opgegeven bestand niet vinden.
exitcode = 0        ← de fout is weg
```

Dus het toevoegen van een tweede taal aan de gate maakte de gate **in stilte zwakker**: een type-fout in de GUI zou door een groene ruff worden weggeschreven. Opgelost met `&&`, en gemeten dat het nu beide kanten faalt:

| Injectie | `npm run lint` |
|---|---|
| niets | `0` ✅ |
| `export const __f6_probe: number = "kapot";` in `types.ts` | `1` ❌ (svelte-check) |
| `novatts/_f6_probe.py` met `x = 1` | `1` ❌ (ruff) |

Tegelijk is `ruff` vervangen door de expliciete venv-interpreter (`backend\.venv\Scripts\python.exe -m ruff`), zodat de gate niet meer van een ontwikkelaars-PATH afhangt. Dit is §12.8 in een andere taal — Z §12.13.

#### F6 — twee dingen die de meting tegenspraken

1. **Mijn eerste verklaring waarom `$derived` niet werkt was onjuist, en ik heb hem niet opgeschreven omdat ik hem eerst wilde meten.** Het symptoom was *"Property 'hook_mode' does not exist on type 'never'"* — het leek alsof Svelte 5 `$derived` op `$state` kapot is. Dat is niet zo: op component-**top-level** narrowt TypeScript `status` naar `null`, direct na `let status: ServerStatus | null = $state(null)`, dus élke top-level eigenschapsread faalt. Gemeten met een gewone regel zonder `$derived`:

   ```svelte
   const __topLevelPlainRead = status?.hook_mode;   // faalt exact even hard
   ```

   Binnensloten wordt die narrowing van een gecapte `let` gereset, en daarom werken de `const hookOn = () => …`-functies wel. Overigens gebruikt de rest van deze GUI nergens `$derived` — overal staan de expressies in de template, waar ze tegen de **gedeclareerde** type worden gecheckt. De regel die hieruit volgt staat nu als commentaar in `Dashboard.svelte`, want de volgende agent die dit bestand opent moet hem niet opnieuw uitzoeken.

2. **Mijn eerste opzet had geneste `<label>`** (`label.field-row` met daarin `label.chk`). Dat is ongeldig HTML; de browser haalt de buitenste eruit en dan stopt het pad-veld de checkbox te togglen. Nu is de buitenste een `div`. Geverifieerd in de browser: met "on" aangevinkt wordt het pad-veld `enabled`, en daarvoor moest `form.file_watch` daadwerkelijk door de checkbox worden gezet.

#### F6 — de GUI echt gezien, niet alleen gebouwd

`svelte-check` en `vite build` zeggen niets over de vraag of de kaart iets zinvols toont. Daarom de volledige keten één keer handmatig gedraaid: backend op `:8765` (`hook_mode=both`, geen client), de gebouwde GUI op **`:1420`** — die poort staat al in de CORS-allowlist, dus geen eenmalige CORS-uitzondering nodig — en daarna:

| Geverifieerd in de browser | Uitkomst |
|---|---|
| `brand-sub` | `Qwen3 · LunaHook + clipboard` |
| Hook-kaart, geen client | `waiting` · *LunaTranslator not connected* |
| `/settings` → sectie "Text hook" | rendert met `ws://127.0.0.1:6677` live uit de settings |
| Source-select | 3 opties, `both` geselecteerd |
| Bind address | read-only, met *restart required* ernaast |
| File watch | pad-veld disabled; na tikken **enabled** (bewijst de binding) |
| Space form / Dual hook | `true` / `false`, de gedocumenteerde defaults |
| Console / netwerk | 0 fouten, alle requests 200 |

Er is bewust **niet** op *Save to .env* geklikt: dat zou de echte `.env` van de gebruiker herschrijven. `git status` bevestigt achteraf dat hij schoon is.

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

- [x] `backend/vntts/` verwijderen — **gedaan in F0** (niet hier; nul functionele impact, makkelijk terug te draaien)
- [ ] G5.5 (`update(instruct=)` no-op), G5.6 (kw-only), G5.7 (ruff E303) fixen
- [x] G5.8 (`.env.example` timeout) — **gedaan in F0**
- [ ] G6.2: persoonlijke speakers uit `data/speakers.json` naar `data/games/` verplaatsen + gitignore
- [ ] `[project] description` in `pyproject.toml` van `"…(RenPy/Qwen3)"` naar `"…(LunaHook/Qwen3)"`
- [ ] Ruff-uitsluitingen herevalueren zodra de persoonlijke hulpscripts zijn opgeschoond

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
| **D9** ✅ | **Ja** — en hij is in **F4** ingebouwd, niet F3. `status()` geeft `hook_last_raw`: de laatste ruwe regel die de hook aanleverde, vóór parsing. Het is het enige veld dat "er komt niets binnen" scheidt van "het komt binnen en wordt verkeerd geparseerd"; elk ander veld in `/status` ziet die twee gevallen identiek. | Afgevinkt in F4. |
| **D10** | Moet `qwen_autostart` in de toekomst `both`-aware zijn? Met `hook_mode=websocket` start de Qwen-server soms terwijl er niets op de ws komt. | F7 — niet blokkerend voor de port |
| **D11** ✅ | **Uitgevoerd in F0:** `backend/vntts/` verwijderd in een eigen commit. Reden: nul functionele impact, 35 bestanden, nul verwijzingen — makkelijk terug te draaien als het toch nodig blijkt. De "eigen commit"-vorm is bovendien waardevoller dan de inhoud: het bevestigt dat er in deze repo een dode 171 KB template lag die drie jaar niemand had opgemerkt. | F9 hoeft dit niet meer te doen. |

### 9.3 Uit F0 voortgekomen besluiten

| # | Besluit | Gevolg |
|---|---|---|
| **D12** ✅ | **De Makefile-gates worden afnemend gemaakt vóór enige productiecode wijzigt.** | F0. `|| true` weg, nieuw `gate`-target. Nu permanente anti-regressieregel §12.8. |
| **D13** ✅ | **Ruff-uitsluitingen worden per-bestand en per-regelcode gegeven, nooit globaal.** | Alleen `convert_vox_to_clone.py` → `["E701", "E702"]`, met comment. De echte fouten in dat bestand (`E722`, `F841`) zijn gerepareerd, niet uitgehaald — als er iets wordt genegeerd, moet de rest van dat bestand wel schoon zijn. |
| **D14** ✅ | **De RenPy-functionele smoke verhuist van F0 naar F8.** | F0 heeft geen game, geen GPU en geen qwentts; een smoke zonder spel zou een no-op zijn die groen lijkt. F8 is waar de ws-route daadwerkelijk naast RenPy komt te staan. |

### 9.4 Uit F4 voortgekomen besluiten

| # | Besluit | Gevolg |
|---|---|---|
| **D15** ✅ | **Trust-gate = "gesteld, niet gegokt".** Registreer een spreker alleen als `Dialogue.speaker_is_guess is False`. De geplande regel (`is_plausible_character_name`) is gemeten een **no-op**: élke naam die de parser als spreker accepteert, slaagt er ook voor. De gate gaat dus over **registerhygiëne**, niet over verkeerd geluid — auto-registratie koppelt sowieso nooit een stem (`voice=""`). | F4. De vlag leeft op `Dialogue`, niet her-afgeleid door de caller, want de multi-spreker-split herschrijft de regel naar colonvorm vóór de per-beurt-parse. Een gok spreekt op de modelstem maar wordt niet bewaard; het `speaker_guessed`-event maakt hem zichtbaar. |
| **D16** ✅ | **`hook_mode` wordt één keer gelezen, bij start.** Later wisselen kost een herstart. | F4, zelfde precedent als `hook_host`. De ws opnieuw binden zou LunaTranslator's verbinding droppen; een herstart die de gebruiker kent is beter dan een stil weggevallen hook midden in een scène. De GUI-hint "herstart vereist" is F6. |
| **D17** ✅ | **`HookTextProcessor` houdt zijn constructor-snapshot** van `hook_dual_hook` / `hook_space_form`. | F4. Maakt `push()` testbaar zonder `settings`; live-herladen is een F7-vraag, geen F4-bug. |
| **D18** ✅ | **`is_blacklisted_name()` wordt niet toegevoegd.** | F4. De poort weigert al zodra de blacklist de regel leegmaakt (`REASON_BLACKLIST`) — dat is de waarneembare faalvorm. Een tweede, naam-gebaseerde blacklist zou een tweede waarheid naast `filter_text` zetten. B's versie is dus expliciet afgevinkt i.p.v. stil vergeten. |

### 9.5 Uit F5 voortgekomen besluiten

| # | Besluit | Gevolg |
|---|---|---|
| **D19** ✅ | **F5 = een dunne file-tailer óver `HookTextProcessor`, geen letterlijke port van B's `file_monitor.py`.** | F5. Er viel geen referentiegedrag te kopiëren (`VN_Suite.py` kent geen file-route), dus "overnemen" zou een tweede, licht afwijkende kopie van de interpretatie van een regel zijn — precies wat F3 met `app.py` afkeerde. De enige nieuwe beslissing is `new_file_text`, en die is pure. |
| **D20** ✅ | **Eén regel per delivery.** | F5, gemeten: de parser plakt regels binnen één aanvoer aan elkaar, dus "de hele wijziging als één regel" laat regel twee de tekst van spreker één worden. Verkeerde stem op verkeerde tekst is erger dan een regel die als vertelstem inleest. Alle regels van een groeiend log komen nu los binnen. |
| **D21** ✅ | **`set_known_speakers()` komt op `InputAdapter`, abstract.** | F5. Het was duck-typing; zodra `_adapters()` de lus typecheckt, wordt de aanname een mypy-fout in plaats van een stille werkende aanname. Een volgende bron kan de priming niet meer overslaan. |

### 9.6 Uit F6 voortgekomen besluiten

| # | Besluit | Gevolg |
|---|---|---|
| **D22** ✅ | **`hook_host` wordt in de GUI read-only getoond, en `/status` spiegelt hem.** | F6. F1 sloot `hook_host` al uit van `SettingsBody` (het is het adres waarop de server bindt). De GUI mag het daarom niet bewerken, maar wél tonen — anders moet de gebruiker in `.env` duiken om te zien waar hij naartoe moet wijzen. Dat het getoonde adres ook echt het gebonde adres is, is nu een assertion in `test_status_contract.py` i.p.v. een aanname. |
| **D23** ✅ | **De GUI exposeert alle 9 hook-instellingen, niet de 2 uit het plan.** | F6. Het plan is geschreven vóór F5 bestond en noemde `hook_mode` + `hook_port`. Met alleen die twee zou de F5-route (`file_watch`, `file_watch_path`) onzichtbaar blijven in de GUI, terwijl de backend hem al volledig ondersteunt. Eén "Text hook"-sectie is bovendien vindbaarder dan losse velden verspreid over twee panelen — dat is het prioriteitscriterium van het hele project. |
| **D24** ✅ | **De nieuwe `ServerStatus`-velden zijn in de GUI optioneel (`?`).** | F6. Het backend stuurt ze altijd, maar `ServerStatus` had al een gemengde stijl (`qwen_mgr?`, `import_status?` — latere toevoegingen als optioneel). De GUI moet ook tegen een oudere backend kunnen draaien: een `gui/dist` uit een vorige build tegen deze backend is een echte situatie bij het installatiewerk in F7. `SettingsData` is wél volledig, want dat is een round-trip: een ontbrekend veld zou stiekem worden weggeschreven bij het opslaan. |
| **D25** ✅ | **De kaart toont drie toestanden, geen verbindingsvlag.** | F6. D9 wilde onderscheiden "er komt niets aan" van "het komt aan en wordt verkeerd gelezen". Eén boolean kan dat niet, want de drie toestanden hebben elk een andere oplossing en geen van drie is zichtbaar in "niet verbonden". Vandaar: `hook_clients` (wie), `hook_last_raw` (komt er iets aan) en `hook_dropped` (houdt de synthese het bij). |

---

## 10. Baseline-logboek

### 10.1 Nulmeting — gemeten op 2026-09-29, commit `38f2a57` (vóór enige codewijziging)

| Gate | Uitkomst | Detail |
|---|---|---|
| `setup.cmd` | ✅ | node 22.23.2 · npm 12.0.2 · Python 3.11.9 · ruff 0.16.9 · mypy 2.3.1 |
| `pytest` (7 suites) | ✅ **105 passed** in 54.8 s | ⚠️ **alleen na handmatig installeren van 2 ontbrekende dev-deps** — zie G5.10 |
| `ruff check backend` | ❌ **27 errors** (4 auto-fixable) | 15 `convert_vox_to_clone.py` · 1 `import_voices.py` · 7 `novatts/` · 4 `tests/test_openai_speech.py`. **Geen enkele is een correctness-bug** — allemaal `SIM105`/`SIM108`/`E701`/`E702`/`F401`/`I001`/`W293` |
| `mypy --strict backend/novatts` | ❌ **2 errors** | 1× ontbrekende `pyperclip`-stubs (`types-pyperclip` niet geïnstalleerd) · 1× `main.py:785` *unused type: ignore* — mypy-2.3.1-artifact, want `os.startfile` is nu bekend |
| `npm run build` (vite) | ✅ | 50 packages, build OK |
| **`make lint`** | ⚠️ **exit 0, altijd** | zie **G5.11** |
| **`make test`** | ⚠️ **exit 0, altijd** | zie **G5.11** |

### 10.2 De headline-vondst van F0: de gates zijn decoratief

```makefile
lint:
	$(PYTHON) -m ruff check backend || true            # ← faalt nooit
	$(PYTHON) -m mypy --strict backend/novatts || true # ← faalt nooit

test:
	$(PYTHON) -m pytest backend/tests/ -v || true      # ← faalt nooit
```

`|| true` schakelt de exitcode uit. `make lint` print "✓ Linting complete" en `make test`
print "✓ Tests complete" **ongeacht de uitkomst**. Daarom konden 27 ruff-errors en 2
mypy-errors blijven staan in een repo waarvan de README zegt dat die gates groen zijn.

**Gevolg voor het hele plan:** de regel *"elke fase is gated op pytest + ruff + mypy + build"*
is waardeloos zolang de gate `|| true` is. **F0 repareert dit vóór er één regel productiecode
verandert.** Anders bouwen we acht fasen op een vangnet van gips.

**Wat wél echt gezond was:** 105 tests groen. De testsuite-inhoud is degelijk — alleen de
verpakking (ontbrekende dev-deps) en de runner (de `|| true`) waren stuk.

### 10.3 Logboek

| Datum | Fase | Commit(s) | `pytest` | `ruff` | `mypy` | `build` | Opmerking |
|---|---|---|---|---|---|---|---|
| 2026-09-28 | inspectie | — | — | — | — | — | Beide repos gelezen, `VN_Suite.py` als referentie geverifieerd. |
| 2026-09-29 | F0 | `38f2a57` | **105 ✅** | **27 ❌** | **2 ❌** | ✅ | **Nulmeting.** Gates niet-afnemend → §10.2. |
| 2026-09-29 | F0 | *"F0: make the gates real…"* | **105 ✅** | **0 ✅** | **0 ✅** | ✅ | **Eindmeting F0.** Gates nu afnemend. `pytest` onveranderd 105 → de 27+2 fixes hebben geen test geraakt, wat bewijst dat het om stijl ging en niet om gedrag. |
| 2026-09-29 | F1 | *"F1: foundation…"* | **153 ✅** | **0 ✅** | **0 ✅** | ✅ | 105 → 153: 48 tests voor de nieuwe logica. **Stijging is gedocumenteerd, per anti-regressieregel §12.9.** |
| 2026-09-29 | F2 | `1e0971b` | **195 ✅** | **0 ✅** | **0 ✅** | ✅ | 153 → 195. Parser 11 → ~800 regels, 5 mutanten gevangen. 3 gaten bewust vastgespeld. **0 runtime-impact** — er is nog niets aangesloten. |
| 2026-09-29 | F3 | `aa67c6e` | **263 ✅** | **0 ✅** | **0 ✅** | ✅ | 195 → 263. Ws-server in drie lagen, 11 mutanten gevangen. **Nog 0 runtime-impact** — de adapter is nog niet aangesloten. |
| 2026-09-29 | F4 | *"F4: gate…"* | **318 ✅** | **0 ✅** | **0 ✅** | ✅ | 263 → 318. **Eerste fase met runtime-impact.** Nieuwe `gate.py` + bedrading; **27/27 mutanten** met caching uit (§12.10). RenPy-route houdt dezelfde adapter, parser en registratie. |
| 2026-09-29 | F5 | *"F5: file tailer…"* | **333 ✅** (+6 ❌ omgevingsafhankelijk) | **0 ✅** | **0 ✅** | ✅ | 318 → 345. Dunne laag over `HookTextProcessor` i.p.v. een port (D19). **33/33 mutanten**, waarvan 6 nieuw. De 6 failures bestonden al op de F4-boom: Open WebUI zit op 8080 waar `NOVATTS_QWEN_URL` wijst — zie de F5-sectie. |
| 2026-09-29 | F6 | *"F6: the GUI…"* | **354 ✅** (0 ❌) | **0 ✅** | **0 ✅** | ✅ | 345 → 354. **Eerste fase zonder nieuwe runtime-impact in de backend** — de GUI hangt aan `/status`, en `status()` kreeg alleen de file-route erbij. 9 nieuwe tests voor een methode die er vóór F6 **nul** had. `svelte-check` van 2 bestaande errors + 1 warning → **0/0**, met de oorzaak in `api.ts` gerepareerd i.p.v. de casts verzwakt. `npm run lint` bleek `&` te gebruiken en maskeerde de eerste opdracht (§12.13) — nu gemeten dat beide talen de gate kunnen laten falen. De 6 omgevingsfailures uit F5 zijn weg: poort 8080 gaf vrij. |

> **Waarom staat hier geen hash?** Dit document zit ín de commit die het beschrijft, en een
> commit kan zijn eigen hash niet bevatten — elke amend zou de verwijzing weer verouderen.
> Zoek de commit op met `git log --oneline --grep="make the gates real"`.
> De hash van het *eerdere* F0-nulmeting-document (`38f2a57`) staat hier wel, want dat
> was al vastgezet vóór deze commit bestond.

> De regel `pytest 105 → 105` over twee metingen is het belangrijkste gegeven in deze tabel.
> Zou het aantal gewijzigd zijn, dan had een van de `contextlib.suppress`-/ternary-hervormingen
> gedrag aangeraakt. Dat is nu meetbaar uitgesloten — **vanaf nu is 105 het getal dat niet mag
> veranderen zonder dat het in de commit-message staat waarom.**

---

## 11. Voortgang per fase

| Fase | Status | Bijzonderheden |
|---|---|---|
| F0 Baseline & veiligheid | ✅ | Gates konden niet falen (`|| true`) → gerepareerd. 27 ruff → 0, 2 mypy → 0, dev-deps compleet, `vntts/` weg, `stop_all.cmd` op poort 8765. Eindstand **105 ✅ / 0 / 0 / ✅**. |
| F1 Foundation | ✅ | 9 hook-velden + `Dialogue.raw` + `_env_bool` (een echte valkuil: `bool("False")` is `True`). 105 → **153 tests**, alle 3 mutanten gevangen. Nog 0 runtime-impact. |
| F2 `parser/luna.py` | ✅ | 11 → ~800 regels, 5 woordensets + 16 UI-regexen, multi-spreker-split. 153 → **195 tests**, 5 mutanten gevangen. Drie gaten bewust vastgespeld i.p.v. "opgelost". 0 runtime-impact. |
| F3 `adapters/luna.py` | ✅ | Drie lagen (pure functies · `HookTextProcessor` · `LunaAdapter`). Eigen event loop + dispatch-thread; synthese blijft van de loop af (G4.1). 195 → **263 tests**, 11 mutanten gevangen. Nog niet aangesloten. |
| F4 `NovaApp`-bedrading | ✅ | Nieuwe `gate.py`: één poort voor alle bronnen. Trust-gate = "gesteld, niet gegokt" (het plan was een gemeten no-op). `hook_mode`-selectie, `status()`-velden, G5.4, stop-volgorde, `_refresh_known_speakers`. 263 → **318 tests**, **27/27 mutanten**. `NovaApp` had hiervoor nul tests. Twee naad-bugs gevangen (`push()` en de handmatige `Dialogue`-rebuilds) → §12.11. |
| F5 `file_monitor.py` | ✅ | D19: dunne laag over `HookTextProcessor`, géén port — B's route heeft geen referentiegedrag. D20: één regel per delivery, **gemeten** (de parser plakt regels aan elkaar). `set_known_speakers` van duck-typing naar `InputAdapter` (D21). `_adapters()` vervangt drie losse adapterslijsten. 318 → **345 tests**, **33/33 mutanten** — waarvan 2 herricht na de refactor (§12.12). Limiet rond `Rick\nTekst` bewust gedocumenteerd én vastgespeld. |
| F6 GUI | ✅ | Nieuwe sectie "Text hook" (9 velden, D23), Hook-kaart met **drie** toestanden i.p.v. één vlag (D25), `brand-sub` om (G6.3). `status()` kreeg de file-route erbij en had **nul** tests → `test_status_contract.py` (9). `svelte-check` als gate erbij, wat 2 bestaande type-errors aan het licht bracht: oorzaak in `api.ts` (responsformaat i.p.v. bestandsformaat), niet verzwakt met `as unknown as`. `npm run lint` maskeerde de eerste opdracht met `&` → §12.13. 345 → **354 tests**, alle gates groen, en de GUI één keer **echt bekeken** tegen een draaiende backend. |
| F7 Lifecycle & docs | ⬜ | |
| F8 Cutover RenPy→LunaHook | ⬜ | Bevat de handmatige RenPy-smoke die uit F0 is gehaald. |
| F9 Opruimen | ⬜ | `vntts/` en G5.8 zijn al afgehandeld in F0. |

---

## 12. Anti-regressie-regels (permanent)

1. **Nooit een Main-module vervangen door de B-variant.** `SpeakerRegistry`, `VoiceManager`, `EmotionSounds`, `Qwen3Backend`, `AudioPlayer`, `Blacklist`, `GameManager`, `parser/renpy`, `TTSBackend`, `text_clean`, `qwen_manager`, `cutter*` — allemaal blijven zoals ze zijn.
2. **Nooit de synthese uit de event loop halen.** Eén regel = één dialoog; de ws-handler geeft `on_dialogue` en *verder niets*. Main's `dialogue-worker` is de enige toegestane synthese-route (G4.1).
3. **Nooit een speaker op GPU binden zonder registry-mutatie.** Onbekende naam → `Narrator` of "wachten op GUI-bevestiging". Faalveilig is niet onderhandelbaar (`ULTIMATE_PROMPT.md` §2).
4. **Nooit `:` splitsen op Luna-tekst.** `RenPyParser` eerst (RenPy levert wél `Name:`), dan pas `LunaParser` space-form. Dat is de volgorde uit `V2_ROADMAP.md` §4.2.
5. **Nooit de clip-`:`-prefix in de TTS laten.** `blacklist.filter_text` spaart hem; daarna moet hij eraf vóór synthese (B doet dit met een regex in `app.py:157`; Main heeft `VoiceManager.clean_dialogue` niet meer — dus expliciet implementeren).
6. **Nooit `itertools`/`asyncio` mixen zonder de shutdown-volgorde te testen.** `NovaApp.stop()` moet altijd: adapters → worker → player → qwen → cache-clear → registry-autosave.
7. **Nooit een `.wav`/`.spk`/`.rvq`/persoonlijke mapping committen.** Zoals `e48c8ef` al besloot voor de emotion-map.
8. **Nooit `|| true` (of een andere exitcode-demping) op een gate zetten.** Dat is de koorts van dit project: `Makefile` deed precies dat, waardoor `make lint`/`make test` 27 ruff-errors en 2 mypy-errors als "✓" afvinkten. **Een gate die niet kan falen is geen gate.** Als een gate hinderlijk is, is de oplossing *repareren wat hij vindt*, niet hem dempen.
9. **Nooit de baseline-testcount als toevalligheid behandelen.** `105` is het getal. Verandert het, dan staat in de commit-message welke test is toegevoegd of weggevallen en waarom.
10. **Nooit een mutant-controle draaien zonder bytecode-caching uit.** Python valideert een `.pyc` op `(mtime in seconden, size)`. Een harness die de bron terugzet met dezelfde lengte binnen dezelfde seconde (`[0]` → `[1]`) laat de **herstelde** bron de **gemuteerde** bytecode laden — en dan toont een volgende testrun een regressie die niet bestaat. Dit is in F4 echt gebeurd en kostte een uur zoeken naar een bug in correcte code. **Draai elke mutant met `python -B` (`PYTHONDONTWRITEBYTECODE=1`) en ruim de project-`__pycache__` op vóór elke meting.** De regel is de algemene vorm van §12.8: een meting die niet kan falen is geen meting — maar een meting die *iets anders* meet dan je denkt is erger, want hij liegt met een getal.
11. **Nooit een `Dialogue` met de hand herbouwen — gebruik `dataclasses.replace(dialogue, ...)`.** `Dialogue` is een frozen dataclass, dus `replace` kopieert elk veld, ook een veld dat pas later wordt toegevoegd. Een handmatige `Dialogue(...)` naast de originele was drie keer exact dezelfde fout: `raw` verdween in de emotie-segmenten, `speaker_is_guess` in `HookTextProcessor.push()`, en beide in `voice_manager.clean_dialogue`. Gevolg: de F4-trust-gate was op het enige pad dat de hook echt gebruikt **inert**, terwijl parser- én gatetests groen waren. De reconstructie-plekken (`push`, `gate.admit`, `_segment_dialogue`, `clean_dialogue`) gebruiken nu alle vier `replace`.
12. **Nooit een mutant als "gevangen" tellen die niet is toegepast.** De harness moet het zoekpatroon in de bron verifiëren vóór hij meet, en anders `MIS … PATROON 0x (verwacht 1)` melden. In F5 gebeurde precies dat: de `_adapters()`-refactor maakte W3 en W10 stuk, hun `old`-strings bestonden niet meer, dus de mutatie werd **niet geschreven** en de test "faalde" omdat de bron onveranderd was. Dat is het gevaarlijkste soort groen: een meting die niet faalt om de verkeerde reden. Het alarm is wat het aan het licht bracht — daarom is het een harde eis in de harness en geen netheidje. Algemene vorm: **elke meting moet kunnen zeggen "ik deed niets"**, anders is haar "ik slaagde" betekenisloos.
13. **Nooit twee checks achter `&` of `;` aan één exitcode hangen.** §12.8 in een andere taal, en F6 vond de bekende ziekte op een plek waar niemand hem zocht: `npm run lint` was `npm run lint --workspaces --if-present & ruff check backend`, en op Windows levert `&` de exitcode van de **laatste** opdracht. Toen F6 daar `svelte-check` bij zette, werd de gate er stilzwijgend *zwakker* door — een type-fout in de GUI werd door een groene ruff weggeschreven. Gemeten: `cmd /c "type C:\nietbestaand.txt & echo ok"` geeft `exitcode = 0`. De regel is dus de ruimere vorm van §12.8: **het gaat niet om `|| true`, het gaat om elke constructie die de exitcode van een check weggooit** — en de Fix is altijd dezelfde: `&&` (of apart draaien), plus één injectietest die bewijst dat de gate wél rood wordt. Overigens ook: als een gate een *bestaande* rode baseline aantreft, is repareren wat hij vindt de taak van de fase die hem introduceeert, want een gate met een rode baseline is geen afnemende gate.

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
| `adapters/legacy_clipboard.py` | 96 | ✅ poll 0.25 s, `last_clipboard` dedup, `set_known_speakers` — **hernoemd in F8**, de klasse heet nog `ClipboardAdapter` (D30) |
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
| G5.4 ✅ | `_synth_emotion_aware` hardcodt `"source": "clipboard"` in de `Event("error", …)`-calls — wordt onjuist zodra de bron `luna`/`file` is. **→ Was al opgelost vóór F9**: alle vier de `Event("error")` in `_synth_emotion_aware` gebruiken `dialogue.source`, en de vijfde (in de API-route) gebruikt `"api"`. Er staat nergens meer een hardcoded `"clipboard"` in een event. | `main.py` |
| G5.5 ✅ | `SpeakerRegistry.update(…, instruct=…)` accepteert `instruct` maar **wijst het nooit toe**. Stille no-op. **→ Opgelost in F9**, in drie lagen: de toewijzing, `SpeakerPatchBody` (had alleen `voice`) en de endpoint (gaf alleen `voice` door). Zie D33. **→ Later in F9 uitgebreid tot VIER lagen**: `_load()` las het veld niet terug, dus de waarde overleefde een herstart niet. Die vierde laag vond alleen een echte herstart-meting, met 370 groene tests erboven (D37). | `registry/speakers.py` |
| G5.6 ✅ | `registry.update()` is keyword-only. **→ Was al waar**: de signature bevat `*`, dus `update(name, "voice")` gaf al `TypeError`. Afgestreept in F9, niet gesloten — er is niets veranderd (D35). | idem |
| G5.7 ✅ | `main.py:451-453` losse regel tussen functie en import (ruff E303). **→ Regel bestaat niet meer**: `ruff check` geeft 0, en `ruff check --select E303` ook (ruff meldt dat de selectie zonder `preview` geen effect heeft). Afgestreept in F9 (D35). | `main.py:451-453` |
| G5.8 ✅ | `.env.example` zegt `NOVATTS_QWEN_TIMEOUT=120.0`; `config.py:79` zegt `300.0`. **→ Opgelost in F0.** | `backend/.env.example:11` |
| G5.9 ✅ | `pyproject.toml` mist `[build-system]` — `pip install -e backend` werkt niet. **→ Opgelost in F0** (setuptools + `packages.find`; `pip install -e .` geverifieerd). | `backend/pyproject.toml` |
| G5.10 | `requirements-dev.txt` is **onvolledig**: `pytest` ontbreekt (terwijl er 7 testsuites zijn), `httpx2` ontbreekt (zonder het faalt `starlette.testclient` → `test_cutter.py` + `test_openai_speech.py` breken tijdens collectie), `types-pyperclip` ontbreekt (de enige `import-untyped`-fout). **Gevolg: de testsuite is vanaf een schone `setup.cmd` nooit draaibaar geweest.** Bevestigd in de nulmeting. **→ Opgelost in F0.** | `backend/requirements-dev.txt` |
| G5.11 ✅ | **De Makefile-gates konden niet falen.** `lint` en `test` eindigden allebei op `|| true`, dus `make lint`/`make test` printten "✓" en exitten 0 bij 27 ruff-errors en 2 mypy-errors. **De ergste vondst van F0** — de hele vangnet-garantie uit het plan steunde op deze targets. **→ Opgelost in F0:** `|| true` verwijderd, nieuw `gate`-target, alle 29 fouten gerepareerd. | `Makefile:126, 128, 133` |

### G6 — Docs/data-drift

| # | Drift | Actie |
|---|---|---|
| G6.1 | `data/emotion_sound_map.json` + `emotion_aliases.json` bestaan **niet** in Main (bewust uitgehaald in `e48c8ef`) | `emotions.py` bouwt ze op uit de schijf. **Geen actie** — moet zo blijven. |
| G6.2 ✅ | `data/speakers.json` bevat game-lokale namen (`where_the_heart_is`, `Anna`, `Brenda`, `D`, `Lilya`) | Persoonlijke data in de repo. **→ Opgelost in F9 (D36):** uit de tracking gehaald en in `.gitignore`. Het is het *globale* register dat geldt als er geen actieve game is (`games.py:speakers_path()`), dus het is werkdata en geen voorbeeld — precies als het al genegeerde `data/games/*/speakers.json`. De geschiedenis is met rust gelaten. |
| G6.3 ✅ | `brand-sub` in de GUI zegt nog `"Qwen3 · RenPy clipboard"` | **→ Was al opgelost in F6**: de regel zegt nu `Qwen3 · LunaHook + clipboard`. Afgestreept in F9, niet gesloten (D35). |
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

**Websockets 17.1** (F1 zette `>=12.0`): de legacy `websockets.serve`-shim bestaat nog maar is deprecated. Hier wordt `websockets.asyncio.server.serve` gebruikt, de nieuwe asyncio-implementatie. **F7 heeft de vloer gemeten en op `>=13.0` gezet, niet op `>=14.0`** — zie D26 en de meting in de F7-sectie. Kort: 12.0 crasht op import, 13.0 werkt, en 14.0 was een comfortgrens die ik eerst had willen nemen zonder te weten waarom.

**Mutatiecheck** (11 mutanten, alle gevangen): synchroon in de loop (= B's ontwerp) → 1 failure · `name`-keys weg → 9 · `data`-key weg → 1 · dual-hook genegeerd → 1 · dual-hook altijd uit → 2 · TTL genegeerd → 1 · queue onbeperkt → 1 · registry-eis 2 woorden weg → 1 · min-length genegeerd → 1 · name-only valt door → 2.

Twee mutanten waren **no-ops en telden niet mee**: een `; _ = 0` die ik als "synchrone callback" introduceerde (niets veranderde) en het verwijderen van een `log.debug` vlak vóór een `return []`. Beide overleefden dus terecht. Een mutatiecheck die stille no-ops telt, is een controlesom die groen kleurt zonder iets te controleren — de eerste helft van elke mutatie moet gecontroleerd worden op of zij het gedrag werkelijk verandert.

**D9 is deels beantwoord.** `adapter.last_raw` bewaart de laatste ruwe regel vóór parsing, omdat "er komt niets aan" en "het komt aan en wordt verkeerd geparseerd" er van buitenaf identiek uitzien. F4 beslist of `/status` dit exposeert.

**Openstaand voor F4:** de trust-gate op auto-registratie. `source == "luna"` moet géén permanent stem koppelen, want de space-vorm is een gok.

---

### ✅ F4 — Bedrading in `NovaApp` *(gereed 2026-09-29)*

Doel bereikt: de hook-pipeline is live naast de RenPy-pipeline, en elke regel die spreekt is door één poort gegaan. **De RenPy-route houdt dezelfde adapter, dezelfde parser en dezelfde registratie** — `hook_mode=clipboard` gedraagt zich als vóór F4, met één bewuste toevoeging: de dedup van 500 ms geldt nu óók voor de clipboard (`A → B → A` binnen een halve seconde sprak vroeger twee keer `A`, want de adapter onderdrukt alleen een onveranderde herhaling).

- [x] `NovaApp._start_adapters()`: adapter-keuze uit `settings.hook_mode` — `clipboard` / `websocket` / `both` (**default `websocket` sinds F8**; in F1–F7 nog `both`). **B's inline `app.py` NIET overgenomen** (G4.1); Main's `dialogue-worker` + `_wake` + `_pending_seq` blijft de enige synthese-route
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

**Openstaand:** niets. D10 (`qwen_autostart` hook-aware) is in F7 beantwoord — **nee**, zie D10 en §9.2; de kosten van die keuze staan nu in de README in plaats van weggenomen.

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

### ✅ F7 — Lifecycle, build & documentatie

Nul regels productie-Python en nul regels GUI (`git diff --stat -- backend/novatts gui/src`
is leeg), dus de testcount moest **exact 354** blijven. Dat is §12.9 in de praktijk: deze fase
mocht niets aan het gedrag raken, en als er wél iets was veranderd had dat in deze sectie
gestaan.

#### F7 — de headline: een poort-check die altijd "ja" zei

Het meldingsblok van `start_all.cmd` (na de wachttijd) moest zeggen of de hook al aan het
binden was. Ik schreef:

```cmd
) else (
  netstat -ano ^| findstr ":%HOOK_PORT%" ^| findstr "LISTENING" >nul 2>&1
  if errorlevel 1 ( echo ... luistert nog niet ... ) else ( echo ... luistert op ws:// ... )
)
```

Binnen een `( … )`-blok heeft cmd **geen escape nodig** voor `|`. Door er toch `^` voor te
zetten wordt de pipe letterlijk: de hele regel draait als **één** commando, de uitkomst wordt
genegeerd, en de exitcode is altijd `0`. Gemeten, met een `netstat`-stub op PATH zodat de
uitkomst reproduceerbaar was en niet van deze machine afhing:

| Variant | poort vrij | poort bezet |
|---|---|---|
| A: `netstat -ano ^| findstr … ^| findstr …` | **"iets gevonden"** ❌ | "iets gevonden" |
| B: `netstat -ano \| findstr … \| findstr …` | **"niets gevonden"** ✅ | "iets gevonden" ✅ |

Variant A is niet "kapot in één richting" — hij is kapot in de richting die het best **lijkt**
te werken. Hij zegt altijd dat er iets luistert. Erger: mijn eerste testrun gaf **groen** voor
het geval "geen busy-poort". Dat geval haalde zijn groenheid uit dezelfde bug (een kapotte
check gaf toevallig het gewenste antwoord). Drie regels code, twee gemeten oorzaken, één
valse groen — dit is de algemene vorm van §12.8/§12.12 in een taal waar de toolchain ons
niets opleverde.

De fix is één teken, maar het verschil zit in de **regel ernaast**: de `for /f … in ('…')`
 elders in hetzelfde bestand heeft de `^|` juist wél nodig, omdat die tekst wél door de
 parser van het `for` gaat. Twee plaatsen in één bestand, tegengestelde regel, en de
 gemeten reden staat als commentaar bij beide — Z §12.14.

> De `for /f`-regel in het *andere* blok (de busy-warning bij start) was correct. Ik had die
> ook verdacht en had het uit de greep gelaten op grond van "het is hetzelfde teken" — gemeten
> blijkt de betekenis plaats-gebonden, niet bestand-gebonden.

#### F7 — `start_all.cmd`: de hook is geen dienst om te doodgaan

Het oorspronkelijke plan was "dood de ws-poort 6677 niet bij start". Dat is uitgebreider dan
één regel weglaten: het *start*-script doodde toen nog elke luisteraar op een poort. Voor 8765
is dat terecht (dat is ons eigen backend-proces, en G5.1/2/3 zijn in F0 al gerepareerd), maar
hetzelfde trucje op **6677** zou ook een *vorig* NovaTTS-instantie kunnen slaan — of iets dat
helemaal geen NovaTTS is. Dus:

| Wat | Waarom |
|---|---|
| Geen blanket-kill op 6677 | 6677 is een gedeelde poort; "dood alles wat erop luistert" is een andere operatie dan "dood ons eigen proces" |
| Wél een waarschuwing vóór start | een bezette bind-poort faalt **stil** — de backend blijft draaien, alleen is er geen hook. Dat is de ergste faalvorm: geen error, geen regel |
| De waarschuwing noemt het pid + `stop_all.cmd` | een melding zonder handeling is een klacht, geen hulp |

Het script leest `NOVATTS_HOOK_PORT` / `NOVATTS_HOOK_MODE` uit `backend\.env` in plaats van
vaste waarden, en meldt ná de wachttijd wat er werkelijk gebeurde: welk adres, welke `.xdll`,
of er al een client aan hing, en `hook_mode=clipboard` zegt hij niets over websockets.

**Over de test:** de blokken zijn uit `start_all.cmd` *gelicht* (op markers) en in echte cmd
uitgevoerd. Lichten i.p.v. kopiëren is hier de hele truc: een gekopieerd blok
veroudert stil, en een stil verouderd testscript is erger dan geen testscript, want het
geeft zekerheid die niet klopt. Twee keer had ik het harness zelf stuk (`GOTO` met een blok;
`Write-Output` in de returnwaarde in plaats van naar de host) — beide gemeld als meetfout, niet
als codefout.

> **Herwaardeerd op 2026-09-29, en dit staat hier omdat de eerdere claim niet reproduceerbaar
> was.** De DoD- en logregels zeiden "13/13 cmd-gevallen". Het harnas dat over is, heeft **8**
> gevallen, en dat was bovendien stuk op drie manieren die geen van all een fout gaven maar een
> schijn van dekking:
>
> | # | wat | gevolg |
> |---|---|---|
> | 1 | de slotmarker was de hele tekst `echo [1/2] Backend ... (AUTOSTART=1) ...`, en commit `2b58a30` herschreef die regel naar `NOVATTS_QWEN_AUTOSTART=1` | de marker matcht nooit meer, de lus tilde de rest van het bestand, en het harnas **hing** in plaats van iets te melden |
> | 2 | de `.env`-inhoud werd als meerregelig argument aan `call :label` meegegeven | `call` met een regeleinde in het argument is een grondige cmd-beperking: alleen de eerste regel komt aan, de rest ontsnapt en wordt als commando uitgevoerd. **Alle meerregelige gevallen schreven dus een `.env` van één regel** en failden daarna op `NOVATTS_HOOK_PORT is not recognized` |
> | 3 | `STUB_PORT` werd pas ná het bouwen van de netstat-stub toegewezen | de stub werd met de waarde van de *vorige* case gebouwd, of helemaal niet; het geval "poort al bezet" testte dus de bezette tak **niet** |
>
> Drie van de acht gevallen waren daarmee nooit echt uitgevoerd. Dat het harnas wél groen
> heette in F7 is dus geen bewijs dat het toen werkte — het is een reden om het getal met
> scepsis te lezen (D35). Gerepareerd: de slotmarker is nu de eerste 18 tekens, zodat de staart
> van de regel mag veranderen; de `.env`-inhoud komt uit bestanden in plaats van uit een
> argument; en `STUB_PORT` wordt vóór het bouwen gezet. Nu **8/8**, met het discriminatiebewijs
> zichtbaar in de logregel hieronder: vóór fix 2 vielen er 7 gevallen, vóór fix 3 één.

#### F7 — `.env` met spaties: de app luisterde naar een ander adres dan het log

Gevonden door het geval `NOVATTS_HOOK_PORT = 7300`. Het script las de sleutel als
`NOVATTS_HOOK_PORT ` (met een spatie), vond geen match, en viel terug op 6677 — terwijl
**pydantic-settings wél trimt** en de backend dus op 7300 draaide. De ergste vorm van de
bevinding is niet "het script las het niet", maar **het log noemde een poort waar niemand
op luisterde**. Een startmelding die liegt is schadelijker dan geen startmelding.

Opgelost met een subroutine (het script draait met `DisableDelayedExpansion`, dus `!x!` kan
niet), spaties uit sleutel én waarde gestript. Opnieuw gemeten: 8/8, inclusief het geval dat
het brak. Tabs worden niet gestript — daar schrijft niemand met de hand mee, en een
onleeselijke `%V:<TAB>=%` in de bron zou de volgende agent meer kosten dan het bugje.

#### F7 — `setup.ps1`: waarschuwen ja, blokkeren nooit, en op loopback zwijgen

De firewallcheck is bewust drie-armig, want loopback en LAN zijn niet hetzelfde probleem:

| `NOVATTS_HOOK_HOST` | Uitkomst | Waarom |
|---|---|---|
| `127.0.0.1` / `localhost` / `::1` | **niets** | loopback-verkeer gaat niet door de Windows Firewall; een waarschuwing zou schreeuwen om een reden die er niet is |
| `0.0.0.0` | waarschuwing + `netsh`-regel | niet alleen bereikbaar, maar er staat ook **ruwe gametekst** mee open |
| iets anders | waarschuwing | bereikbaar, dus mogelijk een firewall-regel nodig |

Twee dingen die ik onderweg heb rechtgezet omdat ze een volgende agent zouden misleiden:

1. De eerste versie had een variabele `$isLoopback` die **niet**-loopback bevatte. De naam zei
   het tegenovergestelde van de waarde. Dat is precies het soort detail dat leesbaar lijkt
   en toch een hele ochtend kost; de variabele heet nu wat hij waarde is.
2. mijn eerste harnesoverride werkte niet, omdat in PowerShell een **functie** een variabele
   met dezelfde naam verslaat (Alias → Functie → Cmdlet → Variabele). De waarschuwingen
   gingen dus gewoon naar het scherm in plaats van in een array terecht te komen. Dat is een
   bug in het meetinstrument; de uitkomsten bleken wel juist, dus ik heb dat niet als
   "gedeeltelijk gelukt" weggeschreven maar als meetfout gemeld.

6/6 gevallen groen, en het script is daarnaast alleen **geparseerd** (niet uitgevoerd — dat zou
de omgeving opnieuw installeren).

#### F7 — de `websockets`-floor stond te laag, en dat is gemeten i.p.v. uit de changelog gelezen

`requirements.txt` vroag `websockets>=12.0`. De code gebruikt echter
`websockets.asyncio.server.serve`, `websockets.asyncio.client.connect` en
`from websockets.asyncio.server import ServerConnection`, en die namespace bestaat pas vanaf
**13.0**. Omdat `uvicorn[standard]` alleen `websockets>=10.4` vraagt, is `>=12.0` op een
machine die al 12.x heeft *"al voldaan"* — en dan crasht de import bij **opstarten** in plaats
van bij installeren. In een schone temp-venv gemeten:

```
websockets 12.0   -> ModuleNotFoundError: No module named 'websockets.asyncio'
websockets 13.0   -> import OK
websockets 14.0   -> import OK
```

Dus de floor is `>=13.0`, niet `>=14.0`. Mijn eigen eerdere notitie had `>=14.0` gezegd omdat
dat de versie is waarin de nieuwe implementatie de standaard werd — maar dat is een *comfort*-reden, en de handler is al de enkelvoudige vorm die sinds 10.1 bestaat. Een ondergrens die niet kan crashen is meer waard dan de nieuwste versie.

#### F7 — de installer hoefde niets, en dat is een controleerbare bewering

Het plan vroeg te verifiëren dat `NovaTTS.iss` de persoonlijke bestanden blijft uitsluiten.
Dat klopt, en de *reden* waarom het correct is, is genuanceerder dan de uitsluitingslijst
doet vermoeden:

| Bestand in `data/` | In de uitsluiting? | In de installer? |
|---|---|---|
| `emotion_sound_map.json.example` | nee | **ja** |
| `emotion_aliases.json.example` | nee | **ja** |
| `emotion_sound_map.json` | ja | nee |
| `emotion_aliases.json` | ja | nee |

De uitsluiting noemt de *persoonlijke* naam; de `.example` gaat gewoon mee. Dat is precies
de vorm die je wilt: een verse installatie heeft de voorbeelden om na te kopiëren, en geen
enkele audio of mapping van de ontwikkelaar. `backend\.env.example` gaat als apart item mee en
bevat al alle 9 hooksleutels mét commentaar (F1), dus de installer levert een werkende hook
config uit.

> Er is hier dus niets aangepast. Een planregel kan "bestaand, behouden" zijn; dan is het
> werk *meten dat het klopt*, niet iets bedenken om te veranderen.

#### F7 — de Makefile-gate miste de GUI

`lint` draaide ruff + mypy. Svelte-check stond sinds F6 in `npm run lint`, maar niet in de
Makefile — dus `make gate` sloeg zeven type-errors in de GUI gewoon over. Toegevoegd, en
`-B` op de testregel gekomen om §12.10 niet per ongeluk te schenden vanuit een gate.

Er is **geen** `type`-target toegevoegd. Het plan noemde `test`/`lint`/`type`; `type` bestaat
niet en een gate die alleen mypy herhaalt is een tweede deur naar dezelfde kamer, met een
tweede plek waar hij stil kan staan. `lint` dekt het nu.

`make` bestaat hier niet, dus ik heb de commando's die de targets draaien **rechtstreeks vanuit
de root** uitgevoerd (354 passed · ruff 0 · mypy 0/33) i.p.v. te beweren dat de targets werken.

#### F7 — documentatie die een claim maakt, moet die claim eerst meten

De `data/README.md`-paragraaf over de hook moest iets zeggen over sprekerregistratie. Ik
schreef eerst "Only `Name: Text` and the JSON form register" en *"you will see the name after a
restart of the dialogue flow"*, en ging dat toen meten:

```
vorm                       spreker    tekst                        is_guess  registreert
colon (RenPy-stijl)        Rick       Hello                        False     True
space-vorm                 Rick       Hello                        True      False
json naam                  Rick       Hello                        False     True
json, andere sleutels      Rick       Hello                        False     True
```

De eerste helft klopte. De tweede helft niet: `/speakers` leest **live** uit het geheugen, dus
er is niets om te herstarten — reloaden van het tabblad volstaat. En het bestand op schijf loopt
tot ~30 s na (`maybe_autosave()` in het dialoogpad), altijd bij een nette shutdown. Nu staat dat
er zo, inclusief de reden waarom een naam na een crash toch in het bestand kan ontbreken.

Mijn eerste twee proefversies waren beide fout, en beide op een manier die de conclusie omkeerde:
de eerste voerde JSON rechtstreeks aan `push()` (dus zonder `decode_wire_message`) en liet zien
dat de hele JSON-string als spraak door zou gaan; de tweede rekende de naam-reconstructie dubbel
om, die al in `decode_wire_message` zit (`return f"{name}: {body_text}", keys`). Pas toen ik
`adapters/luna.py:556-565` had gelezen en de proef exact liet volgen op de adapter, was het een
meting. **Een proef die een andere route volgt dan productie is een aanname met een tabel.**

#### F7 — `docs/COLLEGA_RAPPORT_CRLF.md` §5 wees naar een dood pad

§5 heette *"Wat moet de Luna-edition overnemen"* en zei: kopieer `.gitattributes` naar
`D:\Projects\NovaTTSLun@`. Dat pad **bestaat niet meer**; de donor heet nu `NovaTTSLuna` en is
gearchiveerd onder tag `donor` (D7), en de Luna-edition wordt inmiddels in déze tak gebouwd.
Bijgewerkt naar wat geldt, met bewijs per punt:

| # | Punt | Status | Bewijs |
|---|---|---|---|
| 1 | `.gitattributes` | ✅ | `*.cmd`, `*.bat`, `*.iss`, `*.ps1` op `text eol=crlf` |
| 2 | CRLF-fix | ✅ | 11 bestanden gescand: overal `CRLF=n, kale-LF=0` — ook de drie die F7 bewerkte |
| 3 | `.gitignore` `backend/.env` | ✅ | regel 13 |
| 4 | functioneel testen | ⚠️ **deels** | zie hieronder |

Punt 2 is geen cosmetiek: `cmd.exe` voert een `.cmd` met kale-LF uit in een gebroken modus met
fouten die naar de *volgende* regel wijzen. Punt 2 is hier bovendien blijven liggen omdat de
`.gitattributes`-regel de duurzame vorm is — die hoeft niet opnieuw gedraaid te worden na elke
`git clone`, in tegenstelling tot het losse commando dat §5 opleverde.

**Punt 4 staat bewust op deels.** Er is nog één koude `start_all.cmd --visible` nodig, plus een
klik op *Save to .env*, om de keten af te vinken. F7 heeft de achterliggende keten gedraaid
(backend op `:8765`, de gebouwde GUI erop, `/health` + `/status`, Hook-kaart en
Text-hook-sectie nagekeken) en juist **niet** op Save geklikt, omdat dat de echte `.env` van de
gebruiker herschrijft. Die klik hoort bij een release-test met een `.env` die men mag wijzigen;
hem nu doen zou de groene vinkje op een toekomstige test zetten.

#### F7 — wat er níét in deze fase zat

- **Geen productiecode.** Zowel Python als GUI onaangeroerd, dus geen enkel gedrag veranderd.
- **Geen `NovaTTSLuna` aangeraakt.** Bestaat nog, maar buiten deze opdracht en niet gevraagd;
  §5 sprak er alleen *over*.
- **Geen hook-end-to-end draaien.** Er is hier geen spel en geen LunaTranslator. De
  functionele smoke staat nog in F8 (D14), waar de ws-route daadwerkelijk naast RenPy komt.
- **Niets gepusht.** Zoals bij elke eerdere fase.

---

### ✅ F8 — Cutover: RenPy → LunaHook

Doel: de *replace* uit de opdracht, expliciet en omkeerbaar. **Vorm vastgelegd in D1:**
de primaire route wisselen, de RenPy-code behouden als fallback. Geen verwijdering van
`ClipboardAdapter` / `parser/renpy` — die blijven als expliciete keuze bestaan totdat de
ws-route bewezen stabiel is.

De vijf stappen zijn alle vijf gedaan, in deze volgorde, en elke stap had een gate:

| Stap | Wat | Gate |
|---|---|---|
| 1 | nulmeting: de nulmeting-voor-de-cutover | functionele E2E op beide routes |
| 2 | default om naar `websocket` | pytest, plus een proef die bewijst dat de knop om is |
| 3 | `clipboard.py` → `legacy_clipboard.py` | pytest, ruff, mypy + de valback opnieuw functioneel |
| 4 | GUI: legacy-badge en uitleg | svelte-check, build |
| 5 | README "Migratie vanaf RenPy" | elke claim uit die sectie gemeten |

**Gate per stap:** `pytest` groen (354 → **355**, de +1 is de nieuwe D29-test).
Stap 5 vereist een handmatige `start_all.cmd --min` + echte LunaHook-sessie — die
staat hieronder als overgedragen checklist, want een spel draai ik hier niet.

#### F8 stap 1 — de nulmeting, en waarom die vóór stap 2 moest

Het hele idee van een nulmeting is dat hij de cutover draagt. Draai je hem erna, dan meet
je de nieuwe situatie en noem je het een bewijs. Gemeten is daarom eerst, met de default
nog op `both`:

| route | wat er gebeurde | bewijs |
|---|---|---|
| hook · `Rick It's 2 parts.` | 2 beurten, naam als gok → niet geregistreerd (D15) | `hook_last_raw` klopte, 0 gedropt |
| hook · `{"name":"Anne","text":"Good night babe!"}` | **geregistreerd** — de JSON-herstap werkt (G3.1) | `Anne` verscheen in `/speakers` |
| hook · `Anne Hallo! Rick Mooi.` | **2 beurten, 2 stems** (G3.2) | `Anne: Hallo!` + `Rick: Mooi.` |
| hook · `Marty: I'll be back.` | colon-vorm, `Marty` geregistreerd | `/speakers` |
| hook · lege regel | genegeerd | `hook_last_raw` bleef op de vorige staan |
| hook · `Rick` (kale naam) | genegeerd — de hook praat de naam niet uit | geen dialoog |
| clipboard · 3 RenPy-regels | 3 WAV's, 1.4–2.4 s | bestanden in `data/cache/` |
| clipboard · onbekende naam | `NovaRookie` geregistreerd | `/speakers` |

**De kernclaim van de DoD is "NovaTTS speelt Ricks gekloonde stem", en die bleek op één
manier meetbaar zonder te luisteren.** Het cachepad is
`_cache_path(text, voice, instruct, emotion)`: de stem zit ín de hash. Dus dezelfde tekst
met en zonder toegewezen stem moet twee verschillende bestanden geven.

```
ongestemd   'NovaVoiceProof1790678460 zeven woorden in totaal.' -> adfad972…wav  345644 bytes
gestemd     idem, met Samantha: (M-All_Peter_Griffin)          -> b5ed358…wav  299564 bytes
```

Gelijke hashes zouden hebben betekend dat de stem nergens aankomt. Ze verschillen, dus
de stemparameter bereikt het model. Wat dit **niet** bewijst is dat die stem subjectief
de goede is — dat kan alleen een mens beoordelen, en dat hoort dus in de game-sessie.
Ik noem dit een *indirecte* meting omdat het zo is.

#### F8 — twee meetinstrumenten lagen tegen de code, en een derde was een echte

Dit is het belangrijkste deel van de fase, en het gaat niet over de cutover. Drie
harnassen gaven een **zeker, verkeerd** antwoord:

**1. De applicatielog staat in `.err`, niet in het logbestand.** Mijn eerste geïsoleerde
harnas las `f8_backend.log` en meldde "niets gesproken" voor regels die wél gesproken
werden. Het bestand bevat alleen de uvicorn-accesslog; de applicatielog gaat naar stderr.
Een `grep` op het verkeerde stream is een haarnet dat niets vangt.

**2. De audiocache maakt synthese stil.** Tweede run, dezelfde regels: alles binnen
(`hook_last_raw` klopte), en wéér geen logregel. Oorzaak: de cache sleutelt op tekst-hash,
dus de tweede keer is het een hit — en `Cache hit` wordt op **debug** gelogd, dus op
INFO-niveau is een cache-hit volledig stil. **"Geen regel in de log" betekent niet "niets
gebeurd".** Het echte bewijs is het bestand in `data/cache/`, en elke proef gebruikt
daarom een unieke tekst.

**3. Twee routes in één proces is vervuild.** Ik wilde weten of de hook meer
crashdump-achtige rommel doorlaat dan het klembord. Gemeten met `hook_mode=both`, en de
tabel die eruit kwam kon niet kloppen: `ClipboardAdapter._is_garbage` vangt
`'  File "game/script.rpy", line 3'` (in-proces bewezen), dus het klembord had die regel
nóóit mogen spreken. Opnieuw gemeten met **één route per proces**:

```
'  File "game/script.rpy", line 3'   klembord: niet gesproken   hook: niet gesproken
'RuntimeError: boom'                 klembord: niet gesproken   hook: niet gesproken
'traceback follows'                  klembord: niet gesproken   hook: niet gesproken
'some exception happened'            klembord: niet gesproken   hook: niet gesproken
```

Allebei stil. En dat is een *ander* antwoord dan ik voorspelde: ik had verwacht dat de
hook hier de zwakkere route zou zijn, omdat hij alleen `is_renpy_exception` aanroept terwijl
het klembord daarnaast `_is_garbage` heeft. Dat gat blijkt niet te bestaan, maar om een
andere reden: de hook blokkeert deze regels via de **plausibiliteitsregel**
(`RuntimeError` is geen sprekersnaam), niet via crashdumperkenning. Gemeten, niet
geredeneerd — zie D31.

Alle drie de fouten hebben dezelfde vorm: een harnas dat een antwoord gaf zonder de
benodigde route te volgen. Dat is precies §12.14, nu drie keer bevestigd in één sessie.

#### F8 stap 2 — de default om, en de ene plaats waar hij níét mee omging

`hook_mode: "both"` → `"websocket"` in `config.py`, `.env.example` en de GUI-select.
Maar de **validator** valt nog steeds terug op `both` bij een onleesbare waarde. Dat is
niet vergeten, dat is D29.

De proef die bewijst dat de knop echt om staat, moet kunnen slagen én falen. Daarom twee
bevingen in één draai, waarvan de tweede een "niets gebeurt" is en dus een zwakkere vorm:

| bewering | gemeten |
|---|---|
| de hook doet het nog | unieke regel over de ws → **nieuw** wav-bestand (295724 bytes) |
| het klembord doet het niet meer | unieke RenPy-regel op het klembord, 6 s gewacht → **geen** nieuw bestand |

Een "geen bewijs"-meting is zwakker dan een "wel bewijs"-meting, dus de reden staat erbij:
een nog lopende synthese uit de vorige stap zou in dit meetvenster kunnen vallen. Daarom
is de hook eerst bewezen (wél audio, dus de server is warm en de keten staat), en pas dan
de afwezigheid gecontroleerd.

#### F8 stap 3 — de rename, en wat er níét is hernoemd

`git mv` zodat de geschiedenis bewaard blijft. De **klassenaam is bewust hetzelfd
gebleven**: `ClipboardAdapter`. Hernoemen zou `main.py`, de hele testsuite en elke import
raken zonder winst, en een klassenaam die niet meer bij zijn bestand past is erger dan een
module die "legacy" heet en een klasse die zegt wat hij is. Het *bestand* draagt de status;
de docstring draagt de reden.

Wat wél meebeweegt: het comment in `requirements-dev.txt` noemde het oude pad. Dat is
geen ruff-exemptie maar de `types-pyerclip`-stub, dus het zou stil vervallen zijn — een
verwijzing naar een pad dat niet meer bestaat, in een bestand dat een volgende agent leest
als hij een typefout van `pyperclip` zoekt.

**Het waarschuwen uit het plan bleek niet van toepassing.** De stapnotitie zei dat
`source="renpy"` expliciet geschreven moet worden *"anders breekt mypy op de Literal"*.
Maar `Dialogue.source` is een kale `str`, geen `Literal` — dus er viel niets te typen.
Mypy zegt het zelf: 33 bestanden, 0 fouten.

#### F8 stap 4 — de GUI, en waarom de valback zichtbaar blijft

Opties hernoemd en herordend zodat de geadvanceerde keuze op het default staat, en de
legacy-optie blijft **zichtbaar met uitleg** in plaats van in `.env` te begraven:

> Legacy route: NovaTTS reads the RenPy `copy_voice_to_clipboard` output. It still works
> and is still tested. Choose this only if your game has no hook.

Een terugvalweg die een gebruiker niet kan vinden is geen terugvalweg. Iemand op RenPy zou
anders concluderen dat zijn spel stuk is, terwijl er een regel `.env` voor nodig is die
hij niet kent.

#### F8 stap 5 — een docsectie die zelf een claim maakt

De README-sectie "Migrating from RenPy" moest zeggen wat een RenPy-gebruiker ziet na
de upgrade. Vier claims, alle vier eerst gemeten:

| claim | gemeten |
|---|---|
| `clipboard` start nog steeds de legacy adapter | `hook_mode=clipboard` → poort 6677 **vrij**, log zegt `Clipboard adapter started (poll 0.25s) -- legacy RenPy route` |
| de hook luistert niet als `clipboard` aanstaat | zelfde meting: `LunaHook websocket adapter not started` |
| de stem wordt echt gebruikt | zie stap 1, twee verschillende hashes |
| `versions: 1` is geen teller die ik hoef te herstellen | het is een vaste literal in `registry.to_dict()` |

#### F8 — de meting waarvan ik wou dat ik hem niet nodig had

Ik wilde weten of de hook-route meer rommel doorlaat dan het klembord, want dat zou een
reden zijn om aarzelen over de cutover. Gemeten, en het antwoord is: **nee**.

| regel | hook | klembord |
|---|---|---|
| `%^&*(){}[]<>\|#~` | **gesproken** (215084 bytes) | **gesproken** |
| `!!!???` | **gesproken** (69164 bytes, D10/D11-meting) | **gesproken** |
| `Traceback (most recent call last):` | geblokkeerd | geblokkeerd |
| `RuntimeError: boom` | geblokkeerd (plausibiliteit) | geblokkeerd (`_is_garbage`) |
| `ab` (korter dan `min_text_length`) | genegeerd | genegeerd |

Er is dus **geen inhoudsguard voor interpunctie**, in geen van beide routes: alleen
`min_text_length=3` en crashdumperkenning. Dat is **bestaand Main-gedrag**, geen
regressie van de hook, en het is daarom ook géén F8-probleem om op te lossen — een
inhoudsguard toevoegen zou het gedrag van de RenPy-route veranderen, en dat is een
ander werk. Wel staat het nu in de README, want het is een eigenschap die een gebruiker
verwacht als hij een game-UI ziet.

> Het opvallende is dat de hook op één ding wél beter is dan de RenPy-route: een kale
> naam valt weg in plaats van als vertelstem uitgesproken te worden, en de
> multi-spreker-split bestaat alleen op de hook.

#### F8 — de overgedragen checklist: wat een echte sessie nog moet leveren

Alles hierboven draaide zonder spel en zonder LunaTranslator. Wat een client die ik zelf
schrijf **niet** kan bewijzen, is dat Textractor deze frames daadwerkelijk produceert —
mijn eigen protocolaanname is geen bewijs voor andermans gedrag. Dus dit blijft over, in
volgorde, en elke stap is zo geschreven dat hij een waarheid-van-het-bare-feit oplevert:

| # | stap | waar te kijken |
|---|---|---|
| 1 | start NovaTTS (`start_all.cmd --min`), Hook-kaart op `waiting` | dashboard |
| 2 | start LunaTranslator, `Extensions → Add → textractor_websocket_x64.xdll`, op `ws://127.0.0.1:6677` | — |
| 3 | 3. Hook-kaart moet `1 client` tonen | dashboard |
| 4 | open het spel, één regel dialoog | kaart moet naar *connected, no line yet* → dan een regel |
| 5 | hoor je Rick's **gekloone** stem? | gehoor — het enige wat geen automatisering kan |
| 6 | Characters-tab: is de naam er? | GUI, alleen een tabreload nodig |
| 7 | Settings → *Save to .env* | **alleen** met een `.env` die je mag wijzigen |
| 8 | `stop_all.cmd`, en is poort 6677 weer vrij? | `netstat -ano \| findstr 6677` |

Stap 5 is het enige dat een mens moet doen, en het is tegelijk het belangrijkste: al het
andere is bewezen dat het *pad* klopt, niet dat het resultaat goed is.

#### F8 — wat er níét in deze fase zat

- **Geen inhoudsguard toegevoegd.** Zie hierboven: bestaand gedrag, beide routes gelijk,
  en een gedragswijziging op de RenPy-route hoort niet bij een cutover.
- **Geen `Dialogue.source` aangeraakt.** De planwaarschuwing bleek overbodig.
- **`data/` niet opgeruimd buiten het register terug.** De drie namen die de metingen
  registreerden (`Anne`, `Marty`, `NovaRookie`) zijn verwijderd en het bestand is
  terug op de originele vier. Eerste terugzetpoging faalde omdat mijn eigen back-up al
  besmet was toen ik hem maakte — zie D32.
- **Geen `start_all.cmd --min` koud gedraaid**, en niet op *Save to .env* geklikt. Punt 4
  van het CRLF-rapport blijft daarom op *deels*, precies zoals F7 het heeft neergezet.
- **Niets gepusht.** Zoals bij elke eerdere fase.

---

### ✅ F9 — Opruimen

Zeven openstaande regels, en de eerste bevinding was dat er minder openstond dan
de lijst suggereerde — of juist meer. Van de zes die de F9-checklist noemde waren
**vier** al afgehandeld zonder dat iemand dat had bijgehouden, en de twee die echt
openstonden bleken samen vier lagen diep. Geen van beide bevindingen was te zien
uit de checklist alleen; ze kwamen pas uit meten.

> Herwaardeerd zijn de rijen die de F9-checklist zelf noemde (G5.4–G5.7, G6.2,
> G6.3). De overige openstaande rijen in §4 zijn **niet** opnieuw beoordeeld, dus
> "vier regels lagen" betekent niet "de rest klopt". De G3.x/G4.x-rijen zijn trouwens
> geen takenlijst maar een gap-inventaris ("ontbreekt in B"), en horen dus niet op ✅.

| item | wat het was | uitkomst |
|---|---|---|
| G5.5 `update(instruct=)` no-op | echte bug, **in vier lagen** | gefixt, 15 nieuwe tests |
| G5.6 kw-only | **al waar** — de signature bevat `*` sinds vóór deze editie | checklist afgestreept |
| G5.7 ruff E303 | **al weg** — `ruff check` geeft 0, ook expliciet op `--select E303` | checklist afgestreept |
| G5.8 `.env.example` timeout | al afgehandeld in F0 | — |
| G6.2 / D5 persoonlijke speakers | `data/speakers.json` met 7 namen zat in de tracking | uit de tracking + `.gitignore`, geschiedenis met rust gelaten |
| `description` in `pyproject.toml` | zei `(RenPy/Qwen3)` | `(LunaHook/RenPy/Qwen3)` |
| ruff-uitsluitingen herevalueren | nog niets opgeschoond | blijft staan — er valt niets te herwaarderen zolang de bestanden bestaan |

Daar staat nog een regel bij die de F9-checklist niet noemde en die wél openstond:

| G5.4 fout-events hardcoded `"source": "clipboard"` | zou fout labelen zodra de bron `luna`/`file` is | **al waar** — alle vijf `Event("error")` gebruiken `dialogue.source` of `"api"` |

#### G5.5 was één regel, en bleek vier lagen

De audit noteerde `SpeakerRegistry.update()` nam `instruct` en wees het nooit toe.
Dat klopte. Maar ik had ook al geconcludeerd dat `main.py` het doorgeeft, en die
conclusie was **fout**. Mijn `grep` vond `instruct=body.instruct` en ik las die
regel als de spreker-PATCH, terwijl het `/speak` was. De waarheid, gemeten door de
regel te lezen in plaats van de zoekhit te interpretieren:

```python
# vóór
class SpeakerPatchBody(BaseModel):
    voice: str | None = None

async def update_speaker(name: str, body: SpeakerPatchBody) -> dict[str, Any]:
    updated = rt.registry.update(name, voice=body.voice)   # alleen voice
```

Dus `instruct` en `emotion` waren vanuit het proces **onbereikbaar**: niet
ontvangen, niet doorgestuurd, en in het register niet toegewezen. Dat zijn drie
lagen, waar de audit er één noemde — en het bleken er vier.

Dat maakt de volgorde van het fixen niet neutraal. Alleen laag 1 repareren is
**erger dan niets doen**: `update()` gaat dan `instruct` wél honorseren, de
signature nodigt uit om het te gebruiken, en de endpoint slurpt het alsnog. De
bug verhuist van duidelijk naar onzichtbaar. Daarom is er een apart endpoint-
testbestand bijgekomen, en niet alleen tests in de registrytests.

De GUI is bewust **niet** uitgebreid: `updateSpeaker` in `api.ts` is getypt als
`Partial<Pick<Speaker, "voice">>` en stuurt alleen `voice`. De GUI heeft dus geen
knop om een instructie te zetten, en dat ook niet gekregen — dat zou een feature
zijn, geen fix. `instruct` en `emotion` zijn nu bruikbaar vanuit scripts en
importers, en de docstring bij het veld zegt dat met zoveel woorden.

#### Laag 4: de waarde bereikte het bestand en kwam toch niet terug

Na drie lagen gevonden te hebben, was ik klaar. Toen startte ik NovaTTS echt,
`PATCH`te een instructie, en zag dit:

```
na herstart : instruct='' voice='F9Voice' emotion='neutral'
```

`voice` overleefde de herstart. `instruct` en `emotion` niet — terwijl ze wél in het
bestand stonden, wat meting 2 van dezelfde run had bewezen. Dus in `_load()`:

```python
speakers[name] = Speaker(name=name, voice=raw_voice)   # instruct en emotion weggegooid
```

Dat is een *vierde* laag, van dezelfde soort als laag 1: een veld dat de code
schrijft en niet terugleest. Het gevolg is erger dan een no-op, want het is een
leugen in plaats van een gat: `GET /speakers` rapporteerde `""` voor een bestand
dat duidelijk iets anders zei. Een gebruiker die na een herstart naar de GUI gaat
ziet zijn instructie weg, en de API bevestigt dat kloppend.

**370 tests waren groen toen dit gevonden was.** Niet één keek in de laadrichting:
de bewering "instruct overleeft een herstart" was simpelweg nooit als test
geschreven. Dat is het sterkste argument van deze hele fase, en het staat hier
omdat het gemakkelijk is om weg te rationaliseren — zie D37.

#### Laag 5: een featuregat, en daarom géén bug

Het register wordt bij synthesize op **één** veld geraadpleegd. Gemeten, niet
afgeleid:

```python
# tts/voice_manager.py, synthesize()
instruct = getattr(dialogue, "instruct", "") or ""   # uit de Dialogue, niet uit het register
emotion = getattr(dialogue, "emotion", "") or ""
voice   = self.resolve_voice(speaker, voice_override)   # dit is de enige register-look-up
```

En `Dialogue` heeft geen `emotion`-veld, en de hook- en RenPy-parsers krijgen hun
`instruct` uit de wire respectively de aanroep. Kortom: `Speaker.instruct` en
`Speaker.emotion` worden nu opgeslagen, teruggelezen en in `/speakers` getoond — en
gebruikt voor niets.

Dat is een **gat in het product**, geen defect: er is geen code die verkeerd doet,
er ontbreekt code. `instruct` per spreker laten meewegen in de synthese is een
feature met een ontwerpbeslissing erin (laat de spreker-winst de per-regel-instructie
winnen, of maak het een template dat de regel kan overschrijven?). Die beslissing is
niet in F9 genomen en hoort niet in een opruimfase die draait om "G5.5 fixen".

Wat er wél staat is een eerlijke alinea in de docstring van `update()`, plus deze
paragraaf, zodat de volgende agent die het gat wil sluiten het als een keuze ziet
en niet als een vergeetigheid.

#### G5.6 en G5.7: afgestreept, en waarom dat een resultaat is

G5.6 vroeg om `update()` keyword-only te maken. Het is het al:

```
self, name: str, *, voice: str | None = None, instruct: str | None = None, emotion: str | None = None,
```

G5.7 vroeg om een `E303` in `main.py:451-453` te repareren. `ruff check` geeft 0
fouten, en ook `ruff check --select E303` geeft 0 (met de waarschuwing dat E303
zonder `preview` geen effect heeft — de regel bestaat in de huidige ruff niet meer
als actieve controle).

Beide afgestreept, niet "gesloten". Er is hier niets veranderd.

#### G6.2 / D5 — de persoonlijke namen eruit, zonder de geschiedenis te slopen

`data/speakers.json` zat in de tracking met zeven namen: `Anna`, `Brenda`, `D`,
`Lilya`, `Narrator`, `Rick`, `Woman`. Wat het bestand **is**, bepaalt of het weg
mag:

```
games.py, speakers_path():
    if not g:
        return Path(settings.speakers_file)     # data/speakers.json
    return self.games_dir / g / "speakers.json"
```

Het is dus het **globale** register dat geldt wanneer er geen actieve game is —
geen voorbeeldbestand, maar het echte werkbestand van de gebruiker. Precies
dezelfde reden als `data/games/*/speakers.json`, dat al genegeerd was.

De beslissing die de gebruiker nam: eruit de tracking en in `.gitignore`, en de
geschiedenis met rust. Gemeten of dat gedaan is zonder gegevens kwijt te raken:

| | |
|---|---|
| bestand na `git rm --cached` | staat nog op schijf, 7 sprekers |
| `git check-ignore` | `data/speakers.json` wordt nu genegeerd |
| overige `data/`-bestanden | blijven tracked (`active_game.json`, `blacklist.json`, de `*.example`-mappen) |
| geschiedenis | ongemoeid; de namen blijven in oude commits vindbaar |

Het laatste is een bewuste keuze en geen vergetelheid. De repo is nog nooit
gepusht, dus een rewrite zou nu goedkoop zijn — maar het zou 30 commits herschrijven
en alle hashes veranderen, waardoor de `pre-luna`-tag wijkt. Dat is een grotere
ingreep dan het probleem waard is, en het is niet om te draaien.

> Wel meegenomen en **niet** gedaan: `data/active_game.json` bevat
> `{"active": "where_the_heart_is"}` en `data/blacklist.json` bevat
> `{"custom_words": ["save", "*"], ...}`. Geen van beide is persoonlijke data in
> de zin van D5 — een gamenaam en twee stopwoorden — dus ik heb ze laten staan
> in plaats van de opdracht stilzwijgend te verbreden.

#### F9 — wat hier níét in zat

- **Geen GUI-veld voor `instruct`/`emotion`.** Uitbreiding van het product, geen
  bugfix. Wel doorgegeven aan de API, zodat de drie velden die het register al
  ondersteunt ook echt bereikbaar zijn.
- **Geen geschiedenis herschreven.** Zie hierboven.
- **Geen ruff-uitsluitingen geherevalueerd.** De persoonlijke hulpscripts staan
  nog in de repo, dus de enige uitsluiting (`convert_vox_to_clone.py`, E701/E702)
  is nog steeds nodig. Niets te doen.
- **Niets gepusht.** Zoals bij elke fase.

---

## 8. Definition of Done

Overgenomen uit `V2_ROADMAP.md` §14, aangescherpt op Main. **Dit is de acceptatietest — geen checkbox is een vinkje waard.**

**Bijgewerkt in F9**, na afronding van alle fasen. Drie statussen, want “áfgestreept” en “opgelost” zien er in een lijst identiek uit en betekenen het verschil:

| teken | betekenis |
|---|---|
| ✅ | **gemeten**, met de meting erbij |
| ⚠️ | **deels** — wat wél bewezen is en wat niet, uitdrukkelijk |
| ⬜ | **niet gedaan**, met de reden |

> Drie regels hieronder staan bewust **niet** op ✅. Ze staan open omdat ze waar zijn, en een DoD die groen gemaakt is door de regel te verzachten is geen DoD. Welke het zijn en waarom staat er: de module-limiet van 500 regels, de duurtest van een uur, en het punt dat een mens moet beoordelen of een stem goed klinkt.

### Functioneel
- ⚠️ LunaTranslator + `textractor_websocket_x64.xdll` → `ws://127.0.0.1:6677` levert `Rick It's 2 parts.` → NovaTTS speelt **Ricks** gekloonde stem, geen leak naar andere speakers — **bewesen:** het ws-pad end-to-end (F8, echte `websockets`-client, unieke tekst → nieuw aud-bestand), de stemparameter bereikt het model (dezelfde tekst gaf twee verschillende cache-hashes), en *geen* leak want `Rick` wordt bij een gokte naam níet geregistreerd (D15). **Niet bewezen:** (a) dat Textractor deze frames écht produceert — geen spel en geen LunaTranslator in deze omgeving; (b) of de stem subjectief *goed* klinkt. (a) staat als stap 1–4 en (b) als stap 5 in de F8-checklist
- ✅ Zelfde regel als JSON `{"name": "Rick", "text": "..."}` → speaker **Rick** (G3.1) — F8 stuurde `{"name":"Anne","text":"Good night babe!"}` over de ws en `Anne` verscheen in `/speakers`. De naamwaarde maakt niet uit, dus dit is dezelfde regel. De wire-shapes zitten ook in F2's unittests
- ⚠️ Multi-spreker `"Anne Hallo! Rick Mooi."` → 2 aparte turns met 2 stems, in volgorde (G3.2) — **de 2 turns in volgorde zijn bewezen** (F8: `Anne: 'Hallo!'` en `Rick: 'Mooi.'`, in die volgorde). **“2 stems” is niet bewezen**, want op dat moment had geen van de sprekers een stem toegewezen, dus beide vielen terug op dezelfde. Wat wél bewezen is dat elke beurt een eigen speaker-veld heeft; de 2-stems-stap vraagt dezelfde `PATCH /speakers` als de stembewijs-meting uit F8
- ✅ Narratie (`You have your shower.`, `Good night babe!`, `Meanwhile, back at…`) wordt **nooit** een speaker — `test_narration_registers_nothing` (gate) plus vier parserpinnen. Let op: dit gaat over *narratie wordt geen spreker*. Een ander, zwakker punt is wél waar en staat elders: interpunctie-afval wordt wél gesproken (F8)
- ✅ RenPy-clipboard op `hook_mode=both` blijft 100% werken (geen regressie op Main) — F8, vóór de default-omzetting: 3 unieke RenPy-regels op het klembord → 3 WAV's van 1.4–2.4 s. En ná de omzetting nog eens, in `hook_mode=clipboard`: legacy-adapter start, poort 6677 blijft vrij, de log noemt `legacy_clipboard`
- ✅ `NOVATTS_FILE_WATCH=1` levert tekst als de ws en clipboard stil zijn — F5: een dunne staart over dezelfde `HookTextProcessor`, 33/33 mutanten
- ✅ `GET /status` toont `hook_mode` + een correcte `hook_clients` — F6 (9 tests, 3/3 mutanten) en F8 live: `hook_clients` 0 → 1 → 0 na het weghalen van de client, en de route zonder adapter geeft de getallen van de adapter die níet draait
- ✅ Per-game switch behoudt Luna-geschiedenis per game — `test_main_wiring.py`, per-game registry swap
- ✅ `stop_all.cmd` doodt backend + GUI + tts-server, op **8765** — F0 herstelde G5.1/G5.2/G5.3; F7 meet de cmd-gevallen, maar de "13/13" is teruggezet naar **8/8** na herwaardering: het harnas dat over is telt acht gevallen en was stuk op drie manieren die een schijn van dekking gaven in plaats van een fout. Zie de F7-testsectie hierboven

### Kwaliteit
- ✅ `pytest` groen — **7 bestaande suites + nieuwe Luna-suites**, 0 regressies — **370 passed** (F0: 105 → F8: 355 → F9: 370)
- ✅ `ruff check` + `mypy --strict` + `npm run build` + `npm run check` groen — 0 / 0 in 33 bestanden / build ok / svelte-check 0 en 0
- [⚠️] `main.py` blijft < 1100 regels; elk nieuw module < 500 regels (`ULTIMATE_PROMPT.md` §2) — **de eerste helft klopt, de tweede niet.** `novatts/main.py` 1041 (limiet 1100, ✅); `novatts/parser/luna.py` **774** (❌); `novatts/adapters/luna.py` **516** (❌); `gate.py` 174 en `registry/speakers.py` 191 (✅). De limiet is niet gehaald en ga ik niet stilletjes aanpassen: eronder zit waarschijnlijk dat `parser/luna.py` in F2 van 11 naar 774 groeide omdat de multi-sprekersplit daar hoort, en `luna.py` in F3 en F5. De limiet is een maatstaf voor vindbaarheid en die is per bestand niet gehaald. **Beslissing voor de gebruiker, geen opruimwerk:** opsplitsen is omkeerbaar maar kost tijd, en beide bestanden zijn nu elk goed te lezen — laag-indeling en een docstring die de lagen benoemt
- ✅ `adapters/luna.py` **dood de event loop niet** tijdens synthese (G4.1) — aantoonbaar: 2 gelijktijdig verzonden regels komen allebei door — `test_luna_adapter.py:536` stuurt twee frames en het tweede wordt verwerkt terwijl het eerste nog synthetiseert
- [⬜] 1 uur ws-verbinding zonder crash, zonder thread-leak, zonder onbeperkte queue — **niet gedaan.** Geen enkele fase heeft dit gedraaid; het is een duurtest en die is nooit gestart. Bewust geen vinkje: er is geen meting, dus er valt niets te citeren

### Documentatie
- ✅ README: pipeline, hook-config, LunaTranslator-setup, `hook_mode`, migratiepad — F6 (pipeline, drie-statenkaart), F7 (vijf build-commando's, Qwen-sectie), F8 (nieuwe “Migrating from RenPy”-sectie, met elke claim ervan eerst gemeten)
- ✅ `INSTALL.md` + `data/README.md` bijgewerkt — F7, en in F8 de hook-default
- [⚠️] `docs/COLLEGA_RAPPORT_CRLF.md` §5 afgevinkt — drie van vier ✅; **punt 4 (functioneel testen) staat op “deels”** en blijft daar. De twee ontbrekende proeven zijn een koude `start_all.cmd --min` en een klik op *Save to .env*; die laatste herschrijft de echte `.env` van de gebruiker, dus die doe je niet vanuit een geautomatiseerde fase. Punt 1 is in F10 verder gebracht: de `.gitattributes` dekte alleen de Windows-bestanden, en legt nu de hele working tree vast (met POSIX-uitzonderingen) — zie §4.1 van dat rapport en §12.18 hier
- ✅ **`LUNA_EDITION_REFERENCE.md` (dit bestand) bijgewerkt: ✅ per fase, §9 ingekort, §10 aangevuld**

---

## 9. Beslissingen

### 9.1 Vastgelegd (2026-09-28) — dit zijn de regels waar we tegenaan bouwen

| # | Besluit | Gevolg voor het plan |
|---|---|---|
| **D1** ✅ | **"Vervangen" = primaire route wisselen, RenPy-code behouden als fallback.** | **Uitgevoerd in F8.** `ClipboardAdapter` is niet verwijderd; hij is verhuist naar `adapters/legacy_clipboard.py` met een `DEPRECATED`-docstring die naar de ws-route verwijst, en de klasse naam is bewust ongewijzigd gelaten (D30). De default is omgezet naar `websocket`, maar `clipboard` en `both` werken allebei nog — en dat is na de cutover functioneel gemeten, niet aangenomen. De waarschuwing in deze rij ("`source=\"renpy\"` … anders breekt mypy op de `Literal`") bleek **onnodig**: `Dialogue.source` is een `str`. Planwaarschuwingen moeten gemeten worden, anders staan ze er als werk. |
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
| **D10** ✅ | **Nee — `qwen_autostart` blijft zoals hij is en wordt níét hook-aware.** Gegeven door de gebruiker op 2026-09-29. De reden is niet "dat is te veel werk" maar dat de juiste vorm drie triggers zou vereisen: Qwen wordt ook gestart door de GUI-knop *Test TTS*, door Perfect Cut en door `POST /v1/audio/speech`. Een hook-aware autostart zou die alle drie breken, of de autostart drie keer aan drie plekken moeten krijgen — en de eerste optie is een regressie op drie werkbare features. | F7. `maybe_autostart()` blijft onafhankelijk van `hook_mode`. Vastgelegd omdat de *volgende* agent dit anders "logisch" lijkt te vinden en meeneemt dat het een gemiste optimalisatie is: het is een bewuste keuze. Het kosten van de keuze is gedocumenteerd in de README-hook-sectie (de Qwen kan opstarten terwijl er niets op de ws komt) in plaats van weggenomen. |
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

### 9.7 Uit F7 voortgekomen besluiten

| # | Besluit | Gevolg |
|---|---|---|
| **D26** ✅ | **De `websockets`-floor is `>=13.0`, gemeten in een temp-venv — niet `>=14.0` zoals mijn eigen notitie wilde.** `websockets.asyncio` bestaat vanaf 13.0; 14.0 maakte die implementatie pas de standaard. Onze handler is de enkelvoudige vorm die sinds 10.1 bestaat, dus 13.x is echt genoeg. | F7. Belangrijk omdat `uvicorn[standard]` alleen `websockets>=10.4` vraagt: op een machine met al 12.x is `>=12.0` *"al voldaan"* en crasht de import bij **opstarten** in plaats van bij installeren. Een ondergrens die niet kan crashen weegt zwaarder dan de nieuwste versie; de meting staat als commentaar in `requirements.txt` inclusief de redenering, zodat niemand hem "netter" hoeft te maken. |
| **D27** ✅ | **Het start-script meldt de hook, maar grijpt er nooit in.** Geen blanket-kill op 6677; wél een waarschuwing vóór start mét pid + `stop_all.cmd`. | F7. 6677 is een gedeelde poort — hetzelfde trucje als bij 8765 zou een vorig NovaTTS óf een willekeurig ander proces slaan. En een bezette bind-poort faalt **stil** (backend draait, alleen is er geen hook), dus de waarschuwing is geen extraatje maar het enige wat de gebruiker kan waarschuwen. `stop_all.cmd` hoeft daarom niets extra's te doen: de hook-socket gaat vanzelf dicht met de backend. |
| **D28** ✅ | **Elke bewering in een doc die gedrag beschrijft wordt eerst gemeten, anders blijft hij een aanname met een tabel.** | F7. Twee voorbeelden uit dezelfde paragraaf: de JSON-route leek gebroken omdat mijn proef `push()` rechtstreeks voedde (en dus `decode_wire_message()` oversloeg), en een alinea over sprekerregistratie wilde zeggen dat je de GUI moest herstarten terwijl `/speakers` live uit het geheugen leest. Allebei de *conclusie* omgekeerd. De regel is ook praktisch: `data/README.md` is de plek waar iemand gaat kijken als iets onverwacht doet, dus een aanname daar is geen cosmetiek. |

### 9.8 Uit F8 voortgekomen besluiten

| # | Besluit | Gevolg |
|---|---|---|
| **D29** ✅ | **De default en de validator-fallback zijn per definitie verschillend: `websocket` en `both`.** | F8. De default beantwoordt *"wat moet een verse installatie gebruiken"* → de betere route. De fallback beantwoordt *"wat moet er gebeuren als deze instelling onleesbaar is"* → de route die het minst breekt, en dat is `both`, want die levert nog tekst als één bron dood is. De instinct is ze gelijk te trekken; dat zou een typefout in `.env` stilletjes de bron laten verwijderen waarop iemand vertrouwde. Vastgelegd omdat het eruitziet als een inconsistentie en het een bewuste keuze is. Eigen test: `test_the_default_is_websocket_but_a_broken_value_still_falls_back_to_both` — omdat de neiging om ze gelijk te trekken een *volgende* agent overkomt. |
| **D30** ✅ | **Bij een rename blijft de logregel-prefix hetzelfde; de nieuwe status wordt erachter gezet.** | F8. `Clipboard adapter started (poll 0.25s) -- legacy RenPy route`. Een bestaande `grep` op de prefix blijft werken, en de startup-lognamen voortaan het woord *legacy* mee — wat precies de reden is dat `legacy_clipboard.py` in de log verschijnt in plaats van `clipboard.py`. De klasse is bewust niet hernoemd om dezelfde reden: een klassenaam die niet meer bij zijn bestand past is lastiger te lezen dan een bestand met een duidelijke naam. |
| **D31** ✅ | **Twee routes in één proces mag niet als de vraag is welke route wat weigert.** Eén route per proces, en de log is geen bewijs. | F8. Gemeten in twee ronden en beide gaven een verkeerd antwoord: `both` in één proces liet de hook rommel spreken die het klembord blokkeert (een synthese uit de vorige meting viel in het meetvenster), en de log gaf "niets gesproken" voor regels die wél gesproken waren — deels omdat de applicatielog in `.err` staat en deels omdat een cache-hit op debug-niveau stil is. Drie keer dezelfde vorm: een bewijs dat de verkeerde route volgde. Nu een harnas-conventie, niet een tip voor deze ene meting. |
| **D32** ✅ | **Een back-up die je ná de eerste meting maakt is geen back-up.** | F8. Om de stem te bewijzen wees ik `Samantha` een stem toe en zette ik daarna terug. Maar de eerste clipboard-E2E had al drie namen geregistreerd, en toen ik de "back-up" maakte was die dus al besmet. Ook mijn terugzetcontrole was zwak: ik las `$json.Samantha.voice`, maar het bestand is `{versions, speakers}` — dus die controle gaf een lege string en zou ook bij een mislukte terugzetting groen zijn geweest. Uiteindelijk met de juiste sleutel gecontroleerd en de drie meetnamen verwijderd. De les is niet "maak betere back-ups" maar: **controleer een terugzetting op de structuur die het bestand écht heeft**, anders bewijs je niets. |

### 9.9 Uit F9 voortgekomen besluiten

| # | Besluit | Gevolg |
|---|---|---|
| **D33** ✅ | **Alleen de laag repareren die in het audit-ticket staat is erger dan niets repareren.** | F9. G5.5 noemde `SpeakerRegistry.update()`. Die gerepareerd zou het *uitsluitend* erger hebben gemaakt: het register gaat dan `instruct` wél toewijzen, de signature nodigt uit om het te gebruiken, en de endpoint geeft het nog steeds niet door. De fout verhuist van duidelijk naar onzichtbaar. Vandaar een apart endpoint-testbestand (`test_speaker_patch_api.py`) naast de registrytests, en de regel dat een fix de **hele keten** volgt of geen van de lagen. Algemener: een ticket dat één regel van een keten noemt, is een ticket dat de helft van een bug beschrijft. **Het bleken er vier lagen, niet twee**, en de vierde ("_load() leest het veld niet terug") vond alleen een echte herstart-meting. |
| **D34** ✅ | **Een grep-hit is geen meting van dát hij in de functie zit die je denkt.** | F9. Ik concludeerde "de API geeft `instruct` door" op basis van een `grep` op `instruct=body.instruct` — en las die treffer als `PATCH /speakers/{name}`, terwijl het `/speak` was. Dat is §12.14 in een nieuw vorm: een proef die de verkeerde plek volgde. Concreet gevolg voor de aanpak: de regel lezen kostte niets en gaf het antwoord meteen, terwijl de interpretatie van de zoekhit een fase kostte en fout was. Bij een bug die meerdere lagen kan hebben is *lezen* de meting en zoeken de aanwijzing. |
| **D35** ✅ | **Een checklistregel die niemand herwaardeert gaat liegen, en een leugen is erger dan een ontbrekende regel.** | F9. G5.6 (kw-only) en G5.7 (ruff E303) stonden open terwijl beide al jaren waar waren — de signature bevat `*` en ruff geeft 0 fouten. Afgestreept, niet "gesloten": er is niets veranderd. Dat onderscheid staat nu in het document, want een afgestreept item en een opgelost item zien er in een lijst identiek uit en betekenen het verschil. |
| **D36** ✅ | **D5 wordt opgelost door uit de tracking te halen, niet door de geschiedenis te herschrijven.** | F9. `data/speakers.json` is het **globale** register wanneer er geen actieve game is (`games.py:speakers_path()`), dus het is werkdata van de gebruiker en geen voorbeeld — precies de reden als het al genegeerde `data/games/*/speakers.json`. Nu uit de tracking en in `.gitignore`; de geschiedenis blijft ongemoeid, dus de namen blijven in oude commits vindbaar. Dat is een bewuste afweging, geen vergetelheid: de repo is nooit gepusht dus een rewrite zou nu goedkoop zijn, maar het herschrijft 30 commits en alle hashes, waardoor de `pre-luna`-tag wijkt. Niet omkeerbaar, en niet om te draaien voor het probleem dat het oplost. |
| **D37** ✅ | **Een groene suite is geen bewijs dat een waarde een herstart overleeft — meet de round trip, niet de helften.** | F9. Na de derde laag waren 370 tests groen, waaronder een test die bewees dat de instructie *in het bestand* terechtkomt. Toen NovaTTS echt startte en herstartte, was de instructie weg — want `_load()` las alleen `voice`. Geen enkele test keek in die richting, dus er was niets om rood te worden. De regel die hieruit volgt: bij een waarde die moet *persisteren* is de vraag niet "wordt hij geschreven?" maar "komt hij na een nieuw proces terug?", en dat is een meting over twee processen. In de testvorm is dat `SpeakerRegistry(path)` twee keer maken, of één keer maken na een handgeschreven bestand. |
| **D38** ✅ | **Een meetinstrument dat een gat melden kan is gevaarlijker dan een meetinstrument dat niets zegt.** | F9. Twee keer meldde een harnas een tekort dat er niet was. Eerst zocht het met een regex naar `<naam>…FAILED` terwijl pytest `FAILED…<naam>` schrijft, dus het vond niets terwijl de samenvatting erboven gewoon "1 failed" zei. Later zette ik `test_load_tolerates_a_null…` in de must-fail-lijst van mutatie C omdat hij thematisch hoorde — maar die test assertiont `== ""`, en zowel de kapotte als de goede code leveren exact `""`, dus hij kon C structureel niet zien. In beide gevallen was de **verwachting van het harnas** fout, niet de code. Een harnas dat teveel kan zien leidt tot een fix die niet nodig is; een harnas dat te weinig kan zien leidt tot een fix die ontbreekt. Daarom: elke mutatie heeft een must-fail- én een mag-niet-vallen-lijst, en een regel "NIET omgevallen" is een uitkomst om te onderzoeken, niet iets om weg te filteren. |


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
| 2026-09-29 | F7 | *"F7: lifecycle…"* | **354 ✅** (0 ❌) | **0 ✅** | **0 ✅** | ✅ | **354 → 354, opzettelijk.** Nul regels productie-Python en nul regels GUI (`git diff --stat -- backend/novatts gui/src` leeg), dus het aantal tests mag hier per definitie niet wijzigen — dat maakt deze regel de anti-regressiebewijs voor §12.9 in plaats van een herhaling. Buiten `pytest`: ~~13/13 cmd-gevallen~~ **→ 8/8 na herwaardering in F11, want het harnas bleek op drie manieren stuk zonder één fout te geven** (zie de F7-testsectie en §12.19), 6/6 PowerShell-gevallen, beide met een gedocumenteerde valse-groen achter de vingers. `websockets`-floor gemeten 12.0 crasht / 13.0 werkt. |
| 2026-09-29 | F8 | *"F8: cutover…"* | **355 ✅** (0 ❌) | **0 ✅** | **0 ✅** | ✅ | 354 → 355: de +1 is `test_the_default_is_websocket_but_a_broken_value_still_falls_back_to_both`, dat de default en de fallback uit elkaar houdt (D29). Dit is de eerste fase die **gedrag omzet** — `hook_mode` staat nu op `websocket` — en daarom ook de eerste met functionele metingen buiten `pytest`. De kernclaim van de DoD is indirect bewezen: dezelfde tekst met en zonder toegewezen stem geeft twee verschillende cache-hashes, dus de stem bereikt het model; of die stem *goed* klinkt kan alleen een mens beoordelen. Drie meetinstrumenten gaven een zeker verkeerd antwoord en dat kostte meer tijd dan de hele cutover — zie §12.15. |
| 2026-09-29 | F9 | *"F9: opruimen…"* | **370 ✅** (0 ❌) | **0 ✅** | **0 ✅** | ✅ | 355 → 370: 15 tests voor G5.5. **De +15 maskeerden een bug**: de instructie-tests bewzen het geheugen en het bestand, en zagen niet dat `_load()` het veld niet teruglas — 370 groen en het product stuk. Gevonden door de herstart-meting, niet door de suite (D37). Daarnaast G5.4/G5.5/G5.6/G5.7/G6.2/G6.3 herwaardeerd (4 van de 6 lagen al afgehandeld), `data/speakers.json` uit de tracking (D36), en de `description` naar `(LunaHook/RenPy/Qwen3)`. 33/33 mutanten. **G5.5 bleek vier lagen, niet één** — en de vijfde is een featuregat, bewust niet dichtgezet. |
| 2026-09-29 | F10 | *"F10: regeleindes…"* | **370 ✅** (0 ❌) | **0 ✅** | **0 ✅** | ✅ | **370 → 370, opzettelijk**: nul regels Python en nul regels GUI, alleen `.gitattributes` en twee documenten. Nul runtime-impact is hier het *punt*, want de wijziging hoort de uitkomst niet te raken. De `.gitattributes` kreeg de vorm van de hele working tree vastgelegd in het project in plaats van in de globale `core.autocrlf` van de gebruiker (§12.18). Dat leverde twee bestanden op die stuk waren en daar niets van wisten: `setup.sh` met `#!/bin/bash\r` in de shebag, en een `Makefile` waarvan **alle 88** receptregels een CR droegen terwijl `INSTALL.md` `make dev` voorschrijft. 136 paden geteld in plaats van vijf: nul afwijkingen. En de uitschrijfactie vier keer herhaald onder verschillende `core.autocrlf`-standen, met identieke uitkomst — de sterkere claim dan "het werkt hier". Het functionele bewijs dat een CRLF-script breekt is hier **niet** te leveren: Git Bash op Windows stript de CR bij lezen, dus wat hier aantoonbaar was is de byte-toestand, en wat daarop volgt is POSIX- en make-semantiek. |
| 2026-09-29 | F11 | *"F11: een lege map…"* | **370 ✅** (0 ❌) | **0 ✅** | **0 ✅** | ✅ | Ontstaan doordat iemand `start_all.cmd --min` draaide en vroeg of de CMD kapot was. **Het script was niet kapot; de melding was onjuist.** `start_all.cmd` testte `gui\node_modules`, een map die dit project nooit vult: de root `package.json` heeft `"workspaces": ["gui"]`, dus npm hoist alles naar `node_modules\.bin` in de root. De test vuurde dus bij élke start, meldde een ontbrekende install en draaide daarna een `npm install` die "up to date" zegt en niets verandert (gemeten: 0,8 s, geen `gui/node_modules` erna, lockfiles schoon). Het script sprak zichzelf tegen, want het tauri-blok eronder kijkt wél op beide plekken. Vervangen door een test op een echt binair (`vite.cmd`) op beide plekken, plus een waarschuwing wanneer de install de zaak niet repareert. **5/5 cmd-gevallen, en het discriminatiebewijs is meegeleverd: de oude conditie haalt 2 gevallen om, de nieuwe 0** — anders beweest 5/5 niets. Het F7-cmd-harnas bleek onderweg **stuk op drie manieren zonder één fout te geven** (verouderde slotmarker die op hing · `call :label` met regeleinden, wat een grondige cmd-beperking is · `STUB_PORT` pas ná het bouwen van de stub); de claim "13/13" is teruggezet naar 8/8, zie de F7-testsectie. Eén correctie op mezelf, want de tussenmeting loog om de eindstand: een meting halverwege gaf **364 + 6 rode tests** en dat stond bijna in dit document als de uitkomst, terwijl de eindmeting **370 groen** geeft. Die 6 waren de bekende omgevingsgroep — Open WebUI, een `python`-proces, op 8080 waar `NOVATTS_QWEN_URL` wijst, `405` op `/v1/audio/speech` — en de eindmeting zag ze niet omdat de poort inmiddels vrij was. Twee metingen, twee uitkomsten, één oorzaak: de omgeving, niet de code. |

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
| F7 Lifecycle & docs | ✅ | De headline is een **cmd-bug die altijd "ja" zei**: `^|` binnen `( … )` maakt de pipe letterlijk, dus de check kon nooit "nog niet aan het binden" melden (§12.14). Gemeten met een `netstat`-stub: variant `^|` gaf 0 bij een vrije én een bezette poort, de kale `|` gaf 1 en 0. Tweede vondst: `NOVATTS_HOOK_PORT = 7300` werd door het script genegeerd terwijl de backend hem wél las — **het log noemde een poort waar niemand op luisterde**. `websockets>=12.0` bleek te laag (12.0 crasht op import, 13.0 werkt) → `>=13.0` (D26). `start_all.cmd` meldt de hook maar doodt hem nooit (D27). `setup.ps1` zwijgt op loopback en waarschuwt alleen bij een blootgesteld adres. Makefile-gate miste svelte-check. Docs: pipeline, 9 env-sleutels, `hook_mode`-tabel, Hook-kaart-drie-toestanden, LunaTranslator-stappen, `data/README.md`, en §5 van het CRLF-rapport — dat wees naar een pad (`NovaTTSLun@`) dat niet meer bestaat en is herschreven met bewijs per punt, punt 4 bewust **deels**. Twee doc-claims bleken onjuist en zijn door meting gecorrigeerd (D28). **354 → 354 tests, opzettelijk.** |
| F8 Cutover RenPy→LunaHook | ✅ | De vijf stappen in de geplande volgorde, wat het verschil maakt: **stap 1 was de nulmeting, vóór het default omging**, want een meting ná de wijziging meet de nieuwe situatie en noemt het een bewijs. `hook_mode` staat nu op `websocket`; het klembord start niet meer mee (bewezen met een regel die wél audio oplevert, en daarna één die dat níet doet). `clipboard.py` → `legacy_clipboard.py` via `git mv`, klasse naam bewust ongewijzigd (D30), legacy-badge zichtbaar in de GUI in plaats van begraven in `.env`. Kernclaim indirect bewezen via de cache-hash: dezelfde tekst geeft twee audiostreamen met en zonder stem — of die stem *goed klinkt* kan alleen een mens beoordelen, en dat staat als 8-staps checklist overgedraven. Ook gemeten: **beide routes laten interpunctie door** — bestaand Main-gedrag, dus gedocumenteerd en niet "opgelost". De mypy-waarschuwing uit het plan bleek onnodig (`Dialogue.source` is een `str`). **355 tests.** Drie meetinstrumenten gaven een zeker verkeerd antwoord (§12.15). |
| F9 Opruimen | ✅ | `vntts/` en G5.8 al in F0. **G5.5 bleek vier lagen diep** (toewijzing · `SpeakerPatchBody` · endpoint · `_load()`), niet één zoals de audit noteerde; de vierde vond alleen een echte herstart-meting, met 370 groene tests erboven (D37). Een vijfde laag bleek een *featuregat* — niets gebruikt `Speaker.instruct` voor synthese — en is bewust niet dichtgezet, want dat is een ontwerpbeslissing. 4 van de 6 herwaardeerde checklistregels lagen al afgehandeld zonder dat iemand dat bijhield (D35). `data/speakers.json` uit de tracking met de geschiedenis ongemoeid (D36). Twee DoD-regels bewust **niet** op ✅ gezet: de module-limiet van 500 regels wordt gehaald door twee van de vier nieuwe modules niet, en de duurtest is nooit gedraaid. |
| F10 Regeleindes | ✅ | Buiten de featurelijn: het gevonden gat was dat de vorm van de working tree in het gitprofiel van één gebruiker stond in plaats van in het project. `.gitattributes` legt nu vast dat tekst CRLF op schijf staat, met `*.sh`/`Makefile`/`*.mk` als uitzondering op LF. Dat vond twee bestanden die kapot waren zonder dat iets dat merkte: `setup.sh` (shebag met CR) en de `Makefile` (88/88 receptregels met CR, terwijl `INSTALL.md` `make dev` voorschrijft). Geteld over 136 paden, nul afwijkingen; de uitschrijfactie viermaal herhaald onder verschillende `core.autocrlf`-standen met identieke uitkomst. **370 → 370 tests, want er viel geen regel productiecode om te schrijven** — en dát is hier de bewering die gemeten moest worden, want een `.gitattributes` hoort de uitkomst niet te raken. Het functionele bewijs dat CRLF een bash-script breekt is hier niet te leveren (Git Bash stript de CR); wat gemeten is, is de byte-toestand. Details in §12.18. |
| F11 De valse alarmmelding | ✅ | Ontstaan doordat iemand `start_all.cmd --min` draaide en vroeg of de CMD kapot was. Het script was niet kapot, de melding wel: de controle vroeg naar `gui\node_modules`, een map die een npm-workspace nooit vult. Dus iedere start meldde een ontbrekende install en draaide daarna een install die niets doet. Het script sprak zichzelf tegen, want het tauri-blok eronder kijkt wél op beide plekken. Vervangen door een controle op een echt binair, plus een waarschuwing wanneer de install niet helpt. **5/5 cmd-gevallen, met discriminatie: de oude conditie haalt er 2 om.** Onderweg bleek het F7-cmd-harnas **stuk zonder één fout te geven** — verouderde marker (hing op), `call :label` met regeleinden (onmogelijk in cmd), en `STUB_PORT` te laat toegewezen (bezette tak nooit getest) — dus de "13/13" is teruggezet naar 8/8 (§12.19, en de F7-testsectie). **370 tests**, want er viel geen regel Python of GUI om te schrijven. |

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
14. **Nooit een conditie in een script testen op één uitkomst.** F7 leverde de pijnlijkste versie van deze regel tot nu toe, in een taal zonder typechecker en zonder testtoolchain. De regel is de algemene vorm van §12.8/§12.12: **elke conditie die op een grondwaarde steunt — een exitcode, een `grep`, een `netstat`, een `Test-Path` — moet zowel op de waar-positie als op de lege-positie zijn bewezen.** Concreet: `^|` binnen een `( … )`-blok maakt de pipe letterlijk, zodat `netstat … ^| findstr … ^| findstr …` als één commando draait en altijd `errorlevel 0` geeft — de check zei dan permanent dat er een client wachtte. Gemeten, want het kostte een test om het te zien.

    Wat het gevaarlijk maakt is de richting waarin het misgaat. Een kapotte check is niet willekeurig stuk; hij is stuk in de richting die het best lijkt te werken. En het geval "geen bezette poort" haalde zijn groenheid uit precies dezelfde bug — een gemeten groen dat de verkeerde reden had, het gevaarlijkste soort (§12.12). Drie extra regels die hieruit volgen en die in F7 alle drie golden:

    - **Binnen `( … )` is `|` GEEN escape nodig, en `^|` maakt hem letterlijk.** Buiten een blok — `for /f … in ('…')` — is de escape wél nodig. Twee plaatsen in hetzelfde bestand, tegengestelde regel, en de gemeten reden staat als commentaar bij beide, want de betekenis is plaats-gebonden en niet bestand-gebonden.
    - **Een startmelding die een waarde noemt, moet dezelfde waarde gebruiken als de app.** Gemeten: het script las `NOVATTS_HOOK_PORT = 7300` niet (spaties), terwijl pydantic-settings wél trimt — de backend draaide op 7300 en het log riep 6677. Onlees-configuratie is erger dan geen melding, want hij is niet merkbaar.
    - **Een proef die een andere route volgt dan productie is een aanname met een tabel.** Twee F7-proeven sloten `decode_wire_message()` over en rekenden de JSON-herstap dubbel om; beide sloten de conclusie "dit werkt niet" — wat aantoont dat een gemeten verhaal niet zomaar klopt als er één regel code is overgeslagen.

    En de vorm waarin dit opgeslagen moet worden: **de regel in het document, het harnas in de temp-map.** Een harnas in de repo is een tweede ding dat roet aan, maar een harnas dat nergens is, betekent dat de *reden* in het document moet staan — anders lost het probleem zichzelf op en is de volgende agent het kwijt.
15. **Nooit de afwezigheid van een logregel als bewijs gebruiken.** F8 leverde drie meetinstrumenten die een *zeker* antwoord gaven en alle drie lagen. §12.14 gaat over condities die je op twee posities moet toetsen; deze regel gaat over iets dat ernaast ligt en minstens zo gevaarlijk is: **het kiezen van het bewijsstuk.** Een pipeline heeft altijd paden waarop iets wél gebeurt en toch niets laat zien, en drie F8-harnassen belandden elk in zo'n pad.

    | pad | wat er gebeurde | hoe het eruit zag |
    |---|---|---|
    | applicatielog gaat naar **stderr**, niet naar stdout | de regels stonden in `.log.err` terwijl het harnas `.log` las | "niets gesproken" voor regels die wél gesproken waren |
    | **audiocache** op tekst-hash, `Cache hit` op *debug* | dezelfde regel een tweede keer sturen geeft een hit en géén INFO-regel | opnieuw "niets gesproken", nu voor een regel die in de eerste ronde wél een WAV had gemaakt |
    | synthese is **asynchroon** en overstemt zichzelf | de synthese van de vorige meting landde binnen het meetvenster van de volgende | de klembord-route leek rommel te spreken die hij blokkeert |

    De regel die eruit volgt is niet "log meer". Die zou de eerste twee rijen niet hebben opgelost, want die loggden níets te melden. De regel is: **kies een artefact dat niet kan bestaan tenzij de gebeurtenis plaatsvond.** Voor "er is audio gemaakt" is dat het bestand in `data/cache/`; voor "er is een spreker geregistreerd" is dat de naam in `/speakers`; voor "de poort is vrij" is dat `Get-NetTCPConnection`. Een logregel is een *hint* — handig om te vinden, ongeschikt om te bewijzen.

    En de vorm die het meeste opleverde: **één route per proces als de vraag is welke route wat doet.** Twee routes in één proces is verleidelijk omdat het dan zeker "dezelfde omgeving" is, maar het is precies die gedeelde omgeving die het meetvenster van de ene route in het antwoord van de andere laat vallen. Ook het gemakkelijkste om te vergeten: de eerste draai gaf een tabel die met de code niet kon kloppen, en alleen de tweede draai — één route per keer, eigen proces — gaf de waarheid.

    Tot slot de vorm die het meest tijd kostte en het minste opleverde: **geloof niet in een terugzetting die je niet op de juiste sleutel hebt gecontroleerd.** Het spelregister is `{versions, speakers}`, dus `$json.Samantha.voice` geeft een lege string — ook wanneer de terugzetting mislukt was. Mijn eigen back-up bleek bovendien al besmet op het moment dat ik hem maakte (D32). Een terugzetcontrole die de structuur raakt die het bestand *niet* heeft, is net zo'n dode check als een `^|` in een blok.
16. **Nooit een keten repareren op de laag die in het ticket staat, en nooit een persisterende waarde bewijzen met een halve round trip.** F9 was een no-op van één regel en bleek vier lagen (D33), waarvan de vierde — `_load()` las `instruct` niet terug — alleen zichtbaar werd door NovaTTS echt te starten, te herstarten en opnieuw te lezen. **370 tests waren groen toen die bug werd gevonden** (D37). Twee regels staan er dus naast: (a) loop de keten van ingang tot gebruik af voordat je "klaar" zegt — hier was dat `update()` → body → endpoint → `_load()` → synthese; (b) bij een waarde die moet overleven is de slotproef een **tweede instantie** die dezelfde file opent, want binnen één proces is de waarde per definitie nog warm. En als de keten uitkomt bij "niets gebruikt dit eigenlijk", dan is dat een gat in het product en geen defect: zeg het en laat het staan, in plaats van het als bijwerking van een bugfix te repareren.
17. **Een conversie die haar eigen resultaat niet opnieuw meet is geen conversie.** F9 vond vier regels met `\r\r\n` in `LUNA_EDITION_REFERENCE.md`, en die bleven overeind door vier opeenvolgende scripts heen die allemaal "klaar" meldden. Twee oorzaken, en ze versterken elkaar:

    | oorzaak | gevolg |
    |---|---|
    | `f9_doc.py` riep zijn `prep()` (zet `\n` om in het regeleinde van het bestand) óók op de **vervangende** tekst, terwijl daar al `eol` met de hand was ingevoegd | er ontstond `\r\n` + `\r\n` = `\r\r\n` |
    | `\r\r\n` is een **vast punt** van de gebruikelijke twee-staps conversie (`-replace "\r\n","\n"` en daarna `-replace "\n","\r\n"`) | de eerste stap maakt er `\r\n` van, de tweede maakt het weer `\r\r\n`, voor altijd |

    Het patroon is het punt, niet het incident: **noem na een conversie het getal opnieuw.** Niet "ik heb het omgezet", maar "er staan nog 4 CRLF-regels". Een vreemde regeleinde is bovendien stil — het document rendert gewoon, en het valt pas op bij `git diff`, waar het dan het hele bestand als gewijzigd toont in plaats van de echte wijziging.

    En de vraag die hier meestal achter zit, is niet "welk regeleinde" maar "welke vorm wil dit project". Voor deze repo is dat gemeten en niet afgeleid: **alle 17 blobs staan als LF, alle 17 working-tree-bestanden als CRLF**, wat komt door de globale `core.autocrlf=true` van de gebruiker en niet door een besluit van het project. De eigen `.gitattributes` zegt letterlijk *"overig consistent Unix (behalve Windows-specifieke tooling)"* en regelt alleen `cmd`/`bat`/`iss`/`ps1`. Voor zestien van de zeventien bestanden valt dat samen; voor `LUNA_EDITION_REFERENCE.md` niet — git maakte daar de brug niet en zette CRLF in de index, met een diff van 1580/1387 in plaats van 225/32. `git add --renormalize` veranderde daar niets aan. Opgelost door het bestand terug te zetten op LF, wat is wat de `.gitattributes` voorschrijft.

    Eén bijvangst bij het controleren: **twee diff-algoritmen vergelijken op gelijkheid is een kapotte controle.** `difflib` en `git` vonden 226/33 en 225/32 op hetzelfde paar bestanden, één regel verschil, en dat is niet een afwijking maar twee verschillende algoritmen die geen van beide het minimale edit-script hoeven te vinden. De zinvolle controle is op orde van grootte: is de diff klein, of is het het hele bestand? Daar is geen tweede algoritme voor nodig.

18. **Nooit de vorm van een bestand laten afhangen van iemands gitconfig.** Regel 17 besloot met de vaststelling dat alle blobs LF waren en alle working-tree-bestanden CRLF, en dat dit kwam door de globale `core.autocrlf=true` van de gebruiker — niet door een besluit van dit project. Dat bleef een stelling zonder gevolg, en had dat ook kunnen blijven: niets in het project dwong die vorm af, dus een volgende agent die hier tegenaan liep, zou het opnieuw hebben moeten uitzoeken.

    De regels staan nu in `.gitattributes` in plaats van in het profiel van één gebruiker:

    ```
    *                  text=auto eol=crlf
    *.cmd/.bat/.iss/.ps1   text eol=crlf
    *.sh / Makefile / *.mk  text eol=lf
    ```

    Dat de eerste regel veilig is volgt uit hoe git werkt, en is geen hoop: git schrijft tekst altijd als LF in de database en converteert pas bij het uitschrijven. De regels raken dus geen blob, geen hash en geen regel geschiedenis — alleen de vorm op schijf. Ze kunnen daarom nooit "het hele bestand gewijzigd" in een diff veroorzaken; gebeurt dat wel, dan is er iets anders aan de hand en moet dat worden onderzocht in plaats van weggecorrigeerd.

    De uitzonderingen bestaan omdat CRLF daar geen "windows" is maar een fout, en gemeten, niet aangenomen:

    | bestand | gemeten | gevolg |
    |---|---|---|
    | `setup.sh` | 169 CRLF-regels, shebang `#!/bin/bash\r` | de shebag leest de **kernel**, dus op elk POSIX-systeem *bad interpreter: /bin/bash^M* |
    | `Makefile` | 164 CRLF-regels, **alle 88** receptregels met CR | `INSTALL.md` schrijft `make dev` voor, en make voert `commando\r` uit |

    Eerlijkheid over wat hier meetbaar was: op deze machine met Git Bash werkt een CRLF-script prima, omdat MSYS de CR bij het lezen stripst. Die functionele breuk is hier dus níet aan te tonen, en op Linux of macOS wel. Gemeten is de byte-toestand; de conclusie volgt uit POSIX- en make-semantiek, en is als zodanig geformuleerd.

    Gemeten over de hele repo in plaats van een steekproef (`git ls-files --eol`, 136 paden): 116 `i/lf w/crlf`, 9 binaire, 2 zonder enig regeleinde (éénregelige JSON — niets te converteren, dus een eigen categorie en géén afwijking), 2 `i/lf w/lf` en dat zijn precies `setup.sh` en `Makefile`. Nul afwijkingen. En de uitschrijfactie is herhaald onder vier `core.autocrlf`-standen (`true`, `false`, `input`, en de echte config): **identieke uitkomst**, met de binaire bestanden byte-voor-byte gelijk aan hun blob. Dat is de sterkere formulering dan "het klopt op deze machine", want het neemt de oorzaak weg in plaats van het symptoom te controleren.

    Wat een bestaande working tree betreft: git schrijft een bestand pas opnieuw uit als de inhoud wijkt, dus een map die al open staat houdt de oude vorm tot je er iets in verandert of het bestand weghaalt en terugzet. Op een verse clone klopt het meteen. En de regels moeten niet zorgen voor de vorm van bestanden die git niet bijhoudt — `.env`, `data/cache`, de venv; die hebben hun eigen weg.

19. **Nooit een pad testen; test of iets dat nodig is aanwezig is.** F11: `start_all.cmd` vroeg `if not exist "%ROOT%\gui\node_modules"` en meldde bij elke start dat de install ontbrak. Het pad klopt niet met de architectuur — de root `package.json` heeft `"workspaces": ["gui"]`, dus npm hoist alles naar `node_modules\.bin` in de root en vult `gui\node_modules` nooit. De melding was dus structureel onjuist, en de `npm install` die erop volgde bevestigde dat: 0,8 s, "up to date", geen `gui\node_modules` erna, lockfiles schoon. Het script sprak zichzelf tegen, want het tauri-blok verderop kijkt wél op beide plekken.

    Het patroon is niet "gebruik `--root` in plaats van `--cwd`". Het is: **een pad dat je nooit hebt aangemaakt is geen bewijs van een ontbrekende install**, en de vraag die je stelt moet dezelfde zijn als de vraag die je beantwoordt. "Is er een install?" beantwoord je met het ding dat je nodig hebt, niet met de map die je zou aanmaken.

    | | |
    |---|---|
    | **gemeten, en het onderscheidt** | de nieuwe conditie geeft 5/5, de oude haalt 2 van die 5 om |
    | **geteld, niet gesampled** | 136 paden, nul afwijkingen |
    | **beide takken getest** | de waarschuwing na een mislukte install is een eigen geval, anders zou die regel nooit blijken te werken |

    En de regel erboven blijft staan, want dit was de derde keer in één sessie. De eerste twee fouten kwamen uit een harnas, deze uit het script zelf. Telkens was de vorm: **een meting die een plausibel getal of een plausibele boodschap opleverde, en dus niet opviel.** Concreet, drie variaties op één regel:

    - `for /f "delims=" %%L in ("pad")` zonder `usebackq` telt de letterlijke tekst van het pad: altijd 1. Er stonden 27 regels.
    - `if x GOTO label (` — cmd leest de `(` als het begin van een blok en zegt `GOTO was unexpected at this time`.
    - `call :label "a<newline>b"` geeft alleen de eerste regel door; de rest ontsnapt en wordt als commando uitgevoerd. Alle vijf meerregelige gevallen leverden dus een `.env` van één regel, en failden daarna met `NOVATTS_HOOK_PORT is not recognized` — een fout die naar het script wijst terwijl de oorzaak in het harnas zat.

    Ook dit hoort erbij: het F7-harnas hing op een **verouderde marker** (een commit herschreef één woord in de regel waar de marker naar zocht) in plaats van te melden dat de marker niet meer klopt. Een harnas dat stil ophoudt te meten is erger dan een harnas dat faalt. Dus twee regels erbij, die in beide harnassen staan: tel de getilde regels en meld een te korte lift als fout, en gebruik een marker die op een **structuurkenmerk** eindigt in plaats van op de volledige tekst — de eerste achttien tekens, niet de hele regel.


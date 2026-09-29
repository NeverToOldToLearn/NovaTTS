# Handover — CRLF, local setup en Luna-edition

Voor: collega op de **NovaTTS Luna**-editie (`D:\Projects\NovaTTSLun@`)
Nieuwste triage: **2026-09-18**

## 1. Waarschuwing die je tegenkomt

```
D:\Projects\NovaTTSLun@> start_all.cmd
Of kopieer backend\.venv NIET via cloud-sync -- draai setup in de nieuwe map.
```

**Betekenis.** De `backend\.venv` is machine- en padgebonden (headers en absolute
paden in `pyvenv.cfg`). Via cloud-sync kopiëren (OneDrive, Dropbox, enz.)
geeft een kapotte venv; Python of pip vindt het base-home niet meer terug. De
waarschuwing in `start_all.cmd:18-24` detecteert dit en forceert `setup.ps1`.

**Wat te doen op een nieuwe laptop, clone, of na verhuizing naar een andere
map:**

```powershell
./start_all.cmd --repair      # herbouwt venv + npm -- alle .cmd hebben nu \r\n
# of:
./setup.ps1 -Force -Shortcuts # maakt ook Start Menu/Desktop snelkoppelingen
```

Geen shortcuts/handmatige python-venv nodig. `--repair` verwijdert alleen
`.venv`, dus je `.env` en game-voice mappings in `data\` blijven staan.

## 2. Root cause: waarom alles in één keer brak

Alle `.cmd`-bestanden zijn ooit geschreven met `write` en kregen **Unix
`\n` line endings** i.p.v. Windows `\r\n`. `cmd.exe` vereist CRLF. Zonder dat
wordt de eerste regel (`@echo off`) verkeerd geparst — vandaar fouten als

```
'isableDelayedExpansion' is not recognized as ...
```

## 3. Wat er nu is gefixt (21-26 september 2026)

| Wanneer | Fix |
|--------|-----|
| 21-26 sep, **Tauri close-hang** | `gui/src-tauri/src/lib.rs` had een oneindige `CloseRequested` -> `prevent_close()` + `_window.close()`-lus; handler is verwijderd, cleanup loopt via `ExitRequested`/`Exit`. |
| 22 sep, **Settings-tab** | GUI mistte een plek om paden te wijzigen. Toegevoegd: `GET/POST /settings` (backend: `backend/novatts/main.py`), `SettingsPanel.svelte`, wijzigingen in `gui/src/lib/{api,types}.ts` + `App.svelte`, geverifieerde `vite build` `79.85 kB`. |
| 22 sep, **Backend resilience** | `NovaApp.start():110` start Qwen nu in een try/except zodat autostart-falen de backend niet crasht. |
| 26 sep, **CRLF voor Windows** | Alle `.cmd` naar CRLF gezet. Herhalen na `git clone` op schone clone. |

**Status verificatie (`ruff`/`mypy`/`vite build`) 26 sep:** alleen pre-existing
`SIM105` style-waarschuwingen in `games.py`/`main.py`/`player/audio.py` en
één `pyperclip` stubs-hint (`clipboard.py:13`). Nieuw code schoon.

## 4. Permanente preventie

### 4.1 `.gitattributes` — **uitgebreid (29 sep 2026)**

De oude versie stond alleen CRLF-voor op de Windows-bestanden en liet de rest
over aan de gitconfig van de gebruiker. Dat betekende dat de vorm op schijf niet
in het project stond, maar in `core.autocrlf` van wie er dan ook mee werkt. Op
een machine met `core.autocrlf=input` of `false` zag dezelfde clone er anders
uit. De regels zijn nu expliciet, in twee delen:

```
*               text=auto eol=crlf     # de hele map CRLF op schijf, LF in git

*.cmd/.bat/.iss/.ps1  text eol=crlf    # expliciet, want cmd.exe vereist dit

*.sh / Makefile / *.mk  text eol=lf    # uitzondering: hier is CRLF een fout
```

**Waarom de uitzondering bestaat.** `setup.sh` en de `Makefile` stonden als
CRLF op schijf terwijl hun blobs LF waren — gemeten, 169 respectievelijk 164
regels, alle 88 receptregels van de Makefile inclusief. Twee gevolgen:

- `setup.sh` begint met `#!/bin/bash\r`. Die shebag leest de **kernel**, niet
  bash, dus op elk POSIX-systeem volgt *bad interpreter: /bin/bash^M*. Op deze
  Windows-machine met Git Bash werkt het toevallig, omdat MSYS de CR bij het
  lezen stripst — en juist daarom is het hier niet te meten en elders wel.
- `INSTALL.md` schrijft `make dev` en `make dev-tauri` voor. Make voert een
  receptregel uit mét de CR, dus het recept wordt `commando\r`.

Het vaste punt dat dit volledig onschadelijk maakt: git schrijft tekst altijd
als LF in de database, en de `eol`-convertie gebeurt bij het uitschrijven naar
de working tree. Deze regels veranderen dus geen enkele blob, geen enkele hash
en geen enkele regel geschiedenis — alleen de vorm op schijf.

**Bewijs** (136 getrackte paden, `git ls-files --eol`): 116 staan `i/lf w/crlf`,
9 `i/lf w/-text` (binaire ico's/png's), 2 zonder enig regeleinde (éénregelige
JSON, dus niets te converteren), 2 `i/lf w/lf` — en dat zijn precies
`setup.sh` en de `Makefile`. Nul afwijkingen. Daarnaast is dezelfde
uitschrijfactie onder vier `core.autocrlf`-instellingen (`true`, `false`,
`input`, en de echte config) uitgevoerd: de vier uitkomsten zijn identiek, en
de binaire bestanden zijn byte-voor-byte gelijk aan hun blob.

### 4.2 `.gitignore` (gewijzigd)

- `backend/.env` (was globaal `.env`) — alleen lokaal backend `.env` blijft lokaal; `.env.example` wel mee.
- `*.log` — alle logs genegeerd.
- **Absolute paden uit `.env.example`** (die verwijzen naar `D:\Projects\qwentts.cpp` / `E:\LLM's\...`) zijn op Windows onportable. Zie 4.3.

### 4.3 Herinstallatie / op schone laptop (GitHub)

**Workflow voor elke eindgebruiker:**

```powershell
git clone https://github.com/.../NovaTTS.git
cd NovaTTS

# one-click setup (venv + npm, maakt backend\.env uit .env.example)
./setup.ps1                 # of met shortcuts: ./setup.ps1 -Shortcuts
# of:
./Install.cmd               # wrapper voor setup.ps1

# daarna: pas paden aan vóór eerste run
notepad backend\.env        # of via GUI → Settings-tab (na eerste run + Save)
# velden: NOVATTS_QWEN_BIN, MODEL, CODEC, SAMPLES_DIR, evt. URL/DEFAULT_VOICE

./start_all.cmd --visible   # default --min (dashboard → Qwen ✓)
./stop_all.cmd              # sluit backend + tts-server
```

`start_all.cmd` heeft nu een self-heal: als `.venv` verplaatst is of
`node_modules`/`dist` ontbreekt, draait hij `setup.ps1` of `npm install`/`build`
automatisch (regels 41-50) voordat backend/GUI starten — dus een losse
`git pull` na sync is genoeg.

**Zaken die NIET via GitHub gaan (per machine instellen):**

- Qwen binaries/modellen/codec en `Samples_Clone` staan NIET in de repo (GBs groot, padafhankelijk). Elke machine zet eigen `backend\.env`.
- `backend\.env`, `*.wav`, `data/cache` zijn ignored.
- Tauri NSIS-installer (25 MB `*.exe`) is een CI-/release-artefact, niet per commit.

## 5. Wat de Luna-edition overneemt — **afgehandeld (F7)**

Deze sectie wees naar `D:\Projects\NovaTTSLun@`. Dat pad bestaat niet meer; de
Luna-edition wordt inmiddels **in deze tak** gebouwd (`Luna-Hook`), en de donor
`NovaTTSLuna` is gearchiveerd onder tag `donor`. De drie preventiepunten staan
hieronder met hun meetbaar bewijs in plaats van met een opdracht:

| # | Punt | Status | Bewijs |
|---|---|---|---|
| 1 | `.gitattributes` | ✅ hier, **uitgebreid 29 sep** | `* text=auto eol=crlf`, plus de vier Windows-bestanden expliciet, plus `*.sh`/`Makefile`/`*.mk` op `eol=lf`. Zie §4.1 voor de meting |
| 2 | CRLF-fix op alle `.cmd`/`.ps1` | ✅ hier | 11 bestanden gescand: overal `CRLF=n, kale-LF=0` — ook de drie die F7 bewerkte (`start_all.cmd`, `stop_all.cmd`, `setup.ps1`) |
| 3 | `.gitignore` `backend/.env` | ✅ hier | regel 13, met de `.env.example`-flow erboven |
| 4 | functioneel testen | ⚠️ **deels** | zie hieronder |

> Punt 2 is geen cosmetiek: `cmd.exe` voert een `.cmd` met kale-LF regels uit in
> een gebroken modus, met fouten die naar de *volgende* regel wijzen. De
> `.gitattributes`-regel is de duurzame vorm — die hoeft niet opnieuw gedraaid
> te worden na elke `git clone`, in tegenstelling tot het losse commando hierboven.

**Wat er aan punt 4 nog ontbreekt.** Er is een koude start van
`start_all.cmd --visible` + het aanklikken van *Save to .env* nodig om de
keten volledig af te vinken. F7 heeft de achterliggende keten wél gedraaid:
backend op `:8765`, de gebouwde GUI erop, `/health` en `/status` geverifieerd,
de Hook-kaart en de Text-hook-sectie inhoudelijk nagekeken — en juist *niet* op
Save geklikt, omdat dat de echte `.env` van de gebruiker zou herschrijven. Die
laatste klik hoort bij een release-test met een `.env` die men mag veranderen.

## 6. Open punten / bekende zaken

- Kleurige batch-waarschuwing staat soms in Windows zelfs zonder kleur: dat is cosmetisch.
- Als het startscript “hangt” na start: check of een oude `tts-server.exe` (qwentts) nog draait op `:8080` (via Taakbeheer → Details).
- `core.autocrlf` werkte op deze machine als `true`, maar alleen met `.gitattributes` blijft het deterministisch na `git clone` + AI-writes. De uitgebreide regels (§4.1) maken die afhankelijkheid van de persoonlijke gitconfig nu helemaal weg: gemeten identiek onder `true`, `false`, `input` en de echte config. Je hoeft `core.autocrlf` dus niet meer in te stellen.
- **Bestaande working trees blijven zoals ze zijn tot je de bestanden aanraakt.** Git schrijft een bestand pas opnieuw uit als de inhoud wijkt. Een map die je al een tijd open hebt, houdt dus de oude vorm tot je er iets in verandert of het bestand verwijdert en terugzet. Op een verse clone is het meteen goed.

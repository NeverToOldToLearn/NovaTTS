# NovaTTS — Installatiehandleiding

Dit document beschrijft hoe je NovaTTS van nul af aan opzet, compileert en distribueert.

## Systeemvereisten

### Ondersteunde OS
- **Windows 10 / 11** (64-bit)

### Vereiste Software

Installeer deze in volgorde:

#### 1. Rust & Cargo
- **Versie:** 1.98.1 of hoger
- **Download:** https://rustup.rs/
- **Installatie:** Voer het `.exe` uit en volg de wizard (standaard instellingen OK)
- **Verificatie:**
  ```bash
  rustc --version
  cargo --version
  ```

#### 2. Node.js & npm
- **Versie:** Node 22.x LTS of hoger (npm 10.x)
- **Download:** https://nodejs.org/ (kies LTS)
- **Installatie:** Standaard wizard
- **Verificatie:**
  ```bash
  node --version
  npm --version
  ```

#### 3. Python
- **Versie:** 3.11 of hoger
- **Download:** https://www.python.org/downloads/
- **Installatie:** ✅ **Zorg ervoor "Add python.exe to PATH" aan te vinken**
- **Verificatie:**
  ```bash
  python --version
  ```

#### 4. Git (optioneel, maar aangeraden)
- **Download:** https://git-scm.com/download/win
- **Installatie:** Standaard wizard

## NovaTTS Klonen & Opzetten

### Stap 1: Repository klonen
```bash
git clone <REPO_URL> NovaTTS
cd NovaTTS
```

*Nog geen publieke repo? Dan kan je de map handmatig kopieëren.*

### Stap 2: Afhankelijkheden installeren

#### Backend (Python)
```bash
cd backend
python -m venv .venv
# Activeer de virtual environment:
.venv\Scripts\activate
# Installeer requirements
pip install -r requirements.txt
pip install -e .
```

#### GUI (Node/Tauri)
```bash
# Terug in de root
cd ..
npm install
```

Dit installeert npm-modules in root (`node_modules/`) en in `gui/` (workspace setup). De Tauri CLI wordt gehoist naar de root.

### Stap 3: Qwen3-TTS model downloaden (optioneel voor dev)

Als je audio-generatie wilt testen:

```bash
cd backend
python setup_qwen.py --variant 1.7b-customvoice
```

Dit downloadt Qwen3-TTS GGUF-modellen van HuggingFace (~2.3 GB). *Pas het pad `setup_qwen.py` aan als je modellen elders wilt.*

## Développement & Debugging

### GUI dev-server (frontend alleen, geen backend)
```bash
npm run dev
# Opent Vite dev server op http://localhost:1420
```

### Backend dev (Python API server)
```bash
cd backend
.venv\Scripts\activate
python -m novatts.main
# Luistert op http://127.0.0.1:8765 standaard
```

### Volledige Tauri dev (GUI + backend integratie)
```bash
npm run dev-tauri
# Opent een Tauri-venster met Svelte frontend, hot reload
```

## Compilatie & Installer

### Build GUI + Installer (NSIS)
```bash
npm run build-tauri
```

**Dit doet:**
1. Rust-deps compileren (eerste keer: ~2-5 min)
2. Svelte frontend bundelen (`gui/dist/`)
3. Tauri-exe produceren (`gui/src-tauri/target/release/novatts-gui.exe`)
4. NSIS-installer genereren: `gui/src-tauri/target/release/bundle/nsis/NovaTTS_2.0.0_x64-setup.exe`

**Output:** NSIS-installer (~759 MB, bevat GUI + backend-exe + data)

### Build Backend (optioneel, als je een standalone backend exe wilt)
```bash
cd backend
pip install pyinstaller
pyinstaller Novabackend.spec
# Output: backend/dist/novatts-backend.exe
```

## Probleemoplossing

### Fout: "Couldn't recognize the current folder as a Tauri project"
**Oorzaak:** Je staat in de verkeerde map.
- Zorg dat je in de **repository root** staat (`NovaTTS/`)
- Tauri zoekt `tauri.conf.json` in `gui/src-tauri/`

### Fout: "target directory already exists"
```bash
cargo clean
rm -r gui/src-tauri/target
npm run build-tauri
```

### Fout: Rust compiler wil niet compileren
- Controleer: `rustc --version` (1.98.1+)
- Update: `rustup update`

### Fout: npm zegt "ERESOLVE unable to resolve dependency tree"
```bash
npm install --legacy-peer-deps
```

### Fout: NSIS downloads / makensis hangt
Dit kan enkele minuten duren (normaal). Als het langer dan 10 min hangt:
```bash
# Kill het proces:
taskkill /IM makensis.exe /F
# Opnieuw proberen:
npm run build-tauri
```

## Distributie

Na een succesvol build:

### Standalone Installer
- **Bestand:** `gui/src-tauri/target/release/bundle/nsis/NovaTTS_2.0.0_x64-setup.exe`
- **Grootte:** ~759 MB (bevat alles: GUI, backend, data)
- **Installatie:** Gebruikers draaien dit .exe → Windows installer start

### Portable (optioneel)
```bash
# Zip de exe + runtime:
$exe = "gui/src-tauri/target/release/novatts-gui.exe"
# Zet frontend + backend naast elkaar
# Distribueer als ZIP
```

## Environment & Configuratie

### Backend-instellingen
- **Bestand:** `backend/.env` (wordt gelezen in `novatts.config.Settings`)
- **Voorbeeld:** `backend/.env.example`
- **Belangrijke vars:**
  - `NOVATTS_HOST`, `NOVATTS_PORT` — API luister-adres
  - `NOVATTS_QWEN_URL` — Qwen3-TTS server (default: `http://127.0.0.1:8080`)
  - `NOVATTS_QWEN_BIN`, `NOVATTS_QWEN_MODEL` — Paden naar TTS-binary & model

### Qwen3-TTS Server (optioneel)
Als je lokale TTS wilt:
```bash
cd D:\Projects\qwentts.cpp\build\Release
.\tts-server.exe --model "E:\LLM's\Qwen3TTS\qwen-talker-1.7b-base-Q8_0.gguf" \
                  --codec "E:\LLM's\Qwen3TTS\qwen-tokenizer-12hz-Q8_0.gguf" \
                  --port 8080
```

## Mappen & Structuur

```
NovaTTS/
├── backend/                 # Python API + TTS backend
│   ├── novatts/            # Python package
│   ├── tests/              # Unit tests
│   ├── requirements.txt    # Python deps
│   ├── .env.example        # Config template
│   └── .venv/              # Virtual env (git-ignored)
├── gui/                     # Svelte/Tauri GUI
│   ├── src/                # Svelte components
│   ├── src-tauri/          # Tauri Rust backend (bundler config)
│   ├── package.json        # npm deps
│   └── node_modules/       # (git-ignored)
├── data/                    # Game configs, audio cache
│   ├── games/              # Per-game speaker.json
│   └── cache/              # Generated audio (git-ignored)
├── docs/                    # Documentatie
├── package.json            # Root workspace (npm)
└── Makefile                # Build commands
```

## Build-commands (Makefile)

```bash
make setup          # Installeer alles
make dev            # Svelte dev-server
make dev-tauri      # Tauri dev (GUI + backend)
make build-tauri    # Compile installer
make lint           # Linters draaien
make clean          # Opschonen (target/, dist/, cache)
```

## Volgende Stappen

1. **Controleer alles werkt:** `npm run build-tauri`
2. **Test de installer:** Voer `NovaTTS_2.0.0_x64-setup.exe` uit op een schone VM
3. **Configureer versies:**
   - Update `gui/src-tauri/tauri.conf.json` voor andere versie
   - Update `backend/novatts/__init__.py` `__version__`
4. **Zet GitHub Actions in (optioneel)** om installers te auto-bouwen op elke push

## Vragen?

Zie `README.md` voor project-overzicht, of check `backend/` / `gui/` voor specifieke build-notes.

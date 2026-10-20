@echo off
setlocal DisableDelayedExpansion
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "CARGOBIN=%USERPROFILE%\.cargo\bin"
set "PATH=%CARGOBIN%;%PATH%"

set "MODE=min"
if /I "%~1"=="--hidden" set "MODE=hidden"
if /I "%~1"=="-h" set "MODE=hidden"
if /I "%~1"=="--min" set "MODE=min"
if /I "%~1"=="--visible" set "MODE=visible"
if /I "%~1"=="--show" set "MODE=visible"
if /I "%~1"=="--repair" goto :repair
if /I "%~1"=="/?" goto :help
if /I "%~1"=="--help" goto :help

REM -- venv self-heal: if venv python is broken (moved/copied), run setup.ps1 --
if not exist "%ROOT%\backend\.venv\Scripts\python.exe" goto :need_setup
"%ROOT%\backend\.venv\Scripts\python.exe" --version >nul 2>&1
if errorlevel 1 goto :need_setup
"%ROOT%\backend\.venv\Scripts\python.exe" -m pip --version >nul 2>&1
if errorlevel 1 goto :need_setup
goto :pick_py

:need_setup
echo [NovaTTS] Venv onbruikbaar of verplaatst - setup wordt gedraaid...
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\setup.ps1"
if errorlevel 1 (
  echo [NovaTTS] setup.ps1 faalde - installeer handmatig: py -3.11 -m venv backend\.venv
  pause & exit /b 1
)

:pick_py
REM pick python - prefer .venv, then venv, then system python
set "PY="
if exist "%ROOT%\backend\.venv\Scripts\python.exe" set "PY=%ROOT%\backend\.venv\Scripts\python.exe"
if not defined PY if exist "%ROOT%\backend\venv\Scripts\python.exe" set "PY=%ROOT%\backend\venv\Scripts\python.exe"
if not defined PY set "PY=python"

REM -- ensure node_modules exist for gui build --
REM npm workspaces hoist naar de repo-root: gui/node_modules hoeft niet te
REM bestaan, zolang er maar een werkende vite in gui/ of in de root staat.
set "HAVE_VITE=0"
if exist "%ROOT%\gui\node_modules\.bin\vite.cmd" set "HAVE_VITE=1"
if exist "%ROOT%\node_modules\.bin\vite.cmd" set "HAVE_VITE=1"
if "%HAVE_VITE%"=="0" (
  echo [NovaTTS] npm dependencies ontbreken - npm install wordt gedraaid...
  if exist "%ROOT%\gui" (
    pushd "%ROOT%\gui" 2>nul && npm install --no-audit --no-fund 1>nul 2>&1 && popd
  ) else (
    npm install --no-audit --no-fund 1>nul 2>&1
  )
)
REM -- check vite build exists --
if not exist "%ROOT%\gui\dist\index.html" (
  echo [NovaTTS] gui/dist ontbreekt - vite build wordt gedraaid...
  pushd "%ROOT%\gui" 2>nul && npm run build 1>nul 2>&1 && popd
)

REM idempotent: kill stale
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING" 2^>nul') do (
  echo Stopping stale backend pid %%a ...
  taskkill /PID %%a /F >nul 2>nul
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080" ^| findstr "LISTENING" 2^>nul') do (
  echo Stopping stale qwen pid %%a ...
  taskkill /PID %%a /F >nul 2>nul
)
taskkill /F /IM tts-server.exe >nul 2>nul

echo [1/2] Backend (http://127.0.0.1:8765) - autostart Qwen via backend/.env (AUTOSTART=1) ...

REM /c, not /k: the console window belongs to the backend and must close
REM with it. With /k the window lingers after the backend exits.
REM Only --visible opens a console; every other mode stays windowless and
REM logs to backend.log / gui.log, because the app reports its own state.
REM
REM PADMETHAKEJES: zet de doelpaden EERST in variabelen en gebruik dan
REM alleen nog %VAR% in de start-regels. Twee lesjes, allebei getest in een
REM pad met haakjes (C:\Program Files (x86)\NovaTTS):
REM   1. Een directe "%ROOT%\..." in de start-regel werkt alleen als het pad
REM      tussen quotes staat. De ""path"-idioom van cmd /c zet %PY% juist
REM      BUITEN quotes, en dan leest cmd de ) van (x86) als blok-einde:
REM      "\NovaTTS\backend..." was unexpected at this time.
REM   2. Daarom staan de start-regels op ENKELE regels in een if, niet in een
REM      ( ... )-blok. Op een losse regel is een ) in een uitgebreide
REM      variabele onschadelijk. Getest: backend + GUI draaien in zo'n pad.
set "BE_DIR=%ROOT%\backend"
set "GUI_DIR=%ROOT%\gui"
set "BE_LOG=%ROOT%\backend.log"
set "GUI_LOG=%ROOT%\gui.log"
if "%MODE%"=="visible" start "NovaTTS-backend" cmd /c ""%PY%" "%BE_DIR%\run.py""
if not "%MODE%"=="visible" start "" /B cmd /c ""%PY%" "%BE_DIR%\run.py" > "%BE_LOG%" 2>&1"

REM brief wait for backend to bind port 8765
timeout /t 2 /nobreak >nul 2>nul

echo [2/2] Tauri GUI ...

REM -- Check of @tauri-apps/cli beschikbaar is (workspace hoist: root of gui node_modules) --
set "TAURI_READY=0"
if exist "%ROOT%\gui\node_modules\.bin\tauri.cmd" set "TAURI_READY=1"
if exist "%ROOT%\node_modules\.bin\tauri.cmd" set "TAURI_READY=1"

if "%TAURI_READY%"=="0" (
  echo   @tauri-apps/cli niet gevonden - npm install...
  if exist "%ROOT%\gui" (
    pushd "%ROOT%\gui" 2>nul && npm install --no-audit --no-fund 1>nul 2>&1 && popd
  ) else (
    npm install --no-audit --no-fund 1>nul 2>&1
  )
  if exist "%ROOT%\gui\node_modules\.bin\tauri.cmd" set "TAURI_READY=1"
  if exist "%ROOT%\node_modules\.bin\tauri.cmd" set "TAURI_READY=1"
)

set "GUI_CMD=npx tauri dev"
if "%TAURI_READY%"=="0" (
  set "GUI_CMD=npm run dev"
  set "NO_TAURI=1"
)

REM Ook de GUI-start op enkele regels (zelfde reden als hierboven); de cwd
REM moet gui/ zijn voor npx tauri, dus hier wel een cd /d - maar dan via de
REM gequote variabele %GUI_DIR%.
if "%MODE%"=="visible" start "NovaTTS-gui" cmd /c "cd /d "%GUI_DIR%" && %GUI_CMD%"
if not "%MODE%"=="visible" start "" /B cmd /c "cd /d "%GUI_DIR%" && %GUI_CMD% > "%GUI_LOG%" 2>&1"

echo.
echo Backend: http://127.0.0.1:8765/health  ^|  GUI: Tauri window of http://localhost:1420
echo Logs:    backend.log  ^|  gui.log
echo Modes:   start_all.cmd [--min^| --visible ^| --hidden ^| --repair]  default=--min ^(geen vensters^)
echo Repair:  start_all.cmd --repair  ^(of setup.ps1 -Force^)
echo Qwen:    autostart + auto-import Samples_Clone ^(bg, ~1-2 min^). Dashboard toont progress.
echo Sluiten: het NovaTTS-venster sluiten stopt backend + Qwen mee.
echo Alleen bij een crash: stop_all.cmd
if defined NO_TAURI if not "%MODE%"=="hidden" (
  echo.
  echo Tauri CLI ontbreekt - de GUI draait nu als browserpagina op http://localhost:1420
  pause
)
exit /b 0

:repair
echo [NovaTTS] Repair - venv + deps opnieuw opbouwen...
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\setup.ps1" -Force
pause
exit /b 0

:help
echo Gebruik: start_all.cmd [--min ^| --visible ^| --hidden ^| --repair]
echo   --min      ^(default^) geen console-vensters; logs naar backend.log / gui.log
echo   --hidden   als --min, maar zonder pauze-klaarmelding
echo   --visible  console-vensters zichtbaar ^(debuggen^)
echo   --repair   force rebuild venv + npm (na verhuizing)
exit /b 0

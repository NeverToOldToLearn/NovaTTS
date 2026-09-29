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
echo [NovaTTS] Venv onbruikbaar of verplaatst — setup wordt gedraaid...
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\setup.ps1"
if errorlevel 1 (
  echo [NovaTTS] setup.ps1 faalde — installeer handmatig: py -3.11 -m venv backend\.venv
  pause & exit /b 1
)

:pick_py
REM pick python - prefer .venv, then venv, then system python
set "PY="
if exist "%ROOT%\backend\.venv\Scripts\python.exe" set "PY=%ROOT%\backend\.venv\Scripts\python.exe"
if not defined PY if exist "%ROOT%\backend\venv\Scripts\python.exe" set "PY=%ROOT%\backend\venv\Scripts\python.exe"
if not defined PY set "PY=python"

REM -- ensure the workspace install exists for the gui build --
REM Test a real binary, not a directory name. This project is an npm
REM workspace -- the root package.json lists "gui" under "workspaces" --
REM so npm hoists every dependency to ROOT\node_modules and never populates
REM gui\node_modules. On a fresh clone that directory simply does not exist.
REM
REM The old test was `if not exist "%ROOT%\gui\node_modules"`, so it fired on
REM EVERY start, announced a missing install, and then ran an install that
REM reported "up to date" and changed nothing. Measured 2026-09-29: the
REM message appeared while ROOT\node_modules\.bin held tauri, vite,
REM svelte-check and tsc. The script contradicted itself, because the tauri
REM check further down already looks in both places.
REM
REM The install itself stays in %ROOT%\gui on purpose: from there npm walks up
REM and finds the workspace root, so this one location is correct both when
REM gui is a workspace member and when it is not.
set "NODE_READY=0"
if exist "%ROOT%\node_modules\.bin\vite.cmd" set "NODE_READY=1"
if exist "%ROOT%\gui\node_modules\.bin\vite.cmd" set "NODE_READY=1"
if "%NODE_READY%"=="0" (
  echo [NovaTTS] node_modules ontbreekt — npm install wordt gedraaid...
  pushd "%ROOT%\gui" 2>nul && npm install --no-audit --no-fund 1>nul 2>&1 && popd
  if not exist "%ROOT%\node_modules\.bin\vite.cmd" if not exist "%ROOT%\gui\node_modules\.bin\vite.cmd" (
    echo [NovaTTS] LET OP: npm install slaagde niet of is incompleet — de GUI kan niet bouwen.
    echo          Controleer node/npm, of draai handmatig: cd gui ^&^& npm install
  )
)
REM -- check vite build exists --
if not exist "%ROOT%\gui\dist\index.html" (
  echo [NovaTTS] gui/dist ontbreekt — vite build wordt gedraaid...
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

REM -- hook config out of .env, zodat de melding hieronder de waarheid vertelt --
REM Niet hardcoden: NOVATTS_HOOK_PORT is wijzigbaar vanuit de GUI (F6).
set "HOOK_PORT=6677"
set "HOOK_MODE=both"
if exist "%ROOT%\backend\.env" (
  for /f "usebackq tokens=1,* delims==" %%a in ("%ROOT%\backend\.env") do (
    call :read_hook_var "%%a" "%%b"
  )
)
goto :after_hook_var

REM Strip spaces from key and value. Without this, a hand-edited line like
REM "NOVATTS_HOOK_PORT = 7300" is silently ignored here -- while the backend
REM itself DOES honour it, because pydantic-settings trims. That mismatch is
REM worse than not reading it at all: the log below would then name a port the
REM server is not using. (Tabs are not stripped; a tab-indented key is not a
REM shape anybody writes by hand.)
:read_hook_var
set "HK=%~1"
set "HV=%~2"
set "HK=%HK: =%"
set "HV=%HV: =%"
if /I "%HK%"=="NOVATTS_HOOK_PORT" set "HOOK_PORT=%HV%"
if /I "%HK%"=="NOVATTS_HOOK_MODE" set "HOOK_MODE=%HV%"
exit /b
:after_hook_var

REM -- 6677 wordt hier bewust NIET gedood. Het is NovaTTS' eigen hook-poort, en
REM    "dood alles wat erop luistert" zou ook een proces van een vorig
REM    NovaTTS-instantie kunnen zijn. Maar een bezette poort blokkeert het
REM    binden stilletjes, dus we melden het met het pid en wat te doen.
set "HOOK_TAKEN="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%HOOK_PORT%" ^| findstr "LISTENING" 2^>nul') do (
  if not "%%a"=="0" if not "%%a"=="4" set "HOOK_TAKEN=%%a"
)
if defined HOOK_TAKEN (
  echo Let op: poort %HOOK_PORT% is al in gebruik door pid %HOOK_TAKEN% .
  echo          De nieuwe backend kan daar niet op binden -- de hook blijft dan stille.
  echo          Los dit op met: stop_all.cmd
)

echo [1/2] Backend (http://127.0.0.1:8765) - autostart Qwen via backend/.env (NOVATTS_QWEN_AUTOSTART=1) ...

if "%MODE%"=="hidden" (
  echo   Mode: hidden ^(geen vensters^) - logs in .log
  start "" /B cmd /c "cd /d "%ROOT%\backend" && "%PY%" run.py > "%ROOT%\backend.log" 2>&1"
) else if "%MODE%"=="visible" (
  start "NovaTTS-backend" cmd /k "cd /d "%ROOT%\backend" && "%PY%" run.py"
) else (
  start "NovaTTS-backend" /MIN cmd /k "cd /d "%ROOT%\backend" && "%PY%" run.py"
)

REM brief wait for backend to bind port 8765
timeout /t 2 /nobreak >nul 2>nul

REM -- Zeg wat de hook doet. Anders weet een gebruiker niet dat hij nog iets
REM    moet instellen: LunaTranslator is een extern programma dat je zelf
REM    aan de game moet hangen, en daar staat niets anders op de weg.
if /I "%HOOK_MODE%"=="clipboard" (
  echo   Hook: uit ^(hook_mode=clipboard^) -- alleen de RenPy-clipboard-route.
) else (
  REM No ^ before the pipes HERE, unlike the for /f line above. Inside a
  REM parenthesised block cmd already treats | as a pipe, so "escaping" it
  REM passes a literal ^| to netstat, the whole line runs as ONE command, and
  REM the exit code is always 0 -- i.e. this test could never report "not yet
  REM listening". Measured: with an empty result the ^| form returns 0, the
  REM plain form returns 1.
  netstat -ano | findstr ":%HOOK_PORT%" | findstr "LISTENING" >nul 2>&1
  if errorlevel 1 (
    echo   Hook: poort %HOOK_PORT% luistert nog niet -- de backend start nog.
  ) else (
    echo   Hook: luistert op ws://127.0.0.1:%HOOK_PORT% ^(%HOOK_MODE%^) en wacht op LunaTranslator.
    echo         LunaTranslator: Extensions -^> Add -^> textractor_websocket_x64.xdll -^> bovenstaand adres
  )
)

echo [2/2] Tauri GUI ...

REM -- Check of @tauri-apps/cli beschikbaar is (workspace hoist: root of gui node_modules) --
set "TAURI_READY=0"
if exist "%ROOT%\gui\node_modules\.bin\tauri.cmd" set "TAURI_READY=1"
if exist "%ROOT%\node_modules\.bin\tauri.cmd" set "TAURI_READY=1"

if "%TAURI_READY%"=="0" (
  echo   @tauri-apps/cli niet gevonden — npm install...
  if exist "%ROOT%\gui" (
    pushd "%ROOT%\gui" 2>nul && npm install --no-audit --no-fund 1>nul 2>&1 && popd
  ) else (
    npm install --no-audit --no-fund 1>nul 2>&1
  )
  if exist "%ROOT%\gui\node_modules\.bin\tauri.cmd" set "TAURI_READY=1"
  if exist "%ROOT%\node_modules\.bin\tauri.cmd" set "TAURI_READY=1"
)

if "%TAURI_READY%"=="0" (
  echo   Tauri CLI niet beschikbaar — browser dev fallback op http://localhost:1420
  if "%MODE%"=="hidden" (
    start "" /B cmd /c "cd /d "%ROOT%\gui" && npm run dev > "%ROOT%\gui.log" 2>&1"
  ) else if "%MODE%"=="visible" (
    start "NovaTTS-gui" cmd /k "cd /d "%ROOT%\gui" && npm run dev"
  ) else (
    start "NovaTTS-gui" /MIN cmd /k "cd /d "%ROOT%\gui" && npm run dev"
  )
) else (
  REM npx tauri dev opent zelf al een window; backend blijft /MIN of /B
  if "%MODE%"=="hidden" (
    echo   hidden: tauri wordt normaal gestart ^(eigen window wel zichtbaar^), backend blijft verborgen
  )
  start "NovaTTS-gui" cmd /k "cd /d "%ROOT%\gui" && npx tauri dev"
)

echo.
echo Backend: http://127.0.0.1:8765/health  ^|  GUI: Tauri window of http://localhost:1420
echo Modes: start_all.cmd [--min^| --visible ^| --hidden ^| --repair]  default=--min
echo Repair: start_all.cmd --repair  (of setup.ps1 -Force)
echo Qwen: autostart + auto-import Samples_Clone ^(bg, ~1-2 min^). Dashboard toont progress.
echo Hook: ws://127.0.0.1:%HOOK_PORT% ^(hook_mode=%HOOK_MODE%^) -- de GUI toont in de Hook-kaart
echo        of er een client is en of er al een regel binnen is.
echo Sluiten: stop_all.cmd  ^(anders blijft backend clip-pollen^).
if not "%MODE%"=="hidden" pause
exit /b 0

:repair
echo [NovaTTS] Repair — venv + deps opnieuw opbouwen...
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\setup.ps1" -Force
pause
exit /b 0

:help
echo Gebruik: start_all.cmd [--min ^| --visible ^| --hidden ^| --repair]
echo   --min      ^(default^) vensters geminimaliseerd
echo   --visible  vensters normaal zichtbaar
echo   --hidden   backend/gui zonder venster ^(logs naar backend.log / gui.log^)
echo   --repair   force rebuild venv + npm (na verhuizing)
exit /b 0

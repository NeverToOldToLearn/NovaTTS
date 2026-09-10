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

REM -- ensure node_modules exist for gui build --
if not exist "%ROOT%\gui\node_modules" (
  echo [NovaTTS] gui/node_modules ontbreekt — npm install wordt gedraaid...
  pushd "%ROOT%\gui" 2>nul && npm install --no-audit --no-fund 1>nul 2>&1 && popd
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

echo [1/2] Backend (http://127.0.0.1:8765) - autostart Qwen via backend/.env (AUTOSTART=1) ...

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

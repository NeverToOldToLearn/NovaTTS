@echo off
REM Stops everything NovaTTS starts: GUI, backend (:8765) and Qwen (:8081).
REM Closing the main GUI window already does this, but a crash or a forced
REM kill leaves the backend polling the clipboard - use this then.
setlocal
set "BACKEND_PORT=8765"

echo Stopping NovaTTS ...

REM 1) Graceful: the backend clears its audio cache and raw clipboard log
REM    on the way out. 8765 is the NovaTTS backend (8081 is Qwen).
powershell -NoProfile -Command "try { Invoke-RestMethod http://127.0.0.1:%BACKEND_PORT%/shutdown -Method Post -TimeoutSec 3 2>$null | Out-Null; Write-Host '  backend shutdown ok' } catch { Write-Host '  backend shutdown skipped (not running)' }" 2>nul
timeout /t 2 /nobreak >nul 2>nul

REM 2) Force-kill whatever still holds the backend port, plus its tree
REM    (/T also takes down the tts-server.exe it autostarted).
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%BACKEND_PORT%" ^| findstr "LISTENING" 2^>nul') do (
  echo   killing backend pid %%a
  taskkill /PID %%a /T /F >nul 2>nul
)

REM 3) Qwen, in case the backend died before cleaning up after it.
taskkill /F /IM tts-server.exe >nul 2>nul

REM 4) A GUI that never got to run its own cleanup.
taskkill /F /IM novatts-gui.exe >nul 2>nul

echo Done.
timeout /t 1 /nobreak >nul 2>nul
endlocal

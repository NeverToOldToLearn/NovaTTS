@echo off
echo Stopping NovaTTS ...
REM Try graceful shutdown via API (short timeout to avoid hang)
powershell -NoProfile -Command "try { Invoke-RestMethod http://127.0.0.1:8081/shutdown -Method Post -TimeoutSec 3 2>$null | Out-Null; Write-Host 'backend shutdown' } catch { Write-Host 'backend shutdown (skipped)' }" 2>nul
timeout /t 2 /nobreak >nul 2>nul
REM Force kill anything on port 8765
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8081" ^| findstr "LISTENING" 2^>nul') do (
  echo   killing backend pid %%a
  taskkill /PID %%a /F >nul 2>nul
)
REM Kill tts-server
taskkill /F /IM tts-server.exe >nul 2>nul
echo Done.
timeout /t 1 /nobreak >nul 2>nul

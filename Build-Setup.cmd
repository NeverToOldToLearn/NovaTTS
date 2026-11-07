@echo off
rem Eén commando voor een complete NovaTTS-setup:
rem   backend-exe  ->  Tauri/GUI release-build  ->  Inno Setup installer
rem Resultaat: dist-installer\NovaTTS-Setup-2.5.0d.exe
setlocal
title NovaTTS setup bouwen

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0.dev\Build-2.5.0d.ps1" -Rebuild %*
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo Build mislukt ^(exit %RC%^). Zie .build\2.5.0d\log.txt
) else (
  echo Klaar: dist-installer\NovaTTS-Setup-2.5.0d.exe
)
pause
exit /b %RC%

#Requires -Version 5.1
param([switch]$Force)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT = $PSScriptRoot
if (-not $ROOT) { $ROOT = (Get-Location).Path }

Write-Host "[NovaTTS] Install — one-click setup" -ForegroundColor Cyan
Write-Host "  Root: $ROOT" -ForegroundColor DarkGray

$extra = @()
if ($Force) { $extra += "-Force" }
$extra += "-Shortcuts"

$setup = Join-Path $ROOT "setup.ps1"
if (-not (Test-Path $setup)) { Write-Host "[NovaTTS] setup.ps1 niet gevonden" -ForegroundColor Red; pause; exit 1 }

& $setup @extra
if ($LASTEXITCODE -ne 0) { Write-Host "[NovaTTS] setup faalde — zie output hierboven" -ForegroundColor Red; pause; exit $LASTEXITCODE }

Write-Host "" ; Write-Host "[NovaTTS] Klaar!" -ForegroundColor Green
Write-Host "  Start:  .\start_all.cmd [--min|--visible|--hidden]" -ForegroundColor Green
Write-Host "  Repair: .\start_all.cmd --repair  (of .\setup.ps1 -Force)" -ForegroundColor DarkGray
Write-Host "  Stop:   .\stop_all.cmd" -ForegroundColor DarkGray
Write-Host "  Snelkoppelingen: Start Menu\NovaTTS + Desktop\NovaTTS.lnk" -ForegroundColor DarkGray
Write-Host ""
pause

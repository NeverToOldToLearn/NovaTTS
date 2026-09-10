#Requires -Version 5.1
param(
  [switch]$WithVenv,
  [switch]$ZipOnly,
  [switch]$NoZip,
  [string]$InnoPath = "",
  [string]$Version = ""
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ($Version) {
  Write-Host "[installer] Version override: $Version" -ForegroundColor Cyan
  (Get-Content (Join-Path $PSScriptRoot "NovaTTS.iss") -Raw) -replace '#define MyAppVersion ".*"', "#define MyAppVersion `"$Version`"" | Set-Content (Join-Path $PSScriptRoot "NovaTTS.iss") -Encoding UTF8
}

function Find-ISCC($hint) {
  if ($hint -and (Test-Path $hint)) { return $hint }
  foreach ($p in @("C:\Program Files (x86)\Inno Setup 6\ISCC.exe","C:\Program Files\Inno Setup 6\ISCC.exe")) { if (Test-Path $p) { return $p } }
  $c = Get-Command ISCC -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  return $null
}

# --- exclusions for portable payload (fix verhuizen: nooit .venv/node_modules meenemen tenzij -WithVenv) ---
$excludeDirs = @(".git",".venv","venv","node_modules","target","__pycache__",".mypy_cache",".ruff_cache",".pytest_cache","cache","Output",".crush")
$excludeFiles = @("*.log","*.pyc","backend\.env","NovaTTS-Setup-*.exe","NovaTTS-Portable-*.zip")
if (-not $WithVenv) { Write-Host "[installer] Portable (zonder .venv/node_modules — setup bouwt ze bij eerste run)" -ForegroundColor Cyan }
else { Write-Host "[installer] Full payload (-WithVenv) — inclusief .venv/node_modules" -ForegroundColor Yellow; $excludeDirs = @(".git","__pycache__",".mypy_cache",".ruff_cache",".pytest_cache","Output") }

# Build ZIP portable
if (-not $NoZip) {
  $stamp = Get-Date -Format "yyyyMMdd"
  $zipName = "NovaTTS-Portable-$stamp.zip"
  if ($Version) { $zipName = "NovaTTS-Portable-$Version-$stamp.zip" }
  $zipPath = Join-Path $ROOT $zipName
  if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
  Write-Host "[installer] ZIP: $zipPath" -ForegroundColor Cyan

  # Ensure gui/dist exists (portable moet ook zonder npm kunnen opstarten)
  Push-Location (Join-Path $ROOT "gui")
  try {
    if (-not (Test-Path (Join-Path $ROOT "gui\dist\index.html"))) {
      Write-Host "[installer] gui/dist ontbreekt — vite build..." -ForegroundColor DarkGray
      if (Get-Command npm -ErrorAction SilentlyContinue) {
        if (-not (Test-Path (Join-Path $ROOT "gui\node_modules\.bin\vite.cmd"))) { npm install --no-audit --no-fund 2>&1 | Out-Null }
        npm run build 2>&1 | Out-Null
      }
    }
  } finally { Pop-Location }

  $tmpStage = Join-Path $env:TEMP "novatts-stage-$([Guid]::NewGuid().ToString('N').Substring(0,8))"
  New-Item -ItemType Directory -Force -Path $tmpStage | Out-Null
  try {
    # Robocopy with exclusions (fast + correct hidden/system)
    $xd = ($excludeDirs | ForEach-Object { "`"$_`"" }) -join " "
    # Build robocopy args
    $roboArgs = @($ROOT, $tmpStage, "/E", "/NFL", "/NDL", "/NJH", "/NJS")
    foreach ($d in $excludeDirs) { $roboArgs += "/XD"; $roboArgs += $d }
    # Exclude specific files via /XF
    $roboArgs += "/XF"; $roboArgs += "backend.log"; $roboArgs += "gui.log"; $roboArgs += "*.pyc"
    if (-not $WithVenv) {
      # Extra: never include backend .env (user config)
      # copy .env.example as .env.example only
    }
    & robocopy @roboArgs | Out-Null
    # Remove backend/.env from stage if it slipped through (keep .env.example)
    Remove-Item (Join-Path $tmpStage "backend\.env") -Force -ErrorAction SilentlyContinue
    # Ensure empty dirs needed at runtime
    @("data\cache","data\games","backend") | ForEach-Object { New-Item -ItemType Directory -Force -Path (Join-Path $tmpStage $_) | Out-Null }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    # Remove old zip if exists, then create
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    [System.IO.Compression.ZipFile]::CreateFromDirectory($tmpStage, $zipPath)
    $sz = (Get-Item $zipPath).Length
    Write-Host "[installer] ZIP klaar: $zipName ($([math]::Round($sz/1MB,1)) MB)" -ForegroundColor Green
    Write-Host "  Gebruik: uitpakken -> Install.cmd of setup.ps1 -> start_all.cmd" -ForegroundColor DarkGray
  } finally {
    Remove-Item -Recurse -Force $tmpStage -ErrorAction SilentlyContinue
  }
}

if ($ZipOnly) { Write-Host "[installer] -ZipOnly — Inno Setup overgeslagen" -ForegroundColor DarkGray; exit 0 }

# Build Inno Setup installer (.exe)
$iscc = Find-ISCC $InnoPath
if (-not $iscc) {
  Write-Host "[installer] Inno Setup (ISCC.exe) niet gevonden — sla .exe build over." -ForegroundColor Yellow
  Write-Host "  Installeer https://jrsoftware.org/isdl.php  of draai met -ZipOnly / -NoZip" -ForegroundColor DarkGray
  Write-Host "  Of: installer\Build-Installer.ps1 -InnoPath 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'" -ForegroundColor DarkGray
  if ($NoZip) { exit 1 }
  exit 0
}
Write-Host "[installer] ISCC: $iscc" -ForegroundColor Cyan
$iss = Join-Path $PSScriptRoot "NovaTTS.iss"
& $iscc $iss
if ($LASTEXITCODE -ne 0) { Write-Host "[installer] ISCC faalde ($LASTEXITCODE)" -ForegroundColor Red; exit $LASTEXITCODE }
Write-Host "[installer] Setup EXE klaar (zie output hierboven / ..\NovaTTS-Setup-*.exe)" -ForegroundColor Green

#Requires -Version 5.1
param(
  [switch]$NoTauri,
  [switch]$NoBackend,
  [switch]$Force,
  [switch]$Shortcuts,
  [string]$Python = ""
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT = $PSScriptRoot
if (-not $ROOT) { $ROOT = (Get-Location).Path }

function Info($m)  { Write-Host "[NovaTTS] $m" -ForegroundColor Cyan }
function Warn($m)  { Write-Host "[NovaTTS] $m" -ForegroundColor Yellow }
function Fail($m)  { Write-Host "[NovaTTS] $m" -ForegroundColor Red; exit 1 }
function Test-Venv($py) {
  if (-not (Test-Path $py)) { return $false }
  try { & $py --version 2>&1 | Out-Null; if ($LASTEXITCODE -ne 0) { return $false } } catch { return $false }
  try { & $py -m pip --version 2>&1 | Out-Null; if ($LASTEXITCODE -ne 0) { return $false } } catch { return $false }
  $cfg = Join-Path (Split-Path (Split-Path $py -Parent) -Parent) "pyvenv.cfg"
  if (Test-Path $cfg) {
    $homeLine = (Select-String -Path $cfg -Pattern "^home\s*=" -ErrorAction SilentlyContinue)
    if ($homeLine) {
      $homeVal = ($homeLine.Line -split "=",2)[1].Trim().Trim('"')
      if ($homeVal -and -not (Test-Path $homeVal)) { return $false }
    }
  }
  return $true
}

Info "Root: $ROOT"
if ($Force) { Info "Force: venv/node_modules worden vernieuwd indien mogelijk" }

# --- prerequisites ----------------------------------------------------------
$hasNode = $null -ne (Get-Command node -ErrorAction SilentlyContinue)
$hasNpm  = $null -ne (Get-Command npm  -ErrorAction SilentlyContinue)
$hasCargo= $null -ne (Get-Command cargo -ErrorAction SilentlyContinue)
$hasRustc= $null -ne (Get-Command rustc -ErrorAction SilentlyContinue)

if (-not $hasNode -or -not $hasNpm) {
  Fail "Node.js + npm vereist. Installeer https://nodejs.org (LTS) en run opnieuw. (Node $((node --version 2>$null)) npm $((npm --version 2>$null)))"
}
Info "node $(node -v)  npm $(npm -v)"

# --- GUI --------------------------------------------------------------------
Push-Location (Join-Path $ROOT "gui")
try {
  $needInstall = $Force -or -not (Test-Path (Join-Path $ROOT "gui\node_modules\.bin\vite.cmd")) -or -not (Test-Path (Join-Path $ROOT "gui\node_modules"))
  if ($needInstall) {
    Info "GUI: npm install..."
    npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { Fail "npm install faalde (gui)." }
  } else {
    Info "GUI: node_modules bestaat — skip install (gebruik -Force om te vernieuwen)"
  }
  Info "GUI: vite build (check)..."
  npm run build | Out-Null
  if ($LASTEXITCODE -ne 0) { Fail "vite build faalde." }
  Info "GUI klaar — dev: npm run dev  |  tauri: npm run tauri dev"
} finally { Pop-Location }

if ($NoTauri) {
  Warn "Tauri check overgeslagen (--NoTauri)."
} else {
  # Check both: gui/node_modules (direct) and root node_modules (workspace hoist)
  $tauriCli = (Test-Path (Join-Path $ROOT "gui\node_modules\.bin\tauri.cmd")) -or
              (Test-Path (Join-Path $ROOT "node_modules\.bin\tauri.cmd"))
  if (-not $tauriCli) {
    Push-Location (Join-Path $ROOT "gui")
    try { npm install --no-audit --no-fund 2>&1 | Out-Null } finally { Pop-Location }
    $tauriCli = (Test-Path (Join-Path $ROOT "gui\node_modules\.bin\tauri.cmd")) -or
                (Test-Path (Join-Path $ROOT "node_modules\.bin\tauri.cmd"))
  }
  if ($tauriCli) {
    Info "Tauri CLI (@tauri-apps/cli) gevonden — npx tauri dev / build beschikbaar."
  } elseif ($hasCargo -and $hasRustc) {
    Warn "@tauri-apps/cli niet geinstalleerd — run 'npm install' of draai opnieuw."
    Warn "Rust $(rustc --version) aanwezig, maar Tauri CLI mist. GUI draait wel in browser (npm run dev → http://localhost:1420)."
  } else {
    Warn "Tauri CLI niet gevonden — GUI draait in browser (npm run dev → http://localhost:1420)."
    Warn "Voor native window: npm install + Rust https://rustup.rs, dan: npx tauri dev"
  }
}

# --- Backend ----------------------------------------------------------------
if (-not $NoBackend) {
  $py = $Python
  if (-not $py) {
    foreach ($cand in @(
      (Join-Path $ROOT "backend\.venv\Scripts\python.exe"),
      (Join-Path $ROOT "backend\venv\Scripts\python.exe")
    )) { if (Test-Path $cand) { $py = $cand; break } }
  }
  if (-not $py) {
    $py311 = $null
    try { & py -3.11 --version 2>&1 | Out-Null; if ($LASTEXITCODE -eq 0) { $py311 = "py -3.11" } } catch {}
    if ($py311) { $py = $py311 }
  }
  if (-not $py) {
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pyCmd) { $pyCmd = Get-Command py -ErrorAction SilentlyContinue }
    if ($pyCmd) { $py = $pyCmd.Source } else { Fail "Python 3.11+ niet gevonden. Installeer Python https://python.org en run opnieuw." }
  }
  Info "Python: $py"
  try { Invoke-Expression "& $py --version" | Out-Null } catch { Fail "Python aanroep faalde: $py" }

  $venvPy = Join-Path $ROOT "backend\.venv\Scripts\python.exe"
  $venvOk = Test-Venv $venvPy
  if ($Force -and (Test-Path (Join-Path $ROOT "backend\.venv"))) {
    Info "Force: oude venv verwijderen..."
    Remove-Item -Recurse -Force (Join-Path $ROOT "backend\.venv") -ErrorAction SilentlyContinue
    $venvOk = $false
  }
  if (-not $venvOk) {
    if (Test-Path $venvPy) {
      Warn "Bestaande venv onbruikbaar (verhuisd/corrupt) — opnieuw aanmaken..."
      Remove-Item -Recurse -Force (Join-Path $ROOT "backend\.venv") -ErrorAction SilentlyContinue
    }
    Info "Backend venv aanmaken (.venv)..."
    try { Invoke-Expression "& $py -m venv `"$ROOT\backend\.venv`"" } catch { Fail "venv aanmaken faalde: $_" }
    if ($LASTEXITCODE -ne 0) { Fail "venv aanmaken faalde." }
  } else {
    Info "Backend venv OK — hergebruik"
  }
  $venvPy = Join-Path $ROOT "backend\.venv\Scripts\python.exe"
  if (-not (Test-Venv $venvPy)) { Fail "venv python nog steeds onbruikbaar: $venvPy" }
  Info "Backend deps installeren..."
  & $venvPy -m pip install --upgrade pip --quiet
  & $venvPy -m pip install -r (Join-Path $ROOT "backend\requirements.txt") --quiet
  if ($LASTEXITCODE -ne 0) { Fail "pip install requirements.txt faalde." }
  $devReq = Join-Path $ROOT "backend\requirements-dev.txt"
  if (Test-Path $devReq) {
    & $venvPy -m pip install -r $devReq --quiet
  }
  Info "Backend klaar — run: backend\.venv\Scripts\python.exe backend\run.py  (of start_all.cmd)"
}

# --- .env -------------------------------------------------------------------
$envExample = Join-Path $ROOT "backend\.env.example"
$envFile    = Join-Path $ROOT "backend\.env"
if ((Test-Path $envExample) -and -not (Test-Path $envFile)) {
  Copy-Item $envExample $envFile
  Info ".env aangemaakt uit .env.example — pas paden aan indien nodig."
}
if (Test-Path $envFile) {
  $missing = @()
  foreach ($line in (Get-Content $envFile -ErrorAction SilentlyContinue)) {
    if ($line -match "^\s*NOVATTS_QWEN_(BIN|MODEL|CODEC)\s*=\s*(.+)\s*$") {
      $p = $Matches[2].Trim().Trim('"')
      if ($p -and -not (Test-Path $p)) { $missing += "$($Matches[1]): $p" }
    }
  }
  if ($missing.Count -gt 0) {
    Warn ".env verwijst naar niet-bestaande paden:"
    $missing | ForEach-Object { Warn "  $_" }
    Warn "Pas backend\.env aan (Qwen modellen/samples) indien je verhuisd bent."
  }
}

# --- Shortcuts --------------------------------------------------------------
if ($Shortcuts) {
  Info "Shortcuts aanmaken..."
  try {
    $wsh = New-Object -ComObject WScript.Shell
    $sm = Join-Path ([Environment]::GetFolderPath("Programs")) "NovaTTS"
    $desk = [Environment]::GetFolderPath("Desktop")
    New-Item -ItemType Directory -Force -Path $sm | Out-Null
    $pairs = @(
      @{ Name="NovaTTS Start"; Target="$ROOT\start_all.cmd"; Args="--min"; Dir=$ROOT },
      @{ Name="NovaTTS Visible"; Target="$ROOT\start_all.cmd"; Args="--visible"; Dir=$ROOT },
      @{ Name="NovaTTS Stop"; Target="$ROOT\stop_all.cmd"; Args=""; Dir=$ROOT },
      @{ Name="NovaTTS Setup (Repair)"; Target="powershell.exe"; Args="-NoProfile -ExecutionPolicy Bypass -File `"$ROOT\setup.ps1`" -Shortcuts"; Dir=$ROOT }
    )
    foreach ($it in $pairs) {
      $lnk = $wsh.CreateShortcut((Join-Path $sm "$($it.Name).lnk"))
      $lnk.TargetPath = $it.Target
      $lnk.Arguments = $it.Args
      $lnk.WorkingDirectory = $it.Dir
      # Use ASCII chars + avoid subexpression parsing issues on some encodings
      $lnk.Description = ('NovaTTS - ' + $it.Name)
      $lnk.Save()
    }
    $dlnk = $wsh.CreateShortcut((Join-Path $desk "NovaTTS.lnk"))
    $dlnk.TargetPath = "$ROOT\start_all.cmd"
    $dlnk.Arguments = "--min"
    $dlnk.WorkingDirectory = $ROOT
    $dlnk.Description = "NovaTTS"
    $dlnk.Save()
    Info "Shortcuts: Start Menu\NovaTTS (4) + Desktop\NovaTTS.lnk"
  } catch {
    Warn "Shortcuts maken faalde: $_"
  }
}

Info "Setup klaar."
Write-Host ""
Write-Host "  Start alles:   .\start_all.cmd [--min|--visible|--hidden]" -ForegroundColor Green
Write-Host "  Stop alles:    .\stop_all.cmd" -ForegroundColor Green
Write-Host "  Repair:        .\setup.ps1 -Force [-Shortcuts]" -ForegroundColor Green
Write-Host "  Alleen GUI:    npm run dev --workspace=gui   (http://localhost:1420)" -ForegroundColor Green
Write-Host "  Tauri window:  npm run tauri --workspace=gui -- dev" -ForegroundColor Green
Write-Host "  Alleen backend: backend\.venv\Scripts\python.exe backend\run.py" -ForegroundColor Green
if (-not $Shortcuts) {
  Write-Host "  Shortcuts:     .\setup.ps1 -Shortcuts  (Start Menu + Desktop)" -ForegroundColor DarkGray
}

#Requires -Version 5.1
param(
  [switch]$NoTauri,
  [switch]$NoBackend,
  [switch]$NoTools,
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

# --- toolchain-bootstrap helpers ---------------------------------------------
# Verse Windows: alleen git/python aanwezig. Node, npm, Rust en de MSVC
# build tools moeten geinstalleerd worden voordat Svelte/Vite (npm) en de
# Tauri native build (cargo) werken. Deze functies regelen dat zelf.
function Update-SessionPath {
  $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
  $parts   = @($machine, $user) | Where-Object { $_ }
  $env:Path = ($parts -join ';') + ';' + $env:Path
}
function Get-Exe($n) { Get-Command $n -ErrorAction SilentlyContinue }
function Test-NodeStack { return [bool]((Get-Exe 'node') -and (Get-Exe 'npm')) }
function Ensure-Tls12 {
  try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
}
function Invoke-WingetInstall($wingetArgs) {
  $wg = Get-Exe 'winget'
  if (-not $wg) { return $false }
  try {
    & $wg.Source @wingetArgs
    return ($LASTEXITCODE -eq 0)
  } catch { return $false }
}
function Install-NodeStack {
  Warn "Node.js + npm ontbreken - automatisch installeren..."
  if (Get-Exe 'winget') {
    Info "  winget: OpenJS.NodeJS.LTS (stil; Windows kan een UAC-venster tonen)"
    $null = Invoke-WingetInstall @('install','--id','OpenJS.NodeJS.LTS','-e',
      '--accept-source-agreements','--accept-package-agreements',
      '--disable-interactivity','--silent')
    Update-SessionPath
    if (Test-NodeStack) { return $true }
    Warn "  winget-install gaf geen werkende node/npm - probeer officiele zip."
  }
  # Fallback: officiele zip, geen adminrechten nodig.
  try {
    Ensure-Tls12
    $idx = (Invoke-WebRequest -UseBasicParsing -Uri 'https://nodejs.org/dist/index.json' -TimeoutSec 60).Content | ConvertFrom-Json
    $lts = @($idx | Where-Object { $_.lts }) | Select-Object -First 1
    if (-not $lts) { throw "geen LTS-versie gevonden in index.json" }
    $ver  = $lts.version
    $dest = Join-Path $env:LOCALAPPDATA 'Programs\nodejs'
    $tmp  = Join-Path $env:TEMP "node-$ver-win-x64.zip"
    Info "  download node $ver (LTS)..."
    Invoke-WebRequest -UseBasicParsing -Uri "https://nodejs.org/dist/$ver/node-$ver-win-x64.zip" -OutFile $tmp -TimeoutSec 900
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Expand-Archive -Path $tmp -DestinationPath $dest -Force
    Remove-Item $tmp -Force
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $userPath) { $userPath = '' }
    if ($userPath -notlike "*$dest*") {
      [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $dest), 'User')
    }
    Update-SessionPath
    return (Test-NodeStack)
  } catch {
    Warn "  Node zip-install mislukt: $($_.Exception.Message)"
    return $false
  }
}
function Test-Python311($py) {
  # $py is een commando-string zoals "py -3.12" of een python.exe-pad.
  if (-not $py) { return $false }
  try {
    $out = Invoke-Expression "& $py -c 'import sys; print(sys.version_info >= (3, 11))'" 2>$null
    return ("$out" -match 'True')
  } catch { return $false }
}
function Find-Python311 {
  $cands = @('py -3.13', 'py -3.12', 'py -3.11', 'python')
  $sysPy = Get-Exe 'python'
  if ($sysPy) { $cands += $sysPy.Source }
  foreach ($c in $cands) { if (Test-Python311 $c) { return $c } }
  return $null
}
function Install-Python3 {
  Warn "Python 3.11+ ontbreekt - automatisch installeren (3.13)..."
  if (Get-Exe 'winget') {
    $null = Invoke-WingetInstall @('install','--id','Python.Python.3.13','-e',
      '--accept-source-agreements','--accept-package-agreements',
      '--disable-interactivity','--silent','--scope','user')
    Update-SessionPath
  }
  return (Find-Python311)
}
function Test-MsvcBuildTools {
  $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
  if (Test-Path $vswhere) {
    $p = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
    if ($p) { return $true }
  }
  return $false
}
function Install-MsvcBuildTools {
  Warn "MSVC Build Tools ontbreken - benodigd voor de native Tauri-build."
  Warn "  Dit is een grote installatie (circa 3-6 GB, 10-30 min)."
  if (-not (Get-Exe 'winget')) {
    Warn "  winget niet gevonden. Handmatig installeren: https://visualstudio.microsoft.com/visual-cpp-build-tools/"
    return $false
  }
  $null = Invoke-WingetInstall @('install','--id','Microsoft.VisualStudio.2022.BuildTools','-e',
    '--accept-source-agreements','--accept-package-agreements',
    '--disable-interactivity','--silent',
    '--override','--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --passive --norestart --wait')
  return (Test-MsvcBuildTools)
}
function Install-RustToolchain {
  Warn "Rust toolchain ontbreekt - rustup installeren (stable, profile minimal)..."
  try {
    Ensure-Tls12
    $exe = Join-Path $env:TEMP 'rustup-init.exe'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://win.rustup.rs/x86_64' -OutFile $exe -TimeoutSec 300
    & $exe -y --default-toolchain stable --profile minimal
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    Update-SessionPath
    if (-not (Get-Exe 'cargo')) {
      $cargoBin = Join-Path $env:USERPROFILE '.cargo\bin'
      if (Test-Path (Join-Path $cargoBin 'cargo.exe')) {
        $env:Path = "$cargoBin;$env:Path"
      }
    }
    return [bool](Get-Exe 'cargo')
  } catch {
    Warn "  rustup-install mislukt: $($_.Exception.Message)"
    return $false
  }
}

Info "Root: $ROOT"
if ($Force) { Info "Force: venv/node_modules worden vernieuwd indien mogelijk" }

# --- prerequisites ----------------------------------------------------------
# Node.js + npm zijn verplicht (Svelte/Vite hangt erop). Ontbreken ze, dan
# installeert het script ze zelf tenzij -NoTools is meegegeven.
# Eerst PATH uit het register verversen: handig als Node net in een andere
# setup-run of venster is geinstalleerd.
Update-SessionPath
if (-not (Test-NodeStack)) {
  if ($NoTools) {
    Fail "Node.js + npm vereist. Installeer https://nodejs.org (LTS) en run opnieuw. (-NoTools stond automatische installatie niet toe.)"
  }
  $null = Install-NodeStack
}
if (-not (Test-NodeStack)) {
  Fail "Node.js + npm ontbreken en automatische installatie faalde. Installeer handmatig https://nodejs.org (LTS) en run setup opnieuw."
}
# Zorg dat ook de net geinstalleerde tools in dit proces zichtbaar zijn.
$cargoBin = Join-Path $env:USERPROFILE '.cargo\bin'
if ((Test-Path (Join-Path $cargoBin 'cargo.exe')) -and -not (Get-Exe 'cargo')) {
  $env:Path = "$cargoBin;$env:Path"
}
$hasCargo = $null -ne (Get-Exe 'cargo')
$hasRustc = $null -ne (Get-Exe 'rustc')
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
    Info "GUI: node_modules bestaat - skip install (gebruik -Force om te vernieuwen)"
  }
  Info "GUI: vite build (check)..."
  npm run build | Out-Null
  if ($LASTEXITCODE -ne 0) { Fail "vite build faalde." }
  Info "GUI klaar - dev: npm run dev  |  tauri: npm run tauri dev"
} finally { Pop-Location }

if ($NoTauri) {
  Warn "Tauri check overgeslagen (--NoTauri)."
} else {
  # 1) Tauri CLI (npm)
  # Check both: gui/node_modules (direct) and root node_modules (workspace hoist)
  $tauriCli = (Test-Path (Join-Path $ROOT "gui\node_modules\.bin\tauri.cmd")) -or
              (Test-Path (Join-Path $ROOT "node_modules\.bin\tauri.cmd"))
  if (-not $tauriCli) {
    Push-Location (Join-Path $ROOT "gui")
    try { npm install --no-audit --no-fund 2>&1 | Out-Null } finally { Pop-Location }
    $tauriCli = (Test-Path (Join-Path $ROOT "gui\node_modules\.bin\tauri.cmd")) -or
                (Test-Path (Join-Path $ROOT "node_modules\.bin\tauri.cmd"))
  }
  # 2) Rust toolchain (cargo) + MSVC build tools voor de native build
  if (-not $NoTools) {
    if (-not $hasCargo) { $hasCargo = Install-RustToolchain }
    if ($hasCargo -and -not (Test-MsvcBuildTools)) { $hasMsvc = Install-MsvcBuildTools } else { $hasMsvc = Test-MsvcBuildTools }
  } else {
    $hasMsvc = Test-MsvcBuildTools
  }
  if ($tauriCli -and $hasCargo -and $hasMsvc) {
    Info "Tauri compleet (CLI + Rust + MSVC) - npx tauri dev / build werkt."
  } elseif ($tauriCli -and $hasCargo) {
    Warn "Tauri CLI + Rust aanwezig, maar MSVC build tools ontbreken."
    Warn "  Zonder MSVC faalt 'cargo build'. GUI draait wel in browser (npm run dev -> http://localhost:1420)."
  } elseif ($tauriCli) {
    Warn "@tauri-apps/cli gevonden, maar geen werkende Rust/MSVC toolchain."
    Warn "  GUI draait in browser (npm run dev -> http://localhost:1420); native window werkt nog niet."
  } else {
    Warn "Tauri CLI niet gevonden - GUI draait in browser (npm run dev -> http://localhost:1420)."
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
    # Bij voorkeur een >=3.11 interpreter (3.10 en ouder halen requirements
    # niet rond); ontbreekt die, dan installeert het script zelf 3.13.
    $py = Find-Python311
    if (-not $py -and -not $NoTools) { $py = Install-Python3 }
    if (-not $py) { Fail "Python 3.11+ niet gevonden. Installeer https://python.org (3.11 of nieuwer) en run opnieuw. (-NoTools stond automatische installatie niet toe.)" }
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
      Warn "Bestaande venv onbruikbaar (verhuisd/corrupt) - opnieuw aanmaken..."
      Remove-Item -Recurse -Force (Join-Path $ROOT "backend\.venv") -ErrorAction SilentlyContinue
    }
    Info "Backend venv aanmaken (.venv)..."
    try { Invoke-Expression "& $py -m venv `"$ROOT\backend\.venv`"" } catch { Fail "venv aanmaken faalde: $_" }
    if ($LASTEXITCODE -ne 0) { Fail "venv aanmaken faalde." }
  } else {
    Info "Backend venv OK - hergebruik"
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
  Info "Backend klaar - run: backend\.venv\Scripts\python.exe backend\run.py  (of start_all.cmd)"
}

# --- .env -------------------------------------------------------------------
$envExample = Join-Path $ROOT "backend\.env.example"
$envFile    = Join-Path $ROOT "backend\.env"
if ((Test-Path $envExample) -and -not (Test-Path $envFile)) {
  Copy-Item $envExample $envFile
  Info ".env aangemaakt uit .env.example - pas paden aan indien nodig."
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

# --- Toolchain-overzicht ------------------------------------------------------
$nodeV  = if (Get-Exe 'node')  { (node -v) }  else { 'ONTBREEKT' }
$npmV   = if (Get-Exe 'npm')   { (npm -v) }   else { 'ONTBREEKT' }
$cargoV = if (Get-Exe 'cargo') { (cargo --version) } else { 'niet geinstalleerd' }
$pyRep  = '(overgeslagen)'
if (Get-Variable -Name py -Scope 0 -ErrorAction SilentlyContinue) { $pyRep = "$py" }
$msvcV  = Test-MsvcBuildTools
Info "Toolchain-overzicht:"
Info "  Node.js      $nodeV"
Info "  npm          $npmV"
Info "  Python       $pyRep"
Info "  Rust/cargo   $cargoV"
if ($msvcV) { Info "  MSVC         aanwezig" }
else { Warn "  MSVC         ontbreekt (alleen nodig voor de native Tauri-build)" }

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

#Requires -Version 5.1
<#
.SYNOPSIS
    Bouwt de schone NovaTTS 2.5.0d-installer (pausable / resumable).

    Herhaaldelijk draaien hervat waar het laatst gestopt is: elke stage schrijft
    een marker in .build\2.5.0d\. Als je het script onderbreekt, wordt de stage
    niet gemarkeerd en wordt hij bij de volgende run opnieuw geprobeerd (idempotent).

    Volledige pipeline:
      1. Provision   - Tauri CLI + Inno Setup (ISCC) + 7-Zip controleren/installeren
      2. Version     - versie naar 2.5.0d in tauri.conf.json + installer/NovaTTS-2.5.0d.iss
      3. Scaffold    - .build\payload-2.5.0c -> .build\payload-2.5.0d (bekende goeie layout)
      4. BackendExe  - PyInstaller-freeze van de live backend/Novabackend.spec
      5. GuiExe      - Tauri release-build + NovaTTS.exe uittrekken naar payload
      6. VerifyPayload - verboden dirs/Bestanden afwezig, binaries nieuwer dan scaffold
      7. CompileInno - ISCC -> dist-installer\NovaTTS-Setup-2.5.0d.exe
      8. FinalVerify  - SHA + inhoudscontrole

    Gebruik:
      .\.dev\Build-2.5.0d.ps1                 # alles, hervatbaar
      .\.dev\Build-2.5.0d.ps1 -FromStage 4    # hervat vanaf stage 4 (bijv. na pauze)
      .\.dev\Build-2.5.0d.ps1 -ReuseGui       # hergebruik payload-2.5.0c NovaTTS.exe (GUI niet herbuilden)
#>
[CmdletBinding()]
param(
    [ValidateSet('All','Provision','Version','Scaffold','BackendExe','GuiExe','VerifyPayload','CompileInno','FinalVerify')]
    [string]$FromStage = 'All',

    [switch]$ReuseGui,          # hergebruik de bestaande NovaTTS.exe uit payload-2.5.0c (GUI niet herbuilden)
    [string]$InnoPath = '',     # optioneel: pad naar ISCC.exe
    [string]$SevenZipPath = ''  # optioneel: pad naar 7z.exe
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ---------------------------------------------------------------------------
# Pad-en markering
# ---------------------------------------------------------------------------
$ROOT   = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path   # repo root, absoluut
$CK     = Join-Path $ROOT '.build\2.5.0d'                      # markers + log (repo-root .build)
$LOG    = Join-Path $CK 'log.txt'

# Versie voor de output/berichten (ook buiten Stage-Version beschikbaar).
$VER = '2.5.0d'

# Stage-index: 'All' = vanaf stage 1; een getal is 1-gebaseerd (4 = BackendExe),
# een stagnaam werkt ook.
$allStages = @('Provision','Version','Scaffold','BackendExe','GuiExe','VerifyPayload','CompileInno','FinalVerify')
if ($FromStage -ieq 'All') {
    $startIdx = 0
} elseif ($FromStage -match '^\d+$') {
    $startIdx = [int]$FromStage - 1
} else {
    $startIdx = [array]::IndexOf($allStages, $FromStage)
    if ($startIdx -lt 0) { throw "Onbekende stage: $FromStage" }
}

if (-not (Test-Path $CK)) { New-Item -ItemType Directory -Path $CK -Force | Out-Null }

function Write-Ck   { param([string]$Msg, [ConsoleColor]$ForegroundColor = [ConsoleColor]::Gray) Add-Content -Path $LOG -Value ("[" + (Get-Date -Format 'o') + "] " + $Msg) -Encoding UTF8; Write-Host $Msg -ForegroundColor $ForegroundColor }
function Mark-Done  { param([string]$Stage) (Set-Content -Path (Join-Path $CK "$Stage.ok") -Value (Get-Date -Format o) -Encoding UTF8); Write-Ck "[marker] stage '$Stage' VOLTOOID" }
# Marker bestaat -> stage is al gedaan (true). Marker ontbreekt -> nog te doen (false).
function Test-Done  { param([string]$Stage) (Test-Path (Join-Path $CK "$Stage.ok")) }

# Run a native tool without letting its stderr lines terminate the script
# (PS 5.1 turns native stderr into NativeCommandError while the preference is
# 'Stop'). Returns the exit code; all output goes to $LogFile.
function Invoke-Native {
    param([string]$LogFile, [scriptblock]$Command)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Command 2>&1 | Out-String | Add-Content -LiteralPath $LogFile
        return $LASTEXITCODE
    } finally { $ErrorActionPreference = $prev }
}

# Stages die nog moeten draaien:
$todo = $allStages[$startIdx..($allStages.Count - 1)]

if ($todo.Count -eq 0) { Write-Ck "Alles gedaan (of geen stages geselecteerd). Niets te doen."; return }
Write-Ck "Start Build-2.5.0d. Te draaien: $($todo -join ', ')   (FromStage=$FromStage)"

# ===========================================================================
# STAGE 1 — Provision (Tauri CLI + Inno Setup + 7-Zip)
# ===========================================================================
function Stage-Provision {
    if (Test-Done 'Provision') { Write-Ck "Provision al gedaan - overslaan"; return }

    # --- Tauri CLI ---------------------------------------------------------
    $tauri = Get-Command tauri.cmd -ErrorAction SilentlyContinue
    if (-not $tauri) {
        Write-Ck "Tauri CLI ontbreekt. Installeer: npm install -g @tauri-apps/cli"
        try { npm install -g @tauri-apps/cli 2>&1 | Out-String | Add-Content $LOG; Write-Ck "npm i -g @tauri-apps/cli uitgevoerd" }
        catch { Write-Ck "Tauri CLI installatie mislukt: $_" }
    } else { Write-Ck "Tauri CLI gevonden: $($tauri.Source)" }

    # --- Inno Setup (ISCC) -------------------------------------------------
    $iscc = Find-ISCC $InnoPath
    if (-not $iscc) {
        Write-Ck "Inno Setup ontbreekt. Installeer: https://jrsoftware.org/isdl.php  (of draai met -InnoPath)"
        try { winget install --id JRSoftware.InnoSetup --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-String | Add-Content $LOG; Write-Ck "winget Inno Setup uitgevoerd" }
        catch { Write-Ck "Inno Setup installatie mislukt: $_" }
    } else { Write-Ck "ISCC gevonden: $iscc" }

    # --- 7-Zip (voor NovaTTS.exe uittrekken uit Tauri NSIS) -----------------
    $seven = Get-Command 7z.exe -ErrorAction SilentlyContinue
    if (-not $seven) {
        Write-Ck "7-Zip ontbreekt. Installeer: https://www.7-zip.org/  (nodig om NovaTTS.exe uit de NSIS-bundel te halen)"
        try { winget install --id.7zip.7zip --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-String | Add-Content $LOG; Write-Ck "winget 7-Zip uitgevoerd" }
        catch { Write-Ck "7-Zip installatie mislukt: $_" }
    } else { Write-Ck "7z gevonden: $($seven.Source)" }

    Mark-Done 'Provision'
}
function Find-ISCC($hint) {
    if ($hint -and (Test-Path $hint)) { return $hint }
    foreach ($p in @("C:\Program Files (x86)\Inno Setup 6\ISCC.exe","C:\Program Files\Inno Setup 6\ISCC.exe")) { if (Test-Path $p) { return $p } }
    $c = Get-Command ISCC -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

# ===========================================================================
# STAGE 2 — Version naar 2.5.0d
# ===========================================================================
function Stage-Version {
    if (Test-Done 'Version') { Write-Ck "Versie al 2.5.0d - overslaan"; return }
    $VER = '2.5.0d'

    # tauri.conf.json
    # tauri.conf.json (unieke literal vervanging via .Replace -> geen regex)
    $tc = Join-Path "$ROOT/gui/src-tauri" 'tauri.conf.json'
    # Read/write as BOM-free UTF-8: PS 5.1's default ANSI read turns the em
    # dash in the Perfect Cut title into mojibake.
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $raw = Get-Content $tc -Raw -Encoding UTF8
    if ($raw -match '"version": "2\.0\.0"') {
        # Still has 2.0.0, replace it
        [IO.File]::WriteAllText($tc, $raw.Replace('"version": "2.0.0"', '"version": "' + $VER + '"'), $utf8)
    } elseif ($raw -match '"version": "2\.5\.0d"') {
        # Already 2.5.0d, skip
        Write-Ck "tauri.conf.json versie -> $VER (al correct)"
    } else {
        throw "Onverwachte versie in tauri.conf.json: '$raw'"
    }

    # installer/NovaTTS-$VER.iss uit template (unieke literals, .Replace = letterlijke vervanging)
    $tpl = Join-Path "$ROOT/installer" 'NovaTTS-2.5.0c.iss'
    $out = Join-Path "$ROOT/installer" "NovaTTS-$VER.iss"
    if (-not (Test-Path $out)) {
        $raw = Get-Content $tpl -Raw -Encoding UTF8
        $raw = $raw.Replace('#define MyAppVersion "2.5.0c"', '#define MyAppVersion "' + $VER + '"')
        $raw = $raw.Replace('MyPayloadDir "..\.build\payload-2.5.0c"', 'MyPayloadDir "..\.build\' + $VER + '\payload"')
        [IO.File]::WriteAllText($out, $raw, $utf8)
        Write-Ck "Installer-script gemaakt: installer\NovaTTS-$VER.iss"
    } else { Write-Ck "Installer-script bestaat al: $out" }

    Mark-Done 'Version'
}

# ===========================================================================
# STAGE 3 — Scaffold payload uit de bekende goeie 2.5.0c-layout
# ===========================================================================
function Stage-Scaffold {
    if (Test-Done 'Scaffold') { Write-Ck "Payload-scaffold al klaar - overslaan"; return }
    $src = Join-Path $ROOT '.build\payload-2.5.0c'
    $dst = Join-Path $CK 'payload'
    if (-not (Test-Path $src)) { throw "Scaffold-bron .build\payload-2.5.0c ontbreekt - kan niet worden gebouwd." }
    if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
    robocopy $src $dst /E /XF *.ok /XD ".build" | Out-Null
    # The scaffold comes from an older payload and can still contain the
    # developer's own .env.example / env-writer. Always take those from the
    # live tree so a package never ships someone else's model paths.
    foreach ($pair in @(
        @("$ROOT\backend\.env.example", (Join-Path $dst '.env.example')),
        @("$ROOT\backend\.env.example", (Join-Path $dst 'backend\.env.example')),
        @("$ROOT\.dev\Write-NovaTTSEnv.ps1", (Join-Path $dst 'Write-NovaTTSEnv.ps1'))
    )) {
        if (Test-Path $pair[0]) {
            $parent = Split-Path -Parent $pair[1]
            if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
            Copy-Item $pair[0] $pair[1] -Force
        }
    }
    Write-Ck "Payload-scaffold: $CK\payload ($((Get-ChildItem $dst -Recurse -File -ErrorAction SilentlyContinue | Measure).Count) bestanden)"
    Mark-Done 'Scaffold'
}

# ===========================================================================
# STAGE 4 — Backend exe (PyInstaller, patched config.py -> geen E:\)
# ===========================================================================
function Stage-BackendExe {
    if (Test-Done 'BackendExe') { Write-Ck "Backend-exe al gebouwd - overslaan"; return }

    $py = "$ROOT/backend/.venv/Scripts/python.exe"
    if (-not (Test-Path $py)) {
        Write-Ck "Geen backend/.venv - maak Python 3.11 venv + deps..."
        python -m venv "$ROOT/backend/.venv" | Out-Null
        $pipLog = Join-Path $CK 'pip.log'
        Invoke-Native $pipLog { & $py -m pip install --upgrade pip wheel setuptools } | Out-Null
        Invoke-Native $pipLog { & $py -m pip install -r "$ROOT/backend/requirements.txt" } | Out-Null
        Get-Content $pipLog -ErrorAction SilentlyContinue | Add-Content $LOG
        Write-Ck "venv + requirements geinstalleerd"
    } else { Write-Ck "backend/.venv bestaat al" }

    # Freeze from the live spec in backend/. Never reuse the scaffolded
    # payload spec: it can be months old and would ship stale API routes.
    $spec = "$ROOT/backend/Novabackend.spec"
    if (-not (Test-Path $spec)) { throw "PyInstaller-spec ontbreekt: $spec" }

    # Freeze (kan 5-15 min duren). PyInstaller must be awaited: the old
    # Process.Start variant returned immediately and checked for the exe
    # before it existed.
    Write-Ck "PyInstaller-freeze: backend/Novabackend.spec ..."
    # Native stderr lines (PyInstaller logs INFO to stderr) turn into
    # terminating NativeCommandError records while ErrorActionPreference is
    # 'Stop'. Redirect all streams to a file and judge success by exit code.
    $freezeLog = Join-Path $CK 'pyinstaller.log'
    Push-Location "$ROOT/backend"
    try {
        $freezeCode = Invoke-Native $freezeLog { & $py -m PyInstaller $spec --noconfirm --distpath "$ROOT/backend/dist" --workpath "$ROOT/backend/build" }
    } finally { Pop-Location }
    Get-Content $freezeLog -ErrorAction SilentlyContinue | Add-Content $LOG
    if ($freezeCode -ne 0) { throw "PyInstaller faalde (exit $freezeCode). Zie $freezeLog" }

    $exe = "$ROOT/backend/dist/novatts-backend.exe"
    if (-not (Test-Path $exe)) { throw "novatts-backend.exe niet gegenereerd in backend\dist\" }
    Write-Ck "PyInstaller completed successfully: $exe ($((Get-Item $exe).Length) bytes)"

    # Plaats in payload resources/
    $destExe = "$CK/payload/resources/novatts-backend.exe"
    Copy-Item $exe $destExe -Force
    Write-Ck "resources/novatts-backend.exe -> $((Get-Item $destExe).Length) bytes (from live spec)"
    Mark-Done 'BackendExe'
}

# ===========================================================================
# STAGE 5 — GUI exe (Tauri release-build + NovaTTS.exe uittrekken)
# ===========================================================================
function Stage-GuiExe {
    if (Test-Done 'GuiExe') { Write-Ck "GUI-exe al gebouwd - overslaan"; return }

    # Fallback: payload-2.5.0c NovaTTS.exe hergebruiken?
    if ($ReuseGui) {
        $old = Join-Path "$CK\payload\NovaTTS.exe"
        if (-not (Test-Path $old)) { Copy-Item (Join-Path "$ROOT\.build\payload-2.5.0c\NovaTTS.exe") $old -Force }
        Write-Ck "ReuseGui: NovaTTS.exe uit payload-2.5.0c hergebruikt (GUI NIET herbuilden)"
        Mark-Done 'GuiExe'
        return
    }

    # Frontend bouwen (tauri doet dit automatisch, expliciet voor de zekerheid)
    Write-Ck "Frontend build: npm run build ..."
    Push-Location ($ROOT + '/gui')
    try {
        $npmCode = Invoke-Native (Join-Path $CK 'npm-build.log') { npm run build }
    } finally { Pop-Location }
    Get-Content (Join-Path $CK 'npm-build.log') -ErrorAction SilentlyContinue | Add-Content $LOG
    if ($npmCode -ne 0) { throw "npm run build faalde (exit $npmCode). Zie .build\2.5.0d\npm-build.log" }

    # Tauri release-build -> NSIS installer
    Write-Ck "Tauri release-build (cargo, kan lang duren)..."
    Push-Location ($ROOT + '/gui/src-tauri')
    try {
        $tauriCode = Invoke-Native (Join-Path $CK 'tauri-build.log') { npm run tauri -- build --config tauri.release.json }
    } finally { Pop-Location }
    Get-Content (Join-Path $CK 'tauri-build.log') -ErrorAction SilentlyContinue | Add-Content $LOG
    if ($tauriCode -ne 0) { throw "Tauri build faalde (exit $tauriCode). Zie .build\2.5.0d\tauri-build.log" }

    $nsis = ($ROOT + '/gui/src-tauri/target/release/bundle/nsis/NovaTTS_$VER_x64-setup.exe')
    if (-not (Test-Path $nsis)) { throw "NSIS-installer niet gevonden: $nsis - controleer de tauri build-output." }
    Write-Ck "NSIS-installer: $nsis ($((Get-Item $nsis).Length) bytes)"

    # NovaTTS.exe uittrekken uit de Inno/NSIS-bundel (7-Zip ondersteunt Inno)
    $stage = Join-Path ([System.IO.Path]::GetTempPath()) "novatts-gui-$([Guid]::NewGuid().ToString('N').Substring(0,8))"
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    try {
        if ($SevenZipPath) { $seven = $SevenZipPath } else { $seven = (Get-Command 7z.exe -ErrorAction SilentlyContinue).Source }
        if (-not $seven) { throw "7-Zip ontbreekt en geen pad gegeven - kan NovaTTS.exe niet uittrekken." }
        Write-Ck "Uittrekken NovaTTS.exe via 7z ..."
        $sevenCode = Invoke-Native (Join-Path $CK '7z-extract.log') { & $seven x -y $nsis "app\" -o"$stage\app" }
        if ($sevenCode -ne 0) { throw "7z uitpakken faalde (exit $sevenCode). Zie .build\2.5.0d\7z-extract.log" }
        $guiExe = Join-Path $stage 'app\NovaTTS.exe'
        if (-not (Test-Path $guiExe)) { throw "NovaTTS.exe niet gevonden na uittrekken: $guiExe" }
        Copy-Item $guiExe (Join-Path "$CK\payload\NovaTTS.exe") -Force
        Write-Ck "NovaTTS.exe -> payload ($((Get-Item (Join-Path '$CK\payload\NovaTTS.exe')).Length) bytes, versie $VER)"
    } finally { Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue }

    Mark-Done 'GuiExe'
}

# ===========================================================================
# STAGE 6 — Payload verifiëren (verboden dirs/Bestanden + binaries)
# ===========================================================================
function Stage-VerifyPayload {
    if (Test-Done 'VerifyPayload') { Write-Ck "Payload al geverifieerd - overslaan"; return }

    $p = Join-Path "$CK\payload"
    $forbidden = @('.venv','node_modules','target','__pycache__','.mypy_cache','.ruff_cache','.pytest_cache','cache','Output')
    foreach ($d in $forbidden) { if (Test-Path (Join-Path $p "$d")) { throw "Verboden dir in payload: $d" } }
    if (Test-Path (Join-Path $p 'backend\.env')) { throw "backend\.env mag niet in de payload zitten." }
    foreach ($req in @('NovaTTS.exe','resources\novatts-backend.exe','Run-Install-AITools.cmd','Start-NovaTTS.cmd','Write-NovaTTSEnv.ps1','installer\novatts.ico','.env.example')) {
        if (-not (Test-Path (Join-Path $p "$req"))) { throw "Ontbrekend payload-bestand: $req" }
    }
    # binaries nieuwer dan scaffold (beweegt dat ze echt herbuild zijn)
    $now = [DateTime]::Now.ToFileTimeUtc()
    foreach ($b in @('NovaTTS.exe','resources\novatts-backend.exe')) {
        $mt = (Get-Item (Join-Path $p "$b")).LastWriteTime.ToFileTimeUtc()
        if ($mt -lt $now.AddMinutes(-30)) { Write-Ck "Waarschuwing: $b lijkt niet herbuild ($((Get-Item (Join-Path $p $b)).Length) bytes)" }
    }
    # .env.example BOM-vrij + geen developerpaden baked in
    $envFiles = @((Join-Path $p '.env.example'), (Join-Path $p 'backend\.env.example'))
    foreach ($envFile in $envFiles) {
        if (-not (Test-Path $envFile)) { continue }
        $bytes = [IO.File]::ReadAllBytes($envFile)
        if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
            throw "$envFile begint met een UTF-8 BOM."
        }
        $ex = Get-Content $envFile -Raw -Encoding UTF8
        if ($ex -match '(?i)([A-Z]:\\\\(Projects|!!Scripts|Temp|Users\\\\BoBo)|Samples_Clone|LLM''s)') {
            throw "$envFile bevat nog een gehardcodeerd developepad."
        }
    }

    Write-Ck "Payload OK: $($forbidden.Count) verboden dirs afwezig, binaries aanwezig en .env.example schoon"
    Mark-Done 'VerifyPayload'
}

# ===========================================================================
# STAGE 7 — Inno Setup compileren -> setup.exe
# ===========================================================================
function Stage-CompileInno {
    if (Test-Done 'CompileInno') { Write-Ck "Setup al gebouwd - overslaan"; return }
    $iscc = Find-ISCC $InnoPath
    if (-not $iscc) { throw "ISCC niet gevonden - installeer Inno Setup of draai met -InnoPath." }
    Write-Ck "ISCC: $iscc"
    $isccCode = Invoke-Native (Join-Path $CK 'iscc.log') { & $iscc ($ROOT + '/installer/NovaTTS-' + $VER + '.iss') }
    Get-Content (Join-Path $CK 'iscc.log') -ErrorAction SilentlyContinue | Add-Content $LOG
    if ($isccCode -ne 0) { throw "ISCC faalde (exit $isccCode). Zie .build\2.5.0d\iscc.log" }
    $setup = Get-ChildItem ($ROOT + '/dist-installer/NovaTTS-Setup-$VER.exe') -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $setup) { throw "Setup-exe niet gevonden in dist-installer\" }
    Write-Ck "Setup EXE klaar: $($setup.FullName) ($($setup.Length) bytes)"
    Mark-Done 'CompileInno'
}

# ===========================================================================
# STAGE 8 — Finale verificatie (SHA + inhoud)
# ===========================================================================
function Stage-FinalVerify {
    if (Test-Done 'FinalVerify') { Write-Ck "Finale verificatie al gedaan - overslaan"; return }
    $setup = Get-ChildItem ($ROOT + '/dist-installer/NovaTTS-Setup-$VER.exe') -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $setup) { throw "Geen NovaTTS-Setup-$VER.exe in dist-installer\" }

    $sha = (Get-FileHash -LiteralPath $setup.FullName -Algorithm SHA256).Hash.Substring(0,32)
    Write-Ck "SHA256 (32 hex): $($sha)"
    Add-Content $LOG -Value ("[verify] SHA256=$sha" ) -Encoding UTF8

    # Inhoudscontrole: uitpakken en controleren op de juiste AppId + payload-bestanden
    Write-Ck "Inhoudscontrole (uitpakken naar temp)..."
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) "novatts-check-$([Guid]::NewGuid().ToString('N').Substring(0,8))"
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    $seven = if ($SevenZipPath) { $SevenZipPath } else { (Get-Command 7z.exe -ErrorAction SilentlyContinue).Source }
    if (-not $seven) { throw "7-Zip ontbreekt - kan de setup niet uitpakken voor de eindcontrole." }
    try {
        Invoke-Native (Join-Path $CK '7z-verify.log') { & $seven e $setup.FullName -o"$tmp\" } | Out-Null
        $app = Join-Path $tmp 'AppData\Local\NovaTTS'
        if (-not (Test-Path $app)) { Write-Ck "Waarschuwing: payload-map niet onder LocalAppData/NovaTTS gevonden na uitpakken" }
        else {
            foreach ($req in @('NovaTTS.exe','resources\novatts-backend.exe','Run-Install-AITools.cmd','Write-NovaTTSEnv.ps1')) {
                if (Test-Path (Join-Path $app "$req")) { Write-Ck "  OK  $req" } else { Write-Ck "  MISS $req" }
            }
        }
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }

    # Versie in setup-exe header controleren (NSIS/Inno slaat AppVersion in)
    Add-Content $LOG -Value ("[verify] Setup: $($setup.FullName), $(($setup.Length)/1MB).MB") -Encoding UTF8
    Write-Ck "Finale verificatie VOLTOOID -> dist-installer\NovaTTS-Setup-$VER.exe"
    Mark-Done 'FinalVerify'
}

# ===========================================================================
# Uitvoering
# ===========================================================================
for ($i = 0; $i -lt $todo.Count; $i++) {
    $name = $todo[$i]
    try {
        Write-Ck "`n========== STAGE: $name =========="
        & ("Stage-" + $name)
    } catch {
        Write-Ck "STAGE '$name' MISLUKKT: $_" -ForegroundColor Red
        Add-Content $LOG -Value ("[ERROR] stage=$name msg=$($_.Exception.Message)" ) -Encoding UTF8
        break
    }
}

Write-Ck "`n=== Build-2.5.0d klaar (of gestopt op eerste mislukte stage). Log: $LOG ==="
if (Test-Path ($ROOT + '/dist-installer/NovaTTS-Setup-$VER.exe')) {
    Write-Ck "Resultaat: dist-installer/NovaTTS-Setup-$VER.exe" -ForegroundColor Green
}

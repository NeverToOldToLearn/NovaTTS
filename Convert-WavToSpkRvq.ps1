# ============================================================
# Convert-WavToSpkRvq.ps1
# Scans a folder of paired .wav + .txt files and converts them
# into pre-extracted .spk + .rvq voice references for qwentts.cpp
# ============================================================
# Usage:
#   .\Convert-WavToSpkRvq.ps1
#   .\Convert-WavToSpkRvq.ps1 -SourceDir "D:\MyVoices" -Force
# ============================================================

param(
    [string]$SourceDir   = "",
    [string]$CodecExe    = "",
    [string]$CodecModel  = "",
    [string]$TalkerModel = "",
    [switch]$Force       # Overwrite existing .spk/.rvq
)

# Read a value from the environment or the NovaTTS .env, so no machine-specific
# path is baked into this script. Falls back to a repo-relative default.
function Get-NovaEnv([string]$Name, [string]$Default = "") {
    $v = [Environment]::GetEnvironmentVariable($Name)
    if ($v) { return $v }
    foreach ($f in @((Join-Path $PSScriptRoot '.env'), (Join-Path $env:LOCALAPPDATA 'NovaTTS\.env'), (Join-Path $env:LOCALAPPDATA 'NovaTTS\backend\.env'))) {
        if (Test-Path -LiteralPath $f) {
            $line = Get-Content -LiteralPath $f -Encoding UTF8 |
                Where-Object { $_ -match ('^\s*' + [regex]::Escape($Name) + '\s*=') } |
                Select-Object -First 1
            if ($line) { return ($line -replace '^\s*[^=]+\s*=\s*', '').Trim().Trim('"') }
        }
    }
    return $Default
}

if (-not $SourceDir)   { $SourceDir   = Get-NovaEnv 'NOVATTS_QWEN_SAMPLES_DIR' (Join-Path $PSScriptRoot 'data\samples') }
if (-not $CodecExe)    { $CodecExe    = Get-NovaEnv 'NOVATTS_QWEN_CODEC_BIN' }
if (-not $CodecModel)  { $CodecModel  = Get-NovaEnv 'NOVATTS_QWEN_CODEC' }
if (-not $TalkerModel) { $TalkerModel = Get-NovaEnv 'NOVATTS_QWEN_MODEL' }
if (-not $CodecExe -and (Get-NovaEnv 'NOVATTS_QWEN_BIN')) {
    $CodecExe = Join-Path (Split-Path (Get-NovaEnv 'NOVATTS_QWEN_BIN')) 'qwen-codec.exe'
}

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Convert WAV+TXT -> .spk + .rvq ===" -ForegroundColor Cyan
Write-Host "Source folder : $SourceDir"
Write-Host ""

# --- Validation ---
if (-not (Test-Path $SourceDir)) {
    Write-Error "Source directory not found: $SourceDir"
}
if (-not (Test-Path $CodecExe)) {
    Write-Error "qwen-codec.exe not found: $CodecExe"
}
if (-not (Test-Path $CodecModel)) {
    Write-Error "Codec model not found: $CodecModel"
}
if (-not (Test-Path $TalkerModel)) {
    Write-Error "Talker model not found: $TalkerModel"
}

$wavFiles = Get-ChildItem -Path $SourceDir -Filter "*.wav" -File
if ($wavFiles.Count -eq 0) {
    Write-Host "No .wav files found in $SourceDir" -ForegroundColor Yellow
    exit 0
}

$converted = 0
$skipped   = 0
$failed    = 0

foreach ($wav in $wavFiles) {
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($wav.Name)
    $txtPath  = Join-Path $SourceDir "$baseName.txt"
    $spkPath  = Join-Path $SourceDir "$baseName.spk"
    $rvqPath  = Join-Path $SourceDir "$baseName.rvq"

    Write-Host "Processing: $($wav.Name)" -ForegroundColor White

    # Check for matching .txt
    if (-not (Test-Path $txtPath)) {
        Write-Host "  -> SKIPPED (no matching .txt found)" -ForegroundColor Yellow
        $skipped++
        continue
    }

    # Skip if already converted (unless -Force)
    if ((Test-Path $spkPath) -and (Test-Path $rvqPath) -and -not $Force) {
        Write-Host "  -> SKIPPED (already has .spk + .rvq). Use -Force to overwrite." -ForegroundColor DarkGray
        $skipped++
        continue
    }

    try {
        # qwen-codec --talker produces both .spk and .rvq next to the input
        $args = @(
            "--model",  $CodecModel,
            "--talker", $TalkerModel,
            "-i",       $wav.FullName
        )

        Write-Host "  -> Running qwen-codec..." -NoNewline
        $proc = Start-Process -FilePath $CodecExe -ArgumentList $args -Wait -PassThru -NoNewWindow

        if ($proc.ExitCode -ne 0) {
            throw "qwen-codec exited with code $($proc.ExitCode)"
        }

        # Verify output files were created
        if (-not (Test-Path $spkPath) -or -not (Test-Path $rvqPath)) {
            throw "Expected .spk / .rvq were not created"
        }

        Write-Host " OK" -ForegroundColor Green
        Write-Host "     Created: $baseName.spk + $baseName.rvq" -ForegroundColor Green
        $converted++
    }
    catch {
        Write-Host " FAILED" -ForegroundColor Red
        Write-Host "     Error: $($_.Exception.Message)" -ForegroundColor Red
        $failed++
    }
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host "Converted : $converted"
Write-Host "Skipped   : $skipped"
Write-Host "Failed    : $failed"
Write-Host ""

if ($converted -gt 0) {
    Write-Host "You can now use Start-QwenTTS-Multi.ps1 to load these voices." -ForegroundColor Green
}

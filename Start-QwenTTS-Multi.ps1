# ============================================================
# Start-QwenTTS-Multi.ps1
# Starts tts-server and automatically registers all .spk/.rvq
# voice pairs found in a folder.
# ============================================================
# Usage:
#   .\Start-QwenTTS-Multi.ps1
#   .\Start-QwenTTS-Multi.ps1 -VoiceDir "D:\MyVoices" -Port 8081
# ============================================================

param(
    [string]$TtsExe     = "D:\Projects\qwentts.cpp\build\Release\tts-server.exe",
    [string]$Model      = "E:\LLM's\Qwen3TTS\qwen-talker-1.7b-base-Q8_0.gguf",
    [string]$Codec      = "E:\LLM's\Qwen3TTS\qwen-tokenizer-12hz-Q8_0.gguf",
    [string]$HostIp     = "127.0.0.1",
    [int]   $Port       = 8081,
    [string]$Alias      = "qwen3-tts",
    [string]$VoiceDir   = "D:\!!Scripts!!\!!VisualNove-TTS",
    [int]   $MaxWaitSec = 45
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Qwen TTS Multi-Voice Launcher ===" -ForegroundColor Cyan
Write-Host ""

# --- Validation ---
if (-not (Test-Path $TtsExe))  { Write-Error "tts-server.exe not found: $TtsExe" }
if (-not (Test-Path $Model))   { Write-Error "Talker model not found: $Model" }
if (-not (Test-Path $Codec))   { Write-Error "Codec model not found: $Codec" }
if (-not (Test-Path $VoiceDir)){ Write-Error "Voice directory not found: $VoiceDir" }

# Collect all .spk files that have a matching .rvq
$spkFiles = Get-ChildItem -Path $VoiceDir -Filter "*.spk" -File
$voicePairs = @()

foreach ($spk in $spkFiles) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($spk.Name)
    $rvq  = Join-Path $VoiceDir "$base.rvq"
    if (Test-Path $rvq) {
        $voicePairs += [PSCustomObject]@{
            Name = $base
            Spk  = $spk.FullName
            Rvq  = $rvq
        }
    }
}

if ($voicePairs.Count -eq 0) {
    Write-Host "No complete .spk + .rvq pairs found in $VoiceDir" -ForegroundColor Yellow
    Write-Host "Run Convert-WavToSpkRvq.ps1 first." -ForegroundColor Yellow
    exit 1
}

Write-Host "Found $($voicePairs.Count) voice(s) to register:" -ForegroundColor White
$voicePairs | ForEach-Object { Write-Host "  • $($_.Name)" -ForegroundColor Gray }
Write-Host ""

# --- Start server in separate window ---
Write-Host "Starting tts-server on ${HostIp}:${Port} ..." -ForegroundColor Cyan

$serverArgs = @(
    "--model",  $Model,
    "--codec",  $Codec,
    "--alias",  $Alias,
    "--host",   $HostIp,
    "--port",   $Port
)

Start-Process -FilePath $TtsExe -ArgumentList $serverArgs -WindowStyle Normal

# --- Wait until server is healthy ---
Write-Host "Waiting for server to become ready..." -NoNewline
$ready = $false
for ($i = 1; $i -le $MaxWaitSec; $i++) {
    try {
        $null = Invoke-RestMethod -Uri "http://${HostIp}:${Port}/health" -Method GET -TimeoutSec 1 -ErrorAction Stop
        $ready = $true
        break
    } catch {
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 1
    }
}

if (-not $ready) {
    Write-Host ""
    Write-Error "Server did not become ready within $MaxWaitSec seconds."
}

Write-Host ""
Write-Host "Server is online." -ForegroundColor Green
Write-Host ""

# --- Register every voice ---
$success = 0
$failed  = 0

foreach ($v in $voicePairs) {
    Write-Host "Registering: $($v.Name) ..." -NoNewline

    try {
        $spkB64 = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($v.Spk))
        $rvqB64 = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($v.Rvq))

        # Optional: look for a matching .txt to use as ref_text (improves ICL quality)
        $txtPath = Join-Path $VoiceDir "$($v.Name).txt"
        $refText = ""
        if (Test-Path $txtPath) {
            $refText = (Get-Content -Path $txtPath -Raw -Encoding UTF8).Trim()
        }

        $body = @{
            name    = $v.Name
            spk_b64 = $spkB64
            rvq_b64 = $rvqB64
        }
        if ($refText -ne "") {
            $body.ref_text = $refText
        }

        $json = $body | ConvertTo-Json -Depth 5 -Compress

        $null = Invoke-RestMethod -Uri "http://${HostIp}:${Port}/v1/audio/voices" `
                                  -Method POST `
                                  -Body $json `
                                  -ContentType "application/json; charset=utf-8" `
                                  -TimeoutSec 30

        Write-Host " OK" -ForegroundColor Green
        $success++
    }
    catch {
        Write-Host " FAILED" -ForegroundColor Red
        Write-Host "   $($_.Exception.Message)" -ForegroundColor Red
        if ($_.ErrorDetails) { Write-Host "   $($_.ErrorDetails.Message)" -ForegroundColor Red }
        $failed++
    }
}

Write-Host ""
Write-Host "=== Registration Summary ===" -ForegroundColor Cyan
Write-Host "Success : $success"
Write-Host "Failed  : $failed"
Write-Host ""

# Show final voice list
try {
    $voices = Invoke-RestMethod -Uri "http://${HostIp}:${Port}/v1/audio/voices"
    Write-Host "Currently registered voices:" -ForegroundColor Cyan
    $voices.voices | ForEach-Object {
        $kind = if ($_.kind) { $_.kind } else { "unknown" }
        Write-Host ("  • {0,-30} [{1}]" -f $_.name, $kind) -ForegroundColor Gray
    }
} catch {
    Write-Host "Could not fetch final voice list." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "TTS server is running at http://${HostIp}:${Port}" -ForegroundColor Green
Write-Host "You can close this window – the server keeps running in its own window."
Write-Host ""
Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

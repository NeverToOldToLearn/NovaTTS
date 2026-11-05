<#
.SYNOPSIS
    Writes (or repairs) the NovaTTS .env so the Qwen paths point at the
    AI-Tools build under %LOCALAPPDATA%\NovaTTS\AI-Tools.

.NOTES
    - Writes UTF-8 WITHOUT BOM: a BOM makes python-dotenv prefix the first
      key with U+FEFF, so that setting is silently ignored.
    - Preserves unrelated keys and comments.
    - Repairs only known-broken values; a user's custom paths are kept.
    - ASCII-only strings to avoid Windows encoding/parse errors.
#>

param(
    [string]$Root = (Join-Path $env:LOCALAPPDATA 'NovaTTS'),
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# The app reads .env next to itself ({app}); the AI-Tools build always lives
# under %LOCALAPPDATA%\NovaTTS\AI-Tools (spaces-free path for CMake).
$root     = $Root
$aiHome   = Join-Path $env:LOCALAPPDATA 'NovaTTS\AI-Tools'
$qwen     = Join-Path $aiHome 'qwentts.cpp'
$bin      = Join-Path $qwen 'build\Release\tts-server.exe'
$codecBin = Join-Path $qwen 'build\Release\qwen-codec.exe'
$model    = Join-Path $qwen 'models\qwen-talker-1.7b-base-Q8_0.gguf'
$tok      = Join-Path $qwen 'models\qwen-tokenizer-12hz-Q8_0.gguf'
$samples  = Join-Path $root 'data\samples'

try { New-Item -ItemType Directory -Path $samples -Force | Out-Null } catch {}

# Ordered so the file reads top-to-bottom in a sensible order.
$keys = [ordered]@{
    'NOVATTS_HOST'                      = '127.0.0.1'
    'NOVATTS_PORT'                      = '8765'
    'NOVATTS_QWEN_URL'                  = 'http://127.0.0.1:8080'
    'NOVATTS_QWEN_BIN'                  = $bin
    'NOVATTS_QWEN_MODEL'                = $model
    # tts-server --codec expects the tokenizer GGUF, NOT qwen-codec.exe.
    'NOVATTS_QWEN_CODEC'                = $tok
    # qwen-codec.exe is the separate .spk/.rvq extractor binary.
    'NOVATTS_QWEN_CODEC_BIN'            = $codecBin
    'NOVATTS_QWEN_AUTOSTART'            = '1'
    'NOVATTS_QWEN_AUTO_IMPORT_SAMPLES'  = '1'
    'NOVATTS_QWEN_SAMPLES_DIR'          = $samples
}

$targets = @(
    (Join-Path $root '.env'),
    (Join-Path $root 'backend\.env')
)

foreach ($envPath in $targets) {
    $dir = Split-Path -Parent $envPath
    if ($dir) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    $lines = @()
    if (Test-Path -LiteralPath $envPath) {
        $lines = @(Get-Content -LiteralPath $envPath -Encoding UTF8)
        if ($lines.Count -gt 0 -and $lines[0].Length -gt 0 -and $lines[0][0] -eq [char]0xFEFF) {
            $lines[0] = $lines[0].Substring(1)
        }
    }

    $list = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $lines) { $list.Add([string]$line) }

    foreach ($key in $keys.Keys) {
        $value = [string]$keys[$key]
        $found = $false
        for ($i = 0; $i -lt $list.Count; $i++) {
            if ($list[$i] -match ('^\s*' + [regex]::Escape($key) + '\s*=')) {
                $current = ($list[$i] -replace '^\s*[^=]+\s*=\s*', '').Trim().Trim('"')
                $repair = $false
                if ($Force) {
                    $repair = $true
                } elseif ([string]::IsNullOrWhiteSpace($current)) {
                    $repair = $true
                } elseif ($key -in @('NOVATTS_QWEN_BIN', 'NOVATTS_QWEN_CODEC_BIN') -and (Test-Path -LiteralPath $value)) {
                    # Engine binaries are version-locked to the AI-Tools build,
                    # so always use the installed copy when it exists.
                    $repair = $true
                } elseif ($key -in @('NOVATTS_QWEN_BIN', 'NOVATTS_QWEN_MODEL', 'NOVATTS_QWEN_CODEC', 'NOVATTS_QWEN_CODEC_BIN', 'NOVATTS_QWEN_SAMPLES_DIR') -and -not (Test-Path -LiteralPath $current)) {
                    # Stale path from another machine/drive (e.g. an old E:\
                    # model location) - replace it with the install path.
                    $repair = $true
                } elseif ($key -eq 'NOVATTS_QWEN_CODEC' -and $current -match '(?i)\.exe$') {
                    $repair = $true
                } elseif ($key -eq 'NOVATTS_QWEN_CODEC_BIN' -and $current -match '(?i)Program Files') {
                    $repair = $true
                } elseif ($key -eq 'NOVATTS_QWEN_AUTOSTART' -and $current -eq '0') {
                    $repair = $true
                }
                if ($repair) { $list[$i] = "$key=$value" }
                $found = $true
                break
            }
        }
        if (-not $found) { $list.Add("$key=$value") }
    }

    [System.IO.File]::WriteAllLines($envPath, $list, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "[NovaTTS] Wrote $envPath"
}

Write-Host "[NovaTTS] Qwen bin: $bin"

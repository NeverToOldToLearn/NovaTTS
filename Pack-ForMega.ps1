#Requires -Version 5.1
<#
.SYNOPSIS
  Pack a slim NovaTTS copy for MegaSync / cloud upload (~few MB, not ~10 GB).

.DESCRIPTION
  Zips project source + data while excluding rebuildable artifacts
  (Rust target/, node_modules, .venv, build caches, etc.).
  On the destination machine: extract, then run Install.cmd / setup.ps1.

.EXAMPLE
  .\Pack-ForMega.ps1
  .\Pack-ForMega.ps1 -IncludeGit
  .\Pack-ForMega.ps1 -OutDir D:\Backups
#>
param(
  [string]$OutDir = "",
  [switch]$IncludeGit,
  [switch]$IncludeToken
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT = $PSScriptRoot
if (-not $ROOT) { $ROOT = (Get-Location).Path }

function Info($m) { Write-Host "[NovaTTS] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[NovaTTS] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[NovaTTS] $m" -ForegroundColor Red; exit 1 }

if (-not $OutDir) { $OutDir = $ROOT }
if (-not (Test-Path -LiteralPath $OutDir)) {
  New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$zipName = "NovaTTS-slim-$stamp.zip"
$zipPath = Join-Path $OutDir $zipName

# Directory names that should never be packed (any depth)
$excludeDirNames = [System.Collections.Generic.HashSet[string]]::new(
  [StringComparer]::OrdinalIgnoreCase
)
@(
  "node_modules",
  ".venv",
  "venv",
  "target",
  "dist",
  "build",
  ".mypy_cache",
  ".ruff_cache",
  ".pytest_cache",
  "__pycache__",
  ".crush",
  "installer\Output"
) | ForEach-Object { [void]$excludeDirNames.Add($_) }

if (-not $IncludeGit) {
  [void]$excludeDirNames.Add(".git")
}

# Exact relative paths / files to skip
$excludeFiles = [System.Collections.Generic.HashSet[string]]::new(
  [StringComparer]::OrdinalIgnoreCase
)
@(
  "backend\.env",
  "NovaTTS.lnk",
  "Github-Token.txt"
) | ForEach-Object { [void]$excludeFiles.Add($_) }

if ($IncludeToken) {
  [void]$excludeFiles.Remove("Github-Token.txt")
}

$excludeNameGlobs = @(
  "*.log",
  "NovaTTS-Setup-*.exe",
  "NovaTTS-Portable-*.zip",
  "NovaTTS-slim-*.zip"
)

function Test-ExcludedPath([string]$rel) {
  $norm = $rel -replace "/", "\"
  if ($excludeFiles.Contains($norm)) { return $true }

  $parts = $norm -split "\\"
  foreach ($p in $parts) {
    if ($excludeDirNames.Contains($p)) { return $true }
  }

  $leaf = Split-Path $norm -Leaf
  foreach ($g in $excludeNameGlobs) {
    if ($leaf -like $g) { return $true }
  }
  return $false
}

Info "Root: $ROOT"
Info "Collecting files (excluding rebuildable artifacts)..."

$files = Get-ChildItem -LiteralPath $ROOT -Recurse -File -Force -ErrorAction SilentlyContinue |
  Where-Object {
    $rel = $_.FullName.Substring($ROOT.Length).TrimStart("\", "/")
    -not (Test-ExcludedPath $rel)
  }

if (-not $files -or $files.Count -eq 0) {
  Fail "No files to pack."
}

$bytes = ($files | Measure-Object -Property Length -Sum).Sum
Info ("Selected {0} files ({1:N1} MB)" -f $files.Count, ($bytes / 1MB))

if (Test-Path -LiteralPath $zipPath) {
  Remove-Item -LiteralPath $zipPath -Force
}

# Compress-Archive needs a staging folder for relative paths inside the zip
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("NovaTTS-slim-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stage -Force | Out-Null

try {
  Info "Staging copy..."
  $i = 0
  foreach ($f in $files) {
    $i++
    if ($i % 50 -eq 0) {
      Write-Progress -Activity "Staging NovaTTS slim pack" -Status "$i / $($files.Count)" `
        -PercentComplete ([int](100 * $i / $files.Count))
    }
    $rel = $f.FullName.Substring($ROOT.Length).TrimStart("\", "/")
    $dest = Join-Path $stage $rel
    $destDir = Split-Path $dest -Parent
    if (-not (Test-Path -LiteralPath $destDir)) {
      New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    Copy-Item -LiteralPath $f.FullName -Destination $dest -Force
  }
  Write-Progress -Activity "Staging NovaTTS slim pack" -Completed

  Info "Creating zip: $zipPath"
  Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zipPath -CompressionLevel Optimal

  $zipSize = (Get-Item -LiteralPath $zipPath).Length
  Info ("Done: {0} ({1:N1} MB)" -f $zipPath, ($zipSize / 1MB))
  Write-Host ""
  Write-Host "On the other PC:" -ForegroundColor Green
  Write-Host "  1. Extract the zip"
  Write-Host "  2. Run Install.cmd  (or setup.ps1)"
  Write-Host "  3. Point backend\.env at Qwen model paths if you want TTS"
  if (-not $IncludeGit) {
    Warn "Git history was excluded (use -IncludeGit to keep .git)."
  }
  if (-not $IncludeToken -and (Test-Path (Join-Path $ROOT "Github-Token.txt"))) {
    Warn "Github-Token.txt was excluded (use -IncludeToken to keep it)."
  }
}
finally {
  if (Test-Path -LiteralPath $stage) {
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
  }
}

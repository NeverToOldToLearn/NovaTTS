<#
.SYNOPSIS
    Installs deps, builds whisper.cpp + qwentts.cpp (Vulkan), downloads models.
    Safe for Inno Setup [Run] and interactive use.

.PARAMETER Skip
    Skip compile if binaries already exist; still ensure models if missing.

.PARAMETER NonInteractive
    No Read-Host prompts (required when launched from Inno Setup).

.NOTES
    Exit codes: 0 = success, 1 = failure.
    ASCII-only strings to avoid Windows encoding/parse errors.
#>

param(
    [switch]$Skip,
    [switch]$NonInteractive
)

# Bootstrap LOG FIRST (before StrictMode / Stop)
$Script:LogDir = Join-Path $env:LOCALAPPDATA 'NovaTTS\logs'
try { New-Item -ItemType Directory -Path $Script:LogDir -Force | Out-Null } catch {}
$Script:LogPath = Join-Path $Script:LogDir 'AIToolsLog.txt'
$Script:StatusPath = Join-Path $Script:LogDir 'AIToolsStatus.txt'
try {
    Add-Content -Path $Script:LogPath -Value ("[" + (Get-Date -Format 'o') + "] SCRIPT_START pid=$PID") -Encoding UTF8
} catch {}

try { Set-ExecutionPolicy Bypass -Scope Process -Force -ErrorAction SilentlyContinue } catch {}
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $NonInteractive) {
    try {
        if ($null -eq [Console]::WindowHeight) { $NonInteractive = $true }
    } catch { $NonInteractive = $true }
}

$Script:ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-IsAdminEarly {
    try {
        return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}

# Always use LocalAppData path (no spaces). Program Files broke cmake -S/-B splitting.
$Script:AIHome = Join-Path $env:LOCALAPPDATA 'NovaTTS\AI-Tools'
$Script:WhisperHome = Join-Path $Script:AIHome 'whisper.cpp'
$Script:QwenHome = Join-Path $Script:AIHome 'qwentts.cpp'
$Script:VulkanRoot = 'C:\VulkanSDK'

try {
    $boot = "[" + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + "] boot AIHome=$($Script:AIHome) Admin=$(Test-IsAdminEarly)"
    Add-Content -Path $Script:LogPath -Value $boot -Encoding UTF8
} catch {}

function Write-Status {
    param([string]$Phase, [string]$Detail = '')
    $line = (Get-Date -Format 'HH:mm:ss') + " | $Phase | $Detail"
    Set-Content -Path $Script:StatusPath -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
}

function Write-Log {
    param(
        [AllowEmptyString()]
        [string]$Message = "",
        [ValidateSet('Info', 'Warn', 'Error', 'Success')]$Level = 'Info'
    )
    if ([string]::IsNullOrWhiteSpace($Message)) { return }
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$ts] [$Level] $Message"
    Add-Content -Path $Script:LogPath -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    $fc = switch ($Level) {
        'Success' { 'Green' }
        'Warn'    { 'Yellow' }
        'Error'   { 'Red' }
        default   { 'White' }
    }
    if ($Level -eq 'Warn') { Write-Warning $Message }
    elseif ($Level -eq 'Error') { Write-Host $Message -ForegroundColor Red }
    else { Write-Host $Message -ForegroundColor $fc }
}

function Write-Step {
    param([string]$Title)
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " $Title" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Status -Phase $Title
}

function Test-IsAdmin {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-Dependency {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-MsvcTools {
    # True when a Visual Studio / BuildTools instance has the C++ toolset.
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path -LiteralPath $vswhere) {
        $path = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
        if (-not [string]::IsNullOrWhiteSpace($path)) { return $true }
    }
    return $false
}

function Invoke-WingetElevated {
    # BuildTools / Vulkan installers need admin. UAC elevation keeps the same
    # user profile, so paths under $env:LOCALAPPDATA stay valid.
    param([Parameter(Mandatory)][string[]]$Arguments)
    if (Test-IsAdmin) {
        & winget @Arguments
        return [int]$LASTEXITCODE
    }
    $quoted = ($Arguments | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join ' '
    $cmd = "& winget $quoted; exit `$LASTEXITCODE"
    try {
        Write-Log "Elevating winget: $quoted" -Level Info
        # -EncodedCommand avoids all nested-quote problems with Start-Process.
        $b64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))
        $p = Start-Process -FilePath 'powershell.exe' `
            -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $b64) `
            -Verb RunAs -Wait -PassThru
        return [int]$p.ExitCode
    } catch {
        Write-Log "Elevation failed for winget: $($_.Exception.Message)" -Level Warn
        return 1
    }
}

function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    $argList = @($Arguments | ForEach-Object { [string]$_ })
    $shown = ($argList | ForEach-Object {
        if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
    }) -join ' '
    Write-Log ("RUN: $FilePath $shown") -Level Info
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $FilePath @argList 2>&1
        $ec = $LASTEXITCODE
        if ($null -eq $ec) { $ec = 0 }
        if ($null -ne $output) {
            foreach ($line in @($output)) {
                if ($null -eq $line) { continue }
                $s = $line.ToString()
                if ([string]::IsNullOrWhiteSpace($s)) { continue }
                Write-Log $s -Level Info
            }
        }
        return [int]$ec
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Get-VulkanSdkPath {
    # Respect an existing SDK installed outside C:\VulkanSDK.
    if ($env:VULKAN_SDK -and (Test-Path -LiteralPath $env:VULKAN_SDK)) { return $env:VULKAN_SDK }
    if (-not (Test-Path -LiteralPath $Script:VulkanRoot)) { return $null }
    $latest = Get-ChildItem -LiteralPath $Script:VulkanRoot -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($null -eq $latest) { return $null }
    return $latest.FullName
}

function Ensure-AIHome {
    if (-not (Test-Path -LiteralPath $Script:AIHome)) {
        New-Item -ItemType Directory -Path $Script:AIHome -Force | Out-Null
    }
}

function Test-QwenReady {
    $needed = @(
        (Join-Path $Script:QwenHome 'build\Release\tts-server.exe'),
        (Join-Path $Script:QwenHome 'build\Release\qwen-codec.exe'),
        (Join-Path $Script:QwenHome 'models\qwen-talker-1.7b-base-Q8_0.gguf'),
        (Join-Path $Script:QwenHome 'models\qwen-tokenizer-12hz-Q8_0.gguf')
    )
    foreach ($p in $needed) {
        if (-not (Test-Path -LiteralPath $p)) { return $false }
    }
    return $true
}

function Install-VulkanSdk {
    Write-Step "Vulkan SDK"
    $sdk = Get-VulkanSdkPath
    if ($sdk) {
        $env:VULKAN_SDK = $sdk
        Write-Log "Vulkan SDK found: $sdk" -Level Success
        return $true
    }
    try {
        Write-Log "Download Vulkan SDK 1.4.321.1..."
        Write-Status -Phase "Vulkan SDK" -Detail "downloading"
        $ver = '1.4.321.1'
        $installerUrl = "https://sdk.lunarg.com/sdk/download/$ver/windows/vulkansdk-windows-X64-$ver.exe"
        $installerFile = Join-Path $env:TEMP "vulkansdk-windows-X64-$ver.exe"
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerFile -UseBasicParsing
        Write-Log "Silent install Vulkan SDK..."
        Write-Status -Phase "Vulkan SDK" -Detail "installing"
        # The SDK installer writes to C:\VulkanSDK and needs admin on a fresh
        # machine. Elevate just this process when the script is not elevated.
        $spArgs = @{ FilePath = $installerFile; ArgumentList = '/S'; Wait = $true; PassThru = $true }
        if (-not (Test-IsAdmin)) { $spArgs.Verb = 'RunAs' }
        $proc = Start-Process @spArgs
        if ($proc.ExitCode -ne 0) { throw "Vulkan SDK installer exit $($proc.ExitCode)" }
        $sdk = Get-VulkanSdkPath
        if (-not $sdk) { throw "Vulkan SDK not found under $Script:VulkanRoot after install." }
        $env:VULKAN_SDK = $sdk
        Write-Log "Vulkan SDK: $sdk" -Level Success
        return $true
    }
    catch {
        Write-Log "Vulkan SDK failed: $($_.Exception.Message)" -Level Error
        Write-Log "Manual: https://vulkan.lunarg.com/sdk/home" -Level Warn
        return $false
    }
}

function Install-Dependencies {
    Write-Step "Dependencies (winget)"
    if (-not (Test-Dependency winget)) {
        throw "winget missing - install App Installer from the Microsoft Store."
    }
    # CMake needs an MSVC toolset on Windows. Install BuildTools + the C++
    # workload when no Visual Studio instance provides it.
    if (Test-MsvcTools) {
        Write-Log "MSVC C++ toolset present" -Level Success
    } else {
        Write-Log "Installing MSVC 2022 BuildTools (C++ workload)..."
        Write-Status -Phase "winget" -Detail "MSVC BuildTools"
        $ec = Invoke-WingetElevated -Arguments @(
            'install', '--id', 'Microsoft.VisualStudio.2022.BuildTools', '-e',
            '--silent', '--accept-package-agreements', '--accept-source-agreements',
            '--disable-interactivity', '--source', 'winget',
            '--override', '--quiet --wait --norestart --nocache --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended'
        )
        if ($ec -ne 0) {
            Write-Log "MSVC BuildTools winget exit $ec" -Level Warn
        } elseif (-not (Test-MsvcTools)) {
            Write-Log "MSVC BuildTools installed but vswhere still reports no C++ toolset" -Level Warn
        } else {
            Write-Log "MSVC BuildTools done" -Level Success
        }
    }
    $packages = @(
        @{ Id = 'Kitware.CMake';      Cmd = 'cmake';  Label = 'CMake' }
        @{ Id = 'Git.Git';            Cmd = 'git';    Label = 'Git' }
        @{ Id = 'Python.Python.3.12'; Cmd = 'python'; Label = 'Python' }
        @{ Id = 'OpenJS.NodeJS.LTS';  Cmd = 'node';   Label = 'Node.js' }
        @{ Id = 'Rustlang.Rustup';    Cmd = 'rustc';  Label = 'Rust' }
    )
    foreach ($pkg in $packages) {
        if (Test-Dependency $pkg.Cmd) {
            Write-Log "$($pkg.Label) present" -Level Success
            continue
        }
        Write-Log "Installing $($pkg.Label)..."
        Write-Status -Phase "winget" -Detail $pkg.Label
        & winget install --id $pkg.Id --silent --accept-package-agreements --accept-source-agreements --disable-interactivity --source winget
        if ($LASTEXITCODE -ne 0) {
            Write-Log "winget exit $($LASTEXITCODE) for $($pkg.Label)" -Level Warn
        } else {
            Write-Log "$($pkg.Label) done" -Level Success
        }
    }
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machinePath;$userPath"
}

function Install-PythonHuggingface {
    Write-Step "huggingface_hub"
    if (-not (Test-Dependency python)) { throw "python not in PATH" }
    Write-Status -Phase "pip" -Detail "huggingface_hub"
    # huggingface-hub 2.x has no [cli] extra; WARNING on stderr + ErrorAction Stop
    # would abort the whole script before any cpp build.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & python -m pip install --upgrade huggingface_hub 2>&1 | ForEach-Object {
            if ($null -eq $_) { return }
            $line = $_.ToString()
            if ([string]::IsNullOrWhiteSpace($line)) { return }
            if ($line -match "ERROR") { Write-Log $line -Level Error }
            else { Write-Log $line -Level Info }
        }
    } finally {
        $ErrorActionPreference = $prev
    }
    # Verify import (do not trust pip exit code alone)
    & python -c "import huggingface_hub; print(huggingface_hub.__version__)"
    if ($LASTEXITCODE -ne 0) { throw "huggingface_hub import failed after pip install" }
    Write-Log "huggingface_hub done" -Level Success
}

function Invoke-HfDownload {
    param(
        [Parameter(Mandatory)][string]$Repo,
        [Parameter(Mandatory)][string[]]$Files,
        [Parameter(Mandatory)][string]$LocalDir
    )
    New-Item -ItemType Directory -Path $LocalDir -Force | Out-Null
    Write-Log "Download from HF repo=$Repo dir=$LocalDir files=$($Files -join ', ')" -Level Info

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $hfCmd = $null
        foreach ($name in @("hf", "huggingface-cli")) {
            $c = Get-Command $name -ErrorAction SilentlyContinue
            if ($c) { $hfCmd = $c.Source; break }
        }

        if ($hfCmd) {
            Write-Log "Using CLI: $hfCmd" -Level Info
            $args = @("download", $Repo) + @($Files) + @("--local-dir", $LocalDir)
            $output = & $hfCmd @args 2>&1
            $ec = $LASTEXITCODE
            if ($null -eq $ec) { $ec = 0 }
            foreach ($line in @($output)) {
                if ($null -eq $line) { continue }
                $s = $line.ToString()
                if (-not [string]::IsNullOrWhiteSpace($s)) { Write-Log $s -Level Info }
            }
            if ($ec -ne 0) {
                Write-Log "CLI exit $ec - falling back to python hf_hub_download" -Level Warn
            } else {
                # confirm files landed
                $missing = @($Files | Where-Object { -not (Test-Path -LiteralPath (Join-Path $LocalDir $_)) })
                if ($missing.Count -eq 0) { return }
                Write-Log "CLI reported ok but missing: $($missing -join ', ')" -Level Warn
            }
        }

        foreach ($file in $Files) {
            $dest = Join-Path $LocalDir $file
            if (Test-Path -LiteralPath $dest) {
                Write-Log "Already present: $dest" -Level Success
                continue
            }
            Write-Log "python hf_hub_download: $file ..." -Level Info
            $code = "from huggingface_hub import hf_hub_download; print(hf_hub_download(repo_id=r'$Repo', filename=r'$file', local_dir=r'$LocalDir'))"
            $output = & python -c $code 2>&1
            $ec = $LASTEXITCODE
            if ($null -eq $ec) { $ec = 0 }
            foreach ($line in @($output)) {
                if ($null -eq $line) { continue }
                $s = $line.ToString()
                if (-not [string]::IsNullOrWhiteSpace($s)) { Write-Log $s -Level Info }
            }
            if ($ec -ne 0 -or -not (Test-Path -LiteralPath $dest)) {
                throw "python download failed for $Repo / $file (exit=$ec exists=$(Test-Path -LiteralPath $dest))"
            }
            Write-Log "Downloaded: $dest" -Level Success
        }
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Build-Whisper {
    Write-Step "whisper.cpp (Vulkan)"
    Ensure-AIHome
    if (-not (Test-Path -LiteralPath $Script:WhisperHome)) {
        Write-Status -Phase "whisper.cpp" -Detail "git clone"
        $ec = Invoke-Native -FilePath git -Arguments @('clone', '--depth', '1', 'https://github.com/ggml-org/whisper.cpp.git', $Script:WhisperHome)
        if ($ec -ne 0) { throw "git clone whisper.cpp failed (exit $ec)" }
    } else {
        Write-Log "whisper.cpp exists: $Script:WhisperHome" -Level Warn
    }
    $buildDir = Join-Path $Script:WhisperHome 'build'
    Write-Status -Phase "whisper.cpp" -Detail "cmake configure"
    $ec = Invoke-Native -FilePath cmake -Arguments @('-S', $Script:WhisperHome, '-B', $buildDir, '-DGGML_VULKAN=ON', '-DGGML_AVX512=OFF')
    if ($ec -ne 0) { throw "cmake configure whisper.cpp failed (exit $ec)" }
    Write-Status -Phase "whisper.cpp" -Detail "cmake build"
    $ec = Invoke-Native -FilePath cmake -Arguments @('--build', $buildDir, '--config', 'Release', '--target', 'whisper-cli')
    if ($ec -ne 0) { throw "cmake build whisper-cli failed (exit $ec)" }
    Write-Log "whisper-cli built" -Level Success
    # Official whisper.cpp helper: models\download-ggml-model.cmd <model>
    # e.g. tiny | base | small | medium | large-v3 | large-v3-turbo
    $modelsDir = Join-Path $Script:WhisperHome 'models'
    $whisperModel = 'tiny'
    if ($env:NOVATTS_WHISPER_MODEL) { $whisperModel = $env:NOVATTS_WHISPER_MODEL }
    $modelBin = Join-Path $modelsDir ("ggml-" + $whisperModel + ".bin")
    # large-v3-turbo file name is still ggml-large-v3-turbo.bin
    if (-not (Test-Path -LiteralPath $modelBin)) {
        Write-Status -Phase "whisper.cpp" -Detail ("download ggml-" + $whisperModel)
        $dlCmd = Join-Path $modelsDir 'download-ggml-model.cmd'
        $dlSh = Join-Path $modelsDir 'download-ggml-model.sh'
        try {
            if (Test-Path -LiteralPath $dlCmd) {
                Write-Log "Running: $dlCmd $whisperModel" -Level Info
                $prev = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                try {
                    $output = & cmd.exe /c "`"$dlCmd`" $whisperModel" 2>&1
                    $ec = $LASTEXITCODE
                    foreach ($line in @($output)) {
                        if ($null -eq $line) { continue }
                        $s = $line.ToString()
                        if (-not [string]::IsNullOrWhiteSpace($s)) { Write-Log $s -Level Info }
                    }
                    if ($ec -ne 0) { Write-Log "download-ggml-model.cmd exit $ec" -Level Warn }
                } finally { $ErrorActionPreference = $prev }
            } elseif (Test-Path -LiteralPath $dlSh) {
                Write-Log "download-ggml-model.cmd missing; trying HF ggml-tiny.bin fallback" -Level Warn
                Invoke-HfDownload -Repo 'ggerganov/whisper.cpp' -Files @('ggml-tiny.bin') -LocalDir $modelsDir
            } else {
                Write-Log "No download-ggml-model.cmd in models - HF fallback ggml-tiny.bin" -Level Warn
                Invoke-HfDownload -Repo 'ggerganov/whisper.cpp' -Files @('ggml-tiny.bin') -LocalDir $modelsDir
            }
            if (Test-Path -LiteralPath $modelBin) {
                Write-Log "Whisper model OK: $modelBin" -Level Success
            } elseif (Test-Path -LiteralPath (Join-Path $modelsDir 'ggml-tiny.bin')) {
                Write-Log "Whisper ggml-tiny.bin OK (fallback)" -Level Success
            } else {
                Write-Log "Whisper model not found after download (non-fatal)" -Level Warn
            }
        } catch {
            Write-Log "whisper model download failed (non-fatal): $($_.Exception.Message)" -Level Warn
        }
    } else {
        Write-Log "Whisper model OK: $modelBin" -Level Success
    }
    Write-Log "Build-Whisper finished - next: qwentts.cpp" -Level Info
}

function Build-QwenTts {
    Write-Step "qwentts.cpp (Vulkan)"
    Ensure-AIHome
    if (-not (Test-Path -LiteralPath $Script:QwenHome)) {
        Write-Status -Phase "qwentts.cpp" -Detail "git clone + submodules"
        $ec = Invoke-Native -FilePath git -Arguments @('clone', '--recurse-submodules', '--depth', '1', 'https://github.com/ServeurpersoCom/qwentts.cpp.git', $Script:QwenHome)
        if ($ec -ne 0) { throw "git clone qwentts.cpp failed (exit $ec)" }
    } else {
        Write-Log "qwentts.cpp exists: $Script:QwenHome" -Level Warn
        Push-Location $Script:QwenHome
        try { $null = Invoke-Native -FilePath git -Arguments @('submodule', 'update', '--init', '--recursive') } finally { Pop-Location }
    }
    $buildDir = Join-Path $Script:QwenHome 'build'
    Write-Status -Phase "qwentts.cpp" -Detail "cmake configure"
    $ec = Invoke-Native -FilePath cmake -Arguments @('-S', $Script:QwenHome, '-B', $buildDir, '-DGGML_VULKAN=ON')
    if ($ec -ne 0) { throw "cmake configure qwentts.cpp failed (exit $ec)" }
    Write-Status -Phase "qwentts.cpp" -Detail "cmake build (long: 10-40 min)"
    $ec = Invoke-Native -FilePath cmake -Arguments @('--build', $buildDir, '--config', 'Release')
    if ($ec -ne 0) { throw "cmake build qwentts.cpp failed (exit $ec)" }
    Write-Log "qwentts binaries OK" -Level Success
    $modelsDir = Join-Path $Script:QwenHome 'models'
    $talker = Join-Path $modelsDir 'qwen-talker-1.7b-base-Q8_0.gguf'
    $tok = Join-Path $modelsDir 'qwen-tokenizer-12hz-Q8_0.gguf'
    if (-not ((Test-Path -LiteralPath $talker) -and (Test-Path -LiteralPath $tok))) {
        Write-Status -Phase "qwentts.cpp" -Detail "download GGUF models"
        Invoke-HfDownload `
            -Repo 'Serveurperso/Qwen3-TTS-GGUF' `
            -Files @('qwen-talker-1.7b-base-Q8_0.gguf', 'qwen-tokenizer-12hz-Q8_0.gguf') `
            -LocalDir $modelsDir
    }
    Write-Log "Qwen GGUF models OK" -Level Success
}


function Write-NovaTTSEnv {
    Write-Step "Write NovaTTS .env (Qwen paths)"
    $bin = Join-Path $Script:QwenHome 'build\Release\tts-server.exe'
    $codecBin = Join-Path $Script:QwenHome 'build\Release\qwen-codec.exe'
    $model = Join-Path $Script:QwenHome 'models\qwen-talker-1.7b-base-Q8_0.gguf'
    $tok = Join-Path $Script:QwenHome 'models\qwen-tokenizer-12hz-Q8_0.gguf'
    $samples = Join-Path $env:LOCALAPPDATA 'NovaTTS\data\samples'
    try { New-Item -ItemType Directory -Path $samples -Force | Out-Null } catch {}

    $targets = @(
        (Join-Path $env:LOCALAPPDATA 'NovaTTS\.env'),
        (Join-Path $env:LOCALAPPDATA 'NovaTTS\backend\.env')
    )
    # Also next to this script (install root)
    if ($Script:ScriptDir) {
        $targets += (Join-Path $Script:ScriptDir '.env')
        $targets += (Join-Path $Script:ScriptDir 'backend\.env')
    }

    $keys = @{
        'NOVATTS_QWEN_BIN'        = $bin
        'NOVATTS_QWEN_MODEL'      = $model
        # tts-server --codec expects the tokenizer GGUF, NOT qwen-codec.exe.
        'NOVATTS_QWEN_CODEC'      = $tok
        # qwen-codec.exe is the separate .spk/.rvq extractor binary.
        'NOVATTS_QWEN_CODEC_BIN'  = $codecBin
        'NOVATTS_QWEN_URL'        = 'http://127.0.0.1:8080'
        'NOVATTS_QWEN_AUTOSTART'  = '1'
        'NOVATTS_QWEN_SAMPLES_DIR'= $samples
    }

    foreach ($envPath in ($targets | Select-Object -Unique)) {
        $dir = Split-Path -Parent $envPath
        if (-not (Test-Path -LiteralPath $dir)) {
            try { New-Item -ItemType Directory -Path $dir -Force | Out-Null } catch { continue }
        }
        $lines = @()
        if (Test-Path -LiteralPath $envPath) {
            try { $lines = Get-Content -LiteralPath $envPath -ErrorAction SilentlyContinue } catch { $lines = @() }
        }
        if ($null -eq $lines) { $lines = @() }
        $list = [System.Collections.Generic.List[string]]::new()
        foreach ($ln in $lines) { $list.Add([string]$ln) }

        foreach ($k in $keys.Keys) {
            $val = [string]$keys[$k]
            $found = $false
            for ($i = 0; $i -lt $list.Count; $i++) {
                $s = $list[$i].Trim()
                if ($s.StartsWith($k + '=') -or $s.StartsWith($k + ' ')) {
                    $list[$i] = "$k=$val"
                    $found = $true
                    break
                }
            }
            if (-not $found) { $list.Add("$k=$val") }
        }
        # NOVATTS_QWEN_CODEC now holds the tokenizer GGUF (see $keys).

        try {
            # UTF-8 WITHOUT BOM: a BOM makes python-dotenv prefix the first
            # key with U+FEFF, so that setting is silently ignored.
            [System.IO.File]::WriteAllLines($envPath, $list, (New-Object System.Text.UTF8Encoding($false)))
            Write-Log "Wrote $envPath" -Level Success
        } catch {
            Write-Log "Could not write $envPath : $($_.Exception.Message)" -Level Warn
        }
    }
    Write-Log "Qwen bin=$bin" -Level Info
    Write-Log "Restart NovaTTS (GUI + backend) so Settings pick up .env" -Level Info
}


function Verify-AITools {
    Write-Step "Verify"
    $items = @(
        (Join-Path $Script:QwenHome 'build\Release\tts-server.exe'),
        (Join-Path $Script:QwenHome 'build\Release\qwen-codec.exe'),
        (Join-Path $Script:QwenHome 'models\qwen-talker-1.7b-base-Q8_0.gguf'),
        (Join-Path $Script:QwenHome 'models\qwen-tokenizer-12hz-Q8_0.gguf')
    )
    $fail = 0
    foreach ($item in $items) {
        if (Test-Path -LiteralPath $item) {
            Write-Log "OK  $item" -Level Success
        } else {
            Write-Log "MISSING  $item" -Level Error
            $fail++
        }
    }
    if ($fail -gt 0) {
        throw "Verify: $fail file(s) missing - see $Script:LogPath"
    }
}

$exitCode = 0
try {
    if (-not (Test-IsAdmin)) {
        Write-Log "Not admin - using user-local AIHome if set. Elevated recommended for Vulkan SDK." -Level Warn
    }

    if (-not $Skip -and (Test-QwenReady)) {
        $Skip = $true
        Write-Log "Existing Qwen build/models found - skip compile." -Level Info
    }

    Write-Step "Install-AITools started"
    Write-Log "NonInteractive=$NonInteractive Skip=$Skip Log=$Script:LogPath"
    Write-Status -Phase "start" -Detail "Skip=$Skip"

    if (-not $Skip) {
        if (-not (Install-VulkanSdk)) {
            throw "Vulkan SDK is required for the Vulkan build. Install it from https://vulkan.lunarg.com/sdk/home and re-run."
        }
        Install-Dependencies
        Install-PythonHuggingface
        Build-Whisper
        Write-Log "Starting Build-QwenTts..." -Level Info
        Build-QwenTts
        Write-Log "Build-QwenTts returned" -Level Info
    } else {
        Install-PythonHuggingface
        $modelsDir = Join-Path $Script:QwenHome 'models'
        $talker = Join-Path $modelsDir 'qwen-talker-1.7b-base-Q8_0.gguf'
        $tok = Join-Path $modelsDir 'qwen-tokenizer-12hz-Q8_0.gguf'
        if (-not ((Test-Path -LiteralPath $talker) -and (Test-Path -LiteralPath $tok))) {
            Write-Status -Phase "models" -Detail "download GGUF"
            Invoke-HfDownload `
                -Repo 'Serveurperso/Qwen3-TTS-GGUF' `
                -Files @('qwen-talker-1.7b-base-Q8_0.gguf', 'qwen-tokenizer-12hz-Q8_0.gguf') `
                -LocalDir $modelsDir
        }
    }

    Verify-AITools
    Write-NovaTTSEnv
    Write-Step "Done"
    Write-Log "Success. Log: $Script:LogPath" -Level Success
    Write-Status -Phase "done" -Detail "ok"
    $exitCode = 0
}
catch {
    $msg = $_.Exception.Message
    if ([string]::IsNullOrWhiteSpace($msg)) { $msg = $_.ToString() }
    if ([string]::IsNullOrWhiteSpace($msg)) { $msg = "Unknown error (empty exception message)" }
    Write-Log "ERROR: $msg" -Level Error
    try { Write-Log ("ERROR detail: " + $_.ScriptStackTrace) -Level Error } catch {}
    Write-Status -Phase "failed" -Detail $msg
    $exitCode = 1
}
finally {
    Write-Host ""
    Write-Host "------------------------------------------------------------" -ForegroundColor Yellow
    Write-Host "Log: $Script:LogPath" -ForegroundColor Yellow
    Write-Host "Status: $Script:StatusPath" -ForegroundColor Yellow
    Write-Host "------------------------------------------------------------" -ForegroundColor Yellow
    if (-not $NonInteractive) {
        Write-Host "Press Enter to close..." -ForegroundColor Yellow
        try { Read-Host | Out-Null } catch { }
    }
}

exit $exitCode

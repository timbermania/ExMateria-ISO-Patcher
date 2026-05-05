<#
.SYNOPSIS
    End-to-end ExMateria installer for Windows.

.DESCRIPTION
    Brings a fresh Windows machine all the way from "nothing installed" to
    "FFT music plays in your DAW", in one shot:

      1. Installs Chocolatey, then CMake + Visual Studio 2022 Build Tools
         (C++ workload) + Git via choco.
      2. Installs uv (the Python tool installer).
      3. uv-installs ExMateria-ISO-Patcher itself, exposing
         `fft-iso-patcher extract` on PATH.
      4. Runs `fft-iso-patcher extract` against the FFT ISO you point it at,
         dumping the disc tree into the standard exmateria assets dir
         (%APPDATA%\exmateria\assets\).
      5. Clones ExMateria-DAW-Plugin and runs the CMake build (which
         pulls JUCE 8.0.4 via FetchContent on first configure).
      6. Copies the resulting .vst3 bundle into your per-user VST3 folder.

    Skips steps that are already done. Re-runnable.

.PARAMETER IsoPath
    Path to your Final Fantasy Tactics .bin / .iso. You supply this — the
    script never downloads game data.

.PARAMETER WorkDir
    Where the DAW-Plugin repo gets cloned and built. Defaults to
    `$env:USERPROFILE\exmateria-build`. Stays around so re-runs are fast.

.PARAMETER SkipPlugin
    Stop after extracting the disc — don't build the DAW plugin. Useful
    if you only want the patcher / extractor and not the audio plugin.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install_exmateria.ps1 `
        -IsoPath "C:\Games\FFT\Final Fantasy Tactics.bin"

.NOTES
    Run from an *elevated* PowerShell (the choco installs need admin).
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $IsoPath,

    [string] $WorkDir = (Join-Path $env:USERPROFILE 'exmateria-build'),

    [switch] $SkipPlugin
)

$ErrorActionPreference = 'Stop'

function Write-Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Test-Command($name) {
    $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Assert-Admin {
    $current = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($current)
    if (-not $principal.IsInRole(
            [System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'This script needs to run from an elevated PowerShell (right-click → Run as Administrator).'
    }
}

function Refresh-EnvPath {
    $machine = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user    = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

# ----- preflight ------------------------------------------------------------

if (-not (Test-Path $IsoPath)) {
    throw "ISO not found at: $IsoPath"
}
Assert-Admin

# ----- 1. Chocolatey --------------------------------------------------------

if (-not (Test-Command 'choco')) {
    Write-Step 'Installing Chocolatey'
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol =
        [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString(
        'https://community.chocolatey.org/install.ps1'))
    Refresh-EnvPath
} else {
    Write-Step 'Chocolatey already installed'
}

# ----- 2. CMake + Build Tools + Git -----------------------------------------

Write-Step 'Installing build toolchain via Chocolatey (skips already-installed)'
choco install -y --no-progress cmake git
choco install -y --no-progress visualstudio2022buildtools `
    --package-parameters '--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended'
Refresh-EnvPath

# ----- 3. uv ----------------------------------------------------------------

if (-not (Test-Command 'uv')) {
    Write-Step 'Installing uv'
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    Refresh-EnvPath
} else {
    Write-Step 'uv already installed'
}

# ----- 4. ExMateria-ISO-Patcher --------------------------------------------

Write-Step 'Installing exmateria-iso-patcher (provides fft-iso-patcher extract)'
uv tool install --reinstall `
    git+https://github.com/timbermania/ExMateria-ISO-Patcher
Refresh-EnvPath

if (-not (Test-Command 'fft-iso-patcher')) {
    throw "fft-iso-patcher not on PATH after install. Try opening a new PowerShell."
}

# ----- 5. Extract the disc --------------------------------------------------

Write-Step "Extracting $IsoPath to the standard exmateria assets dir"
fft-iso-patcher extract $IsoPath --force

if ($SkipPlugin) {
    Write-Step 'Done (--SkipPlugin set; the DAW plugin was not built).'
    return
}

# ----- 6. Clone + build the DAW plugin --------------------------------------

if (-not (Test-Path $WorkDir)) {
    New-Item -ItemType Directory -Path $WorkDir | Out-Null
}

$pluginDir = Join-Path $WorkDir 'ExMateria-DAW-Plugin'
if (Test-Path $pluginDir) {
    Write-Step "Updating existing plugin clone at $pluginDir"
    git -C $pluginDir fetch --quiet
    git -C $pluginDir reset --hard origin/main
} else {
    Write-Step "Cloning ExMateria-DAW-Plugin into $pluginDir"
    git clone --depth 1 https://github.com/timbermania/ExMateria-DAW-Plugin $pluginDir
}

Write-Step 'Configuring CMake (fetches JUCE 8.0.4 on first run)'
cmake -S $pluginDir -B (Join-Path $pluginDir 'build') -DCMAKE_BUILD_TYPE=Release

Write-Step 'Building the plugin (this takes a few minutes the first time)'
cmake --build (Join-Path $pluginDir 'build') --config Release

# ----- 7. Install the .vst3 bundle ------------------------------------------

$vst3Dest = Join-Path $env:LOCALAPPDATA 'Programs\Common\VST3'
if (-not (Test-Path $vst3Dest)) {
    New-Item -ItemType Directory -Path $vst3Dest -Force | Out-Null
}

$vst3Bundles = Get-ChildItem -Path (Join-Path $pluginDir 'build') `
    -Recurse -Directory -Filter '*.vst3' -ErrorAction SilentlyContinue
if (-not $vst3Bundles) {
    throw "Build finished but no .vst3 bundle landed under $pluginDir\build"
}

Write-Step "Installing VST3 bundle(s) to $vst3Dest"
foreach ($bundle in $vst3Bundles) {
    $target = Join-Path $vst3Dest $bundle.Name
    if (Test-Path $target) {
        Remove-Item -Path $target -Recurse -Force
    }
    Copy-Item -Path $bundle.FullName -Destination $target -Recurse -Force
    Write-Host "    $($bundle.Name)" -ForegroundColor Green
}

Write-Step 'All done.'
Write-Host ""
Write-Host 'Next steps:' -ForegroundColor Yellow
Write-Host '  1. Restart your DAW (REAPER, etc.) and rescan plugins.'
Write-Host '  2. Drop the FFT plugin on a track.'
Write-Host '  3. Pick an SMD file (e.g. MUSIC_31.SMD for "Trisection").'
Write-Host '  4. Press play.'

<#
.SYNOPSIS
    ExMateria installer (prebuilt, fast path).

.DESCRIPTION
    Brings a Windows machine from "nothing installed" to "FFT music plays
    in your DAW" by downloading the prebuilt GitHub Releases — no build
    tools required. Specifically:

      1. Installs uv (Python tool installer) via the official one-liner.
      2. uv tool installs the latest exmateria-iso-patcher wheel from
         GitHub Releases (no compile step).
      3. Runs `fft-iso-patcher extract` against the FFT ISO you provide,
         dumping the disc tree into the standard exmateria assets dir
         (%APPDATA%\exmateria\assets\).
      4. Downloads the latest exmateria-daw-plugin Windows .vst3 zip
         from GitHub Releases and unzips into your per-user VST3 folder.

    Skips steps that are already done. No admin needed (everything goes
    into per-user locations). For the build-from-source variant, see
    install_exmateria_from_source.ps1 in this directory.

.PARAMETER IsoPath
    Path to your Final Fantasy Tactics .bin / .iso. You supply this — the
    script never downloads game data.

.PARAMETER SkipPlugin
    Stop after extracting the disc — don't fetch / install the DAW plugin.

.PARAMETER VST3Dir
    Override the VST3 install folder. Defaults to
    `%LOCALAPPDATA%\Programs\Common\VST3\`.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install_exmateria.ps1 `
        -IsoPath "C:\Games\FFT\Final Fantasy Tactics.bin"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $IsoPath,

    [switch] $SkipPlugin,

    [string] $VST3Dir = (Join-Path $env:LOCALAPPDATA 'Programs\Common\VST3')
)

$ErrorActionPreference = 'Stop'

$IsoPatcherRepo = 'timbermania/ExMateria-ISO-Patcher'
$DawPluginRepo  = 'timbermania/ExMateria-DAW-Plugin'

function Write-Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Test-Command($name) {
    $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Refresh-EnvPath {
    $machine = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user    = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Get-LatestRelease($repo) {
    Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{
        'User-Agent' = 'install_exmateria.ps1'
    }
}

# ----- preflight ------------------------------------------------------------

if (-not (Test-Path $IsoPath)) {
    throw "ISO not found at: $IsoPath"
}

# ----- 1. uv ----------------------------------------------------------------

if (-not (Test-Command 'uv')) {
    Write-Step 'Installing uv (no admin required)'
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    Refresh-EnvPath
} else {
    Write-Step 'uv already installed'
}

# ----- 2. exmateria-iso-patcher (prebuilt wheel) ----------------------------

Write-Step "Fetching latest $IsoPatcherRepo release"
$patcherRelease = Get-LatestRelease $IsoPatcherRepo
$wheelAsset = $patcherRelease.assets | Where-Object { $_.name -like '*-py3-none-any.whl' } | Select-Object -First 1
if (-not $wheelAsset) {
    throw "No .whl asset on $IsoPatcherRepo release $($patcherRelease.tag_name)"
}
Write-Host "    $($patcherRelease.tag_name) → $($wheelAsset.name)"

Write-Step 'Installing exmateria-iso-patcher (prebuilt wheel — no compile)'
uv tool install --reinstall $wheelAsset.browser_download_url
Refresh-EnvPath

if (-not (Test-Command 'fft-iso-patcher')) {
    throw "fft-iso-patcher not on PATH after install. Try opening a new PowerShell."
}

# ----- 3. Extract the disc --------------------------------------------------

Write-Step "Extracting $IsoPath to the standard exmateria assets dir"
fft-iso-patcher extract $IsoPath --force

if ($SkipPlugin) {
    Write-Step 'Done (--SkipPlugin set; the DAW plugin was not installed).'
    return
}

# ----- 4. exmateria-daw-plugin (prebuilt VST3) ------------------------------

Write-Step "Fetching latest $DawPluginRepo release"
$pluginRelease = Get-LatestRelease $DawPluginRepo
$pluginAsset = $pluginRelease.assets | Where-Object { $_.name -like '*windows*.zip' } | Select-Object -First 1
if (-not $pluginAsset) {
    throw "No Windows .zip asset on $DawPluginRepo release $($pluginRelease.tag_name)"
}
Write-Host "    $($pluginRelease.tag_name) → $($pluginAsset.name)"

$tempZip = Join-Path $env:TEMP $pluginAsset.name
Write-Step "Downloading $($pluginAsset.name)"
Invoke-WebRequest $pluginAsset.browser_download_url -OutFile $tempZip -UseBasicParsing

if (-not (Test-Path $VST3Dir)) {
    New-Item -ItemType Directory -Path $VST3Dir -Force | Out-Null
}

Write-Step "Installing VST3 bundle into $VST3Dir"
$tempUnzip = Join-Path $env:TEMP "exmateria_vst3_$(Get-Random)"
New-Item -ItemType Directory -Path $tempUnzip -Force | Out-Null
Expand-Archive -Path $tempZip -DestinationPath $tempUnzip -Force

$vst3Bundles = Get-ChildItem -Path $tempUnzip -Recurse -Directory -Filter '*.vst3' -ErrorAction SilentlyContinue
if (-not $vst3Bundles) {
    throw "No .vst3 bundle found inside $tempZip"
}

foreach ($bundle in $vst3Bundles) {
    $target = Join-Path $VST3Dir $bundle.Name
    if (Test-Path $target) {
        Remove-Item -Path $target -Recurse -Force
    }
    Copy-Item -Path $bundle.FullName -Destination $target -Recurse -Force
    Write-Host "    $($bundle.Name)" -ForegroundColor Green
}

Remove-Item $tempZip -Force -ErrorAction SilentlyContinue
Remove-Item $tempUnzip -Recurse -Force -ErrorAction SilentlyContinue

# ----- done -----------------------------------------------------------------

Write-Step 'All done.'
Write-Host ""
Write-Host 'Next steps:' -ForegroundColor Yellow
Write-Host '  1. Restart your DAW (REAPER, etc.) and rescan plugins.'
Write-Host '  2. Drop the FFT plugin on a track.'
Write-Host '  3. Pick an SMD file (e.g. MUSIC_31.SMD for "Trisection").'
Write-Host '  4. Press play.'

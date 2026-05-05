<#
.SYNOPSIS
    ExMateria installer (prebuilt, fast path).

.DESCRIPTION
    Brings a Windows machine from "nothing installed" to "FFT music plays
    in your DAW" by downloading the prebuilt GitHub Releases — no Python,
    no uv, no build tools required. Specifically:

      1. Downloads the latest fft-iso-patcher.exe (PyInstaller-bundled
         single-file binary) into ``-PatcherDir`` (default: your Downloads
         folder). Portable: no PATH munging, no Start Menu / registry
         entries — just a file you can move, pin to taskbar, or throw
         away when you're done.
      2. Runs ``fft-iso-patcher extract`` against the FFT ISO you provide,
         dumping the disc tree into the standard exmateria assets dir
         (%APPDATA%\exmateria\assets\) and caching the source ISO at
         %APPDATA%\exmateria\iso\original.bin.
      3. Downloads the latest exmateria-daw-plugin Windows .vst3 zip
         from GitHub Releases and unzips into your per-user VST3 folder
         (this one IS opinionated about location — DAWs only scan a
         fixed set of folders, so the .vst3 has to land in one of them).

    No admin needed.

.PARAMETER IsoPath
    Path to your Final Fantasy Tactics .bin / .iso. You supply this — the
    script never downloads game data.

.PARAMETER PatcherDir
    Where the portable fft-iso-patcher.exe lands. Defaults to
    ``%USERPROFILE%\Downloads``. Move / rename the file freely after
    install.

.PARAMETER SkipPlugin
    Stop after extracting the disc — don't fetch / install the DAW plugin.

.PARAMETER VST3Dir
    Override the VST3 install folder. Defaults to
    ``%LOCALAPPDATA%\Programs\Common\VST3``. (Most DAWs scan that and
    ``%PROGRAMFILES%\Common Files\VST3``.)

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install_exmateria.ps1 `
        -IsoPath "C:\Games\FFT\Final Fantasy Tactics.bin"

.EXAMPLE
    # Drop the patcher .exe somewhere specific.
    powershell -ExecutionPolicy Bypass -File install_exmateria.ps1 `
        -IsoPath "C:\Games\FFT\Final Fantasy Tactics.bin" `
        -PatcherDir "D:\Tools\ExMateria"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $IsoPath,

    [string] $PatcherDir = (Join-Path $env:USERPROFILE 'Downloads'),

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

function Get-LatestRelease($repo) {
    Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{
        'User-Agent' = 'install_exmateria.ps1'
    }
}

# ----- preflight ------------------------------------------------------------

if (-not (Test-Path $IsoPath)) {
    throw "ISO not found at: $IsoPath"
}

# ----- 1. fft-iso-patcher.exe (portable single-file binary) -----------------

Write-Step "Fetching latest $IsoPatcherRepo release"
$patcherRelease = Get-LatestRelease $IsoPatcherRepo
$exeAsset = $patcherRelease.assets | Where-Object { $_.name -eq 'fft-iso-patcher.exe' } | Select-Object -First 1
if (-not $exeAsset) {
    throw "No fft-iso-patcher.exe asset on $IsoPatcherRepo release $($patcherRelease.tag_name)"
}
Write-Host "    $($patcherRelease.tag_name) → $($exeAsset.name) ($([math]::Round($exeAsset.size / 1MB, 1)) MB)"

if (-not (Test-Path $PatcherDir)) {
    New-Item -ItemType Directory -Path $PatcherDir -Force | Out-Null
}
$exePath = Join-Path $PatcherDir 'fft-iso-patcher.exe'

Write-Step "Downloading fft-iso-patcher.exe to $PatcherDir"
Invoke-WebRequest $exeAsset.browser_download_url -OutFile $exePath -UseBasicParsing
Write-Host "    $exePath"

# ----- 2. Extract the disc --------------------------------------------------

Write-Step "Extracting $IsoPath to the standard exmateria assets dir"
& $exePath extract $IsoPath --force

if ($SkipPlugin) {
    Write-Step 'Done (--SkipPlugin set; the DAW plugin was not installed).'
    Write-Host ""
    Write-Host "Patcher: $exePath" -ForegroundColor Yellow
    Write-Host '  Double-click it any time to launch the TUI.'
    return
}

# ----- 3. exmateria-daw-plugin (prebuilt VST3) ------------------------------

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
Write-Host "Patcher: $exePath" -ForegroundColor Yellow
Write-Host '  Double-click it any time to launch the TUI.'
Write-Host '  Move / rename / pin / discard freely — it carries no install state.'
Write-Host ""
Write-Host 'How to use the DAW plugin:' -ForegroundColor Yellow
Write-Host '  1. Restart your DAW (REAPER, etc.) and rescan plugins.'
Write-Host '  2. Drop the FFT plugin on a track.'
Write-Host '  3. Pick an SMD file (e.g. MUSIC_31.SMD for "Trisection").'
Write-Host '  4. Press play.'

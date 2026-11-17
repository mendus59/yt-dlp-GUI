# Builds "YT Downloader.exe" (a single-file Windows app) from ytdlp_gui.py.
#
# Usage (PowerShell, from the repo root or this folder):
#     powershell -ExecutionPolicy Bypass -File .\app\build.ps1
#     powershell -ExecutionPolicy Bypass -File .\app\build.ps1 -YtDlpSource ..\yt-dlp-master
#
# yt-dlp comes from PyPI unless -YtDlpSource points at a local yt-dlp checkout.
# The build environment lives in %LOCALAPPDATA%\ytdlp-gui-build (kept out of
# OneDrive). The finished exe lands in .\dist at the repo root.

param(
    [string]$YtDlpSource = '',
    [string]$OutName = 'YT Downloader'
)

$ErrorActionPreference = 'Stop'
$here  = $PSScriptRoot
$root  = Split-Path $here -Parent
$build = Join-Path $env:LOCALAPPDATA 'ytdlp-gui-build'
$venv  = Join-Path $build 'venv'
$py    = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path $py)) {
    Write-Host 'Creating build virtual environment...'
    python -m venv $venv
    if ($LASTEXITCODE) { throw 'venv creation failed' }
}

if ($YtDlpSource) {
    $pkg = (Resolve-Path $YtDlpSource).Path + '[default,deno]'
    Write-Host "Installing yt-dlp from local source: $YtDlpSource"
} else {
    $pkg = 'yt-dlp[default,deno]'
    Write-Host 'Installing yt-dlp from PyPI'
}
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet --upgrade $pkg pyinstaller
if ($LASTEXITCODE) { throw 'pip install failed' }

$deno = Join-Path $venv 'Scripts\deno.exe'
if (-not (Test-Path $deno)) { throw "deno.exe not found at $deno" }
$icon = Join-Path $here 'app.ico'

$piArgs = @(
    '--noconfirm', '--clean', '--onefile', '--windowed',
    '--name', $OutName,
    '--icon', $icon,
    '--add-data', "$icon;.",
    '--add-binary', "$deno;deno",
    '--exclude-module', 'setuptools',
    '--exclude-module', 'pkg_resources',
    '--distpath', (Join-Path $build 'dist'),
    '--workpath', (Join-Path $build 'work'),
    '--specpath', $build,
    (Join-Path $here 'ytdlp_gui.py')
)

Write-Host 'Running PyInstaller...'
& $py -m PyInstaller @piArgs
if ($LASTEXITCODE) { throw 'PyInstaller failed' }

$outDir = Join-Path $root 'dist'
New-Item -ItemType Directory -Force $outDir | Out-Null
Copy-Item (Join-Path $build "dist\$OutName.exe") $outDir -Force
Write-Host ''
Write-Host "Built: $(Join-Path $outDir "$OutName.exe")"

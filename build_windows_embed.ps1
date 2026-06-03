# Two-part Windows build (Variant A): immutable embeddable-Python base + tiny app.
#
# Produces:
#   dist\telegram-download-chat-base-<version>.zip  -> full first install
#   dist\app-<version>.zip                          -> tiny per-release update
#
# The base (runtime\) bundles the official Windows *embeddable* CPython plus all
# third-party packages and the launchers; it is installed once and only changes
# when Python or a dependency is bumped. The app part (app\) is just our source
# package and is replaced wholesale by app-<version>.zip via
# scripts\package_embed.py (apply). There is no manifest / per-file diff.
#
# Usage: .\build_windows_embed.ps1

$ErrorActionPreference = "Stop"

# --- Python version for the embeddable runtime (pin: deps' .pyd are ABI-locked) ---
$pyVersion = "3.12.8"
$pyTag = "312"
$embedUrl = "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-embed-amd64.zip"

$dist = "dist\telegram-download-chat"
$runtime = "$dist\runtime"
$pyDir = "$runtime\python"
$siteDir = "$runtime\site-packages"
$appDir = "$dist\app"

Write-Host "Building two-part (embeddable) Windows distribution..."

# Clean previous build
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Path $pyDir, $siteDir, $appDir | Out-Null

# --- Base part 1: embeddable CPython ---
Write-Host "Downloading embeddable Python $pyVersion..."
$embedZip = "$env:TEMP\python-embed-$pyVersion.zip"
Invoke-WebRequest -Uri $embedUrl -OutFile $embedZip
Expand-Archive -Path $embedZip -DestinationPath $pyDir -Force

# Point the embeddable interpreter at our site-packages and the app/ dir.
# Paths are relative to runtime\python\.
$pth = @(
    "python$pyTag.zip",
    ".",
    "..\site-packages",
    "..\..\app",
    "import site"
) -join "`r`n"
Set-Content -Path "$pyDir\python$pyTag._pth" -Value $pth -Encoding ascii

# --- Base part 2: all third-party packages into site-packages (pip --target) ---
Write-Host "Installing dependencies into site-packages..."
$getPip = "$env:TEMP\get-pip.py"
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip
& "$pyDir\python.exe" $getPip --no-warn-script-location
# Install the project's runtime + GUI deps (not the project source itself; that
# lives in the updatable app/ part).
& "$pyDir\python.exe" -m pip install --target $siteDir -r requirements.txt
& "$pyDir\python.exe" -m pip install --target $siteDir "PySide6-Essentials" "reportlab" "jinja2"

# --- Base part 3: launchers ---
Write-Host "Writing launchers..."
# CLI (console): pass through all args.
Set-Content -Path "$dist\telegram-download-chat.cmd" -Encoding ascii -Value @'
@echo off
"%~dp0runtime\python\python.exe" -m telegram_download_chat %*
'@
# GUI (no console window): launch via pythonw through a .vbs shim.
Set-Content -Path "$dist\telegram-download-chat-gui.vbs" -Encoding ascii -Value @'
Set sh = CreateObject("WScript.Shell")
base = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
sh.Run """" & base & "runtime\python\pythonw.exe"" -m telegram_download_chat gui", 0, False
'@

# --- Resolve version ---
$version = $env:SETUPTOOLS_SCM_PRETEND_VERSION
if (-not $version) {
    $version = & "$pyDir\python.exe" -c "import sys; sys.path.insert(0,'src'); from telegram_download_chat import __version__; print(__version__)"
}
Write-Host "Packaging app version $version..."

# --- App part: build app-<version>.zip and unpack it into the base tree ---
& "$pyDir\python.exe" scripts\package_embed.py build-app "src\telegram_download_chat" --version "$version" --output-dir "dist"
Expand-Archive -Path "dist\app-$version.zip" -DestinationPath $appDir -Force

# --- Base installer: zip the whole first-install tree ---
Write-Host "Zipping base installer..."
Compress-Archive -Path "$dist\*" -DestinationPath "dist\telegram-download-chat-base-$version.zip" -Force

Write-Host "Done!" -ForegroundColor Green
Write-Host "  First install: dist\telegram-download-chat-base-$version.zip"
Write-Host "  Update:        dist\app-$version.zip"

# Minimal portable Windows build (no installer footprint).
#
# Produces a self-contained, portable distribution that the user extracts and
# runs from anywhere: dist/telegram-download-chat/telegram-download-chat.exe.
# Unlike build_windows.ps1 (--onefile), this uses PyInstaller --onedir so the
# files are visible on disk, then packages them into a versioned .zip plus a
# manifest.json that enables file-level incremental updates (see
# scripts/package_portable.py).
#
# Usage: .\build_windows_portable.ps1

# Stop on first error
$ErrorActionPreference = "Stop"

Write-Host "Building portable telegram-download-chat for Windows..."

# Create and activate virtual environment
Write-Host "Setting up virtual environment..."
if (-not (Test-Path -Path ".venv")) {
    python -m venv .venv
}
.\.venv\Scripts\Activate.ps1

# Install dependencies
Write-Host "Installing dependencies..."
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pyinstaller

# Clean previous builds
Write-Host "Cleaning previous builds..."
if (Test-Path -Path "dist") {
    Remove-Item -Recurse -Force "dist" -ErrorAction SilentlyContinue
}
if (Test-Path -Path "build") {
    Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue
}

# Create hooks directory if it doesn't exist
$hooksDir = "$PSScriptRoot\hooks"
if (-not (Test-Path -Path $hooksDir)) {
    New-Item -ItemType Directory -Path $hooksDir | Out-Null
}

# Build portable (one-dir) distribution
Write-Host "Building portable distribution..."
.\.venv\Scripts\pyinstaller.exe `
    --onedir `
    --windowed `
    --name "telegram-download-chat" `
    --icon "assets/icon.ico" `
    --add-data "assets/icon.ico;assets/" `
    --hidden-import "telegram_download_chat.core" `
    --hidden-import "telegram_download_chat.paths" `
    --additional-hooks-dir "$hooksDir" `
    "launcher.py"

$distDir = "dist\telegram-download-chat"
if (-not (Test-Path -Path "$distDir\telegram-download-chat.exe")) {
    Write-Host "Build failed! Portable executable not found." -ForegroundColor Red
    exit 1
}

# Resolve version (setuptools-scm pretend version in CI, else installed package)
$version = $env:SETUPTOOLS_SCM_PRETEND_VERSION
if (-not $version) {
    $version = .\.venv\Scripts\python.exe -c "from telegram_download_chat import __version__; print(__version__)"
}
Write-Host "Packaging portable distribution for version $version..."

# Write manifest.json + portable zip via the cross-platform packager
.\.venv\Scripts\python.exe scripts\package_portable.py "$distDir" --version "$version" --output-dir "dist"

Write-Host "Portable build complete!" -ForegroundColor Green
Write-Host "  Folder: $distDir"
Write-Host "  Zip:    dist\telegram-download-chat-portable-$version.zip"

Write-Host "Done!"

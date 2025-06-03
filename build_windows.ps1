# Simplified Windows build script
# Usage: .\build_windows_v2.ps1

# Stop on first error
$ErrorActionPreference = "Stop"

Write-Host "Building telegram-download-chat for Windows..."

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

# Build executable
Write-Host "Building executable..."
.\.venv\Scripts\pyinstaller.exe `
    --onefile `
    --windowed `
    --name "telegram-download-chat" `
    --icon "assets/icon.ico" `
    --add-data "assets/icon.ico;assets/" `
    --hidden-import "telegram_download_chat.core" `
    --hidden-import "telegram_download_chat.paths" `
    --additional-hooks-dir "$hooksDir" `
    "launcher.py"

# Check if build was successful
if (Test-Path -Path "dist\telegram-download-chat.exe") {
    Write-Host "Build complete! Executable created: dist\telegram-download-chat.exe" -ForegroundColor Green
} else {
    Write-Host "Build failed! Executable not found." -ForegroundColor Red
    exit 1
}

# Deactivate virtual environment
# Note: deactivate is not needed in PowerShell script as it ends anyway

Write-Host "Done!"

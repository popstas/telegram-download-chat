# Build script for Windows
# Usage: .\build_windows.ps1

# Stop on first error
$ErrorActionPreference = "Stop"

# Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
# pip install --upgrade pip
pip install -e ".[gui]"
pip install pyinstaller Pillow>=10.0.0

# Clean previous builds
Write-Host "Cleaning previous builds..."
if (Test-Path -Path "dist") {
    try {
        Remove-Item -Recurse -Force "dist" -ErrorAction Stop
    } catch {
        Write-Host "Warning: Could not clean dist directory: $_"
    }
}
if (Test-Path -Path "build") {
    try {
        Remove-Item -Recurse -Force "build" -ErrorAction Stop
    } catch {
        Write-Host "Warning: Could not clean build directory: $_"
    }
}

# Ensure we're using the correct Python from the virtual environment
$pythonExe = "$PSScriptRoot\venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    Write-Error "Python executable not found at $pythonExe. Please create a virtual environment first."
    exit 1
}

# Install/update dependencies
Write-Host "Installing/updating dependencies..."
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -e ".[gui]"
& $pythonExe -m pip install pyinstaller Pillow>=10.0.0

# Apply PyInstaller patch to suppress pkg_resources warning
Write-Host "Applying PyInstaller patch..."
& $pythonExe patch_pyinstaller_importers.py

# Create the spec file for PyInstaller
$spec_content = @"
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['src/telegram_download_chat/cli.py'],
    pathex=['.'],
    binaries=[],
    datas=[('assets/icon.png', 'assets')],
    hiddenimports=['telegram_download_chat.core', 'telegram_download_chat.paths'],
    hookspath=[],
    hooksconfig={},
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='telegram-download-chat',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Set to False to hide console window for GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.png',
)
"@

Set-Content -Path "telegram-download-chat.spec" -Value $spec_content

# Change to the src directory to handle relative imports correctly
$originalDir = Get-Location
Set-Location -Path "$originalDir\src"

# Build the executable with --onefile and console enabled
$pyinstallerArgs = @(
    '--clean',
    '--noconfirm',
    '--onefile',
    '--console',
    '--name', 'telegram-download-chat',
    '--icon', "$originalDir\assets\icon.png",
    '--hidden-import', 'telegram_download_chat.core',
    '--hidden-import', 'telegram_download_chat.paths',
    '--hidden-import', 'telegram_download_chat._pyinstaller.pyimod02_importers',
    '--add-data', "$originalDir\assets\icon.png;assets",
    '--paths', "$originalDir\src",
    '--additional-hooks-dir', "$originalDir\src\_pyinstaller_hooks",
    '--distpath', "$originalDir\dist",
    '--workpath', "$originalDir\build",
    '--specpath', "$originalDir",
    '--hidden-import', 'telegram_download_chat._pyinstaller',
    "$originalDir\launcher.py"
)

# Run PyInstaller
& $pythonExe -m PyInstaller @pyinstallerArgs

# Clean up
Set-Location -Path $originalDir

# Create a zip archive with the executable
$version = (Get-Content pyproject.toml | Select-String -Pattern 'version = "(\d+\.\d+\.\d+)"').Matches.Groups[1].Value
$archiveName = "telegram-download-chat-windows-x86_64-v$version.zip"

# Include the executable and assets in the zip
$tempDir = "telegram-download-chat-v$version"
New-Item -ItemType Directory -Path $tempDir -Force
Copy-Item -Path ".\dist\telegram-download-chat.exe" -Destination $tempDir
Copy-Item -Path ".\assets\icon.png" -Destination $tempDir

# Create zip archive
Compress-Archive -Path "$tempDir\*" -DestinationPath $archiveName -Force
Remove-Item -Recurse -Force $tempDir

Write-Host "Build complete! Executable is: dist\telegram-download-chat.exe"
Write-Host "Archive created: $archiveName"

# Deactivate virtual environment
deactivate

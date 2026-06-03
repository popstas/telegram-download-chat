# Build a setup.exe installer (Inno Setup) wrapping the two-part embeddable build.
#
# Runs build_windows_embed.ps1 to produce dist\telegram-download-chat\ (runtime\
# + app\ + launchers), then compiles installer.iss with ISCC into
# dist\telegram-download-chat-setup-<version>.exe.
#
# Requires Inno Setup 6 (ISCC.exe): https://jrsoftware.org/isdl.php
#
# Usage: .\build_windows_installer.ps1

$ErrorActionPreference = "Stop"

# 1. Build the portable two-part tree (and the base/app zips).
& "$PSScriptRoot\build_windows_embed.ps1"

# 2. Resolve the version the embed build just stamped into app\version.txt.
$versionFile = Join-Path $PSScriptRoot "dist\telegram-download-chat\app\version.txt"
if (-not (Test-Path $versionFile)) {
    throw "version.txt not found; did build_windows_embed.ps1 run? ($versionFile)"
}
$version = (Get-Content $versionFile -Raw).Trim()

# 3. Locate ISCC (PATH, then the default Inno Setup 6 install locations).
$iscc = (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($candidate in @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles}\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $candidate) { $iscc = $candidate; break }
    }
}
if (-not $iscc) {
    throw "Inno Setup (ISCC.exe) not found. Install it from https://jrsoftware.org/isdl.php"
}

# 4. Compile the installer, passing the version as a preprocessor define.
Write-Host "Compiling installer for version $version with $iscc..."
& $iscc "/dMyAppVersion=$version" (Join-Path $PSScriptRoot "installer.iss")

Write-Host "Installer: dist\telegram-download-chat-v$version-setup.exe" -ForegroundColor Green

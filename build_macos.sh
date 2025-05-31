#!/bin/bash
# Build script for macOS
# Usage: ./build_macos.sh

# Stop on first error and print commands
set -e
set -x

# Get the script's directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Ensure we're using the correct Python from the virtual environment
PYTHON_EXEC="$SCRIPT_DIR/venv/bin/python"
if [ ! -f "$PYTHON_EXEC" ]; then
    echo "Error: Python executable not found at $PYTHON_EXEC"
    exit 1
fi

# Install/update dependencies
echo "Installing/updating dependencies..."
"$PYTHON_EXEC" -m pip install --upgrade pip
"$PYTHON_EXEC" -m pip install -e ".[gui]"
"$PYTHON_EXEC" -m pip install pyinstaller Pillow>=10.0.0

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf "$SCRIPT_DIR/dist" "$SCRIPT_DIR/build" "$SCRIPT_DIR/telegram-download-chat.spec"

# Create a temporary directory for the build
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

# Build the executable with PyInstaller
echo "Building executable..."
"$PYTHON_EXEC" -m PyInstaller \
    --clean \
    --noconfirm \
    --onefile \
    --console \
    --name telegram-download-chat \
    --icon "$SCRIPT_DIR/assets/icon.png" \
    --hidden-import telegram_download_chat.core \
    --hidden-import telegram_download_chat.paths \
    --hidden-import telegram_download_chat._pyinstaller \
    --add-data "$SCRIPT_DIR/assets/icon.png:assets" \
    --paths "$SCRIPT_DIR/src" \
    --additional-hooks-dir "$SCRIPT_DIR/src/_pyinstaller_hooks" \
    --distpath "$SCRIPT_DIR/dist" \
    --workpath "$SCRIPT_DIR/build" \
    --specpath "$SCRIPT_DIR" \
    "$SCRIPT_DIR/launcher.py"

# Create a zip archive with the executable
VERSION=$(grep -oP 'version = "\K[0-9]+\.[0-9]+\.[0-9]+(?=")' "$SCRIPT_DIR/pyproject.toml")
ARCHIVE_NAME="telegram-download-chat-macos-x86_64-v${VERSION}.tar.gz"

# Create a temporary directory for the archive
TEMP_DIR="$(mktemp -d)"
cp "$SCRIPT_DIR/dist/telegram-download-chat" "$TEMP_DIR/"
cp "$SCRIPT_DIR/assets/icon.png" "$TEMP_DIR/"

# Create tar.gz archive
echo "Creating archive..."
tar -czf "$SCRIPT_DIR/$ARCHIVE_NAME" -C "$TEMP_DIR" .

# Cleanup
rm -rf "$TEMP_DIR"

echo "Build complete!"
echo "Executable: $SCRIPT_DIR/dist/telegram-download-chat"
echo "Archive: $SCRIPT_DIR/$ARCHIVE_NAME"

# Deactivate virtual environment
deactivate

exit 0

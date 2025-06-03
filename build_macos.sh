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

# Apply patch for PySide6.QtAsyncio.events.py f-string syntax error
echo "Applying patch for PySide6.QtAsyncio.events.py..."
EVENTS_PY="$SCRIPT_DIR/venv/lib/python3.9/site-packages/PySide6/QtAsyncio/events.py"
if [ -f "$EVENTS_PY" ]; then
    patch -N -r - "$EVENTS_PY" < "$SCRIPT_DIR/patch_qtasyncio_events.patch" || true
else
    echo "Warning: Could not find $EVENTS_PY to apply patch"
fi

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf "$SCRIPT_DIR/dist" "$SCRIPT_DIR/build" "$SCRIPT_DIR/telegram-download-chat.spec"

# Create a temporary directory for the build
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

# Create .icns file from icon.png if it doesn't exist
ICONSET_DIR="$SCRIPT_DIR/telegram-download-chat.iconset"
ICON_SRC="$SCRIPT_DIR/assets/icon.png"
ICONSET_DEST="$SCRIPT_DIR/telegram-download-chat.icns"

if [ ! -f "$ICONSET_DEST" ]; then
    echo "Creating .icns file..."
    mkdir -p "$ICONSET_DIR"
    
    # Create icons of different sizes
    sips -z 16 16     "$ICON_SRC" --out "$ICONSET_DIR/icon_16x16.png" > /dev/null
    sips -z 32 32     "$ICON_SRC" --out "$ICONSET_DIR/icon_16x16@2x.png" > /dev/null
    sips -z 32 32     "$ICON_SRC" --out "$ICONSET_DIR/icon_32x32.png" > /dev/null
    sips -z 64 64     "$ICON_SRC" --out "$ICONSET_DIR/icon_32x32@2x.png" > /dev/null
    sips -z 128 128   "$ICON_SRC" --out "$ICONSET_DIR/icon_128x128.png" > /dev/null
    sips -z 256 256   "$ICON_SRC" --out "$ICONSET_DIR/icon_128x128@2x.png" > /dev/null
    sips -z 256 256   "$ICON_SRC" --out "$ICONSET_DIR/icon_256x256.png" > /dev/null
    sips -z 512 512   "$ICON_SRC" --out "$ICONSET_DIR/icon_256x256@2x.png" > /dev/null
    sips -z 512 512   "$ICON_SRC" --out "$ICONSET_DIR/icon_512x512.png" > /dev/null
    sips -z 1024 1024 "$ICON_SRC" --out "$ICONSET_DIR/icon_512x512@2x.png" > /dev/null
    
    # Create .icns file
    iconutil -c icns "$ICONSET_DIR" -o "$ICONSET_DEST"
    
    # Clean up
    rm -rf "$ICONSET_DIR"
fi

# Build the app bundle with PyInstaller
echo "Building macOS app bundle..."
"$PYTHON_EXEC" -m PyInstaller \
    --clean \
    --noconfirm \
    --windowed \
    --name "telegram-download-chat" \
    --icon "$ICONSET_DEST" \
    --hidden-import telegram_download_chat.core \
    --hidden-import telegram_download_chat.paths \
    --hidden-import telegram_download_chat._pyinstaller \
    --add-data "$SCRIPT_DIR/assets/icon.png:assets" \
    --paths "$SCRIPT_DIR/src" \
    --additional-hooks-dir "$SCRIPT_DIR/src/_pyinstaller_hooks" \
    --distpath "$SCRIPT_DIR/dist" \
    --workpath "$SCRIPT_DIR/build" \
    --specpath "$SCRIPT_DIR" \
    --osx-bundle-identifier "com.popstas.telegram-download-chat" \
    "$SCRIPT_DIR/launcher.py"

# Create a nicer app bundle structure
APP_PATH="$SCRIPT_DIR/dist/Telegram Download Chat.app"
CONTENTS_DIR="$APP_PATH/Contents"

# Create Info.plist
cat > "$CONTENTS_DIR/Info.plist" <<EOL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Telegram Download Chat</string>
    <key>CFBundleDisplayName</key>
    <string>Telegram Download Chat</string>
    <key>CFBundleIdentifier</key>
    <string>com.popstas.telegram-download-chat</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleExecutable</key>
    <string>Telegram Download Chat</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSRequiresAquaSystemAppearance</key>
    <false/>
</dict>
</plist>
EOL

# Copy icon to Resources
RESOURCES_DIR="$CONTENTS_DIR/Resources"
mkdir -p "$RESOURCES_DIR"
cp "$ICONSET_DEST" "$RESOURCES_DIR/AppIcon.icns"

# Make sure the executable has the right permissions
chmod +x "$CONTENTS_DIR/MacOS/Telegram Download Chat"

# Create DMG (optional)
echo "Creating DMG..."
DMG_NAME="telegram-download-chat.dmg"
DMG_TEMP_DIR="$SCRIPT_DIR/dmg_temp"
DMG_APP_DIR="$DMG_TEMP_DIR/telegram-download-chat.app"

mkdir -p "$DMG_TEMP_DIR"
cp -R "$APP_PATH" "$DMG_APP_DIR"

# Create a symbolic link to Applications
ln -s /Applications "$DMG_TEMP_DIR/Applications"

# Create the DMG
hdiutil create -volname "telegram-download-chat" \
    -srcfolder "$DMG_TEMP_DIR" \
    -ov -format UDZO "$SCRIPT_DIR/dist/$DMG_NAME"

# Clean up
rm -rf "$DMG_TEMP_DIR"

echo "Build complete!"
echo "App bundle: $APP_PATH"
echo "DMG: $SCRIPT_DIR/dist/$DMG_NAME"

# Ensure the final DMG has the correct name
mv -f "$SCRIPT_DIR/dist/telegram-download-chat.dmg" "$SCRIPT_DIR/dist/telegram-download-chat.dmg"

# Deactivate virtual environment
deactivate

exit 0

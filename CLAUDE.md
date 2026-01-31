# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram Download Chat is a Python CLI utility that downloads and analyzes Telegram chat history. It provides both command-line and GUI interfaces for downloading messages from chats, groups, channels, or archived exports and saving them in JSON/TXT formats.

### Key Components

- **Core Engine** (`core/` package): Contains `TelegramChatDownloader` plus helper modules (`auth`, `config`, `download`, `entities`, `media`, `messages`, `context`) built on Telethon
- **CLI Interface** (`cli.py`): Command-line interface with argument parsing and async message processing
- **GUI Interface** (`gui_app.py`): PySide6-based graphical interface with threading for async operations
- **Configuration** (`paths.py`): Handles config file management and application directories

### Architecture

The application follows a modular design:
1. **Configuration Layer**: YAML-based config with API credentials and user settings
2. **Telegram Client Layer**: Telethon wrapper for authenticated API communication
3. **Processing Layer**: Message filtering, date splitting, format conversion
4. **Interface Layer**: CLI and GUI frontends sharing the same core functionality

## Development Commands

### Setup Development Environment
```bash
# Install in development mode with all dependencies
pip install -e ".[dev,gui]"

# Or install from requirements
pip install -r requirements.txt
```

### Testing
```bash
# Run tests
pytest

# Run tests with async support
pytest -v

# Run specific test
pytest tests/test_telegram_download_chat.py::TestClass::test_method
```

### Code Quality
```bash
# Format code
black src/ tests/

# Sort imports
isort src/ tests/

# Type checking
mypy src/
```

### Building
```bash
# Build package
python -m build

# Install from source
pip install .

# Build PyInstaller executables
./build_macos.sh      # macOS
./build_windows.ps1   # Windows
```

### Running
```bash
# CLI mode
python -m telegram_download_chat username

# GUI mode  
python -m telegram_download_chat gui
# or
telegram-download-chat gui

# From source
python main.py  # Launches GUI by default
```

## Configuration

- Config file auto-created at OS-specific locations (see `paths.py`)
- Requires Telegram API credentials from https://my.telegram.org
- Example config in `config.example.yml`
- GUI provides config editing interface

## Key Features to Understand

### Message Processing
- Downloads via Telethon's `iter_messages()` with pagination
- Supports resume from interruption using temporary files
- Can filter by date ranges, specific users, or message threads
- Outputs JSON (full metadata) and TXT (human-readable) formats

### Authentication
- Uses Telethon sessions for persistent login
- GUI handles phone/code/password flow
- CLI opens browser for authentication

### Filtering & Splitting
- `--subchat`: Extract message threads/replies
- `--split`: Split output by month/year
- `--user`: Filter by specific sender
- `--until`: Date-based filtering
- `--media`: Download media attachments (photos, videos, documents, etc.)

### PyInstaller Integration
- Custom hooks in `_pyinstaller/` for bundling
- Platform-specific build scripts
- GUI auto-launches when no CLI args provided
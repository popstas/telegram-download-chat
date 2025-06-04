Update README.md after features changes.

Use `telegram-download-chat` for run cli.

После build_windows.ps1 запускай приложение.

# Telegram Download Chat GUI Structure

## Project Structure
src/telegram_download_chat/
├── gui/                      # Main GUI package
│   ├── __init__.py           # Package initialization
│   ├── main.py               # Main application entry point
│   ├── worker.py             # Background worker thread
│   ├── windows/              # Window classes
│   │   └── main_window.py    # Main application window
│   │
│   ├── widgets/              # Custom widgets
│   │   ├── file_list.py      # File list with preview
│   │   └── log_viewer.py     # Log viewing widget
│   │
│   ├── tabs/                 # Application tabs
│   │   ├── download_tab.py   # Download tab
│   │   ├── convert_tab.py    # Convert tab
│   │   └── settings_tab.py   # Settings tab
│   │
│   └── utils/                # Utility modules
│       ├── config.py         # Configuration management
│       ├── file_utils.py     # File operations
│       └── telegram_auth.py  # Telegram authentication
│
└── gui_app_.py              # Old GUI implementation (renamed)

## Key Components

1. **Main Window**
   - Central widget with tabbed interface
   - Menu bar with File, Edit, View, Help
   - Status bar with progress indicators

2. **Tabs**
   - **Download Tab**: For downloading chat history
   - **Convert Tab**: For converting between formats (future)
   - **Settings Tab**: Application configuration

3. **Widgets**
   - FileList: Displays downloaded files with preview
   - LogViewer: Shows log output with copy/expand features

4. **Worker Thread**
   - Handles long-running operations
   - Emits progress and completion signals

## Development Notes
- Uses PySide6 for the GUI
- Follows MVC pattern where possible
- Uses signals/slots for inter-component communication
- Config stored in YAML format
- Session management for Telegram authentication

## Running the Application
- Use `python -m telegram_download_chat.gui.main` to start the GUI
- Or use the launcher: `python launcher.py`
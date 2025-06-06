#!/usr/bin/env python3
"""
Entry point for PyInstaller to handle imports correctly.
Launches GUI by default when no arguments are provided.
"""
import sys
import os
from pathlib import Path

# Add the src directory to the Python path
src_dir = Path(__file__).parent / 'src'
sys.path.insert(0, str(src_dir))

def is_gui_mode():
    """Determine if we should run in GUI mode."""
    # Filter out -m and module name if present
    args = [arg for i, arg in enumerate(sys.argv) 
           if not (arg == '-m' or (i > 0 and sys.argv[i-1] == '-m'))]
    
    # If no arguments or only the script name is provided
    if len(args) == 1:
        return True
    
    # Check for help flag or other CLI flags
    if any(arg in args[1:] for arg in ['-h', '--help', '--version', '--debug']):
        return False
    
    # If we have any non-flag arguments, assume CLI mode
    if len(args) > 1 and not args[1].startswith('-'):
        return False
        
    # Default to GUI mode for other cases
    return True

def main():
    if is_gui_mode():
        try:
            from telegram_download_chat.gui.main import main as gui_main
            gui_main()
        except ImportError:
            print("GUI dependencies not installed. Falling back to CLI mode.")
            from telegram_download_chat.cli import main as cli_main
            cli_main()
    else:
        from telegram_download_chat.cli import main as cli_main
        cli_main()

if __name__ == "__main__":
    main()

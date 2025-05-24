"""Handle OS-specific paths for the application."""
import os
import sys
from pathlib import Path
from typing import Dict, Any

def get_app_dir() -> Path:
    """
    Get the application directory based on the OS.
    
    Returns:
        Path: Path to the application directory
    """
    if sys.platform == 'win32':
        base_dir = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
    elif sys.platform == 'darwin':
        base_dir = Path.home() / 'Library' / 'Application Support'
    else:  # Linux and other UNIX-like
        base_dir = Path.home() / '.local' / 'share'
    
    return base_dir / 'telegram-download-chat'

def get_default_config() -> Dict[str, Any]:
    """
    Get the default configuration.
    
    Returns:
        dict: Default configuration
    """
    return {
        'settings': {
            'api_id': 'YOUR_API_ID',
            'api_hash': 'YOUR_API_HASH'
        },
    }

def ensure_app_dirs() -> None:
    """Ensure all required application directories exist."""
    app_dir = get_app_dir()
    dirs = [
        app_dir,
        app_dir / 'downloads',
    ]
    
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)

def get_default_config_path() -> Path:
    """
    Get the path to the default config file.
    
    Returns:
        Path: Path to the default config file
    """
    return get_app_dir() / 'config.yml'

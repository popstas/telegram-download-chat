"""File utility functions for the Telegram Download Chat GUI."""
import os
import shutil
from pathlib import Path
from typing import List, Optional, Union

def ensure_dir_exists(directory: Union[str, Path]) -> Path:
    """Ensure that a directory exists, creating it if necessary.
    
    Args:
        directory: Path to the directory
        
    Returns:
        Path: The path to the directory
    """
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    return path


def format_file_size(size_bytes: int) -> str:
    """Format a size in bytes to a human-readable string.
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        str: Human-readable file size (e.g., "1.2 MB")
    """
    if not isinstance(size_bytes, (int, float)) or size_bytes < 0:
        return "0 B"
    
    size = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def get_file_size(file_path: Union[str, Path]) -> str:
    """Get a human-readable file size for a file path.
    
    Args:
        file_path: Path to the file
        
    Returns:
        str: Human-readable file size (e.g., "1.2 MB")
    """
    path = Path(file_path)
    if not path.is_file():
        return "0 B"
    
    return format_file_size(path.stat().st_size)


def get_file_preview(file_path: Union[str, Path], max_lines: int = 100) -> str:
    """Get a preview of a text file.
    
    Args:
        file_path: Path to the file
        max_lines: Maximum number of lines to return
        
    Returns:
        str: Preview of the file content
    """
    path = Path(file_path)
    if not path.is_file():
        return ""
    
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    lines.append(f"... (showing first {max_lines} lines)")
                    break
                lines.append(line.rstrip())
            return '\n'.join(lines)
    except Exception as e:
        return f"Error reading file: {e}"


def open_file_explorer(path: Union[str, Path]) -> bool:
    """Open the system file explorer at the given path.
    
    Args:
        path: Path to open in file explorer
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        path = Path(path)
        if path.is_file():
            path = path.parent
        
        if not path.exists():
            return False
            
        if os.name == 'nt':  # Windows
            os.startfile(str(path.absolute()))
        elif os.name == 'posix':  # macOS and Linux
            if os.uname().sysname == 'Darwin':  # macOS
                import subprocess
                subprocess.Popen(['open', str(path.absolute())])
            else:  # Linux
                import subprocess
                subprocess.Popen(['xdg-open', str(path.absolute())])
        return True
    except Exception as e:
        print(f"Error opening file explorer: {e}")
        return False


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard.
    
    Args:
        text: Text to copy
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception as e:
        print(f"Error copying to clipboard: {e}")
        return False

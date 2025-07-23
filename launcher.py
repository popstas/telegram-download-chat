#!/usr/bin/env python3
"""
Launcher script that ensures proper argument handling for the executable.
"""
import os
import sys
import warnings
from pathlib import Path

# Suppress pkg_resources deprecation warnings
warnings.filterwarnings(
    "ignore", message="pkg_resources is deprecated", category=DeprecationWarning
)


def main():
    # Add the src directory to the Python path
    src_dir = Path(__file__).parent / "src"
    sys.path.insert(0, str(src_dir))

    # Filter out -m and module name if present
    args = sys.argv[1:]
    if args and args[0] == "-m":
        args = args[2:]  # Remove -m and the module name

    # Replace sys.argv with the filtered arguments
    sys.argv = [sys.argv[0]] + args

    # Import and run the main module
    from telegram_download_chat.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Main entry point for the telegram-download-chat package."""

import sys

from telegram_download_chat.cli import main

if __name__ == "__main__":
    # The exit code must reach the caller: the GUI runs downloads as
    # `python -m telegram_download_chat` and treats a non-zero code as a
    # failure. Dropping it reported every failed download as completed.
    sys.exit(main())

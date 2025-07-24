"""Command line interface for telegram-download-chat."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import traceback
from pathlib import Path

from telegram_download_chat.core import TelegramChatDownloader
from telegram_download_chat.paths import (
    get_default_config_path,
    get_downloads_dir,
    get_relative_to_downloads_dir,
)

from . import commands
from .arguments import CLIOptions, parse_args
from .commands import filter_messages_by_subchat

_downloader_instance: TelegramChatDownloader | None = None


def _signal_handler(sig, frame):
    global _downloader_instance
    if _downloader_instance:
        print("\nReceived termination signal, stopping download gracefully...")
        _downloader_instance.stop()
    else:
        sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


async def async_main() -> int:
    """Entry point for asynchronous CLI operations."""
    global _downloader_instance
    args = parse_args()
    downloader = TelegramChatDownloader(config_path=args.config)
    _downloader_instance = downloader

    try:
        if args.show_config:
            config_path = (
                Path(args.config) if args.config else get_default_config_path()
            )
            downloader.logger.info(f"Configuration file: {config_path}")
            if config_path.exists():
                downloader.logger.info("\nCurrent configuration:")
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        downloader.logger.info(f.read())
                except Exception as e:  # pragma: no cover - just logging
                    downloader.logger.error(f"\nError reading config file: {e}")
            else:
                downloader.logger.info(
                    "\nConfiguration file does not exist yet. It will be created on first run."
                )
            return 0

        if args.debug:
            downloader.logger.setLevel(logging.DEBUG)
            downloader.logger.debug("Debug logging enabled")

        if args.last_days is not None:
            from datetime import datetime, timedelta

            base_str = args.from_date or datetime.utcnow().strftime("%Y-%m-%d")
            try:
                base_date = datetime.strptime(base_str, "%Y-%m-%d")
            except ValueError:
                downloader.logger.error("Invalid date format for --from")
                return 1
            args.until = (base_date - timedelta(days=args.last_days)).strftime(
                "%Y-%m-%d"
            )

        if not args.chat:
            downloader.logger.error("Chat identifier is required")
            return 1

        import tempfile

        stop_file = Path(tempfile.gettempdir()) / "telegram_download_stop.tmp"
        downloader.set_stop_file(str(stop_file))

        downloads_dir = Path(
            downloader.config.get("settings", {}).get("save_path", get_downloads_dir())
        )
        downloads_dir.mkdir(parents=True, exist_ok=True)

        if args.subchat and not args.output and not args.chat.endswith(".json"):
            downloader.logger.error("--subchat requires an existing JSON file as input")
            return 1

        if args.chat.endswith(".json"):
            return await commands.convert(downloader, args, downloads_dir)

        if args.chat.startswith("folder:"):
            return await commands.folder(downloader, args, downloads_dir)

        await downloader.connect()
        return await commands.download(downloader, args, downloads_dir)

    except Exception as e:  # pragma: no cover - just logging
        downloader.logger.error(f"An error occurred: {e}", exc_info=args.debug)
        downloader.logger.error(traceback.format_exc())
        return 1
    finally:
        await downloader.close()
        downloader.cleanup_stop_file()
        try:
            stop_file.unlink()
        except Exception:
            pass


def main() -> int:
    """Synchronous entry point for the CLI."""
    if (len(sys.argv) >= 2 and sys.argv[1] == "gui") or len(sys.argv) == 1:
        try:
            from telegram_download_chat.gui.main import main as gui_main

            gui_main()
            return 0
        except ImportError as e:  # pragma: no cover - GUI optional
            print(
                "GUI dependencies not installed. Please install with: pip install 'telegram-download-chat[gui]'"
            )
            print(e)
            return 1
        except Exception as e:  # pragma: no cover - GUI optional
            print(f"Error starting GUI: {e}")
            print(e)
            return 1

    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        print("Operation cancelled by user")
        return 1
    except Exception as e:  # pragma: no cover - just logging
        print(f"Unhandled exception: {e}")
        return 1


__all__ = [
    "async_main",
    "main",
    "parse_args",
    "CLIOptions",
    "commands",
    "filter_messages_by_subchat",
    "get_relative_to_downloads_dir",  # used in tests via commands
]

"""Command line interface for telegram-download-chat."""

from __future__ import annotations

import asyncio
import inspect
import logging
import signal
import sys
import tempfile
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from telegram_download_chat.core import DownloaderContext, TelegramChatDownloader

try:  # GUI is optional
    from telegram_download_chat.gui.main import main as gui_main
except ImportError:  # pragma: no cover - GUI optional
    gui_main = None
from telegram_download_chat.paths import (
    get_default_config_path,
    get_downloads_dir,
    get_relative_to_downloads_dir,
)

from . import commands
from .arguments import CLIOptions, parse_args
from .commands import filter_messages_by_subchat

_downloader_ctx: DownloaderContext | None = None


def _signal_handler(sig, frame):
    """Handle termination signals and stop active downloads."""
    global _downloader_ctx
    if _downloader_ctx:
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(_downloader_ctx.stop)
        except RuntimeError:
            _downloader_ctx.stop()
    else:
        sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def show_config(downloader: TelegramChatDownloader, config: str | None) -> int:
    """Display configuration file path and contents."""
    config_path = Path(config) if config else get_default_config_path()
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


async def convert_json_to_txt(
    ctx: DownloaderContext,
    downloader: TelegramChatDownloader,
    args: CLIOptions,
    downloads_dir: Path,
) -> int:
    """Convert JSON file to TXT using :mod:`commands`."""
    async with ctx:
        return await commands.convert(downloader, args, downloads_dir)


async def download_folder(
    ctx: DownloaderContext,
    downloader: TelegramChatDownloader,
    args: CLIOptions,
    downloads_dir: Path,
) -> int:
    """Download all chats from a folder."""
    async with ctx:
        return await commands.folder(downloader, args, downloads_dir)


async def download_chat(
    ctx: DownloaderContext,
    downloader: TelegramChatDownloader,
    args: CLIOptions,
    downloads_dir: Path,
) -> int:
    """Download a single chat."""
    async with ctx:
        return await commands.download(downloader, args, downloads_dir)


async def async_main() -> int:
    """Entry point for asynchronous CLI operations."""
    global _downloader_ctx
    args = parse_args()
    downloader = TelegramChatDownloader(config_path=args.config)
    ctx = DownloaderContext(downloader)
    _downloader_ctx = ctx

    try:
        if args.show_config:
            return show_config(downloader, args.config)

        if args.debug:
            downloader.logger.setLevel(logging.DEBUG)
            downloader.logger.debug("Debug logging enabled")

        if args.last_days is not None:
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

        stop_file = Path(tempfile.gettempdir()) / "telegram_download_stop.tmp"
        if inspect.iscoroutinefunction(downloader.set_stop_file):
            await downloader.set_stop_file(str(stop_file))
        else:
            downloader.set_stop_file(str(stop_file))

        downloads_dir = Path(
            downloader.config.get("settings", {}).get("save_path", get_downloads_dir())
        )
        downloads_dir.mkdir(parents=True, exist_ok=True)

        if args.subchat and not args.output and not args.chat.endswith(".json"):
            downloader.logger.error("--subchat requires an existing JSON file as input")
            return 1

        if args.chat.endswith(".json"):
            return await convert_json_to_txt(ctx, downloader, args, downloads_dir)

        if args.chat.startswith("folder:"):
            return await download_folder(ctx, downloader, args, downloads_dir)

        return await download_chat(ctx, downloader, args, downloads_dir)

    except Exception as e:  # pragma: no cover - just logging
        downloader.logger.error(f"An error occurred: {e}", exc_info=args.debug)
        downloader.logger.error(traceback.format_exc())
        return 1
    finally:
        _downloader_ctx = None


def main() -> int:
    """Synchronous entry point for the CLI."""
    if (len(sys.argv) >= 2 and sys.argv[1] == "gui") or len(sys.argv) == 1:
        if gui_main is not None:
            try:
                gui_main()
                return 0
            except Exception as e:  # pragma: no cover - GUI optional
                print(f"Error starting GUI: {e}")
                print(e)
                return 1
        else:
            print(
                "GUI dependencies not installed. Please install with: pip install 'telegram-download-chat[gui]'"
            )
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
    "show_config",
    "convert_json_to_txt",
    "download_folder",
    "download_chat",
    "get_relative_to_downloads_dir",  # used in tests via commands
]

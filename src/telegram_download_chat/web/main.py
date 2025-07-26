from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui

from telegram_download_chat.cli import commands
from telegram_download_chat.cli.arguments import CLIOptions
from telegram_download_chat.core import DownloaderContext, TelegramChatDownloader
from telegram_download_chat.paths import get_downloads_dir

chat_input = ui.input("Chat identifier")
limit_input = ui.input("Message limit", value="0")


async def start_download() -> None:
    chat = chat_input.value.strip()
    try:
        limit = int(limit_input.value or 0)
    except ValueError:
        limit = 0

    downloader = TelegramChatDownloader()
    ctx = DownloaderContext(downloader)
    args = CLIOptions(chat=chat, chats=[chat], limit=limit)
    downloads_dir = Path(
        downloader.config.get("settings", {}).get("save_path", get_downloads_dir())
    )
    async with ctx:
        result = await commands.download(downloader, args, downloads_dir)
    ui.notify(f"Downloaded {result.get('messages', 0)} messages")


def main() -> None:
    ui.button("Download", on_click=lambda: asyncio.create_task(start_download()))
    ui.run(title="Telegram Download Chat Web")


if __name__ == "__main__":
    main()

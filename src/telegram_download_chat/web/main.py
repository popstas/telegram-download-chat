from __future__ import annotations

from pathlib import Path

from pywebio import start_server
from pywebio.input import NUMBER, TEXT, input, input_group
from pywebio.output import put_markdown, put_text

from telegram_download_chat.cli.arguments import CLIOptions
from telegram_download_chat.cli.commands import download
from telegram_download_chat.core import DownloaderContext, TelegramChatDownloader
from telegram_download_chat.paths import get_downloads_dir


async def app() -> None:
    """PyWebIO application entry point."""
    put_markdown("# Telegram Download Chat Web Interface")
    data = await input_group(
        "Download chat",
        [
            input("Chat identifier", name="chat", required=True, type=TEXT),
            input("Limit (0=all)", name="limit", type=NUMBER, value=100),
        ],
    )
    downloader = TelegramChatDownloader()
    async with DownloaderContext(downloader):
        downloads_dir = Path(
            downloader.config.get("settings", {}).get("save_path", get_downloads_dir())
        )
        downloads_dir.mkdir(parents=True, exist_ok=True)
        args = CLIOptions(
            chat=data["chat"],
            chats=[
                data["chat"],
            ],
            limit=int(data["limit"]),
        )
        result = await download(downloader, args, downloads_dir)
    put_markdown(f"**Downloaded {result['messages']} messages**")
    put_text(f"JSON saved to: {result['result_json']}")
    put_text(f"TXT saved to: {result['result_txt']}")


def main(port: int = 8080) -> None:
    """Start the PyWebIO server."""
    start_server(app, port=port)

from __future__ import annotations

import asyncio
from pathlib import Path

from pywebio import start_server
from pywebio.input import NUMBER, TEXT
from pywebio.input import input as input_field
from pywebio.input import input_group
from pywebio.output import put_markdown, put_text

from telegram_download_chat.cli.arguments import CLIOptions
from telegram_download_chat.cli.commands import download
from telegram_download_chat.core import DownloaderContext, TelegramChatDownloader


async def web_app() -> None:
    """Simple PyWebIO application to download chats."""
    put_markdown("# Telegram Download Chat Web")
    data = await input_group(
        "Download options",
        [
            input_field("Chat identifier", name="chat", type=TEXT),
            input_field("Message limit (0 = all)", name="limit", type=NUMBER, value=0),
            input_field(
                "Output directory",
                name="output_dir",
                type=TEXT,
                value=str(Path.cwd()),
            ),
        ],
    )

    chat = data.get("chat")
    limit = int(data.get("limit") or 0)
    output_dir = Path(data.get("output_dir") or Path.cwd())
    output_dir.mkdir(parents=True, exist_ok=True)

    put_text("Starting download...")
    downloader = TelegramChatDownloader()
    ctx = DownloaderContext(downloader)
    args = CLIOptions(chat=chat, limit=limit)

    async with ctx:
        result = await download(downloader, args, output_dir)

    put_text(
        f"Finished. Saved {result.get('messages', 0)} messages to {result.get('result_json')}"
    )


def main() -> None:
    """Run the PyWebIO server."""
    start_server(web_app, port=8080, debug=True)


if __name__ == "__main__":  # pragma: no cover - manual start
    main()

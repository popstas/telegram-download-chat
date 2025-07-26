import asyncio
from pathlib import Path

import streamlit as st

from telegram_download_chat.cli.arguments import CLIOptions
from telegram_download_chat.cli.commands import download
from telegram_download_chat.core import DownloaderContext, TelegramChatDownloader
from telegram_download_chat.paths import get_downloads_dir


def run_download(chat: str, limit: int, until: str | None) -> dict:
    downloader = TelegramChatDownloader()

    async def _run() -> dict:
        ctx = DownloaderContext(downloader)
        async with ctx:
            downloads_dir = Path(
                downloader.config.get("settings", {}).get(
                    "save_path", get_downloads_dir()
                )
            )
            downloads_dir.mkdir(parents=True, exist_ok=True)
            opts = CLIOptions(chat=chat, limit=limit, until=until)
            return await download(downloader, opts, downloads_dir)

    return asyncio.run(_run())


def main() -> None:
    """Launch the Streamlit web interface."""
    st.title("Telegram Download Chat")

    chat = st.text_input("Chat identifier")
    limit = st.number_input("Message limit", value=0, step=100, min_value=0)
    until = st.text_input("Until date (YYYY-MM-DD)", "")

    if st.button("Download") and chat:
        result = run_download(chat, int(limit), until or None)
        st.json(result)


if __name__ == "__main__":
    main()

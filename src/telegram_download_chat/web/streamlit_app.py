"""Simple Streamlit interface for Telegram Chat Downloader."""

from __future__ import annotations

import asyncio

import streamlit as st

from telegram_download_chat.core import DownloaderContext, TelegramChatDownloader


async def download_chat(chat: str, limit: int) -> list[dict]:
    """Download messages from a chat and return them as serializable dicts."""
    downloader = TelegramChatDownloader()
    ctx = DownloaderContext(downloader)
    async with ctx:
        messages = await downloader.download_chat(
            chat_id=chat,
            request_limit=limit or 100,
            total_limit=limit or 0,
            output_file=None,
            silent=True,
        )
        serializable = [
            downloader.make_serializable(m.to_dict() if hasattr(m, "to_dict") else m)
            for m in messages
        ]
        return serializable


def main() -> None:
    st.title("Telegram Download Chat")
    chat = st.text_input("Chat ID or username")
    limit = st.number_input("Message limit", min_value=0, value=100)

    if st.button("Download") and chat:
        with st.spinner("Downloading..."):
            messages = asyncio.run(download_chat(chat, int(limit)))
        st.success(f"Downloaded {len(messages)} messages")
        if messages:
            st.json(messages[:50])


if __name__ == "__main__":
    main()

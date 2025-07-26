import asyncio

import gradio as gr

from telegram_download_chat.cli.arguments import CLIOptions
from telegram_download_chat.cli.commands import process_chat_download
from telegram_download_chat.core import DownloaderContext, TelegramChatDownloader
from telegram_download_chat.paths import get_downloads_dir


async def download_chat(chat_id: str, limit: int = 100) -> str:
    """Download a chat and return path to the saved JSON file."""
    downloader = TelegramChatDownloader()
    ctx = DownloaderContext(downloader)
    args = CLIOptions(chat=chat_id, chats=[chat_id], limit=limit)
    downloads_dir = get_downloads_dir()
    async with ctx:
        result = await process_chat_download(downloader, chat_id, args, downloads_dir)
    if error := result.get("error"):
        return f"Error: {error}"
    return f"Saved to {result.get('result_json')}"


def gradio_download(chat_id: str, limit: int = 100) -> str:
    return asyncio.run(download_chat(chat_id, int(limit)))


def main() -> None:
    """Launch the Gradio web interface."""
    iface = gr.Interface(
        fn=gradio_download,
        inputs=[
            gr.Textbox(label="Chat ID", placeholder="@username or chat id"),
            gr.Number(label="Limit", value=100),
        ],
        outputs="text",
        title="Telegram Chat Downloader",
        description="Download Telegram chats through a simple web interface.",
    )
    iface.launch()


if __name__ == "__main__":
    main()

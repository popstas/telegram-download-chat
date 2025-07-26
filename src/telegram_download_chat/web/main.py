"""Simple NiceGUI web interface for Telegram Download Chat."""
from __future__ import annotations

from pathlib import Path

from nicegui import ui

from telegram_download_chat.core import TelegramChatDownloader
from telegram_download_chat.paths import get_downloads_dir

downloader = TelegramChatDownloader()


async def start_download(chat_id: str, limit: int) -> None:
    """Download chat and save messages."""
    await downloader.connect()
    output_dir = Path(
        downloader.config.get("settings", {}).get("save_path", get_downloads_dir())
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{chat_id}.json"

    messages = await downloader.download_chat(
        chat_id=chat_id,
        request_limit=limit if limit > 0 else 100,
        total_limit=limit if limit > 0 else 0,
    )
    await downloader.save_messages(messages, str(output_file))
    await downloader.close()

    ui.notify(f"Saved {len(messages)} messages to {output_file}")


@ui.page("/")
def index() -> None:
    ui.label("Telegram Download Chat (NiceGUI)")
    chat_input = ui.input("Chat ID or URL").props("outlined")
    limit_input = ui.number("Limit (0 for all)", value=0).props("outlined")

    async def on_click() -> None:
        await start_download(chat_input.value, int(limit_input.value or 0))

    ui.button("Download", on_click=on_click)
    ui.label("Check server console for logs.")


def main() -> None:
    """Run NiceGUI application."""
    ui.run(native=False)


if __name__ == "__main__":
    main()

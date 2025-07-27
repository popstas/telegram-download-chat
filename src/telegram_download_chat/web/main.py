"""Streamlit based web interface for telegram-download-chat."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

import streamlit as st

from telegram_download_chat.cli.arguments import CLIOptions
from telegram_download_chat.core import DownloaderContext, TelegramChatDownloader
from telegram_download_chat.paths import get_default_config_path, get_downloads_dir


class ProgressHandler(logging.Handler):
    """Update a Streamlit progress bar from downloader logs."""

    PROGRESS_RE = re.compile(r"Fetched: (\d+)")

    def __init__(self, bar, status, total: int):
        super().__init__()
        self.bar = bar
        self.status = status
        self.total = total

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - UI
        msg = record.getMessage()
        match = self.PROGRESS_RE.search(msg)
        if match:
            current = int(match.group(1))
            if self.total > 0:
                percent = min(current / self.total, 1.0)
                self.bar.progress(percent)
            self.status.text(msg)


async def run_download(options: CLIOptions) -> Path:
    """Download a chat and save messages to disk."""

    downloader = TelegramChatDownloader(config_path=options.config)
    if options.debug:
        downloader.logger.setLevel(logging.DEBUG)
    progress_placeholder = st.empty()
    status_placeholder = st.empty()
    handler = ProgressHandler(
        progress_placeholder.progress(0), status_placeholder, options.limit
    )
    downloader.logger.addHandler(handler)

    ctx = DownloaderContext(downloader)
    downloads_dir = Path(
        downloader.config.get("settings", {}).get("save_path", get_downloads_dir())
    )
    downloads_dir.mkdir(parents=True, exist_ok=True)

    async with ctx:
        chat_name = await downloader.get_entity_name(options.chat)
        output_file = (
            Path(options.output)
            if options.output
            else downloads_dir / f"{chat_name}.json"
        )
        messages = await downloader.download_chat(
            chat_id=options.chat,
            request_limit=min(100, options.limit or 100),
            total_limit=options.limit or 0,
            output_file=None,
            silent=False,
            until_date=options.until,
        )
        await downloader.save_messages(
            messages, str(output_file), sort_order=options.sort
        )

    downloader.logger.removeHandler(handler)
    progress_placeholder.progress(1.0)
    status_placeholder.text("Download complete")
    return output_file.with_suffix(".txt")


def show_config_file(config: Optional[str]) -> None:
    """Display configuration file path and contents."""

    cfg_path = Path(config) if config else get_default_config_path()
    st.info(f"Configuration file: {cfg_path}")
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            st.code(f.read())
    else:
        st.warning("Config file does not exist yet. It will be created on first run.")


def build_options() -> CLIOptions | None:
    """Render the input form and return CLIOptions if submitted."""

    if "form" not in st.session_state:
        st.session_state["form"] = {}
    data = st.session_state["form"]

    with st.form("download_form"):
        chat = st.text_input("Chat ID or username", value=data.get("chat", ""))
        output = st.text_input("Output file path", value=data.get("output", ""))
        limit = int(
            st.number_input(
                "Message limit (0 = no limit)",
                min_value=0,
                value=int(data.get("limit", 0)),
            )
        )
        from_date = st.text_input(
            "Base date for --last-days (YYYY-MM-DD)", value=data.get("from_date", "")
        )
        last_days = st.number_input(
            "Last days", min_value=0, value=int(data.get("last_days", 0))
        )
        until = st.text_input("Until date (YYYY-MM-DD)", value=data.get("until", ""))
        split_options = ["", "month", "year"]
        split = (
            st.selectbox(
                "Split output",
                split_options,
                index=split_options.index(data.get("split", "")),
            )
            or None
        )
        sort = st.selectbox(
            "Sort order",
            ["asc", "desc"],
            index=["asc", "desc"].index(data.get("sort", "asc")),
        )
        keywords = st.text_input(
            "Keywords (comma separated)", value=data.get("keywords", "")
        )
        submitted = st.form_submit_button("Download")

    if not submitted:
        return None

    if not chat:
        st.error("Chat ID is required")
        return None

    st.session_state["form"] = {
        "chat": chat,
        "output": output,
        "limit": limit,
        "from_date": from_date,
        "last_days": last_days,
        "until": until,
        "split": split or "",
        "sort": sort,
        "keywords": keywords,
    }

    return CLIOptions(
        chat=chat or None,
        chats=[chat] if chat else [],
        output=output or None,
        limit=limit,
        config=None,
        debug=False,
        show_config=False,
        subchat=None,
        subchat_name=None,
        user=None,
        from_date=from_date or None,
        last_days=int(last_days) if last_days else None,
        until=until or None,
        split=split,
        sort=sort,
        results_json=False,
        keywords=keywords or None,
    )


def main() -> None:  # pragma: no cover - UI
    st.title("Telegram Download Chat")
    options = build_options()
    if not options:
        return

    if options.show_config:
        show_config_file(options.config)
        return

    txt_path = asyncio.run(run_download(options))
    if txt_path.exists():
        st.download_button(
            "Download TXT file",
            data=txt_path.read_bytes(),
            file_name=txt_path.name,
            mime="text/plain",
        )
        with open(txt_path, "r", encoding="utf-8") as f:
            preview = "".join([f.readline() for _ in range(100)])
        st.text_area("Preview", preview, height=300)


if __name__ == "__main__":
    main()

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
from telegram_download_chat.core.presets import (
    add_preset,
    apply_preset,
    is_preset_modified,
    load_presets,
    remove_preset,
)
from telegram_download_chat.gui.utils import ConfigManager
from telegram_download_chat.paths import get_default_config_path, get_downloads_dir


def load_form_state() -> dict:
    """Load persisted form state from config."""
    cfg = ConfigManager()
    cfg.load()
    data = cfg.get("form_settings", {})
    if isinstance(data, dict):
        return data
    return {}


def save_form_state(state: dict) -> None:
    """Persist form state to config."""
    cfg = ConfigManager()
    cfg.load()
    cfg.set("form_settings", state)
    cfg.save()


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
    stop_placeholder = st.empty()
    handler = ProgressHandler(
        progress_placeholder.progress(0), status_placeholder, options.limit
    )
    downloader.logger.addHandler(handler)
    if stop_placeholder.button("Stop"):
        downloader.stop()

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
    stop_placeholder.empty()
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


def get_default_form_values() -> dict:
    """Get default values for the form."""
    return {
        "chat": "",
        "output": "",
        "limit": 0,
        "from_date": "",
        "last_days": 0,
        "until": "",
        "split": "",
        "sort": "asc",
        "keywords": "",
    }


def build_options() -> CLIOptions | None:
    """Render the input form and return CLIOptions if submitted."""

    # --- State Initialization ---
    if "form" not in st.session_state:
        defaults = get_default_form_values()
        defaults.update(load_form_state())
        st.session_state.form = defaults

    # --- Preset Handling ---
    presets = load_presets()
    preset_names = [p.get("name") for p in presets]

    def on_preset_change():
        # Read the widget's new value directly from its key in session_state.
        preset_name = st.session_state["form.preset"]
        selected_preset = next((p for p in presets if p["name"] == preset_name), None)
        if selected_preset:
            st.session_state.form.update(selected_preset.get("args", {}))
            st.session_state.form["preset"] = preset_name
        else:
            st.session_state.form = get_default_form_values()

    st.selectbox(
        "Preset",
        [""] + preset_names,
        key="form.preset",
        on_change=on_preset_change,
    )

    # --- Form Definition ---
    with st.form("download_form", clear_on_submit=False):
        form = st.session_state.form
        form["chat"] = st.text_input("Chat ID or username", value=form["chat"])
        form["output"] = st.text_input("Output file path", value=form["output"])
        form["limit"] = int(st.number_input("Message limit (0 = no limit)", min_value=0, value=form["limit"]))
        form["from_date"] = st.text_input("Base date for --last-days (YYYY-MM-DD)", value=form["from_date"])
        form["last_days"] = int(st.number_input("Last days", min_value=0, value=form["last_days"]))
        form["until"] = st.text_input("Until date (YYYY-MM-DD)", value=form["until"])

        split_options = ["", "month", "year"]
        split_idx = split_options.index(form["split"]) if form["split"] in split_options else 0
        form["split"] = st.selectbox("Split output", split_options, index=split_idx) or ""

        sort_options = ["asc", "desc"]
        sort_idx = sort_options.index(form["sort"]) if form["sort"] in sort_options else 0
        form["sort"] = st.selectbox("Sort order", sort_options, index=sort_idx)

        form["keywords"] = st.text_input("Keywords (comma separated)", value=form["keywords"])

        submitted = st.form_submit_button("Download")

    if not submitted:
        return None

    if not form.get("chat"):
        st.error("Chat ID is required")
        return None

    save_form_state(form)

    return CLIOptions(
        chat=form.get("chat"),
        chats=[form.get("chat")] if form.get("chat") else [],
        output=form.get("output"),
        limit=form.get("limit"),
        config=None,
        debug=False,
        show_config=False,
        subchat=None,
        subchat_name=None,
        user=None,
        from_date=form.get("from_date"),
        last_days=form.get("last_days"),
        until=form.get("until"),
        split=form.get("split"),
        sort=form.get("sort"),
        results_json=False,
        keywords=form.get("keywords"),
    )


def main() -> None:  # pragma: no cover - UI
    st.title("Telegram Download Chat")
    st.set_page_config(page_title="Telegram Download Chat", page_icon="assets/icon.png")

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

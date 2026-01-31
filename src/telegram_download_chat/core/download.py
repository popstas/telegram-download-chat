import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import GetHistoryRequest

from ..partial import PartialDownloadManager


class DownloadMixin:
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        logger = getattr(self, "logger", None)
        self.partial_manager = PartialDownloadManager(self.make_serializable, logger)
        self._stop_requested = False
        self._stop_file: Path | None = None

    async def download_chat(
        self,
        chat_id: str,
        request_limit: int = 100,
        total_limit: int = 0,
        output_file: Optional[str] = None,
        save_partial: bool = True,
        silent: bool = False,
        until_date: Optional[str] = None,
        from_date: Optional[str] = None,
        since_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not self.client:
            await self.connect()

        entity = await self.get_entity(chat_id)

        offset_id = since_id or 0
        all_messages: List[Any] = []

        output_path = Path(output_file) if output_file else None
        if output_file and save_partial:
            loaded_messages, last_id = self._load_partial_messages(output_path)
            if loaded_messages:
                all_messages = loaded_messages
                offset_id = max(offset_id, last_id)
                if not silent:
                    self.logger.info(
                        f"Resuming download from message ID {offset_id}..."
                    )

        total_fetched = len(all_messages)
        last_save = asyncio.get_event_loop().time()
        save_interval = 60

        while True:
            if self._stop_requested or (self._stop_file and self._stop_file.exists()):
                self._stop_requested = True
                if not silent:
                    self.logger.info("Stop requested, breaking download loop...")
                break

            try:
                history = await self.client(
                    GetHistoryRequest(
                        peer=entity,
                        offset_id=offset_id,
                        offset_date=None,
                        add_offset=0,
                        limit=request_limit,
                        max_id=0,
                        min_id=since_id or 0,
                        hash=0,
                    )
                )
            except FloodWaitError as e:
                wait = e.seconds + 1
                if not silent:
                    self.logger.info(f"Flood-wait {wait}s, sleeping...")

                if output_file and save_partial and all_messages:
                    self._save_partial_messages(all_messages, output_path)

                await asyncio.sleep(wait)
                continue

            if not history.messages:
                self.logger.debug("No more messages available")
                break

            new_messages = []
            for msg in history.messages:
                if not hasattr(msg, "id") or any(
                    m.id == msg.id for m in all_messages if hasattr(m, "id")
                ):
                    continue

                if until_date and hasattr(msg, "date") and msg.date:
                    until = datetime.strptime(until_date, "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                    msg_date = msg.date
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=timezone.utc)
                    if msg_date.date() < until.date():
                        if not silent:
                            self.logger.debug(
                                f"Reached message from {msg_date} which is older than {until_date}"
                            )
                        break

                if from_date and hasattr(msg, "date") and msg.date:
                    from_parsed = datetime.strptime(from_date, "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                    msg_date = msg.date
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=timezone.utc)
                    if msg_date.date() > from_parsed.date():
                        continue

                if since_id is None or msg.id > since_id:
                    new_messages.append(msg)

            all_messages.extend(new_messages)

            if not new_messages:
                self.logger.debug("No new messages found, stopping")
                break

            if until_date and len(new_messages) < len(history.messages):
                if not silent:
                    self.logger.info(
                        f"Reached messages older than {until_date}, stopping"
                    )
                break

            offset_id = min(msg.id for msg in history.messages)
            if since_id is not None and offset_id <= since_id:
                break
            total_fetched = len(all_messages)

            current_time = asyncio.get_event_loop().time()
            if (
                output_file
                and save_partial
                and current_time - last_save > save_interval
            ):
                self._save_partial_messages(all_messages, output_path)
                last_save = current_time

            if not silent:
                self.logger.info(
                    f"Fetched: {total_fetched} (batch: {len(new_messages)} new)"
                )

            if total_limit > 0 and total_fetched >= total_limit:
                break

        if output_file and save_partial and all_messages:
            self._save_partial_messages(all_messages, output_path)

        if total_limit > 0 and len(all_messages) >= total_limit:
            all_messages = all_messages[:total_limit]

        return all_messages

    def get_temp_file_path(self, output_file: Path) -> Path:
        return self.partial_manager.get_temp_file_path(output_file)

    def _save_partial_messages(
        self, messages: List[Dict[str, Any]], output_file: Path
    ) -> None:
        self.partial_manager.save_messages(messages, output_file)

    def _load_partial_messages(
        self, output_file: Path
    ) -> tuple[list[Dict[str, Any]], int]:
        return self.partial_manager.load_messages(output_file)

    def stop(self) -> None:
        self._stop_requested = True
        if self._stop_file:
            try:
                self._stop_file.touch()
            except Exception:
                pass

    def set_stop_file(self, stop_file_path: str) -> None:
        self._stop_file = Path(stop_file_path)
        if self._stop_file.exists():
            try:
                self._stop_file.unlink()
            except Exception:
                pass

    def cleanup_stop_file(self) -> None:
        if self._stop_file and self._stop_file.exists():
            try:
                self._stop_file.unlink()
            except Exception:
                pass

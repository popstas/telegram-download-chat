import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from telethon.errors import FloodWaitError, ChannelForumMissingError
from telethon.tl.functions.messages import GetHistoryRequest, GetForumTopicsRequest

from ..partial import PartialDownloadManager


class DownloadMixin:
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        logger = getattr(self, "logger", None)
        self.partial_manager = PartialDownloadManager(self.make_serializable, logger)
        self._stop_requested = False
        self._stop_file: Path | None = None

    async def get_all_topic_ids(self, chat_entity):
        """
        Retrieves the ID (top_msg_id) and title for all forum topics in a supergroup.
        """
        topics_map = {1: "General"} # Topic ID 1 is always the 'General' topic

        if not hasattr(chat_entity, 'megagroup') or not chat_entity.megagroup:
            return {}

        try:
            result = await self.client(GetForumTopicsRequest(
                peer=chat_entity,
                offset_date=None,
                offset_id=0,
                offset_topic=0,
                limit=0,
            ))
            if result and hasattr(result, 'topics'):
                for topic in result.topics:
                    topics_map[topic.id] = topic.title
            return topics_map

        except ChannelForumMissingError:
            self.logger.debug("Chat is not a forum, only 'General' topic exists.")
            return {1: "General"}

        except Exception as e:
            self.logger.info(f"Error fetching topics: {e}")
            return {}

    async def download_chat(
        self,
        chat_id: str,
        request_limit: int = 100,
        total_limit: int = 0,
        output_file: Optional[str] = None,
        save_partial: bool = True,
        silent: bool = False,
        until_date: Optional[str] = None,
        since_id: Optional[int] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        if not self.client:
            await self.connect()

        topic_id = None
        topic_title = "Main Chat"
        entity = await self.get_entity(chat_id)
        if not entity:
            self.logger.error(f"Could not find entity for chat_id: {chat_id}")
            return {}

        topics = await self.get_all_topic_ids(entity)
        is_forum = len(topics) > 1
        messages_by_topic: Dict[str, List[Dict[str, Any]]] = {}

        if is_forum:
            for topic_id, topic_title in topics.items():
                self.logger.info(f"Downloading topic: '{topic_title}' (ID: {topic_id})")
                topic_messages = await self.download_chat_by_topic(
                    chat_id,
                    topic_id=topic_id,
                    request_limit=request_limit,
                    total_limit=total_limit,
                    output_file=output_file,
                    save_partial=save_partial,
                    silent=silent,
                    until_date=until_date,
                    since_id=since_id,
                )
                messages_by_topic[topic_title] = topic_messages
        else:
            self.logger.info("Downloading chat...")
            all_messages = await self.download_chat_by_topic(
                chat_id,
                topic_id=topic_id,
                request_limit=request_limit,
                total_limit=total_limit,
                output_file=output_file,
                save_partial=save_partial,
                silent=silent,
                until_date=until_date,
                since_id=since_id,
            )
            messages_by_topic["Main Chat"] = all_messages

        return messages_by_topic

    async def download_chat_by_topic(
        self,
        chat_id: str,
        topic_id: Optional[int] = None,
        request_limit: int = 100,
        total_limit: int = 0,
        output_file: Optional[str] = None,
        save_partial: bool = True,
        silent: bool = False,
        until_date: Optional[str] = None,
        since_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not self.client:
            await self.connect()

        entity = await self.get_entity(chat_id)
        if not entity:
            self.logger.error(f"Could not find entity for chat_id: {chat_id}")
            return []

        offset_id = since_id or 0
        all_messages: List[Any] = []

        output_path = Path(output_file) if output_file else None
        if output_file and save_partial:
            loaded_messages, last_id = self._load_partial_messages(output_path, topic_id)
            if loaded_messages:
                all_messages = loaded_messages
                offset_id = max(offset_id, last_id)
                if not silent:
                    self.logger.info(
                        f"Resuming download for topic {topic_id} from message ID {offset_id}..."
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
                # Use get_messages with reply_to=topic_id to fetch from a specific topic
                history = await self.client.get_messages(
                    entity,
                    limit=request_limit,
                    offset_id=offset_id,
                    min_id=since_id or 0,
                    reply_to=topic_id
                )
            except FloodWaitError as e:
                wait = e.seconds + 1
                if not silent:
                    self.logger.info(f"Flood-wait {wait}s, sleeping...")

                if output_file and save_partial and all_messages:
                    self._save_partial_messages(all_messages, output_path, topic_id)

                await asyncio.sleep(wait)
                continue

            if not history:
                self.logger.debug("No more messages available")
                break

            new_messages = []
            for msg in history:
                # The `since_id` check needs to be done manually when using `reply_to`
                if not hasattr(msg, "id") or any(
                    hasattr(m, "id") and m.id == msg.id for m in all_messages
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

                if since_id is None or msg.id > since_id:
                    new_messages.append(msg)

            all_messages.extend(new_messages)

            if not new_messages:
                self.logger.debug("No new messages found, stopping")
                break

            if until_date and len(new_messages) < len(history):
                if not silent:
                    self.logger.info(
                        f"Reached messages older than {until_date}, stopping"
                    )
                break

            offset_id = min(msg.id for msg in history)
            if since_id is not None and offset_id <= since_id:
                break
            total_fetched = len(all_messages)

            current_time = asyncio.get_event_loop().time()
            if (
                output_file
                and save_partial
                and current_time - last_save > save_interval
            ):
                self._save_partial_messages(all_messages, output_path, topic_id)
                last_save = current_time

            if not silent:
                self.logger.info(
                    f"Fetched: {total_fetched} (batch: {len(new_messages)} new)"
                )

            if total_limit > 0 and total_fetched >= total_limit:
                break

        if output_file and save_partial and all_messages:
            self._save_partial_messages(all_messages, output_path, topic_id)

        if total_limit > 0 and len(all_messages) >= total_limit:
            all_messages = all_messages[:total_limit]

        return all_messages

    def get_temp_file_path(self, output_file: Path, topic_id: Optional[int] = None) -> Path:
        return self.partial_manager.get_temp_file_path(output_file, topic_id)

    def _save_partial_messages(
        self, messages: List[Dict[str, Any]], output_file: Path, topic_id: Optional[int] = None
    ) -> None:
        self.partial_manager.save_messages(messages, output_file, topic_id)

    def _load_partial_messages(
        self, output_file: Path, topic_id: Optional[int] = None
    ) -> tuple[list[Dict[str, Any]], int]:
        return self.partial_manager.load_messages(output_file, topic_id)

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

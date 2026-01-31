import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ..paths import get_relative_to_downloads_dir


class MessagesMixin:
    def convert_archive_to_messages(
        self, archive: Dict[str, Any], user_filter: str | None = None
    ) -> List[Dict[str, Any]]:
        self.logger.debug("Converting archive to messages...")
        if user_filter:
            self.logger.info(f"Filtering messages by user: {user_filter}")
            user_filter = (
                user_filter.replace("user", "")
                if user_filter.startswith("user")
                else user_filter
            )

        messages = []
        chats = archive.get("chats", {}).get("list", [])
        left_chats = archive.get("left_chats", {}).get("list", [])
        chats.extend(left_chats)

        self.logger.info(
            f"Found {len(chats)} chats, including {len(left_chats)} left chats"
        )
        for chat in chats:
            chat_id = chat.get("id")
            if not chat_id:
                continue

            for message in chat.get("messages", []):
                if message.get("type") != "message":
                    continue

                text = message.get("text", "")
                if isinstance(text, list):
                    text_parts = []
                    for part in text:
                        if isinstance(part, str):
                            text_parts.append(part)
                        elif isinstance(part, dict):
                            text_parts.append(part.get("text", ""))
                    text = "".join(text_parts)
                elif not isinstance(text, str):
                    text = str(text)

                from_id = message.get("from_id", "")
                if isinstance(from_id, str) and from_id.startswith("user"):
                    try:
                        user_id = int(from_id[4:])
                    except (ValueError, TypeError):
                        user_id = from_id
                else:
                    user_id = from_id

                if user_filter and str(user_id) != user_filter:
                    continue

                formatted = {
                    "id": message.get("id"),
                    "peer_id": {
                        "_": "PeerChat"
                        if chat.get("type") == "group"
                        else "PeerChannel",
                        "channel_id"
                        if chat.get("type") in ["channel", "public_supergroup"]
                        else "user_id": chat_id,
                    },
                    "date": message.get("date"),
                    "message": text,
                    "from_id": {"_": "PeerUser", "user_id": user_id},
                }

                if "reply_to_message_id" in message:
                    formatted["reply_to_msg_id"] = message["reply_to_message_id"]

                messages.append(formatted)

        return messages

    def prepare_messages_for_txt(
        self, messages: List[Dict[str, Any]], sort_order: str = "asc"
    ) -> List[Dict[str, Any]]:
        def parse_dt(msg: Dict[str, Any]) -> datetime:
            date_str = msg.get("date")
            if not date_str:
                return datetime.min
            try:
                return datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
            except Exception:
                return datetime.min

        id_map: Dict[Any, Dict[str, Any]] = {
            m.get("id"): m for m in messages if m.get("id") is not None
        }
        children: Dict[Any, List[Dict[str, Any]]] = {}
        roots: List[Dict[str, Any]] = []

        for msg in messages:
            reply = msg.get("reply_to") or {}
            reply_id = reply.get("reply_to_msg_id") or msg.get("reply_to_msg_id")
            if reply_id and reply_id in id_map:
                children.setdefault(reply_id, []).append(msg)
            else:
                roots.append(msg)

        def sort_msgs(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            return sorted(msgs, key=parse_dt, reverse=(sort_order == "desc"))

        def traverse(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
            child_msgs = []
            for child in sort_msgs(children.get(msg.get("id"), [])):
                child_msgs.extend(traverse(child))

            if sort_order == "desc":
                return child_msgs + [msg]
            return [msg] + child_msgs

        ordered_messages: List[Dict[str, Any]] = []
        for root in sort_msgs(roots):
            ordered_messages.extend(traverse(root))

        return ordered_messages

    async def save_messages_as_txt(
        self, messages: List[Dict[str, Any]], txt_path: Path, sort_order: str = "asc"
    ) -> int:
        saved = 0
        txt_path.parent.mkdir(parents=True, exist_ok=True)

        ordered_messages = self.prepare_messages_for_txt(messages, sort_order)

        for msg in ordered_messages:
            try:
                date_str = msg.get("date", "")
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        date_fmt = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except (ValueError, TypeError):
                        date_fmt = ""
                else:
                    date_fmt = ""

                sender_name = ""
                sender_id = self._get_sender_id(msg)
                if sender_id:
                    sender_name = await self._get_user_display_name(sender_id)

                text = msg.get("text", "")
                if not text and "message" in msg:
                    text = msg["message"]

                recipient_name = ""
                recipient_id = self._get_recipient_id(msg)
                if recipient_id:
                    recipient_name = await self._get_peer_display_name(recipient_id)

                if date_fmt or sender_name:
                    if recipient_name:
                        line = (
                            f"{date_fmt} {sender_name} -> {recipient_name}:\n{text}\n\n"
                        )
                    else:
                        line = f"{date_fmt} {sender_name}:\n{text}\n\n"
                else:
                    line = f"{text}\n\n"

                with open(txt_path, "a", encoding="utf-8") as f:
                    f.write(line)
                saved += 1
            except Exception as e:
                logging.warning(f"Error saving message to TXT: {e}")

        if self._fetched_usernames_count > 0 or self._fetched_chatnames_count > 0:
            self._save_config()

        return saved

    def make_serializable(self, obj):
        if isinstance(obj, dict):
            return {k: self.make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self.make_serializable(x) for x in obj]
        elif isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        else:
            try:
                return str(obj)
            except Exception:
                return None

    def get_attachments_dir(self, output_file: Path) -> Path:
        """Get the attachments directory path for a given output file.

        Creates a name <output_file_without_extension>_attachments in the same
        directory as the output file.
        """
        return output_file.parent / f"{output_file.stem}_attachments"

    async def save_messages(
        self,
        messages,
        output_file: str,
        save_txt: bool = True,
        sort_order: str = "asc",
        download_media: bool = False,
    ) -> None:
        output_path = Path(output_file)

        serializable_messages = []
        for msg in messages:
            try:
                msg_dict = msg.to_dict() if hasattr(msg, "to_dict") else msg
                serializable_messages.append(self.make_serializable(msg_dict))
            except Exception as e:
                self.logger.warning(f"Failed to serialize message: {e}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(serializable_messages, f, ensure_ascii=False, indent=2)

        if save_txt:
            txt_path = output_path.with_suffix(".txt")
            saved = await self.save_messages_as_txt(
                serializable_messages, txt_path, sort_order
            )
            txt_path_relative = get_relative_to_downloads_dir(txt_path)
            self.logger.info(f"Saved {saved} messages to {txt_path_relative}")

        # Download media attachments if requested
        if download_media:
            self.logger.info("Downloading media attachments...")
            await self.download_all_media(messages, self.get_attachments_dir(output_path))

        partial = self.get_temp_file_path(output_path)
        if partial.exists() and not self._stop_requested:
            self.logger.debug(f"Removing partial file: {partial}")
            partial.unlink()

        output_file_relative = get_relative_to_downloads_dir(output_path)
        self.logger.info(f"Saved {len(messages)} messages to {output_file_relative}")

import json
import logging
import time
from pathlib import Path, PurePath
from typing import Any, Callable, Dict, List, Tuple


class PartialDownloadManager:
    """Manage partial download files for resuming later."""

    def __init__(
        self,
        make_serializable: Callable[[Any], Any],
        logger: logging.Logger | None = None,
    ) -> None:
        self.make_serializable = make_serializable
        self.logger = logger or logging.getLogger(__name__)
        self._last_saved_ids: Dict[PurePath, int] = {}

    def get_temp_file_path(self, output_file: Path, topic_id: int | None = None) -> Path:
        """Return path for temporary partial file."""
        if topic_id is not None:
            return output_file.with_suffix(f".{topic_id}.part.jsonl")
        return output_file.with_suffix(f".part.jsonl")

    def save_messages(self, messages: List[Dict[str, Any]], output_file: Path, topic_id: int | None = None) -> None:
        """Save messages to a JSONL temporary file for partial downloads."""
        start_time = time.time()
        temp_file = self.get_temp_file_path(output_file, topic_id)
        temp_file.parent.mkdir(parents=True, exist_ok=True)

        last_saved_id = self._last_saved_ids.get(temp_file, 0)

        new_saved = 0
        new_last_id = last_saved_id
        with open(temp_file, "a", encoding="utf-8") as f:
            for msg in messages:
                try:
                    msg_dict = msg.to_dict() if hasattr(msg, "to_dict") else msg
                    serialized = self.make_serializable(msg_dict)
                    msg_id = serialized.get("id", 0)

                    if msg_id > last_saved_id:
                        json.dump({"m": serialized, "i": msg_id}, f, ensure_ascii=False)
                        f.write("\n")
                        new_saved += 1
                        if msg_id > new_last_id:
                            new_last_id = msg_id
                except Exception as e:  # pragma: no cover - safety net
                    self.logger.warning(f"Failed to serialize message: {e}")

        if new_last_id > last_saved_id:
            self._last_saved_ids[temp_file] = new_last_id

        elapsed = time.time() - start_time
        self.logger.info(
            f"Saved {new_saved} new messages to partial file in {elapsed:.2f}s"
        )

    def load_messages(self, output_file: Path, topic_id: int | None = None) -> Tuple[List[Dict[str, Any]], int]:
        """Load messages from partial file if it exists."""
        temp_file = self.get_temp_file_path(output_file, topic_id)
        if not temp_file.exists():
            return [], 0

        messages: List[Dict[str, Any]] = []
        last_id = 0
        try:
            with open(temp_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if isinstance(data, dict) and "m" in data:
                            messages.append(data["m"])
                            last_id = data.get("i", last_id)
                    except json.JSONDecodeError as e:
                        logging.warning(f"Skipping invalid JSON line: {e}")
                        continue
            self._last_saved_ids[temp_file] = last_id
            return messages, last_id
        except (IOError, json.JSONDecodeError) as e:
            logging.warning(f"Error loading partial messages: {e}")
            return [], 0

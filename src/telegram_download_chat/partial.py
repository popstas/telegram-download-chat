import json
import logging
import time
from pathlib import Path
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

    def get_temp_file_path(self, output_file: Path) -> Path:
        """Return path for temporary partial file."""
        return output_file.with_suffix(".part.jsonl")

    def save_messages(self, messages: List[Dict[str, Any]], output_file: Path) -> None:
        """Save messages to a JSONL temporary file for partial downloads."""
        start_time = time.time()
        temp_file = self.get_temp_file_path(output_file)
        temp_file.parent.mkdir(parents=True, exist_ok=True)

        existing_ids: set[int] = set()
        if temp_file.exists():
            try:
                with open(temp_file, "r", encoding="utf-8") as f:
                    all_lines = f.readlines()
                    last_10k_lines = (
                        all_lines[-10000:] if len(all_lines) > 10000 else all_lines
                    )
                    for line in last_10k_lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            if isinstance(data, dict) and "i" in data:
                                existing_ids.add(data["i"])
                        except json.JSONDecodeError:
                            continue
            except IOError:
                pass

        new_saved = 0
        with open(temp_file, "a", encoding="utf-8") as f:
            for msg in messages[-10000:]:
                try:
                    msg_dict = msg.to_dict() if hasattr(msg, "to_dict") else msg
                    serialized = self.make_serializable(msg_dict)
                    msg_id = (
                        msg_dict.get("id")
                        if hasattr(msg_dict, "get")
                        else getattr(msg_dict, "id", 0)
                    )
                    if msg_id not in existing_ids:
                        json.dump({"m": serialized, "i": msg_id}, f, ensure_ascii=False)
                        f.write("\n")
                        existing_ids.add(msg_id)
                        new_saved += 1
                except Exception as e:  # pragma: no cover - safety net
                    self.logger.warning(f"Failed to serialize message: {e}")

        elapsed = time.time() - start_time
        self.logger.info(
            f"Saved {new_saved} new messages to partial file in {elapsed:.2f}s"
        )

    def load_messages(self, output_file: Path) -> Tuple[List[Dict[str, Any]], int]:
        """Load messages from partial file if it exists."""
        temp_file = self.get_temp_file_path(output_file)
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
            return messages, last_id
        except (IOError, json.JSONDecodeError) as e:
            logging.warning(f"Error loading partial messages: {e}")
            return [], 0

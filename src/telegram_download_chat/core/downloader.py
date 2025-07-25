import logging
from typing import Optional

from ..partial import PartialDownloadManager
from .auth import AuthMixin
from .config import ConfigMixin
from .download import DownloadMixin
from .entities import EntitiesMixin
from .messages import MessagesMixin


class TelegramChatDownloader(
    ConfigMixin, AuthMixin, DownloadMixin, EntitiesMixin, MessagesMixin
):
    """Main class for downloading Telegram chat history."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self.config_path = config_path
        self.config = self._load_config()
        self._setup_logging()
        logger = getattr(self, "logger", logging.getLogger(__name__))
        self.partial_manager = PartialDownloadManager(self.make_serializable, logger)
        self.client = None
        self.phone_code_hash = None
        self._fetched_usernames_count = 0
        self._fetched_chatnames_count = 0
        self._self_id: Optional[int] = None
        self._self_name: Optional[str] = None
        self._stop_requested = False
        self._stop_file = None

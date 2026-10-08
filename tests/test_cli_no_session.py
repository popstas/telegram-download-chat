"""A download without a session reports one line, not a traceback (issue #91)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram_download_chat.cli import async_main
from telegram_download_chat.core.auth_utils import NO_SESSION_MESSAGE, NoSessionError


@pytest.mark.asyncio
async def test_missing_session_is_reported_without_a_traceback():
    downloader = MagicMock()
    downloader.logger = MagicMock()
    downloader.config = {"settings": {}}
    # A session was there when the download started; connect() finds it gone.
    downloader.prepare_client = AsyncMock(return_value=True)
    downloader.set_stop_file = MagicMock()
    downloader.close = AsyncMock()
    downloader.cleanup_stop_file = MagicMock()

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(side_effect=NoSessionError(NO_SESSION_MESSAGE))
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("sys.argv", ["telegram-download-chat", "popstas", "--limit", "10"]):
        with patch(
            "telegram_download_chat.cli.TelegramChatDownloader", return_value=downloader
        ):
            with patch(
                "telegram_download_chat.cli.DownloaderContext", return_value=ctx
            ):
                assert await async_main() == 1

    # connect() already logged the instruction; the CLI must not repeat it with
    # a stack trace on top.
    downloader.logger.exception.assert_not_called()

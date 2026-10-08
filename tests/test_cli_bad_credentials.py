"""Placeholder credentials must explain themselves, not raise int('YOUR_API_ID').

A first run writes a config with `YOUR_API_ID` in it. The next run used to die
with `ValueError: invalid literal for int()` and a traceback on top of the
instructions, which is the first thing a new user sees (issue #91's reporter
was one).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram_download_chat.core.auth import AuthMixin
from telegram_download_chat.core.auth_utils import ConfigurationError


class _Downloader(AuthMixin):
    def __init__(self, settings):
        self.config = {"settings": settings}
        self.logger = MagicMock()
        self.client = None


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"api_id": "YOUR_API_ID", "api_hash": "YOUR_API_HASH"},
        {"api_id": "not-a-number", "api_hash": "0123456789abcdef"},
    ],
    ids=["missing", "placeholders", "not-a-number"],
)
@pytest.mark.asyncio
async def test_unusable_credentials_name_my_telegram_org(settings):
    with pytest.raises(ConfigurationError) as excinfo:
        await _Downloader(settings).prepare_client()

    assert "my.telegram.org" in str(excinfo.value)


@pytest.mark.asyncio
async def test_the_cli_reports_it_without_a_traceback():
    from telegram_download_chat import cli

    downloader = MagicMock()
    downloader.logger = MagicMock()
    downloader.config = {"settings": {}}
    downloader.close = AsyncMock()
    downloader.prepare_client = AsyncMock(
        side_effect=ConfigurationError("Set api_id and api_hash: my.telegram.org")
    )

    with patch("sys.argv", ["telegram-download-chat", "popstas"]):
        with patch.object(cli, "TelegramChatDownloader", return_value=downloader):
            assert await cli.async_main() == 1

    # prepare_client() logs the message itself; the CLI must not add a
    # traceback, nor repeat the line.
    downloader.logger.exception.assert_not_called()
    downloader.logger.error.assert_not_called()

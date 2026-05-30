"""Regression test: a session written by a newer Telethon yields a clear error.

When the installed Telethon is older than the one that created the
``session.session`` file, Telethon's ``SQLiteSession`` unpacks ``select * from
sessions`` into the wrong number of targets and raises
``ValueError: too many values to unpack (expected 5)``. ``connect()`` should turn
that cryptic message into an actionable "upgrade Telethon" instruction rather
than a generic connection failure.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram_download_chat.core import TelegramChatDownloader


def _downloader() -> TelegramChatDownloader:
    downloader = TelegramChatDownloader()
    downloader.config = {
        "settings": {
            "api_id": "12345",
            "api_hash": "abcdef1234567890abcdef1234567890",
        }
    }
    downloader.client = None
    return downloader


@pytest.mark.asyncio
async def test_connect_raises_clear_error_on_newer_session_schema():
    downloader = _downloader()

    mock_auth = MagicMock()
    # initialize() fails the way Telethon does when the session schema is newer
    # than the installed library (the 5-target unpack of a 6-column row).
    mock_auth.initialize = AsyncMock(
        side_effect=ValueError("too many values to unpack (expected 5)")
    )
    mock_auth.client = None

    with patch("telegram_download_chat.core.auth.TelegramAuth", return_value=mock_auth):
        with pytest.raises(RuntimeError) as exc_info:
            await downloader.connect()

    message = str(exc_info.value)
    assert "Telethon" in message
    assert "pip install -U 'telethon>=1.43.0'" in message
    # The original ValueError is preserved as the cause.
    assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.asyncio
async def test_connect_passes_through_unrelated_value_error():
    """A ValueError that is NOT the schema mismatch is not relabeled as an upgrade."""
    downloader = _downloader()

    mock_auth = MagicMock()
    mock_auth.initialize = AsyncMock(side_effect=ValueError("some other problem"))
    mock_auth.client = None

    with patch("telegram_download_chat.core.auth.TelegramAuth", return_value=mock_auth):
        with pytest.raises(ValueError) as exc_info:
            await downloader.connect()

    # Re-raised unchanged (not wrapped in RuntimeError, no upgrade text).
    assert "some other problem" in str(exc_info.value)
    assert "telethon" not in str(exc_info.value).lower()

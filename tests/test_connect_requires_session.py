"""connect() never prompts and never sends a login code on its own (issue #91).

The GUI runs downloads as a CLI subprocess with no stdin, so the old
"no session -> client.start()" branch crashed with ``RuntimeError: lost
sys.stdin``. Interactive login now lives only in the ``login`` command, and
connect() raises an actionable error instead. A phone saved in the config must
not turn a plain download into a silent code request either.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram_download_chat.core import TelegramChatDownloader
from telegram_download_chat.core.auth_utils import NO_SESSION_MESSAGE, NoSessionError


def _downloader(**settings) -> TelegramChatDownloader:
    downloader = TelegramChatDownloader.__new__(TelegramChatDownloader)
    downloader.logger = MagicMock()
    downloader.config = {
        "settings": {
            "api_id": "12345",
            "api_hash": "abcdef1234567890abcdef1234567890",
            **settings,
        }
    }
    downloader.client = None
    return downloader


def _auth(authorized: bool):
    auth = MagicMock()
    auth.initialize = AsyncMock()
    auth.is_authenticated = MagicMock(return_value=authorized)
    auth.request_code = AsyncMock(return_value="hash")
    auth.sign_in = AsyncMock(return_value=True)
    auth.client = MagicMock()
    auth.client.start = AsyncMock()
    auth.client.is_user_authorized = AsyncMock(return_value=authorized)
    return auth


@pytest.mark.asyncio
async def test_no_session_raises_actionable_error_without_prompting():
    downloader = _downloader()
    auth = _auth(authorized=False)

    with patch("telegram_download_chat.core.auth.TelegramAuth", return_value=auth):
        with pytest.raises(NoSessionError) as exc_info:
            await downloader.connect()

    assert str(exc_info.value) == NO_SESSION_MESSAGE
    assert "login" in NO_SESSION_MESSAGE
    assert "GUI" in NO_SESSION_MESSAGE
    auth.client.start.assert_not_called()
    auth.request_code.assert_not_called()


@pytest.mark.asyncio
async def test_no_session_error_is_not_wrapped_as_connect_failure():
    """The generic handler must not relabel it "Failed to connect to Telegram"."""
    downloader = _downloader()
    auth = _auth(authorized=False)

    with patch("telegram_download_chat.core.auth.TelegramAuth", return_value=auth):
        with pytest.raises(NoSessionError) as exc_info:
            await downloader.connect()

    assert "Failed to connect" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_phone_in_config_does_not_trigger_a_code_request():
    """A phone saved by the GUI must not make a plain download send a code."""
    downloader = _downloader(phone="+41791234567")
    auth = _auth(authorized=False)

    with patch("telegram_download_chat.core.auth.TelegramAuth", return_value=auth):
        with pytest.raises(NoSessionError):
            await downloader.connect()

    auth.request_code.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_phone_still_requests_a_code():
    """The GUI login flow passes the phone explicitly and must keep working."""
    downloader = _downloader()
    auth = _auth(authorized=False)

    with patch("telegram_download_chat.core.auth.TelegramAuth", return_value=auth):
        await downloader.connect("+41791234567")

    auth.request_code.assert_awaited_once_with("+41791234567")
    assert downloader.phone_code_hash == "hash"


@pytest.mark.asyncio
async def test_explicit_phone_and_code_signs_in():
    downloader = _downloader()
    auth = _auth(authorized=False)

    with patch("telegram_download_chat.core.auth.TelegramAuth", return_value=auth):
        with patch.object(
            TelegramChatDownloader, "_fetch_self_info", AsyncMock()
        ) as fetch:
            assert await downloader.connect("+41791234567", "12345") is True

    auth.sign_in.assert_awaited_once()
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_session_connects():
    downloader = _downloader()
    auth = _auth(authorized=True)

    with patch("telegram_download_chat.core.auth.TelegramAuth", return_value=auth):
        with patch.object(
            TelegramChatDownloader, "_fetch_self_info", AsyncMock()
        ) as fetch:
            assert await downloader.connect() is True

    fetch.assert_awaited_once()
    auth.client.start.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_client_reports_authorization_without_raising():
    """The login command needs the client built even when there is no session."""
    downloader = _downloader()
    auth = _auth(authorized=False)

    with patch("telegram_download_chat.core.auth.TelegramAuth", return_value=auth):
        assert await downloader.prepare_client() is False

    assert downloader.client is auth.client

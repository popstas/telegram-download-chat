"""Login code requests are traced at DEBUG level only (issue #91).

A user reported "no code arrives" and the log stopped at "No session found,
starting interactive login" with nothing about what Telegram answered. The
code request is now logged with the delivery type, but only under --debug so
normal runs stay quiet.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telethon import types
from telethon.errors import FloodWaitError

from telegram_download_chat.core.auth_utils import (
    TelegramAuth,
    describe_sent_code,
    mask_phone,
)

LOGGER = "telegram_download_chat.core.auth_utils"


@pytest.fixture
def caplog(caplog):
    # TelegramChatDownloader._setup_logging turns off propagation on the package
    # logger, so attach the capture handler to this module's logger directly.
    log = logging.getLogger(LOGGER)
    log.addHandler(caplog.handler)
    yield caplog
    log.removeHandler(caplog.handler)


def _sent_code(code_type, next_type=None, timeout=None):
    return types.auth.SentCode(
        type=code_type, phone_code_hash="hash", next_type=next_type, timeout=timeout
    )


async def _auth_with(send_code_request):
    client = MagicMock()
    client.connect = AsyncMock()
    client.is_user_authorized = AsyncMock(return_value=False)
    client.send_code_request = send_code_request
    client.session.dc_id = 4
    with patch(
        "telegram_download_chat.core.auth_utils.TelegramClient", return_value=client
    ):
        auth = TelegramAuth(api_id=1, api_hash="h", session_path="s.session")
        await auth.initialize()
    return auth


def test_mask_phone_keeps_only_last_digits():
    assert mask_phone("+41 79 123 45 67") == "+*********67"
    assert mask_phone("") == ""


def test_describe_sent_code_names_delivery():
    text = describe_sent_code(
        _sent_code(
            types.auth.SentCodeTypeApp(length=5),
            next_type=types.auth.CodeTypeSms(),
            timeout=60,
        )
    )
    assert "SentCodeTypeApp" in text
    assert "Telegram app" in text
    assert "next_type=CodeTypeSms" in text
    assert "timeout=60" in text


@pytest.mark.asyncio
async def test_code_request_logged_at_debug(caplog):
    result = _sent_code(types.auth.SentCodeTypeApp(length=5))
    auth = await _auth_with(AsyncMock(return_value=result))

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        assert await auth.client.send_code_request("+41791234567") is result

    messages = [r.getMessage() for r in caplog.records if r.name == LOGGER]
    assert any("+*********67" in m for m in messages)
    assert any("SentCodeTypeApp" in m and "dc=4" in m for m in messages)
    assert all("791234567" not in m for m in messages)
    assert all(r.levelno == logging.DEBUG for r in caplog.records if r.name == LOGGER)


@pytest.mark.asyncio
async def test_code_request_silent_at_info(caplog):
    result = _sent_code(types.auth.SentCodeTypeSms(length=5))
    auth = await _auth_with(AsyncMock(return_value=result))

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await auth.client.send_code_request("+41791234567")

    assert [r for r in caplog.records if r.name == LOGGER] == []


@pytest.mark.asyncio
async def test_code_request_failure_logged_and_reraised(caplog):
    error = FloodWaitError(request=None, capture=120)
    auth = await _auth_with(AsyncMock(side_effect=error))

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        with pytest.raises(FloodWaitError):
            await auth.client.send_code_request("+41791234567")

    assert any(
        "FloodWaitError" in r.getMessage() for r in caplog.records if r.name == LOGGER
    )

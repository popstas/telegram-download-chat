"""`connect()` must learn who we are even when the session is already open.

`ensure_session` connects and authorizes the client before a download, so
`connect()` takes its `is_user_authorized()` short-circuit — which used to skip
`_fetch_self_info()` and leave `_self_id` unset. Own messages are marked by it
(`render.py`) and "me" is resolved through it (`entities.py`), so losing it
degrades an export silently.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from telegram_download_chat.core.auth import AuthMixin


class _Downloader(AuthMixin):
    def __init__(self):
        self.config = {"settings": {"api_id": 1, "api_hash": "h"}}
        self.logger = MagicMock()
        self.client = MagicMock()
        self.client.is_user_authorized = AsyncMock(return_value=True)
        self.client.get_me = AsyncMock(
            return_value=MagicMock(id=42, first_name="Stanislav", last_name=None)
        )
        self._self_id = None
        self.prepare_client = AsyncMock(
            side_effect=AssertionError("an open session needs no second client")
        )


@pytest.mark.asyncio
async def test_an_already_open_session_still_identifies_the_user():
    downloader = _Downloader()

    await downloader.connect()

    assert downloader._self_id == 42


@pytest.mark.asyncio
async def test_the_identity_is_fetched_once():
    downloader = _Downloader()

    await downloader.connect()
    await downloader.connect()

    downloader.client.get_me.assert_awaited_once()

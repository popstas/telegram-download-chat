"""Channel posts are authored by the channel itself (``from_id`` is absent and
``peer_id`` is a ``PeerChannel``). The display name must resolve to the channel
title, not the raw numeric channel id.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon.tl.types import Channel

from telegram_download_chat.core.entities import EntitiesMixin


def _mixin():
    m = EntitiesMixin()
    m._get_user_display_name = AsyncMock(return_value="Alice User")
    m._get_peer_display_name = AsyncMock(return_value="My Channel")
    return m


class TestSenderIsChannel:
    def test_broadcast_post_with_no_from_id(self):
        msg = {
            "from_id": None,
            "peer_id": {"_": "PeerChannel", "channel_id": 1511414765},
            "post": True,
        }
        assert _mixin()._sender_is_channel(msg) is True

    def test_channel_from_id(self):
        msg = {"from_id": {"_": "PeerChannel", "channel_id": 42}}
        assert _mixin()._sender_is_channel(msg) is True

    def test_regular_user_message(self):
        msg = {
            "from_id": {"_": "PeerUser", "user_id": 7},
            "peer_id": {"_": "PeerChannel", "channel_id": 1511414765},
        }
        assert _mixin()._sender_is_channel(msg) is False

    def test_plain_int_user_from_id(self):
        msg = {"from_id": 123}
        assert _mixin()._sender_is_channel(msg) is False


class TestResolveSenderDisplayName:
    @pytest.mark.asyncio
    async def test_channel_post_uses_channel_title(self):
        m = _mixin()
        msg = {
            "from_id": None,
            "peer_id": {"_": "PeerChannel", "channel_id": 1511414765},
            "post": True,
        }
        name = await m._resolve_sender_display_name(msg)
        assert name == "My Channel"
        m._get_peer_display_name.assert_awaited_once_with(1511414765)
        m._get_user_display_name.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_signed_post_uses_post_author(self):
        m = _mixin()
        msg = {
            "from_id": None,
            "peer_id": {"_": "PeerChannel", "channel_id": 1511414765},
            "post": True,
            "post_author": "Ivan Editor",
        }
        name = await m._resolve_sender_display_name(msg)
        assert name == "Ivan Editor"
        m._get_peer_display_name.assert_not_awaited()
        m._get_user_display_name.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_regular_message_uses_user_name(self):
        m = _mixin()
        msg = {"from_id": {"_": "PeerUser", "user_id": 7}}
        name = await m._resolve_sender_display_name(msg)
        assert name == "Alice User"
        m._get_user_display_name.assert_awaited_once_with(7)

    @pytest.mark.asyncio
    async def test_no_sender_is_unknown(self):
        m = _mixin()
        name = await m._resolve_sender_display_name({})
        assert name == "Unknown"


class TestCachePoisoning:
    """A failed resolution stringifies the id (e.g. ``"1511414765"``). Caching
    that sentinel as a name would permanently mask the real title; treat such a
    cached value as a miss and never store it."""

    def _entities(self, config):
        m = EntitiesMixin()
        m.config = config
        m.logger = logging.getLogger("test")
        m._fetched_usernames_count = 0
        m._fetched_chatnames_count = 0
        m._save_config = MagicMock()
        return m

    @pytest.mark.asyncio
    async def test_peer_name_ignores_poisoned_user_cache(self):
        m = self._entities({"users_map": {1511414765: "1511414765"}, "chats_map": {}})
        entity = MagicMock(spec=Channel)
        entity.title = "My Channel"
        m.get_entity = AsyncMock(return_value=entity)
        name = await m._get_peer_display_name(1511414765)
        assert name == "My Channel"

    @pytest.mark.asyncio
    async def test_user_name_failure_is_not_cached(self):
        m = self._entities({"users_map": {}})
        m.fetch_user_name = AsyncMock(return_value="999")  # resolution failed
        name = await m._get_user_display_name(999)
        assert name == "999"
        assert 999 not in m.config["users_map"]

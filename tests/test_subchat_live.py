"""--subchat on a live download: Telethon messages and forum-topic fetch."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon.tl.functions.messages import GetHistoryRequest, GetRepliesRequest
from telethon.tl.types import Message, MessageReplyHeader, PeerChannel

from telegram_download_chat.cli.commands import filter_messages_by_subchat
from telegram_download_chat.core.download import DownloadMixin

DATE = datetime(2026, 11, 11, tzinfo=timezone.utc)


def _msg(msg_id, reply_to_msg_id=None, reply_to_top_id=None):
    reply_to = None
    if reply_to_msg_id is not None:
        reply_to = MessageReplyHeader(
            reply_to_msg_id=reply_to_msg_id,
            reply_to_top_id=reply_to_top_id,
            forum_topic=True,
        )
    return Message(
        id=msg_id,
        peer_id=PeerChannel(1),
        date=DATE,
        message=f"m{msg_id}",
        reply_to=reply_to,
    )


def test_filter_accepts_telethon_messages():
    messages = [
        _msg(2853),  # topic root, no reply header
        _msg(2900, reply_to_msg_id=2853),
        _msg(2901, reply_to_msg_id=2900, reply_to_top_id=2853),
        _msg(2902, reply_to_msg_id=10),
        _msg(2903),
    ]
    filtered = filter_messages_by_subchat(messages, "https://t.me/c/2419773158/2853")
    assert [m.id for m in filtered] == [2853, 2900, 2901]


def test_filter_accepts_mixed_dicts_and_messages():
    # download_chat returns partial-file dicts next to live Message objects.
    messages = [
        {"id": 2853, "reply_to": None},
        {"id": 2950, "reply_to": {"reply_to_msg_id": 2853}},
        {"id": 2951, "reply_to": {"reply_to_msg_id": 7}},
        _msg(3000, reply_to_msg_id=2950, reply_to_top_id=2853),
    ]
    filtered = filter_messages_by_subchat(messages, "2853")
    ids = [m["id"] if isinstance(m, dict) else m.id for m in filtered]
    assert ids == [2853, 2950, 3000]


def _make_download_mixin(entity):
    d = DownloadMixin.__new__(DownloadMixin)
    d.logger = MagicMock()
    d._stop_requested = False
    d._stop_file = None
    d._current_entity = None
    d.get_entity = AsyncMock(return_value=entity)
    return d


@pytest.mark.asyncio
async def test_download_chat_reply_to_uses_replies_and_adds_root():
    entity = MagicMock(name="forum")
    d = _make_download_mixin(entity)

    requests = []
    pages = [
        [_msg(2901, 2900, 2853), _msg(2900, 2853)],
        [],
    ]

    async def client_call(request):
        requests.append(request)
        history = MagicMock()
        history.messages = pages.pop(0)
        return history

    client = MagicMock(side_effect=client_call)
    client.get_messages = AsyncMock(return_value=_msg(2853))
    d.client = client

    result = await d.download_chat(
        "forum", save_partial=False, silent=True, reply_to=2853
    )

    assert all(isinstance(r, GetRepliesRequest) for r in requests)
    assert requests[0].msg_id == 2853
    client.get_messages.assert_awaited_once_with(entity, ids=2853)
    assert sorted(m.id for m in result) == [2853, 2900, 2901]


@pytest.mark.asyncio
async def test_download_chat_reply_to_skips_root_outside_window():
    entity = MagicMock(name="forum")
    d = _make_download_mixin(entity)

    old_root = _msg(2853)
    old_root.date = datetime(2020, 1, 1, tzinfo=timezone.utc)

    async def client_call(request):
        history = MagicMock()
        history.messages = []
        return history

    client = MagicMock(side_effect=client_call)
    client.get_messages = AsyncMock(return_value=old_root)
    d.client = client

    result = await d.download_chat(
        "forum",
        save_partial=False,
        silent=True,
        reply_to=2853,
        until_date="2026-01-01",
    )
    assert result == []


@pytest.mark.asyncio
async def test_download_chat_default_uses_history():
    d = _make_download_mixin(MagicMock())
    requests = []

    async def client_call(request):
        requests.append(request)
        history = MagicMock()
        history.messages = []
        return history

    d.client = MagicMock(side_effect=client_call)
    await d.download_chat("chat", save_partial=False, silent=True)
    assert isinstance(requests[0], GetHistoryRequest)

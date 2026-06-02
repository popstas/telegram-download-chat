"""Tests for fetching cited/replied messages outside the date window (Task 2)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from telegram_download_chat.core.citations import (
    collect_missing_cited_ids,
    fetch_cited_messages,
)


class _FakeMessage:
    def __init__(self, msg_id):
        self.id = msg_id

    def to_dict(self):
        return {"_": "Message", "id": self.id, "message": f"cited {self.id}"}


def _make_downloader(messages_by_id):
    """Fake downloader whose client.get_messages resolves ids from a map."""
    calls = []

    class _Client:
        async def get_messages(self, entity, ids=None):
            calls.append(list(ids))
            return [messages_by_id.get(i) for i in ids]

    downloader = SimpleNamespace()
    downloader.client = _Client()
    downloader.logger = MagicMock()
    downloader._calls = calls
    return downloader


def test_collect_missing_cited_ids_finds_dangling_reference():
    messages = [
        {"id": 10, "message": "reply", "reply_to": {"reply_to_msg_id": 5}},
        {"id": 11, "message": "another", "reply_to_msg_id": 6},
    ]
    # Neither 5 nor 6 are present in the list.
    assert collect_missing_cited_ids(messages) == [6, 5]


def test_collect_missing_cited_ids_ignores_present_targets():
    messages = [
        {"id": 5, "message": "original"},
        {"id": 10, "message": "reply", "reply_to": {"reply_to_msg_id": 5}},
    ]
    assert collect_missing_cited_ids(messages) == []


def test_collect_missing_cited_ids_skips_comments():
    # A comment's reply_to lives in the discussion id space; never fetch it from
    # the channel entity.
    messages = [
        {"id": 1, "message": "post"},
        {
            "id": 1001,
            "comment_of": 1,
            "message": "comment replying within discussion",
            "reply_to": {"reply_to_msg_id": 999},
        },
    ]
    assert collect_missing_cited_ids(messages) == []


def test_collect_missing_cited_ids_dedups_repeated_references():
    messages = [
        {"id": 10, "reply_to_msg_id": 5},
        {"id": 11, "reply_to_msg_id": 5},
    ]
    assert collect_missing_cited_ids(messages) == [5]


@pytest.mark.asyncio
async def test_fetch_cited_messages_returns_fetched_objects():
    downloader = _make_downloader({5: _FakeMessage(5), 6: _FakeMessage(6)})
    messages = [
        {"id": 10, "reply_to": {"reply_to_msg_id": 5}},
        {"id": 11, "reply_to_msg_id": 6},
    ]
    fetched = await fetch_cited_messages(downloader, SimpleNamespace(id=1), messages)
    assert sorted(m.id for m in fetched) == [5, 6]
    assert downloader._calls == [[6, 5]]


@pytest.mark.asyncio
async def test_fetch_cited_messages_filters_unresolved():
    # id 6 cannot be resolved (returns None) and is dropped.
    downloader = _make_downloader({5: _FakeMessage(5), 6: None})
    messages = [
        {"id": 10, "reply_to_msg_id": 5},
        {"id": 11, "reply_to_msg_id": 6},
    ]
    fetched = await fetch_cited_messages(downloader, SimpleNamespace(id=1), messages)
    assert [m.id for m in fetched] == [5]


@pytest.mark.asyncio
async def test_fetch_cited_messages_noop_when_nothing_missing():
    downloader = _make_downloader({})
    messages = [
        {"id": 5, "message": "original"},
        {"id": 10, "reply_to_msg_id": 5},
    ]
    fetched = await fetch_cited_messages(downloader, SimpleNamespace(id=1), messages)
    assert fetched == []
    assert downloader._calls == []


@pytest.mark.asyncio
async def test_cited_marker_survives_serialization(tmp_path):
    """An outside-window citation stamped on a Telethon-like object keeps its
    ``cited_outside_window`` marker in the saved JSON.

    Telethon's ``to_dict()`` drops attributes outside the TL schema, so
    ``save_messages`` must re-stamp the marker. Without it, a resumed ``--limit``
    run could not tell a backfilled citation from a downloaded chat post and
    would over-count toward the limit, stopping real backfill.
    """
    import json
    from unittest.mock import MagicMock

    from telegram_download_chat.core import TelegramChatDownloader

    class _Cited:
        def __init__(self, mid):
            self.id = mid
            self.cited_outside_window = True

        def to_dict(self):
            # Mirrors Telethon: the custom attribute is NOT included here.
            return {"_": "Message", "id": self.id, "message": f"cited {self.id}"}

    out = tmp_path / "messages.json"
    downloader = TelegramChatDownloader()
    downloader.logger = MagicMock()
    await downloader.save_messages([_Cited(7)], str(out), save_txt=False)

    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved[0]["id"] == 7
    assert saved[0]["cited_outside_window"] is True


@pytest.mark.asyncio
async def test_fetch_cited_messages_chunks_large_id_sets(monkeypatch):
    import telegram_download_chat.core.citations as citations

    monkeypatch.setattr(citations, "_CHUNK_SIZE", 2)
    by_id = {i: _FakeMessage(i) for i in range(1, 6)}
    downloader = _make_downloader(by_id)
    # Five distinct missing reply targets -> chunked into 2 + 2 + 1.
    messages = [{"id": 100 + i, "reply_to_msg_id": i} for i in range(1, 6)]
    fetched = await citations.fetch_cited_messages(
        downloader, SimpleNamespace(id=1), messages
    )
    assert sorted(m.id for m in fetched) == [1, 2, 3, 4, 5]
    assert [len(c) for c in downloader._calls] == [2, 2, 1]

"""Tests for core/comments.py — linked group resolution and per-post fetch."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from telethon.errors import FloodWaitError, MsgIdInvalidError

from telegram_download_chat.core.comments import (
    download_post_comments,
    get_linked_discussion,
    map_discussion_to_comments,
)

DISCUSSION_FIXTURE = Path(__file__).parent / "fixtures" / "discussion_messages.json"


class FakeMessage:
    """Minimal stand-in for a Telethon message with to_dict()."""

    def __init__(self, msg_id: int, reply_to=None, reactions=None):
        self.id = msg_id
        self._reply_to = reply_to
        self._reactions = reactions

    def to_dict(self):
        data = {"_": "Message", "id": self.id, "message": f"comment {self.id}"}
        if self._reply_to is not None:
            data["reply_to"] = self._reply_to
        if self._reactions is not None:
            data["reactions"] = self._reactions
        return data


def _reactions(*pairs):
    """Build a raw ``MessageReactions`` dict from (emoji, count) pairs."""
    return {
        "_": "MessageReactions",
        "results": [
            {
                "_": "ReactionCount",
                "reaction": {"_": "ReactionEmoji", "emoticon": emoji},
                "count": count,
            }
            for emoji, count in pairs
        ],
    }


class _AsyncIter:
    """Wrap a list of items (or an exception) into an async iterator."""

    def __init__(self, items=None, raises=None):
        self._items = list(items or [])
        self._raises = raises

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._raises is not None:
            raise self._raises
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def _make_downloader(iter_factory):
    """Build a fake downloader whose client.iter_messages uses iter_factory."""
    client = MagicMock()
    client.iter_messages = MagicMock(side_effect=iter_factory)

    downloader = SimpleNamespace()
    downloader.client = client
    downloader.logger = MagicMock()
    downloader._stop_requested = False
    downloader._progress_sink = None
    # Mirror messages.MessagesMixin.make_serializable behavior.
    downloader.make_serializable = _make_serializable
    return downloader


def _make_serializable(obj):
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(x) for x in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)


@pytest.mark.asyncio
async def test_parent_id_normalization():
    post_id = 500

    def factory(entity, reply_to=None):
        assert reply_to == post_id
        return _AsyncIter([FakeMessage(1001), FakeMessage(1002)])

    downloader = _make_downloader(factory)
    comments = await download_post_comments(
        downloader, object(), [post_id], silent=True
    )

    assert len(comments) == 2
    for c in comments:
        assert c["reply_to_msg_id"] == post_id
        assert c["reply_to"]["reply_to_msg_id"] == post_id
        assert c["comment_of"] == post_id
    # Native discussion ids preserved.
    assert {c["discussion_msg_id"] for c in comments} == {1001, 1002}
    assert {c["id"] for c in comments} == {1001, 1002}


@pytest.mark.asyncio
async def test_normalization_preserves_existing_reply_to_fields():
    post_id = 7

    def factory(entity, reply_to=None):
        msg = FakeMessage(42, reply_to={"_": "MessageReplyHeader", "quote_text": "q"})
        return _AsyncIter([msg])

    downloader = _make_downloader(factory)
    comments = await download_post_comments(
        downloader, object(), [post_id], silent=True
    )

    assert comments[0]["reply_to"]["quote_text"] == "q"
    assert comments[0]["reply_to"]["reply_to_msg_id"] == post_id


@pytest.mark.asyncio
async def test_limit_caps_per_post():
    def factory(entity, reply_to=None):
        return _AsyncIter([FakeMessage(i) for i in range(100)])

    downloader = _make_downloader(factory)
    comments = await download_post_comments(
        downloader, object(), [1, 2], silent=True, limit=10
    )

    # Two posts, capped at 10 each.
    assert len(comments) == 20


@pytest.mark.asyncio
async def test_min_reactions_filters_low_reaction_comments():
    def factory(entity, reply_to=None):
        return _AsyncIter(
            [
                FakeMessage(1, reactions=_reactions(("👍", 5))),  # total 5 -> keep
                FakeMessage(2, reactions=_reactions(("👍", 1), ("❤️", 1))),  # 2 -> keep
                FakeMessage(3, reactions=_reactions(("👍", 1))),  # total 1 -> drop
                FakeMessage(4),  # no reactions -> drop
            ]
        )

    downloader = _make_downloader(factory)
    comments = await download_post_comments(
        downloader, object(), [10], silent=True, min_reactions=2
    )

    assert {c["id"] for c in comments} == {1, 2}


@pytest.mark.asyncio
async def test_min_reactions_zero_keeps_all():
    def factory(entity, reply_to=None):
        return _AsyncIter(
            [FakeMessage(1, reactions=_reactions(("👍", 1))), FakeMessage(2)]
        )

    downloader = _make_downloader(factory)
    comments = await download_post_comments(
        downloader, object(), [10], silent=True, min_reactions=0
    )

    assert len(comments) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [None, 0])
async def test_limit_none_or_zero_returns_all(limit):
    def factory(entity, reply_to=None):
        return _AsyncIter([FakeMessage(i) for i in range(25)])

    downloader = _make_downloader(factory)
    comments = await download_post_comments(
        downloader, object(), [99], silent=True, limit=limit
    )

    assert len(comments) == 25


@pytest.mark.asyncio
async def test_comments_disabled_post_is_skipped():
    def factory(entity, reply_to=None):
        if reply_to == 1:
            return _AsyncIter(raises=MsgIdInvalidError(request=None))
        return _AsyncIter([FakeMessage(10), FakeMessage(11)])

    downloader = _make_downloader(factory)
    comments = await download_post_comments(downloader, object(), [1, 2], silent=True)

    # Post 1 raised MsgIdInvalidError and was skipped; post 2 yielded 2 comments.
    assert len(comments) == 2
    assert all(c["comment_of"] == 2 for c in comments)


@pytest.mark.asyncio
async def test_flood_wait_retries_without_duplicating(monkeypatch):
    sleeps = []

    async def fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr(
        "telegram_download_chat.core.comments.asyncio.sleep", fake_sleep
    )

    calls = {"n": 0}

    def factory(entity, reply_to=None):
        calls["n"] += 1
        if calls["n"] == 1:
            err = FloodWaitError(request=None)
            err.seconds = 0
            return _AsyncIter(raises=err)
        return _AsyncIter([FakeMessage(1), FakeMessage(2), FakeMessage(3)])

    downloader = _make_downloader(factory)
    comments = await download_post_comments(downloader, object(), [500], silent=True)

    # First attempt floods, the retry re-fetches from scratch: exactly 3, no dups.
    assert calls["n"] == 2
    assert len(comments) == 3
    assert sleeps  # slept once before retry


@pytest.mark.asyncio
async def test_generic_error_skips_post_and_continues():
    def factory(entity, reply_to=None):
        if reply_to == 1:
            return _AsyncIter(raises=RuntimeError("network boom"))
        return _AsyncIter([FakeMessage(10)])

    downloader = _make_downloader(factory)
    comments = await download_post_comments(downloader, object(), [1, 2], silent=False)

    # Post 1 errored generically and was skipped; post 2 still fetched.
    assert len(comments) == 1
    assert comments[0]["comment_of"] == 2
    assert downloader.logger.warning.called


@pytest.mark.asyncio
async def test_stop_check_breaks_between_posts():
    calls = {"n": 0}

    def factory(entity, reply_to=None):
        calls["n"] += 1
        return _AsyncIter([FakeMessage(1)])

    downloader = _make_downloader(factory)

    def stop_after_first():
        return calls["n"] >= 1

    comments = await download_post_comments(
        downloader, object(), [1, 2, 3], silent=True, stop_check=stop_after_first
    )

    # First post fetched (1 comment); stop_check then halts before post 2.
    assert calls["n"] == 1
    assert len(comments) == 1


@pytest.mark.asyncio
async def test_progress_events_emitted_per_post():
    events = []

    def factory(entity, reply_to=None):
        return _AsyncIter([FakeMessage(1)])

    downloader = _make_downloader(factory)
    downloader._progress_sink = events.append

    await download_post_comments(downloader, object(), [10, 20], silent=True)

    assert [e["type"] for e in events] == ["comments", "comments"]
    assert events[-1] == {
        "type": "comments",
        "posts_done": 2,
        "posts_total": 2,
        "comments": 2,
    }


@pytest.mark.asyncio
async def test_get_linked_discussion_returns_id():
    full = SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=123456))

    async def fake_client(request):
        return full

    downloader = SimpleNamespace(client=fake_client, logger=MagicMock())
    linked = await get_linked_discussion(downloader, object())
    assert linked == 123456


@pytest.mark.asyncio
async def test_get_linked_discussion_no_linked_group_returns_none():
    full = SimpleNamespace(full_chat=SimpleNamespace(linked_chat_id=None))

    async def fake_client(request):
        return full

    downloader = SimpleNamespace(client=fake_client, logger=MagicMock())
    linked = await get_linked_discussion(downloader, object())
    assert linked is None


@pytest.mark.asyncio
async def test_get_linked_discussion_swallows_errors():
    async def fake_client(request):
        raise RuntimeError("boom")

    downloader = SimpleNamespace(client=fake_client, logger=MagicMock())
    linked = await get_linked_discussion(downloader, object())
    assert linked is None


# ---------------------------------------------------------------------------
# Part B: map_discussion_to_comments (single-pass discussion -> comments)
# ---------------------------------------------------------------------------


def _load_discussion_messages():
    with open(DISCUSSION_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _mapping_downloader():
    downloader = SimpleNamespace()
    downloader.logger = MagicMock()
    downloader.make_serializable = _make_serializable
    return downloader


def test_map_discussion_direct_reply_maps_to_post():
    msgs = _load_discussion_messages()
    downloader = _mapping_downloader()

    comments, raw_media = map_discussion_to_comments(
        downloader, msgs, [5477, 5445], limit=None, min_reactions=0
    )

    by_disc = {c["discussion_msg_id"]: c for c in comments}
    # Direct replies map to their parent channel post via the forwarded root.
    assert by_disc[9240]["comment_of"] == 5477
    assert by_disc[9240]["reply_to_msg_id"] == 5477
    assert by_disc[9131]["comment_of"] == 5445
    # Forwarded roots themselves are not emitted as comments.
    assert 9230 not in by_disc
    assert 9120 not in by_disc
    # Media-bearing comments are returned as raw messages keyed by their id.
    raw_ids = {m["id"] for m in raw_media}
    assert raw_ids == {9240, 9131}


def test_map_discussion_nested_reply_maps_via_top_id():
    msgs = _load_discussion_messages()
    downloader = _mapping_downloader()

    comments, _ = map_discussion_to_comments(
        downloader, msgs, [5477, 5445], limit=None, min_reactions=0
    )

    by_disc = {c["discussion_msg_id"]: c for c in comments}
    # 9241 replies to 9240 but carries reply_to_top_id=9230 (the thread root for
    # post 5477), so it maps to 5477.
    assert by_disc[9241]["comment_of"] == 5477


def test_map_discussion_out_of_window_post_dropped():
    msgs = _load_discussion_messages()
    downloader = _mapping_downloader()

    # 9300 replies into a thread root (9299) that is not present, so it cannot
    # be mapped to an in-window post and is dropped.
    comments, _ = map_discussion_to_comments(
        downloader, msgs, [5477, 5445], limit=None, min_reactions=0
    )

    assert all(c["discussion_msg_id"] != 9300 for c in comments)


def test_map_discussion_post_not_in_window_dropped():
    msgs = _load_discussion_messages()
    downloader = _mapping_downloader()

    # Only post 5445 is in-window; comments mapping to 5477 are dropped.
    comments, raw_media = map_discussion_to_comments(
        downloader, msgs, [5445], limit=None, min_reactions=0
    )

    assert {c["discussion_msg_id"] for c in comments} == {9131}
    assert {m["id"] for m in raw_media} == {9131}


def test_map_discussion_limit_caps_per_post():
    msgs = _load_discussion_messages()
    downloader = _mapping_downloader()

    # Post 5477 has two comments (9240, 9241); limit=1 keeps only the first.
    comments, _ = map_discussion_to_comments(
        downloader, msgs, [5477, 5445], limit=1, min_reactions=0
    )

    by_post = {}
    for c in comments:
        by_post.setdefault(c["comment_of"], []).append(c["discussion_msg_id"])
    assert by_post[5477] == [9240]
    assert by_post[5445] == [9131]


def test_map_discussion_min_reactions_filters():
    msgs = _load_discussion_messages()
    downloader = _mapping_downloader()

    # 9240 has 👍4 (keep), 9241 has ❤️1 (drop), 9131 has none (drop).
    comments, raw_media = map_discussion_to_comments(
        downloader, msgs, [5477, 5445], limit=None, min_reactions=2
    )

    assert {c["discussion_msg_id"] for c in comments} == {9240}
    # The dropped comments' media is excluded from the raw media set too.
    assert {m["id"] for m in raw_media} == {9240}


def test_map_discussion_forwarded_roots_not_emitted():
    msgs = _load_discussion_messages()
    downloader = _mapping_downloader()

    comments, _ = map_discussion_to_comments(
        downloader, msgs, [5477, 5445], limit=None, min_reactions=0
    )

    disc_ids = {c["discussion_msg_id"] for c in comments}
    assert 9230 not in disc_ids
    assert 9120 not in disc_ids
    # The three in-window comments are exactly 9240, 9131, 9241.
    assert disc_ids == {9240, 9131, 9241}

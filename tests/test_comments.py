"""Tests for core/comments.py — linked group resolution and per-post fetch."""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon.errors import FloodWaitError

from telegram_download_chat.core.comments import (
    coerce_datetime,
    download_post_comments,
    fetch_discussion_messages,
    get_linked_discussion,
    map_discussion_to_comments,
)

DISCUSSION_FIXTURE = Path(__file__).parent / "fixtures" / "discussion_messages.json"


class FakeRoot:
    """Forwarded thread root: carries ``fwd_from.channel_post`` = parent post id."""

    def __init__(self, root_id: int, channel_post: int, date=None):
        self.id = root_id
        self.fwd_from = SimpleNamespace(channel_post=channel_post)
        self.reply_to = None
        self.media = None
        self.date = date

    def to_dict(self):
        return {"_": "Message", "id": self.id, "message": ""}


class FakeComment:
    """A discussion comment; ``reply_to`` is wired by :func:`_discussion`."""

    def __init__(self, msg_id: int, reactions=None, media=None, date=None):
        self.id = msg_id
        self.fwd_from = None
        self.media = media
        self.date = date
        self._reactions = reactions
        self.reply_to = None  # set when placed under a thread root

    def to_dict(self):
        data = {"_": "Message", "id": self.id, "message": f"comment {self.id}"}
        if self._reactions is not None:
            data["reactions"] = self._reactions
        return data


def _discussion(comments_by_post, *, root_base=900000):
    """Build a flat discussion list: a forwarded root per post + its replies.

    Each reply is a direct reply to its post's thread root
    (``reply_to.reply_to_msg_id == root_id``), mirroring the live structure the
    single-pass mapper consumes.
    """
    msgs = []
    for i, (post_id, replies) in enumerate(comments_by_post.items()):
        root_id = root_base + i
        msgs.append(FakeRoot(root_id, post_id))
        for r in replies:
            r.reply_to = SimpleNamespace(reply_to_msg_id=root_id, reply_to_top_id=None)
            msgs.append(r)
    return msgs


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


def _make_serializable(obj):
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(x) for x in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)


def _make_downloader(discussion_messages=None, *, iter_factory=None):
    """Build a fake downloader for the single-pass discussion download.

    ``client.iter_messages(entity)`` (no ``reply_to``) yields the whole linked
    discussion group in one pass. Pass ``discussion_messages`` for the simple
    case or ``iter_factory`` to drive flood-wait/error scenarios.
    """
    client = MagicMock()
    if iter_factory is None:
        client.iter_messages = MagicMock(
            side_effect=lambda entity: _AsyncIter(list(discussion_messages or []))
        )
    else:
        client.iter_messages = MagicMock(side_effect=iter_factory)

    downloader = SimpleNamespace()
    downloader.client = client
    downloader.logger = MagicMock()
    downloader._stop_requested = False
    downloader._progress_sink = None
    # Mirror messages.MessagesMixin.make_serializable behavior.
    downloader.make_serializable = _make_serializable

    async def get_entity(_linked_id):
        return object()

    downloader.get_entity = get_entity
    return downloader


@pytest.mark.asyncio
async def test_parent_id_normalization():
    post_id = 500
    disc = _discussion({post_id: [FakeComment(1001), FakeComment(1002)]})

    downloader = _make_downloader(disc)
    comments = await download_post_comments(downloader, 999, [post_id], silent=True)

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
    root = FakeRoot(900000, post_id)
    comment = FakeComment(42)
    comment.reply_to = SimpleNamespace(reply_to_msg_id=900000, reply_to_top_id=None)
    # The serialized message carries an extra quote field that normalization
    # must preserve while still pointing reply_to_msg_id at the channel post.
    comment.to_dict = lambda: {
        "_": "Message",
        "id": 42,
        "message": "c",
        "reply_to": {"_": "MessageReplyHeader", "quote_text": "q"},
    }

    downloader = _make_downloader([root, comment])
    comments = await download_post_comments(downloader, 999, [post_id], silent=True)

    assert comments[0]["reply_to"]["quote_text"] == "q"
    assert comments[0]["reply_to"]["reply_to_msg_id"] == post_id


@pytest.mark.asyncio
async def test_limit_caps_per_post():
    disc = _discussion(
        {
            1: [FakeComment(i) for i in range(100)],
            2: [FakeComment(1000 + i) for i in range(100)],
        }
    )

    downloader = _make_downloader(disc)
    comments = await download_post_comments(
        downloader, 999, [1, 2], silent=True, limit=10
    )

    # Two posts, capped at 10 each.
    assert len(comments) == 20


@pytest.mark.asyncio
async def test_min_reactions_filters_low_reaction_comments():
    disc = _discussion(
        {
            10: [
                FakeComment(1, reactions=_reactions(("👍", 5))),  # total 5 -> keep
                FakeComment(2, reactions=_reactions(("👍", 1), ("❤️", 1))),  # 2 -> keep
                FakeComment(3, reactions=_reactions(("👍", 1))),  # total 1 -> drop
                FakeComment(4),  # no reactions -> drop
            ]
        }
    )

    downloader = _make_downloader(disc)
    comments = await download_post_comments(
        downloader, 999, [10], silent=True, min_reactions=2
    )

    assert {c["id"] for c in comments} == {1, 2}


@pytest.mark.asyncio
async def test_min_reactions_zero_keeps_all():
    disc = _discussion(
        {10: [FakeComment(1, reactions=_reactions(("👍", 1))), FakeComment(2)]}
    )

    downloader = _make_downloader(disc)
    comments = await download_post_comments(
        downloader, 999, [10], silent=True, min_reactions=0
    )

    assert len(comments) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [None, 0])
async def test_limit_none_or_zero_returns_all(limit):
    disc = _discussion({99: [FakeComment(i) for i in range(25)]})

    downloader = _make_downloader(disc)
    comments = await download_post_comments(
        downloader, 999, [99], silent=True, limit=limit
    )

    assert len(comments) == 25


@pytest.mark.asyncio
async def test_post_with_no_replies_yields_no_comments():
    # Post 1 has a forwarded thread root but no comments; post 2 has two. The
    # single pass simply maps nothing for post 1 (no per-post request at all).
    disc = _discussion({1: [], 2: [FakeComment(10), FakeComment(11)]})

    downloader = _make_downloader(disc)
    comments = await download_post_comments(downloader, 999, [1, 2], silent=True)

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
    disc = _discussion({500: [FakeComment(1), FakeComment(2), FakeComment(3)]})

    def factory(entity):
        calls["n"] += 1
        if calls["n"] == 1:
            err = FloodWaitError(request=None)
            err.seconds = 0
            return _AsyncIter(raises=err)
        return _AsyncIter(list(disc))

    downloader = _make_downloader(iter_factory=factory)
    comments = await download_post_comments(downloader, 999, [500], silent=True)

    # First attempt floods, the retry re-pages from scratch: exactly 3, no dups.
    assert calls["n"] == 2
    assert len(comments) == 3
    assert sleeps  # slept once before retry


@pytest.mark.asyncio
async def test_generic_error_returns_empty_and_logs():
    def factory(entity):
        return _AsyncIter(raises=RuntimeError("network boom"))

    downloader = _make_downloader(iter_factory=factory)
    comments = await download_post_comments(downloader, 999, [1, 2], silent=False)

    # The discussion download failed; comment fetch is best-effort, so it logs a
    # warning and returns no comments instead of aborting the run.
    assert comments == []
    assert downloader.logger.warning.called


@pytest.mark.asyncio
async def test_stop_check_breaks_discussion_pass():
    disc = _discussion({1: [FakeComment(1), FakeComment(2), FakeComment(3)]})
    seen = {"n": 0}

    def stop_after_first():
        seen["n"] += 1
        return seen["n"] >= 2  # stop once the first message has been collected

    downloader = _make_downloader(disc)
    comments = await download_post_comments(
        downloader, 999, [1], silent=True, stop_check=stop_after_first
    )

    # The pass stopped early, so not all messages were collected.
    assert len(comments) < 3


@pytest.mark.asyncio
async def test_progress_event_emitted_once_for_the_pass():
    events = []
    disc = _discussion({10: [FakeComment(1)], 20: [FakeComment(2)]})

    downloader = _make_downloader(disc)
    downloader._progress_sink = events.append

    await download_post_comments(downloader, 999, [10, 20], silent=True)

    # A single discussion pass emits one summary event covering all posts.
    assert [e["type"] for e in events] == ["comments"]
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


@pytest.mark.asyncio
async def test_download_post_comments_single_pass_over_fixtures(tmp_path):
    """The full single-pass path (fetch_discussion_messages -> map -> media) over
    the Task B1 fixtures yields the same comments + ``attachment_path`` the old
    per-post path produced for an equivalent input."""
    msgs = _load_discussion_messages()
    downloader = _make_downloader(msgs)
    downloader.download_all_media = AsyncMock(
        return_value={
            "9240": "documents/9240_post5477.pdf",
            "9131": "documents/9131_post5445.pdf",
        }
    )
    attachments = tmp_path / "attachments"

    comments = await download_post_comments(
        downloader,
        1619992925,
        [5477, 5445],
        download_media=True,
        attachments_dir=attachments,
        silent=True,
    )

    by_disc = {c["discussion_msg_id"]: c for c in comments}
    # Direct replies map to their parent post and carry the downloaded media link.
    assert by_disc[9240]["comment_of"] == 5477
    assert by_disc[9240]["attachment_path"] == "documents/9240_post5477.pdf"
    assert by_disc[9131]["comment_of"] == 5445
    assert by_disc[9131]["attachment_path"] == "documents/9131_post5445.pdf"
    # Nested reply mapped via reply_to_top_id; out-of-window + roots excluded.
    assert by_disc[9241]["comment_of"] == 5477
    assert 9300 not in by_disc
    assert 9230 not in by_disc and 9120 not in by_disc
    # Only the two media-bearing, in-window comments were sent to media download.
    raw_arg, dir_arg = downloader.download_all_media.await_args.args
    assert {m["id"] for m in raw_arg} == {9240, 9131}
    assert dir_arg == attachments


@pytest.mark.parametrize(
    "value, expected",
    [
        # Aware datetime passes through unchanged.
        (
            datetime(2025, 5, 1, 11, 0, tzinfo=timezone.utc),
            datetime(2025, 5, 1, 11, 0, tzinfo=timezone.utc),
        ),
        # Naive datetime is assumed UTC.
        (
            datetime(2025, 5, 1, 11, 0),
            datetime(2025, 5, 1, 11, 0, tzinfo=timezone.utc),
        ),
        # The space-separated str(datetime) form Telethon serialization produces.
        (
            "2025-05-01 11:00:00+00:00",
            datetime(2025, 5, 1, 11, 0, tzinfo=timezone.utc),
        ),
        # Plain ISO-8601 string.
        (
            "2025-05-01T11:00:00+00:00",
            datetime(2025, 5, 1, 11, 0, tzinfo=timezone.utc),
        ),
        # Naive ISO string gets UTC.
        (
            "2025-05-01T11:00:00",
            datetime(2025, 5, 1, 11, 0, tzinfo=timezone.utc),
        ),
        # Unparseable / wrong-typed values yield None (date bound is optional).
        ("garbage", None),
        (None, None),
        (12345, None),
    ],
)
def test_coerce_datetime(value, expected):
    assert coerce_datetime(value) == expected


@pytest.mark.asyncio
async def test_fetch_discussion_messages_stops_below_min_date():
    """The single date-bounded pass stops once a message older than ``min_date``
    is reached (newest-first), excluding it and everything after it."""
    floor = datetime(2025, 5, 1, 12, 0, tzinfo=timezone.utc)
    # iter_messages yields newest-first.
    newer = FakeComment(3, date="2025-05-01 13:00:00+00:00")
    at_floor = FakeComment(2, date="2025-05-01 12:00:00+00:00")  # not < floor -> kept
    older = FakeComment(1, date="2025-05-01 11:00:00+00:00")  # < floor -> stop
    trailing = FakeComment(0, date="2025-05-01 10:00:00+00:00")  # never reached
    downloader = _make_downloader([newer, at_floor, older, trailing])

    result = await fetch_discussion_messages(
        downloader, 123, min_date=floor, silent=True
    )

    assert [m.id for m in result] == [3, 2]

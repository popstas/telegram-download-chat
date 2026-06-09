"""Tests for resuming an interrupted ``--comments`` run (Task B4).

The per-post ``*.comments-progress.json`` checkpoint was retired once comments
moved to a single date-bounded download of the linked discussion group. Resume
is now handled by the standard output-merge path: a restart simply re-downloads
the discussion group, re-maps it onto the in-window posts, and the
``(comment_of, id)`` dedup (:func:`_dedup_messages`) keeps the merged output
free of duplicates. No sidecar file is required for correctness.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import telegram_download_chat.core.comments as comments_mod
from telegram_download_chat.cli.commands import _dedup_messages, fetch_channel_comments
from telegram_download_chat.core.comments import download_post_comments


class _AsyncIter:
    def __init__(self, items=None):
        self._items = list(items or [])

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class _FakeRoot:
    """Forwarded thread root carrying ``fwd_from.channel_post`` = parent post id."""

    def __init__(self, root_id, channel_post):
        self.id = root_id
        self.fwd_from = SimpleNamespace(channel_post=channel_post)
        self.reply_to = None
        self.media = None

    def to_dict(self):
        return {"_": "Message", "id": self.id, "message": ""}


class _FakeComment:
    def __init__(self, msg_id):
        self.id = msg_id
        self.fwd_from = None
        self.media = None
        self.reply_to = None  # wired by _discussion_from_posts

    def to_dict(self):
        return {"_": "Message", "id": self.id, "message": f"comment {self.id}"}


def _discussion_from_posts(comments_by_post, *, root_base=900000):
    """Synthesize a flat discussion list (forwarded roots + direct replies)."""
    msgs = []
    for i, (post_id, comments) in enumerate(comments_by_post.items()):
        root_id = root_base + i
        msgs.append(_FakeRoot(root_id, post_id))
        for c in comments:
            c.reply_to = SimpleNamespace(reply_to_msg_id=root_id, reply_to_top_id=None)
            msgs.append(c)
    return msgs


def _make_serializable(obj):
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(x) for x in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)


def _make_downloader(comments_by_post, *, broadcast=True, linked_chat_id=999):
    entity = SimpleNamespace(id=42, broadcast=broadcast)
    discussion = _discussion_from_posts(comments_by_post)
    calls = {"iter": 0}

    class _Client:
        async def __call__(self, request):
            return SimpleNamespace(
                full_chat=SimpleNamespace(linked_chat_id=linked_chat_id)
            )

        def iter_messages(self, channel_entity):
            calls["iter"] += 1
            return _AsyncIter(list(discussion))

    downloader = SimpleNamespace(
        client=_Client(),
        logger=MagicMock(),
        _stop_requested=False,
        _progress_sink=None,
        make_serializable=_make_serializable,
    )

    async def get_entity(_chat):
        return entity

    downloader.get_entity = get_entity
    downloader._iter_calls = calls
    return downloader


def _args(**overrides):
    from telegram_download_chat.cli.arguments import parse_args

    args = parse_args(["@chan"])
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


# --- the checkpoint machinery is gone -------------------------------------


def test_checkpoint_helpers_removed():
    """The per-post checkpoint API no longer exists on ``core.comments``."""
    for name in (
        "get_comments_checkpoint_path",
        "load_comments_checkpoint",
        "save_comments_checkpoint",
        "clear_comments_checkpoint",
    ):
        assert not hasattr(comments_mod, name), f"{name} should have been removed"


def test_fetch_channel_comments_has_no_checkpoint_param():
    """``fetch_channel_comments`` no longer accepts a ``checkpoint_path``."""
    import inspect

    sig = inspect.signature(fetch_channel_comments)
    assert "checkpoint_path" not in sig.parameters


def test_persist_comments_checkpoint_removed():
    import telegram_download_chat.cli.commands as commands_mod

    assert not hasattr(commands_mod, "_persist_comments_checkpoint")


# --- resume via re-map + dedup --------------------------------------------


@pytest.mark.asyncio
async def test_resume_remaps_and_dedup_avoids_duplicates():
    """A resume re-fetches the discussion and dedup keeps the merge duplicate-free."""
    comments_by_post = {
        1: [_FakeComment(1001), _FakeComment(1002)],
        2: [_FakeComment(1003)],
    }
    posts = [{"id": 1, "message": "post 1"}, {"id": 2, "message": "post 2"}]
    args = _args(comments=True)

    # First run: fetch + persist (simulated saved messages.json).
    first = await fetch_channel_comments(
        _make_downloader(comments_by_post), "@chan", posts, args
    )
    assert {c["comment_of"] for c in first} == {1, 2}
    saved = posts + first

    # Resume run: re-fetch the same discussion group (fresh downloader so its
    # iter counter starts clean) and re-map onto the same posts.
    second = await fetch_channel_comments(
        _make_downloader(comments_by_post), "@chan", saved, args
    )
    assert {(c["comment_of"], c["id"]) for c in second} == {
        (c["comment_of"], c["id"]) for c in first
    }

    # Merging the resumed comments into the already-saved output must not
    # duplicate any comment record (keyed by (comment_of, id)).
    merged = _dedup_messages(saved + second)
    comment_keys = [
        (m["comment_of"], m["id"]) for m in merged if m.get("comment_of") is not None
    ]
    assert len(comment_keys) == len(set(comment_keys)) == 3


@pytest.mark.asyncio
async def test_single_pass_no_request_per_empty_post():
    """The discussion group is downloaded exactly once regardless of post count."""
    downloader = _make_downloader({1: [_FakeComment(1001)], 5: []})
    # Many in-window posts, most with no comments — the old path issued one
    # request per post; the new path issues exactly one discussion download.
    posts = [{"id": i, "message": f"post {i}"} for i in range(1, 20)]
    args = _args(comments=True)

    await fetch_channel_comments(downloader, "@chan", posts, args)

    assert downloader._iter_calls["iter"] == 1


# --- stop mid-download returns partial; resume recovers the rest ----------


@pytest.mark.asyncio
async def test_stop_mid_download_returns_partial_then_resume_recovers():
    comments_by_post = {1: [_FakeComment(1001)], 2: [_FakeComment(1002)]}
    posts = [{"id": 1, "message": "post 1"}, {"id": 2, "message": "post 2"}]
    args = _args(comments=True)

    # Stopped run: flip the stop flag before the discussion download yields, so
    # the pass returns an empty/partial result without error.
    stopped = _make_downloader(comments_by_post)
    stopped._stop_requested = True
    partial = await fetch_channel_comments(stopped, "@chan", posts, args)
    assert partial == []  # nothing collected once stopped immediately

    # Resume run (not stopped): re-downloads the full discussion and maps it.
    resumed = _make_downloader(comments_by_post)
    recovered = await fetch_channel_comments(resumed, "@chan", posts, args)
    assert {c["comment_of"] for c in recovered} == {1, 2}


@pytest.mark.asyncio
async def test_download_post_comments_single_pass_signature():
    """``download_post_comments`` takes the single-pass shape (no ``on_post_done``)."""
    import inspect

    sig = inspect.signature(download_post_comments)
    assert "on_post_done" not in sig.parameters
    assert "linked_id" in sig.parameters
    assert "min_date" in sig.parameters

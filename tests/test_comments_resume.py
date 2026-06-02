"""Tests for resumable channel-comment fetching (Task 5).

Restarting an interrupted ``--comments`` run must skip posts whose comments were
already fetched, via a sidecar checkpoint file that mirrors the partial-download
file lifecycle.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from telegram_download_chat.cli.arguments import parse_args
from telegram_download_chat.cli.commands import fetch_channel_comments
from telegram_download_chat.core.comments import (
    clear_comments_checkpoint,
    download_post_comments,
    get_comments_checkpoint_path,
    load_comments_checkpoint,
    save_comments_checkpoint,
)


class _AsyncIter:
    def __init__(self, items=None):
        self._items = list(items or [])

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class _FakeComment:
    def __init__(self, msg_id):
        self.id = msg_id
        self.media = None

    def to_dict(self):
        return {"_": "Message", "id": self.id, "message": f"comment {self.id}"}


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
    seen = []

    class _Client:
        async def __call__(self, request):
            return SimpleNamespace(
                full_chat=SimpleNamespace(linked_chat_id=linked_chat_id)
            )

        def iter_messages(self, channel_entity, reply_to=None):
            seen.append(reply_to)
            value = comments_by_post.get(reply_to, [])
            if isinstance(value, Exception):
                raise value
            return _AsyncIter(value)

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
    downloader._seen_reply_to = seen
    return downloader


def _args(**overrides):
    args = parse_args(["@chan"])
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


# --- checkpoint file primitives -------------------------------------------


def test_checkpoint_roundtrip(tmp_path):
    path = get_comments_checkpoint_path(tmp_path / "messages.json")
    assert path.name == "messages.comments-progress.json"

    assert load_comments_checkpoint(path) == set()

    save_comments_checkpoint(path, [3, 1, 2])
    assert load_comments_checkpoint(path) == {1, 2, 3}

    clear_comments_checkpoint(path)
    assert not path.exists()
    # Clearing a missing file is a no-op.
    clear_comments_checkpoint(path)


def test_load_checkpoint_ignores_garbage(tmp_path):
    path = tmp_path / "messages.comments-progress.json"
    path.write_text("not json", encoding="utf-8")
    assert load_comments_checkpoint(path) == set()


# --- download_post_comments callback --------------------------------------


@pytest.mark.asyncio
async def test_on_post_done_fires_for_scanned_posts():
    done = []
    downloader = _make_downloader(
        {1: [_FakeComment(1001)], 2: []},  # post 2 scanned, no comments
    )
    await download_post_comments(
        downloader,
        SimpleNamespace(),
        [1, 2],
        on_post_done=done.append,
    )
    # Both posts scanned (post 2 has zero comments but is still done).
    assert done == [1, 2]


@pytest.mark.asyncio
async def test_on_post_done_skips_transient_failure():
    done = []
    downloader = _make_downloader(
        {1: [_FakeComment(1001)], 2: RuntimeError("boom")},
    )
    await download_post_comments(
        downloader,
        SimpleNamespace(),
        [1, 2],
        on_post_done=done.append,
    )
    # Post 2 failed transiently -> not checkpointed so a restart retries it.
    assert done == [1]


# --- fetch_channel_comments resume integration ----------------------------


@pytest.mark.asyncio
async def test_restart_skips_already_fetched_posts(tmp_path):
    checkpoint = get_comments_checkpoint_path(tmp_path / "messages.json")
    # Post 1 was fetched in a prior interrupted run.
    save_comments_checkpoint(checkpoint, [1])

    downloader = _make_downloader(
        {1: [_FakeComment(1001)], 2: [_FakeComment(1002)]},
    )
    posts = [{"id": 1, "message": "post 1"}, {"id": 2, "message": "post 2"}]
    args = _args(comments=True)

    comments = await fetch_channel_comments(
        downloader, "@chan", posts, args, checkpoint_path=checkpoint
    )

    # Only post 2 is queried; post 1 is skipped from the checkpoint.
    assert downloader._seen_reply_to == [2]
    assert [c["comment_of"] for c in comments] == [2]


@pytest.mark.asyncio
async def test_checkpoint_cleared_on_completion(tmp_path):
    checkpoint = get_comments_checkpoint_path(tmp_path / "messages.json")
    downloader = _make_downloader({1: [_FakeComment(1001)]})
    posts = [{"id": 1, "message": "post 1"}]
    args = _args(comments=True)

    await fetch_channel_comments(
        downloader, "@chan", posts, args, checkpoint_path=checkpoint
    )

    # A fully-completed fetch leaves no checkpoint behind.
    assert not checkpoint.exists()


@pytest.mark.asyncio
async def test_checkpoint_kept_when_stopped(tmp_path):
    checkpoint = get_comments_checkpoint_path(tmp_path / "messages.json")

    downloader = _make_downloader({1: [_FakeComment(1001)], 2: [_FakeComment(1002)]})

    # Flip the stop flag once post 1 has been scanned, so post 2 is skipped and
    # the partial checkpoint (just post 1) must be preserved for the next run.
    orig_iter = downloader.client.iter_messages

    def iter_messages(channel_entity, reply_to=None):
        it = orig_iter(channel_entity, reply_to=reply_to)
        if reply_to == 1:
            downloader._stop_requested = True
        return it

    downloader.client.iter_messages = iter_messages

    posts = [{"id": 1, "message": "post 1"}, {"id": 2, "message": "post 2"}]
    args = _args(comments=True)

    await fetch_channel_comments(
        downloader, "@chan", posts, args, checkpoint_path=checkpoint
    )

    # Post 2 was never queried (stopped); the checkpoint persists with post 1.
    assert downloader._seen_reply_to == [1]
    assert checkpoint.exists()
    assert load_comments_checkpoint(checkpoint) == {1}


@pytest.mark.asyncio
async def test_progressive_checkpoint_written_per_post(tmp_path):
    checkpoint = get_comments_checkpoint_path(tmp_path / "messages.json")
    downloader = _make_downloader({1: [_FakeComment(1001)], 2: [_FakeComment(1002)]})

    # Capture the on-disk checkpoint at the moment post 2 starts scanning: it
    # must already contain post 1, which proves the checkpoint is persisted
    # after each post rather than once at the end of the run.
    checkpoint_at_post2 = {}
    orig_iter = downloader.client.iter_messages

    def iter_messages(channel_entity, reply_to=None):
        if reply_to == 2:
            checkpoint_at_post2["state"] = load_comments_checkpoint(checkpoint)
        return orig_iter(channel_entity, reply_to=reply_to)

    downloader.client.iter_messages = iter_messages

    posts = [{"id": 1, "message": "post 1"}, {"id": 2, "message": "post 2"}]
    args = _args(comments=True)

    await fetch_channel_comments(
        downloader, "@chan", posts, args, checkpoint_path=checkpoint
    )

    # Post 1 was checkpointed before post 2 was queried (progressive write).
    assert checkpoint_at_post2.get("state") == {1}
    assert downloader._seen_reply_to == [1, 2]
    # A clean completion still clears the checkpoint at the end.
    assert not checkpoint.exists()

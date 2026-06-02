"""Integration tests for wiring --comments into the download flow (Task 2)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from telegram_download_chat.cli.arguments import parse_args
from telegram_download_chat.cli.commands import fetch_channel_comments
from telegram_download_chat.core.render import RenderMixin


class _AsyncIter:
    """Wrap a list of items into an async iterator."""

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


def _make_downloader(*, broadcast, linked_chat_id, comments_by_post):
    """Build a fake downloader exposing get_entity + client for comment fetch."""
    entity = SimpleNamespace(id=42, broadcast=broadcast)

    class _Client:
        async def __call__(self, request):
            return SimpleNamespace(
                full_chat=SimpleNamespace(linked_chat_id=linked_chat_id)
            )

        def iter_messages(self, channel_entity, reply_to=None):
            return _AsyncIter(comments_by_post.get(reply_to, []))

    downloader = SimpleNamespace()
    downloader.client = _Client()
    downloader.logger = MagicMock()
    downloader._stop_requested = False
    downloader._progress_sink = None
    downloader.make_serializable = _make_serializable

    async def get_entity(_chat):
        return entity

    downloader.get_entity = get_entity
    return downloader


def _args(**overrides):
    argv = overrides.pop("argv", ["@chan"])
    args = parse_args(argv)
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


@pytest.mark.asyncio
async def test_comments_flag_defaults_off():
    args = _args()
    assert args.comments is False
    assert args.comments_limit is None


@pytest.mark.asyncio
async def test_comments_flag_and_limit_parse():
    args = parse_args(["@chan", "--comments", "--comments-limit", "50"])
    assert args.comments is True
    assert args.comments_limit == 50


@pytest.mark.asyncio
async def test_fetch_channel_comments_appends_normalized():
    downloader = _make_downloader(
        broadcast=True,
        linked_chat_id=999,
        comments_by_post={
            1: [_FakeComment(1001), _FakeComment(1002)],
            2: [_FakeComment(1003)],
        },
    )
    posts = [{"id": 1, "message": "post 1"}, {"id": 2, "message": "post 2"}]
    args = _args(comments=True)

    comments = await fetch_channel_comments(downloader, "@chan", posts, args)

    assert len(comments) == 3
    assert {c["comment_of"] for c in comments} == {1, 2}
    for c in comments:
        assert c["reply_to_msg_id"] == c["comment_of"]
        assert c["reply_to"]["reply_to_msg_id"] == c["comment_of"]


@pytest.mark.asyncio
async def test_fetch_channel_comments_limit_forwarded():
    downloader = _make_downloader(
        broadcast=True,
        linked_chat_id=999,
        comments_by_post={1: [_FakeComment(i) for i in range(100)]},
    )
    posts = [{"id": 1, "message": "post 1"}]
    args = _args(comments=True, comments_limit=10)

    comments = await fetch_channel_comments(downloader, "@chan", posts, args)

    assert len(comments) == 10


@pytest.mark.asyncio
async def test_fetch_channel_comments_no_linked_group():
    downloader = _make_downloader(
        broadcast=True, linked_chat_id=None, comments_by_post={}
    )
    posts = [{"id": 1, "message": "post 1"}]
    args = _args(comments=True)

    comments = await fetch_channel_comments(downloader, "@chan", posts, args)

    assert comments == []


@pytest.mark.asyncio
async def test_fetch_channel_comments_non_broadcast():
    downloader = _make_downloader(
        broadcast=False, linked_chat_id=999, comments_by_post={1: [_FakeComment(5)]}
    )
    posts = [{"id": 1, "message": "post 1"}]
    args = _args(comments=True)

    comments = await fetch_channel_comments(downloader, "@chan", posts, args)

    assert comments == []


@pytest.mark.asyncio
async def test_fetch_channel_comments_disabled_when_flag_off():
    downloader = _make_downloader(
        broadcast=True, linked_chat_id=999, comments_by_post={1: [_FakeComment(5)]}
    )
    posts = [{"id": 1, "message": "post 1"}]
    args = _args(comments=False)

    comments = await fetch_channel_comments(downloader, "@chan", posts, args)

    assert comments == []


@pytest.mark.asyncio
async def test_combined_list_renders_comment_nested_under_post(tmp_path):
    """Posts + normalized comments thread through HTML so each comment
    anchors to its parent post bubble."""
    downloader = _make_downloader(
        broadcast=True,
        linked_chat_id=999,
        comments_by_post={1: [_FakeComment(1001)]},
    )
    posts = [
        {
            "id": 1,
            "date": "2026-01-01T10:00:00+00:00",
            "from_id": {"channel_id": 42},
            "user_display_name": "Channel",
            "message": "Original post",
        }
    ]
    args = _args(comments=True)

    comments = await fetch_channel_comments(downloader, "@chan", posts, args)
    combined = posts + comments

    # Give the comment a date/sender so it renders as a bubble.
    combined[1]["date"] = "2026-01-01T10:05:00+00:00"
    combined[1]["from_id"] = {"user_id": 7}
    combined[1]["user_display_name"] = "Commenter"

    out = tmp_path / "out.html"
    RenderMixin().render_html(combined, out, chat_title="t")
    html = out.read_text(encoding="utf-8")

    # The comment cites/anchors to the parent post bubble.
    assert 'id="msg-1"' in html
    assert 'href="#msg-1"' in html

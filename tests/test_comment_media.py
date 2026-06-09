"""Tests for comment media download + HTML rendering (Task 4).

Comment messages must participate in ``--media`` download and HTML media
rendering the same way regular/post messages do: their attachments are
downloaded and each comment's normalized dict gets an ``attachment_path`` so the
saved JSON keeps it and the HTML export renders it inline.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from telegram_download_chat.cli.commands import _dedup_messages
from telegram_download_chat.core.comments import download_post_comments
from telegram_download_chat.core.render import RenderMixin


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
    """Telethon-message stand-in; ``media`` truthy marks a downloadable file."""

    def __init__(self, msg_id, media=None, reactions=None):
        self.id = msg_id
        self.media = media
        self._reactions = reactions

    def to_dict(self):
        data = {"_": "Message", "id": self.id, "message": f"comment {self.id}"}
        if self._reactions is not None:
            data["reactions"] = self._reactions
        return data


def _reactions(count):
    return {
        "_": "MessageReactions",
        "results": [
            {
                "_": "ReactionCount",
                "reaction": {"_": "ReactionEmoji", "emoticon": "👍"},
                "count": count,
            }
        ],
    }


def _make_serializable(obj):
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(x) for x in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)


def _make_downloader(comments_by_post, download_results=None):
    client = MagicMock()
    client.iter_messages = MagicMock(
        side_effect=lambda entity, reply_to=None: _AsyncIter(
            comments_by_post.get(reply_to, [])
        )
    )
    downloader = SimpleNamespace()
    downloader.client = client
    downloader.logger = MagicMock()
    downloader._stop_requested = False
    downloader._progress_sink = None
    downloader.make_serializable = _make_serializable
    downloader.download_all_media = AsyncMock(return_value=download_results or {})
    return downloader


@pytest.mark.asyncio
async def test_comment_media_downloaded_and_stamped(tmp_path):
    """A comment carrying media is downloaded and gets an attachment_path."""
    downloader = _make_downloader(
        comments_by_post={5: [_FakeComment(1001, media=object()), _FakeComment(1002)]},
        download_results={"1001": "images/1001_pic.jpg"},
    )
    attachments = tmp_path / "attachments"

    comments = await download_post_comments(
        downloader,
        object(),
        [5],
        silent=True,
        download_media=True,
        attachments_dir=attachments,
    )

    # download_all_media is called only with the raw comment that has media.
    downloader.download_all_media.assert_awaited_once()
    raw_arg, dir_arg = downloader.download_all_media.await_args.args
    assert [m.id for m in raw_arg] == [1001]
    assert dir_arg == attachments

    by_id = {c["id"]: c for c in comments}
    assert by_id[1001]["attachment_path"] == "images/1001_pic.jpg"
    assert "attachment_path" not in by_id[1002]


@pytest.mark.asyncio
async def test_min_reactions_excludes_dropped_comment_media(tmp_path):
    """A media comment below min_reactions is dropped before its media downloads."""
    downloader = _make_downloader(
        comments_by_post={
            5: [
                _FakeComment(1001, media=object(), reactions=_reactions(5)),  # keep
                _FakeComment(1002, media=object(), reactions=_reactions(1)),  # drop
            ]
        },
        download_results={"1001": "images/1001_pic.jpg"},
    )
    attachments = tmp_path / "attachments"

    comments = await download_post_comments(
        downloader,
        object(),
        [5],
        silent=True,
        min_reactions=3,
        download_media=True,
        attachments_dir=attachments,
    )

    assert {c["id"] for c in comments} == {1001}
    # Only the kept comment's raw media is handed to download_all_media.
    downloader.download_all_media.assert_awaited_once()
    raw_arg, _ = downloader.download_all_media.await_args.args
    assert [m.id for m in raw_arg] == [1001]


@pytest.mark.asyncio
async def test_no_media_download_when_flag_off():
    """Without download_media, comment media is never fetched."""
    downloader = _make_downloader(
        comments_by_post={5: [_FakeComment(1001, media=object())]},
    )

    comments = await download_post_comments(
        downloader, object(), [5], silent=True, download_media=False
    )

    downloader.download_all_media.assert_not_awaited()
    assert "attachment_path" not in comments[0]


@pytest.mark.asyncio
async def test_no_media_download_without_attachments_dir():
    """download_media=True but no attachments_dir is a no-op for media."""
    downloader = _make_downloader(
        comments_by_post={5: [_FakeComment(1001, media=object())]},
    )

    comments = await download_post_comments(
        downloader,
        object(),
        [5],
        silent=True,
        download_media=True,
        attachments_dir=None,
    )

    downloader.download_all_media.assert_not_awaited()
    assert "attachment_path" not in comments[0]


@pytest.mark.asyncio
async def test_no_media_download_when_no_comment_has_media():
    """All comments are text-only: no download pass is attempted."""
    downloader = _make_downloader(
        comments_by_post={5: [_FakeComment(1001), _FakeComment(1002)]},
    )

    await download_post_comments(
        downloader,
        object(),
        [5],
        silent=True,
        download_media=True,
        attachments_dir=Path("/tmp/x"),
    )

    downloader.download_all_media.assert_not_awaited()


@pytest.mark.asyncio
async def test_comment_media_download_failure_is_swallowed(tmp_path):
    """A failing media download must not abort comment fetching."""
    downloader = _make_downloader(
        comments_by_post={5: [_FakeComment(1001, media=object())]},
    )
    downloader.download_all_media = AsyncMock(side_effect=RuntimeError("boom"))

    comments = await download_post_comments(
        downloader,
        object(),
        [5],
        silent=True,
        download_media=True,
        attachments_dir=tmp_path,
    )

    assert len(comments) == 1
    assert "attachment_path" not in comments[0]


@pytest.mark.asyncio
async def test_post_media_reconciliation_ignores_comment_id_collision(tmp_path):
    """A comment whose native discussion id collides with a post id must neither
    shield the failed post from reconciliation nor be touched by it.

    Comment ids and channel-post ids live in separate id spaces and can be equal
    (both small integers). The post-media reconciliation must namespace comments
    out, otherwise a same-numbered comment would keep a failed post's dangling
    attachment_path alive.
    """
    import json

    from telegram_download_chat.core import TelegramChatDownloader

    out = tmp_path / "messages.json"
    attachments = out.parent / "attachments"
    # The comment's attachment already exists on disk (downloaded earlier).
    (attachments / "images").mkdir(parents=True)
    (attachments / "images" / "5_c.jpg").write_bytes(b"x")

    class _Post:
        def __init__(self, mid):
            self.id = mid
            self.media = object()

        def to_dict(self):
            return {"_": "Message", "id": self.id, "message": "post"}

    comment = {
        "id": 5,  # collides with the post id below
        "comment_of": 1,
        "message": "comment",
        "attachment_path": "images/5_c.jpg",
    }
    post = _Post(5)

    downloader = TelegramChatDownloader()
    downloader.logger = MagicMock()
    downloader.get_predicted_attachment_path = MagicMock(return_value="images/5_p.jpg")
    # The post's media download fails -> absent from the results map.
    downloader.download_all_media = AsyncMock(return_value={})

    await downloader.save_messages(
        [post, comment], str(out), save_txt=False, download_media=True
    )

    saved = json.loads(out.read_text(encoding="utf-8"))
    by = {(m.get("comment_of"), m["id"]): m for m in saved}
    # Comment keeps its real (existing) attachment.
    assert by[(1, 5)]["attachment_path"] == "images/5_c.jpg"
    # Failed post download is nulled, not shielded by the comment's id.
    assert by[(None, 5)]["attachment_path"] is None


def test_html_renders_comment_media_inline(tmp_path):
    """A comment with an attachment_path renders its image in the HTML export."""
    post = {
        "id": 1,
        "date": "2026-01-01T10:00:00+00:00",
        "from_id": {"channel_id": 42},
        "user_display_name": "Channel",
        "message": "Original post",
    }
    comment = {
        "id": 1001,
        "comment_of": 1,
        "reply_to_msg_id": 1,
        "reply_to": {"reply_to_msg_id": 1},
        "date": "2026-01-01T10:05:00+00:00",
        "from_id": {"user_id": 7},
        "user_display_name": "Commenter",
        "message": "nice pic",
        "attachment_path": "images/1001_pic.jpg",
    }

    out = tmp_path / "out.html"
    RenderMixin().render_html([post, comment], out, chat_title="t")
    html = out.read_text(encoding="utf-8")

    # The comment image renders inside the collapsible comments block.
    assert 'class="comments"' in html
    assert 'class="media-img"' in html
    assert "images/1001_pic.jpg" in html


def test_resume_dedup_then_render_surfaces_comment_media_link(tmp_path):
    """End-to-end Part A: a stale comment (no attachment_path, as saved by an
    earlier run) followed by a fresh re-fetch carrying attachment_path must
    dedup to the copy WITH the path, so render.py emits the media link on resume.
    """
    post = {
        "id": 1,
        "date": "2026-01-01T10:00:00+00:00",
        "from_id": {"channel_id": 42},
        "user_display_name": "Channel",
        "message": "Original post",
    }
    stale_comment = {
        "id": 1001,
        "comment_of": 1,
        "reply_to_msg_id": 1,
        "reply_to": {"reply_to_msg_id": 1},
        "date": "2026-01-01T10:05:00+00:00",
        "from_id": {"user_id": 7},
        "user_display_name": "Commenter",
        "message": "nice pic",
    }
    fresh_comment = {**stale_comment, "attachment_path": "images/1001_pic.jpg"}

    # Resume merge order: existing (stale) first, fresh second.
    deduped = _dedup_messages([post, stale_comment, fresh_comment])
    comment_records = [m for m in deduped if m.get("comment_of") is not None]
    assert len(comment_records) == 1
    assert comment_records[0]["attachment_path"] == "images/1001_pic.jpg"

    out = tmp_path / "out.html"
    RenderMixin().render_html(deduped, out, chat_title="t")
    html = out.read_text(encoding="utf-8")

    assert 'class="comments"' in html
    assert 'class="media-img"' in html
    assert "images/1001_pic.jpg" in html

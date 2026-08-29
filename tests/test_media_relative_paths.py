"""Attachment paths stored in the export must stay relative to ``attachments/``.

Telethon returns the absolute path it wrote to, so relativizing against a
relative ``attachments_dir`` used to fail and store that absolute path, which
``render.py`` then dropped as a traversal attempt -- the media disappeared from
the export with no error anywhere.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from telegram_download_chat.core.media import MediaMixin, relative_attachment_path
from telegram_download_chat.core.render import RenderMixin


def _make_media_mixin() -> MediaMixin:
    """A minimal MediaMixin instance without running heavy __init__."""
    d = MediaMixin.__new__(MediaMixin)
    d.logger = MagicMock()
    d.client = MagicMock()
    d._stop_requested = False
    d._progress_sink = None
    d._premium_checked = True
    d._is_premium = False
    d._fast_dl_settings = (False, 1, 0)
    d.get_filename = lambda media: "x.bin"
    return d


# ---------------------------------------------------------------------------
# relative_attachment_path
# ---------------------------------------------------------------------------


class TestRelativeAttachmentPath:
    def test_absolute_download_path_against_relative_dir(self, tmp_path, monkeypatch):
        """The regression: absolute file, relative attachments dir -> relative."""
        monkeypatch.chdir(tmp_path)
        attachments = Path("chat/attachments")
        downloaded = (tmp_path / "chat/attachments/images/7_pic.jpg").resolve()

        assert relative_attachment_path(downloaded, attachments) == "images/7_pic.jpg"

    def test_absolute_download_path_against_absolute_dir(self, tmp_path):
        attachments = tmp_path / "chat" / "attachments"
        downloaded = attachments / "videos" / "9_clip.mp4"

        assert relative_attachment_path(downloaded, attachments) == "videos/9_clip.mp4"

    def test_already_relative_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        attachments = Path("chat/attachments")
        stored = attachments / "images" / "7_pic.jpg"

        once = relative_attachment_path(stored, attachments)
        twice = relative_attachment_path(attachments / once, attachments)
        assert once == "images/7_pic.jpg"
        assert twice == once

    def test_path_outside_attachments_dir_falls_back(self, tmp_path):
        attachments = tmp_path / "chat" / "attachments"
        outside = tmp_path / "elsewhere" / "pic.jpg"

        # The fallback still normalizes separators, hence as_posix() and not str().
        assert relative_attachment_path(outside, attachments) == outside.as_posix()


# ---------------------------------------------------------------------------
# download_all_media
# ---------------------------------------------------------------------------


async def test_download_all_media_stores_relative_path(tmp_path, monkeypatch):
    """The results map feeding ``attachment_path`` must never hold an absolute path."""
    monkeypatch.chdir(tmp_path)
    attachments = Path("chat/attachments")  # relative, as a relative save_path gives
    saved = (tmp_path / "chat/attachments/images/7_pic.jpg").resolve()
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"x")

    downloader = _make_media_mixin()
    downloader._detect_premium_once = AsyncMock()
    # Telethon hands back the absolute path it actually wrote to.
    downloader.download_message_media = AsyncMock(return_value=saved)

    msg = MagicMock()
    msg.id = 7
    msg.media = object()

    results = await downloader.download_all_media([msg], attachments)

    assert results == {"7": "images/7_pic.jpg"}


# ---------------------------------------------------------------------------
# Resume heals paths written by an older version
# ---------------------------------------------------------------------------


async def test_resume_rewrites_absolute_attachment_path(tmp_path):
    """A dict carrying an absolute path from an older export is re-relativized."""
    from telegram_download_chat.core import TelegramChatDownloader

    out = tmp_path / "messages.json"
    attachments = out.parent / "attachments"
    (attachments / "images").mkdir(parents=True)
    picture = attachments / "images" / "7_pic.jpg"
    picture.write_bytes(b"x")

    downloader = TelegramChatDownloader()
    downloader.logger = MagicMock()
    downloader.download_all_media = AsyncMock(return_value={})

    stale = {
        "id": 7,
        "message": "",
        "attachment_path": str(picture.resolve()),  # absolute: the old bug
    }

    await downloader.save_messages(
        [stale], str(out), save_txt=False, download_media=True
    )

    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved[0]["attachment_path"] == "images/7_pic.jpg"


def test_absolute_attachment_path_renders_nothing(tmp_path):
    """Guard on the symptom: render.py drops absolute paths, so the fix matters."""
    absolute = {
        "id": 7,
        "date": "2026-01-01T10:00:00+00:00",
        "from_id": {"user_id": 1},
        "user_display_name": "User",
        "message": "",
        "attachment_path": str((tmp_path / "attachments/images/7_pic.jpg").resolve()),
    }
    relative = dict(absolute, id=8, attachment_path="images/8_pic.jpg")

    out = tmp_path / "out.html"
    RenderMixin().render_html([absolute, relative], out, chat_title="t")
    html = out.read_text(encoding="utf-8")

    assert "7_pic.jpg" not in html  # silently dropped -- an empty bubble
    assert "images/8_pic.jpg" in html

"""Telegram marks media hidden behind a spoiler with ``media.spoiler == true``.
The HTML export must blur such images (click-to-reveal), mirroring the Telegram
web client.
"""

from pathlib import Path

from telegram_download_chat.core.render import RenderMixin


def _msg(spoiler):
    media = {"_": "MessageMediaPhoto", "photo": {"_": "Photo"}}
    if spoiler is not None:
        media["spoiler"] = spoiler
    return {
        "id": 1,
        "date": "2026-01-01T10:00:00+00:00",
        "from_id": {"user_id": 7},
        "user_display_name": "Commenter",
        "message": "Ловите спойлер",
        "attachment_path": "images/1_pic.jpg",
        "media": media,
    }


def _render(msg, tmp_path):
    out = tmp_path / "out.html"
    RenderMixin().render_html([msg], out, chat_title="t")
    return out.read_text(encoding="utf-8")


def test_spoiler_photo_is_blurred(tmp_path):
    html = _render(_msg(spoiler=True), tmp_path)
    assert "images/1_pic.jpg" in html
    # The image is wrapped in the click-to-reveal spoiler control and gets the
    # blur class. (Bare class-name checks would match the <style> block, so
    # assert on the actual element markup.)
    assert '<label class="spoiler-wrap">' in html
    assert 'class="media-img spoiler-media"' in html


def test_non_spoiler_photo_is_not_blurred(tmp_path):
    html = _render(_msg(spoiler=False), tmp_path)
    assert 'class="media-img"' in html
    assert '<label class="spoiler-wrap">' not in html
    assert "media-img spoiler-media" not in html


def test_missing_spoiler_flag_is_not_blurred(tmp_path):
    html = _render(_msg(spoiler=None), tmp_path)
    assert '<label class="spoiler-wrap">' not in html
    assert "media-img spoiler-media" not in html

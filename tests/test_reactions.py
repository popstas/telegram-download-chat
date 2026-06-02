"""Tests for message reactions normalization and HTML pill rendering (Task 6).

Reactions are normalized from Telethon's verbose ``MessageReactions`` dict into a
stable list shape stored in the saved JSON, then rendered as pills (emoji +
count) under each message in the HTML export.
"""

from telegram_download_chat.core.reactions import normalize_reactions
from telegram_download_chat.core.render import HTML_TEMPLATE, RenderMixin


def _msg_reactions(results, recent=None):
    """Build a raw Telethon ``MessageReactions``-style dict (to_dict shape)."""
    d = {"_": "MessageReactions", "results": results}
    if recent is not None:
        d["recent_reactions"] = recent
    return d


def _emoji_count(emoticon, count, chosen=False):
    rc = {
        "_": "ReactionCount",
        "reaction": {"_": "ReactionEmoji", "emoticon": emoticon},
        "count": count,
    }
    if chosen:
        rc["chosen_order"] = 0
    return rc


def _custom_count(doc_id, count):
    return {
        "_": "ReactionCount",
        "reaction": {"_": "ReactionCustomEmoji", "document_id": doc_id},
        "count": count,
    }


# ── Normalization ──────────────────────────────────────────────────────────


def test_normalize_none_and_empty():
    assert normalize_reactions(None) is None
    assert normalize_reactions({}) is None
    assert normalize_reactions({"_": "MessageReactions", "results": []}) is None


def test_normalize_standard_emoji():
    raw = _msg_reactions([_emoji_count("👍", 5), _emoji_count("❤", 2)])
    out = normalize_reactions(raw)
    assert out == [
        {"emoji": "👍", "count": 5},
        {"emoji": "❤", "count": 2},
    ]


def test_normalize_chosen_flag():
    raw = _msg_reactions([_emoji_count("🔥", 3, chosen=True)])
    out = normalize_reactions(raw)
    assert out == [{"emoji": "🔥", "count": 3, "chosen": True}]


def test_normalize_custom_emoji():
    raw = _msg_reactions([_custom_count(987654321, 4)])
    out = normalize_reactions(raw)
    assert out == [{"custom_emoji_id": 987654321, "count": 4}]


def test_normalize_recent_peers():
    raw = _msg_reactions(
        [_emoji_count("👍", 2)],
        recent=[
            {
                "_": "MessagePeerReaction",
                "reaction": {"_": "ReactionEmoji", "emoticon": "👍"},
                "peer_id": {"_": "PeerUser", "user_id": 111},
            },
            {
                "_": "MessagePeerReaction",
                "reaction": {"_": "ReactionEmoji", "emoticon": "👍"},
                "peer_id": {"_": "PeerUser", "user_id": 222},
            },
        ],
    )
    out = normalize_reactions(raw)
    assert out == [{"emoji": "👍", "count": 2, "recent": [111, 222]}]


def test_normalize_idempotent_on_list():
    """Already-normalized list (from resume) passes through unchanged."""
    already = [{"emoji": "👍", "count": 5}, {"custom_emoji_id": 7, "count": 1}]
    assert normalize_reactions(already) == already


def test_normalize_drops_garbage_list_entries():
    mixed = [{"emoji": "👍", "count": 5}, {"bogus": True}, "nope"]
    assert normalize_reactions(mixed) == [{"emoji": "👍", "count": 5}]


# ── HTML rendering ─────────────────────────────────────────────────────────


def _renderer():
    return RenderMixin()


def _message(mid, text, reactions):
    return {
        "id": mid,
        "date": "2026-01-01T10:00:00+00:00",
        "from_id": {"user_id": 42},
        "user_display_name": "Alice",
        "message": text,
        "reactions": reactions,
    }


def test_html_template_defines_reaction_css():
    assert ".reaction" in HTML_TEMPLATE
    assert ".reaction.chosen" in HTML_TEMPLATE


def test_html_renders_emoji_pills(tmp_path):
    out = tmp_path / "out.html"
    _renderer().render_html(
        [_message(1, "hi", [{"emoji": "👍", "count": 5}, {"emoji": "❤", "count": 2}])],
        out,
        chat_title="t",
    )
    html = out.read_text(encoding="utf-8")
    assert 'class="reactions"' in html
    assert "👍" in html
    assert 'class="reaction-count">5<' in html
    assert "❤" in html


def test_html_renders_chosen_pill(tmp_path):
    out = tmp_path / "out.html"
    _renderer().render_html(
        [_message(1, "hi", [{"emoji": "🔥", "count": 3, "chosen": True}])],
        out,
        chat_title="t",
    )
    html = out.read_text(encoding="utf-8")
    assert "reaction chosen" in html


def test_html_renders_custom_emoji_placeholder(tmp_path):
    out = tmp_path / "out.html"
    _renderer().render_html(
        [_message(1, "hi", [{"custom_emoji_id": 555, "count": 9}])],
        out,
        chat_title="t",
    )
    html = out.read_text(encoding="utf-8")
    assert "custom emoji 555" in html  # tooltip carries the document id
    assert 'class="reaction-count">9<' in html


def test_html_no_reactions_no_block(tmp_path):
    out = tmp_path / "out.html"
    _renderer().render_html(
        [_message(1, "hi", None)],
        out,
        chat_title="t",
    )
    html = out.read_text(encoding="utf-8")
    assert 'class="reactions"' not in html


def test_html_renders_raw_telethon_reactions(tmp_path):
    """render_html called on raw (un-normalized) JSON still produces pills."""
    out = tmp_path / "out.html"
    raw = _msg_reactions([_emoji_count("👍", 7)])
    _renderer().render_html(
        [_message(1, "hi", raw)],
        out,
        chat_title="t",
    )
    html = out.read_text(encoding="utf-8")
    assert "👍" in html
    assert 'class="reaction-count">7<' in html


# ── Capture path (save_messages normalizes raw reactions in the JSON) ───────


import json
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_save_messages_normalizes_reactions(tmp_path):
    """save_messages stores the normalized reactions shape (posts/regular msgs)."""
    from telegram_download_chat.core import TelegramChatDownloader

    raw_post = MagicMock()
    raw_post.to_dict.return_value = {
        "id": 1,
        "message": "post",
        "reactions": _msg_reactions([_emoji_count("👍", 5)]),
    }
    # A comment is a plain dict (no to_dict) carrying raw reactions; it must be
    # normalized the same way regular messages are.
    comment = {
        "id": 1001,
        "message": "comment",
        "comment_of": 1,
        "reactions": _msg_reactions([_custom_count(42, 3)]),
    }
    no_reactions = MagicMock()
    no_reactions.to_dict.return_value = {"id": 2, "message": "plain"}

    output_file = tmp_path / "messages.json"
    downloader = TelegramChatDownloader()
    downloader.logger = MagicMock()
    await downloader.save_messages(
        [raw_post, comment, no_reactions], str(output_file), save_txt=False
    )

    saved = json.loads(output_file.read_text(encoding="utf-8"))
    by_id = {m["id"]: m for m in saved}
    assert by_id[1]["reactions"] == [{"emoji": "👍", "count": 5}]
    assert by_id[1001]["reactions"] == [{"custom_emoji_id": 42, "count": 3}]
    assert "reactions" not in by_id[2]

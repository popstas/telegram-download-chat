"""Tests for message reactions normalization and HTML pill rendering (Task 6).

Reactions are normalized from Telethon's verbose ``MessageReactions`` dict into a
stable list shape stored in the saved JSON, then rendered as pills (emoji +
count) under each message in the HTML export.
"""

from telegram_download_chat.core.reactions import (
    format_reactions_text,
    normalize_reactions,
    total_reaction_count,
)
from telegram_download_chat.core.render import (
    HTML_TEMPLATE,
    RenderMixin,
    _comment_filters,
    _comment_reaction_percentiles,
)


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


# ── total_reaction_count ───────────────────────────────────────────────────


def test_total_reaction_count_none_and_empty():
    assert total_reaction_count(None) == 0
    assert total_reaction_count([]) == 0
    assert total_reaction_count(_msg_reactions([])) == 0


def test_total_reaction_count_sums_all_counts():
    raw = _msg_reactions([_emoji_count("👍", 5), _emoji_count("❤️", 2)])
    assert total_reaction_count(raw) == 7


def test_total_reaction_count_includes_custom_emoji():
    raw = _msg_reactions([_emoji_count("👍", 5), _custom_count(123, 3)])
    assert total_reaction_count(raw) == 8


def test_total_reaction_count_on_normalized_list():
    norm = [{"emoji": "👍", "count": 5}, {"custom_emoji_id": 7, "count": 1}]
    assert total_reaction_count(norm) == 6


# ── format_reactions_text ──────────────────────────────────────────────────


def test_format_reactions_text_none_empty():
    assert format_reactions_text(None) == ""
    assert format_reactions_text([]) == ""
    assert format_reactions_text(_msg_reactions([])) == ""


def test_format_reactions_text_emoji():
    raw = _msg_reactions([_emoji_count("👍", 5), _emoji_count("❤️", 2)])
    assert format_reactions_text(raw) == "👍5 ❤️2"


def test_format_reactions_text_custom_emoji_placeholder():
    raw = _msg_reactions([_emoji_count("👍", 5), _custom_count(123, 3)])
    assert format_reactions_text(raw) == "👍5 ⭐3"


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

# ── Comment percentile filter (Task 2) ──────────────────────────────────────


def test_comment_reaction_percentiles_empty():
    assert _comment_reaction_percentiles([]) == []


def test_comment_reaction_percentiles_distribution():
    totals = [0, 0, 1, 2, 3, 5, 8, 10, 12, 20]
    assert _comment_reaction_percentiles(totals) == [
        {"percentile": 50, "threshold": 5, "count": 5},
        {"percentile": 20, "threshold": 12, "count": 2},
        {"percentile": 10, "threshold": 20, "count": 1},
        {"percentile": 5, "threshold": 20, "count": 1},
    ]


def test_comment_filters_empty():
    assert _comment_filters([]) == []


def test_comment_filters_always_has_one_plus_and_hides_zero():
    # Most comments have 0 reactions, so the 50th-percentile threshold is 0 and
    # must be hidden; a fixed "1+" floor is always present.
    totals = [0, 0, 0, 0, 1, 2, 6, 14]
    buttons = _comment_filters(totals)
    thresholds = [b["threshold"] for b in buttons]
    assert thresholds[0] == 1  # always-present 1+ floor, first
    assert 0 not in thresholds  # no "0+" buttons
    labels = [b["label"] for b in buttons]
    assert labels[0] == "1+"
    assert all("0+" not in lbl for lbl in labels)
    # Counts: 1+ -> comments with >=1 reaction.
    assert buttons[0] == {"label": "1+", "threshold": 1, "count": 4}


def test_comment_filters_dedupes_threshold_one_percentile():
    # A percentile whose threshold equals 1 must not duplicate the fixed 1+.
    totals = [0, 1, 1, 5]
    buttons = _comment_filters(totals)
    thresholds = [b["threshold"] for b in buttons]
    assert thresholds.count(1) == 1


def _post_msg(mid, text):
    return {
        "id": mid,
        "date": "2026-01-01T10:00:00+00:00",
        "from_id": {"channel_id": 500},
        "user_display_name": "Channel",
        "message": text,
    }


def _comment_msg(mid, sender, text, comment_of, reactions=None):
    d = {
        "id": mid,
        "date": f"2026-01-01T10:{mid % 60:02d}:00+00:00",
        "from_id": {"user_id": sender},
        "user_display_name": f"U{sender}",
        "message": text,
        "comment_of": comment_of,
        "discussion_msg_id": mid,
        "reply_to": {"reply_to_msg_id": comment_of},
        "reply_to_msg_id": comment_of,
    }
    if reactions is not None:
        d["reactions"] = reactions
    return d


def test_html_comment_filter_bar_present(tmp_path):
    out = tmp_path / "out.html"
    RenderMixin().render_html(
        [
            _post_msg(1, "post"),
            _comment_msg(1001, 2, "a", 1, [{"emoji": "👍", "count": 5}]),
            _comment_msg(1002, 3, "b", 1, [{"emoji": "👍", "count": 1}]),
        ],
        out,
        chat_title="t",
    )
    html = out.read_text(encoding="utf-8")
    # Filter bar with an All button, a fixed 1+ button, and percentile buttons.
    assert 'class="cfilter"' in html
    assert 'data-threshold="0"' in html  # All
    assert 'data-threshold="1"' in html  # always-present 1+ floor
    assert ">1+ (" in html  # 1+ button label
    # Comment bubbles carry their total reaction count for client-side filtering.
    assert 'data-reactions="5"' in html
    assert 'data-reactions="1"' in html


def test_html_no_comment_filter_bar_without_comments(tmp_path):
    out = tmp_path / "out.html"
    RenderMixin().render_html([_post_msg(1, "post only")], out, chat_title="t")
    html = out.read_text(encoding="utf-8")
    assert 'class="cfilter"' not in html


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

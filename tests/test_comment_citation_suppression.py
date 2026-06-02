"""Tests for suppressing the parent-post citation inside channel comments (Task 3).

Channel comments are normalized so each points at its parent channel post
(``comment_of``) and the render path nests them under that post. Showing the
post as a quoted citation inside every comment is redundant, so it is
suppressed — but only for channel comments and only when the cited parent is
the post itself. Ordinary reply citations (and comments quoting another comment)
stay unaffected.
"""

from telegram_download_chat.core.render import RenderMixin


def _renderer():
    return RenderMixin()


def _post(mid, minute, text):
    return {
        "id": mid,
        "date": f"2026-01-01T10:{minute:02d}:00+00:00",
        "from_id": {"channel_id": 500},
        "user_display_name": "Channel",
        "message": text,
    }


def _comment(mid, minute, sender, text, comment_of, reply_to_msg_id=None):
    """A normalized channel comment.

    By default ``reply_to_msg_id`` points at the parent post (as
    ``core/comments.py`` normalizes them); pass a different value to model a
    comment that quotes another comment.
    """
    target = reply_to_msg_id if reply_to_msg_id is not None else comment_of
    return {
        "id": mid,
        "date": f"2026-01-01T10:{minute:02d}:00+00:00",
        "from_id": {"user_id": sender},
        "user_display_name": f"User{sender}",
        "message": text,
        "comment_of": comment_of,
        "discussion_msg_id": mid,
        "reply_to": {"reply_to_msg_id": target},
        "reply_to_msg_id": target,
    }


def test_comment_does_not_cite_parent_post(tmp_path):
    renderer = _renderer()
    out = tmp_path / "out.html"
    renderer.render_html(
        [
            _post(1, 0, "Original post"),
            _comment(1001, 5, 2, "great post", comment_of=1),
        ],
        out,
        chat_title="t",
    )
    html = out.read_text(encoding="utf-8")
    # The comment renders, but with no quoted citation of the parent post.
    assert "great post" in html
    assert 'href="#msg-1"' not in html
    assert 'class="rq"' not in html


def test_comment_quoting_another_comment_is_still_cited(tmp_path):
    renderer = _renderer()
    out = tmp_path / "out.html"
    renderer.render_html(
        [
            _post(1, 0, "Original post"),
            _comment(1001, 5, 2, "first comment", comment_of=1),
            # This comment replies to comment 1001, not to the post.
            _comment(1002, 6, 3, "reply to first", comment_of=1, reply_to_msg_id=1001),
        ],
        out,
        chat_title="t",
    )
    html = out.read_text(encoding="utf-8")
    # The intra-comment reply is preserved (cites the quoted comment).
    assert "first comment" in html
    assert 'href="#msg-1001"' in html


def test_non_comment_reply_citation_unaffected(tmp_path):
    """A regular reply (no ``comment_of``) still renders its citation."""
    renderer = _renderer()
    out = tmp_path / "out.html"
    renderer.render_html(
        [
            {
                "id": 1,
                "date": "2026-01-01T10:00:00+00:00",
                "from_id": {"user_id": 1},
                "user_display_name": "Alice",
                "message": "the original",
            },
            {
                "id": 2,
                "date": "2026-01-01T10:05:00+00:00",
                "from_id": {"user_id": 2},
                "user_display_name": "Bob",
                "message": "the reply",
                "reply_to": {"reply_to_msg_id": 1},
            },
        ],
        out,
        chat_title="t",
    )
    html = out.read_text(encoding="utf-8")
    assert 'href="#msg-1"' in html
    assert 'class="rq"' in html


def test_comments_render_in_collapsible_details(tmp_path):
    """Channel comments fold into a collapsible <details> whose summary shows
    the comment count; the post itself stays a normal bubble."""
    renderer = _renderer()
    out = tmp_path / "out.html"
    renderer.render_html(
        [
            _post(1, 0, "Original post"),
            _comment(1001, 5, 2, "first comment", comment_of=1),
            _comment(1002, 6, 3, "second comment", comment_of=1),
        ],
        out,
        chat_title="t",
    )
    html = out.read_text(encoding="utf-8")
    # A single collapsible block holds both comments and reports the count.
    assert html.count('<details class="comments"') == 1
    assert "2 comments" in html
    # Comment bodies live inside the collapsible block.
    body = html.split('<div class="comments-body">', 1)[1]
    assert "first comment" in body
    assert "second comment" in body
    # The post bubble is NOT inside the collapsible block.
    pre = html.split('<details class="comments"', 1)[0]
    assert "Original post" in pre
    # The stylesheet defines the collapsible rules.
    assert ".comments-sum" in html


def test_comment_count_is_singular_for_one_comment(tmp_path):
    renderer = _renderer()
    out = tmp_path / "out.html"
    renderer.render_html(
        [
            _post(1, 0, "Original post"),
            _comment(1001, 5, 2, "only comment", comment_of=1),
        ],
        out,
        chat_title="t",
    )
    html = out.read_text(encoding="utf-8")
    assert "1 comment" in html
    assert "1 comments" not in html


def test_comments_for_two_posts_get_separate_blocks(tmp_path):
    renderer = _renderer()
    out = tmp_path / "out.html"
    renderer.render_html(
        [
            _post(1, 0, "First post"),
            _comment(1001, 5, 2, "on first", comment_of=1),
            _post(2, 30, "Second post"),
            _comment(2001, 35, 2, "on second", comment_of=2),
        ],
        out,
        chat_title="t",
    )
    html = out.read_text(encoding="utf-8")
    assert html.count('<details class="comments"') == 2
    # Each post's comment block follows its post in document order.
    order = [
        html.index("First post"),
        html.index("on first"),
        html.index("Second post"),
        html.index("on second"),
    ]
    assert order == sorted(order)


def test_messages_without_comments_have_no_details(tmp_path):
    """A plain chat export emits no collapsible comment blocks."""
    renderer = _renderer()
    out = tmp_path / "out.html"
    renderer.render_html(
        [_post(1, 0, "just a post")],
        out,
        chat_title="t",
    )
    html = out.read_text(encoding="utf-8")
    assert '<details class="comments"' not in html

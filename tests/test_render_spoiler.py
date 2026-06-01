"""Tests for spoiler entity rendering in HTML/PDF exports.

The HTML export wraps ``MessageEntitySpoiler`` text in ``<span class="spoiler">``;
this is only meaningful if the embedded stylesheet actually defines a ``.spoiler``
rule, otherwise the "hidden" text renders as plain visible text. These tests guard
both the markup and the presence of the CSS.
"""

from telegram_download_chat.core.render import HTML_TEMPLATE, format_entities


def _spoiler(offset=0, length=6):
    return [{"_": "MessageEntitySpoiler", "offset": offset, "length": length}]


def test_html_spoiler_wraps_in_span():
    out = format_entities("secret", _spoiler(), "html")
    assert out == '<span class="spoiler">secret</span>'


def test_pdf_spoiler_keeps_text_without_markup():
    # PDF has no spoiler concept; the text must survive but carry no tags.
    out = format_entities("secret", _spoiler(), "pdf")
    assert out == "secret"


def test_html_template_defines_spoiler_css():
    # Without a .spoiler rule the span emitted above would be visible plain text.
    assert ".spoiler" in HTML_TEMPLATE

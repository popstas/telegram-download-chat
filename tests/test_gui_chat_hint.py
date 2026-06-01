"""Tests for the Chat-field help hint in the download tab.

The hint appears in two toggleable forms: an info (ⓘ) button with a hover
tooltip, and a collapsible "How to fill this?" help block. Both default on and
are controlled by settings.gui_chat_hint_tooltip / settings.gui_chat_hint_help.
"""

import os
from unittest.mock import patch

import pytest

# Skip the whole module when the optional GUI dependency is absent (CI installs
# the package without [gui]). Importing download_tab pulls in PySide6.
pytest.importorskip("PySide6")

# Allow the Qt-based tests to run without a display (e.g. CI).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    for widget in app.allWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()


def _make_tab(flags):
    """Construct a DownloadTab with the given (tooltip, help) flags."""
    from telegram_download_chat.gui.tabs.download_tab import DownloadTab

    with patch.object(DownloadTab, "_load_settings", lambda self: None), patch.object(
        DownloadTab, "_chat_hint_flags", lambda self: flags
    ):
        return DownloadTab()


def test_hint_text_mentions_saved_messages_and_formats():
    from telegram_download_chat.gui.tabs.download_tab import (
        _chat_hint_html,
        _chat_hint_tooltip,
    )

    tip = _chat_hint_tooltip()
    html = _chat_hint_html()
    for needle in ("Saved Messages", "me", "folder:Work", "messages.json"):
        assert needle in tip
        assert needle in html
    assert html.startswith("<ul")


def test_default_flags_tooltip_off_help_on(qapp):
    """With no config overrides, the tooltip is off and the help block is on."""
    from telegram_download_chat.gui.tabs.download_tab import DownloadTab
    from telegram_download_chat.gui.utils import config as cfg_mod

    class _EmptyConfig:
        def load(self):
            pass

        def get(self, key, default=None):
            return default  # no overrides -> use defaults

    # _chat_hint_flags imports ConfigManager from gui.utils.config at call time.
    with patch.object(cfg_mod, "ConfigManager", _EmptyConfig), patch.object(
        DownloadTab, "_load_settings", lambda self: None
    ):
        tab = DownloadTab()

    assert tab.chat_info_btn is None  # tooltip off by default
    assert tab.chat_edit.toolTip() == ""
    assert tab.chat_help_btn is not None  # help on by default
    assert tab.chat_help_label is not None


def test_both_flags_on(qapp):
    tab = _make_tab((True, True))
    # Tooltip on the field and the info button.
    assert "Saved Messages" in tab.chat_edit.toolTip()
    assert tab.chat_info_btn is not None
    assert "Saved Messages" in tab.chat_info_btn.toolTip()
    # Collapsible help starts hidden, toggles open. Use isHidden() (the explicit
    # flag) since isVisible() also requires the top-level window to be shown.
    assert tab.chat_help_btn is not None
    assert tab.chat_help_label is not None
    assert tab.chat_help_label.isHidden() is True
    assert "▶" in tab.chat_help_btn.text()
    tab._toggle_chat_help()
    assert tab.chat_help_label.isHidden() is False
    assert "▼" in tab.chat_help_btn.text()


def test_both_flags_off(qapp):
    tab = _make_tab((False, False))
    assert tab.chat_info_btn is None
    assert tab.chat_help_btn is None
    assert tab.chat_help_label is None
    assert tab.chat_edit.toolTip() == ""


def test_tooltip_only(qapp):
    tab = _make_tab((True, False))
    assert tab.chat_info_btn is not None
    assert "Saved Messages" in tab.chat_edit.toolTip()
    assert tab.chat_help_btn is None
    assert tab.chat_help_label is None


def test_help_only(qapp):
    tab = _make_tab((False, True))
    assert tab.chat_info_btn is None
    assert tab.chat_edit.toolTip() == ""
    assert tab.chat_help_btn is not None
    assert tab.chat_help_label is not None

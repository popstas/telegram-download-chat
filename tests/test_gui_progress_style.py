"""Tests for the shared GUI progress-bar styling (gui/utils/styles.py).

Verifies the progress bar reads as green (healthy progress) rather than the
default highlight/red, that the helper applies the sheet, and that the download
and convert tabs actually use the shared green styling.
"""

import os
from unittest.mock import patch

import pytest

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


def test_progress_bar_stylesheet_is_green(qapp):
    from telegram_download_chat.gui.utils.styles import (
        PROGRESS_GREEN,
        progress_bar_stylesheet,
    )

    sheet = progress_bar_stylesheet()
    # The filled chunk (and the indeterminate sweep) must be green.
    assert "QProgressBar::chunk" in sheet
    assert PROGRESS_GREEN in sheet
    assert "QProgressBar:indeterminate::chunk" in sheet
    # Must not fall back to a red error color.
    for red in ("#f44336", "#d32f2f", "#b71c1c", "red"):
        assert red not in sheet


def test_style_progress_bar_applies_sheet(qapp):
    from PySide6.QtWidgets import QProgressBar

    from telegram_download_chat.gui.utils.styles import (
        PROGRESS_GREEN,
        style_progress_bar,
    )

    bar = QProgressBar()
    style_progress_bar(bar)
    assert "QProgressBar::chunk" in bar.styleSheet()
    assert PROGRESS_GREEN in bar.styleSheet()


def test_download_tab_progress_styled_green(qapp):
    from telegram_download_chat.gui.tabs.download_tab import DownloadTab
    from telegram_download_chat.gui.utils.styles import PROGRESS_GREEN

    with patch.object(DownloadTab, "_load_settings", lambda self: None):
        tab = DownloadTab()

    assert PROGRESS_GREEN in tab.progress.styleSheet()
    # Resetting the style keeps it green, not red.
    tab._reset_progress_style()
    assert PROGRESS_GREEN in tab.progress.styleSheet()


def test_convert_tab_progress_styled_green(qapp):
    from telegram_download_chat.gui.tabs.convert_tab import ConvertTab
    from telegram_download_chat.gui.utils.styles import PROGRESS_GREEN

    tab = ConvertTab()
    assert PROGRESS_GREEN in tab.progress.styleSheet()

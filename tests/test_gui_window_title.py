"""Tests for the GUI main window title including the application version."""

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


def test_window_title_includes_version(qapp):
    from telegram_download_chat import __version__
    from telegram_download_chat.gui.windows.main_window import MainWindow

    # Avoid touching the real config/settings during construction.
    with patch.object(MainWindow, "_load_settings", lambda self: None):
        window = MainWindow()

    title = window.windowTitle()
    assert __version__ in title
    assert "Telegram Download Chat" in title

"""Tests for the shared GUI checkbox styling (gui/utils/styles.py).

Verifies that the unchecked checkbox indicator is styled with the text-input
(QLineEdit) background color, that the checked state is left untouched, and that
the download tab actually applies the shared stylesheet to its checkboxes.
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


def test_input_background_matches_lineedit(qapp):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QLineEdit

    from telegram_download_chat.gui.utils.styles import input_background_color

    edit = QLineEdit()
    expected = edit.palette().color(QPalette.Base).name()
    assert input_background_color(edit) == expected


def test_checkbox_stylesheet_targets_unchecked_with_input_bg(qapp):
    from telegram_download_chat.gui.utils.styles import (
        checkbox_stylesheet,
        input_background_color,
    )

    sheet = checkbox_stylesheet()
    assert "QCheckBox::indicator:unchecked" in sheet
    # Unchecked indicator background must equal the input background color.
    assert input_background_color() in sheet
    # Checked state must not be overridden so it keeps its native appearance.
    assert ":checked" not in sheet


def test_style_checkboxes_applies_sheet(qapp):
    from PySide6.QtWidgets import QCheckBox

    from telegram_download_chat.gui.utils.styles import (
        input_background_color,
        style_checkboxes,
    )

    boxes = [QCheckBox(), QCheckBox()]
    style_checkboxes(boxes)
    for box in boxes:
        assert "indicator:unchecked" in box.styleSheet()
        assert input_background_color() in box.styleSheet()


def test_download_tab_checkboxes_styled(qapp):
    from telegram_download_chat.gui.tabs.download_tab import DownloadTab

    # Avoid touching the real config during construction.
    with patch.object(DownloadTab, "_load_settings", lambda self: None):
        tab = DownloadTab()

    for chk in (
        tab.debug_chk,
        tab.overwrite_chk,
        tab.media_chk,
        tab.html_chk,
        tab.pdf_chk,
    ):
        assert "indicator:unchecked" in chk.styleSheet()

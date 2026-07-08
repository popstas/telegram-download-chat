"""Regression test for issue #86.

Clicking "Get Code" without API credentials must surface the real error
("API ID and API Hash are required"), not the AttributeError raised by the
finally block when `self.downloader` was never assigned.
"""

import asyncio
import os

import pytest
from unittest.mock import patch

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


def _make_tab():
    from telegram_download_chat.gui.tabs.settings_tab import SettingsTab

    with patch.object(SettingsTab, "_load_settings", lambda self: None):
        return SettingsTab()


def test_missing_credentials_raises_original_error(qapp):
    tab = _make_tab()
    # Ensure credential fields are empty and a phone is present so the
    # failure happens at credential validation, before `self.downloader`
    # would ever be assigned.
    tab.api_id_edit.setText("")
    tab.api_hash_edit.setText("")
    tab.phone_edit.setText("+10000000000")

    with pytest.raises(Exception) as excinfo:
        asyncio.run(tab._request_code_async("+10000000000"))

    message = str(excinfo.value)
    assert "API ID and API Hash are required" in message
    assert "has no attribute 'downloader'" not in message

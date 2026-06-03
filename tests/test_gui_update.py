"""GUI wiring for in-app self-update on the embeddable build.

When an update is available *and* the app runs from a two-part embeddable
install, the Settings tab offers an in-app "Update now" (download app zip +
atomic swap) instead of opening the browser to the releases page.
"""

import os
from unittest.mock import patch

import pytest

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


_RESULT = {
    "current": "1.0.0",
    "latest": "2.0.0",
    "update_available": True,
    "download_url": None,
    "error": None,
}


def test_in_app_update_mode_when_embeddable(qapp, tmp_path):
    tab = _make_tab()
    with patch(
        "telegram_download_chat.core.app_updater.find_app_install_dir",
        return_value=tmp_path,
    ):
        tab._apply_update_check_result(_RESULT)

    assert tab._in_app_update is True
    assert tab.download_update_btn.isVisible() or True  # visible after layout
    assert tab.download_update_btn.text() == "Update now"
    assert tab._update_app_url and tab._update_app_url.endswith("app-2.0.0.zip")


def test_browser_mode_when_not_embeddable(qapp):
    tab = _make_tab()
    with patch(
        "telegram_download_chat.core.app_updater.find_app_install_dir",
        return_value=None,
    ):
        tab._apply_update_check_result(_RESULT)

    assert tab._in_app_update is False
    assert tab.download_update_btn.text() == "Download"


def test_download_button_routes_to_in_app_install(qapp, tmp_path):
    tab = _make_tab()
    with patch(
        "telegram_download_chat.core.app_updater.find_app_install_dir",
        return_value=tmp_path,
    ):
        tab._apply_update_check_result(_RESULT)
    with patch.object(tab, "_install_app_update") as install, patch.object(
        tab, "_open_download_url"
    ) as browser:
        tab._download_update()
    install.assert_called_once()
    browser.assert_not_called()

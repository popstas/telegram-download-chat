"""Tests for the GitHub release update checker (core/update_checker.py).

Covers version parsing/comparison, installer URL resolution, the
``fetch_latest_version`` redirect/HTML parsing, the ``check_for_update``
convenience wrapper, and (when PySide6 is available) the Settings tab's
Check-updates/Download button swap logic.
"""

import os
import urllib.error
from unittest.mock import patch

import pytest

# Allow the Qt-based GUI tests below to run without a display (e.g. CI).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from telegram_download_chat.core import update_checker as uc


class _FakeResponse:
    """Minimal context-manager stand-in for urllib's response object."""

    def __init__(self, final_url="", body=b""):
        self._final_url = final_url
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def geturl(self):
        return self._final_url

    def read(self):
        return self._body


class TestCompareVersions:
    def test_latest_newer(self):
        assert uc.compare_versions("0.10.3", "0.10.4") is True

    def test_latest_older(self):
        assert uc.compare_versions("0.10.4", "0.10.3") is False

    def test_equal(self):
        assert uc.compare_versions("1.2.3", "1.2.3") is False

    def test_major_bump(self):
        assert uc.compare_versions("0.9.9", "1.0.0") is True

    def test_different_lengths(self):
        assert uc.compare_versions("1.2", "1.2.1") is True
        assert uc.compare_versions("1.2.0", "1.2") is False

    def test_v_prefix_tolerated(self):
        assert uc.compare_versions("v1.0.0", "v1.0.1") is True

    def test_prerelease_suffix_parsed_numerically(self):
        # Non-numeric trailing chunks fall back to the numeric prefix.
        assert uc.compare_versions("1.0.0", "1.0.1rc1") is True

    def test_non_numeric_falls_back_to_lexicographic(self):
        # A leading non-numeric chunk makes _version_parts raise, exercising the
        # lexicographic fallback branch.
        assert uc.compare_versions("abc", "abd") is True
        assert uc.compare_versions("abd", "abc") is False


class TestInstallerUrl:
    def test_includes_version_tag_and_asset(self):
        url = uc.get_installer_url("0.10.4")
        assert url == (
            "https://github.com/popstas/telegram-download-chat"
            "/releases/download/v0.10.4/telegram-download-chat.exe"
        )

    def test_v_prefixed_version_not_doubled(self):
        url = uc.get_installer_url("v0.10.4")
        assert "/download/v0.10.4/" in url
        assert "/vv" not in url

    def test_releases_page_url(self):
        assert uc.get_releases_page_url().endswith("/releases")


class TestFetchLatestVersion:
    def test_parses_version_from_redirect_url(self):
        resp = _FakeResponse(
            final_url="https://github.com/popstas/telegram-download-chat/releases/tag/v0.10.5"
        )
        with patch("urllib.request.urlopen", return_value=resp):
            version, error = uc.fetch_latest_version()
        assert version == "0.10.5"
        assert error is None

    def test_parses_version_from_html_fallback(self):
        body = (
            b'<a href="/popstas/telegram-download-chat/releases/tag/v0.11.0">'
            b"v0.11.0</a>"
        )
        resp = _FakeResponse(final_url="https://github.com/", body=body)
        with patch("urllib.request.urlopen", return_value=resp):
            version, error = uc.fetch_latest_version()
        assert version == "0.11.0"
        assert error is None

    def test_unparseable_returns_error(self):
        resp = _FakeResponse(final_url="https://github.com/", body=b"nothing here")
        with patch("urllib.request.urlopen", return_value=resp):
            version, error = uc.fetch_latest_version()
        assert version is None
        assert error

    def test_network_error_returns_error(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("boom"),
        ):
            version, error = uc.fetch_latest_version()
        assert version is None
        assert "Network error" in error


class TestCheckForUpdate:
    def test_update_available(self):
        with patch.object(uc, "fetch_latest_version", return_value=("0.99.0", None)):
            result = uc.check_for_update(current_version="0.10.3")
        assert result["update_available"] is True
        assert result["latest"] == "0.99.0"
        assert result["download_url"].endswith(
            "/releases/download/v0.99.0/telegram-download-chat.exe"
        )
        assert result["error"] is None

    def test_up_to_date(self):
        with patch.object(uc, "fetch_latest_version", return_value=("0.10.3", None)):
            result = uc.check_for_update(current_version="0.10.3")
        assert result["update_available"] is False
        assert result["download_url"] is None
        assert result["error"] is None

    def test_error_propagates(self):
        with patch.object(
            uc, "fetch_latest_version", return_value=(None, "Network error: x")
        ):
            result = uc.check_for_update(current_version="0.10.3")
        assert result["update_available"] is False
        assert result["latest"] is None
        assert result["error"]


# ---------------------------------------------------------------------------
# GUI button-swap logic (requires PySide6)
# ---------------------------------------------------------------------------


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


def _make_settings_tab():
    from telegram_download_chat.gui.tabs.settings_tab import SettingsTab

    # Avoid touching the real config/session during construction.
    with patch.object(SettingsTab, "_load_settings", lambda self: None):
        tab = SettingsTab()
    return tab


def test_settings_tab_update_available_swaps_button(qapp):
    tab = _make_settings_tab()
    result = {
        "current": "0.10.3",
        "latest": "0.99.0",
        "update_available": True,
        "download_url": uc.get_installer_url("0.99.0"),
        "error": None,
    }
    with patch.object(uc, "is_windows", return_value=True):
        tab._apply_update_check_result(result)
    assert tab.download_update_btn.isHidden() is False
    assert tab.check_updates_btn.isHidden() is True
    assert tab._update_download_url.endswith("telegram-download-chat.exe")
    assert "0.99.0" in tab.update_status_label.text()


def test_settings_tab_update_available_non_windows_uses_releases_page(qapp):
    tab = _make_settings_tab()
    result = {
        "current": "0.10.3",
        "latest": "0.99.0",
        "update_available": True,
        "download_url": uc.get_installer_url("0.99.0"),
        "error": None,
    }
    with patch.object(uc, "is_windows", return_value=False):
        tab._apply_update_check_result(result)
    assert tab.download_update_btn.isHidden() is False
    assert tab._update_download_url == uc.get_releases_page_url()


def test_settings_tab_up_to_date_keeps_check_button(qapp):
    tab = _make_settings_tab()
    tab._apply_update_check_result(
        {
            "current": "0.10.3",
            "latest": "0.10.3",
            "update_available": False,
            "download_url": None,
            "error": None,
        }
    )
    assert tab.check_updates_btn.isHidden() is False
    assert tab.download_update_btn.isHidden() is True
    assert tab._update_download_url is None
    assert "up to date" in tab.update_status_label.text().lower()


def test_settings_tab_error_shows_message(qapp):
    tab = _make_settings_tab()
    tab._apply_update_check_result(
        {
            "current": "0.10.3",
            "latest": None,
            "update_available": False,
            "download_url": None,
            "error": "Network error: boom",
        }
    )
    assert tab.check_updates_btn.isHidden() is False
    assert tab.download_update_btn.isHidden() is True
    assert "failed" in tab.update_status_label.text().lower()

"""Tests for the GUI speech-to-text checkbox (``--stt``)."""

import os

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


def _make_tab():
    from unittest.mock import patch

    from telegram_download_chat.gui.tabs.download_tab import DownloadTab

    with patch.object(DownloadTab, "_load_settings", lambda self: None):
        tab = DownloadTab()
    tab.chat_edit.setText("popstas")
    return tab


def _collect_cmd(tab):
    from unittest.mock import patch

    captured = {}
    tab.download_started.connect(lambda args, out: captured.setdefault("args", args))
    with patch.object(tab, "_save_settings", lambda: None):
        tab.start_download()
    return captured.get("args", [])


def test_stt_flag_absent_when_unchecked(qapp):
    tab = _make_tab()
    tab.stt_chk.setChecked(False)
    assert "--stt" not in _collect_cmd(tab)


def test_stt_flag_added_when_checked(qapp):
    tab = _make_tab()
    tab.stt_chk.setChecked(True)
    assert "--stt" in _collect_cmd(tab)


def test_stt_setting_round_trip(qapp):
    tab = _make_tab()
    tab.stt_chk.setChecked(True)

    settings = {}
    tab.save_settings(settings)
    assert settings["stt"] is True

    other = _make_tab()
    other.load_settings(settings)
    assert other.stt_chk.isChecked() is True

"""Tests for the GUI comments wiring and the structured ``comments`` event.

Covers:
* the download tab's "Download comments" checkbox + "Comments per post" combo
  command build (``--comments``; ``--comments-limit N`` only for numeric
  presets, neither when "No limit");
* the combo being enabled only while the checkbox is checked;
* settings round-trip (save/restore) of the comments flag and limit;
* the GUI worker translating a ``comments`` progress event into Qt signals.
"""

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

    # Avoid touching the real config during construction.
    with patch.object(DownloadTab, "_load_settings", lambda self: None):
        tab = DownloadTab()
    tab.chat_edit.setText("@somechannel")
    return tab


def _collect_cmd(tab):
    """Run start_download with save disabled and capture the emitted cmd args."""
    from unittest.mock import patch

    captured = {}
    tab.download_started.connect(lambda args, out: captured.setdefault("args", args))
    with patch.object(tab, "_save_settings", lambda: None):
        tab.start_download()
    return captured.get("args", [])


# ---------------------------------------------------------------------------
# Command build
# ---------------------------------------------------------------------------


def test_no_comments_when_unchecked(qapp):
    tab = _make_tab()
    tab.comments_chk.setChecked(False)
    args = _collect_cmd(tab)
    assert "--comments" not in args
    assert "--comments-limit" not in args


def test_comments_no_limit_omits_limit_flag(qapp):
    tab = _make_tab()
    tab.comments_chk.setChecked(True)
    # "No limit" is the default (index 0, data None).
    tab._set_comments_limit(None)
    args = _collect_cmd(tab)
    assert "--comments" in args
    assert "--comments-limit" not in args


def test_comments_with_numeric_preset_adds_limit_flag(qapp):
    tab = _make_tab()
    tab.comments_chk.setChecked(True)
    tab._set_comments_limit(50)
    args = _collect_cmd(tab)
    assert "--comments" in args
    assert "--comments-limit" in args
    assert args[args.index("--comments-limit") + 1] == "50"


def test_combo_enabled_only_when_checked(qapp):
    tab = _make_tab()
    tab.comments_chk.setChecked(False)
    assert not tab.comments_limit_combo.isEnabled()
    tab.comments_chk.setChecked(True)
    assert tab.comments_limit_combo.isEnabled()
    tab.comments_chk.setChecked(False)
    assert not tab.comments_limit_combo.isEnabled()


# ---------------------------------------------------------------------------
# Settings round-trip
# ---------------------------------------------------------------------------


def test_settings_round_trip(qapp):
    tab = _make_tab()
    tab.comments_chk.setChecked(True)
    tab._set_comments_limit(100)

    settings = {}
    tab.save_settings(settings)
    assert settings["comments"] is True
    assert settings["comments_limit"] == 100

    other = _make_tab()
    other.load_settings(settings)
    assert other.comments_chk.isChecked() is True
    assert other.comments_limit_combo.currentData() == 100
    assert other.comments_limit_combo.isEnabled()


def test_settings_restore_no_limit(qapp):
    tab = _make_tab()
    tab.load_settings({"comments": True, "comments_limit": None})
    assert tab.comments_chk.isChecked() is True
    assert tab.comments_limit_combo.currentData() is None


# ---------------------------------------------------------------------------
# Worker translation of the comments progress event
# ---------------------------------------------------------------------------


def test_worker_handles_comments_event(qapp):
    from telegram_download_chat.gui.worker import WorkerThread

    w = WorkerThread([], None)
    comments = []
    progress = []
    statuses = []
    w.comments_progress.connect(lambda d, t, c: comments.append((d, t, c)))
    w.progress.connect(lambda c, m: progress.append((c, m)))
    w.status_update.connect(statuses.append)

    w._handle_progress_event(
        {"type": "comments", "posts_done": 3, "posts_total": 10, "comments": 42}
    )

    assert comments == [(3, 10, 42)]
    assert (3, 10) in progress
    assert any("3/10" in s and "42 comments" in s for s in statuses)


def test_worker_comments_event_malformed_is_ignored(qapp):
    from telegram_download_chat.gui.worker import WorkerThread

    w = WorkerThread([], None)
    comments = []
    w.comments_progress.connect(lambda d, t, c: comments.append((d, t, c)))

    # Non-numeric counters must be swallowed, not raise.
    w._handle_progress_event(
        {"type": "comments", "posts_done": "x", "posts_total": 10, "comments": 1}
    )
    assert comments == []

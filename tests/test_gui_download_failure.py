"""The GUI must not claim success when the CLI subprocess failed (issue #91).

A user whose download died with "lost sys.stdin" saw the traceback in the log
while the status bar said "Download completed", because the worker never read
the exit code. The GUI also has to refuse to start a download with no session
instead of letting the subprocess crash.
"""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    # Deleting the windows here crashes Qt under the offscreen platform; the
    # process is about to exit anyway, so just drain pending events.
    app.processEvents()


# Keep windows alive for the whole module: a garbage-collected parent takes its
# Qt children with it and the next access segfaults.
_WINDOWS = []


class _FakeProc:
    """Minimal Popen stand-in that ends with the given exit code."""

    def __init__(self, returncode, lines=("boom\n",)):
        self._lines = list(lines) + [""]
        self.stdout = self
        self.returncode = returncode

    def readline(self):
        return self._lines.pop(0) if self._lines else ""

    def poll(self):
        return None if self._lines else self.returncode

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return self.returncode


def _run_worker(monkeypatch, tmp_path, returncode):
    from telegram_download_chat.gui import worker as worker_mod
    from telegram_download_chat.gui.worker import WorkerThread

    captured = {}

    def fake_popen(*args, **kwargs):
        captured["kwargs"] = kwargs
        return _FakeProc(returncode)

    monkeypatch.setattr(worker_mod.subprocess, "Popen", fake_popen)

    w = WorkerThread(["chat"], str(tmp_path))
    results = []
    w.finished.connect(
        lambda files, stopped, code: results.append((files, stopped, code))
    )
    w.run()
    return results, captured["kwargs"]


def test_worker_reports_the_exit_code(qapp, monkeypatch, tmp_path):
    results, _ = _run_worker(monkeypatch, tmp_path, returncode=1)

    assert results and results[0][2] == 1


def test_worker_reports_success_as_zero(qapp, monkeypatch, tmp_path):
    results, _ = _run_worker(monkeypatch, tmp_path, returncode=0)

    assert results and results[0][2] == 0


def test_worker_gives_the_child_no_stdin(qapp, monkeypatch, tmp_path):
    """Without this the child inherits a console and could sit on a prompt."""
    _, kwargs = _run_worker(monkeypatch, tmp_path, returncode=0)

    assert kwargs["stdin"] is subprocess.DEVNULL


def _window():
    from telegram_download_chat.gui.windows.main_window import MainWindow

    with patch.object(MainWindow, "_load_settings", lambda self: None):
        window = MainWindow()
    window.status_bar = MagicMock()
    window.log_viewer = MagicMock()
    window.file_list = MagicMock()
    window._files_before_download = set()
    _WINDOWS.append(window)
    return window


def _try_start_download(window):
    """Call _start_download without letting it spawn a real subprocess.

    Returns (warned, scheduled): whether the user was warned, and whether the
    worker was scheduled to start.
    """
    with patch("telegram_download_chat.gui.windows.main_window.QTimer") as timer:
        with patch(
            "telegram_download_chat.gui.windows.main_window.QMessageBox"
        ) as message_box:
            window._start_download(["chat"], None)
    return message_box, timer.singleShot.called


def test_failed_download_reports_an_error(qapp):
    window = _window()

    with patch(
        "telegram_download_chat.gui.windows.main_window.QMessageBox"
    ) as message_box:
        window._on_worker_finished([], False, 1)

    message_box.critical.assert_called_once()
    assert not any(
        "completed" in str(call).lower()
        for call in window.status_bar.showMessage.call_args_list
    )


def test_successful_download_still_reports_completion(qapp):
    window = _window()

    with patch("telegram_download_chat.gui.windows.main_window.QMessageBox") as box:
        window._on_worker_finished([], False, 0)

    box.critical.assert_not_called()
    assert any(
        "completed" in str(call).lower()
        for call in window.status_bar.showMessage.call_args_list
    )


def test_download_refused_without_a_session(qapp):
    window = _window()
    window._logged_in = False

    message_box, scheduled = _try_start_download(window)

    assert not scheduled
    message_box.warning.assert_called_once()
    # The user is sent where logging in actually happens.
    assert window.tab_widget.currentWidget() is window.settings_tab


def test_download_proceeds_when_logged_in(qapp):
    window = _window()
    window._logged_in = True

    message_box, scheduled = _try_start_download(window)

    message_box.warning.assert_not_called()
    assert scheduled
    assert window.download_tab.stop_btn.isEnabled()


def test_auth_state_signal_updates_the_gate(qapp):
    window = _window()

    window._on_auth_state_changed(True)
    assert window._logged_in is True

    window._on_auth_state_changed(False)
    assert window._logged_in is False


def test_window_inherits_the_startup_session_state(qapp):
    """The tab validates while it is built, before the signal is connected."""
    window = _window()

    assert window._logged_in == window.settings_tab.is_logged_in


def test_download_proceeds_while_the_session_state_is_unknown(qapp):
    """Startup validation may not have finished; don't block on a guess."""
    window = _window()
    window._logged_in = None

    message_box, scheduled = _try_start_download(window)

    message_box.warning.assert_not_called()
    assert scheduled


def test_settings_tab_announces_the_validated_session(qapp):
    """The startup validation path must reach the window, or it blocks downloads."""
    from telegram_download_chat.gui.tabs.settings_tab import SettingsTab

    with patch.object(SettingsTab, "_load_settings", lambda self: None):
        tab = SettingsTab()
    _WINDOWS.append(tab)

    states = []
    tab.auth_state_changed.connect(states.append)

    tab._set_logged_in(True, skip_validation=True)
    tab._set_logged_in(False, show_login=True)

    assert states == [True, False]

"""GUI QR login: the Settings tab offers it and the flow runs off the UI thread."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


_WIDGETS = []


def _tab():
    from telegram_download_chat.gui.tabs.settings_tab import SettingsTab

    with patch.object(SettingsTab, "_load_settings", lambda self: None):
        tab = SettingsTab()
    _WIDGETS.append(tab)
    return tab


def test_login_group_offers_qr(qapp):
    tab = _tab()

    assert "QR" in tab.qr_login_btn.text()


def test_qr_button_starts_the_qr_flow(qapp):
    from telegram_download_chat.gui.auth.session_manager import SessionManager

    # Patch before the tab is built: the click is wired to the bound method.
    with patch.object(SessionManager, "login_qr") as login_qr:
        tab = _tab()
        tab.qr_login_btn.click()

    login_qr.assert_called_once()


def test_qr_pixmap_scales_the_matrix(qapp):
    from telegram_download_chat.gui.widgets.qr_dialog import qr_pixmap

    pixmap = qr_pixmap("tg://login?token=abc", module_px=4)

    assert not pixmap.isNull()
    assert pixmap.width() == pixmap.height()
    assert pixmap.width() % 4 == 0


def test_dialog_shows_the_code_and_the_url(qapp):
    from telegram_download_chat.gui.widgets.qr_dialog import QrLoginDialog

    dialog = QrLoginDialog()
    _WIDGETS.append(dialog)
    dialog.set_code("tg://login?token=abc")

    assert not dialog.qr_label.pixmap().isNull()
    assert "tg://login?token=abc" in dialog.url_label.text()

    dialog.set_status("Waiting")
    assert dialog.status_label.text() == "Waiting"


def _auth_mock():
    auth = MagicMock()
    auth.initialize = AsyncMock()
    auth.client = MagicMock()
    auth.client.disconnect = AsyncMock()
    auth.client.get_me = AsyncMock(
        return_value=MagicMock(username="popstas", phone="41791234567")
    )
    return auth


@pytest.mark.asyncio
async def test_worker_coroutine_touches_no_widgets(qapp):
    """Qt objects belong to the UI thread; the worker returns plain values."""
    tab = _tab()
    tab._set_logged_in = MagicMock()
    tab._update_telegram_auth = MagicMock()
    auth = _auth_mock()
    user = MagicMock(username="popstas", phone="41791234567")

    async def fake_qr_login(client, *, on_code, password=None, **kwargs):
        on_code("tg://login?token=abc")
        return user

    with patch(
        "telegram_download_chat.gui.auth.session_manager.qr_login", new=fake_qr_login
    ):
        result = await tab.session_manager._do_qr_login_async(auth)

    assert result == {"username": "popstas", "phone": "41791234567"}
    tab._set_logged_in.assert_not_called()
    tab._update_telegram_auth.assert_not_called()
    # The session file must be released before a download subprocess starts.
    auth.client.disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_worker_coroutine_releases_the_session_on_failure(qapp):
    from telegram_download_chat.core.qr_login import QrLoginTimeout

    tab = _tab()
    auth = _auth_mock()

    async def fake_qr_login(client, **kwargs):
        raise QrLoginTimeout("not scanned")

    with patch(
        "telegram_download_chat.gui.auth.session_manager.qr_login", new=fake_qr_login
    ):
        with pytest.raises(QrLoginTimeout):
            await tab.session_manager._do_qr_login_async(auth)

    auth.client.disconnect.assert_awaited()


@pytest.mark.asyncio
async def test_password_is_passed_as_a_value_not_read_from_the_widget(qapp):
    """QR login cannot prompt mid-flow, so the typed password is handed over."""
    tab = _tab()
    auth = _auth_mock()
    captured = {}

    async def fake_qr_login(client, *, on_code, password=None, **kwargs):
        captured["password"] = password() if password else None
        return MagicMock(username="p", phone=None)

    with patch(
        "telegram_download_chat.gui.auth.session_manager.qr_login", new=fake_qr_login
    ):
        await tab.session_manager._do_qr_login_async(auth, password="hunter2")
        await tab.session_manager._do_qr_login_async(auth)

    assert captured["password"] is None  # second call, no password given


def test_finish_marks_the_session_logged_in_on_the_ui_thread(qapp):
    tab = _tab()
    tab._set_logged_in = MagicMock()
    tab.config = MagicMock()
    manager = tab.session_manager
    manager._qr_result = {"username": "popstas", "phone": "41791234567"}

    with patch(
        "telegram_download_chat.gui.auth.session_manager.QMessageBox"
    ) as message_box:
        manager.finish_qr_login(True, "")

    tab._set_logged_in.assert_called_once_with(True, skip_validation=True)
    tab.config.set.assert_called_once_with("settings.phone", "41791234567")
    message_box.information.assert_called_once()


def test_finish_reports_failure_and_leaves_the_session_alone(qapp):
    tab = _tab()
    tab._set_logged_in = MagicMock()
    manager = tab.session_manager

    with patch(
        "telegram_download_chat.gui.auth.session_manager.QMessageBox"
    ) as message_box:
        manager.finish_qr_login(False, "not scanned")

    tab._set_logged_in.assert_not_called()
    message_box.critical.assert_called_once()
    assert tab.qr_login_btn.isEnabled()


def test_login_qr_reads_the_widgets_on_the_ui_thread(qapp):
    """The worker gets plain values; widgets stay on the thread that owns them."""
    tab = _tab()
    tab._update_telegram_auth = MagicMock()
    tab.telegram_auth = _auth_mock()
    tab.password_edit.setText("hunter2")

    with patch(
        "telegram_download_chat.gui.widgets.qr_dialog.QrLoginDialog"
    ) as dialog_cls:
        with patch.object(type(tab.session_manager), "_run_qr_worker") as run_worker:
            tab.session_manager.login_qr()

    tab._update_telegram_auth.assert_called_once()
    run_worker.assert_called_once_with(
        tab.telegram_auth, "hunter2", dialog_cls.return_value
    )
    # The dialog is shown and the login UI is disabled while it is pending.
    dialog_cls.return_value.exec.assert_called_once()
    assert not tab.qr_login_btn.isEnabled()


def test_login_qr_refuses_without_api_credentials(qapp):
    tab = _tab()
    tab._update_telegram_auth = MagicMock()
    tab.telegram_auth = None

    with patch(
        "telegram_download_chat.gui.auth.session_manager.QMessageBox"
    ) as message_box:
        tab.session_manager.login_qr()

    message_box.critical.assert_called_once()
    assert not hasattr(tab.session_manager, "_qr_thread")

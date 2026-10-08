import asyncio
import logging
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox
from telethon.errors import SessionPasswordNeededError

from ...core import TelegramAuth, TelegramChatDownloader
from ...core.auth_utils import TelegramAuthError
from ...core.qr_login import qr_login
from ...paths import get_app_dir


class SessionManager:
    """Handle login and logout logic for the settings tab."""

    def __init__(self, tab):
        self.tab = tab

    # UI helpers ---------------------------------------------------------
    def _set_ui_enabled(self, enabled: bool) -> None:
        self.tab.phone_edit.setEnabled(enabled)
        self.tab.code_edit.setEnabled(enabled)
        self.tab.password_edit.setEnabled(enabled)
        self.tab.get_code_btn.setEnabled(enabled)
        self.tab.login_btn.setEnabled(enabled)
        self.tab.logout_btn.setEnabled(enabled)
        qr_btn = getattr(self.tab, "qr_login_btn", None)
        if qr_btn is not None:
            qr_btn.setEnabled(enabled)

    # QR login ----------------------------------------------------------
    async def _do_qr_login_async(
        self, telegram_auth, password: Optional[str] = None, on_code=None
    ) -> dict:
        """Log in by QR code, off the UI thread.

        Touches no widgets: Qt objects may only be used from the thread that
        owns them, so everything UI-side happens in :meth:`login_qr` and
        :meth:`finish_qr_login`. ``on_code`` receives each issued
        ``tg://login`` URL and must marshal it to the UI thread itself (a Qt
        signal does that).
        """
        await telegram_auth.initialize()

        try:
            try:
                user = await qr_login(
                    telegram_auth.client,
                    on_code=on_code or (lambda url: None),
                    password=(lambda: password) if password else None,
                )
            except SessionPasswordNeededError as e:
                # This thread cannot prompt, so point at the field to fill in.
                raise RuntimeError(
                    "Two-step verification is enabled. Enter your password in "
                    "the Password field and scan the QR code again."
                ) from e

            telegram_auth._is_authenticated = True
            me = await telegram_auth.client.get_me()
            return {
                "username": getattr(me, "username", None)
                or getattr(user, "username", None),
                "phone": getattr(me, "phone", None) or getattr(user, "phone", None),
            }
        finally:
            # Release the session file; a download runs in another process.
            await telegram_auth.client.disconnect()

    def login_qr(self) -> None:
        """Show the QR dialog and run the login on a background thread."""
        from ..widgets.qr_dialog import QrLoginDialog

        tab = self.tab
        # Everything that reads or writes widgets happens here, on the UI
        # thread, and is handed to the worker as plain values.
        tab._update_telegram_auth()
        telegram_auth = tab.telegram_auth
        if telegram_auth is None:
            QMessageBox.critical(
                tab, "Error", "Please save your API ID and API Hash first."
            )
            return
        password = tab.password_edit.text().strip() or None

        dialog = QrLoginDialog(tab)
        self._qr_dialog = dialog
        self._qr_result = None
        tab.qr_code_issued.connect(dialog.set_code)
        self._set_ui_enabled(False)

        self._run_qr_worker(telegram_auth, password, dialog)
        dialog.exec()

    def _run_qr_worker(self, telegram_auth, password, dialog) -> None:
        """Run the QR login off the UI thread, cancellable from the dialog."""
        tab = self.tab
        # The loop and task are created before the thread starts, so Cancel can
        # always reach the task instead of leaving it to time out while it
        # holds the session file open.
        self._qr_loop = loop = asyncio.new_event_loop()
        self._qr_task = task = loop.create_task(
            self._do_qr_login_async(
                telegram_auth, password=password, on_code=tab.qr_code_issued.emit
            )
        )
        dialog.rejected.connect(lambda: loop.call_soon_threadsafe(task.cancel))

        def run_async():
            try:
                self._qr_result = loop.run_until_complete(task)
                tab.qr_login_done.emit(True, "")
            except asyncio.CancelledError:
                tab.qr_login_done.emit(False, "")
            except Exception as e:  # reported on the UI thread
                logging.error(f"QR login failed: {e}", exc_info=True)
                tab.qr_login_done.emit(False, str(e))
            finally:
                loop.close()
                self._qr_loop = None
                self._qr_task = None

        self._qr_thread = threading.Thread(target=run_async, daemon=True)
        self._qr_thread.start()

    def finish_qr_login(self, succeeded: bool, message: str) -> None:
        """Apply the outcome of a QR login. UI thread only."""
        tab = self.tab
        dialog = getattr(self, "_qr_dialog", None)
        if dialog is not None:
            try:
                tab.qr_code_issued.disconnect(dialog.set_code)
            except (RuntimeError, TypeError):
                pass
            dialog.accept() if succeeded else dialog.reject()
            self._qr_dialog = None

        self._set_ui_enabled(True)

        if not succeeded:
            if message:
                QMessageBox.critical(tab, "QR Login Failed", message)
            return

        result = self._qr_result or {}
        phone = result.get("phone")
        if phone:
            tab.config.set("settings.phone", str(phone))
            tab.config.save()
        tab.password_edit.clear()
        # _set_logged_in announces the new state to the rest of the window.
        tab._set_logged_in(True, skip_validation=True)
        QMessageBox.information(
            tab,
            "Login Successful",
            f"Logged in as {result.get('username') or phone or 'Telegram user'}",
        )

    # Login --------------------------------------------------------------
    async def _do_login_async(self) -> None:
        tab = self.tab
        logging.debug("Starting login process...")
        self._set_ui_enabled(False)
        tab.login_btn.setText("Logging in...")

        try:
            phone = tab.phone_edit.text().strip()
            code = tab.code_edit.text().strip()
            password = tab.password_edit.text().strip()

            if not phone or not code:
                error_msg = "Please enter both phone number and verification code."
                logging.error(error_msg)
                QMessageBox.critical(tab, "Error", error_msg)
                return

            logging.info(f"Attempting login with phone: {phone}")

            # If the user hasn't requested a verification code yet, the
            # `phone_code_hash` attribute will be empty. Earlier versions
            # relied on the downloader instance being present, but the
            # downloader is now closed right after sending the code to avoid
            # database locks.  We only need the phone_code_hash for signing in,
            # so check that instead of the downloader instance.
            if not getattr(tab, "phone_code_hash", None):
                error_msg = "Please request a verification code first."
                logging.error(error_msg)
                QMessageBox.critical(tab, "Error", error_msg)
                return

            try:
                tab._update_telegram_auth()

                if not hasattr(tab, "telegram_auth") or not tab.telegram_auth:
                    raise TelegramAuthError("Telegram auth not initialized")

                sign_in_kwargs = {
                    "phone": phone,
                    "code": code,
                    "password": password or None,
                }

                if hasattr(tab, "phone_code_hash") and tab.phone_code_hash:
                    sign_in_kwargs["phone_code_hash"] = tab.phone_code_hash
                    logging.info(f"Using phone_code_hash: {tab.phone_code_hash}")
                else:
                    logging.warning(
                        "No phone_code_hash found, attempting direct sign in"
                    )

                try:
                    await tab.telegram_auth.sign_in(**sign_in_kwargs)
                except TelegramAuthError as e:
                    if "password" in str(e).lower() and not password:
                        password, ok = QInputDialog.getText(
                            tab,
                            "2FA Required",
                            "Please enter your 2FA password:",
                            QLineEdit.Password,
                        )
                        if ok and password:
                            await tab.telegram_auth.sign_in(
                                phone,
                                code,
                                password,
                                phone_code_hash=sign_in_kwargs.get("phone_code_hash"),
                            )
                        else:
                            raise TelegramAuthError("2FA password is required")
                    else:
                        raise

                logging.info("Login successful")

                me = await tab.telegram_auth.client.get_me()
                name = (
                    f"{me.first_name or ''} {me.last_name or ''}".strip()
                    or me.username
                    or "Unknown"
                )
                username = getattr(me, "username", "no_username")

                tab._set_logged_in(True)

                QMessageBox.information(
                    tab,
                    "Login Successful",
                    f"Successfully logged in as {name} (@{username})",
                )

                tab.config.set("settings.phone", phone)
                tab.config.save()

                await tab.telegram_auth.client.disconnect()

                await tab._validate_session_async()

                tab.auth_state_changed.emit(True)

            except TelegramAuthError as e:
                raise

            except Exception as e:
                logging.error(f"Login error: {e}", exc_info=True)
                raise TelegramAuthError(f"Login failed: {str(e)}")

        except TelegramAuthError as e:
            logging.error(f"Authentication error: {e}")
            QMessageBox.critical(tab, "Login Error", f"Failed to login: {str(e)}")

        except Exception as e:
            logging.error(f"Unexpected error during login: {e}", exc_info=True)
            QMessageBox.critical(
                tab,
                "Error",
                f"An unexpected error occurred: {str(e)}",
            )

        finally:
            logging.debug("Login process completed, resetting UI")
            self._set_ui_enabled(True)
            tab.login_btn.setText("Login")

    def login(self) -> None:
        tab = self.tab
        logging.debug("Login button clicked")
        try:
            loop = asyncio.get_event_loop()
            logging.debug(f"Got existing event loop: {loop}")
            if not loop.is_running():
                logging.debug("Event loop is not running, creating a new one")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                logging.debug(f"Created new event loop: {loop}")
                try:
                    logging.debug("Running event loop with login task")
                    task = loop.create_task(self._do_login_async())
                    task.add_done_callback(tab._handle_async_exception)
                    loop.run_until_complete(task)
                except Exception as e:
                    logging.error(f"Error in login task: {e}", exc_info=True)
                    QMessageBox.critical(tab, "Error", f"Login failed: {str(e)}")
            else:
                task = loop.create_task(self._do_login_async())
                task.add_done_callback(tab._handle_async_exception)
        finally:
            tab.login_btn.setEnabled(True)
            tab.login_btn.setText("Login")

    # Logout -------------------------------------------------------------
    async def _do_logout_async(self) -> None:
        tab = self.tab
        try:
            session_path = Path(
                tab.config.get("session_path", get_app_dir() / "session.session")
            )
            telegram_auth = getattr(tab, "telegram_auth", None)

            if telegram_auth is None:
                api_id = tab.config.get("settings.api_id")
                api_hash = tab.config.get("settings.api_hash")
                if api_id and api_hash:
                    proxy_url = tab.config.get("settings.proxy_url") or None
                    telegram_auth = TelegramAuth(
                        api_id=int(api_id),
                        api_hash=api_hash,
                        session_path=session_path,
                        proxy_url=proxy_url,
                    )
                    try:
                        await telegram_auth.initialize()
                    except Exception:
                        telegram_auth = None

            if telegram_auth:
                await telegram_auth.logout_and_cleanup(session_path)
                if telegram_auth is tab.telegram_auth:
                    tab.telegram_auth = None
            elif session_path.exists():
                session_path.unlink()
            tab._set_logged_in(False, show_login=True)
            QMessageBox.information(
                tab, "Logged Out", "You have been logged out successfully."
            )
        except Exception as e:
            logging.error(f"Error during logout: {e}")
            QMessageBox.critical(
                tab,
                "Error",
                f"Failed to log out: {e}\n\nYou may need to manually delete the session file.",
            )
            tab._set_logged_in(False, show_login=True)
        finally:
            tab.logout_btn.setText("Logout")

    def logout(self) -> None:
        tab = self.tab
        try:
            tab.logout_btn.setEnabled(False)
            tab.logout_btn.setText("Logging out...")
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._do_logout_async())
            else:
                loop.run_until_complete(self._do_logout_async())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._do_logout_async())

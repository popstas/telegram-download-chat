import asyncio
import logging
from pathlib import Path

from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox

from ...core.auth_utils import TelegramAuthError
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

            if not hasattr(tab, "downloader") or not tab.downloader:
                error_msg = "Please request a verification code first."
                logging.error(error_msg)
                QMessageBox.critical(tab, "Error", error_msg)
                return

            tab._update_telegram_auth()

            if not hasattr(tab, "telegram_auth") or not tab.telegram_auth:
                raise TelegramAuthError("Telegram auth not initialized")

            sign_in_kwargs = {
                "phone": phone,
                "code": code,
                "password": password or None,
                "phone_code_hash": getattr(tab, "phone_code_hash", None),
            }

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
                            phone=phone,
                            code=code,
                            password=password,
                            phone_code_hash=getattr(tab, "phone_code_hash", None),
                        )
                    else:
                        QMessageBox.warning(tab, "Error", "2FA password is required")
                        return
                else:
                    QMessageBox.warning(tab, "Login Error", str(e))
                    return

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

            tab.auth_state_changed.emit(True)

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
            if hasattr(tab, "telegram_auth") and tab.telegram_auth:
                try:
                    await tab.telegram_auth.logout_and_cleanup(session_path)
                finally:
                    tab.telegram_auth = None
            else:
                if session_path.exists():
                    try:
                        session_path.unlink()
                    except Exception as e:  # pragma: no cover - best effort cleanup
                        logging.warning(f"Error deleting session file: {e}")
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

import asyncio
import logging
from pathlib import Path

from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox
from telethon.errors import (
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from ...core import TelegramChatDownloader
from ...paths import get_app_dir
from ..utils.telegram_auth import TelegramAuthError


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

            try:
                tab._update_telegram_auth()

                if not hasattr(tab, "telegram_auth") or not tab.telegram_auth:
                    raise TelegramAuthError("Telegram auth not initialized")

                sign_in_kwargs = {
                    "phone": phone,
                    "code": code,
                    "password": password,
                }

                if hasattr(tab, "phone_code_hash") and tab.phone_code_hash:
                    sign_in_kwargs["phone_code_hash"] = tab.phone_code_hash
                    logging.info(f"Using phone_code_hash: {tab.phone_code_hash}")
                else:
                    logging.warning(
                        "No phone_code_hash found, attempting direct sign in"
                    )

                await tab.telegram_auth.sign_in(**sign_in_kwargs)

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

            except SessionPasswordNeededError:
                if not password:
                    password, ok = QInputDialog.getText(
                        tab,
                        "2FA Required",
                        "Please enter your 2FA password:",
                        QLineEdit.Password,
                    )
                    if ok and password:
                        await tab.telegram_auth.sign_in(phone, code, password)
                        tab._set_logged_in(True)
                        tab.auth_state_changed.emit(True)
                    else:
                        raise TelegramAuthError("2FA password is required")
                else:
                    raise

            except (
                PhoneCodeInvalidError,
                PhoneCodeExpiredError,
                PhoneCodeEmptyError,
            ):
                QMessageBox.warning(
                    tab,
                    "Error",
                    "Invalid or expired verification code. Please try again.",
                )
                tab.code_edit.clear()
                tab.code_edit.setFocus()
                return

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
            if hasattr(tab, "telegram_auth") and tab.telegram_auth:
                try:
                    logging.debug("Starting Telegram client cleanup...")
                    client = getattr(tab.telegram_auth, "client", None)
                    if client:
                        try:
                            if hasattr(client, "_sender") and client._sender:
                                if hasattr(client._sender, "_send_loop_task"):
                                    client._sender._send_loop_task.cancel()
                                if hasattr(client._sender, "_recv_loop_task"):
                                    client._sender._recv_loop_task.cancel()
                        except Exception as e:
                            logging.warning(
                                f"Error stopping client tasks (non-critical): {e}"
                            )
                        try:
                            logging.debug("Attempting graceful logout...")
                            if hasattr(tab.telegram_auth, "log_out"):
                                logged_out = await tab.telegram_auth.log_out()
                                if logged_out:
                                    logging.info(
                                        "Successfully logged out from Telegram."
                                    )
                                else:
                                    logging.debug(
                                        "Client already disconnected; skipping logout."
                                    )
                        except Exception as e:
                            logging.warning(
                                f"Error during graceful logout (non-critical): {e}"
                            )
                    try:
                        if hasattr(tab.telegram_auth, "close") and callable(
                            tab.telegram_auth.close
                        ):
                            logging.debug("Closing Telegram auth instance...")
                            await tab.telegram_auth.close()
                            logging.info("Telegram auth instance closed successfully.")
                    except Exception as e:
                        logging.warning(
                            f"Error closing Telegram auth instance (non-critical): {e}"
                        )
                except Exception as e:
                    logging.error(
                        f"Error during Telegram client cleanup: {e}", exc_info=True
                    )
                finally:
                    tab.telegram_auth = None
            await asyncio.sleep(1.0)
            if session_path.exists():
                max_attempts = 5
                for attempt in range(max_attempts):
                    try:
                        session_path.unlink()
                        logging.info(
                            f"Successfully deleted session file: {session_path}"
                        )
                        break
                    except (PermissionError, OSError) as e:
                        if attempt == max_attempts - 1:
                            logging.error(
                                f"Failed to delete session file after {max_attempts} attempts: {e}"
                            )
                            break
                        else:
                            wait_time = 0.5 * (attempt + 1)
                            logging.debug(
                                f"Retrying session file deletion in {wait_time} seconds (attempt {attempt + 1}/{max_attempts})..."
                            )
                            await asyncio.sleep(wait_time)
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

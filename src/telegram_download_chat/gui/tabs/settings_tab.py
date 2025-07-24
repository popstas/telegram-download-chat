"""Settings tab for the Telegram Download Chat GUI."""
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from telethon.errors import (
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from ...core import TelegramChatDownloader
from ...paths import get_app_dir
from ..utils.config import ConfigManager
from ..utils.telegram_auth import TelegramAuth, TelegramAuthError


class CodeRequestWorker(QObject):
    """Worker for handling code requests in a separate thread."""

    finished = Signal()
    error = Signal(str)
    code_sent = Signal(str)

    def __init__(self, telegram_auth, phone):
        super().__init__()
        self.telegram_auth = telegram_auth
        self.phone = phone

    def run(self):
        """Run the code request in a separate thread."""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def request():
                return await self.telegram_auth.request_code(self.phone)

            loop.run_until_complete(request())
            self.code_sent.emit(self.phone)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class SettingsTab(QWidget):
    """Settings tab for the Telegram Download Chat GUI."""

    # Signal emitted when the API credentials are saved
    api_credentials_saved = Signal(dict)  # settings dict

    # Signal emitted when the user logs in or out
    auth_state_changed = Signal(bool)  # is_authenticated

    def __init__(self, parent=None):
        """Initialize the settings tab.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.config = ConfigManager()
        self.telegram_auth = None
        self._setup_ui()
        self._connect_signals()
        self._load_settings()

    def _setup_ui(self):
        """Set up the user interface."""
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        # API Credentials Group
        self._setup_api_credentials_group(layout)

        # Session Management Group
        self._setup_session_group(layout)

        # Add stretch to push everything to the top
        layout.addStretch()

        session_file = get_app_dir() / "session.session"
        is_session_exists = session_file.exists()
        self._set_logged_in(is_session_exists)

    def _setup_api_credentials_group(self, parent_layout):
        """Set up the API credentials group.

        Args:
            parent_layout: Parent layout to add the group to
        """
        # API Credentials Group
        api_group = QGroupBox("Telegram API Credentials")
        api_layout = QVBoxLayout(api_group)

        # Form layout for API ID and Hash
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        try:
            # API ID
            self.api_id_edit = QLineEdit()
            self.api_id_edit.setPlaceholderText("Enter your Telegram API ID")
            form.addRow("API ID:", self.api_id_edit)

            # API Hash with show/hide button
            self.api_hash_edit = QLineEdit()
            self.api_hash_edit.setPlaceholderText("Enter your Telegram API Hash")
            self.api_hash_edit.setEchoMode(QLineEdit.Password)

            # Create a container for the hash field and button
            hash_container = QWidget()
            hash_layout = QHBoxLayout(hash_container)
            hash_layout.setContentsMargins(0, 0, 0, 0)
            hash_layout.setSpacing(5)

            # Add hash field (expands) and button to container
            hash_layout.addWidget(self.api_hash_edit, 1)

            # Show/hide password button
            self.show_password_btn = QPushButton()
            # Use the correct enum value for the icon
            from PySide6.QtWidgets import QStyle

            self.show_password_btn.setIcon(
                self.style().standardIcon(
                    QStyle.StandardPixmap.SP_FileDialogDetailedView
                )
            )
            self.show_password_btn.setToolTip("Show/Hide API Hash")
            self.show_password_btn.setCheckable(True)
            self.show_password_btn.setFixedSize(24, 24)
            self.show_password_btn.setStyleSheet(
                """
                QPushButton {
                    border: none;
                    padding: 0;
                    background: transparent;
                }
                QPushButton:hover {
                    background: #f0f0f0;
                    border-radius: 3px;
                }
            """
            )

            # Connect the button
            self.show_password_btn.toggled.connect(self._toggle_password_visibility)

            # Add button to container
            hash_layout.addWidget(self.show_password_btn)

            # Add the container to the form
            form.addRow("API Hash:", hash_container)

            # Add form to API layout
            api_layout.addLayout(form)

        except Exception as e:
            logging.error(f"Error setting up API credentials group: {e}")
            error_label = QLabel(f"Error setting up API credentials: {str(e)}")
            error_label.setStyleSheet("color: red;")
            api_layout.addWidget(error_label)

        # Save button
        self.save_btn = QPushButton("Save API Credentials")
        self.save_btn.setStyleSheet(
            """
            QPushButton {
                padding: 8px 16px;
                font-weight: bold;
            }
        """
        )
        api_layout.addWidget(self.save_btn)

        # Help text
        help_text = (
            "<p>To get your API credentials:</p>"
            "<ol style='margin-top: 0; padding-left: 20px;'>"
            "<li>Don't use VPN while creating the app</li>"
            "<li>Login to <a href='https://my.telegram.org/apps'>my.telegram.org/apps</a> with your phone number</li>"
            "<li>Go to 'API development tools, create a new application</li>"
            "<li>Use only small letters for application name, select Desktop app</li>"
            "<li>Copy the API ID and API Hash</li>"
            "</ol>"
        )

        help_label = QLabel(help_text)
        help_label.setOpenExternalLinks(True)
        help_label.setWordWrap(True)
        help_label.setStyleSheet("margin: 5px 0;")
        api_layout.addWidget(help_label)

        # Add API group to parent layout
        parent_layout.addWidget(api_group)

        # Add a separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("margin: 10px 0;")
        parent_layout.addWidget(line)

    def _setup_session_group(self, parent_layout):
        """Set up the session management group."""
        # Session Management Group
        session_group = QGroupBox("Telegram Session")
        session_group.setStyleSheet("QGroupBox { margin-top: 5px; }")
        session_layout = QVBoxLayout(session_group)
        session_layout.setContentsMargins(5, 15, 5, 5)
        session_layout.setSpacing(10)

        # Login form (shown when not logged in)
        self.login_group = QGroupBox()
        self.login_group.setTitle("Login to Telegram")
        self.login_group.setStyleSheet("QGroupBox { margin-top: 5px; }")
        login_form = QFormLayout(self.login_group)
        login_form.setContentsMargins(5, 15, 5, 5)
        login_form.setSpacing(10)

        # Phone number
        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("+1234567890")

        # Get code button
        self.get_code_btn = QPushButton("Get Code")
        self.get_code_btn.setEnabled(False)

        # Phone layout
        phone_layout = QHBoxLayout()
        phone_layout.addWidget(self.phone_edit)
        phone_layout.addWidget(self.get_code_btn)
        login_form.addRow("Phone:", phone_layout)

        # Code input
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Enter the code from Telegram")
        login_form.addRow("Code:", self.code_edit)

        # Password (for 2FA)
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Enter your cloud password (if any)")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.returnPressed.connect(
            self._do_login
        )  # Add Enter key support
        login_form.addRow("Password:", self.password_edit)

        # Login button
        self.login_btn = QPushButton("Login")
        self.login_btn.setEnabled(False)
        login_form.addRow(self.login_btn)

        # Add login form to session layout
        session_layout.addWidget(self.login_group)

        # Logged in status (shown when logged in)
        self.logged_in_group = QGroupBox()
        self.logged_in_group.setTitle("Session Status")
        self.logged_in_group.setStyleSheet("QGroupBox { margin-top: 15px; }")
        logged_in_layout = QVBoxLayout(self.logged_in_group)
        logged_in_layout.setContentsMargins(5, 15, 5, 5)
        logged_in_layout.setSpacing(10)

        # Status label
        self.status_label = QLabel("You are logged in.")
        logged_in_layout.addWidget(self.status_label)

        # Logout button
        self.logout_btn = QPushButton("Logout")
        self.logout_btn.setStyleSheet(
            """
            QPushButton {
                padding: 8px 16px;
                font-weight: bold;
                color: #f44336;
            }
        """
        )
        logged_in_layout.addWidget(self.logout_btn)

        # Add logged in group to session layout (initially hidden)
        session_layout.addWidget(self.logged_in_group)
        self.logged_in_group.setVisible(False)

        # Add session group to parent layout
        parent_layout.addWidget(session_group)

    def _connect_signals(self):
        """Connect signals to slots."""
        # API Credentials
        self.save_btn.clicked.connect(self._save_api_credentials)
        self.show_password_btn.toggled.connect(self._toggle_password_visibility)

        # Login
        self.phone_edit.textChanged.connect(self._update_login_button_state)
        self.code_edit.textChanged.connect(self._update_login_button_state)
        self.get_code_btn.clicked.connect(self._request_code)
        self.login_btn.clicked.connect(self._do_login)

        # Logout
        self.logout_btn.clicked.connect(self._do_logout)

    def _load_settings(self):
        """Load settings from config and check session status."""
        try:
            self.config.load()

            session_file = get_app_dir() / "session.session"
            is_session_exists = session_file.exists()
            self._set_logged_in(is_session_exists, skip_validation=True)
            if not self.config.get("session_path", ""):
                self.config.set("session_path", str(session_file))
            # Safely load API credentials if widgets exist
            if hasattr(self, "api_id_edit") and self.api_id_edit is not None:
                api_id = self.config.get("settings.api_id", "")
                self.api_id_edit.setText(str(api_id))

            if hasattr(self, "api_hash_edit") and self.api_hash_edit is not None:
                api_hash = self.config.get("settings.api_hash", "")
                self.api_hash_edit.setText(str(api_hash))

            # Load phone number if available and widget exists
            if hasattr(self, "phone_edit") and self.phone_edit is not None:
                phone = self.config.get("settings.phone", "")
                self.phone_edit.setText(phone)

            # Check if we have a valid session
            self._check_session_status()

        except Exception as e:
            logging.error(f"Error loading settings: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load settings: {e}")

    def _check_session_status(self):
        """Check if we have a valid session and update UI accordingly."""
        # First check if we have API credentials
        if not (self.api_id_edit.text() and self.api_hash_edit.text()):
            self._set_logged_in(False, show_login=True)
            return

        # Then check if we have a session path
        session_path = self.config.get(
            "session_path", get_app_dir() / "session.session"
        )
        if not session_path:
            self._set_logged_in(False, show_login=True)
            return

        # Check if session file exists
        session_file = Path(session_path)
        if not session_file.exists():
            self._set_logged_in(False, show_login=True)
            return

        # If we got here, we have credentials and a session file
        # Try to validate the session asynchronously
        try:
            # Get or create the event loop
            loop = asyncio.get_event_loop()
            # Schedule the validation task
            loop.create_task(self._validate_session_async())
        except RuntimeError as e:
            if "no running event loop" in str(e):
                # If no event loop is running, create a new one and run the task
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.create_task(self._validate_session_async())
            else:
                # For other errors, log and show error
                logging.error(f"Error scheduling session validation: {e}")
                self._set_logged_in(False, show_login=True)

    async def _validate_session_async(self):
        """Asynchronously validate the Telegram session."""
        try:
            # First ensure we have valid API credentials
            if not (self.api_id_edit.text() and self.api_hash_edit.text()):
                self._set_logged_in(False, show_login=True)
                return

            # Initialize or update the Telegram auth instance
            self._update_telegram_auth()
            if not self.telegram_auth:
                self._set_logged_in(False, show_login=True)
                return

            # Try to connect and validate the session
            try:
                await self.telegram_auth.initialize()
                is_valid = await self.telegram_auth.client.is_user_authorized()

                # Update UI based on validation result
                if is_valid:
                    # Successfully validated session
                    self._set_logged_in(True, skip_validation=True)
                else:
                    # Session exists but is not authorized - show login
                    self._set_logged_in(False, show_login=True)

            except Exception as auth_error:
                logging.error(f"Session validation error: {auth_error}")
                # If we can't validate (e.g., network issue), keep current UI state
                # but show an error message
                self.status_label.setText(
                    f"Error validating session: {str(auth_error)}\n"
                    "Please check your connection and try again."
                )

        except Exception as e:
            logging.error(f"Unexpected error during session validation: {e}")
            # On any unexpected error, show login form
            self._set_logged_in(False, show_login=True)

    def _validate_session(self):
        """Start session validation in a background task."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        task = loop.create_task(self._validate_session_async())
        task.add_done_callback(self._handle_async_exception)

    def _save_api_credentials(self):
        """Save API credentials to config."""
        api_id = self.api_id_edit.text().strip()
        api_hash = self.api_hash_edit.text().strip()

        if not api_id or not api_hash:
            QMessageBox.warning(self, "Error", "Please enter both API ID and API Hash.")
            return

        try:
            # Validate API ID is a number
            int(api_id)
        except ValueError:
            QMessageBox.warning(self, "Error", "API ID must be a number.")
            return

        # Save to config
        self.config.set("settings.api_id", api_id)
        self.config.set("settings.api_hash", api_hash)
        self.config.save()

        # Update the Telegram auth instance
        self._update_telegram_auth()

        QMessageBox.information(self, "Success", "API credentials saved successfully!")

        # Emit signal
        self.api_credentials_saved.emit({"api_id": api_id, "api_hash": api_hash})

    def _toggle_password_visibility(self, checked: bool):
        """Toggle password visibility.

        Args:
            checked: Whether to show the password
        """
        if checked:
            self.api_hash_edit.setEchoMode(QLineEdit.Normal)
            self.show_password_btn.setIcon(QIcon.fromTheme("visibility-off"))
        else:
            self.api_hash_edit.setEchoMode(QLineEdit.Password)
            self.show_password_btn.setIcon(QIcon.fromTheme("visibility"))

    def _update_login_button_state(self):
        """Update the state of the login button based on input."""
        phone = self.phone_edit.text().strip()
        code = self.code_edit.text().strip()

        # Enable/disable get code button based on phone number
        self.get_code_btn.setEnabled(bool(phone))

        # Enable login button if we have both phone and code, regardless of password
        self.login_btn.setEnabled(bool(phone) and bool(code))

    def _update_telegram_auth(self):
        """Update the Telegram auth instance with current credentials."""
        api_id = self.api_id_edit.text().strip()
        api_hash = self.api_hash_edit.text().strip()

        if not api_id or not api_hash:
            return

        # Create or update the Telegram auth instance
        session_path = Path(self.config.get("session_path", ""))
        if not session_path:
            from telegram_download_chat.paths import get_app_dir

            session_path = get_app_dir() / "session.session"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            self.config.set("session_path", str(session_path))

        self.telegram_auth = TelegramAuth(
            api_id=int(api_id), api_hash=api_hash, session_path=session_path
        )

    async def _request_code_async(self, phone):
        """Send the code request to Telegram using TelegramChatDownloader.

        This method handles the entire code request flow including validation,
        error handling, and UI updates.
        """
        logging.debug("Starting _request_code_async method")

        # Get credentials and phone number
        api_id = self.api_id_edit.text().strip()
        api_hash = self.api_hash_edit.text().strip()

        logging.debug(
            f"Using API ID: {api_id}, API Hash: {'*' * 8 + api_hash[-4:] if api_hash else 'None'}"
        )

        try:
            # Validate inputs
            if not all([api_id, api_hash]):
                error_msg = "API ID and API Hash are required"
                logging.error(error_msg)
                raise ValueError(error_msg)
            if not phone:
                error_msg = "Phone number is required"
                logging.error(error_msg)
                raise ValueError(error_msg)

            logging.debug("Creating TelegramChatDownloader instance")
            try:
                self.downloader = TelegramChatDownloader()
                logging.debug("TelegramChatDownloader instance created successfully")
            except Exception as e:
                error_msg = f"Failed to create TelegramChatDownloader: {str(e)}"
                logging.error(error_msg, exc_info=True)
                raise

            logging.debug("Initiating Telegram connection...")
            try:
                # Store the phone_code_hash from the downloader's client
                await self.downloader.connect(phone)
                # Get the phone_code_hash from the downloader's client
                if hasattr(self.downloader, "client") and hasattr(
                    self.downloader.client, "phone_code_hash"
                ):
                    self.phone_code_hash = self.downloader.client.phone_code_hash
                else:
                    self.phone_code_hash = getattr(
                        self.downloader, "phone_code_hash", None
                    )

                if not self.phone_code_hash:
                    logging.warning("No phone_code_hash received from downloader")
                else:
                    logging.info(
                        f"Successfully connected to Telegram, phone_code_hash: {self.phone_code_hash}"
                    )
            except Exception as e:
                error_msg = f"Failed to connect to Telegram: {str(e)}"
                logging.error(error_msg, exc_info=True)
                raise

            # Save phone number to config
            try:
                self.config.set("settings.phone", phone)
                self.config.save()
                logging.debug(f"Saved phone number to config: {phone}")
            except Exception as e:
                error_msg = f"Failed to save phone number to config: {str(e)}"
                logging.error(error_msg, exc_info=True)
                # Don't raise, as this isn't critical for the login flow

            logging.info("Verification code request completed successfully")
            logging.info(f"Successfully requested verification code for {phone}")
            return True

        except Exception as e:
            logging.error(f"Error in _request_code_async: {str(e)}", exc_info=True)
            # Re-raise the exception to be handled by the done callback
            raise

    def _request_code(self):
        """Request a login code from Telegram."""
        logging.debug("Get Code button clicked")
        try:
            # Get phone number and validate
            phone = self.phone_edit.text().strip()
            if not phone:
                error_msg = "Phone number is empty"
                logging.warning(error_msg)
                QMessageBox.warning(
                    self, "Error", "Please enter your phone number first."
                )
                return

            logging.debug(f"Starting code request for phone: {phone}")

            # Disable UI elements during code request
            self.phone_edit.setEnabled(False)
            self.code_edit.clear()
            self.login_btn.setEnabled(False)
            self.get_code_btn.setEnabled(False)
            self.get_code_btn.setText("Sending...")

            # Show loading state
            status_msg = f"Sending verification code to {phone}..."
            logging.debug(status_msg)
            if hasattr(self, "log_view"):
                self.log_view.append(status_msg)

            # Create a new task in the default executor to run the async code
            def run_async():
                loop = None
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    # Create a future to track the task
                    future = loop.create_future()

                    # Create and run the task
                    async def run_task():
                        try:
                            result = await self._request_code_async(phone)
                            future.set_result(result)
                        except Exception as e:
                            future.set_exception(e)

                    task = loop.create_task(run_task())

                    # Set up a timeout
                    def handle_timeout():
                        if not future.done():
                            future.set_exception(
                                TimeoutError("Request timed out after 60 seconds")
                            )

                    loop.call_later(60, handle_timeout)

                    # Run the loop until the future is done
                    loop.run_until_complete(future)

                    # Get the result or exception
                    try:
                        result = future.result()
                        # Schedule the callback on the main thread
                        QTimer.singleShot(
                            0, lambda: self._on_code_request_done(future, phone)
                        )
                    except Exception as e:
                        logging.error(f"Error in async task: {e}", exc_info=True)
                        QTimer.singleShot(0, lambda: self._on_code_error(str(e)))

                except Exception as e:
                    logging.error(f"Error in run_async: {e}", exc_info=True)
                    QTimer.singleShot(0, lambda: self._on_code_error(str(e)))
                finally:
                    if loop is not None:
                        loop.close()

            # Start the async task in a separate thread
            import threading

            thread = threading.Thread(target=run_async, daemon=True)
            thread.start()
        except Exception as e:
            error_msg = f"Failed to start code request: {str(e)}"
            logging.error(error_msg, exc_info=True)
            if hasattr(self, "log_view"):
                self.log_view.append(error_msg)
            QMessageBox.critical(self, "Error", error_msg)
            # Reset UI on error
            self.phone_edit.setEnabled(True)
            self.get_code_btn.setEnabled(True)
            self.get_code_btn.setText("Get Code")

    def _on_code_error(self, error_msg):
        """Handle errors during code request.

        Args:
            error_msg: Error message to display
        """
        logging.error(f"Code request error: {error_msg}")
        if hasattr(self, "log_view"):
            self.log_view.append(f"Error: {error_msg}")

        # Re-enable UI elements
        self.phone_edit.setEnabled(True)
        self.get_code_btn.setEnabled(True)
        self.get_code_btn.setText("Get Code")

        # Show error message
        QMessageBox.critical(
            self, "Error", f"Failed to request verification code: {error_msg}"
        )

    def _on_code_request_done(self, future, phone):
        """Handle completion of the code request.

        Args:
            future: The future that completed
            phone: The phone number the code was sent to
        """
        try:
            # Update UI first to show success state
            success_msg = (
                f"Verification code sent to {phone}. Please check your messages."
            )
            if hasattr(self, "log_view"):
                self.log_view.append(success_msg)
            logging.info(success_msg)

            # Update UI
            self.code_edit.setFocus()
            self.phone_edit.setEnabled(True)
            self.get_code_btn.setEnabled(True)
            self.get_code_btn.setText("Get Code")
            self.login_btn.setEnabled(True)
            self.get_code_btn.setText("Resend Code")

            # Save phone number
            self.config.set("settings.phone", phone)
            self.config.save()

            # Show success message
            QMessageBox.information(self, "Code Sent", success_msg)

        except asyncio.CancelledError:
            self.log_view.append("Code request was cancelled")

        except TelegramAuthError as e:
            error_msg = f"Failed to send code: {str(e)}"
            self.log_view.append(error_msg)
            QMessageBox.critical(self, "Error", error_msg)

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self.log_view.append(error_msg)
            QMessageBox.critical(
                self, "Error", f"An unexpected error occurred: {str(e)}"
            )

        finally:
            # Always re-enable UI elements
            self.phone_edit.setEnabled(True)
            self.get_code_btn.setEnabled(True)
            self.get_code_btn.setText("Get Code")

    def _on_code_sent(self, phone):
        """Handle successful code sending (legacy)."""
        self.log_view.append(f"Verification code sent to {phone}")
        self.get_code_btn.setEnabled(True)
        self.get_code_btn.setText("Resend Code")
        self._update_login_button_state()

    def _on_code_error(self, error_msg):
        """Handle errors during code request."""
        QMessageBox.critical(self, "Error", f"Failed to request code: {error_msg}")

        # Re-enable the button
        self.get_code_btn.setEnabled(True)
        self.get_code_btn.setText("Get Code")

    def _handle_async_exception(self, task):
        """Handle exceptions from async tasks."""
        try:
            # This will re-raise any exception that occurred in the task
            task.result()
        except Exception as e:
            logging.error(f"Error in async task: {e}")
            # Show error in the UI
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")

    def _set_ui_enabled(self, enabled: bool):
        """Enable or disable UI elements during operations.

        Args:
            enabled: Whether to enable the UI elements
        """
        self.phone_edit.setEnabled(enabled)
        self.code_edit.setEnabled(enabled)
        self.password_edit.setEnabled(enabled)
        self.get_code_btn.setEnabled(enabled)
        self.login_btn.setEnabled(enabled)
        self.logout_btn.setEnabled(enabled)

    async def _do_login_async(self):
        """Handle the login process asynchronously using TelegramChatDownloader."""
        logging.debug("Starting login process...")
        self._set_ui_enabled(False)
        self.login_btn.setText("Logging in...")

        try:
            # Get credentials from UI
            phone = self.phone_edit.text().strip()
            code = self.code_edit.text().strip()
            password = self.password_edit.text().strip()

            if not phone or not code:
                error_msg = "Please enter both phone number and verification code."
                logging.error(error_msg)
                QMessageBox.critical(self, "Error", error_msg)
                return

            logging.info(f"Attempting login with phone: {phone}")

            # Ensure we have a downloader instance
            if not hasattr(self, "downloader") or not self.downloader:
                error_msg = "Please request a verification code first."
                logging.error(error_msg)
                QMessageBox.critical(self, "Error", error_msg)
                return

            try:
                # Update the Telegram auth instance with current credentials
                self._update_telegram_auth()

                # Get the Telegram auth instance
                if not hasattr(self, "telegram_auth") or not self.telegram_auth:
                    raise TelegramAuthError("Telegram auth not initialized")

                # Complete the login with the code and phone_code_hash
                try:
                    sign_in_kwargs = {
                        "phone": phone,
                        "code": code,
                        "password": password,
                    }

                    # If we have a phone_code_hash, use it
                    if hasattr(self, "phone_code_hash") and self.phone_code_hash:
                        sign_in_kwargs["phone_code_hash"] = self.phone_code_hash
                        logging.info(f"Using phone_code_hash: {self.phone_code_hash}")
                    else:
                        logging.warning(
                            "No phone_code_hash found, attempting direct sign in"
                        )

                    # Call sign_in with the appropriate arguments
                    await self.telegram_auth.sign_in(**sign_in_kwargs)

                except Exception as e:
                    logging.error(f"Error during sign in: {e}", exc_info=True)
                    raise

                # If we get here, login was successful
                logging.info("Login successful")

                # Get user info
                me = await self.telegram_auth.client.get_me()
                name = (
                    f"{me.first_name or ''} {me.last_name or ''}".strip()
                    or me.username
                    or "Unknown"
                )
                username = getattr(me, "username", "no_username")

                # Update UI
                self._set_logged_in(True)

                # Show success message
                QMessageBox.information(
                    self,
                    "Login Successful",
                    f"Successfully logged in as {name} (@{username})",
                )

                # Save phone number in settings
                self.config.set("settings.phone", phone)
                self.config.save()

                await self.telegram_auth.client.disconnect()

                # Notify parent
                self.auth_state_changed.emit(True)

            except SessionPasswordNeededError:
                # Ask for 2FA password if not provided
                if not password:
                    password, ok = QInputDialog.getText(
                        self,
                        "2FA Required",
                        "Please enter your 2FA password:",
                        QLineEdit.Password,
                    )
                    if ok and password:
                        # Retry with password
                        await self.telegram_auth.sign_in(phone, code, password)
                        self._set_logged_in(True)
                        self.auth_state_changed.emit(True)
                    else:
                        raise TelegramAuthError("2FA password is required")
                else:
                    raise

            except (
                PhoneCodeInvalidError,
                PhoneCodeExpiredError,
                PhoneCodeEmptyError,
            ) as e:
                QMessageBox.warning(
                    self,
                    "Error",
                    "Invalid or expired verification code. Please try again.",
                )
                self.code_edit.clear()
                self.code_edit.setFocus()
                return

            except TelegramAuthError as e:
                raise

            except Exception as e:
                logging.error(f"Login error: {e}", exc_info=True)
                raise TelegramAuthError(f"Login failed: {str(e)}")

        except TelegramAuthError as e:
            logging.error(f"Authentication error: {e}")
            QMessageBox.critical(self, "Login Error", f"Failed to login: {str(e)}")

        except Exception as e:
            logging.error(f"Unexpected error during login: {e}", exc_info=True)
            QMessageBox.critical(
                self, "Error", f"An unexpected error occurred: {str(e)}"
            )

        finally:
            # Always re-enable UI
            logging.debug("Login process completed, resetting UI")
            self._set_ui_enabled(True)
            self.login_btn.setText("Login")

    def _do_login(self):
        """Perform the login by starting an async task."""
        logging.debug("Login button clicked")

        # Check if we have a running event loop
        try:
            loop = asyncio.get_event_loop()
            logging.debug(f"Got existing event loop: {loop}")

            # If the loop is not running, we need to run it
            if not loop.is_running():
                logging.debug("Event loop is not running, creating a new one")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                logging.debug(f"Created new event loop: {loop}")

                # Run the loop with our task
                try:
                    logging.debug("Running event loop with login task")
                    task = loop.create_task(self._do_login_async())
                    task.add_done_callback(self._handle_async_exception)
                    loop.run_until_complete(task)
                except Exception as e:
                    logging.error(f"Error in login task: {e}", exc_info=True)
                    QMessageBox.critical(self, "Error", f"Login failed: {str(e)}")
            QMessageBox.critical(self, "Error", f"Login failed: {str(e)}")
        finally:
            # Ensure UI is in a consistent state
            self.login_btn.setEnabled(True)
            self.login_btn.setText("Login")

    async def _do_logout_async(self):
        """Log out from Telegram (async)."""
        try:
            # Disable UI during logout
            self.logout_btn.setEnabled(False)
            self.logout_btn.setText("Logging out...")

            # Get session path before we close the client
            session_path = Path(
                self.config.get("session_path", get_app_dir() / "session.session")
            )

            # If we have an active Telegram client, log out and close it
            if hasattr(self, "telegram_auth") and self.telegram_auth:
                try:
                    logging.debug("Starting Telegram client cleanup...")

                    # Get the client instance if it exists
                    client = getattr(self.telegram_auth, "client", None)

                    if client:
                        # 1. First try to stop any ongoing operations
                        try:
                            if hasattr(client, "_sender") and client._sender:
                                # Stop the sender's receive loop
                                if hasattr(client._sender, "_send_loop_task"):
                                    client._sender._send_loop_task.cancel()
                                if hasattr(client._sender, "_recv_loop_task"):
                                    client._sender._recv_loop_task.cancel()
                        except Exception as e:
                            logging.warning(
                                f"Error stopping client tasks (non-critical): {e}"
                            )

                        # 2. Try to log out gracefully
                        try:
                            logging.debug("Attempting graceful logout...")
                            if hasattr(self.telegram_auth, "log_out"):
                                await self.telegram_auth.log_out()
                                logging.info("Successfully logged out from Telegram.")
                        except Exception as e:
                            logging.warning(
                                f"Error during graceful logout (non-critical): {e}"
                            )

                    # 3. Close the telegram_auth instance (also disconnects)
                    try:
                        if hasattr(self.telegram_auth, "close") and callable(
                            self.telegram_auth.close
                        ):
                            logging.debug("Closing Telegram auth instance...")
                            await self.telegram_auth.close()
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
                    # Clear the reference in any case
                    self.telegram_auth = None

            # Give the system some time to release file handles
            await asyncio.sleep(1.0)

            # Try to delete the session file with multiple attempts
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
                        if attempt == max_attempts - 1:  # Last attempt
                            logging.error(
                                f"Failed to delete session file after {max_attempts} attempts: {e}"
                            )
                            # Don't raise, just continue with logout
                            break
                        else:
                            # Wait longer between each attempt
                            wait_time = 0.5 * (attempt + 1)
                            logging.debug(
                                f"Retrying session file deletion in {wait_time} seconds (attempt {attempt + 1}/{max_attempts})..."
                            )
                            await asyncio.sleep(wait_time)

            # Update UI to show login form
            self._set_logged_in(False, show_login=True)

            QMessageBox.information(
                self, "Logged Out", "You have been logged out successfully."
            )
        except Exception as e:
            logging.error(f"Error during logout: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to log out: {e}\n\n"
                "You may need to manually delete the session file.",
            )
            # Still try to show login form even if logout failed
            self._set_logged_in(False, show_login=True)
        finally:
            # Ensure UI is in a consistent state
            self.logout_btn.setText("Logout")

    def _do_logout(self):
        """Log out from Telegram by starting the async logout process."""
        try:
            # Get the current event loop or create a new one if none exists
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, create a task
                loop.create_task(self._do_logout_async())
            else:
                # If loop is not running, run it until complete
                loop.run_until_complete(self._do_logout_async())
        except RuntimeError:
            # If no event loop exists, create one and run it
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._do_logout_async())

    def _set_logged_in(
        self, logged_in: bool, skip_validation: bool = False, show_login: bool = False
    ):
        """Update the UI based on login state.

        Args:
            logged_in: Whether the user is currently logged in
            skip_validation: If True, skip session validation
            show_login: If True, force show the login UI
        """
        # Force show login UI if requested
        if show_login:
            self.login_group.setVisible(True)
            self.logged_in_group.setVisible(False)

            # Enable all login-related fields
            self.phone_edit.setEnabled(True)
            self.code_edit.setEnabled(True)
            self.password_edit.setEnabled(True)
            self.get_code_btn.setEnabled(True)
            self.login_btn.setEnabled(False)  # Will be enabled when code is entered

            # Clear any sensitive data
            self.code_edit.clear()
            self.password_edit.clear()
            self.status_label.setText("Please log in to Telegram")
            return

        # Handle normal login state
        self.login_group.setVisible(not logged_in)
        self.logged_in_group.setVisible(logged_in)

        if logged_in:
            # Clear sensitive fields
            self.code_edit.clear()
            self.password_edit.clear()

            # Get session info
            phone = self.phone_edit.text().strip() or self.config.get(
                "settings.phone", ""
            )
            session_path = self.config.get(
                "session_path", get_app_dir() / "session.session"
            )
            session_name = (
                Path(session_path).name if session_path else "Unknown session"
            )

            # Show loading state while validating
            if not skip_validation:
                self.status_label.setText("Validating session...")
                self.logout_btn.setEnabled(False)
                return

            # Update status with session info
            self.status_label.setText(
                f"You are logged in as {phone or 'Unknown'}\n"
                f"Session: {session_name}"
            )
            self.logout_btn.setEnabled(True)

            # Save session path if available
            if (
                not session_path
                and hasattr(self, "telegram_auth")
                and self.telegram_auth
            ):
                self.config.set("session_path", self.telegram_auth.session_path)
                self.config.save()
        else:
            # Clear session data on logout
            if hasattr(self, "telegram_auth") and self.telegram_auth:
                self.telegram_auth = None
            self.status_label.setText("Not logged in")
            self.logout_btn.setEnabled(False)

    def save_settings(self, settings: Dict[str, Any]):
        """Save tab settings to a dictionary.

        Args:
            settings: Dictionary to save settings to
        """
        settings["api_id"] = self.api_id_edit.text()
        settings["api_hash"] = self.api_hash_edit.text()
        settings["phone"] = self.phone_edit.text()

    def load_settings(self, settings: Dict[str, Any]):
        """Load tab settings from a dictionary.

        Args:
            settings: Dictionary containing settings
        """
        self.api_id_edit.setText(settings.get("api_id", ""))
        self.api_hash_edit.setText(settings.get("api_hash", ""))
        self.phone_edit.setText(settings.get("phone", ""))

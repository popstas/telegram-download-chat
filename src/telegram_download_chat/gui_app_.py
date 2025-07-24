# gui_app.py
#!/usr/bin/env python3
"""
GUI for telegram-download-chat
"""
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from functools import partial
from pathlib import Path
from urllib.parse import urlparse

import qasync
import yaml
from PySide6.QtCore import (
    QAbstractItemModel,
    QDate,
    QModelIndex,
    QSettings,
    QSize,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtGui import (
    QIcon,
    QKeySequence,
    QShortcut,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QTabWidget,
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from telethon.errors import (
    FloodWaitError,
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    PhoneNumberUnoccupiedError,
    RPCError,
    SessionPasswordNeededError,
)

from telegram_download_chat.cli import parse_args
from telegram_download_chat.core import TelegramChatDownloader
from telegram_download_chat.paths import (
    ensure_app_dirs,
    get_app_dir,
    get_default_config_path,
)


class WorkerThread(QThread):
    log = Signal(str)
    progress = Signal(int, int)  # current, maximum
    finished = Signal(list, bool)  # files, was_stopped_by_user

    def __init__(self, cmd_args, output_dir):
        super().__init__()
        self.cmd = cmd_args
        self.output_dir = output_dir
        self.current_max = 1000  # Initial maximum value
        self._is_running = True
        self._stopped_by_user = False
        self.process = None
        self._stop_file = None  # Path to stop file for inter-process communication

    def stop(self):
        self._is_running = False
        self._stopped_by_user = True
        if self.process:
            # Create a stop file to signal the process to stop gracefully
            if not self._stop_file:
                import tempfile

                self._stop_file = (
                    Path(tempfile.gettempdir()) / "telegram_download_stop.tmp"
                )
            try:
                self._stop_file.touch()
                self.log.emit("\nSending graceful shutdown signal...")
            except Exception:
                # Fallback to terminate if stop file creation fails
                self.process.terminate()

    def _update_progress(self, current):
        # Dynamically adjust maximum value based on current progress
        new_max = self.current_max
        if current > self.current_max:
            if current <= 10000:
                new_max = 10000
            elif current <= 50000:
                new_max = 50000
            elif current <= 100000:
                new_max = 100000
            else:
                new_max = (current // 100000 + 1) * 100000

            if new_max != self.current_max:
                self.current_max = new_max

        self.progress.emit(current, self.current_max)

    def run(self):
        files = []
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")

        self.process = subprocess.Popen(
            self.cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            env=env,
        )

        while self.process.poll() is None:
            line = self.process.stdout.readline()
            if not line:
                break

            line = line.rstrip()
            self.log.emit(line)

            # Parse progress from log lines like "2025-06-02 01:08:27,030 - INFO - Fetched: 100 (batch: 100 new)"
            if "Fetched: " in line:
                try:
                    # Extract the part after "Fetched: " and before any space or parenthesis
                    fetched_part = line.split("Fetched: ")[1].split()[0]
                    current = int(fetched_part)
                    self._update_progress(current)
                except (IndexError, ValueError):
                    pass

        # If we broke out of the loop because stop was requested
        if not self._is_running and self.process.poll() is None:
            # Wait for the process to stop
            self.process.wait()

        # after completion, collect files in output_dir
        p = Path(self.output_dir)
        if p.exists():
            # Get list of files with full paths
            all_files = [
                f
                for f in p.iterdir()
                if f.is_file() and f.suffix.lower() in (".txt", ".json")
            ]
            # Sort by modification time, newest first
            for f in sorted(all_files, key=lambda x: x.stat().st_mtime, reverse=True):
                files.append(str(f.absolute()))

        # Clean up stop file if it exists
        if self._stop_file and self._stop_file.exists():
            try:
                self._stop_file.unlink()
            except Exception:
                pass

        self.finished.emit(files, self._stopped_by_user)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Download Chat GUI")
        self.resize(800, 600)
        self.config = {"settings": {}}
        self.downloader = None

        # Set window icon - handle both development and PyInstaller bundled paths
        def get_icon_path():
            # Check if running in PyInstaller bundle
            if getattr(sys, "frozen", False):
                # For PyInstaller bundled app
                base_path = sys._MEIPASS
                icon_path = os.path.join(base_path, "assets", "icon.ico")
                if os.path.exists(icon_path):
                    return icon_path

            # For development
            paths = [
                os.path.join(
                    os.path.dirname(__file__), "..", "..", "assets", "icon.ico"
                ),
                os.path.join(
                    os.path.dirname(__file__), "..", "..", "assets", "icon.png"
                ),
                os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "..",
                    "..",
                    "assets",
                    "icon.ico",
                ),
                os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "..",
                    "..",
                    "assets",
                    "icon.png",
                ),
            ]

            for path in paths:
                if os.path.exists(path):
                    return path
            return None

        icon_path = get_icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

            # Set application-wide icon for Windows
            if sys.platform == "win32":
                import ctypes

                try:
                    myappid = "telegram.download.chat.gui.1.0"  # Arbitrary string
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                        myappid
                    )
                except Exception as e:
                    logging.warning(f"Could not set AppUserModelID: {e}")

        # Load settings before initializing UI components that might need them
        self._load_settings()

        # Initialize UI components
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # Initialize log view and other common widgets
        bottom = QWidget()
        vbox = QVBoxLayout(bottom)
        self.log_view = QTextEdit(readOnly=True)
        # Set fixed height for one line and enable scrolling
        font = self.log_view.font()
        font.setPointSize(12)  # Larger font size
        self.log_view.setFont(font)

        # Track log expansion state
        self.log_expanded = False
        self.log_collapsed_height = int(
            self.log_view.fontMetrics().height() * 1.5
        )  # Slightly more than one line height
        self.log_expanded_height = int(
            self.log_view.fontMetrics().height() * 10.5
        )  # 10 lines height

        self.log_view.setFixedHeight(self.log_collapsed_height)
        self.log_view.setLineWrapMode(QTextEdit.NoWrap)  # No line wrapping
        self.log_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )  # Show vertical scrollbar when needed
        self.log_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )  # Hide horizontal scrollbar

        # Connect textChanged signal to auto-scroll
        self.log_view.textChanged.connect(
            lambda: self.log_view.verticalScrollBar().setValue(
                self.log_view.verticalScrollBar().maximum()
            )
        )
        self.file_list = QListWidget()
        self.preview = QTextEdit(readOnly=True)
        self.preview.setAcceptDrops(False)
        self.open_btn = QPushButton("Open downloads")
        self.copy_btn = QPushButton(
            "Copy to clipboard (Ctrl+C)"
            if os.name == "nt"
            else "Copy to clipboard (⌘+C)"
        )
        # Style the copy button
        self.copy_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #666666;
            }
        """
        )
        self.copy_btn.setEnabled(False)
        self.file_size_label = QLabel("Size: 0 KB")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.current_file = None  # Track the currently shown file

        # Now build the tabs
        self._build_download_tab()
        self._build_convert_tab()
        self._build_settings_tab()

        # Settings are now loaded before UI components that need them

        # Create a horizontal layout for log header with copy button
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Log:"))

        # Add copy button with icon
        self.copy_log_btn = QPushButton()
        self.copy_log_btn.setIcon(
            self.style().standardIcon(getattr(QStyle.StandardPixmap, "SP_FileIcon"))
        )  # Using save icon as copy
        self.copy_log_btn.setToolTip("Copy log to clipboard")
        self.copy_log_btn.setFixedSize(24, 24)
        self.copy_log_btn.setStyleSheet(
            """
            QPushButton {
                border: none;
                padding: 2px;
                background: transparent;
            }
            QPushButton:hover {
                background: #f0f0f0;
                border-radius: 3px;
            }
        """
        )
        self.copy_log_btn.clicked.connect(self.copy_log_to_clipboard)
        log_header.addWidget(self.copy_log_btn)

        # Add expand/collapse button with +/- text
        self.expand_log_btn = QPushButton("+")
        self.expand_log_btn.setToolTip("Expand log")
        self.expand_log_btn.setFixedSize(20, 20)
        self.expand_log_btn.setStyleSheet(
            """
            QPushButton {
                border: none;
                padding: 0px;
                background: transparent;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background: #f0f0f0;
                border-radius: 3px;
            }
        """
        )
        self.expand_log_btn.clicked.connect(self.toggle_log_expansion)

        log_header.addWidget(self.expand_log_btn)

        log_header.addStretch()

        vbox.addLayout(log_header)
        vbox.addWidget(self.log_view)
        vbox.addWidget(QLabel("Files:"))
        vbox.addWidget(self.file_list)
        # Preview section
        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel("Preview (first 100 lines):"))
        preview_header.addStretch()
        preview_header.addWidget(self.file_size_label)
        vbox.addLayout(preview_header)
        vbox.addWidget(self.preview)

        # Buttons layout
        h = QHBoxLayout()
        h.addWidget(self.progress)
        h.addWidget(self.copy_btn)
        h.addWidget(self.open_btn)
        vbox.addLayout(h)

        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.addWidget(self.tabs)
        main_layout.addWidget(bottom)
        self.setCentralWidget(container)

        # Signals
        self.open_btn.clicked.connect(self.open_downloads)
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        self.file_list.currentTextChanged.connect(self.show_preview)

        # Set up keyboard shortcut - handle both Cmd+C and Ctrl+C on macOS
        if sys.platform == "darwin":
            # On macOS, we need to explicitly create a shortcut for Cmd+C
            self.copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self)
            self.copy_shortcut.setContext(Qt.ApplicationShortcut)
            self.copy_shortcut.activated.connect(self.copy_to_clipboard)

            # Also create a separate shortcut for Cmd+C
            self.cmd_copy_shortcut = QShortcut(QKeySequence("Meta+C"), self)
            self.cmd_copy_shortcut.setContext(Qt.ApplicationShortcut)
            self.cmd_copy_shortcut.activated.connect(self.copy_to_clipboard)
        else:
            # On other platforms, use the standard Copy shortcut
            self.copy_shortcut = QShortcut(QKeySequence.Copy, self)
            self.copy_shortcut.setContext(Qt.ApplicationShortcut)
            self.copy_shortcut.activated.connect(self.copy_to_clipboard)

    def _build_download_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()

        # Main chat input with larger size
        chat_label = QLabel("Chat:")
        label_font = chat_label.font()
        label_font.setPointSize(label_font.pointSize() * 2)  # Double the font size
        chat_label.setFont(label_font)

        self.chat_edit = QLineEdit()
        font = self.chat_edit.font()
        font.setPointSize(font.pointSize() * 2)  # Double the font size
        self.chat_edit.setFont(font)
        self.chat_edit.setPlaceholderText("@username, link or chat_id")
        self.chat_edit.returnPressed.connect(self.start_download)
        self.chat_edit.setText(
            self.config["settings"].get("chat_id", "")
        )  # Set default value from config
        self.chat_edit.setMinimumHeight(60)  # Make it taller
        self.chat_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        # Create a container for the chat input to control spacing
        chat_container = QWidget()
        chat_layout = QHBoxLayout(
            chat_container
        )  # Changed from QVBoxLayout to QHBoxLayout
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(10)  # Increased spacing for horizontal layout
        chat_layout.addWidget(chat_label)
        chat_layout.addWidget(self.chat_edit)

        form.addRow(chat_container)
        form.setContentsMargins(5, 5, 5, 5)  # Reduce form margins
        form.setSpacing(10)  # Slightly more spacing between rows

        # Add main form to layout
        layout.addLayout(form)

        # Create a container for settings with compact spacing
        settings_container = QWidget()
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setContentsMargins(0, 0, 0, 0)  # No margins
        settings_layout.setSpacing(0)  # No spacing between widgets
        settings_layout.setAlignment(Qt.AlignTop)  # Align to top

        # Add settings container to the main layout
        layout.addWidget(settings_container)

        # Create a tree view for settings with minimal height
        self.settings_tree = QTreeView()
        self.settings_tree.setHeaderHidden(True)
        self.settings_tree.setIndentation(10)  # Reduce indentation
        self.settings_tree.setRootIsDecorated(True)
        self.settings_tree.setExpandsOnDoubleClick(True)
        self.settings_tree.setEditTriggers(
            QTreeView.EditTrigger.NoEditTriggers
        )  # Disable editing
        self.settings_tree.setSelectionMode(
            QTreeView.SelectionMode.SingleSelection
        )  # Allow single selection
        self.settings_tree.setMinimumHeight(24)  # Ensure minimum height for visibility
        self.settings_tree.setMaximumHeight(200)  # Set a reasonable max height
        self.settings_tree.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )  # Show scrollbar when needed

        # Set size policy
        tree_size_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.settings_tree.setSizePolicy(tree_size_policy)

        # Add tree to settings layout
        settings_layout.addWidget(self.settings_tree)

        # Create a widget that will be shown/hidden
        self.settings_widget = QWidget()
        widget_size_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )
        self.settings_widget.setSizePolicy(
            widget_size_policy
        )  # Take minimum vertical space
        settings_form = QFormLayout(self.settings_widget)
        settings_form.setContentsMargins(2, 2, 2, 2)  # Minimal margins
        settings_form.setSpacing(4)  # Slightly more spacing for better readability
        settings_form.setFieldGrowthPolicy(
            QFormLayout.AllNonFixedFieldsGrow
        )  # Allow fields to grow
        settings_form.setFormAlignment(Qt.AlignTop | Qt.AlignLeft)  # Align to top

        # Add settings widget to the layout
        settings_layout.addWidget(self.settings_widget)

        # Output file selection
        self.output_edit = QLineEdit()
        btn_out = QPushButton("Browse…")
        btn_out.clicked.connect(lambda: self._browse(self.output_edit, False))
        h = QHBoxLayout()
        h.addWidget(self.output_edit)
        h.addWidget(btn_out)
        settings_form.addRow("Output file:", h)

        # Limit messages
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 1000000)
        settings_form.addRow("Message limit:", self.limit_spin)

        # Until date
        self.until_edit = QDateEdit()
        self.until_edit.setCalendarPopup(True)
        self.until_edit.setDisplayFormat("yyyy-MM-dd")
        self.until_edit.setDate(QDate())  # Set to invalid/empty date
        settings_form.addRow("Download until:", self.until_edit)

        # Subchat
        self.subchat_edit = QLineEdit()
        self.subchat_edit.setPlaceholderText("Leave empty for main chat")
        settings_form.addRow("Subchat URL/ID:", self.subchat_edit)

        # Debug mode
        self.debug_chk = QCheckBox("Enable debug mode")
        settings_form.addRow("Debug mode:", self.debug_chk)

        # Create a model for the tree
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(["Settings"])

        # Add settings item with proper styling
        settings_item = QStandardItem(
            "Settings ▶"
        )  # Add arrow indicator (collapsed state)
        settings_item.setCheckable(False)
        settings_item.setSelectable(True)
        settings_item.setEditable(False)
        font = settings_item.font()
        font.setBold(True)
        settings_item.setFont(font)

        # Add to model
        model.appendRow(settings_item)

        # Set the model to the tree view
        self.settings_tree.setModel(model)

        # Make sure the item is expanded and visible
        index = model.indexFromItem(settings_item)
        self.settings_tree.setExpanded(index, False)  # Start collapsed
        self.settings_tree.setCurrentIndex(index)  # Ensure it's selected

        # Connect the click event
        self.settings_tree.clicked.connect(self.toggle_settings_visibility)

        # Add widgets to the container
        settings_layout.addWidget(self.settings_tree)
        settings_layout.addWidget(self.settings_widget)

        # Hide settings by default (show only the tree view)
        self.settings_widget.setVisible(False)

        # Add the container to the main layout with minimal space
        layout.addWidget(
            settings_container, 0, Qt.AlignTop
        )  # Don't allow it to stretch

        # Store the settings item for toggling
        self.settings_item = settings_item

        # Create button container with minimal spacing
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(5, 5, 5, 5)  # Reduce margins
        button_layout.setSpacing(10)  # Reduce spacing between buttons
        button_layout.addStretch()

        # Create start button
        self.start_btn = QPushButton("Start download")
        self.start_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                font-size: 16px;
                padding: 12px 24px;
                border: none;
                border-radius: 6px;
                min-width: 180px;
                min-height: 40px;
                margin-top: 20px;
                margin-right: 10px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #666666;
            }
        """
        )
        self.start_btn.clicked.connect(self.start_download)

        # Create stop button
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #f44336;
                color: white;
                font-weight: bold;
                font-size: 16px;
                padding: 12px 24px;
                border: none;
                border-radius: 6px;
                min-width: 100px;
                min-height: 40px;
                margin-top: 20px;
                margin-left: 10px;
            }
            QPushButton:hover {
                background-color: #e53935;
            }
            QPushButton:pressed {
                background-color: #c62828;
            }
            QPushButton:disabled {
                background-color: #666666;
            }
        """
        )
        self.stop_btn.clicked.connect(self.stop_download)
        self.stop_btn.setEnabled(False)

        # Add buttons to layout
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        button_layout.addStretch()

        # Add the button container to the main layout
        layout.addWidget(button_container)

        # Add some stretch to push everything to the top
        layout.addStretch()

        # Add the tab to the tab widget
        self.tabs.addTab(tab, "Download")

    def toggle_settings_visibility(self, index):
        """Toggle the settings visibility and update arrow indicator."""
        if (
            index.isValid() and index.row() == 0
        ):  # Only handle clicks on the settings item
            # Toggle visibility
            is_visible = self.settings_widget.isVisible()
            self.settings_widget.setVisible(not is_visible)

            # Update arrow indicator
            if is_visible:
                # Collapsing - show right arrow
                self.settings_item.setText("Settings ▶")
            else:
                # Expanding - show down arrow
                self.settings_item.setText("Settings ▼")

    def _build_convert_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.export_edit = QLineEdit()
        btn_exp = QPushButton("Browse…")
        btn_exp.clicked.connect(lambda: self._browse(self.export_edit, True))
        h = QHBoxLayout()
        h.addWidget(self.export_edit)
        h.addWidget(btn_exp)
        self.conv_output = QLineEdit()
        btn_conv_out = QPushButton("Browse…")
        btn_conv_out.clicked.connect(lambda: self._browse(self.conv_output, False))
        h2 = QHBoxLayout()
        h2.addWidget(self.conv_output)
        h2.addWidget(btn_conv_out)
        self.conv_debug = QCheckBox("Debug mode")
        self.conv_user_edit = QLineEdit()
        self.conv_user_edit.setPlaceholderText("Sender's user_id")

        form.addRow("Export file:", h)
        form.addRow("Output file:", h2)
        form.addRow("User filter:", self.conv_user_edit)
        form.addRow("Debug:", self.conv_debug)
        self.conv_btn = QPushButton("Convert Data")
        self.conv_btn.clicked.connect(self.start_convert)
        form.addRow(self.conv_btn)
        self.tabs.addTab(tab, "Convert")

    def _build_settings_tab(self):
        """Build the settings tab with API credentials and Telegram login."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)  # Reduce outer margins
        layout.setSpacing(5)  # Reduce spacing between widgets

        # Create a form for API credentials
        api_group = QWidget()
        form = QFormLayout(api_group)
        form.setContentsMargins(5, 5, 5, 5)  # Reduce form margins
        form.setSpacing(5)  # Reduce spacing between form rows

        # API ID
        self.api_id_edit = QLineEdit()
        self.api_id_edit.setPlaceholderText("Enter your Telegram API ID")
        if "api_id" in self.config.get("settings", {}):
            self.api_id_edit.setText(str(self.config["settings"]["api_id"]))
        form.addRow("API ID:", self.api_id_edit)

        # API Hash
        self.api_hash_edit = QLineEdit()
        self.api_hash_edit.setPlaceholderText("Enter your Telegram API Hash")
        if "api_hash" in self.config.get("settings", {}):
            self.api_hash_edit.setText(str(self.config["settings"]["api_hash"]))
        self.api_hash_edit.setEchoMode(QLineEdit.Password)
        form.addRow("API Hash:", self.api_hash_edit)

        # Add API group to layout
        layout.addWidget(api_group)

        # Add Save button
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self._save_settings)
        save_btn.setStyleSheet(
            """
            QPushButton {
                padding: 8px 16px;
                font-weight: bold;
            }
        """
        )
        layout.addWidget(save_btn)

        # Add help text for API credentials
        help_label = QLabel(
            "<p>To get your API credentials:</p>"
            "<ol style='margin-top: 0; padding-left: 20px;'>"
            "<li>Go to <a href='https://my.telegram.org/'>my.telegram.org</a></li>"
            "<li>Log in with your phone number</li>"
            "<li>Go to 'API development tools'</li>"
            "<li>Create a new application</li>"
            "<li>Copy the API ID and API Hash</li>"
            "</ol>"
        )
        help_label.setOpenExternalLinks(True)
        help_label.setWordWrap(True)
        help_label.setStyleSheet("margin: 5px 0;")
        layout.addWidget(help_label)

        # Add a line separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("margin: 10px 0;")
        layout.addWidget(line)

        # Session file path
        self.session_file = get_app_dir() / "session.session"

        # Create a group for session status (shown when logged in)
        self.session_status_group = QGroupBox("Telegram Session")
        self.session_status_group.setStyleSheet("QGroupBox { margin-top: 5px; }")
        session_status_layout = QVBoxLayout(self.session_status_group)
        session_status_layout.setContentsMargins(5, 15, 5, 5)  # Adjust title margin
        self.session_status_label = QLabel("Session is active")
        self.logout_btn = QPushButton("Logout")
        self.logout_btn.clicked.connect(
            lambda: asyncio.create_task(self._do_logout_async())
        )
        session_status_layout.addWidget(self.session_status_label)
        session_status_layout.addWidget(self.logout_btn)
        self.session_status_group.setVisible(self.session_file.exists())

        # Create a group for Telegram login (shown when not logged in)
        self.login_group = QGroupBox("First time Telegram login")
        self.login_group.setStyleSheet("QGroupBox { margin-top: 5px; }")
        self.login_group.setVisible(not self.session_file.exists())
        login_form = QFormLayout(self.login_group)
        login_form.setContentsMargins(5, 15, 5, 5)  # Adjust title margin
        login_form.setSpacing(5)  # Reduce spacing between form rows

        # Phone number
        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("+1234567890")
        if "phone" in self.config.get("settings", {}):
            self.phone_edit.setText(str(self.config["settings"]["phone"]))

        # Get Code button
        self.get_code_btn = QPushButton("Get Code")
        self.get_code_btn.clicked.connect(self._request_code)

        # Layout for phone and button
        phone_layout = QHBoxLayout()
        phone_layout.addWidget(self.phone_edit)
        phone_layout.addWidget(self.get_code_btn)
        login_form.addRow("Phone:", phone_layout)

        # Code input
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Enter the code from Telegram")
        self.code_edit.textChanged.connect(self._update_login_button_state)
        login_form.addRow("Code:", self.code_edit)

        # Password (for 2FA)
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("Enter your cloud password (if any)")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.returnPressed.connect(
            self._do_login
        )  # Trigger login on Enter key
        login_form.addRow("Password:", self.password_edit)

        # Login button
        self.login_btn = QPushButton("Login")
        self.login_btn.setEnabled(False)
        self.login_btn.clicked.connect(self._do_login)
        login_form.addRow(self.login_btn)

        # Add login and session status groups to layout
        layout.addWidget(self.login_group)
        layout.addWidget(self.session_status_group)

        # Add stretch to push everything to the top
        layout.addStretch()

        # Add the settings tab
        self.tabs.addTab(tab, "Settings")

    def _update_login_button_state(self):
        """Update the login button state based on code input."""
        self.login_btn.setEnabled(bool(self.code_edit.text().strip()))

    def _browse(self, line_edit, is_file):
        path = (
            QFileDialog.getExistingDirectory(self, "Select folder")
            if not is_file
            else QFileDialog.getOpenFileName(
                self, "Select file", filter="JSON Files (*.json)"
            )[0]
        )
        if path:
            line_edit.setText(path)

    def _load_settings(self):
        """Load settings from config file."""
        ensure_app_dirs()  # Make sure the config directory exists
        self.config_path = get_default_config_path()

        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config = yaml.safe_load(f) or {"settings": {}}

                # Get settings from config
                settings = self.config.get("settings", {})

                # Get API credentials from settings section
                api_id = settings.get("api_id", "")
                api_hash = settings.get("api_hash", "")

                # Update the UI
                if hasattr(self, "api_id_edit"):
                    self.api_id_edit.setText(str(api_id))
                if hasattr(self, "api_hash_edit"):
                    self.api_hash_edit.setText(str(api_hash))

                # Load phone number
                if hasattr(self, "phone_edit"):
                    phone = settings.get("phone", "")
                    self.phone_edit.setText(str(phone))

                if hasattr(self, "log_view"):
                    self.log_view.append(f"Loaded settings from {self.config_path}")

            except Exception as e:
                if hasattr(self, "log_view"):
                    self.log_view.append(
                        f"Error loading settings from {self.config_path}: {e}"
                    )
                else:
                    print(f"Error loading settings from {self.config_path}: {e}")
        elif hasattr(self, "log_view"):
            self.log_view.append(f"Config file not found at {self.config_path}")
            self.config = {"settings": {}}

    def _save_settings(self):
        """Save settings to config file."""
        ensure_app_dirs()  # Make sure the config directory exists

        # Update config with current values
        if not hasattr(self, "config"):
            self.config = {"settings": {}}

        # Update settings with API credentials and phone number
        if "settings" not in self.config:
            self.config["settings"] = {}

        self.config["settings"].update(
            {
                "api_id": self.api_id_edit.text(),
                "api_hash": self.api_hash_edit.text(),
                "phone": self.phone_edit.text(),
                "chat_id": self.chat_edit.text(),
            }
        )

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.config, f, default_flow_style=False)
            self.log_view.append(f"Settings saved successfully to {self.config_path}")
            return True
        except Exception as e:
            self.log_view.append(f"Error saving settings to {self.config_path}: {e}")
            return False

    async def _send_code_request_async(self, phone):
        """Send the actual code request to Telegram."""
        try:
            # Initialize the client with current config
            api_id = self.api_id_edit.text().strip()
            api_hash = self.api_hash_edit.text().strip()

            if not all([api_id, api_hash]):
                raise ValueError("API ID and API Hash are required")

            # Create a new Telegram client
            self.downloader = TelegramChatDownloader(str(self.config_path))

            # Connect and send code request
            await self.downloader.connect(phone)

            # Enable UI elements for code entry
            self.code_edit.setFocus()
            # Login button state will be updated by textChanged signal

            # Show success message
            QMessageBox.information(
                self,
                "Code Sent",
                f"A verification code has been sent to {phone}.\n\n"
                "Please check your Telegram app and enter the code below.",
            )
            return True

        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to send verification code: {str(e)}"
            )
            # Reset UI on error
            self._reset_login_ui()
            return False
        finally:
            # Don't disconnect here - we need to keep the connection for the next step
            pass

    def _request_code(self):
        """Request a login code from Telegram."""
        phone = self.phone_edit.text().strip()
        if not phone:
            QMessageBox.warning(self, "Error", "Please enter a phone number")
            return

        # Save settings first to ensure API credentials are stored
        if not self._save_settings():
            QMessageBox.warning(self, "Error", "Failed to save settings")
            return

        # Disable UI elements during code request
        self.phone_edit.setEnabled(False)
        # self.get_code_btn.setEnabled(False)
        self.code_edit.clear()
        self.login_btn.setEnabled(False)

        # Show loading state
        self.log_view.append(f"Sending verification code to {phone}...")

        # Create a task for the async code request
        try:
            loop = asyncio.get_event_loop()
            if (
                not hasattr(self, "_code_request_task")
                or self._code_request_task.done()
            ):
                self._code_request_task = loop.create_task(
                    self._send_code_request_async(phone)
                )
                self._code_request_task.add_done_callback(
                    lambda f: self._on_code_request_done(f, phone)
                )
        except Exception as e:
            error_msg = f"Failed to start code request: {str(e)}"
            self.log_view.append(error_msg)
            QMessageBox.critical(self, "Error", error_msg)
            # Reset UI on error
            self.phone_edit.setEnabled(True)
            self.get_code_btn.setEnabled(True)

    def _on_code_request_done(self, future, phone):
        """Handle completion of the code request."""
        try:
            future.result()  # This will raise any exceptions that occurred in the task
            self.login_btn.setEnabled(True)
        except Exception as e:
            error_msg = str(e)
            self.log_view.append(f"Error sending code to {phone}: {error_msg}")
            QMessageBox.warning(self, "Error", f"Failed to send code: {error_msg}")
            # Reset UI on error
            self.phone_edit.setEnabled(True)
            self.get_code_btn.setEnabled(True)

    async def _do_login_async(self):
        """Handle the login process asynchronously."""
        try:
            phone = self.phone_edit.text().strip()
            code = self.code_edit.text().strip()
            password = self.password_edit.text().strip()

            if not code:
                raise ValueError("Please enter the verification code")

            # Check if we have an active client from the code request
            if (
                not hasattr(self, "downloader")
                or not self.downloader
                or not hasattr(self.downloader, "client")
            ):
                self.downloader = TelegramChatDownloader(str(self.config_path))
                # raise ValueError("Please request a verification code first")

            # Show loading state
            self.log_view.append("Verifying code...")

            try:
                # Try to sign in with the code
                await self.downloader.connect(phone, code, password)
            except SessionPasswordNeededError:
                # If 2FA is enabled, ask for password
                if not password:
                    # If no password provided, ask for it
                    password, ok = QInputDialog.getText(
                        self,
                        "2FA Required",
                        "Please enter your 2FA password:",
                        QLineEdit.Password,
                    )
                    if not ok or not password:
                        raise ValueError("2FA password is required")

                await self.downloader.client.sign_in(password=password)

            # Get user info while we have an active connection
            me = await self.downloader.client.get_me()
            name = (
                f"{me.first_name or ''} {me.last_name or ''}".strip()
                or me.username
                or "Unknown"
            )
            phone = getattr(me, "phone", self.phone_edit.text())
            username = getattr(me, "username", "no_username")

            # Save the session and disconnect
            self.downloader.client.session.save()
            await self.downloader.client.disconnect()

            # Update UI with the user info we already have
            self.login_btn.setEnabled(False)
            self.get_code_btn.setEnabled(True)
            self.get_code_btn.setText("Change Number")

            # Update session status
            self.session_status_label.setText(f"Session for {phone} is active")
            self.session_status_group.setVisible(True)
            self.login_group.setVisible(False)

            # Show success message
            QMessageBox.information(
                self,
                "Login Successful",
                f"Successfully logged in as {name} (@{username})",
            )

            # Save the phone number in settings
            self._save_settings()

        except PhoneCodeInvalidError:
            QMessageBox.warning(
                self, "Error", "Invalid verification code. Please try again."
            )
            self.code_edit.clear()
            self.code_edit.setFocus()
        except Exception as e:
            QMessageBox.critical(self, "Login Failed", f"Failed to login: {str(e)}")
            self._reset_login_ui()
        finally:
            # Make sure we clean up the client if something went wrong
            if (
                hasattr(self, "downloader")
                and self.downloader
                and hasattr(self.downloader, "client")
            ):
                if self.downloader.client.is_connected():
                    await self.downloader.client.disconnect()
                self.downloader = None

    def _do_login(self):
        """Handle the login button click."""
        if not self.code_edit.text().strip():
            QMessageBox.warning(self, "Error", "Please enter the verification code")
            self.code_edit.setFocus()
            return

        # Disable UI elements during login
        self.login_btn.setEnabled(False)

        # Show progress
        self.log_view.append("Logging in to Telegram...")

        # Run the async login in the event loop
        asyncio.create_task(self._do_login_async())

    async def _update_ui_after_login(self):
        """Update the UI after successful login."""
        # This method runs in the event loop
        me = await self.downloader.client.get_me()
        name = (
            f"{me.first_name or ''} {me.last_name or ''}".strip()
            or me.username
            or "Unknown"
        )
        phone = getattr(me, "phone", self.phone_edit.text())

        # Schedule UI updates on the main thread
        self.login_btn.setEnabled(False)
        self.get_code_btn.setEnabled(True)
        self.get_code_btn.setText("Change Number")

        # Update session status
        self.session_status_label.setText(f"Session for {phone} is active")
        self.session_status_group.setVisible(True)
        self.login_group.setVisible(False)

        # Show success message
        QMessageBox.information(
            self,
            "Login Successful",
            f"Successfully logged in as {name} (@{me.username or 'no_username'})",
        )

        # Save the phone number in settings
        self._save_settings()

    async def _do_logout_async(self):
        """Handle logout by deleting the session file and resetting the UI."""
        reply = QMessageBox.question(
            self,
            "Confirm Logout",
            "Are you sure you want to log out?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                # Get the session file path from the downloader if it exists
                session_file = None
                if (
                    hasattr(self, "downloader")
                    and self.downloader
                    and hasattr(self.downloader, "session")
                ):
                    session_file = (
                        Path(self.downloader.session.filename)
                        if self.downloader.session and self.downloader.session.filename
                        else None
                    )

                # Delete the session file if it exists
                if session_file and session_file.exists():
                    session_files = [
                        session_file,
                        session_file.with_suffix(".session-journal"),
                        session_file.with_suffix(".session"),
                    ]

                    for sf in session_files:
                        if sf.exists():
                            try:
                                sf.unlink()
                                self.log_view.append(f"Deleted session file: {sf}")
                            except Exception as e:
                                self.log_view.append(f"Failed to delete {sf}: {str(e)}")

                # Disconnect and clean up the client
                if (
                    hasattr(self, "downloader")
                    and self.downloader
                    and hasattr(self.downloader, "client")
                ):
                    if self.downloader.client.is_connected():
                        try:
                            await self.downloader.client.disconnect()
                        except Exception as e:
                            self.log_view.append(
                                f"Error disconnecting client: {str(e)}"
                            )
                    self.downloader = None

                # Reset the UI
                self._reset_login_ui()
                self.session_status_group.setVisible(False)
                self.login_group.setVisible(True)

                # Clear the session status
                self.session_status_label.setText("No active session")

                self.log_view.append("Successfully logged out")

            except Exception as e:
                QMessageBox.critical(
                    self, "Logout Error", f"Failed to log out: {str(e)}"
                )
                self.log_view.append(f"Error during logout: {str(e)}")

    def _reset_login_ui(self):
        """Reset the login UI to its initial state."""
        self.code_edit.clear()
        self.password_edit.clear()
        self.phone_edit.setEnabled(True)
        self.login_btn.setEnabled(False)
        self.get_code_btn.setEnabled(True)
        self.get_code_btn.setText("Get Code")
        self.session_status_group.setVisible(False)

    def start_download(self):
        cmd = [sys.executable, "-m", "telegram_download_chat"]
        if self.debug_chk.isChecked():
            cmd.append("--debug")
        chat_id = self.chat_edit.text()
        self._save_settings()
        cmd += [chat_id]
        if self.limit_spin.value():
            cmd += ["--limit", str(self.limit_spin.value())]
        if self.subchat_edit.text():
            cmd += ["--subchat", self.subchat_edit.text()]
        if self.until_edit.date():
            cmd += ["--until", self.until_edit.date().toString("yyyy-MM-dd")]
        output_path = (
            Path(self.output_edit.text())
            if self.output_edit.text()
            else get_downloads_dir() / "chat_history.json"
        )
        if self.output_edit.text():
            cmd += ["-o", str(output_path)]
        # Use the directory of the output file
        out_dir = str(output_path.parent)
        self._run_worker(cmd, out_dir)

    def start_convert(self):
        cmd = [sys.executable, "-m", "telegram_download_chat"]
        if self.conv_debug.isChecked():
            cmd.append("--debug")
        input_file = self.export_edit.text()
        cmd += [input_file]
        if self.conv_user_edit.text():
            cmd += ["--user", self.conv_user_edit.text()]
        downloads_dir = get_downloads_dir()
        output_path = (
            Path(self.conv_output.text())
            if self.conv_output.text()
            else downloads_dir / "converted_chat.json"
        )
        if self.conv_output.text():
            cmd += ["-o", str(output_path)]
        # Use the directory of the output file
        out_dir = str(output_path.parent)
        self._run_worker(cmd, out_dir)

    def _run_worker(self, cmd, out_dir):
        # clear
        self.log_view.clear()
        self.file_list.clear()
        self.preview.clear()
        self.worker = WorkerThread(cmd, out_dir)
        self.worker.log.connect(self.log_view.append)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.on_finished)
        self.start_btn.setEnabled(False)
        self.start_btn.setText("Downloading...")
        self.stop_btn.setEnabled(True)
        self.worker.start()

    def stop_download(self):
        if hasattr(self, "worker") and self.worker.isRunning():
            self.stop_btn.setEnabled(False)
            self.worker.stop()
            self.log_view.append("Stopping download and saving messages...")

    def update_progress(self, current, maximum):
        """Update the progress bar with current and maximum values."""
        self.progress.setMaximum(maximum)
        self.progress.setValue(current)

    def on_finished(self, files, was_stopped_by_user):
        self.file_list.clear()
        if files:
            self.file_list.addItems([os.path.basename(f) for f in files])
            self.file_list.setCurrentRow(0)  # Select first file
            self.open_btn.setEnabled(True)
            self.copy_btn.setEnabled(True)
            # Provide appropriate feedback based on how the download ended
            if was_stopped_by_user:
                self.log_view.append(f"\nDownload stopped by user.")
            else:
                self.log_view.append("\nDownload completed!")
        else:
            self.log_view.append("\nNo files were downloaded.")
            self.open_btn.setEnabled(False)
            self.copy_btn.setEnabled(False)
            self.preview.clear()
            self.file_size_label.setText("Size: 0 KB")

        # Reset progress bar and buttons
        self.progress.setMaximum(1000)
        self.progress.setValue(1000)
        self.start_btn.setEnabled(True)
        self.start_btn.setText("Start download")
        self.stop_btn.setEnabled(False)
        # Reset download button to original green style
        self.start_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                font-size: 16px;
                padding: 12px 24px;
                border: none;
                border-radius: 6px;
                min-width: 180px;
                min-height: 40px;
                margin-top: 20px;
                margin-right: 10px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #666666;
            }
        """
        )

    def show_preview(self, filename):
        self.preview.clear()
        # Prepend downloads directory to get full path
        full_path = os.path.join(get_downloads_dir(), filename)
        self.current_file = full_path
        try:
            file_size = os.path.getsize(full_path) / 1024  # Size in KB
            self.file_size_label.setText(f"Size: {file_size:.1f} KB")
            self.copy_btn.setEnabled(True)

            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i >= 100:
                        self.preview.append("\n[Preview truncated to first 100 lines]")
                        break
                    self.preview.append(line.rstrip())
        except Exception as e:
            self.preview.append(f"Error: {e}")
            self.copy_btn.setEnabled(False)

    def copy_to_clipboard(self):
        if not self.current_file:
            self.log_view.append("Error: No file selected")
            return

        if not os.path.exists(self.current_file):
            self.log_view.append(f"Error: File not found: {self.current_file}")
            return

        try:
            # Check file size first (10MB limit)
            file_size = os.path.getsize(self.current_file)
            if file_size > 10 * 1024 * 1024:  # 10MB
                self.log_view.append(
                    "Error: File is too large to copy to clipboard (max 10MB)"
                )
                return

            # Read file with error handling for encoding
            try:
                with open(
                    self.current_file, "r", encoding="utf-8", errors="replace"
                ) as f:
                    content = f.read()  # Read entire file content

                # Copy to clipboard
                clipboard = QApplication.clipboard()
                clipboard.setText(content)

                # Show success message with file name
                file_name = os.path.basename(self.current_file)
                self.log_view.append(
                    f"Copied content of '{file_name}' to clipboard ({file_size / 1024 / 1024:.2f} MB)"
                )

            except UnicodeDecodeError:
                self.log_view.append("Error: Could not decode file as UTF-8 text")

        except PermissionError:
            self.log_view.append(
                "Error: Permission denied when trying to read the file"
            )

        except Exception as e:
            self.log_view.append(f"Error copying to clipboard: {str(e)}")

    def copy_log_to_clipboard(self):
        """Copy the entire log content to clipboard"""
        if self.log_view.toPlainText():
            QApplication.clipboard().setText(self.log_view.toPlainText())
            self.log_view.append(f"Copied log to clipboard")

    def open_downloads(self):
        folder = get_downloads_dir()
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.call(["open", folder])
        else:
            subprocess.call(["xdg-open", folder])

    def toggle_log_expansion(self):
        """Toggle the log view expansion."""
        if self.log_expanded:
            self.log_view.setFixedHeight(self.log_collapsed_height)
            self.expand_log_btn.setText("+")
            self.expand_log_btn.setToolTip("Expand log")
        else:
            self.log_view.setFixedHeight(self.log_expanded_height)
            self.expand_log_btn.setText("-")
            self.expand_log_btn.setToolTip("Collapse log")

        self.log_expanded = not self.log_expanded


def get_downloads_dir():
    args = parse_args()
    downloader = TelegramChatDownloader(config_path=args.config)
    output_dir = downloader.config.get("settings", {}).get(
        "save_path", get_app_dir() / "downloads"
    )
    return output_dir


def main():
    # Create the QApplication instance
    app = QApplication(sys.argv)
    app.setApplicationName("Telegram Download Chat")

    # Set up asyncio to work with PySide6
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Create and show the main window
    win = MainWindow()
    win.show()

    # Run the application
    with loop:
        loop.run_forever()

    # Properly clean up the QApplication
    app.quit()


if __name__ == "__main__":
    main()

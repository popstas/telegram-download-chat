"""Download tab for the Telegram Download Chat GUI."""

from typing import Any, Dict

from PySide6.QtCore import QDate, QModelIndex, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from telegram_download_chat.paths import get_downloads_dir


class DownloadTab(QWidget):
    """Download tab for the Telegram Download Chat GUI."""

    # Signal emitted when the download starts
    download_started = Signal(list, str)  # cmd_args, output_dir

    # Signal emitted when the download is stopped
    download_stopped = Signal()

    def __init__(self, parent=None):
        """Initialize the download tab.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self._setup_ui()
        self._connect_signals()
        self._load_settings()

    def _setup_ui(self):
        """Set up the user interface."""
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        # Chat input
        self._setup_chat_input(layout)

        # Settings container
        self._setup_settings_container(layout)

        # Buttons
        self._setup_buttons(layout)

        # Add stretch to push everything to the top
        layout.addStretch()

    def _setup_chat_input(self, parent_layout):
        """Set up the chat input section.

        Args:
            parent_layout: Parent layout to add the chat input to
        """
        form = QFormLayout()
        form.setContentsMargins(5, 5, 5, 5)
        form.setSpacing(10)

        # Chat label with larger font
        chat_label = QLabel("Chat:")
        label_font = chat_label.font()
        label_font.setPointSize(label_font.pointSize() * 2)
        chat_label.setFont(label_font)

        # Chat input
        self.chat_edit = QLineEdit()
        font = self.chat_edit.font()
        font.setPointSize(font.pointSize() * 2)
        self.chat_edit.setFont(font)
        self.chat_edit.setPlaceholderText("@username, link or chat_id")
        self.chat_edit.setMinimumHeight(60)
        self.chat_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # Add to form
        form.addRow(chat_label, self.chat_edit)
        parent_layout.addLayout(form)

    def _setup_settings_container(self, parent_layout):
        """Set up the settings container.

        Args:
            parent_layout: Parent layout to add the settings container to
        """
        # Create a container for settings with compact spacing
        settings_container = QWidget()
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(0)
        settings_layout.setAlignment(Qt.AlignTop)

        # Add settings container to the main layout
        parent_layout.addWidget(settings_container)

        # Create a tree view for settings with minimal height
        self.settings_tree = QTreeView()
        self.settings_tree.setHeaderHidden(True)
        self.settings_tree.setIndentation(10)
        self.settings_tree.setRootIsDecorated(True)
        self.settings_tree.setExpandsOnDoubleClick(True)
        self.settings_tree.setEditTriggers(QTreeView.NoEditTriggers)
        self.settings_tree.setSelectionMode(QTreeView.SingleSelection)
        self.settings_tree.setMinimumHeight(24)
        self.settings_tree.setMaximumHeight(24)
        self.settings_tree.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # Set size policy
        tree_size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.settings_tree.setSizePolicy(tree_size_policy)

        # Add tree to settings layout
        settings_layout.addWidget(self.settings_tree)

        # Create a widget that will be shown/hidden
        self.settings_widget = QWidget()
        widget_size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.settings_widget.setSizePolicy(widget_size_policy)
        settings_form = QFormLayout(self.settings_widget)
        settings_form.setContentsMargins(2, 2, 2, 2)
        settings_form.setSpacing(4)
        settings_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        settings_form.setFormAlignment(Qt.AlignTop | Qt.AlignLeft)

        # Add settings widget to the layout
        settings_layout.addWidget(self.settings_widget)

        # Sort order
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Ascending", "asc")
        self.sort_combo.addItem("Descending", "desc")
        self.sort_combo.setCurrentIndex(0)
        settings_form.addRow("Sort order:", self.sort_combo)

        # Split output
        self.split_combo = QComboBox()
        self.split_combo.addItem("Don't split", None)
        self.split_combo.addItem("By Month", "month")
        self.split_combo.addItem("By Year", "year")
        settings_form.addRow("Split output:", self.split_combo)

        # Output file selection
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Leave empty to use chat name")
        btn_out = QPushButton("Browse…")
        btn_out.clicked.connect(self._browse_output)
        h = QHBoxLayout()
        h.addWidget(self.output_edit)
        h.addWidget(btn_out)
        settings_form.addRow("Output file:", h)

        # Limit messages
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 1000000)
        settings_form.addRow("Message limit:", self.limit_spin)

        # Base date for last days
        self.from_edit = QDateEdit()
        self.from_edit.setCalendarPopup(True)
        self.from_edit.setDisplayFormat("yyyy-MM-dd")
        self.from_edit.setDate(QDate())
        settings_form.addRow("Base date:", self.from_edit)

        # Last days
        self.last_days_spin = QSpinBox()
        self.last_days_spin.setRange(0, 3650)
        settings_form.addRow("Last days:", self.last_days_spin)

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

        # User filter
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText(
            "@username or user_id (e.g., 12345 or user12345)"
        )
        settings_form.addRow("Filter by user:", self.user_edit)

        # Debug mode
        self.debug_chk = QCheckBox("Enable debug mode")
        settings_form.addRow("Debug mode:", self.debug_chk)

        # Create a model for the tree
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(["Settings"])

        # Add settings item with proper styling
        self.settings_item = QStandardItem(
            "Settings ▶"
        )  # Add arrow indicator (collapsed state)
        self.settings_item.setCheckable(False)
        self.settings_item.setSelectable(True)
        self.settings_item.setEditable(False)
        font = self.settings_item.font()
        font.setBold(True)
        self.settings_item.setFont(font)

        # Add to model
        model.appendRow(self.settings_item)

        # Set the model to the tree view
        self.settings_tree.setModel(model)

        # Make sure the item is expanded and visible
        index = model.indexFromItem(self.settings_item)
        self.settings_tree.setExpanded(index, False)  # Start collapsed
        self.settings_tree.setCurrentIndex(index)  # Ensure it's selected

        # Hide settings by default
        self.settings_widget.setVisible(False)

    def _setup_buttons(self, parent_layout):
        """Set up the buttons and progress bar.

        Args:
            parent_layout: Parent layout to add the buttons to
        """
        # Button container
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        # Start button
        self.start_btn = QPushButton("Start Download")
        self.start_btn.setFixedHeight(40)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 8px 16px;
                min-width: 120px;
            }
            QPushButton:disabled {
                background-color: #666666;
                color: #aaaaaa;
            }
            QPushButton:hover:enabled {
                background-color: #45a049;
            }
            QPushButton:pressed:enabled {
                background-color: #3d8b40;
                padding: 9px 15px 7px 17px;  /* Creates a subtle press effect */
            }
        """
        )
        btn_layout.addWidget(self.start_btn)

        # Add a simple loading indicator (ellipsis)
        self.loading_label = QLabel("")
        self.loading_label.setFixedSize(24, 24)
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.hide()
        btn_layout.addWidget(self.loading_label)

        # Stop button
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedHeight(40)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 8px 16px;
                min-width: 80px;
                opacity: 1;
            }
            QPushButton:disabled {
                background-color: #666666;
                color: #aaaaaa;
                opacity: 0.7;
            }
            QPushButton:hover:enabled {
                background-color: #d32f2f;
            }
            QPushButton:pressed:enabled {
                background-color: #b71c1c;
                padding: 9px 15px 7px 17px;  /* Creates a subtle press effect */
            }
        """
        )
        btn_layout.addWidget(self.stop_btn)

        # Add stretch to push buttons to the left
        btn_layout.addStretch()

        # Create a container for the buttons
        button_container = QWidget()
        button_container.setLayout(btn_layout)

        # Add button container to parent
        parent_layout.addWidget(button_container)

        # Add progress bar with enhanced styling
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Idle")
        self.progress.setVisible(False)

        # Custom progress bar styling
        self.progress.setStyleSheet(
            """
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 4px;
                text-align: center;
                background-color: #f5f5f5;
                height: 24px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 2px;
                width: 10px;
                margin: 0.5px;
            }
            QProgressBar:indeterminate::chunk {
                background-color: #4CAF50;
                border-radius: 2px;
                width: 10px;
                margin: 0.5px;
            }
        """
        )

        # Animation for indeterminate progress
        self.progress_animation = QPropertyAnimation(self.progress, b"value")
        self.progress_animation.setDuration(2000)
        self.progress_animation.setStartValue(0)
        self.progress_animation.setEndValue(100)
        self.progress_animation.setLoopCount(-1)  # Infinite loop

        parent_layout.addWidget(self.progress)

    def _connect_signals(self):
        """Connect signals to slots."""
        self.settings_tree.clicked.connect(self.toggle_settings_visibility)
        self.start_btn.clicked.connect(self.start_download)
        self.stop_btn.clicked.connect(self.stop_download)
        self.chat_edit.returnPressed.connect(self.start_download)

    def _load_settings(self):
        """Load settings from config."""
        try:
            from ..utils.config import ConfigManager

            # Initialize config manager
            config = ConfigManager()
            config.load()

            # Get download settings with defaults
            settings = config.get("form_settings", {})

            # Update UI elements with loaded settings
            if "output" in settings and settings["output"]:
                self.output_edit.setText(settings["output"])

            if "limit" in settings and settings["limit"] is not None:
                self.limit_spin.setValue(settings["limit"])

            if "from_date" in settings and settings["from_date"]:
                try:
                    date = QDate.fromString(settings["from_date"], "yyyy-MM-dd")
                    if date.isValid():
                        self.from_edit.setDate(date)
                except Exception as e:
                    logging.warning(f"Failed to parse from date: {e}")

            if "last_days" in settings and settings["last_days"] is not None:
                self.last_days_spin.setValue(int(settings["last_days"]))

            if "until" in settings and settings["until"]:
                try:
                    date = QDate.fromString(settings["until"], "yyyy-MM-dd")
                    if date.isValid():
                        self.until_edit.setDate(date)
                except Exception as e:
                    logging.warning(f"Failed to parse until date: {e}")

            if "chat" in settings:
                self.chat_edit.setText(settings["chat"])

            if "subchat" in settings:
                self.subchat_edit.setText(settings["subchat"])

            if "debug" in settings:
                self.debug_chk.setChecked(settings["debug"])

            sort_order = settings.get("sort", "asc")
            index = 0 if sort_order == "asc" else 1
            self.sort_combo.setCurrentIndex(index)

            split_by = settings.get("split") or None
            split_index = (
                self.split_combo.findData(split_by)
                if split_by is not None
                else self.split_combo.findData(None)
            )
            if split_index >= 0:
                self.split_combo.setCurrentIndex(split_index)

        except Exception as e:
            logging.error(f"Error loading settings: {e}", exc_info=True)

    def _save_settings(self):
        """Save settings to config."""
        try:
            from ..utils.config import ConfigManager

            # Initialize config manager
            config = ConfigManager()
            config.load()

            # Get current settings
            settings = config.get("form_settings", {})

            # Update settings with current UI values
            settings.update(
                {
                    "chat": self.chat_edit.text().strip(),
                    "output": self.output_edit.text().strip(),
                    "limit": self.limit_spin.value(),
                    "from_date": (
                        self.from_edit.date().toString("yyyy-MM-dd")
                        if self.from_edit.date().isValid()
                        else ""
                    ),
                    "last_days": self.last_days_spin.value(),
                    "until": (
                        self.until_edit.date().toString("yyyy-MM-dd")
                        if self.until_edit.date().isValid()
                        else ""
                    ),
                    "subchat": self.subchat_edit.text().strip(),
                    "user": self.user_edit.text().strip(),
                    "debug": self.debug_chk.isChecked(),
                    "sort": self.sort_combo.currentData() or "asc",
                    "split": self.split_combo.currentData() or "",
                }
            )

            # Save settings to config
            config.set("form_settings", settings)
            config.save()

        except Exception as e:
            logging.error(f"Error saving settings: {e}", exc_info=True)

    def toggle_settings_visibility(self, index: QModelIndex):
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

    def _browse_output(self):
        """Open a file dialog to select the output file."""
        default_dir = get_downloads_dir()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Output As",
            str(default_dir / "output.txt"),
            "Text Files (*.txt);;All Files (*)",
        )

        if file_path:
            self.output_edit.setText(file_path)

    def start_download(self):
        """Start the download process."""
        # Save settings first
        self._save_settings()

        # Validate input
        chat = self.chat_edit.text().strip()
        if not chat:
            QMessageBox.warning(
                self, "Error", "Please enter a chat ID, username, or link."
            )
            return

        # Build command arguments - chat is a positional argument, not a flag
        cmd_args = [chat]

        # Get or generate output path
        output_path = self.output_edit.text().strip()
        if output_path:
            cmd_args.extend(["--output", output_path])

        # Add optional arguments
        limit = self.limit_spin.value()
        if limit > 0:
            cmd_args.extend(["--limit", str(limit)])

        if self.from_edit.date().isValid():
            from_date = self.from_edit.date().toString("yyyy-MM-dd")
            cmd_args.extend(["--from", from_date])

        last_days = self.last_days_spin.value()
        if last_days > 0:
            cmd_args.extend(["--last-days", str(last_days)])

        if self.until_edit.date().isValid():
            until_date = self.until_edit.date().toString("yyyy-MM-dd")
            cmd_args.extend(["--until", until_date])

        subchat = self.subchat_edit.text().strip()
        if subchat:
            cmd_args.extend(["--subchat", subchat])

        user = self.user_edit.text().strip()
        if user:
            cmd_args.extend(["--user", user])

        sort_order = self.sort_combo.currentData()
        if sort_order:
            cmd_args.extend(["--sort", sort_order])

        split_by = self.split_combo.currentData()
        if split_by:
            cmd_args.extend(["--split", split_by])

        if self.debug_chk.isChecked():
            cmd_args.append("--debug")

        # Update UI for download start
        self._set_download_in_progress(True)

        # Emit signal with command arguments and output directory
        self.download_started.emit(cmd_args, output_path)

    def stop_download(self):
        """Stop the download process."""
        self.download_stopped.emit()

    def on_download_finished(self, success: bool, was_stopped: bool = False):
        """Handle download completion.

        Args:
            success: Whether the download completed successfully
            was_stopped: Whether the download was stopped by the user
        """
        # Save settings first
        self._save_settings()

        # Update UI
        self._set_download_in_progress(False)

        if was_stopped:
            # User stopped the download
            QMessageBox.information(
                self,
                "Download Stopped",
                "The download was stopped by the user. Partial results have been saved.",
            )
        elif success:
            # Download completed successfully
            QMessageBox.information(
                self, "Download Complete", "The download has completed successfully!"
            )
        else:
            # Download failed
            QMessageBox.critical(
                self,
                "Download Failed",
                "The download failed. Please check the log for details.",
            )

    def update_progress(self, current: int, total: int):
        """Update the progress bar with download progress.

        Args:
            current: Current progress value
            total: Total value for completion
        """
        if not self.progress.isVisible():
            self.progress.setVisible(True)

        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(current)
            self.progress.setFormat(
                f"Downloading... {current}/{total} ({current/total*100:.1f}%)"
            )
        else:
            # Indeterminate mode
            self.progress.setMaximum(0)
            self.progress.setFormat("Downloading...")

    def _set_download_in_progress(self, in_progress: bool):
        """Update UI elements based on download state.

        Args:
            in_progress: Whether a download is in progress
        """
        self.start_btn.setEnabled(not in_progress)
        self.stop_btn.setEnabled(in_progress)

        if in_progress:
            self.progress.setVisible(True)
            self.progress.setMaximum(0)  # Indeterminate mode
            self.progress.setFormat("Downloading...")
            self._start_loading_animation()
        else:
            self.progress.setMaximum(100)
            self.progress.setValue(100)
            self.progress.setFormat("Completed")
            self._stop_loading_animation()

            # Reset to idle state after a short delay
            QTimer.singleShot(2000, self._reset_progress_to_idle)

    def update_progress(self, current: int, total: int):
        """Update the progress bar with current and total values.

        Args:
            current: Current progress value
            total: Total value for completion
        """
        if total > 0:
            # Switch to determinate mode if not already
            if self.progress.maximum() != total:
                self.progress.setMaximum(total)
                self._stop_progress_animation()

            self.progress.setValue(current)
            percent = (current / total) * 100
            self.progress.setFormat(f"Downloading... {percent:.1f}%")
        else:
            # Fall back to indeterminate mode if we don't have a total
            self.progress.setMaximum(0)
            self.progress.setFormat("Downloading...")
            self._start_progress_animation()

    def _start_progress_animation(self):
        """Start the progress bar animation for indeterminate mode."""
        if self.progress.maximum() == 0:  # Only for indeterminate mode
            self.progress_animation.start()

    def _stop_progress_animation(self):
        """Stop the progress bar animation."""
        if self.progress_animation.state() == QPropertyAnimation.Running:
            self.progress_animation.stop()

    def _reset_progress_to_idle(self):
        """Reset progress bar to idle state."""
        self.progress.setValue(0)
        self.progress.setFormat("Idle")
        self.progress.setVisible(False)
        self._reset_progress_style()

    def _reset_progress_style(self):
        """Reset progress bar style to default."""
        self.progress.setStyleSheet(
            """
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 4px;
                text-align: center;
                background-color: #f5f5f5;
                height: 24px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 2px;
                width: 10px;
                margin: 0.5px;
            }
            QProgressBar:indeterminate::chunk {
                background-color: #4CAF50;
                border-radius: 2px;
                width: 10px;
                margin: 0.5px;
            }
        """
        )

    def _start_loading_animation(self):
        """Show the loading indicator."""
        self.loading_label.setText("…")
        self.loading_label.show()

    def _stop_loading_animation(self):
        """Hide the loading indicator."""
        self.loading_label.hide()
        self.loading_label.setText("")

    def save_settings(self, settings: Dict[str, Any]):
        """Save tab settings to a dictionary.

        Args:
            settings: Dictionary to save settings to
        """
        settings["chat"] = self.chat_edit.text()
        settings["output"] = self.output_edit.text()
        settings["limit"] = self.limit_spin.value()
        settings["from_date"] = (
            self.from_edit.date().toString("yyyy-MM-dd")
            if self.from_edit.date().isValid()
            else ""
        )
        settings["last_days"] = self.last_days_spin.value()
        settings["until"] = (
            self.until_edit.date().toString("yyyy-MM-dd")
            if self.until_edit.date().isValid()
            else ""
        )
        settings["subchat"] = self.subchat_edit.text()
        settings["user"] = self.user_edit.text()
        settings["debug"] = self.debug_chk.isChecked()
        settings["sort"] = self.sort_combo.currentData() or "asc"
        settings["split"] = self.split_combo.currentData() or ""

    def load_settings(self, settings: Dict[str, Any]):
        """Load tab settings from a dictionary.

        Args:
            settings: Dictionary containing settings
        """
        self.chat_edit.setText(settings.get("chat", ""))
        self.output_edit.setText(settings.get("output", ""))
        self.limit_spin.setValue(int(settings.get("limit", 0)))

        from_date = settings.get("from_date", "")
        if from_date:
            self.from_edit.setDate(QDate.fromString(from_date, "yyyy-MM-dd"))

        self.last_days_spin.setValue(int(settings.get("last_days", 0)))

        until_date = settings.get("until", "")
        if until_date:
            self.until_edit.setDate(QDate.fromString(until_date, "yyyy-MM-dd"))

        self.subchat_edit.setText(settings.get("subchat", ""))
        self.user_edit.setText(settings.get("user", ""))
        self.debug_chk.setChecked(bool(settings.get("debug", False)))

        sort_order = settings.get("sort", "asc")
        index = 0 if sort_order == "asc" else 1
        self.sort_combo.setCurrentIndex(index)

        split_by = settings.get("split") or None
        split_index = (
            self.split_combo.findData(split_by)
            if split_by is not None
            else self.split_combo.findData(None)
        )
        if split_index >= 0:
            self.split_combo.setCurrentIndex(split_index)

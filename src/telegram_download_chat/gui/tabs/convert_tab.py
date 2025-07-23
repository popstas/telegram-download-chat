"""Convert tab for the Telegram Download Chat GUI."""
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from telegram_download_chat.gui.utils.file_utils import ensure_dir_exists
from telegram_download_chat.paths import get_app_dir, get_downloads_dir


class ConvertTab(QWidget):
    """Tab for converting between different file formats."""

    # Signal emitted when conversion starts
    conversion_started = Signal(list, str, dict)  # files, output_dir, options

    # Signal emitted when conversion is stopped
    conversion_stopped = Signal()

    def __init__(self, parent=None):
        """Initialize the convert tab.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self._config = QSettings("TelegramDownloadChat", "ConvertTab")
        self._setup_ui()
        self._conversion_in_progress = False
        self._load_config()

    def _load_config(self):
        """Load configuration from settings."""
        # Load last used input file if it exists
        last_input = self._config.value("last_input_file")
        if last_input and Path(last_input).exists():
            self.file_edit.setText(last_input)

        # Load last used output directory if it exists
        last_output = self._config.value("last_output_dir")
        if last_output:
            self.dir_edit.setText(last_output)

    def _save_config(self):
        """Save current configuration to settings."""
        if self.file_edit.text():
            self._config.setValue("last_input_file", self.file_edit.text())
        if self.dir_edit.text():
            self._config.setValue("last_output_dir", self.dir_edit.text())

    def _setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        # Input files group
        input_group = QGroupBox("Input Files")
        input_layout = QVBoxLayout(input_group)

        # Input file selection
        file_layout = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        self.file_edit.setPlaceholderText("Select a file to convert...")

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_file)

        file_layout.addWidget(self.file_edit, 1)
        file_layout.addWidget(browse_btn)

        input_layout.addLayout(file_layout)
        layout.addWidget(input_group)

        # Output options group
        output_group = QGroupBox("Output Options")
        output_layout = QFormLayout(output_group)

        # Output directory
        dir_layout = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("Select output directory...")

        dir_btn = QPushButton("Browse...")
        dir_btn.clicked.connect(self._browse_dir)

        dir_layout.addWidget(self.dir_edit, 1)
        dir_layout.addWidget(dir_btn)
        output_layout.addRow("Output Directory:", dir_layout)

        # Filter options
        filter_group = QGroupBox("Filter Options")
        filter_layout = QFormLayout(filter_group)

        # Subchat filter
        self.subchat_edit = QLineEdit()
        self.subchat_edit.setPlaceholderText("Subchat ID or URL (optional)")
        filter_layout.addRow("Subchat:", self.subchat_edit)

        # Subchat name
        self.subchat_name_edit = QLineEdit()
        self.subchat_name_edit.setPlaceholderText("Optional name for subchat directory")
        filter_layout.addRow("Subchat Name:", self.subchat_name_edit)

        # User filter
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("User ID or username (optional)")
        filter_layout.addRow("Filter by User:", self.user_edit)

        layout.addWidget(filter_group)

        # Split options
        split_group = QGroupBox("Split Options")
        split_layout = QVBoxLayout(split_group)

        self.split_combo = QComboBox()
        self.split_combo.addItem("Don't split", None)
        self.split_combo.addItem("By Month", "month")
        self.split_combo.addItem("By Year", "year")

        split_layout.addWidget(QLabel("Split output by:"))
        split_layout.addWidget(self.split_combo)

        layout.addWidget(split_group)

        layout.addWidget(output_group, 1)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # Buttons
        btn_layout = QHBoxLayout()

        self.convert_btn = QPushButton("Convert")
        self.convert_btn.clicked.connect(self._on_convert_clicked)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop_clicked)

        btn_layout.addStretch()
        btn_layout.addWidget(self.convert_btn)
        btn_layout.addWidget(self.stop_btn)

        layout.addLayout(btn_layout)

        # Set default output directory
        self.dir_edit.setText(str(get_downloads_dir()))

    def _browse_file(self):
        """Open file dialog to select input file."""
        # Start from last used directory or default location
        start_dir = self._config.value("last_input_dir", str(get_downloads_dir()))

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select JSON File to Convert",
            start_dir,
            "JSON Files (*.json);;All Files (*)",
        )

        if file_path:
            self.file_edit.setText(file_path)

            # Save the directory for next time
            file = Path(file_path)
            self._config.setValue("last_input_dir", str(file.parent))

            # Suggest output directory based on file's parent directory if not set
            if not self.dir_edit.text():
                self.dir_edit.setText(str(file.parent))

            # Save the selected file to config
            self._save_config()

    def _browse_dir(self):
        """Open directory dialog to select output directory."""
        # Start from last used output directory or current directory
        start_dir = self.dir_edit.text() or self._config.value(
            "last_output_dir", str(Path.home())
        )

        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", start_dir
        )

        if dir_path:
            self.dir_edit.setText(dir_path)
            # Save the selected directory
            self._save_config()

    def _on_convert_clicked(self):
        """Handle convert button click."""
        try:
            # Get selected file
            file_path = self.file_edit.text().strip()
            if not file_path:
                QMessageBox.warning(self, "Error", "Please select a file to convert.")
                return

            if not Path(file_path).exists():
                QMessageBox.warning(self, "Error", "The selected file does not exist.")
                return

            # Get output directory
            output_dir = self.dir_edit.text().strip()
            if not output_dir:
                QMessageBox.warning(self, "Error", "Please select an output directory.")
                return

            # Create output directory if it doesn't exist
            try:
                ensure_dir_exists(output_dir)
            except Exception as e:
                QMessageBox.critical(
                    self, "Error", f"Failed to create output directory: {e}"
                )
                return

            # Save current configuration
            self._save_config()

            # Prepare options
            options = {
                "subchat": self.subchat_edit.text().strip() or None,
                "subchat_name": self.subchat_name_edit.text().strip() or None,
                "user": self.user_edit.text().strip() or None,
                "split": self.split_combo.currentData(),
            }

            # Update UI for conversion
            self._set_conversion_in_progress(True)

            # Start conversion with single file
            self.conversion_started.emit([file_path], output_dir, options)

        except Exception as e:
            self._set_conversion_in_progress(False)
            QMessageBox.critical(self, "Error", f"Failed to start conversion: {str(e)}")

    def _on_stop_clicked(self):
        """Handle stop button click."""
        try:
            self.conversion_stopped.emit()
            self._set_conversion_in_progress(False)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to stop conversion: {str(e)}")

    def _set_conversion_in_progress(self, in_progress: bool):
        """Update UI for conversion state.

        Args:
            in_progress: Whether a conversion is in progress
        """
        self._conversion_in_progress = in_progress
        self.convert_btn.setEnabled(not in_progress)
        self.stop_btn.setEnabled(in_progress)
        self.progress.setVisible(in_progress)
        if in_progress:
            self.progress.setRange(0, 0)  # Indeterminate progress
        else:
            self.progress.setRange(0, 1)  # Reset progress bar

    def update_progress(self, current: int, total: int):
        """Update progress bar.

        Args:
            current: Current progress
            total: Total steps
        """
        self.progress.setRange(0, total)
        self.progress.setValue(current)

    def conversion_complete(self, success: bool, message: str = ""):
        """Handle conversion completion.

        Args:
            success: Whether the conversion was successful
            message: Status message
        """
        self._set_conversion_in_progress(False)

        if success:
            QMessageBox.information(
                self,
                "Conversion Complete",
                message or "Conversion completed successfully!",
            )
        else:
            QMessageBox.critical(
                self,
                "Conversion Failed",
                message or "An error occurred during conversion.",
            )

"""File list widget for the Telegram Download Chat GUI."""
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..utils.file_utils import get_file_size


class FileListWidget(QWidget):
    """A widget for displaying and managing a list of files."""

    # Signal emitted when a file is selected
    file_selected = Signal(str)

    # Signal emitted when the open button is clicked
    open_requested = Signal()

    # Signal emitted when the copy button is clicked
    copy_requested = Signal()

    def __init__(self, parent=None):
        """Initialize the file list widget.

        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Set up the user interface."""
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        # Files label
        self.files_label = QLabel("Files (0):")
        header.addWidget(self.files_label)

        # Add stretch to push buttons to the right
        header.addStretch()

        # Copy button
        self.copy_btn = QPushButton("Copy to clipboard")
        self.copy_btn.setEnabled(False)
        self._style_copy_button()
        header.addWidget(self.copy_btn)

        # Open button
        self.open_btn = QPushButton("Open downloads")
        header.addWidget(self.open_btn)

        layout.addLayout(header)

        # File list
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.file_list.setIconSize(QSize(32, 32))
        layout.addWidget(self.file_list)

        # Preview header
        preview_header = QHBoxLayout()
        preview_header.setContentsMargins(0, 5, 0, 0)

        # Preview label
        preview_label = QLabel("Preview (first 100 lines):")
        preview_header.addWidget(preview_label)

        # File size label
        self.file_size_label = QLabel("Size: 0 B")
        preview_header.addWidget(self.file_size_label)

        layout.addLayout(preview_header)

        # Preview area
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAcceptDrops(False)
        layout.addWidget(self.preview)

    def _style_copy_button(self):
        """Apply styles to the copy button."""
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

    def _connect_signals(self):
        """Connect signals to slots."""
        self.file_list.currentItemChanged.connect(self._on_file_selected)
        self.open_btn.clicked.connect(self.open_requested)
        self.copy_btn.clicked.connect(self.copy_requested)

    def add_file(self, file_path: str):
        """Add a file to the list.

        Args:
            file_path: Path to the file to add
        """
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return

        # Check if file already exists in the list
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item and item.data(Qt.UserRole) == str(path):
                return  # File already in the list

        # Create list item
        item = QListWidgetItem()
        item.setText(path.name)
        item.setData(Qt.UserRole, str(path))

        # Set icon based on file extension
        icon_name = self._get_icon_name(path.suffix.lower())
        icon = QIcon.fromTheme(icon_name, QIcon(f":/icons/{icon_name}.png"))
        item.setIcon(icon)

        # Add to list
        self.file_list.addItem(item)
        self._update_files_label()

        # Select the first file added
        if self.file_list.count() == 1:
            self.file_list.setCurrentItem(item)

    def _get_icon_name(self, extension: str) -> str:
        """Get the appropriate icon name for a file extension.

        Args:
            extension: File extension (with dot, e.g., '.txt')

        Returns:
            str: Icon name
        """
        icon_map = {
            ".txt": "text-plain",
            ".json": "text-json",
            ".pdf": "application-pdf",
            ".zip": "application-zip",
            ".jpg": "image-jpeg",
            ".jpeg": "image-jpeg",
            ".png": "image-png",
            ".gif": "image-gif",
            ".mp3": "audio-mp3",
            ".mp4": "video-mp4",
            ".doc": "application-msword",
            ".docx": "application-vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application-vnd.ms-excel",
            ".xlsx": "application-vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".ppt": "application-vnd.ms-powerpoint",
            ".pptx": "application-vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        return icon_map.get(extension, "text-x-generic")

    def set_files(self, file_paths: List[str]):
        """Set the list of files to display.

        Args:
            file_paths: List of file paths to display
        """
        self.clear_files()
        for file_path in file_paths:
            self.add_file(file_path)

    def clear_files(self):
        """Clear all files from the list."""
        self.file_list.clear()
        self.preview.clear()
        self.file_size_label.setText("Size: 0 B")
        self._update_files_label()

    def get_selected_file(self) -> Optional[str]:
        """Get the currently selected file path.

        Returns:
            Optional[str]: Path to the selected file, or None if no file is selected
        """
        item = self.file_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def set_preview_text(self, text: str):
        """Set the preview text.

        Args:
            text: Text to display in the preview
        """
        self.preview.setPlainText(text)

    def set_file_size(self, size: str):
        """Set the file size text.

        Args:
            size: File size as a string (e.g., "1.2 MB")
        """
        self.file_size_label.setText(f"Size: {size}")

    def _on_file_selected(
        self, current: QListWidgetItem, previous: QListWidgetItem = None
    ):
        """Handle file selection change.

        Args:
            current: Currently selected item
            previous: Previously selected item
        """
        if current:
            file_path = current.data(Qt.UserRole)
            self.copy_btn.setEnabled(True)
            self.file_selected.emit(file_path)
        else:
            self.copy_btn.setEnabled(False)

    def _update_files_label(self):
        """Update the files count label."""
        count = self.file_list.count()
        self.files_label.setText(f"Files ({count}):")
        self.copy_btn.setEnabled(count > 0)

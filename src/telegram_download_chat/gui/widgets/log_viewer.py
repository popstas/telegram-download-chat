"""Log viewer widget for the Telegram Download Chat GUI."""
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class LogViewer(QWidget):
    """A widget for displaying and managing log messages."""

    # Signal emitted when the log is copied to clipboard
    log_copied = Signal()

    def __init__(self, parent=None):
        """Initialize the log viewer.

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

        # Log header with controls
        self._setup_header(layout)

        # Log text area
        self._setup_log_area(layout)

        # Set initial state (collapsed by default)
        self._is_expanded = False
        self._update_expand_state()

    def _setup_header(self, parent_layout):
        """Set up the log header with controls.

        Args:
            parent_layout: Parent layout to add the header to
        """
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        # Log label
        label = QLabel("Log:")
        header.addWidget(label)

        # Copy button
        self.copy_btn = QPushButton()
        self.copy_btn.setToolTip("Copy log to clipboard")
        self.copy_btn.setFixedSize(24, 24)
        self.copy_btn.setContentsMargins(0, 0, 0, 0)

        # Try to use system theme icon first, fallback to text
        copy_icon = QIcon.fromTheme("edit-copy")
        if copy_icon.isNull():
            # Try to load from resources
            try:
                from ... import resources_rc  # Import resources if available

                copy_icon = QIcon(":/icons/copy.png")
            except ImportError:
                # Fallback to text if no icon is available
                self.copy_btn.setText("Copy")
                self.copy_btn.setFixedWidth(60)

        if not copy_icon.isNull():
            self.copy_btn.setIcon(copy_icon)
            self.copy_btn.setIconSize(QSize(16, 16))

        self.copy_btn.setStyleSheet(
            """
            QPushButton {
                border: 1px solid #555;
                padding: 2px 6px;
                background: #505050;
                color: #e0e0e0;
                border-radius: 3px;
                padding: 0;
                margin: 0;
            }
            QPushButton:hover {
                background: #606060;
                border-color: #777;
            }
            QPushButton:pressed {
                background: #404040;
            }
            QPushButton:disabled {
                color: #888;
                background: #404040;
                border-color: #555;
            }
        """
        )
        header.addWidget(self.copy_btn)

        # Expand/collapse button
        self.expand_btn = QPushButton("+")
        self.expand_btn.setToolTip("Expand log")
        self.expand_btn.setFixedSize(24, 24)
        self.expand_btn.setStyleSheet(
            """
            QPushButton {
                border: 1px solid #555;
                padding: 0px;
                background: #505050;
                color: #e0e0e0;
                font-weight: bold;
                font-size: 14px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: #606060;
                border-color: #777;
            }
        """
        )
        header.addWidget(self.expand_btn)

        # Add stretch to push buttons to the right
        header.addStretch()

        parent_layout.addLayout(header)

    def _setup_log_area(self, parent_layout):
        """Set up the log text area.

        Args:
            parent_layout: Parent layout to add the log area to
        """
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.NoWrap)
        self.log_text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.log_text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Set fixed height for one line and enable scrolling
        font = self.log_text.font()
        font.setPointSize(12)  # Larger font size
        self.log_text.setFont(font)

        # Calculate heights
        self._collapsed_height = int(self.log_text.fontMetrics().height() * 1.5)
        self._expanded_height = int(self.log_text.fontMetrics().height() * 10.5)

        parent_layout.addWidget(self.log_text)

    def _connect_signals(self):
        """Connect signals to slots."""
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        self.expand_btn.clicked.connect(self.toggle_expand)

        # Auto-scroll to bottom when text changes
        self.log_text.textChanged.connect(
            lambda: self.log_text.verticalScrollBar().setValue(
                self.log_text.verticalScrollBar().maximum()
            )
        )

    def append(self, text: str):
        """Append text to the log.

        Args:
            text: Text to append
        """
        self.log_text.append(text)

    def clear(self):
        """Clear the log."""
        self.log_text.clear()

    def copy_to_clipboard(self):
        """Copy the log content to the clipboard."""
        text = self.log_text.toPlainText()
        if text:
            # Get the application clipboard
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(text)

            # Visual feedback
            original_style = self.copy_btn.styleSheet()
            self.copy_btn.setStyleSheet(
                """
                QPushButton {
                    border: 1px solid #4CAF50 !important;
                    background: #81C784 !important;
                    color: white !important;
                    border-radius: 3px;
                    padding: 0;
                    margin: 0;
                }
            """
            )

            # Reset style after 1 second
            QTimer.singleShot(1000, lambda: self.copy_btn.setStyleSheet(original_style))

            # Emit signal to notify parent
            self.log_copied.emit()

    def toggle_expand(self):
        """Toggle between expanded and collapsed state."""
        self._is_expanded = not self._is_expanded
        self._update_expand_state()

    def _update_expand_state(self):
        """Update the UI to reflect the current expand state."""
        if self._is_expanded:
            self.log_text.setFixedHeight(self._expanded_height)
            self.expand_btn.setText("−")  # Minus sign
            self.expand_btn.setToolTip("Collapse log")
        else:
            self.log_text.setFixedHeight(self._collapsed_height)
            self.expand_btn.setText("+")  # Plus sign
            self.expand_btn.setToolTip("Expand log")

    def is_expanded(self) -> bool:
        """Check if the log is expanded.

        Returns:
            bool: True if expanded, False if collapsed
        """
        return self._is_expanded

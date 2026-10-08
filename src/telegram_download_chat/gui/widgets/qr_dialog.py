"""QR login dialog: shows the code to scan and the login status."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)

from ...core.qr_login import qr_code_matrix

DEFAULT_MODULE_PX = 6


def qr_pixmap(data: str, module_px: int = DEFAULT_MODULE_PX) -> QPixmap:
    """Render ``data`` as a QR code pixmap, black modules on white.

    Drawn from the module matrix rather than an image file, so no image
    library is needed and the polarity cannot be flipped by a dark theme.
    """
    matrix = qr_code_matrix(data)
    size = len(matrix)
    image = QImage(size, size, QImage.Format_RGB32)
    dark = QColor(Qt.black).rgb()
    light = QColor(Qt.white).rgb()
    for y, row in enumerate(matrix):
        for x, module in enumerate(row):
            image.setPixel(x, y, dark if module else light)

    return QPixmap.fromImage(
        image.scaled(size * module_px, size * module_px, mode=Qt.FastTransformation)
    )


class QrLoginDialog(QDialog):
    """Modeless dialog showing the QR code while the login is pending."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log in with a QR code")

        layout = QVBoxLayout(self)

        self.hint_label = QLabel(
            "In Telegram on your phone: Settings -> Devices -> Link Desktop Device,\n"
            "then scan this code. It refreshes until you scan it."
        )
        layout.addWidget(self.hint_label)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.qr_label)

        self.url_label = QLabel()
        self.url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.url_label.setWordWrap(True)
        layout.addWidget(self.url_label)

        self.status_label = QLabel("Waiting for the code to be scanned...")
        layout.addWidget(self.status_label)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def set_code(self, url: str) -> None:
        """Show a freshly issued login code."""
        self.qr_label.setPixmap(qr_pixmap(url))
        self.url_label.setText(url)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

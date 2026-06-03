"""Shared GUI styling helpers.

Centralizes small Qt stylesheet snippets so the look stays consistent across
tabs without duplicating CSS in every widget. Currently this provides the
checkbox styling used on the download tab: an unchecked checkbox indicator that
matches the background color of the text inputs (QLineEdit), so empty
checkboxes read as gray instead of standing out as bright white boxes. The
checked state is intentionally left to the native (Fusion) style.
"""

from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QCheckBox, QWidget


def input_background_color(widget: Optional[QWidget] = None) -> str:
    """Return the hex color used as the background of input widgets.

    QLineEdit paints its background using the palette's ``Base`` role, so
    reading that role yields the exact color the text inputs use. When a
    ``widget`` is given its palette is used; otherwise the application palette
    is consulted.

    Args:
        widget: Optional widget whose palette should be sampled.

    Returns:
        The background color as a ``#rrggbb`` hex string.
    """
    palette = widget.palette() if widget is not None else QApplication.palette()
    return palette.color(QPalette.Base).name()


def checkbox_stylesheet(widget: Optional[QWidget] = None) -> str:
    """Build a stylesheet that makes unchecked checkbox indicators gray.

    The unchecked indicator is given the same background color as the text
    inputs (QLineEdit's ``Base`` color) plus a subtle border, so an empty
    checkbox matches the surrounding inputs. The checked state is deliberately
    not styled so it keeps its normal native appearance (including the
    checkmark).

    Args:
        widget: Optional widget whose palette should be sampled.

    Returns:
        A Qt stylesheet string targeting ``QCheckBox::indicator:unchecked``.
    """
    palette = widget.palette() if widget is not None else QApplication.palette()
    base = palette.color(QPalette.Base).name()
    border = palette.color(QPalette.Mid).name()
    return (
        "QCheckBox::indicator:unchecked {\n"
        f"    background-color: {base};\n"
        f"    border: 1px solid {border};\n"
        "    border-radius: 3px;\n"
        "}\n"
    )


def style_checkboxes(
    checkboxes: Iterable[QCheckBox], widget: Optional[QWidget] = None
) -> None:
    """Apply the shared unchecked-gray stylesheet to each checkbox.

    Args:
        checkboxes: The checkboxes to style.
        widget: Optional widget whose palette should be sampled for colors.
    """
    sheet = checkbox_stylesheet(widget)
    for checkbox in checkboxes:
        checkbox.setStyleSheet(sheet)


# The green used for the filled portion of progress bars. A single source of
# truth so every progress bar in the GUI reads the same; the default (Fusion)
# progress chunk can render as a flat red/highlight color depending on the
# palette, which reads as an error rather than healthy progress.
PROGRESS_GREEN = "#4CAF50"


def progress_bar_stylesheet(color: str = PROGRESS_GREEN) -> str:
    """Build the shared stylesheet for a determinate/indeterminate progress bar.

    The filled chunk (and the indeterminate sweep) are painted green so progress
    reads as healthy rather than as the default highlight/red. A rounded track,
    centered text, and a thin chunk gap give a clearer "progress line" than the
    flat native bar.

    Args:
        color: The chunk fill color as a ``#rrggbb`` hex string.

    Returns:
        A Qt stylesheet string targeting ``QProgressBar`` and its chunk.
    """
    return (
        "QProgressBar {\n"
        "    border: 1px solid #cccccc;\n"
        "    border-radius: 4px;\n"
        "    text-align: center;\n"
        "    background-color: #f5f5f5;\n"
        "    height: 24px;\n"
        "}\n"
        "QProgressBar::chunk {\n"
        f"    background-color: {color};\n"
        "    border-radius: 2px;\n"
        "    width: 10px;\n"
        "    margin: 0.5px;\n"
        "}\n"
        "QProgressBar:indeterminate::chunk {\n"
        f"    background-color: {color};\n"
        "    border-radius: 2px;\n"
        "    width: 10px;\n"
        "    margin: 0.5px;\n"
        "}\n"
    )


def style_progress_bar(progress_bar, color: str = PROGRESS_GREEN) -> None:
    """Apply the shared green progress-bar stylesheet to ``progress_bar``.

    Args:
        progress_bar: The ``QProgressBar`` to style.
        color: The chunk fill color as a ``#rrggbb`` hex string.
    """
    progress_bar.setStyleSheet(progress_bar_stylesheet(color))

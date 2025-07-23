"""
Tab widgets for the Telegram Download Chat GUI.

This package contains the tab widgets used in the main window.
"""

from .convert_tab import ConvertTab  # Will be implemented later
from .download_tab import DownloadTab
from .settings_tab import SettingsTab

__all__ = ["DownloadTab", "SettingsTab", "ConvertTab"]

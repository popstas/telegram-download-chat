"""Main entry point for the Telegram Download Chat GUI."""
import sys
import logging
import signal
from pathlib import Path
import os

from PySide6.QtWidgets import QApplication, QSplashScreen, QMessageBox
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QIcon

from telegram_download_chat import __version__
from telegram_download_chat.gui.windows.main_window import MainWindow
from telegram_download_chat.gui.utils.config import ConfigManager


def get_icon_path():
    """Get the path to the application icon.
    
    Returns:
        str: Path to the icon file, or None if not found
    """
    try:
        # Check if running in PyInstaller bundle
        if getattr(sys, 'frozen', False):
            # For PyInstaller bundled app
            base_path = sys._MEIPASS
            icon_path = os.path.join(base_path, 'assets', 'icon.ico')
            if os.path.exists(icon_path):
                return os.path.normpath(icon_path)
        
        # Get the project root directory (4 levels up from gui/main.py)
        project_root = Path(__file__).parent.parent.parent.parent
        
        # Check in the assets directory at the project root
        icon_path = project_root / 'assets' / 'icon.ico'
        if icon_path.exists():
            return str(icon_path)
            
        # Check in the package directory
        icon_path = Path(__file__).parent / 'assets' / 'icon.ico'
        if icon_path.exists():
            return str(icon_path)
            
        # For development - check additional possible locations
        paths = [
            # Relative to script location
            os.path.join(os.path.dirname(__file__), '..', '..', 'assets', 'icon.ico'),
            # Relative to package location
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'assets', 'icon.ico'),
            # In the package directory
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'icon.ico'),
            # In the root assets directory
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'assets', 'icon.ico')
        ]
        
        # Log all paths that were checked
        logging.info(f"Checking for icon in: {paths}")
        
        for path in paths:
            if os.path.exists(path):
                return os.path.normpath(path)
                
        logging.warning("Icon not found in any of the expected locations")
        return None
    except Exception as e:
        logging.warning(f"Error finding icon path: {e}", exc_info=True)
        return None


def setup_logging():
    """Set up application logging."""
    # Create logs directory if it doesn't exist
    from telegram_download_chat.paths import get_app_dir
    log_dir = get_app_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Clear existing handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Set up file handler
    log_file = log_dir / "telegram_download_chat.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # Set up console handler with DEBUG level
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    
    # Create formatter and add it to the handlers
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'  # Format without milliseconds
    formatter = logging.Formatter(log_format, datefmt=date_format)
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers to the root logger
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Set log level for external libraries
    logging.getLogger('telethon').setLevel(logging.WARNING)
    
    # Enable debug logging for our application
    logging.getLogger('telegram_download_chat').setLevel(logging.INFO)
    logging.debug("Logging system initialized with DEBUG level")


def show_splash_screen():
    """Show a splash screen while the application is loading."""
    try:
        # Try to load splash image from assets
        assets_dir = Path(__file__).parent.parent / "assets"
        splash_path = assets_dir / "splash.png"
        
        if splash_path.exists():
            pixmap = QPixmap(str(splash_path))
            splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint)
            splash.show()
            return splash
    except Exception as e:
        logging.warning(f"Failed to show splash screen: {e}")
    
    return None


def main():
    """Main entry point for the application."""
    # Set up logging
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Set up signal handlers for clean shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    try:
        # Create application
        app = QApplication(sys.argv)
        app.setApplicationName("Telegram Download Chat")
        app.setApplicationVersion(__version__)
        app.setOrganizationName("TelegramDownloadChat")
        app.setStyle("Fusion")  # Use Fusion style for consistent look across platforms
        
        # Show splash screen
        splash = show_splash_screen()
        
        # Initialize config
        config = ConfigManager()
        config.load()
        
        # Create and show main window
        main_window = MainWindow()
        
        # Set up application icon
        try:
            icon_path = get_icon_path()
            if icon_path:
                app_icon = QIcon(icon_path)
                app.setWindowIcon(app_icon)
                
                # Set application ID for Windows taskbar
                if sys.platform == 'win32':
                    import ctypes
                    try:
                        myappid = 'telegram.download.chat.gui.1.0'  # Must be unique per application
                        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
                    except Exception as e:
                        logger.warning(f"Could not set AppUserModelID: {e}")
                
            else:
                logger.warning("Application icon not found in any of the expected locations")
        except Exception as e:
            logger.warning(f"Failed to set application icon: {e}", exc_info=True)
        
        # Show main window and close splash screen after a short delay
        def show_main_window():
            main_window.show()
            if splash:
                splash.finish(main_window)
        
        # Use a timer to show the main window after the event loop starts
        QTimer.singleShot(100, show_main_window)
        
        # Run the application
        sys.exit(app.exec())
        
    except Exception as e:
        logger.exception("Fatal error in application:")
        QMessageBox.critical(
            None,
            "Fatal Error",
            f"A fatal error occurred:\n{str(e)}\n\nCheck the log file for more details."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

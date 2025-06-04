"""Main window for the Telegram Download Chat GUI."""
import os
import sys
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QStatusBar, QMenuBar, QMenu, QFileDialog, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, QSize, Signal, QTimer, QObject, QEvent
from PySide6.QtGui import QAction, QIcon, QCloseEvent, QKeySequence, QShortcut

# Import our custom widgets and tabs
from telegram_download_chat.gui.tabs.download_tab import DownloadTab
from telegram_download_chat.gui.tabs.settings_tab import SettingsTab
from telegram_download_chat.gui.tabs.convert_tab import ConvertTab
from telegram_download_chat.gui.worker import WorkerThread
from telegram_download_chat.gui.utils.config import ConfigManager
from telegram_download_chat.gui.widgets.log_viewer import LogViewer
from telegram_download_chat.gui.widgets.file_list import FileListWidget
from telegram_download_chat.paths import get_downloads_dir


class MainWindow(QMainWindow):
    """Main window for the Telegram Download Chat application."""
    
    # Signal emitted when the window is about to close
    about_to_close = Signal()
    
    def __init__(self, parent=None):
        """Initialize the main window.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.config = ConfigManager()
        self.worker_thread = None
        self._setup_ui()
        self._connect_signals()
        self._load_settings()
        
        # Set window title
        self.setWindowTitle("Telegram Download Chat")
        
        # Set window icon if available
        try:
            from telegram_download_chat.gui.main import get_icon_path
            icon_path = get_icon_path()
            if icon_path:
                self.setWindowIcon(QIcon(icon_path))
                
                # Set application ID for Windows taskbar (if not already set by main.py)
                if sys.platform == 'win32' and not hasattr(self, '_app_id_set'):
                    try:
                        import ctypes
                        myappid = 'telegram.download.chat.gui.1.0'
                        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
                        self._app_id_set = True
                    except Exception as e:
                        logging.warning(f"Could not set AppUserModelID: {e}")
                
            else:
                logging.warning("Window icon not found in any of the expected locations")
        except Exception as e:
            logging.warning(f"Failed to set window icon: {e}", exc_info=True)
    
    def _setup_ui(self):
        """Set up the user interface."""
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # Create menu bar
        self._create_menu_bar()
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # Create tabs
        self._create_tabs()
        
        # Create log viewer
        self.log_viewer = LogViewer()
        main_layout.addWidget(self.log_viewer)
        
        # Create file list widget
        self.file_list = FileListWidget()
        main_layout.addWidget(self.file_list, 1)  # Add stretch factor to make it expand
        
        # Create status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        
        # Set initial size
        self.resize(900, 700)
    
    def _create_menu_bar(self):
        """Create the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        # Exit action
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        
        # Settings action
        settings_action = QAction("&Settings", self)
        settings_action.setShortcut(QKeySequence.Preferences)
        settings_action.triggered.connect(self._show_settings_tab)
        edit_menu.addAction(settings_action)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        
        # Toggle log viewer action
        self.toggle_log_action = QAction("Show &Log", self, checkable=True)
        self.toggle_log_action.setChecked(True)
        self.toggle_log_action.triggered.connect(self._toggle_log_visibility)
        view_menu.addAction(self.toggle_log_action)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        # About action
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)
        
        # About Qt action
        about_qt_action = QAction("About &Qt", self)
        about_qt_action.triggered.connect(QApplication.aboutQt)
        help_menu.addAction(about_qt_action)
    
    def _create_tabs(self):
        """Create the main tabs."""
        # Download tab
        self.download_tab = DownloadTab()
        self.tab_widget.addTab(self.download_tab, "Download")
        
        # Convert tab
        self.convert_tab = ConvertTab()
        self.tab_widget.addTab(self.convert_tab, "Convert")
        
        # Settings tab
        self.settings_tab = SettingsTab()
        self.tab_widget.addTab(self.settings_tab, "Settings")
    
    def _connect_signals(self):
        """Connect signals to slots."""
        # Connect download tab signals
        self.download_tab.download_started.connect(self._start_download)
        self.download_tab.download_stopped.connect(self._stop_download)
        
        # Connect convert tab signals
        self.convert_tab.conversion_started.connect(self._start_conversion)
        self.convert_tab.conversion_stopped.connect(self._stop_conversion)
        
        # Connect settings tab signals
        self.settings_tab.api_credentials_saved.connect(self._on_api_credentials_saved)
        self.settings_tab.auth_state_changed.connect(self._on_auth_state_changed)
        
        # Connect log viewer signals
        self.log_viewer.log_copied.connect(
            lambda: self.status_bar.showMessage("Log copied to clipboard", 3000)
        )
        
        # Connect file list signals
        self.file_list.open_requested.connect(self._open_downloads_folder)
        self.file_list.copy_requested.connect(self._copy_file_to_clipboard)
        self.file_list.file_selected.connect(self._show_file_preview)
        
        # Set up keyboard shortcuts
        self.setup_shortcuts()
    
    def _load_settings(self):
        """Load settings from config."""
        self.config.load()
        
        try:
            # Load window geometry
            geometry_hex = self.config.get('window.geometry')
            if geometry_hex and isinstance(geometry_hex, str):
                try:
                    # Convert hex string back to QByteArray
                    from PySide6.QtCore import QByteArray
                    geometry = QByteArray.fromHex(geometry_hex.encode('utf-8'))
                    if not geometry.isEmpty():
                        self.restoreGeometry(geometry)
                except Exception as e:
                    logging.warning(f"Error restoring window geometry: {e}")
            
            # Load window state
            state_hex = self.config.get('window.state')
            if state_hex and isinstance(state_hex, str):
                try:
                    # Convert hex string back to QByteArray
                    from PySide6.QtCore import QByteArray
                    state = QByteArray.fromHex(state_hex.encode('utf-8'))
                    if not state.isEmpty():
                        self.restoreState(state)
                except Exception as e:
                    logging.warning(f"Error restoring window state: {e}")
            
            # Load log visibility
            log_visible = self.config.get('window.log_visible', True)
            if hasattr(self, 'toggle_log_action'):
                self.toggle_log_action.setChecked(log_visible)
            if hasattr(self, 'log_viewer'):
                self.log_viewer.setVisible(log_visible)
                
        except Exception as e:
            logging.error(f"Error loading window settings: {e}")
            # Continue with default settings
    
    def _save_settings(self):
        """Save settings to config."""
        try:
            self._load_settings()            # Save window geometry and state
            geometry = self.saveGeometry()
            state = self.saveState()
            
            # Convert QByteArray to hex string for YAML serialization
            if not geometry.isEmpty():
                geometry_hex = bytes(geometry).hex()
                self.config.set('window.geometry', geometry_hex)
            
            if not state.isEmpty():
                state_hex = bytes(state).hex()
                self.config.set('window.state', state_hex)
            
            # Save log visibility if log viewer exists
            if hasattr(self, 'log_viewer'):
                self.config.set('window.log_visible', self.log_viewer.isVisible())
                
        except Exception as e:
            logging.error(f"Error saving window settings: {e}")
        
        # Save config
        self.config.save()
    
    def _start_download(self, cmd_args: List[str], output_dir: str):
        """Start a download process.
        
        Args:
            cmd_args: Command line arguments for the download
            output_dir: Output directory for downloaded files
        """
        # Update UI immediately to show we're starting
        self.download_tab.start_btn.setEnabled(False)
        self.download_tab.stop_btn.setEnabled(True)
        self.status_bar.showMessage("Starting download...")
        
        # Use a single shot timer to start the worker asynchronously
        # This allows the UI to update before we start the potentially blocking operations
        QTimer.singleShot(100, lambda: self._start_worker_thread(cmd_args, output_dir))
    
    def _start_worker_thread(self, cmd_args: List[str], output_dir: str):
        """Start the worker thread with the given command and output directory.
        
        This method is called asynchronously after the UI has been updated.
        
        Args:
            cmd_args: Command line arguments for the download
            output_dir: Output directory for downloaded files
        """
        try:
            # Stop any existing download
            if self.worker_thread and self.worker_thread.isRunning():
                self.worker_thread.stop()
                self.worker_thread.wait()
            
            # Clear previous logs
            self.log_viewer.clear()
            
            # Create and start worker thread
            self.worker_thread = WorkerThread(cmd_args, output_dir)
            self.worker_thread.log.connect(self._on_worker_log)
            self.worker_thread.progress.connect(self._on_worker_progress)
            self.worker_thread.finished.connect(self._on_worker_finished)
            
            # Update UI
            self.status_bar.showMessage("Downloading...")
            
            # Start the worker
            self.worker_thread.start()
            
        except Exception as e:
            logging.error(f"Error starting download: {e}", exc_info=True)
            self.status_bar.showMessage(f"Error: {str(e)}", 5000)
            self.download_tab.start_btn.setEnabled(True)
            self.download_tab.stop_btn.setEnabled(False)
    
    def _stop_download(self):
        """Stop the current download process."""
        if self.worker_thread and self.worker_thread.isRunning():
            self.log_viewer.append("\nStopping download and saving messages...")
            self.status_bar.showMessage("Stopping download and saving messages...")
            self.worker_thread.stop()
    
    def _start_conversion(self, files: list, output_dir: str, options: dict):
        """Start a file conversion process.
        
        Args:
            files: List of files to convert
            output_dir: Output directory for converted files
            options: Conversion options including subchat, user filter, and split options
        """
        try:
            # Prepare base command
            cmd_args = []
            
            # Add input file (we'll process one file at a time to handle subchats properly)
            input_file = files[0]  # For now, process first file only
            cmd_args.append(input_file)
            
            # Add output directory
            cmd_args.extend(['--output', output_dir])
            
            # Add subchat filter if specified
            if options.get('subchat'):
                cmd_args.extend(['--subchat', options['subchat']])
                
                # Add subchat name if specified
                if options.get('subchat_name'):
                    cmd_args.extend(['--subchat-name', options['subchat_name']])
            
            # Add user filter if specified
            if options.get('user'):
                cmd_args.extend(['--user', options['user']])
            
            # Add split option if specified
            if options.get('split'):
                cmd_args.extend(['--split', options['split']])
            
            # Start the conversion in a worker thread
            self.worker_thread = WorkerThread(cmd_args, output_dir)
            self.worker_thread.log.connect(self._on_worker_log)
            self.worker_thread.progress.connect(self._on_worker_progress)
            self.worker_thread.finished.connect(self._on_conversion_finished)
            self.worker_thread.start()
            
            # Update UI
            self.status_bar.showMessage("Starting conversion...")
            
        except Exception as e:
            self.status_bar.showMessage(f"Error starting conversion: {str(e)}")
            logging.error(f"Error starting conversion: {e}", exc_info=True)
    
    def _stop_conversion(self):
        """Stop the current conversion process."""
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.stop()
            self.status_bar.showMessage("Stopping conversion...")
    
    def _on_conversion_finished(self, files: list, was_stopped: bool):
        """Handle conversion completion.
        
        Args:
            files: List of converted files
            was_stopped: Whether the conversion was stopped by the user
        """
        try:
            if was_stopped:
                self.status_bar.showMessage("Conversion stopped by user")
                QMessageBox.information(
                    self,
                    "Conversion Stopped",
                    "The conversion was stopped by the user. Partial results have been saved."
                )
            else:
                self.status_bar.showMessage(f"Conversion completed. {len(files)} files converted.")
                
            # Update file list with converted files
            if files:
                for file in files:
                    self.file_list.add_file(file)
                    
            # Reset Convert tab UI state
            self.convert_tab._set_conversion_in_progress(False)
            
        except Exception as e:
            logging.error(f"Error in conversion finished handler: {e}", exc_info=True)
            self.status_bar.showMessage(f"Error: {str(e)}")
    
    def _on_worker_log(self, message: str):
        """Handle log messages from the worker thread.
        
        Args:
            message: Log message
        """
        self.log_viewer.append(message)
    
    def _on_worker_progress(self, current: int, maximum: int):
        """Handle progress updates from the worker thread.
        
        Args:
            current: Current progress value
            maximum: Maximum progress value
        """
        # Update progress in status bar
        if maximum > 0:
            percent = (current / maximum) * 100
            self.status_bar.showMessage(f"Downloading... {percent:.1f}%")
            
        # Forward progress to download tab if it exists
        if hasattr(self, 'download_tab') and hasattr(self.download_tab, 'update_progress'):
            self.download_tab.update_progress(current, maximum)
    
    def _on_worker_finished(self, files: List[str], was_stopped: bool):
        """Handle worker thread completion.
        
        Args:
            files: List of downloaded files
            was_stopped: Whether the download was stopped by the user
        """
        # Update UI and reset progress
        self.download_tab._set_download_in_progress(False)
        self.download_tab.start_btn.setEnabled(True)
        self.download_tab.stop_btn.setEnabled(False)
        
        # Update file list
        if files:
            self.file_list.set_files(files)
            self.file_list.setVisible(True)
            
            # Select first file
            if files:
                self.file_list.file_list.setCurrentRow(0)
        else:
            self.file_list.setVisible(False)
        
        # Show completion message
        if was_stopped:
            self.status_bar.showMessage("Download stopped by user", 5000)
            self.log_viewer.append("\nDownload stopped by user")
            
            # Show message about saved files if any
            if files:
                file_word = "file" if len(files) == 1 else "files"
                self.status_bar.showMessage(
                    f"Messages saved successfully! Found {len(files)} {file_word}.", 5000
                )
        else:
            self.status_bar.showMessage("Download completed", 5000)
            self.log_viewer.append("\nDownload completed")
        
        # Clear worker reference
        self.worker_thread = None
    
    def _on_api_credentials_saved(self, settings: Dict[str, Any]):
        """Handle API credentials being saved.
        
        Args:
            settings: Dictionary containing API credentials
        """
        # Update status bar
        self.status_bar.showMessage("API credentials saved", 3000)
        
        # Update worker thread if running
        if self.worker_thread:
            self.worker_thread.api_id = settings.get('api_id', '')
            self.worker_thread.api_hash = settings.get('api_hash', '')
    
    def _on_auth_state_changed(self, is_authenticated: bool):
        """Handle authentication state changes.
        
        Args:
            is_authenticated: Whether the user is authenticated
        """
        # Update status bar
        status = "Authenticated" if is_authenticated else "Logged out"
        self.status_bar.showMessage(f"Telegram: {status}", 3000)
        
    def closeEvent(self, event: QCloseEvent):
        """Handle window close event.
        
        Args:
            event: Close event
        """
        # Stop any running worker thread
        if hasattr(self, 'worker_thread') and self.worker_thread and self.worker_thread.isRunning():
            self.log_viewer.append("\nStopping download before exit...")
            self.status_bar.showMessage("Stopping download before exit...")
            self.worker_thread.stop()
            self.worker_thread.wait(3000)  # Wait up to 3 seconds for thread to finish
            
        # Save settings
        self._save_settings()
        
        # Emit about_to_close signal
        self.about_to_close.emit()
        
        # Accept the close event
        event.accept()
    
    def _toggle_log_visibility(self, visible: bool):
        """Toggle log viewer visibility.
        
        Args:
            visible: Whether to show the log viewer
        """
        self.log_viewer.setVisible(visible)
        self.toggle_log_action.setChecked(visible)
    
    def _show_settings_tab(self):
        """Show the settings tab."""
        self.tab_widget.setCurrentWidget(self.settings_tab)
    
    def _open_downloads_folder(self):
        """Open the downloads folder in the system file manager."""
        downloads_dir = get_downloads_dir()
        try:
            if sys.platform == 'win32':
                os.startfile(str(downloads_dir))
            elif sys.platform == 'darwin':
                import subprocess
                subprocess.Popen(['open', str(downloads_dir)])
            else:  # Linux and other Unix-like
                import subprocess
                subprocess.Popen(['xdg-open', str(downloads_dir)])
        except Exception as e:
            self.log_viewer.append(f"Error opening downloads folder: {e}")
    
    def _copy_file_to_clipboard(self):
        """Copy the selected file's content to clipboard."""
        selected_file = self.file_list.get_selected_file()
        if not selected_file:
            self.status_bar.showMessage("No file selected", 3000)
            return
            
        try:
            with open(selected_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
            clipboard = QApplication.clipboard()
            clipboard.setText(content)
            
            file_name = os.path.basename(selected_file)
            self.status_bar.showMessage(f"Copied {file_name} to clipboard", 3000)
            self.log_viewer.append(f"Copied {file_name} to clipboard")
            
        except Exception as e:
            error_msg = f"Error copying file to clipboard: {e}"
            self.status_bar.showMessage(error_msg, 5000)
            self.log_viewer.append(error_msg)
    
    def _show_file_preview(self, file_path: str):
        """Show a preview of the selected file.
        
        Args:
            file_path: Path to the file to preview
        """
        if not file_path or not os.path.exists(file_path):
            self.file_list.preview.clear()
            self.file_list.file_size_label.setText("Size: 0 B")
            return
            
        try:
            # Get file size
            file_size = os.path.getsize(file_path)
            self.file_list.file_size_label.setText(f"Size: {file_size / 1024:.1f} KB")
            
            # Read first 100 lines for preview
            self.file_list.preview.clear()
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                for i, line in enumerate(f):
                    if i >= 100:
                        self.file_list.preview.append("\n[Preview truncated to first 100 lines]")
                        break
                    self.file_list.preview.append(line.rstrip())
                        
        except Exception as e:
            self.file_list.preview.setText(f"Error reading file: {e}")
    
    def setup_shortcuts(self):
        """Set up keyboard shortcuts."""
        # Copy to clipboard shortcut (Ctrl+C / Cmd+C)
        copy_shortcut = QShortcut(QKeySequence.Copy, self)
        copy_shortcut.activated.connect(self._on_copy_shortcut_activated)
    
    def _on_copy_shortcut_activated(self):
        """Handle copy shortcut activation."""
        if self.file_list and self.file_list.isVisible() and self.file_list.get_selected_file():
            self._copy_file_to_clipboard()
    
    def _show_about_dialog(self):
        """Show the about dialog."""
        from telegram_download_chat import __version__
        QMessageBox.about(
            self,
            "About Telegram Download Chat",
            f"<h2>Telegram Download Chat</h2>"
            f"<p>Version {__version__}</p>"
            "<p>A tool to download Telegram chat history.</p>"
            "<p>Copyright 2025 Stanislav Popov. All rights reserved.</p>"
        )
    
    def closeEvent(self, event: QCloseEvent):
        """Handle window close event.
        
        Args:
            event: Close event
        """
        # Stop any running downloads
        if self.worker_thread and self.worker_thread.isRunning():
            reply = QMessageBox.question(
                self,
                'Download in Progress',
                'A download is in progress. Are you sure you want to quit?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.worker_thread.stop()
                self.worker_thread.wait()
            else:
                event.ignore()
                return
        
        # Save settings
        self._save_settings()
        
        # Emit about to close signal
        self.about_to_close.emit()
        
        # Accept the close event
        event.accept()

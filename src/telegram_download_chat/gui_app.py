# gui_app.py
#!/usr/bin/env python3
"""
GUI for telegram-download-chat
"""
import sys
import os
import subprocess
from pathlib import Path
from .paths import get_default_config_path, ensure_app_dirs
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QFileDialog, QLabel, QTabWidget, QWidget, QLineEdit,
    QCheckBox, QSpinBox, QDateEdit, QListWidget, QProgressBar, QMessageBox, QStyle
)
from PySide6.QtCore import QThread, Signal, QSize, QDate, Qt, QSettings
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtGui import QIcon
import yaml
from pathlib import Path
import os
from .cli import parse_args
from .core import TelegramChatDownloader
from .paths import get_app_dir


class WorkerThread(QThread):
    log = Signal(str)
    finished = Signal(list)

    def __init__(self, cmd_args, output_dir):
        super().__init__()
        self.cmd = cmd_args
        self.output_dir = output_dir

    def run(self):
        files = []
        process = subprocess.Popen(
            self.cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        for line in process.stdout:
            self.log.emit(line.rstrip())
        process.wait()
        # after completion, collect files in output_dir
        p = Path(self.output_dir)
        print(p)
        if p.exists():
            # Get list of files with full paths
            all_files = [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in ('.txt', '.json')]
            # Sort by modification time, newest first
            for f in sorted(all_files, key=lambda x: x.stat().st_mtime, reverse=True):
                files.append(str(f.absolute()))
        self.finished.emit(files)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Download Chat GUI")
        self.resize(800, 600)
        
        # Set window icon
        icon_path = os.path.join(os.path.dirname(__file__), '..', '..', 'assets', 'icon.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Initialize UI components first
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
        self.log_view.setFixedHeight(int(self.log_view.fontMetrics().height() * 1.5))  # Slightly more than one line height
        self.log_view.setLineWrapMode(QTextEdit.NoWrap)  # No line wrapping
        self.log_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # Show vertical scrollbar when needed
        self.log_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # Hide horizontal scrollbar
        self.file_list = QListWidget()
        self.preview = QTextEdit(readOnly=True)
        self.preview.setAcceptDrops(False)
        self.open_btn = QPushButton("Open downloads")
        self.copy_btn = QPushButton("Copy to clipboard (Ctrl+C)" if os.name == 'nt' else "Copy to clipboard (⌘+C)")
        # Style the copy button
        self.copy_btn.setStyleSheet("""
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
                background-color: #cccccc;
            }
        """)
        self.copy_btn.setEnabled(False)
        self.file_size_label = QLabel("Size: 0 KB")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.current_file = None  # Track the currently shown file
        
        # Now build the tabs
        self._build_download_tab()
        self._build_convert_tab()
        self._build_settings_tab()
        
        # Load settings after all UI components are initialized
        self._load_settings()

        # Create a horizontal layout for log header with copy button
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Log:"))
        
        # Add copy button with icon
        self.copy_log_btn = QPushButton()
        self.copy_log_btn.setIcon(self.style().standardIcon(getattr(QStyle.StandardPixmap, 'SP_FileIcon')))  # Using save icon as copy
        self.copy_log_btn.setToolTip("Copy log to clipboard")
        self.copy_log_btn.setFixedSize(24, 24)
        self.copy_log_btn.setStyleSheet("""
            QPushButton {
                border: none;
                padding: 2px;
                background: transparent;
            }
            QPushButton:hover {
                background: #f0f0f0;
                border-radius: 3px;
            }
        """)
        self.copy_log_btn.clicked.connect(self.copy_log_to_clipboard)
        
        log_header.addWidget(self.copy_log_btn)
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
        
        # Set up keyboard shortcut
        self.copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self)
        self.copy_shortcut.activated.connect(self.copy_to_clipboard)

    def _build_download_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        self.chat_edit = QLineEdit()
        self.chat_edit.setPlaceholderText("@username, link or chat_id")
        self.chat_edit.returnPressed.connect(self.start_download)
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 1000000)
        self.until_edit = QDateEdit()
        self.until_edit.setCalendarPopup(True)
        self.until_edit.setDisplayFormat("yyyy-MM-dd")
        self.until_edit.setDate(QDate())  # Set to invalid/empty date
        self.subchat_edit = QLineEdit()
        self.subchat_edit.setPlaceholderText("Subchat URL or ID")
        self.output_edit = QLineEdit()
        btn_out = QPushButton("Browse…")
        btn_out.clicked.connect(lambda: self._browse(self.output_edit, False))
        h = QHBoxLayout()
        h.addWidget(self.output_edit)
        h.addWidget(btn_out)
        self.debug_chk = QCheckBox("Debug mode")

        form.addRow("Chat:", self.chat_edit)
        form.addRow("Limit:", self.limit_spin)
        form.addRow("Until date:", self.until_edit)
        form.addRow("Subchat:", self.subchat_edit)
        form.addRow("Output file:", h)
        form.addRow("Debug:", self.debug_chk)
        # Create a larger, more prominent download button
        self.start_btn = QPushButton("Start download")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                font-size: 16px;
                padding: 12px 24px;
                border: none;
                border-radius: 6px;
                min-width: 200px;
                min-height: 40px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        self.start_btn.clicked.connect(self.start_download)
        form.addRow(self.start_btn)
        form.setAlignment(self.start_btn, Qt.AlignCenter)  # Center the button
        self.tabs.addTab(tab, "Download")

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
        """Build the settings tab with API credentials."""
        tab = QWidget()
        form = QFormLayout(tab)
        
        # API ID
        self.api_id_edit = QLineEdit()
        self.api_id_edit.setPlaceholderText("Enter your Telegram API ID")
        form.addRow("API ID:", self.api_id_edit)
        
        # API Hash
        self.api_hash_edit = QLineEdit()
        self.api_hash_edit.setPlaceholderText("Enter your Telegram API Hash")
        self.api_hash_edit.setEchoMode(QLineEdit.Password)
        form.addRow("API Hash:", self.api_hash_edit)
        
        # Save button
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self._save_settings)
        form.addRow(save_btn)
        
        # Add help text
        help_label = QLabel(
            "<p>To get your API credentials:</p>"
            "<ol>"
            "<li>Go to <a href='https://my.telegram.org/'>my.telegram.org</a></li>"
            "<li>Log in with your phone number</li>"
            "<li>Go to 'API development tools'</li>"
            "<li>Create a new application</li>"
            "<li>Copy the API ID and API Hash</li>"
            "</ol>"
        )
        help_label.setOpenExternalLinks(True)
        help_label.setWordWrap(True)
        form.addRow(help_label)
        
        self.tabs.addTab(tab, "Settings")

    def _browse(self, line_edit, is_file):
        path = QFileDialog.getExistingDirectory(self, "Select folder") if not is_file else \
               QFileDialog.getOpenFileName(self, "Select file", filter="JSON Files (*.json)")[0]
        if path:
            line_edit.setText(path)
            
    def _load_settings(self):
        """Load settings from config file."""
        ensure_app_dirs()  # Make sure the config directory exists
        config_path = get_default_config_path()
        
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
                    settings = config.get('settings', {})
                    if hasattr(self, 'api_id_edit'):
                        self.api_id_edit.setText(str(settings.get('api_id', '')))
                    if hasattr(self, 'api_hash_edit'):
                        self.api_hash_edit.setText(str(settings.get('api_hash', '')))
                if hasattr(self, 'log_view'):
                    self.log_view.append(f"Loaded settings from {config_path}")
            except Exception as e:
                if hasattr(self, 'log_view'):
                    self.log_view.append(f"Error loading settings from {config_path}: {e}")
                else:
                    print(f"Error loading settings from {config_path}: {e}")
        elif hasattr(self, 'log_view'):
            self.log_view.append(f"Config file not found at {config_path}")
    
    def _save_settings(self):
        """Save settings to config file."""
        ensure_app_dirs()  # Make sure the config directory exists
        config_path = get_default_config_path()
        
        settings = {
            'settings': {
                'api_id': self.api_id_edit.text(),
                'api_hash': self.api_hash_edit.text()
            }
        }
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(settings, f, default_flow_style=False)
            self.log_view.append(f"Settings saved successfully to {config_path}")
        except Exception as e:
            self.log_view.append(f"Error saving settings to {config_path}: {e}")

    def start_download(self):
        cmd = [sys.executable, "-m", "telegram_download_chat.cli"]
        if self.debug_chk.isChecked(): cmd.append("--debug")
        cmd += [self.chat_edit.text()]
        if self.limit_spin.value(): cmd += ["--limit", str(self.limit_spin.value())]
        if self.subchat_edit.text(): cmd += ["--subchat", self.subchat_edit.text()]
        if self.until_edit.date(): cmd += ["--until", self.until_edit.date().toString("yyyy-MM-dd")]
        output_path = Path(self.output_edit.text()) if self.output_edit.text() else get_downloads_dir() / "chat_history.json"
        if self.output_edit.text():
            cmd += ["-o", str(output_path)]
        # Use the directory of the output file
        out_dir = str(output_path.parent)
        self._run_worker(cmd, out_dir)

    def start_convert(self):
        cmd = [sys.executable, "-m", "telegram_download_chat.cli"]
        if self.conv_debug.isChecked(): cmd.append("--debug")
        cmd += [self.export_edit.text()]
        if self.conv_user_edit.text(): cmd += ["--user", self.conv_user_edit.text()]
        downloads_dir = get_downloads_dir()
        output_path = Path(self.conv_output.text()) if self.conv_output.text() else downloads_dir / "converted_chat.json"
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
        self.worker.finished.connect(self.on_finished)
        self.start_btn.setEnabled(False)
        self.worker.start()

    def on_finished(self, files):
        self.file_list.clear()
        if files:
            self.file_list.addItems([os.path.basename(f) for f in files])
            self.file_list.setCurrentRow(0)  # Select first file
            self.open_btn.setEnabled(True)
            self.copy_btn.setEnabled(True)
            self.log_view.append("\nDownload completed!")
        else:
            self.log_view.append("\nNo files were downloaded.")
            self.open_btn.setEnabled(False)
            self.copy_btn.setEnabled(False)
            self.preview.clear()
            self.file_size_label.setText("Size: 0 KB")

        self.start_btn.setEnabled(True)
        # Change download button to gray
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #9e9e9e;
                color: white;
                font-weight: bold;
                font-size: 16px;
                padding: 12px 24px;
                border: none;
                border-radius: 6px;
                min-width: 200px;
                min-height: 40px;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)

    def show_preview(self, filename):
        self.preview.clear()
        # Prepend downloads directory to get full path
        full_path = os.path.join(get_downloads_dir(), filename)
        self.current_file = full_path
        try:
            file_size = os.path.getsize(full_path) / 1024  # Size in KB
            self.file_size_label.setText(f"Size: {file_size:.1f} KB")
            self.copy_btn.setEnabled(True)
            
            with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
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
                self.log_view.append("Error: File is too large to copy to clipboard (max 10MB)")
                return
                
            # Read file with error handling for encoding
            try:
                with open(self.current_file, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()  # Read entire file content
                    
                # Copy to clipboard
                clipboard = QApplication.clipboard()
                clipboard.setText(content)
                
                # Show success message with file name
                file_name = os.path.basename(self.current_file)
                self.log_view.append(f"Copied content of '{file_name}' to clipboard")
                
            except UnicodeDecodeError:
                self.log_view.append("Error: Could not decode file as UTF-8 text")
                
        except PermissionError:
            self.log_view.append("Error: Permission denied when trying to read the file")
            
        except Exception as e:
            self.log_view.append(f"Error copying to clipboard: {str(e)}")
            
    def copy_log_to_clipboard(self):
        """Copy the entire log content to clipboard"""
        if self.log_view.toPlainText():
            QApplication.clipboard().setText(self.log_view.toPlainText())
            self.log_view.append(f"Copied log to clipboard")

    def open_downloads(self):
        folder = get_downloads_dir()
        if sys.platform == 'win32':
            os.startfile(folder)
        elif sys.platform == 'darwin':
            subprocess.call(['open', folder])
        else:
            subprocess.call(['xdg-open', folder])

def get_downloads_dir():
    args = parse_args()
    downloader = TelegramChatDownloader(config_path=args.config)
    output_dir = downloader.config.get('settings', {}).get('save_path', get_app_dir() / 'downloads')
    return output_dir

def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()

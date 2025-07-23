"""Worker thread for handling background tasks."""
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal
from telegram_download_chat.paths import get_downloads_dir


class WorkerThread(QThread):
    """Worker thread for running command line tasks in the background."""
    
    log = Signal(str)
    progress = Signal(int, int)  # current, maximum
    finished = Signal(list, bool)  # files, was_stopped_by_user
    
    def __init__(self, cmd_args, output_dir):
        """Initialize the worker thread.
        
        Args:
            cmd_args: List of command line arguments
            output_dir: Directory where output files will be saved
        """
        super().__init__()
        self.cmd = cmd_args
        self.output_dir = output_dir
        self.current_max = 1000  # Initial maximum value
        self._is_running = True
        self._stopped_by_user = False
        self.process = None
        self._stop_file = None  # Path to stop file for inter-process communication
    
    def stop(self):
        """Stop the worker thread gracefully."""
        self._is_running = False
        self._stopped_by_user = True
        if self.process:
            # Create a stop file to signal the process to stop gracefully
            if not self._stop_file:
                import tempfile
                self._stop_file = Path(tempfile.gettempdir()) / "telegram_download_stop.tmp"
            try:
                self._stop_file.touch()
                self.log.emit("\nSending graceful shutdown signal...")
            except Exception:
                # Fallback to terminate if stop file creation fails
                self.process.terminate()
    
    def _extract_progress(self, line):
        """Extract progress information from command output.
        
        Args:
            line: Output line from the command
        """
        try:
            # Look for progress information in the format: [current/max]
            if '[' in line and ']' in line and '/' in line:
                progress_part = line[line.find('[')+1:line.find(']')]
                if '/' in progress_part:
                    current, max_progress = progress_part.split('/')
                    try:
                        current = int(current.strip())
                        self._update_progress(current)
                    except (ValueError, TypeError):
                        pass
        except Exception as e:
            logging.debug(f"Error extracting progress: {e}")
    
    def _update_progress(self, current):
        """Update the progress bar with current progress.
        
        Args:
            current: Current progress value
        """
        new_max = self.current_max
        if current > self.current_max:
            if current <= 10000:
                new_max = 10000
            elif current <= 50000:
                new_max = 50000
            elif current <= 100000:
                new_max = 100000
            else:
                new_max = (current // 100000 + 1) * 100000
            
            if new_max != self.current_max:
                self.current_max = new_max
        
        self.progress.emit(current, self.current_max)

    def run(self):
        """Run the worker thread."""
        files = []
        
        try:
            # Build the command using the module path directly
            cmd = [sys.executable, "-m", "telegram_download_chat.cli"] + self.cmd
            
            self.log.emit(f"Executing: {' '.join(cmd)}")
            
            # Start the process
            env = os.environ.copy()
            env.setdefault("PYTHONIOENCODING", "utf-8")

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                bufsize=1,  # Line buffered
                universal_newlines=True,
                env=env,
            )
            
            # Read output in real-time
            while self._is_running and self.process.poll() is None:
                line = self.process.stdout.readline()
                if not line:
                    break
                    
                line = line.rstrip()
                self.log.emit(line)
                
                # Try to extract progress information from the output
                self._extract_progress(line)
                
            # Read any remaining output
            if self.process.poll() is not None:
                for line in self.process.stdout:
                    line = line.rstrip()
                    if line:
                        self.log.emit(line)
                        self._extract_progress(line)
        
        except Exception as e:
            self.log.emit(f"Error in worker thread: {str(e)}")
            logging.error("Worker thread error", exc_info=True)
        finally:
            # Ensure process is terminated
            if hasattr(self, 'process') and self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            
            # If we broke out of the loop because stop was requested
            if hasattr(self, 'process') and self.process and self.process.poll() is None:
                # Wait for the process to stop
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            
            # After completion, collect files in output_dir
            if not self.output_dir:
                self.output_dir = get_downloads_dir()
            p = Path(self.output_dir)
            if p.exists():
                # Get list of files with full paths and sort by modification time, newest first
                all_files = [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in ('.txt', '.json')]
                files.extend(str(f.absolute()) for f in sorted(all_files, key=lambda x: x.stat().st_mtime, reverse=True))
        
            # Clean up stop file if it exists
            if self._stop_file and self._stop_file.exists():
                try:
                    self._stop_file.unlink()
                except Exception:
                    pass
            
            # Emit finished signal with collected files
            self.finished.emit(files, self._stopped_by_user)

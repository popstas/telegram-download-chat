"""Worker thread for handling background tasks."""

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List

from PySide6.QtCore import QThread, Signal

from telegram_download_chat.core.progress import PROGRESS_ENV_VAR, parse_progress_line
from telegram_download_chat.paths import get_downloads_dir


class WorkerThread(QThread):
    """Worker thread for running command line tasks in the background."""

    log = Signal(str)
    progress = Signal(int, int)  # current, maximum
    status_update = Signal(str)  # parsed status for status bar
    media_progress = Signal(int, int, str)  # current, total, file (relative path)
    message_progress = Signal(int, str)  # fetched count, last message date (ISO)
    media_summary = Signal(dict)  # post-media-download summary counters
    comments_progress = Signal(int, int, int)  # posts_done, posts_total, comments
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

                self._stop_file = (
                    Path(tempfile.gettempdir()) / "telegram_download_stop.tmp"
                )
            try:
                self._stop_file.touch()
                self.log.emit("\nSending graceful shutdown signal...")
            except Exception:
                # Fallback to terminate if stop file creation fails
                self.process.terminate()

    def _parse_status(self, line):
        """Parse log line and emit status update for the status bar.

        Args:
            line: Output line from the command
        """
        lower = line.lower()
        if "fetched:" in lower:
            # Extract count from "Fetched: N"
            try:
                count = line.split("Fetched:")[1].strip().split()[0]
                self.status_update.emit(f"Fetched {count} messages")
            except (IndexError, ValueError):
                pass
        elif "saved" in lower and "messages to" in lower:
            try:
                # "Saved N messages to ..."
                parts = line.split("Saved")[1].strip().split()
                count = parts[0]
                self.status_update.emit(f"Saved {count} messages")
            except (IndexError, ValueError):
                pass
        elif "resuming download from" in lower:
            self.status_update.emit("Resuming download...")
        elif "flood" in lower and "wait" in lower:
            self.status_update.emit("Rate limited, waiting...")
        elif "downloading media" in lower:
            self.status_update.emit("Downloading media...")

    def _handle_progress_event(self, event):
        """Turn a structured progress event into Qt signals.

        This replaces fragile log-text scraping for the events the core emits
        explicitly (media download progress and message-fetch progress). Plain
        log lines still flow through ``_parse_status``/``_extract_progress`` as a
        fallback.

        Args:
            event: Parsed progress event dict (see ``core/progress.py``).
        """
        etype = event.get("type")
        if etype == "media":
            try:
                current = int(event.get("current") or 0)
                total = int(event.get("total") or 0)
            except (TypeError, ValueError):
                return
            file = str(event.get("file") or "")
            self.media_progress.emit(current, total, file)
            if total > 0:
                self.progress.emit(current, total)
                self.status_update.emit(f"Downloading media {current}/{total}")
        elif etype == "messages":
            try:
                fetched = int(event.get("fetched") or 0)
            except (TypeError, ValueError):
                return
            last_date = str(event.get("last_date") or "")
            self.message_progress.emit(fetched, last_date)
            self._update_progress(fetched)
            if last_date:
                self.status_update.emit(
                    f"Fetched {fetched} messages (up to {last_date})"
                )
            else:
                self.status_update.emit(f"Fetched {fetched} messages")
        elif etype == "media_summary":
            self.media_summary.emit(event)
            self.status_update.emit(self._format_media_summary(event))
        elif etype == "comments":
            try:
                posts_done = int(event.get("posts_done") or 0)
                posts_total = int(event.get("posts_total") or 0)
                comments = int(event.get("comments") or 0)
            except (TypeError, ValueError):
                return
            self.comments_progress.emit(posts_done, posts_total, comments)
            if posts_total > 0:
                self.progress.emit(posts_done, posts_total)
                self.status_update.emit(
                    f"Fetching comments {posts_done}/{posts_total} "
                    f"({comments} comments)"
                )

    @staticmethod
    def _format_media_summary(event):
        """Build a concise status-bar string from a media_summary event."""
        try:
            total = int(event.get("total_files") or 0)
            downloaded = int(event.get("downloaded_files") or 0)
            cached = int(event.get("cached_files") or 0)
            total_mb = float(event.get("total_bytes") or 0) / (1024 * 1024)
            speed = float(event.get("speed_mbps") or 0)
        except (TypeError, ValueError):
            return "Media download complete"
        text = (
            f"Media: {total} files, {total_mb:.1f} MB "
            f"({downloaded} downloaded, {cached} cached)"
        )
        if speed > 0:
            text += f", {speed:.2f} MB/s"
        return text

    def _extract_progress(self, line):
        """Extract progress information from command output.

        Args:
            line: Output line from the command
        """
        try:
            # Look for progress information in the format: [current/max]
            if "[" in line and "]" in line and "/" in line:
                progress_part = line[line.find("[") + 1 : line.find("]")]
                if "/" in progress_part:
                    current, max_progress = progress_part.split("/")
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
            cmd = [sys.executable, "-m", "telegram_download_chat"] + self.cmd

            self.log.emit(f"Executing: {' '.join(cmd)}")

            # Start the process
            env = os.environ.copy()
            # Force UTF-8 child stdio so Cyrillic (and other non-ASCII) chat
            # names in log lines/paths survive the pipe. setdefault would leave a
            # locale codepage in place if the parent env already set this.
            env["PYTHONIOENCODING"] = "utf-8"
            # Ask the CLI to emit structured progress events on stdout so we can
            # consume them instead of scraping human-readable log text.
            env[PROGRESS_ENV_VAR] = "1"

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
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

                # Prefer structured progress events; fall back to text scraping.
                event = parse_progress_line(line)
                if event is not None:
                    self._handle_progress_event(event)
                    continue

                self.log.emit(line)

                # Try to extract progress information from the output
                self._extract_progress(line)
                self._parse_status(line)

            # Read any remaining output
            if self.process.poll() is not None:
                for line in self.process.stdout:
                    line = line.rstrip()
                    if line:
                        event = parse_progress_line(line)
                        if event is not None:
                            self._handle_progress_event(event)
                            continue
                        self.log.emit(line)
                        self._extract_progress(line)
                        self._parse_status(line)

        except Exception as e:
            self.log.emit(f"Error in worker thread: {str(e)}")
            logging.error("Worker thread error", exc_info=True)
        finally:
            # Ensure process is terminated
            if (
                hasattr(self, "process")
                and self.process
                and self.process.poll() is None
            ):
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()

            # If we broke out of the loop because stop was requested
            if (
                hasattr(self, "process")
                and self.process
                and self.process.poll() is None
            ):
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
                all_files = []
                for ext in ("*.json", "*.txt"):
                    all_files.extend(f for f in p.rglob(ext) if f.is_file())
                files.extend(
                    str(f.absolute())
                    for f in sorted(
                        all_files, key=lambda x: x.stat().st_mtime, reverse=True
                    )
                )

            # Clean up stop file if it exists
            if self._stop_file and self._stop_file.exists():
                try:
                    self._stop_file.unlink()
                except Exception:
                    pass

            # Emit finished signal with collected files
            self.finished.emit(files, self._stopped_by_user)

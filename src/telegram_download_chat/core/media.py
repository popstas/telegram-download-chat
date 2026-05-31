"""Media download functionality for Telegram messages."""

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from telethon.errors import FileReferenceExpiredError, FloodWaitError
from telethon.tl.types import (
    Document,
    DocumentAttributeFilename,
    DocumentAttributeSticker,
    GeoPoint,
    MessageMediaContact,
    MessageMediaDice,
    MessageMediaDocument,
    MessageMediaGame,
    MessageMediaGeo,
    MessageMediaGeoLive,
    MessageMediaPhoto,
    MessageMediaPoll,
    MessageMediaVenue,
    MessageMediaWebPage,
    Photo,
    WebPage,
)

from .fast_download import FastDownloadStalled
from .fast_download import download_file as fast_download_file
from .progress import emit_progress

# ---------------------------------------------------------------------------
# Category constants — these become the subdirectory names under attachments/
# ---------------------------------------------------------------------------
_CAT_IMAGES = "images"
_CAT_VIDEOS = "videos"
_CAT_AUDIO = "audio"
_CAT_STICKERS = "stickers"
_CAT_DOCUMENTS = "documents"
_CAT_ARCHIVES = "archives"
_CAT_CONTACTS = "contacts"
_CAT_LOCATIONS = "locations"
_CAT_POLLS = "polls"
_CAT_OTHER = "other"

_ARCHIVE_MIMES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/x-rar-compressed",
    "application/x-rar",
    "application/x-7z-compressed",
    "application/x-bzip2",
    "application/gzip",
    "application/x-tar",
}

_DOCUMENT_MIMES = {
    "application/pdf",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/epub+zip",
    "application/x-mobipocket-ebook",
    "application/json",
    "application/xml",
}

_MIME_TO_EXT = {
    # Images
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/tiff": ".tiff",
    "image/bmp": ".bmp",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "image/avif": ".avif",
    "image/jxl": ".jxl",
    "image/x-icon": ".ico",
    # Video
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/x-msvideo": ".avi",
    "video/x-flv": ".flv",
    "video/x-ms-wmv": ".wmv",
    "video/3gpp": ".3gp",
    "video/3gpp2": ".3g2",
    "video/ogg": ".ogv",
    "video/mpeg": ".mpg",
    # Audio
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/x-aac": ".aac",
    "audio/x-wav": ".wav",
    "audio/wav": ".wav",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/opus": ".opus",
    "audio/webm": ".weba",
    "audio/amr": ".amr",
    # Documents / text
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/html": ".html",
    "text/css": ".css",
    "text/javascript": ".js",
    "application/javascript": ".js",
    "application/json": ".json",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "text/markdown": ".md",
    "application/x-yaml": ".yaml",
    "text/yaml": ".yaml",
    "application/rtf": ".rtf",
    # Microsoft Office
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    # OpenDocument
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    # E-books
    "application/epub+zip": ".epub",
    "application/x-mobipocket-ebook": ".mobi",
    # Archives
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/x-rar-compressed": ".rar",
    "application/x-rar": ".rar",
    "application/x-7z-compressed": ".7z",
    "application/x-bzip2": ".bz2",
    "application/gzip": ".gz",
    "application/x-tar": ".tar",
    # Executables / packages
    "application/vnd.android.package-archive": ".apk",
    "application/x-apple-diskimage": ".dmg",
    "application/x-ms-dos-executable": ".exe",
    "application/x-sh": ".sh",
    # Telegram-specific
    "application/x-tgsticker": ".tgs",
    # Database
    "application/x-sqlite3": ".db",
}


_BYTES_PER_MB = 1024 * 1024


@dataclass
class MediaStats:
    """Counters accumulated over a single ``--media`` download run.

    Surfaced after a run so the CLI and GUI can show a summary: how many files
    were downloaded vs. reused from a previous run (cached), how fast, and how
    many needed a retry (expired file-reference refetch or fast-download
    fallback) or failed outright.
    """

    downloaded_files: int = 0
    downloaded_bytes: int = 0
    cached_files: int = 0
    cached_bytes: int = 0
    failed_files: int = 0
    # Files that needed a retry, broken down by cause.
    expired_reference_retries: int = 0
    fast_download_fallbacks: int = 0
    # Wall-clock seconds spanning the actual downloads (first start to last
    # finish); excludes cached-file checks and text-only messages.
    elapsed_seconds: float = 0.0

    @property
    def total_files(self) -> int:
        """All media files present after the run (downloaded + cached)."""
        return self.downloaded_files + self.cached_files

    @property
    def total_bytes(self) -> int:
        """Total bytes across downloaded and cached files."""
        return self.downloaded_bytes + self.cached_bytes

    @property
    def speed_mbps(self) -> float:
        """Average download speed in MB/s.

        Counts only actually-downloaded bytes over the actual-download elapsed
        window; cached files contribute to neither the numerator nor the basis.
        """
        if self.elapsed_seconds <= 0 or self.downloaded_bytes <= 0:
            return 0.0
        return (self.downloaded_bytes / _BYTES_PER_MB) / self.elapsed_seconds

    def to_event(self) -> Dict[str, Any]:
        """A JSON-serializable summary event for structured progress."""
        return {
            "type": "media_summary",
            "total_files": self.total_files,
            "downloaded_files": self.downloaded_files,
            "downloaded_bytes": self.downloaded_bytes,
            "cached_files": self.cached_files,
            "cached_bytes": self.cached_bytes,
            "total_bytes": self.total_bytes,
            "failed_files": self.failed_files,
            "expired_reference_retries": self.expired_reference_retries,
            "fast_download_fallbacks": self.fast_download_fallbacks,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "speed_mbps": round(self.speed_mbps, 3),
        }

    def summary_line(self) -> str:
        """A concise human-readable one-to-three line summary."""
        total_mb = self.total_bytes / _BYTES_PER_MB
        lines = [
            f"Media summary: {self.total_files} files, {total_mb:.1f} MB "
            f"({self.downloaded_files} downloaded, {self.cached_files} cached)"
        ]
        if self.downloaded_bytes > 0 and self.elapsed_seconds > 0:
            lines.append(f"Average speed: {self.speed_mbps:.2f} MB/s")
        if (
            self.expired_reference_retries
            or self.fast_download_fallbacks
            or self.failed_files
        ):
            lines.append(
                "Retries: "
                f"{self.expired_reference_retries} expired-reference, "
                f"{self.fast_download_fallbacks} fast-download fallback; "
                f"{self.failed_files} failed"
            )
        return "\n".join(lines)


class MediaMixin:
    """Mixin class for downloading media from Telegram messages."""

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_filename(self, media: Any) -> Optional[str]:
        """Return a filename for the given media object, or None if not downloadable."""
        if isinstance(media, MessageMediaPhoto):
            photo = media.photo
            if isinstance(photo, Photo):
                return f"{photo.id}.jpg"

        elif isinstance(media, MessageMediaDocument):
            doc = media.document
            if isinstance(doc, Document):
                for attr in doc.attributes:
                    if isinstance(attr, DocumentAttributeFilename):
                        # Sanitize: strip path components to prevent traversal
                        return Path(attr.file_name).name or f"{doc.id}.bin"
                return f"{doc.id}{self._get_extension_from_mime(doc.mime_type)}"

        elif isinstance(media, MessageMediaWebPage):
            webpage = media.webpage
            if isinstance(webpage, WebPage):
                if webpage.document and isinstance(webpage.document, Document):
                    doc = webpage.document
                    for attr in doc.attributes:
                        if isinstance(attr, DocumentAttributeFilename):
                            return Path(attr.file_name).name or f"{doc.id}.bin"
                    return f"{doc.id}{self._get_extension_from_mime(doc.mime_type)}"
                elif webpage.photo and isinstance(webpage.photo, Photo):
                    return f"{webpage.photo.id}.jpg"
            return None

        elif isinstance(media, MessageMediaContact):
            identifier = media.user_id or media.phone_number or "unknown"
            return f"contact_{identifier}.vcf"

        elif isinstance(media, MessageMediaGeo):
            geo = media.geo
            if isinstance(geo, GeoPoint):
                return f"location_{geo.lat:.6f}_{geo.long:.6f}.json"
            return None

        elif isinstance(media, MessageMediaGeoLive):
            geo = media.geo
            if isinstance(geo, GeoPoint):
                return f"live_location_{geo.lat:.6f}_{geo.long:.6f}.json"
            return None

        elif isinstance(media, MessageMediaVenue):
            vid = getattr(media, "venue_id", None) or "unknown"
            return f"venue_{vid}.json"

        elif isinstance(media, MessageMediaPoll):
            poll_id = getattr(media.poll, "id", "unknown")
            return f"poll_{poll_id}.json"

        elif isinstance(media, MessageMediaDice):
            char = media.emoticon[0] if media.emoticon else "unknown"
            return (
                f"dice_{ord(char):x}_{media.value}.json"
                if char != "unknown"
                else f"dice_unknown_{media.value}.json"
            )

        elif isinstance(media, MessageMediaGame):
            game_id = getattr(media.game, "id", "unknown")
            return f"game_{game_id}.json"

        return None

    def get_predicted_attachment_path(
        self,
        media: Any,
        message_id: str,
        attachments_dir: Path,
    ) -> Optional[str]:
        """Return the relative path (from attachments_dir) where media will be saved.

        Structure: <category>/<message_id>_<filename>
        """
        filename = self.get_filename(media)
        if not filename:
            return None
        category = self._get_media_category(media)
        return f"{category}/{message_id}_{filename}"

    # ------------------------------------------------------------------
    # Download methods
    # ------------------------------------------------------------------

    async def download_message_media(
        self,
        message: Any,
        attachments_dir: Path,
    ) -> Optional[Path]:
        """Download media from a single message into a category subdirectory.

        Directory structure: attachments_dir/<category>/<message_id>_<filename>

        Returns the path to the saved file, or None on failure/skip.
        """
        media = getattr(message, "media", None) or (
            message.get("media") if isinstance(message, dict) else None
        )
        if not media:
            return None

        filename = self.get_filename(media)
        if not filename:
            return None

        message_id = str(
            getattr(message, "id", None)
            or (message.get("id") if isinstance(message, dict) else None)
            or ""
        )
        if not message_id:
            return None

        category = self._get_media_category(media)
        download_to = attachments_dir / category / f"{message_id}_{filename}"

        # Skip if already downloaded from a previous run
        if download_to.exists():
            self.logger.debug(f"Skipping already-downloaded: {download_to}")
            self._record_cached(download_to)
            return download_to

        download_to.parent.mkdir(parents=True, exist_ok=True)

        # Time only actual transfers: the cached early-return above never reaches
        # here, so cached-file checks and text-only messages stay out of the
        # MB/s elapsed-time basis (see MediaStats.speed_mbps).
        dl_start = time.monotonic()
        try:
            # Synthetic types: write directly without a network call
            if self._serialize_synthetic_media(media, download_to):
                self._record_downloaded(download_to)
                self._note_download_window(dl_start, time.monotonic())
                return download_to

            downloaded_path = await self._download_binary_media(
                message, media, download_to, message_id
            )
            if downloaded_path:
                self.logger.debug(
                    f"Downloaded media for message {message_id}: {downloaded_path}"
                )
                self._record_downloaded(downloaded_path)
                self._note_download_window(dl_start, time.monotonic())
                return Path(downloaded_path)
            self.logger.warning(f"Failed to download media for message {message_id}")
            self._record_failed()
            return None
        except Exception as e:
            self.logger.warning(
                f"Failed to download media for message {message_id}: {e}"
            )
            self._record_failed()
            return None

    # ------------------------------------------------------------------
    # Stat recording helpers (no-ops when no run is active)
    # ------------------------------------------------------------------

    def _record_cached(self, path: Path) -> None:
        stats = getattr(self, "_media_stats", None)
        if stats is None:
            return
        stats.cached_files += 1
        try:
            stats.cached_bytes += Path(path).stat().st_size
        except OSError:
            pass

    def _record_downloaded(self, path: Any) -> None:
        stats = getattr(self, "_media_stats", None)
        if stats is None:
            return
        stats.downloaded_files += 1
        try:
            stats.downloaded_bytes += Path(path).stat().st_size
        except OSError:
            pass

    def _record_failed(self) -> None:
        stats = getattr(self, "_media_stats", None)
        if stats is not None:
            stats.failed_files += 1

    def _note_download_window(self, start: float, end: float) -> None:
        """Widen the actual-download wall-clock window to span [start, end].

        Tracked as (min start, max end) across all real downloads so the MB/s
        basis is the time during which downloading happened, not the whole
        media phase (which also covers cached-file checks and text-only
        messages). Concurrent cached checks overlap this window, so they don't
        inflate it. Runs on the asyncio event loop thread, so no lock needed.
        """
        window = getattr(self, "_download_window", None)
        if window is None:
            self._download_window = [start, end]
        else:
            window[0] = min(window[0], start)
            window[1] = max(window[1], end)

    async def _download_binary_media(
        self,
        message: Any,
        media: Any,
        download_to: Path,
        message_id: str,
    ) -> Optional[Path]:
        """Download binary media, preferring the parallel multi-connection path.

        Falls back to the standard single-stream Telethon downloader for small
        files, when fast download is disabled, or when the fast path raises.
        """
        enabled, connections, threshold_bytes = self._resolve_fast_download_settings()
        binary_obj, file_size = self._extract_binary_object(media)

        if (
            enabled
            and binary_obj is not None
            and file_size is not None
            and file_size >= threshold_bytes
        ):
            used = getattr(self, "_current_connections", None) or connections
            try:
                self.logger.debug(
                    "Fast download for message %s: size=%d connections=%d",
                    message_id,
                    file_size,
                    used,
                )
                with download_to.open("wb") as fh:
                    await fast_download_file(
                        self.client,
                        binary_obj,
                        fh,
                        file_size=file_size,
                        connection_count=used,
                    )
                return download_to
            except Exception as e:
                if isinstance(e, (FloodWaitError, FastDownloadStalled)):
                    await self._reduce_threads_on_throttle(used)
                stats = getattr(self, "_media_stats", None)
                if stats is not None:
                    stats.fast_download_fallbacks += 1
                self.logger.warning(
                    "Fast download failed for message %s (%s); "
                    "falling back to standard downloader",
                    message_id,
                    e,
                )
                # Clean up any partial file before retrying via Telethon.
                try:
                    if download_to.exists():
                        download_to.unlink()
                except OSError:
                    pass

        # Standard path: pass full message so Telethon resolves WebPage internally.
        self.logger.debug("Standard download for message %s", message_id)
        try:
            downloaded_path = await self.client.download_media(
                message, file=download_to
            )
        except FileReferenceExpiredError:
            # The reference embedded in the message expired (common during long,
            # heavily-throttled runs). Refetch the message for a fresh reference
            # and retry once via the standard downloader.
            fresh = await self._refetch_message(message, message_id)
            if fresh is None:
                raise
            stats = getattr(self, "_media_stats", None)
            if stats is not None:
                stats.expired_reference_retries += 1
            downloaded_path = await self.client.download_media(fresh, file=download_to)
        return Path(downloaded_path) if downloaded_path else None

    async def _refetch_message(self, message: Any, message_id: Any) -> Optional[Any]:
        """Refetch a message by id to obtain a fresh file reference.

        Telegram file references embedded in ``Message`` objects are short-lived;
        on a throttled run they may expire before the download starts. Resolve the
        target entity (the stored ``_current_entity`` from the active download, or
        the message's ``peer_id`` as a fallback), then refetch the message to get a
        non-stale reference.

        Returns the refetched ``Message`` only if it still carries media whose
        identity matches the original (so an edited/replaced message does not
        silently attach the wrong file under the old name), otherwise ``None``
        (and on any failure).
        """
        entity = getattr(self, "_current_entity", None)
        if entity is None:
            entity = getattr(message, "peer_id", None)
        if entity is None:
            return None

        self.logger.warning(
            "File reference expired for message %s; refetching…", message_id
        )
        try:
            fresh = await self.client.get_messages(entity, ids=int(message_id))
        except Exception as e:
            self.logger.warning(
                "Failed to refetch message %s for fresh file reference: %s",
                message_id,
                e,
            )
            return None

        if fresh is None or not getattr(fresh, "media", None):
            return None

        # Guard against the message being edited/replaced between the original
        # fetch and the refetch: only the file reference may legitimately change,
        # not the underlying document/photo. If the identity differs, refuse to
        # download it under the original file's name/category.
        original_id = self._media_identity(getattr(message, "media", None))
        fresh_id = self._media_identity(fresh.media)
        if original_id is not None and fresh_id != original_id:
            self.logger.warning(
                "Refetched message %s has different media (was %s, now %s); "
                "skipping to avoid attaching the wrong file.",
                message_id,
                original_id,
                fresh_id,
            )
            return None
        return fresh

    def _media_identity(self, media: Any) -> Optional[int]:
        """Return the stable id of a media's underlying document/photo, or None.

        File references rotate, but the document/photo ``id`` is stable, so it is
        what distinguishes the original media from a replacement after an edit.
        """
        binary_obj, _ = self._extract_binary_object(media)
        return getattr(binary_obj, "id", None)

    def _resolve_fast_download_settings(self) -> Tuple[bool, int, int]:
        """Return (enabled, connection_count, threshold_bytes), cached per run."""
        cached = getattr(self, "_fast_dl_settings", None)
        if cached is not None:
            return cached

        settings = (self.config or {}).get("settings", {}) or {}
        cli_disabled = bool(getattr(self, "_no_fast_download", False))
        config_enabled = bool(settings.get("fast_download", True))
        enabled = (not cli_disabled) and config_enabled

        configured = settings.get("media_parallel_connections")
        if configured is not None:
            try:
                connections = max(1, min(16, int(configured)))
            except (TypeError, ValueError):
                connections = 2
        else:
            # Defaults intentionally conservative: 5 concurrent files (see
            # download_all_media) × these counts is the actual fan-out
            # Telegram sees. Higher numbers trigger server-side throttling.
            connections = 4 if getattr(self, "_is_premium", False) else 2

        threshold_mb = settings.get("media_parallel_threshold_mb", 5)
        try:
            threshold_bytes = max(0, int(float(threshold_mb) * 1024 * 1024))
        except (TypeError, ValueError):
            threshold_bytes = 1024 * 1024

        result = (enabled, connections, threshold_bytes)
        self._fast_dl_settings = result
        return result

    async def _reduce_threads_on_throttle(self, used: int) -> None:
        """Halve the live per-file connection count after a rate-limit signal.

        Generation-guarded: a burst of concurrent files can fail near
        simultaneously, but only the first one (running at the current count)
        steps the count down. Stragglers carrying a now-stale higher `used`
        are ignored, so each level is halved at most once.
        """
        lock = getattr(self, "_threads_lock", None)
        if lock is None:
            return
        async with lock:
            # A straggler that started at a higher count (already superseded by
            # an earlier halving) carries used > current — skip it.
            if used != self._current_connections or self._current_connections <= 1:
                return
            self._current_connections = max(1, self._current_connections // 2)
            self.logger.warning("Decrease threads to %d", self._current_connections)

    def _extract_binary_object(
        self, media: Any
    ) -> Tuple[Optional[Union[Document, Photo]], Optional[int]]:
        """Return (Document|Photo, file_size) for fast-downloadable media, or (None, None)."""
        if isinstance(media, MessageMediaDocument) and isinstance(
            media.document, Document
        ):
            return media.document, getattr(media.document, "size", None)

        if isinstance(media, MessageMediaPhoto) and isinstance(media.photo, Photo):
            return media.photo, self._largest_photo_size(media.photo)

        if isinstance(media, MessageMediaWebPage):
            webpage = media.webpage
            if isinstance(webpage, WebPage):
                if webpage.document and isinstance(webpage.document, Document):
                    return webpage.document, getattr(webpage.document, "size", None)
                if webpage.photo and isinstance(webpage.photo, Photo):
                    return webpage.photo, self._largest_photo_size(webpage.photo)

        return None, None

    async def _detect_premium_once(self) -> None:
        """Cache `self._is_premium` from the authenticated user, once per run.

        Premium accounts get a higher per-account download bandwidth ceiling,
        so we open more parallel chunk connections for them by default.
        """
        if getattr(self, "_premium_checked", False):
            return
        self._premium_checked = True
        try:
            me = await self.client.get_me()
            self._is_premium = bool(getattr(me, "premium", False))
        except Exception as e:
            self.logger.debug("Premium detection failed: %s", e)
            self._is_premium = False
        # Invalidate cached settings so the connection count picks up Premium status.
        self._fast_dl_settings = None

    @staticmethod
    def _largest_photo_size(photo: Photo) -> Optional[int]:
        """Largest known byte size across a Photo's available sizes."""
        sizes = [
            getattr(s, "size", None) for s in (getattr(photo, "sizes", None) or [])
        ]
        sizes = [s for s in sizes if isinstance(s, int)]
        return max(sizes) if sizes else None

    async def download_all_media(
        self,
        messages: List[Any],
        attachments_dir: Path,
    ) -> Dict[str, str]:
        """Download media from all messages concurrently (up to 5 at a time).

        Returns dict mapping str(message_id) -> relative path (from attachments_dir)
        for each successfully downloaded file.
        """
        await self._detect_premium_once()

        # Fresh per-run counters for the post-download summary.
        self._media_stats = MediaStats()
        # [min start, max end] across actual downloads; populated by
        # _note_download_window. Stays None when nothing is downloaded.
        self._download_window = None

        enabled, connections, _ = self._resolve_fast_download_settings()
        self._current_connections = connections
        self._threads_lock = asyncio.Lock()
        if enabled and connections > 1:
            self.logger.info(
                "Downloading media attachments (%d threads)...", connections
            )
        else:
            self.logger.info("Downloading media attachments...")

        CONCURRENCY = 5
        semaphore = asyncio.Semaphore(CONCURRENCY)
        results: Dict[str, str] = {}
        total = len(messages)
        completed = 0
        log_interval = max(1, min(50, total // 10))

        async def download_one(msg: Any) -> None:
            nonlocal completed
            if self._stop_requested:
                return
            try:
                async with semaphore:
                    if self._stop_requested:
                        return
                    path = await self.download_message_media(msg, attachments_dir)
                    msg_id = str(
                        getattr(msg, "id", None)
                        or (msg.get("id") if isinstance(msg, dict) else None)
                        or ""
                    )
                    if path and msg_id:
                        try:
                            results[msg_id] = str(
                                path.relative_to(attachments_dir)
                            ).replace("\\", "/")
                        except ValueError:
                            results[msg_id] = str(path)
                    completed += 1
                    # Structured per-file progress event (current/total + the
                    # downloaded file's relative path, when the download succeeded).
                    emit_progress(
                        {
                            "type": "media",
                            "current": completed,
                            "total": total,
                            "file": results.get(msg_id),
                        },
                        sink=getattr(self, "_progress_sink", None),
                    )
                    if completed % log_interval == 0 or completed == total:
                        pct = int(completed / total * 100)
                        self.logger.info(
                            f"Media download progress: {completed}/{total} ({pct}%)"
                        )
            except asyncio.CancelledError:
                # Stop was requested mid-flight; exit cleanly so gather can
                # finish and the CLI can shut down.
                return

        tasks = [asyncio.create_task(download_one(msg)) for msg in messages]

        async def _cancel_watchdog() -> None:
            # Polls _stop_requested and cancels every still-pending task once
            # the user (or a signal handler) asks to stop. This is what makes
            # Ctrl+C actually terminate during a --media run, even if some
            # task is stuck inside Telethon's parallel-download path.
            while True:
                if self._stop_requested:
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    return
                if all(t.done() for t in tasks):
                    return
                await asyncio.sleep(0.5)

        watchdog = asyncio.create_task(_cancel_watchdog())
        try:
            gather_results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            watchdog.cancel()
            try:
                await watchdog
            except (asyncio.CancelledError, Exception):
                pass

        for r in gather_results:
            if isinstance(r, asyncio.CancelledError):
                continue
            if isinstance(r, Exception):
                self.logger.warning(f"Media download task failed: {r}")
        self.logger.info(f"Downloaded {len(results)} media files to {attachments_dir}")

        # Finalize timing and surface the run summary (size/speed/cached/retries)
        # for both the CLI log and the GUI's structured-progress consumer.
        # Elapsed is the actual-download wall-clock window, so cached-file checks
        # and text-only messages stay out of the MB/s basis (0 when nothing was
        # downloaded — speed_mbps already guards on downloaded_bytes too).
        window = self._download_window
        self._media_stats.elapsed_seconds = window[1] - window[0] if window else 0.0
        if self._media_stats.total_files or self._media_stats.failed_files:
            self.logger.info(self._media_stats.summary_line())
        emit_progress(
            self._media_stats.to_event(),
            sink=getattr(self, "_progress_sink", None),
        )
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_media_category(self, media: Any) -> str:
        """Return the category subdirectory name for a media object."""
        if isinstance(media, MessageMediaPhoto):
            return _CAT_IMAGES

        elif isinstance(media, MessageMediaDocument):
            doc = media.document
            if isinstance(doc, Document):
                for attr in doc.attributes:
                    if isinstance(attr, DocumentAttributeSticker):
                        return _CAT_STICKERS
                return self._category_from_mime(doc.mime_type)

        elif isinstance(media, MessageMediaWebPage):
            webpage = media.webpage
            if isinstance(webpage, WebPage):
                if webpage.document and isinstance(webpage.document, Document):
                    for attr in webpage.document.attributes:
                        if isinstance(attr, DocumentAttributeSticker):
                            return _CAT_STICKERS
                    return self._category_from_mime(webpage.document.mime_type)
                elif webpage.photo:
                    return _CAT_IMAGES
            return _CAT_OTHER

        elif isinstance(media, MessageMediaContact):
            return _CAT_CONTACTS

        elif isinstance(
            media, (MessageMediaGeo, MessageMediaGeoLive, MessageMediaVenue)
        ):
            return _CAT_LOCATIONS

        elif isinstance(media, MessageMediaPoll):
            return _CAT_POLLS

        return _CAT_OTHER

    def _category_from_mime(self, mime_type: Optional[str]) -> str:
        """Map a MIME type string to a category name."""
        if not mime_type:
            return _CAT_OTHER
        if mime_type == "application/x-tgsticker":
            return _CAT_STICKERS
        if mime_type.startswith("image/"):
            return _CAT_IMAGES
        if mime_type.startswith("video/"):
            return _CAT_VIDEOS
        if mime_type.startswith("audio/"):
            return _CAT_AUDIO
        if mime_type.startswith("text/"):
            return _CAT_DOCUMENTS
        if mime_type in _ARCHIVE_MIMES:
            return _CAT_ARCHIVES
        if mime_type in _DOCUMENT_MIMES:
            return _CAT_DOCUMENTS
        return _CAT_OTHER

    def _get_extension_from_mime(self, mime_type: Optional[str]) -> str:
        """Derive a file extension from a MIME type string."""
        if not mime_type:
            return ".bin"
        return _MIME_TO_EXT.get(mime_type, ".bin")

    def _serialize_synthetic_media(self, media: Any, target_path: Path) -> bool:
        """Write vCard/JSON for non-binary media types directly to disk.

        Returns True if handled here (no Telethon download call needed).
        """
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(media, MessageMediaContact):
            if media.vcard:
                content = media.vcard
            else:
                content = (
                    "BEGIN:VCARD\nVERSION:3.0\n"
                    f"FN:{media.first_name} {media.last_name}\n"
                    f"TEL:{media.phone_number}\n"
                    "END:VCARD\n"
                )
            target_path.write_text(content, encoding="utf-8")
            return True

        elif isinstance(media, (MessageMediaGeo, MessageMediaGeoLive)):
            geo = media.geo
            if not isinstance(geo, GeoPoint):
                return False
            data: dict = {"lat": geo.lat, "long": geo.long}
            if isinstance(media, MessageMediaGeoLive):
                data["heading"] = getattr(media, "heading", None)
                data["period"] = media.period
            target_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            return True

        elif isinstance(media, MessageMediaVenue):
            geo = media.geo
            data = {
                "title": media.title,
                "address": media.address,
                "provider": media.provider,
                "venue_id": media.venue_id,
                "venue_type": media.venue_type,
                "lat": geo.lat if isinstance(geo, GeoPoint) else None,
                "long": geo.long if isinstance(geo, GeoPoint) else None,
            }
            target_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            return True

        elif isinstance(media, MessageMediaPoll):
            poll = media.poll
            results = media.results
            answers = []
            for ans in poll.answers or []:
                text_val = ans.text
                if hasattr(text_val, "text"):
                    text_val = text_val.text
                answers.append({"text": text_val, "option": ans.option.hex()})
            result_map = {}
            if results and results.results:
                for r in results.results:
                    result_map[r.option.hex()] = r.voters
            for ans in answers:
                ans["voters"] = result_map.get(ans["option"], None)
            question = poll.question
            if hasattr(question, "text"):
                question = question.text
            data = {
                "question": question,
                "answers": answers,
                "total_voters": getattr(results, "total_voters", None),
                "closed": poll.closed,
                "quiz": poll.quiz,
            }
            target_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            return True

        elif isinstance(media, MessageMediaDice):
            data = {"emoticon": media.emoticon, "value": media.value}
            target_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            return True

        elif isinstance(media, MessageMediaGame):
            game = media.game
            data = {
                "id": game.id,
                "short_name": game.short_name,
                "title": game.title,
                "description": game.description,
            }
            target_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            return True

        return False

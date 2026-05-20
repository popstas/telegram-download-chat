"""Media download functionality for Telegram messages."""

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from telethon.errors import FloodWaitError
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
            return download_to

        download_to.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Synthetic types: write directly without a network call
            if self._serialize_synthetic_media(media, download_to):
                return download_to

            downloaded_path = await self._download_binary_media(
                message, media, download_to, message_id
            )
            if downloaded_path:
                self.logger.debug(
                    f"Downloaded media for message {message_id}: {downloaded_path}"
                )
                return Path(downloaded_path)
            self.logger.warning(f"Failed to download media for message {message_id}")
            return None
        except Exception as e:
            self.logger.warning(
                f"Failed to download media for message {message_id}: {e}"
            )
            return None

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
        downloaded_path = await self.client.download_media(message, file=download_to)
        return Path(downloaded_path) if downloaded_path else None

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

"""Media download functionality for Telegram messages."""

from pathlib import Path
from typing import Any, List, Optional

from telethon.tl.types import Document, DocumentAttributeFilename, MessageMediaDocument, MessageMediaPhoto, Photo


class MediaMixin:
    """Mixin class for downloading media from Telegram messages."""

    def _get_original_filename(self, doc: Document) -> Optional[str]:
        """Extract the original filename from document attributes, if present."""
        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                return attr.file_name
        return None

    def get_filename(self, media: Any, use_original_names: bool = False) -> Optional[str]:
        """Returns a filename for the given media object."""
        if isinstance(media, MessageMediaPhoto):
            photo = media.photo
            if isinstance(photo, Photo):
                return f"{photo.id}.jpg"

        elif isinstance(media, MessageMediaDocument):
            doc = media.document
            if isinstance(doc, Document):
                if use_original_names:
                    original = self._get_original_filename(doc)
                    if original:
                        return original
                return f"{doc.id}{self._get_extension_from_mime(doc.mime_type)}"

        return None

    def _get_extension_from_mime(self, mime_type: Optional[str]) -> str:
        """Derive the file extension from its MIME type."""
        if not mime_type:
            return ".bin"

        mime_to_ext = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "video/mp4": ".mp4",
            "video/webm": ".webm",
            "video/quicktime": ".mov",
            "audio/mpeg": ".mp3",
            "audio/ogg": ".ogg",
            "audio/mp4": ".m4a",
            "audio/x-wav": ".wav",
            "application/pdf": ".pdf",
            "application/zip": ".zip",
            "application/x-rar-compressed": ".rar",
            "application/x-7z-compressed": ".7z",
            "text/plain": ".txt",
            "application/json": ".json",
            "application/xml": ".xml",
            "image/tiff": ".tiff",
            "image/bmp": ".bmp",
        }

        return mime_to_ext.get(mime_type, ".bin")

    async def download_message_media(
        self,
        message: Any,
        attachments_dir: Path,
        use_original_names: bool = False,
    ) -> None:
        """Download media from a single message.

        Creates a directory structure:
            attachments_dir/<message_id>/<filename>
        """
        media = getattr(message, "media", None) or (
            message.get("media") if isinstance(message, dict) else None
        )
        if not media:
            return

        filename = self.get_filename(media, use_original_names=use_original_names)
        if not filename:
            return

        message_id = str(
            getattr(message, "id", None)
            or (message.get("id") if isinstance(message, dict) else None)
        )
        if not message_id:
            return

        try:
            # Telethon takes care of creating the directory itself
            download_to = attachments_dir / message_id / filename
            if download_to.exists():
                self.logger.debug(
                    f"Media already exists for message {message_id}, skipping"
                )
                return
            downloaded_path = await self.client.download_media(
                message, file=download_to
            )
            if downloaded_path:
                self.logger.debug(
                    f"Downloaded media for message {message_id}: {downloaded_path}"
                )
            else:
                self.logger.warning(
                    f"Failed to download media for message {message_id}"
                )
        except Exception as e:
            self.logger.warning(
                f"Failed to download media for message {message_id}: {e}"
            )

    async def download_all_media(
        self,
        messages: List[Any],
        attachments_dir: Path,
        use_original_names: bool = False,
    ) -> None:
        """Download media from all messages that have attachments.

        Returns a dict mapping message_id to media info.
        """
        total = len(messages)
        downloaded = 0

        for i, msg in enumerate(messages):
            if self._stop_requested:
                self.logger.info("Stop requested, aborting media download...")
                return

            await self.download_message_media(msg, attachments_dir, use_original_names=use_original_names)
            downloaded += 1

        self.logger.info(f"Downloaded {downloaded} media files to {attachments_dir}")

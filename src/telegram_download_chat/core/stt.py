"""Speech-to-text for voice messages via Telegram Premium transcription.

Telegram transcribes voice messages and round video notes server-side for
Premium accounts (``messages.transcribeAudio``). Telethon exposes it only as a
raw request, so this module wraps it: pick the transcribable messages, look
them up in a local cache, and call the API for whatever is left.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from telethon.errors import FloodWaitError

__all__ = [
    "TranscriptCache",
    "default_cache_path",
    "is_transcribable",
    "transcribe_messages",
    "transcript_key",
]

logger = logging.getLogger(__name__)

#: Delays between re-checks while Telegram reports a transcription as pending.
PENDING_BACKOFF_SECONDS = (2.0, 4.0, 6.0)
#: Longer rate limits abort the whole pass instead of stalling the export.
FLOOD_WAIT_MAX_SECONDS = 30.0
#: How often to log transcription progress.
PROGRESS_LOG_EVERY = 10


def _media_dict(msg: Any) -> Optional[Dict[str, Any]]:
    """Return a message's media as a plain dict, from a raw message or a dict."""
    media = msg.get("media") if isinstance(msg, dict) else getattr(msg, "media", None)
    if media is None:
        return None
    if isinstance(media, dict):
        return media
    to_dict = getattr(media, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:
            return None
    return None


def _document(msg: Any) -> Optional[Dict[str, Any]]:
    media = _media_dict(msg)
    if not media or media.get("_") != "MessageMediaDocument":
        return None
    doc = media.get("document")
    return doc if isinstance(doc, dict) else None


def is_transcribable(msg: Any) -> bool:
    """True for voice messages and round video notes — what Telegram transcribes."""
    doc = _document(msg)
    if not doc:
        return False
    for attr in doc.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        attr_type = attr.get("_")
        if attr_type == "DocumentAttributeAudio" and attr.get("voice"):
            return True
        if attr_type == "DocumentAttributeVideo" and attr.get("round_message"):
            return True
    return False


def transcript_key(msg: Any) -> Optional[int]:
    """Cache key for a message: the media document id, stable across forwards."""
    doc = _document(msg)
    if not doc:
        return None
    doc_id = doc.get("id")
    return doc_id if isinstance(doc_id, int) else None


class TranscriptCache:
    """Append-only JSONL cache of transcriptions, keyed by media document id.

    The document id is stable in Telegram and survives forwarding, so the same
    voice message is never transcribed twice — not on a re-download, not in
    another chat. Each successful transcription appends one line, so a crash
    mid-run keeps everything already transcribed and two concurrent runs cannot
    clobber each other. Failures and pending results are not cached, so a later
    run retries them.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._entries: Dict[int, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as e:
            logger.debug("Failed to read transcript cache %s: %s", self.path, e)
            return
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                logger.debug("Skipping corrupt transcript cache line: %.80s", line)
                continue
            if not isinstance(entry, dict):
                continue
            doc_id = entry.get("doc_id")
            text = entry.get("text")
            if isinstance(doc_id, int) and isinstance(text, str):
                # Later lines win: the file is append-only, so the last write
                # for a document id is the current value.
                self._entries[doc_id] = text

    def get(self, doc_id: Optional[int]) -> Optional[str]:
        if doc_id is None:
            return None
        return self._entries.get(doc_id)

    def put(
        self,
        doc_id: Optional[int],
        text: str,
        chat: Any = None,
        msg_id: Any = None,
    ) -> None:
        if doc_id is None:
            return
        self._entries[doc_id] = text
        entry = {
            "doc_id": doc_id,
            "chat": str(chat) if chat is not None else None,
            "msg_id": msg_id,
            "text": text,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.debug("Failed to append to transcript cache %s: %s", self.path, e)


def default_cache_path() -> Path:
    """Location of the shared transcript cache in the app data directory."""
    from ..paths import get_app_dir

    return get_app_dir() / "stt-cache.jsonl"


def _existing_transcript(msg: Any) -> Optional[str]:
    """A transcript already saved on a previous run (resume path)."""
    value = (
        msg.get("transcript")
        if isinstance(msg, dict)
        else getattr(msg, "transcript", None)
    )
    return value if isinstance(value, str) and value else None


def _field(msg: Any, name: str) -> Any:
    return msg.get(name) if isinstance(msg, dict) else getattr(msg, name, None)


def _peer_ref(peer_id: Any) -> Any:
    """Turn a serialized ``peer_id`` into a Telethon peer, or return it as-is."""
    if not isinstance(peer_id, dict):
        return peer_id
    from telethon.tl.types import PeerChannel, PeerChat, PeerUser

    peer_type = peer_id.get("_")
    if peer_type == "PeerChannel" and peer_id.get("channel_id") is not None:
        return PeerChannel(peer_id["channel_id"])
    if peer_type == "PeerChat" and peer_id.get("chat_id") is not None:
        return PeerChat(peer_id["chat_id"])
    if peer_type == "PeerUser" and peer_id.get("user_id") is not None:
        return PeerUser(peer_id["user_id"])
    return None


async def _input_peer(client: Any, ref: Any, cache: Dict[str, Any]) -> Any:
    key = str(ref)
    if key not in cache:
        cache[key] = await client.get_input_entity(ref)
    return cache[key]


async def _resolve_target(
    client: Any, entity: Any, msg: Any, peer_cache: Dict[str, Any]
) -> Any:
    """Return ``(peer, msg_id)`` addressing a message for transcription.

    Channel comments live in the linked discussion group, so they are addressed
    by their native ``discussion_msg_id`` against that group's peer rather than
    the exported channel post id.
    """
    if _field(msg, "comment_of") is not None:
        ref = _peer_ref(_field(msg, "peer_id"))
        if ref is None:
            return None, None
        msg_id = _field(msg, "discussion_msg_id") or _field(msg, "id")
        return await _input_peer(client, ref, peer_cache), msg_id
    return await _input_peer(client, entity, peer_cache), _field(msg, "id")


async def _transcribe_one(client: Any, peer: Any, msg_id: Any) -> Optional[str]:
    """Transcribe one message, polling while Telegram reports ``pending``.

    A pending result normally arrives via ``UpdateTranscribedAudio``; re-issuing
    the request returns the same (now finished) transcription, which keeps this
    a plain request/response loop.
    """
    from telethon.tl.functions.messages import TranscribeAudioRequest

    attempts = len(PENDING_BACKOFF_SECONDS) + 1
    for attempt in range(attempts):
        result = await client(TranscribeAudioRequest(peer=peer, msg_id=msg_id))
        text = getattr(result, "text", None)
        if not getattr(result, "pending", False):
            return text if isinstance(text, str) and text else None
        if attempt < len(PENDING_BACKOFF_SECONDS):
            await asyncio.sleep(PENDING_BACKOFF_SECONDS[attempt])
    return None


async def transcribe_messages(
    downloader: Any,
    entity: Any,
    messages: Any,
    *,
    cache: Optional[TranscriptCache] = None,
) -> Dict[int, str]:
    """Transcribe voice messages and round video notes in ``messages``.

    Returns a ``{document_id: text}`` map. Document ids are used rather than
    message ids because they are globally unique (a channel post and a comment
    can share a numeric id) and stable across forwards.

    Cached transcripts are served without touching the API, so an account
    without Premium still gets everything transcribed on an earlier run. The
    Premium check — and every request — happens only if something is left.
    """
    log = getattr(downloader, "logger", logger)
    if cache is None:
        cache = TranscriptCache(default_cache_path())

    transcripts: Dict[int, str] = {}
    todo: Dict[int, Any] = {}
    for msg in messages:
        if not is_transcribable(msg) or _existing_transcript(msg):
            continue
        doc_id = transcript_key(msg)
        if doc_id is None:
            continue
        cached = cache.get(doc_id)
        if cached is not None:
            transcripts[doc_id] = cached
        elif doc_id not in todo:
            todo[doc_id] = msg

    if not todo:
        return transcripts

    await downloader._detect_premium_once()
    if not getattr(downloader, "_is_premium", False):
        log.warning(
            "Skipping transcription of %d voice message(s): "
            "Telegram speech-to-text requires a Premium account",
            len(todo),
        )
        return transcripts

    client = downloader.client
    peer_cache: Dict[str, Any] = {}
    total = len(todo)
    log.info("Transcribing %d voice message(s)...", total)
    done = 0
    for doc_id, msg in todo.items():
        try:
            peer, msg_id = await _resolve_target(client, entity, msg, peer_cache)
            if peer is None or msg_id is None:
                continue
            text = await _transcribe_one(client, peer, msg_id)
        except FloodWaitError as e:
            seconds = getattr(e, "seconds", 0) or 0
            if seconds > FLOOD_WAIT_MAX_SECONDS:
                log.warning(
                    "Transcription rate-limited for %ss; skipping the remaining "
                    "%d voice message(s)",
                    seconds,
                    total - done,
                )
                break
            log.debug("Transcription rate-limited, waiting %ss", seconds)
            await asyncio.sleep(seconds)
            try:
                text = await _transcribe_one(client, peer, msg_id)
            except Exception as retry_error:
                log.debug(
                    "Transcription failed for message %s: %s", msg_id, retry_error
                )
                continue
        except Exception as e:
            log.debug("Transcription failed for message %s: %s", _field(msg, "id"), e)
            continue

        done += 1
        if text:
            transcripts[doc_id] = text
            cache.put(doc_id, text, chat=entity, msg_id=msg_id)
        if done % PROGRESS_LOG_EVERY == 0:
            log.info("Transcribed %d/%d voice message(s)", done, total)

    return transcripts

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

from telethon.errors import FloodError

__all__ = [
    "TranscriptCache",
    "default_cache_path",
    "is_transcribable",
    "transcribe_messages",
    "transcript_key",
]

logger = logging.getLogger(__name__)

#: How long to keep collecting transcriptions Telegram reports as pending.
#: Real voice messages take ~15-30s, so this must outlast a slow batch.
PENDING_TIMEOUT_SECONDS = 180.0
#: Delay between collection rounds while transcriptions are still pending.
PENDING_POLL_SECONDS = 5.0
#: Longer rate limits abort the whole pass instead of stalling the export.
FLOOD_WAIT_MAX_SECONDS = 30.0
#: Back-off before retrying a rate-limited request. Telegram's burst limit on
#: transcription arrives as a bare ``FLOOD`` with no retry time of its own, and
#: it clears within a minute, so retry a bounded number of times before giving
#: up on the whole pass.
FLOOD_RETRY_BACKOFF_SECONDS = (5.0, 10.0, 20.0)
#: How often to log transcription progress.
PROGRESS_LOG_EVERY = 10

#: Returned by :func:`_attempt` when Telegram is still working on the audio.
_PENDING = object()


class _RateLimited(Exception):
    """Telegram's transcription rate limit; ends the whole pass."""

    def __init__(self, seconds: float) -> None:
        super().__init__(seconds)
        self.seconds = seconds


def _format_duration(seconds: float) -> str:
    """Render a wait as ``2h 29m`` rather than a raw second count."""
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def _failure_reason(error: Exception) -> str:
    """A short, user-facing reason a message could not be transcribed."""
    text = f"{getattr(error, 'message', '') or ''} {error}"
    if "MSG_VOICE_TOO_LONG" in text:
        return "longer than Telegram transcribes"
    return getattr(error, "message", None) or type(error).__name__


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

    Everything else is addressed by the message's own ``peer_id``, which
    resolves straight from the session cache. The chat identifier the CLI was
    given is a *string*, and Telethon reads a digit string as a username or
    phone number: resolving it costs an online lookup that can rate-limit the
    account for hours and take the whole pass down with it.
    """
    ref = _peer_ref(_field(msg, "peer_id"))
    if _field(msg, "comment_of") is not None:
        if ref is None:
            return None, None
        msg_id = _field(msg, "discussion_msg_id") or _field(msg, "id")
        return await _input_peer(client, ref, peer_cache), msg_id
    if ref is not None:
        try:
            return await _input_peer(client, ref, peer_cache), _field(msg, "id")
        except FloodError:
            raise
        except Exception as e:
            # An unknown peer is worth one fallback to the identifier we were
            # given; a rate limit is not, and is re-raised above.
            logger.debug("Falling back to the chat identifier for the peer: %s", e)
    return await _input_peer(client, entity, peer_cache), _field(msg, "id")


async def _with_flood_retry(call: Any) -> Any:
    """Run ``call``, retrying Telegram's rate limits a bounded number of times.

    Catches ``FloodError`` rather than ``FloodWaitError``: the Premium variant
    is its sibling and not its subclass, and the burst limit arrives as a bare
    ``FLOOD`` carrying no retry time at all. A wait too long to sit out — or one
    that outlasts the retries — becomes :class:`_RateLimited`, which ends the
    pass instead of being re-hit once per message.
    """
    backoff = list(FLOOD_RETRY_BACKOFF_SECONDS)
    while True:
        try:
            return await call()
        except FloodError as e:
            seconds = getattr(e, "seconds", 0) or 0
            if seconds > FLOOD_WAIT_MAX_SECONDS or not backoff:
                raise _RateLimited(seconds) from e
            delay = backoff.pop(0)
            await asyncio.sleep(seconds or delay)


async def _attempt(client: Any, peer: Any, msg_id: Any) -> Any:
    """Issue one transcription request.

    Returns the text, ``None`` when Telegram has nothing to offer, or
    :data:`_PENDING` while it is still working. Raises :class:`_RateLimited`
    when the account's transcription quota is spent.
    """
    from telethon.tl.functions.messages import TranscribeAudioRequest

    result = await _with_flood_retry(
        lambda: client(TranscribeAudioRequest(peer=peer, msg_id=msg_id))
    )
    if getattr(result, "pending", False):
        return _PENDING
    text = getattr(result, "text", None)
    return text if isinstance(text, str) and text else None


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
        if transcripts:
            log.info(
                "%d voice message(s) served from the transcript cache",
                len(transcripts),
            )
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
    if transcripts:
        log.info(
            "Transcribing %d voice message(s) (%d served from the cache)...",
            total,
            len(transcripts),
        )
    else:
        log.info("Transcribing %d voice message(s)...", total)

    pending: Dict[int, Any] = {}
    failures: Dict[str, int] = {}
    rate_limited: Optional[float] = None
    done = 0

    def _store(doc_id: int, text: str, msg_id: Any) -> None:
        nonlocal done
        done += 1
        transcripts[doc_id] = text
        cache.put(doc_id, text, chat=entity, msg_id=msg_id)
        if done % PROGRESS_LOG_EVERY == 0:
            log.info("Transcribed %d/%d voice message(s)", done, total)

    def _record_failure(msg_id: Any, error: Exception) -> None:
        reason = _failure_reason(error)
        failures[reason] = failures.get(reason, 0) + 1
        log.debug("Transcription failed for message %s: %s", msg_id, error)

    # Phase 1 — issue one request per message. Telegram transcribes them in
    # parallel, so the earliest are usually ready by the time the last request
    # goes out; waiting on each in turn would time out on all of them.
    try:
        for doc_id, msg in todo.items():
            msg_id: Any = _field(msg, "id")
            try:
                peer, msg_id = await _with_flood_retry(
                    lambda: _resolve_target(client, entity, msg, peer_cache)
                )
                if peer is None or msg_id is None:
                    continue
                outcome = await _attempt(client, peer, msg_id)
            except _RateLimited:
                raise
            except Exception as e:
                _record_failure(msg_id, e)
                continue
            if outcome is _PENDING:
                pending[doc_id] = (peer, msg_id)
            elif outcome:
                _store(doc_id, outcome, msg_id)
    except _RateLimited as limit:
        # The limit is account-wide, so stop asking for more — but audio
        # already handed to Telegram keeps transcribing, so still collect it.
        rate_limited = limit.seconds

    # Phase 2 — collect whatever was still being transcribed.
    rounds = max(1, int(PENDING_TIMEOUT_SECONDS // max(PENDING_POLL_SECONDS, 1e-9)))
    try:
        for _ in range(rounds):
            if not pending:
                break
            await asyncio.sleep(PENDING_POLL_SECONDS)
            for doc_id in list(pending):
                peer, msg_id = pending[doc_id]
                try:
                    outcome = await _attempt(client, peer, msg_id)
                except _RateLimited:
                    raise
                except Exception as e:
                    del pending[doc_id]
                    _record_failure(msg_id, e)
                    continue
                if outcome is _PENDING:
                    continue
                del pending[doc_id]
                if outcome:
                    _store(doc_id, outcome, msg_id)
    except _RateLimited as limit:
        if rate_limited is None:
            rate_limited = limit.seconds

    if rate_limited is not None:
        log.warning(
            "Transcription rate-limited by Telegram (%s); %d of %d voice "
            "message(s) left untranscribed. Re-run later — audio already "
            "transcribed is served from the local cache.",
            (
                f"retry in {_format_duration(rate_limited)}"
                if rate_limited
                else "no retry time given"
            ),
            total - done - sum(failures.values()),
            total,
        )
    elif pending:
        log.warning(
            "%d voice message(s) were still being transcribed when the pass "
            "gave up after %s; re-run to pick them up.",
            len(pending),
            _format_duration(PENDING_TIMEOUT_SECONDS),
        )
    for reason, count in sorted(failures.items()):
        log.warning("%d voice message(s) could not be transcribed: %s", count, reason)
    log.info("Transcribed %d/%d voice message(s)", done, total)

    return transcripts

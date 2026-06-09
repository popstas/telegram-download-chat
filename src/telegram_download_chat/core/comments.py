"""Download broadcast-channel comments from the linked discussion group.

A broadcast channel keeps its post comments in a linked discussion supergroup.
This module resolves that linked group, downloads it **once** (paginated and
bounded by the in-window posts' date floor), and maps each discussion message to
its parent channel post via the auto-forwarded thread root — replacing the older
per-post ``iter_messages(channel_entity, reply_to=post_id)`` scan that issued one
request per post (including posts with no comments).

Each fetched comment is normalized so the existing reply-thread + anchor logic
(``core/render.py``) nests it under its parent channel post with zero export
changes: both ``reply_to.reply_to_msg_id`` and the top-level ``reply_to_msg_id``
are set to the channel post id, a ``comment_of`` marker is added, and the native
discussion message id is preserved as ``discussion_msg_id``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set

from telethon.errors import FloodWaitError

from .progress import emit_progress
from .reactions import total_reaction_count


def coerce_datetime(value: Any) -> Optional[datetime]:
    """Best-effort parse of a message ``date`` into an aware ``datetime``.

    Accepts a ``datetime`` (live Telethon message), an ISO-8601 string, or the
    ``str(datetime)`` form Telethon serialization produces
    (``"2025-05-01 11:00:00+00:00"``). Returns ``None`` when the value can't be
    parsed — date bounding is an optimization, so an unparseable date simply
    isn't used as a boundary.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        parsed: Optional[datetime] = None
        for candidate in (value, value.replace(" ", "T", 1)):
            try:
                parsed = datetime.fromisoformat(candidate)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def get_comments_checkpoint_path(output_file: Any) -> Path:
    """Return the sidecar checkpoint path for an output file.

    Mirrors the partial-download file convention: a checkpoint lives next to the
    chat's ``messages.json`` and records which post ids have already had their
    comments fetched, so an interrupted ``--comments`` run resumes instead of
    re-scanning every post.
    """
    return Path(output_file).with_suffix(".comments-progress.json")


def load_comments_checkpoint(path: Any) -> Set[int]:
    """Load the set of post ids whose comments were already fetched.

    Returns an empty set when the checkpoint is missing or unreadable so callers
    fall back to scanning every post (the dedup logic keeps that correct, just
    slower).
    """
    p = Path(path)
    if not p.exists():
        return set()
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    done: Set[int] = set()
    if isinstance(data, list):
        for pid in data:
            try:
                done.add(int(pid))
            except (TypeError, ValueError):
                continue
    return done


def save_comments_checkpoint(path: Any, done_post_ids: Iterable[int]) -> None:
    """Persist the set of fetched-post ids to the checkpoint file (best-effort)."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(sorted(int(pid) for pid in done_post_ids), f)
    except OSError:
        # Checkpointing is an optimization; a write failure must not abort the run.
        pass


def clear_comments_checkpoint(path: Any) -> None:
    """Remove the checkpoint file if present (best-effort)."""
    p = Path(path)
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass


async def get_linked_discussion(downloader: Any, entity: Any) -> Optional[int]:
    """Return the linked discussion group id for a broadcast channel, or ``None``.

    Runs ``GetFullChannelRequest`` and reads ``full_chat.linked_chat_id``. A
    channel with no linked discussion group (or any failure resolving it)
    returns ``None`` so callers can skip comment fetching cleanly.
    """
    from telethon.tl.functions.channels import GetFullChannelRequest

    client = getattr(downloader, "client", None)
    if client is None:
        raise RuntimeError("Telegram client is not connected")

    logger = getattr(downloader, "logger", None)
    try:
        full = await client(GetFullChannelRequest(channel=entity))
    except Exception as exc:  # noqa: BLE001 - resolution is best-effort
        if logger is not None:
            logger.debug("Could not resolve linked discussion group: %s", exc)
        return None

    full_chat = getattr(full, "full_chat", None)
    linked = getattr(full_chat, "linked_chat_id", None)
    if not linked:
        return None
    try:
        return int(linked)
    except (TypeError, ValueError):
        return None


def _normalize_comment(downloader: Any, msg: Any, post_id: int) -> Dict[str, Any]:
    """Convert a fetched comment into a normalized, serializable dict.

    Sets ``reply_to.reply_to_msg_id`` and the top-level ``reply_to_msg_id`` to
    the channel ``post_id``, adds ``comment_of=post_id``, and preserves the
    native discussion message id as ``discussion_msg_id``.
    """
    if hasattr(msg, "to_dict"):
        raw = msg.to_dict()
    else:
        raw = msg

    make_serializable = getattr(downloader, "make_serializable", None)
    if make_serializable is not None:
        data = make_serializable(raw)
    else:
        data = dict(raw) if isinstance(raw, dict) else raw

    if not isinstance(data, dict):
        # Fall back to a minimal dict so downstream code stays uniform.
        data = {"id": getattr(msg, "id", None)}

    data["discussion_msg_id"] = data.get("id")
    data["comment_of"] = post_id

    reply_to = data.get("reply_to")
    if not isinstance(reply_to, dict):
        reply_to = {}
    reply_to["reply_to_msg_id"] = post_id
    data["reply_to"] = reply_to
    data["reply_to_msg_id"] = post_id

    return data


def _attr_or_key(obj: Any, name: str) -> Any:
    """Read ``name`` from a dict key or an object attribute, ``None`` if absent.

    Discussion messages reach the mapper either as live Telethon objects (the
    real fetch path) or as serialized dicts (the unit-test fixtures), so field
    access must work on both.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def map_discussion_to_comments(
    downloader: Any,
    discussion_messages: Sequence[Any],
    post_ids: Sequence[int],
    *,
    limit: Optional[int] = None,
    min_reactions: int = 0,
) -> tuple[List[Dict[str, Any]], List[Any]]:
    """Map a single discussion-group download onto per-post comments.

    A broadcast post is auto-forwarded into the linked discussion group as a
    *thread root* carrying ``fwd_from.channel_post`` (the original channel post
    id). Every comment replies within that thread, so its
    ``reply_to.reply_to_top_id`` (nested replies) or
    ``reply_to.reply_to_msg_id`` (direct replies) points back at the root's
    discussion id. This builds ``root_to_post`` from the forwarded roots, then
    maps each comment to its parent post — replacing the per-post
    ``iter_messages(reply_to=post_id)`` scan with one pass over the discussion.

    Args:
        downloader: Object exposing ``logger`` and ``make_serializable``.
        discussion_messages: Messages from the linked discussion group (live
            Telethon objects or serialized dicts).
        post_ids: Ids of the in-window channel posts; comments whose mapped post
            is outside this set are dropped.
        limit: Max comments per post (group-then-cap). ``None`` / ``0`` keeps
            all, matching ``--comments-limit``.
        min_reactions: Drop comments whose total reaction count is below this
            value (applied after ``limit``, mirroring the per-post path); their
            raw media messages are excluded too.

    Returns:
        ``(comments, raw_media_messages)`` — a flat list of normalized comment
        dicts and the subset of source messages that carry media (keyed by id,
        which equals each comment's ``discussion_msg_id``) for a later media
        download pass.
    """
    logger = getattr(downloader, "logger", None)
    post_id_set = {int(p) for p in post_ids}
    unlimited = not limit or limit <= 0

    # Phase 1: forwarded thread roots -> parent channel post id.
    root_to_post: Dict[int, int] = {}
    for msg in discussion_messages:
        channel_post = _attr_or_key(_attr_or_key(msg, "fwd_from"), "channel_post")
        if channel_post is None:
            continue
        msg_id = _attr_or_key(msg, "id")
        if msg_id is not None:
            root_to_post[msg_id] = channel_post

    # Phase 2: group every non-root comment under its parent post (input order).
    grouped: Dict[int, List[Any]] = {}
    for msg in discussion_messages:
        msg_id = _attr_or_key(msg, "id")
        if msg_id in root_to_post:
            continue  # forwarded root, not a comment
        reply_to = _attr_or_key(msg, "reply_to")
        if reply_to is None:
            continue  # service / non-reply message
        root_id = _attr_or_key(reply_to, "reply_to_top_id") or _attr_or_key(
            reply_to, "reply_to_msg_id"
        )
        post_id = root_to_post.get(root_id)
        if post_id is None or post_id not in post_id_set:
            if logger is not None:
                logger.debug(
                    "Discussion message %s maps to root %s with no in-window "
                    "post; skipping",
                    msg_id,
                    root_id,
                )
            continue
        grouped.setdefault(post_id, []).append(msg)

    # Iterate posts in the order they were requested for deterministic output.
    ordered_posts: List[int] = []
    seen: Set[int] = set()
    for p in post_ids:
        pi = int(p)
        if pi in grouped and pi not in seen:
            ordered_posts.append(pi)
            seen.add(pi)

    comments: List[Dict[str, Any]] = []
    raw_media_messages: List[Any] = []
    for post_id in ordered_posts:
        msgs = grouped[post_id]
        if not unlimited:
            msgs = msgs[:limit]
        post_comments = [_normalize_comment(downloader, m, post_id) for m in msgs]
        post_raw = [m for m in msgs if _attr_or_key(m, "media")]

        # Quality gate: drop low-reaction comments and their media (matches the
        # per-post path's post-fetch filter).
        if min_reactions > 0:
            kept_disc_ids: Set[Any] = set()
            filtered: List[Dict[str, Any]] = []
            for comment in post_comments:
                if total_reaction_count(comment.get("reactions")) >= min_reactions:
                    filtered.append(comment)
                    disc_id = comment.get("discussion_msg_id")
                    if disc_id is not None:
                        kept_disc_ids.add(disc_id)
            post_comments = filtered
            post_raw = [m for m in post_raw if _attr_or_key(m, "id") in kept_disc_ids]

        comments.extend(post_comments)
        raw_media_messages.extend(post_raw)

    return comments, raw_media_messages


async def fetch_discussion_messages(
    downloader: Any,
    linked_id: Any,
    *,
    min_date: Optional[datetime] = None,
    stop_check: Optional[Callable[[], bool]] = None,
    silent: bool = False,
) -> List[Any]:
    """Download the linked discussion group once, newest-first.

    Resolves the discussion entity via ``downloader.get_entity(linked_id)`` and
    pages it with a single ``client.iter_messages`` pass. ``iter_messages``
    yields newest-first, so once a message older than ``min_date`` is reached the
    pass stops early: a comment is always at least as new as the post it replies
    to, so nothing older than the in-window posts' date floor can map to an
    in-window post. ``min_date`` is purely an optimization — correctness comes
    from the post-id filter in :func:`map_discussion_to_comments`.

    A ``FloodWaitError`` sleeps and restarts the pass from scratch (mirroring the
    old per-post retry); a stop request returns the messages collected so far.

    Args:
        downloader: Object exposing ``client``, ``logger`` and ``get_entity``.
        linked_id: Id of the linked discussion supergroup.
        min_date: Stop paging once messages older than this aware datetime are
            reached. ``None`` pages the whole group.
        stop_check: Optional callable; when it returns True the pass stops.
            ``downloader._stop_requested`` is also honored.
        silent: Suppress info logging when True.

    Returns:
        The fetched discussion messages (live Telethon objects).
    """
    client = getattr(downloader, "client", None)
    if client is None:
        raise RuntimeError("Telegram client is not connected")

    logger = getattr(downloader, "logger", None)
    entity = await downloader.get_entity(linked_id)

    def _should_stop() -> bool:
        if getattr(downloader, "_stop_requested", False):
            return True
        if stop_check is not None:
            try:
                return bool(stop_check())
            except Exception:  # noqa: BLE001 - stop checks must never crash the run
                return False
        return False

    while True:
        # Restart the list per attempt so a mid-iteration flood-wait retry
        # re-pages from scratch instead of duplicating messages.
        messages: List[Any] = []
        try:
            async for msg in client.iter_messages(entity):
                if _should_stop():
                    if logger is not None and not silent:
                        logger.info(
                            "Stop requested, breaking discussion download loop..."
                        )
                    return messages
                if min_date is not None:
                    msg_date = coerce_datetime(_attr_or_key(msg, "date"))
                    if msg_date is not None and msg_date < min_date:
                        return messages
                messages.append(msg)
            return messages
        except FloodWaitError as exc:
            wait = exc.seconds + 1
            if logger is not None and not silent:
                logger.info(
                    f"Flood-wait {wait}s while fetching discussion, sleeping..."
                )
            await asyncio.sleep(wait)
            continue
        except Exception as exc:  # noqa: BLE001 - comment fetch is best-effort
            # The call site isn't wrapped, so a discussion-download failure must
            # not abort the whole run: log and return what was collected.
            if logger is not None and not silent:
                logger.warning("Failed to fetch discussion messages: %s", exc)
            return messages


async def download_post_comments(
    downloader: Any,
    linked_id: Any,
    post_ids: Sequence[int],
    *,
    min_date: Optional[datetime] = None,
    silent: bool = False,
    stop_check: Optional[Callable[[], bool]] = None,
    limit: Optional[int] = None,
    min_reactions: int = 0,
    download_media: bool = False,
    attachments_dir: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Fetch comments for the given channel ``post_ids`` in a single pass.

    Downloads the linked discussion group once
    (:func:`fetch_discussion_messages`) and maps its messages onto the requested
    posts (:func:`map_discussion_to_comments`), replacing the old per-post
    ``iter_messages(reply_to=post_id)`` scan. Each comment is normalized to point
    at its parent post (see :func:`_normalize_comment`).

    Args:
        downloader: Object exposing ``client``, ``logger``, ``get_entity`` and
            ``make_serializable`` (the ``TelegramChatDownloader``).
        linked_id: Id of the linked discussion supergroup to download.
        post_ids: Ids of the in-window channel posts whose comments to keep.
        min_date: Date floor of the in-window posts; bounds the discussion
            download (optimization only — see :func:`fetch_discussion_messages`).
        silent: Suppress info logging when True.
        stop_check: Optional callable; when it returns True the discussion pass
            stops. ``downloader._stop_requested`` is also honored.
        limit: Max comments per post (group-then-cap). A positive int caps each
            post; ``None`` / ``0`` means unlimited.
        min_reactions: Drop comments whose total reaction count
            (:func:`total_reaction_count`) is below this value. ``0`` keeps all.
            Applied after ``limit`` and before comment media is downloaded, so
            dropped comments never trigger a media fetch.
        download_media: When True (and ``attachments_dir`` is set), download
            the attachments of comments that carry media, reusing
            ``downloader.download_all_media``. Each downloaded comment's
            normalized dict gets an ``attachment_path`` so the saved JSON keeps
            it and the HTML export renders it inline.
        attachments_dir: Target attachments directory for comment media; must
            match the chat's ``attachments/`` dir so ``save_messages`` finds the
            downloaded files.

    Returns:
        A flat list of normalized comment dicts across all in-window posts.
    """
    want_media = bool(download_media) and attachments_dir is not None

    discussion_messages = await fetch_discussion_messages(
        downloader,
        linked_id,
        min_date=min_date,
        stop_check=stop_check,
        silent=silent,
    )

    comments, raw_media_messages = map_discussion_to_comments(
        downloader,
        discussion_messages,
        post_ids,
        limit=limit,
        min_reactions=min_reactions,
    )

    # Single progress event for the whole discussion pass (replacing the old
    # per-post emission); the GUI surfaces it the same way.
    total_posts = len(post_ids)
    emit_progress(
        {
            "type": "comments",
            "posts_done": total_posts,
            "posts_total": total_posts,
            "comments": len(comments),
        },
        sink=getattr(downloader, "_progress_sink", None),
    )

    if want_media and raw_media_messages and attachments_dir is not None:
        await _download_comment_media(
            downloader, comments, raw_media_messages, Path(attachments_dir), silent
        )

    return comments


async def _download_comment_media(
    downloader: Any,
    comments: List[Dict[str, Any]],
    raw_media_messages: List[Any],
    attachments_dir: Path,
    silent: bool,
) -> None:
    """Download comment attachments and stamp ``attachment_path`` on the dicts.

    Reuses ``downloader.download_all_media`` (concurrency, fast-download, and
    expired-reference recovery) on the raw Telethon comment messages. The
    returned mapping is keyed by ``str(message id)``; a comment's native
    discussion id (``discussion_msg_id``) is that same id, so the resulting
    relative path is copied onto each matching normalized comment dict. The file
    lands in the chat's ``attachments/`` dir, where ``save_messages`` then finds
    it and keeps the path in the saved JSON / HTML export.
    """
    logger = getattr(downloader, "logger", None)
    if logger is not None and not silent:
        logger.info("Downloading media for %d comment(s)...", len(raw_media_messages))
    try:
        results = await downloader.download_all_media(
            raw_media_messages, attachments_dir
        )
    except Exception as exc:  # noqa: BLE001 - media is best-effort enrichment
        if logger is not None and not silent:
            logger.warning("Failed to download comment media: %s", exc)
        return

    if not results:
        return
    for comment in comments:
        disc_id = comment.get("discussion_msg_id")
        if disc_id is None:
            continue
        rel = results.get(str(disc_id))
        if rel:
            comment["attachment_path"] = rel


__all__ = [
    "download_post_comments",
    "fetch_discussion_messages",
    "map_discussion_to_comments",
    "coerce_datetime",
    "get_linked_discussion",
    "get_comments_checkpoint_path",
    "load_comments_checkpoint",
    "save_comments_checkpoint",
    "clear_comments_checkpoint",
]

"""Download broadcast-channel comments from the linked discussion group.

A broadcast channel keeps its post comments in a linked discussion supergroup.
This module resolves that linked group and fetches the per-post comment threads
via Telethon's ``iter_messages(channel_entity, reply_to=post_id)``, which maps a
channel-post id onto the discussion thread internally.

Each fetched comment is normalized so the existing reply-thread + anchor logic
(``core/render.py``) nests it under its parent channel post with zero export
changes: both ``reply_to.reply_to_msg_id`` and the top-level ``reply_to_msg_id``
are set to the channel post id, a ``comment_of`` marker is added, and the native
discussion message id is preserved as ``discussion_msg_id``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set

from telethon.errors import FloodWaitError, MsgIdInvalidError

from .progress import emit_progress
from .reactions import total_reaction_count


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


async def download_post_comments(
    downloader: Any,
    channel_entity: Any,
    post_ids: Sequence[int],
    *,
    silent: bool = False,
    stop_check: Optional[Callable[[], bool]] = None,
    limit: Optional[int] = None,
    min_reactions: int = 0,
    download_media: bool = False,
    attachments_dir: Optional[Any] = None,
    on_post_done: Optional[Callable[[int], None]] = None,
) -> List[Dict[str, Any]]:
    """Fetch comment threads for the given channel ``post_ids``.

    For each post id, pages ``client.iter_messages(channel_entity,
    reply_to=post_id)`` and normalizes every comment to point at its parent
    post (see :func:`_normalize_comment`).

    Args:
        downloader: Object exposing ``client``, ``logger`` and
            ``make_serializable`` (the ``TelegramChatDownloader``).
        channel_entity: Resolved broadcast-channel entity.
        post_ids: Ids of the channel posts whose comments to fetch.
        silent: Suppress info logging when True.
        stop_check: Optional callable; when it returns True the fetch stops
            between posts. ``downloader._stop_requested`` is also honored.
        limit: Max comments per post. A positive int caps each post;
            ``None`` / ``0`` means unlimited.
        min_reactions: Drop comments whose total reaction count
            (:func:`total_reaction_count`) is below this value. ``0`` keeps all.
            Applied after ``limit`` (which caps how many are fetched) and before
            comment media is downloaded, so dropped comments never trigger a
            media fetch.
        download_media: When True (and ``attachments_dir`` is set), download
            the attachments of comments that carry media, reusing
            ``downloader.download_all_media``. Each downloaded comment's
            normalized dict gets an ``attachment_path`` so the saved JSON keeps
            it and the HTML export renders it inline.
        attachments_dir: Target attachments directory for comment media; must
            match the chat's ``attachments/`` dir so ``save_messages`` finds the
            downloaded files.
        on_post_done: Optional callback invoked with each post id once that
            post's comment thread has been fully scanned (including posts with
            no comments / comments disabled). Used to checkpoint resume progress.
            Not called for posts skipped due to a transient fetch failure, so a
            restart retries them.

    Returns:
        A flat list of normalized comment dicts across all posts.
    """
    client = getattr(downloader, "client", None)
    if client is None:
        raise RuntimeError("Telegram client is not connected")

    logger = getattr(downloader, "logger", None)
    unlimited = not limit or limit <= 0
    want_media = bool(download_media) and attachments_dir is not None

    def _should_stop() -> bool:
        if getattr(downloader, "_stop_requested", False):
            return True
        if stop_check is not None:
            try:
                return bool(stop_check())
            except Exception:  # noqa: BLE001 - stop checks must never crash the run
                return False
        return False

    comments: List[Dict[str, Any]] = []
    # Raw Telethon comment messages that carry media, kept so they can be
    # batch-downloaded after the fetch loop (download needs the live objects,
    # not the serialized dicts). Their ids are the native discussion ids, which
    # match each normalized comment's ``discussion_msg_id``.
    raw_media_messages: List[Any] = []
    total_posts = len(post_ids)

    for idx, post_id in enumerate(post_ids):
        if _should_stop():
            if logger is not None and not silent:
                logger.info("Stop requested, breaking comment download loop...")
            break

        post_comments: List[Dict[str, Any]] = []
        post_raw_media: List[Any] = []
        # Whether the post's thread was actually scanned (success or legitimately
        # empty). A transient failure leaves this False so the post is retried on
        # the next run rather than checkpointed as done.
        scanned = False
        while True:
            # Restart the list per attempt so a mid-iteration flood-wait retry
            # re-fetches from scratch instead of duplicating comments.
            post_comments = []
            post_raw_media = []
            try:
                async for msg in client.iter_messages(channel_entity, reply_to=post_id):
                    post_comments.append(_normalize_comment(downloader, msg, post_id))
                    if want_media and getattr(msg, "media", None):
                        post_raw_media.append(msg)
                    if not unlimited and len(post_comments) >= limit:
                        break
                scanned = True
                break
            except FloodWaitError as exc:
                wait = exc.seconds + 1
                if logger is not None and not silent:
                    logger.info(
                        f"Flood-wait {wait}s while fetching comments, sleeping..."
                    )
                await asyncio.sleep(wait)
                continue
            except MsgIdInvalidError:
                # Comments disabled or post id not valid for discussion; skip it.
                if logger is not None and not silent:
                    logger.info(
                        f"Post {post_id} has no comments (or comments disabled), skipping"
                    )
                post_comments = []
                scanned = True
                break
            except (
                Exception
            ) as exc:  # noqa: BLE001 - one bad post must not abort the rest
                if logger is not None and not silent:
                    logger.warning(
                        f"Failed to fetch comments for post {post_id}: {exc}"
                    )
                post_comments = []
                scanned = False
                break

        # Quality gate: drop low-reaction comments after the (limit-capped)
        # fetch and before any media download, so dropped comments never trigger
        # a media fetch. Their raw media messages are excluded by id too.
        if min_reactions > 0 and post_comments:
            kept_disc_ids = set()
            filtered: List[Dict[str, Any]] = []
            for comment in post_comments:
                if total_reaction_count(comment.get("reactions")) >= min_reactions:
                    filtered.append(comment)
                    disc_id = comment.get("discussion_msg_id")
                    if disc_id is not None:
                        kept_disc_ids.add(disc_id)
            post_comments = filtered
            if post_raw_media:
                post_raw_media = [
                    m for m in post_raw_media if getattr(m, "id", None) in kept_disc_ids
                ]

        comments.extend(post_comments)
        if want_media and post_raw_media:
            raw_media_messages.extend(post_raw_media)

        if scanned and on_post_done is not None:
            on_post_done(post_id)

        emit_progress(
            {
                "type": "comments",
                "posts_done": idx + 1,
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
    "get_linked_discussion",
    "get_comments_checkpoint_path",
    "load_comments_checkpoint",
    "save_comments_checkpoint",
    "clear_comments_checkpoint",
]

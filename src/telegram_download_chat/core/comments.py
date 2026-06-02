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
from typing import Any, Callable, Dict, List, Optional, Sequence

from telethon.errors import FloodWaitError, MsgIdInvalidError

from .progress import emit_progress


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

    Returns:
        A flat list of normalized comment dicts across all posts.
    """
    client = getattr(downloader, "client", None)
    if client is None:
        raise RuntimeError("Telegram client is not connected")

    logger = getattr(downloader, "logger", None)
    unlimited = not limit or limit <= 0

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
    total_posts = len(post_ids)

    for idx, post_id in enumerate(post_ids):
        if _should_stop():
            if logger is not None and not silent:
                logger.info("Stop requested, breaking comment download loop...")
            break

        post_comments: List[Dict[str, Any]] = []
        while True:
            # Restart the list per attempt so a mid-iteration flood-wait retry
            # re-fetches from scratch instead of duplicating comments.
            post_comments = []
            try:
                async for msg in client.iter_messages(channel_entity, reply_to=post_id):
                    post_comments.append(_normalize_comment(downloader, msg, post_id))
                    if not unlimited and len(post_comments) >= limit:
                        break
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
                break
            except (
                Exception
            ) as exc:  # noqa: BLE001 - one bad post must not abort the rest
                if logger is not None and not silent:
                    logger.warning(
                        f"Failed to fetch comments for post {post_id}: {exc}"
                    )
                post_comments = []
                break

        comments.extend(post_comments)

        emit_progress(
            {
                "type": "comments",
                "posts_done": idx + 1,
                "posts_total": total_posts,
                "comments": len(comments),
            },
            sink=getattr(downloader, "_progress_sink", None),
        )

    return comments


__all__ = ["download_post_comments", "get_linked_discussion"]

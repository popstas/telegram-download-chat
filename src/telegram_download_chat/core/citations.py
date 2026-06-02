"""Fetch cited/replied messages that fall outside the requested date window.

A downloaded message may ``reply_to`` another message whose date lies outside
the requested ``--min-date``/``--max-date`` window. That referenced message is
therefore never fetched by the windowed history walk, leaving the citation empty
in JSON/TXT/HTML output.

This module collects those dangling reply references and fetches the missing
messages by id via ``client.get_messages(entity, ids=[...])`` so the citation is
populated. Channel-comment records (those carrying ``comment_of``) are skipped:
their reply target is the parent channel post (already present) and their own
reply ids live in the linked discussion group's separate id space, which cannot
be resolved against the channel entity.
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional, Sequence

from telethon.errors import FloodWaitError

# Telegram caps a single get_messages(ids=...) call; fetch missing ids in chunks.
_CHUNK_SIZE = 100


def _msg_id(msg: Any) -> Any:
    return msg.get("id") if isinstance(msg, dict) else getattr(msg, "id", None)


def _comment_of(msg: Any) -> Any:
    return (
        msg.get("comment_of")
        if isinstance(msg, dict)
        else getattr(msg, "comment_of", None)
    )


def _reply_to_id(msg: Any) -> Any:
    """Return the reply-to message id of ``msg`` (dict or Telethon object)."""
    if isinstance(msg, dict):
        reply = msg.get("reply_to")
        if isinstance(reply, dict):
            rid = reply.get("reply_to_msg_id")
            if rid:
                return rid
        return msg.get("reply_to_msg_id")
    reply = getattr(msg, "reply_to", None)
    rid = getattr(reply, "reply_to_msg_id", None)
    if rid:
        return rid
    return getattr(msg, "reply_to_msg_id", None)


def _reply_is_cross_peer(msg: Any) -> bool:
    """True when the reply targets a message in a *different* peer.

    A Telegram quote-reply to another chat/channel carries a non-null
    ``reply_to_peer_id``; its ``reply_to_msg_id`` lives in that other peer's id
    space and must not be fetched against the current entity (it would resolve
    to an unrelated, same-numbered message or to nothing).
    """
    if isinstance(msg, dict):
        reply = msg.get("reply_to")
        if isinstance(reply, dict):
            return reply.get("reply_to_peer_id") is not None
        return False
    reply = getattr(msg, "reply_to", None)
    return getattr(reply, "reply_to_peer_id", None) is not None


def collect_missing_cited_ids(messages: Sequence[Any]) -> List[int]:
    """Return reply-target ids referenced by non-comment messages but absent.

    Only real chat/channel messages (``comment_of is None``) are considered, and
    only references that are not already present in ``messages`` are returned.
    The result is sorted descending (newest first) for deterministic fetching.
    """
    present: set = set()
    for msg in messages:
        if _comment_of(msg) is not None:
            continue
        mid = _msg_id(msg)
        if mid is not None:
            present.add(mid)

    missing: set = set()
    for msg in messages:
        if _comment_of(msg) is not None:
            continue
        if _reply_is_cross_peer(msg):
            continue
        rid = _reply_to_id(msg)
        if not isinstance(rid, int):
            continue
        if rid in present:
            continue
        missing.add(rid)

    return sorted(missing, reverse=True)


async def fetch_cited_messages(
    downloader: Any,
    entity: Any,
    messages: Sequence[Any],
    *,
    silent: bool = False,
) -> List[Any]:
    """Fetch messages referenced by replies but missing from ``messages``.

    Args:
        downloader: Object exposing ``client`` and ``logger``.
        entity: Resolved chat/channel entity to fetch the cited messages from.
        messages: The already-downloaded messages (dicts and/or Telethon
            objects).
        silent: Suppress info logging when True.

    Returns:
        A flat list of fetched message objects (those that resolved); empty when
        there is nothing missing to fetch.
    """
    client = getattr(downloader, "client", None)
    if client is None:
        raise RuntimeError("Telegram client is not connected")

    logger = getattr(downloader, "logger", None)

    missing_ids = collect_missing_cited_ids(messages)
    if not missing_ids:
        return []

    if logger is not None and not silent:
        logger.info(
            f"Fetching {len(missing_ids)} cited message(s) outside the date window..."
        )

    fetched: List[Any] = []
    for start in range(0, len(missing_ids), _CHUNK_SIZE):
        chunk = missing_ids[start : start + _CHUNK_SIZE]
        while True:
            try:
                result = await client.get_messages(entity, ids=chunk)
                break
            except FloodWaitError as exc:
                wait = exc.seconds + 1
                if logger is not None and not silent:
                    logger.info(
                        f"Flood-wait {wait}s while fetching cited messages, sleeping..."
                    )
                await asyncio.sleep(wait)
                continue
            except Exception as exc:  # noqa: BLE001 - best-effort enrichment
                if logger is not None and not silent:
                    logger.warning(f"Failed to fetch cited messages {chunk}: {exc}")
                result = None
                break

        if result is None:
            continue
        if not isinstance(result, (list, tuple)):
            result = [result]
        for msg in result:
            if msg is None:
                continue
            fetched.append(msg)

    if logger is not None and not silent:
        logger.info(f"Fetched {len(fetched)} cited message(s)")

    return fetched


__all__ = ["collect_missing_cited_ids", "fetch_cited_messages"]

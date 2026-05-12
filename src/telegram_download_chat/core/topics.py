"""Forum topic enumeration and per-topic message grouping."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


GENERAL_KEY = "general"
GENERAL_TITLE = "General"


def slugify_topic(title: str, topic_id: int) -> str:
    """Sanitize a forum-topic title into a filesystem-safe directory name.

    Mirrors the chat-name sanitization in core/entities.py. Falls back to
    ``topic_<id>`` when the title slugifies to an empty string.
    """
    base = (title or "").strip().lower()
    base = re.sub(r"[^\w\-.]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_")
    base = base[:80].rstrip("_.")
    if not base or base == GENERAL_KEY:
        return f"topic_{topic_id}"
    return base


async def fetch_forum_topics(downloader: Any, entity: Any) -> Dict[int, str]:
    """Return ``{topic_id: title}`` for a forum supergroup.

    Raises ``ValueError`` if the entity is not a forum.
    """
    from telethon.tl.functions.messages import GetForumTopicsRequest

    if not getattr(entity, "forum", False):
        raise ValueError("Chat is not a forum supergroup")

    client = getattr(downloader, "client", None)
    if client is None:
        raise RuntimeError("Telegram client is not connected")

    topics: Dict[int, str] = {}
    offset_topic = 0
    offset_id = 0
    offset_date = None
    page_limit = 100

    while True:
        result = await client(
            GetForumTopicsRequest(
                peer=entity,
                offset_date=offset_date,
                offset_id=offset_id,
                offset_topic=offset_topic,
                limit=page_limit,
            )
        )
        page = getattr(result, "topics", []) or []
        # ForumTopics carries a mix of ForumTopic and ForumTopicDeleted entries;
        # skip deleted ones (they have no .title).
        for topic in page:
            tid = getattr(topic, "id", None)
            title = getattr(topic, "title", None)
            if tid is None or title is None:
                continue
            topics[int(tid)] = title

        if not page or len(page) < page_limit:
            break
        last = page[-1]
        next_offset_topic = getattr(last, "id", None)
        next_offset_id = getattr(last, "top_message", 0) or 0
        next_offset_date = getattr(last, "date", None)
        if next_offset_topic is None or next_offset_topic == offset_topic:
            break
        offset_topic = int(next_offset_topic)
        offset_id = int(next_offset_id)
        offset_date = next_offset_date

    return topics


def _extract_topic_id(msg: Any) -> int | None:
    """Read a message's parent topic id from its reply_to header.

    Mirrors the field handling in ``filter_messages_by_subchat``:
    prefers ``reply_to_top_id``; falls back to ``reply_to_msg_id`` when
    the reply header is marked as ``forum_topic``.
    """
    if isinstance(msg, dict):
        reply_to = msg.get("reply_to")
    else:
        reply_to = getattr(msg, "reply_to", None)
        if reply_to is not None and hasattr(reply_to, "to_dict"):
            reply_to = reply_to.to_dict()

    if not reply_to:
        return None
    if not isinstance(reply_to, dict):
        return None

    top_id = reply_to.get("reply_to_top_id")
    if top_id is not None:
        try:
            return int(top_id)
        except (TypeError, ValueError):
            return None

    if reply_to.get("forum_topic"):
        msg_id = reply_to.get("reply_to_msg_id")
        if msg_id is not None:
            try:
                return int(msg_id)
            except (TypeError, ValueError):
                return None

    return None


def group_messages_by_topic(
    messages: List[Any], topics_map: Dict[int, str]
) -> Dict[str, Tuple[str, List[Any]]]:
    """Bucket messages by parent forum topic.

    Returns a mapping ``{key: (title, [messages])}``. The key is the
    stringified topic id for known topics, or ``"general"`` for messages
    with no topic link or with a topic id missing from ``topics_map``.
    Buckets are only created when they receive at least one message.
    """
    buckets: Dict[str, Tuple[str, List[Any]]] = {}
    for msg in messages:
        topic_id = _extract_topic_id(msg)
        if topic_id is not None and topic_id in topics_map:
            key = str(topic_id)
            title = topics_map[topic_id]
        else:
            key = GENERAL_KEY
            title = GENERAL_TITLE
        if key not in buckets:
            buckets[key] = (title, [])
        buckets[key][1].append(msg)
    return buckets


__all__ = [
    "GENERAL_KEY",
    "GENERAL_TITLE",
    "fetch_forum_topics",
    "group_messages_by_topic",
    "slugify_topic",
]

"""Unread state of a chat for ``--unread`` downloads.

The cursor comes from the session account's dialog (``read_inbox_max_id``),
never from the output file. Nothing here marks anything as read: only
``messages.getPeerDialogs`` and the forum-topic listings are called, which are
read-only.

Forum supergroups keep a read state per topic, and the dialog-level counters of
a forum do not add up to the topics' (live: dialog ``unread_count`` 457, topics
714). So a forum without ``--subchat`` is read per topic: the download starts
at the oldest unread topic's cursor and each message is then kept only if it is
newer than its own topic's cursor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .topics import _extract_topic_id

GENERAL_TOPIC_ID = 1


class UnreadError(ValueError):
    """The chat's unread state cannot be read (e.g. it is not in the dialogs)."""


@dataclass
class UnreadState:
    """Where the unread part of a chat starts."""

    unread_count: int
    read_inbox_max_id: int
    unread_mark: bool = False
    # Forum without --subchat: {topic_id: read_inbox_max_id} of unread topics.
    topic_cursors: Dict[int, int] = field(default_factory=dict)
    # Forum without --subchat: per-topic details for --results-json.
    topics: List[Dict[str, Any]] = field(default_factory=list)
    # Forum topic picked with --subchat.
    topic_id: Optional[int] = None

    def to_result(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "unread_count": self.unread_count,
            "read_inbox_max_id": self.read_inbox_max_id,
        }
        if self.unread_mark:
            result["unread_mark"] = True
        if self.topic_id is not None:
            result["unread_topic_id"] = self.topic_id
        if self.topics:
            result["unread_topics"] = self.topics
        return result


async def _dialog_state(client: Any, entity: Any) -> UnreadState:
    from telethon.tl.functions.messages import GetPeerDialogsRequest
    from telethon.tl.types import InputDialogPeer

    peer = await client.get_input_entity(entity)
    result = await client(GetPeerDialogsRequest(peers=[InputDialogPeer(peer=peer)]))
    dialogs = getattr(result, "dialogs", None) or []
    if not dialogs:
        raise UnreadError(
            "--unread needs a chat from your dialog list; "
            "this chat is not in it (join it first)"
        )
    dialog = dialogs[0]
    return UnreadState(
        unread_count=int(getattr(dialog, "unread_count", 0) or 0),
        read_inbox_max_id=int(getattr(dialog, "read_inbox_max_id", 0) or 0),
        unread_mark=bool(getattr(dialog, "unread_mark", False)),
    )


async def _topic_state(
    client: Any, entity: Any, topic_id: int
) -> Optional[UnreadState]:
    from telethon.tl.functions.messages import GetForumTopicsByIDRequest

    result = await client(GetForumTopicsByIDRequest(peer=entity, topics=[topic_id]))
    for topic in getattr(result, "topics", None) or []:
        # ForumTopicDeleted has no read state; fall back to the dialog.
        if getattr(topic, "id", None) == topic_id and hasattr(
            topic, "read_inbox_max_id"
        ):
            return UnreadState(
                unread_count=int(getattr(topic, "unread_count", 0) or 0),
                read_inbox_max_id=int(topic.read_inbox_max_id or 0),
                topic_id=topic_id,
            )
    return None


async def _forum_state(client: Any, entity: Any) -> UnreadState:
    from telethon.tl.functions.messages import GetForumTopicsRequest

    cursors: Dict[int, int] = {}
    details: List[Dict[str, Any]] = []
    offset_topic = offset_id = 0
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
        page = getattr(result, "topics", None) or []
        for topic in page:
            unread = int(getattr(topic, "unread_count", 0) or 0)
            tid = getattr(topic, "id", None)
            if tid is None or unread <= 0:
                continue
            cursor = int(getattr(topic, "read_inbox_max_id", 0) or 0)
            cursors[int(tid)] = cursor
            details.append(
                {
                    "id": int(tid),
                    "title": getattr(topic, "title", None),
                    "unread_count": unread,
                    "read_inbox_max_id": cursor,
                }
            )
        if len(page) < page_limit:
            break
        last = page[-1]
        if getattr(last, "id", None) in (None, offset_topic):
            break
        offset_topic = int(last.id)
        offset_id = int(getattr(last, "top_message", 0) or 0)
        offset_date = getattr(last, "date", None)

    return UnreadState(
        unread_count=sum(t["unread_count"] for t in details),
        read_inbox_max_id=min(cursors.values()) if cursors else 0,
        topic_cursors=cursors,
        topics=details,
    )


async def fetch_unread_state(
    client: Any, entity: Any, topic_id: Optional[int] = None
) -> UnreadState:
    """Return the unread state of ``entity`` for the session's account.

    ``topic_id`` (from ``--subchat``) picks a forum topic's own read state; a
    reply thread outside a forum has none, so it uses the dialog's; inside a
    forum it uses the per-topic state, since a forum's dialog counters lag its
    topics' (live: 7 unread in the dialog, 0 in every topic).
    """
    if getattr(entity, "left", False):
        # Telegram still answers with a dialog full of zeros, which would read
        # as "nothing unread" instead of "not a member".
        raise UnreadError("--unread needs a chat you are a member of; join it first")
    if getattr(entity, "forum", False):
        if topic_id is not None:
            state = await _topic_state(client, entity, topic_id)
            if state is not None:
                return state
        return await _forum_state(client, entity)
    return await _dialog_state(client, entity)


def _get(msg: Any, key: str) -> Any:
    if isinstance(msg, dict):
        return msg.get(key)
    return getattr(msg, key, None)


def _topic_of(msg: Any) -> int:
    """The forum topic a message is read in.

    A reply inside General carries ``forum_topic=False`` and a
    ``reply_to_top_id`` naming the root of its reply thread, not a topic, so
    only a header marked ``forum_topic`` points at a topic (live: 61 of a
    forum's 138 unread General messages were such replies).
    """
    reply_to = _get(msg, "reply_to")
    if reply_to is not None and not isinstance(reply_to, dict):
        reply_to = reply_to.to_dict() if hasattr(reply_to, "to_dict") else None
    if isinstance(reply_to, dict) and reply_to.get("forum_topic") is False:
        return GENERAL_TOPIC_ID
    return _extract_topic_id(msg) or GENERAL_TOPIC_ID


def is_after_cursor(msg: Any, state: UnreadState) -> bool:
    """Whether ``msg`` is newer than the read cursor that applies to it."""
    msg_id = _get(msg, "id")
    if not isinstance(msg_id, int):
        return False
    if state.topic_cursors:
        topic = _topic_of(msg)
        cursor = state.topic_cursors.get(topic)
        return cursor is not None and msg_id > cursor
    return msg_id > state.read_inbox_max_id


def filter_unread(messages: List[Any], state: UnreadState) -> List[Any]:
    """Keep the messages after the read cursor (incoming and outgoing)."""
    return [m for m in messages if is_after_cursor(m, state)]


def count_unread_incoming(messages: List[Any], state: UnreadState) -> int:
    """Count the downloaded messages that make up ``unread_count``.

    Outgoing messages are kept as context but are never unread, and backfilled
    citations / channel comments are not part of the chat's unread range.
    """
    return sum(
        1
        for m in messages
        if not _get(m, "out")
        and not _get(m, "cited_outside_window")
        and _get(m, "comment_of") is None
        and is_after_cursor(m, state)
    )


__all__ = [
    "UnreadError",
    "UnreadState",
    "count_unread_incoming",
    "fetch_unread_state",
    "filter_unread",
    "is_after_cursor",
]

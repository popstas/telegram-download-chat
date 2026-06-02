"""Normalize Telegram message reactions into a stable, serializable shape.

Telethon exposes reactions on ``message.reactions`` as a ``MessageReactions``
object whose ``to_dict()`` is verbose and version-dependent: ``results`` is a
list of ``ReactionCount``, each with a ``reaction`` that is either a
``ReactionEmoji`` (standard ``.emoticon``) or a ``ReactionCustomEmoji``
(``.document_id``) plus a ``count``; an optional ``recent_reactions`` carries
who reacted.

To keep the saved JSON small and stable across Telethon versions, each message
stores a normalized ``reactions`` list of::

    {"emoji": "👍", "count": 5, "chosen": true, "recent": [123, 456]}
    {"custom_emoji_id": 123456789, "count": 2}

``chosen`` is present only when the current account reacted with it; ``recent``
(when available) lists the peer ids of recent reactors for that reaction.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = ["normalize_reactions", "reaction_key"]


def reaction_key(item: Dict[str, Any]) -> Any:
    """Return a hashable key identifying a normalized reaction entry."""
    if "emoji" in item:
        return ("emoji", item["emoji"])
    if "custom_emoji_id" in item:
        return ("custom", item["custom_emoji_id"])
    return ("?", None)


def _peer_id(peer: Any) -> Optional[int]:
    """Extract a numeric peer id from a Telethon Peer dict, or ``None``."""
    if isinstance(peer, dict):
        for field in ("user_id", "channel_id", "chat_id"):
            val = peer.get(field)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    return None
    if isinstance(peer, int):
        return peer
    return None


def _reaction_identity(reaction: Any) -> Optional[Dict[str, Any]]:
    """Map a Telethon reaction dict to ``{"emoji": ...}`` / ``{"custom_emoji_id": ...}``."""
    if not isinstance(reaction, dict):
        return None
    rtype = reaction.get("_")
    if rtype == "ReactionEmoji":
        emoticon = reaction.get("emoticon")
        if emoticon:
            return {"emoji": emoticon}
        return None
    if rtype == "ReactionCustomEmoji":
        doc_id = reaction.get("document_id")
        if doc_id is None:
            return None
        try:
            return {"custom_emoji_id": int(doc_id)}
        except (TypeError, ValueError):
            return None
    # Some reaction dicts (or already-normalized entries) carry the fields
    # directly without a ``_`` discriminator.
    if reaction.get("emoji"):
        return {"emoji": reaction["emoji"]}
    if reaction.get("custom_emoji_id") is not None:
        try:
            return {"custom_emoji_id": int(reaction["custom_emoji_id"])}
        except (TypeError, ValueError):
            return None
    return None


def normalize_reactions(reactions: Any) -> Optional[List[Dict[str, Any]]]:
    """Convert ``message.reactions`` into the normalized list shape.

    Accepts either a raw Telethon ``MessageReactions`` dict (from ``to_dict()``)
    or an already-normalized list (so re-saving a resumed export is idempotent).
    Returns ``None`` when there are no reactions to store.
    """
    if reactions is None:
        return None

    # Already normalized (e.g. loaded back from a prior save / resume).
    if isinstance(reactions, list):
        cleaned = [
            r
            for r in reactions
            if isinstance(r, dict) and reaction_key(r)[1] is not None
        ]
        return cleaned or None

    if not isinstance(reactions, dict):
        return None

    results = reactions.get("results")
    if not isinstance(results, list):
        return None

    # Pre-group recent reactors by their reaction identity so each normalized
    # entry can carry the peer ids of who reacted.
    recent_by_key: Dict[Any, List[int]] = {}
    recent = reactions.get("recent_reactions")
    if isinstance(recent, list):
        for rec in recent:
            if not isinstance(rec, dict):
                continue
            identity = _reaction_identity(rec.get("reaction"))
            if identity is None:
                continue
            pid = _peer_id(rec.get("peer_id"))
            if pid is None:
                continue
            recent_by_key.setdefault(reaction_key(identity), []).append(pid)

    out: List[Dict[str, Any]] = []
    for rc in results:
        if not isinstance(rc, dict):
            continue
        identity = _reaction_identity(rc.get("reaction"))
        if identity is None:
            continue
        count = rc.get("count")
        if isinstance(count, (int, float)):
            identity["count"] = int(count)
        else:
            identity["count"] = 0
        if rc.get("chosen_order") is not None or rc.get("chosen"):
            identity["chosen"] = True
        peers = recent_by_key.get(reaction_key(identity))
        if peers:
            identity["recent"] = peers
        out.append(identity)

    return out or None

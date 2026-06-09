#!/usr/bin/env python3
"""One-off spike (Task B1 of the comment-media-html-link-resume plan).

NOT part of the test suite. Manually run against a live, authenticated session
to confirm the Part B mapping assumption before coding the single-pass
discussion download:

    - a channel post is auto-forwarded into the linked discussion group as a
      *thread root* carrying ``fwd_from.channel_post`` = the original post id;
    - a comment replies within that thread, pointing at the root via
      ``reply_to.reply_to_top_id`` (nested replies) or
      ``reply_to.reply_to_msg_id`` (direct replies to the post).

The script fetches ~50 messages from the linked discussion group, prints the
mapping-relevant fields, reconstructs ``root_to_post`` from forwarded roots, and
maps each reply to a channel post via ``reply_to_top_id or reply_to_msg_id``.
Compare the printed ``comment 9240 -> post 5477`` / ``9131 -> 5445`` lines with
what the per-post path produced; if they differ, update the plan's mapping
design (the ⚠️ step) before writing Task B2/B3.

Usage::

    .venv/bin/python scripts/spike_discussion_mapping.py ecceverbum
    # or pass the linked discussion id directly:
    .venv/bin/python scripts/spike_discussion_mapping.py --discussion-id 1619992925
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any, Dict, Optional

from telegram_download_chat.core import TelegramChatDownloader
from telegram_download_chat.core.comments import get_linked_discussion


def _peer_channel_post(msg: Any) -> Optional[int]:
    fwd = getattr(msg, "fwd_from", None)
    if fwd is None:
        return None
    return getattr(fwd, "channel_post", None)


def _reply_fields(msg: Any):
    reply_to = getattr(msg, "reply_to", None)
    if reply_to is None:
        return None, None
    return (
        getattr(reply_to, "reply_to_msg_id", None),
        getattr(reply_to, "reply_to_top_id", None),
    )


async def main(chat: Optional[str], discussion_id: Optional[int], limit: int) -> None:
    downloader = TelegramChatDownloader()
    await downloader.connect(cli=True)

    if discussion_id is None:
        if not chat:
            raise SystemExit("Pass a channel username or --discussion-id")
        entity = await downloader.get_entity(chat)
        discussion_id = await get_linked_discussion(downloader, entity)
        if discussion_id is None:
            raise SystemExit(f"{chat!r} has no linked discussion group")
        print(f"Linked discussion id for {chat!r}: {discussion_id}")

    disc_entity = await downloader.get_entity(str(discussion_id))

    root_to_post: Dict[int, int] = {}
    replies = []
    print(f"\nFetching up to {limit} messages from discussion {discussion_id}...\n")
    async for msg in downloader.client.iter_messages(disc_entity, limit=limit):
        channel_post = _peer_channel_post(msg)
        reply_msg_id, reply_top_id = _reply_fields(msg)
        if channel_post is not None:
            root_to_post[msg.id] = channel_post
            print(f"ROOT     disc_id={msg.id:<10} fwd_from.channel_post={channel_post}")
        elif reply_msg_id is not None or reply_top_id is not None:
            replies.append(msg)
            print(
                f"REPLY    disc_id={msg.id:<10} "
                f"reply_to_msg_id={reply_msg_id} reply_to_top_id={reply_top_id}"
            )
        else:
            print(f"OTHER    disc_id={msg.id:<10} (service/no-reply, skipped)")

    print("\n--- Reconstructed mapping (reply_to_top_id or reply_to_msg_id) ---")
    for msg in replies:
        reply_msg_id, reply_top_id = _reply_fields(msg)
        root = reply_top_id or reply_msg_id
        post = root_to_post.get(root)
        status = f"post {post}" if post is not None else "UNMAPPED (root out of window)"
        print(f"comment {msg.id} -> root {root} -> {status}")

    await downloader.client.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "chat", nargs="?", help="Channel username (resolves linked group)"
    )
    parser.add_argument(
        "--discussion-id",
        type=int,
        default=None,
        help="Linked discussion group id (skip channel resolution)",
    )
    parser.add_argument("--limit", type=int, default=50, help="Messages to fetch")
    args = parser.parse_args()
    asyncio.run(main(args.chat, args.discussion_id, args.limit))

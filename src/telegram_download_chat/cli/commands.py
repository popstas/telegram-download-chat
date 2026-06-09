"""Implementation of CLI commands."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from telethon.tl.types import Channel, Chat, User

from telegram_download_chat.core import TelegramChatDownloader
from telegram_download_chat.core.citations import fetch_cited_messages
from telegram_download_chat.core.comments import (
    clear_comments_checkpoint,
    download_post_comments,
    get_comments_checkpoint_path,
    get_linked_discussion,
    load_comments_checkpoint,
    save_comments_checkpoint,
)
from telegram_download_chat.core.topics import (
    GENERAL_KEY,
    fetch_forum_topics,
    group_messages_by_topic,
    slugify_topic,
)
from telegram_download_chat.paths import get_relative_to_downloads_dir

from .arguments import CLIOptions


def _dedup_messages(messages: List[Any]) -> List[Any]:
    """Deduplicate messages by id, preserving original order.

    Comments fetched from a channel's linked discussion group keep their native
    discussion id, which lives in a separate id space from channel post ids and
    can collide with them. Such records carry a ``comment_of`` marker and are
    keyed by ``(comment_of, id)`` so a comment is never collapsed into a same-id
    post and re-fetched comments still dedupe against each other on resume.

    For non-comment ids, an unmarked real post always wins over an
    outside-window citation backfill (``cited_outside_window``) of the same id:
    when a later history walk downloads a post that an earlier run only had as a
    citation, the real record replaces the marker in place (rather than being
    shadowed by the first copy). Otherwise the stale marker would persist,
    permanently excluding that id from the ``--limit`` resume counter and making
    a widened run think one more real post is always missing.

    For comment records, a freshly-fetched copy carrying ``attachment_path``
    replaces a same-key copy that lacks one (e.g. a stale ``messages.json``
    comment saved before its media was downloaded). This mirrors the
    citation-replace precedent so resume runs finally surface the comment's
    media link in the HTML/JSON output. It never demotes: a kept comment that
    already has a path is left in place, and two comments that both have (or
    both lack) a path keep the first.
    """

    def _is_citation(m: Any) -> bool:
        return bool(
            m.get("cited_outside_window")
            if isinstance(m, dict)
            else getattr(m, "cited_outside_window", False)
        )

    def _has_attachment(m: Any) -> bool:
        return bool(
            m.get("attachment_path")
            if isinstance(m, dict)
            else getattr(m, "attachment_path", None)
        )

    seen: Dict[Any, int] = {}
    deduped: List[Any] = []
    for m in messages:
        if isinstance(m, dict):
            mid = m.get("id")
            comment_of = m.get("comment_of")
        else:
            mid = getattr(m, "id", None)
            comment_of = getattr(m, "comment_of", None)
        if mid is None:
            deduped.append(m)
            continue
        key = (comment_of, mid) if comment_of is not None else mid
        if key not in seen:
            seen[key] = len(deduped)
            deduped.append(m)
        elif _is_citation(deduped[seen[key]]) and not _is_citation(m):
            # Replace a previously kept citation marker with the real post.
            deduped[seen[key]] = m
        elif (
            comment_of is not None
            and not _has_attachment(deduped[seen[key]])
            and _has_attachment(m)
        ):
            # Resume: a re-fetched comment carrying attachment_path replaces a
            # stale same-key comment that lacks one, so its media link appears.
            deduped[seen[key]] = m
    return deduped


def _parse_date(value: Any) -> datetime | None:
    """Parse date from various formats to datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def split_messages_by_date(messages: List[Any], split_by: str) -> Dict[str, List[Any]]:
    """Split messages by month or year based on message date.

    Channel comments are bucketed by their parent post's date (not their own),
    so a comment stays in the same file as the post it replies to and renders
    nested under it even when the comment was written in a later month/year.
    """

    def _comment_of(msg: Any) -> Any:
        return (
            msg.get("comment_of")
            if isinstance(msg, dict)
            else getattr(msg, "comment_of", None)
        )

    def _raw_date(msg: Any) -> Any:
        return msg.get("date") if isinstance(msg, dict) else getattr(msg, "date", None)

    def _msg_id(msg: Any) -> Any:
        return msg.get("id") if isinstance(msg, dict) else getattr(msg, "id", None)

    # Map each real channel post id -> its raw date so comments can inherit it.
    post_dates: Dict[Any, Any] = {}
    for msg in messages:
        if _comment_of(msg) is not None:
            continue
        mid = _msg_id(msg)
        if mid is not None:
            post_dates[mid] = _raw_date(msg)

    split_messages: Dict[str, List[Dict[str, Any]]] = {}
    for msg in messages:
        raw_date = _raw_date(msg)
        comment_of = _comment_of(msg)
        if comment_of is not None and comment_of in post_dates:
            raw_date = post_dates[comment_of]
        parsed_date = _parse_date(raw_date)
        if not parsed_date:
            continue

        try:
            # Convert to local timezone for consistent bucketing with render display
            local_date = parsed_date.astimezone()
            key = local_date.strftime("%Y-%m" if split_by == "month" else "%Y")
        except (ValueError, AttributeError):
            continue

        split_messages.setdefault(key, []).append(msg)
    return split_messages


def filter_messages_by_subchat(
    messages: List[Dict[str, Any]], subchat_id: str
) -> List[Dict[str, Any]]:
    """Filter messages by reply_to_msg_id or reply_to_top_id."""
    if subchat_id.startswith("https://t.me/c/"):
        parts = subchat_id.strip("/").split("/")
        if len(parts) >= 3:
            try:
                target_id = int(parts[-1])
            except ValueError as exc:
                raise ValueError(f"Invalid message ID in URL: {subchat_id}") from exc
        else:
            raise ValueError(f"Invalid Telegram chat URL format: {subchat_id}")
    else:
        try:
            target_id = int(subchat_id)
        except ValueError as exc:
            raise ValueError(f"Invalid message ID format: {subchat_id}") from exc

    filtered = []
    for msg in messages:
        reply_to = msg.get("reply_to")
        if not reply_to:
            continue
        if str(reply_to.get("reply_to_msg_id")) == str(target_id) or str(
            reply_to.get("reply_to_top_id")
        ) == str(target_id):
            filtered.append(msg)
    return filtered


def _message_text(msg: Any) -> str:
    """Extract plain text from a message (dict or Telethon object)."""
    if isinstance(msg, dict):
        text = msg.get("message") or msg.get("text") or ""
    else:
        d = msg.to_dict() if hasattr(msg, "to_dict") else {}
        text = d.get("message") or d.get("text") or ""
    if isinstance(text, list):
        text = "".join(
            part if isinstance(part, str) else part.get("text", "") for part in text
        )
    return str(text)


def filter_messages_by_keywords(messages: List[Any], keywords: List[str]) -> List[Any]:
    """Keep only messages whose text contains at least one keyword (case-insensitive)."""
    if not keywords:
        return messages
    kw_lower = [k.strip().lower() for k in keywords if k.strip()]
    if not kw_lower:
        return messages
    filtered = []
    for msg in messages:
        text = _message_text(msg).lower()
        if any(kw in text for kw in kw_lower):
            filtered.append(msg)
    return filtered


def analyze_keywords(
    keywords: List[str], messages: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Analyze messages for occurrences of keywords."""
    results: List[Dict[str, Any]] = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        kw_lower = kw.lower()
        matches = []
        count = 0
        for msg in messages:
            text_str = _message_text(msg)
            if kw_lower in text_str.lower():
                count += 1
                sender = msg.get("from_id") or msg.get("sender_id") or {}
                if isinstance(sender, dict):
                    sender = (
                        sender.get("user_id")
                        or sender.get("channel_id")
                        or sender.get("chat_id")
                    )
                username = f"@{sender}" if sender else None
                peer = msg.get("peer_id") or msg.get("to_id") or {}
                if isinstance(peer, dict):
                    chat_id = (
                        peer.get("channel_id")
                        or peer.get("chat_id")
                        or peer.get("user_id")
                    )
                else:
                    chat_id = peer
                msg_id = msg.get("id")
                url = (
                    f"https://t.me/c/{chat_id}/{msg_id}" if chat_id and msg_id else None
                )
                matches.append({"username": username, "text": text_str, "url": url})
        results.append({"text": kw, "count": count, "messages": matches})
    return results


async def _run_with_status(
    task_coro: Any, logger: logging.Logger, message: str | None = None
):
    """Run a coroutine and show a status message if it takes more than 2 seconds."""
    task = asyncio.create_task(task_coro)
    try:
        done, pending = await asyncio.wait(
            [task], timeout=2.0, return_when=asyncio.FIRST_COMPLETED
        )
        if pending and not message:
            message = "Saving messages..."
            logger.info(message)
    except asyncio.CancelledError:
        task.cancel()
        raise
    return await task


async def save_messages_with_status(
    downloader: TelegramChatDownloader,
    messages: List[Any],
    output_file: str,
    sort_order: str = "asc",
    download_media: bool = False,
    export_html: bool = False,
    export_pdf: bool = False,
    chat_title: Optional[str] = None,
    media_placeholders: bool = False,
    html_media_links: bool = False,
    reactions: bool = False,
) -> None:
    """Save messages to JSON displaying a status message if slow."""
    return await _run_with_status(
        downloader.save_messages(
            messages,
            output_file,
            sort_order=sort_order,
            download_media=download_media,
            export_html=export_html,
            export_pdf=export_pdf,
            chat_title=chat_title,
            media_placeholders=media_placeholders,
            html_media_links=html_media_links,
            reactions=reactions,
        ),
        downloader.logger,
    )


async def save_txt_with_status(
    downloader: TelegramChatDownloader,
    messages: List[Any],
    txt_file: Path,
    sort_order: str = "asc",
    media_placeholders: bool = False,
    reactions: bool = False,
) -> int:
    """Save messages to a text file with progress output."""
    return await _run_with_status(
        downloader.save_messages_as_txt(
            messages,
            txt_file,
            sort_order,
            media_placeholders=media_placeholders,
            reactions=reactions,
        ),
        downloader.logger,
    )


async def fetch_channel_comments(
    downloader: TelegramChatDownloader,
    chat_identifier: Any,
    messages: List[Any],
    args: CLIOptions,
    attachments_dir: Optional[Path] = None,
    checkpoint_path: Optional[Path] = None,
) -> List[Any]:
    """Fetch comments for downloaded channel posts when ``--comments`` is set.

    Returns a flat list of normalized comment dicts to append to ``messages``.
    Returns an empty list (with an info log) when the entity is not a broadcast
    channel or the channel has no linked discussion group.

    When ``--media`` is active, ``attachments_dir`` points at the chat's
    ``attachments/`` directory so comment attachments are downloaded there and
    each comment dict gets an ``attachment_path`` for JSON/HTML output.

    When ``checkpoint_path`` is set, posts whose comments were already fetched in
    a prior interrupted run (recorded in that sidecar file) are skipped. Scanned
    posts are tracked in memory and stashed on ``downloader`` as
    ``_comments_checkpoint_state``; the actual on-disk write/clear is deferred to
    ``_persist_comments_checkpoint`` after the comments are durably saved, so the
    checkpoint can never get ahead of the saved output (a stop keeps the scanned
    set; a clean finish clears it so a later incremental run re-scans for new
    comments — mirroring the partial-download file lifecycle).
    """
    if not getattr(args, "comments", False):
        return []

    entity = await downloader.get_entity(chat_identifier)
    if not getattr(entity, "broadcast", False):
        downloader.logger.info(
            "--comments only applies to broadcast channels; skipping comments"
        )
        return []

    linked = await get_linked_discussion(downloader, entity)
    if not linked:
        downloader.logger.info(
            "Channel has no linked discussion group; skipping comments"
        )
        return []

    # Only real, in-window channel posts get comments. Skip comment records
    # (``comment_of``) so we don't fetch "comments of comments", and skip
    # outside-window citation backfills (``cited_outside_window``): those are
    # fetched by id to populate a quote, not walked as part of the download, so
    # fetching their comment threads would push comment coverage past the posts
    # actually downloaded — matching the post-based resume cursor/count.
    post_ids = [
        m.get("id") if isinstance(m, dict) else getattr(m, "id", None)
        for m in messages
        if not (
            isinstance(m, dict)
            and (m.get("comment_of") is not None or m.get("cited_outside_window"))
        )
    ]
    post_ids = [pid for pid in post_ids if pid is not None]
    if not post_ids:
        return []

    # Skip posts already scanned in a prior interrupted run.
    done_posts: set = (
        load_comments_checkpoint(checkpoint_path) if checkpoint_path else set()
    )
    on_post_done = None
    if done_posts:
        skipped = len(done_posts & set(post_ids))
        if skipped:
            downloader.logger.info(
                f"Resuming comments: skipping {skipped} post(s) already fetched"
            )
        post_ids = [pid for pid in post_ids if pid not in done_posts]

    if checkpoint_path is not None:
        # Accumulate scanned posts in memory only. The checkpoint is written to
        # disk by the caller *after* the comments are durably saved (see
        # ``_persist_comments_checkpoint``). Writing it here — before the
        # comments/media are persisted at the end of the run — would let the
        # checkpoint get ahead of the saved output: a hard kill in between would
        # then make a resume skip posts whose comments/media were never written,
        # losing them permanently. Deferring the write keeps the checkpoint and
        # the saved output in lockstep.
        def on_post_done(post_id: int) -> None:  # noqa: F811 - conditional def
            done_posts.add(post_id)

        downloader._comments_checkpoint_state = {
            "path": checkpoint_path,
            "done": done_posts,
        }

    if not post_ids:
        # Everything was already fetched; nothing new to fetch or save. The
        # caller clears the checkpoint after re-saving the existing output.
        return []

    downloader.logger.info(f"Fetching comments for {len(post_ids)} post(s)...")
    comments = await download_post_comments(
        downloader,
        entity,
        post_ids,
        limit=args.comments_limit,
        min_reactions=getattr(args, "comments_min_reactions", 0) or 0,
        download_media=bool(getattr(args, "media", False)),
        attachments_dir=attachments_dir,
        on_post_done=on_post_done,
    )
    downloader.logger.info(f"Fetched {len(comments)} comment(s)")

    return comments


def _persist_comments_checkpoint(downloader: TelegramChatDownloader) -> None:
    """Persist or clear the comments-resume checkpoint after a durable save.

    Invoked only once the chat's ``messages.json`` has been written, so the
    checkpoint can never get ahead of the saved comments. An interrupted run
    keeps the scanned-post set (so the next run skips those posts); a clean
    finish clears it (so a later incremental run re-scans every post for newly
    added comments). A no-op when no comment fetch ran this chat.
    """
    state = getattr(downloader, "_comments_checkpoint_state", None)
    if not state:
        return
    path = state.get("path")
    if path is not None:
        if getattr(downloader, "_stop_requested", False):
            save_comments_checkpoint(path, state.get("done", set()))
        else:
            clear_comments_checkpoint(path)
    downloader._comments_checkpoint_state = None


async def fetch_outside_window_citations(
    downloader: TelegramChatDownloader,
    chat_identifier: Any,
    messages: List[Any],
) -> List[Any]:
    """Fetch messages cited by replies that fall outside the date window.

    Returns a flat list of fetched message objects to merge into ``messages`` so
    that citations are populated in JSON/TXT/HTML. Returns an empty list when no
    referenced message is missing (e.g. a full, unwindowed download).
    """
    entity = await downloader.get_entity(chat_identifier)
    return await fetch_cited_messages(downloader, entity, messages)


async def process_chat_download(
    downloader: TelegramChatDownloader,
    chat_identifier: Any,
    args: CLIOptions,
    output_dir: Path,
) -> Dict[str, Any]:
    """Download a single chat and save messages with options."""
    safe_chat_name = await downloader.get_entity_name(chat_identifier)
    if not safe_chat_name:
        downloader.logger.error(
            f"Failed to get entity name for chat: {chat_identifier}"
        )
        return {"chat_id": chat_identifier, "error": "failed to resolve chat"}

    if args.output:
        output_path_user = Path(args.output).resolve()
        output_file = str(
            output_path_user.with_suffix(".json")
            if not output_path_user.suffix
            else output_path_user
        )
    else:
        chat_dir = output_dir / safe_chat_name
        stem = f"messages_subchat_{args.subchat}" if args.subchat else "messages"
        output_file = str(chat_dir / f"{stem}.json")
        # Ensure the chat directory exists early so partial files can be written
        chat_dir.mkdir(parents=True, exist_ok=True)

    since_id = args.since_id
    existing_messages: List[Any] = []
    output_path = Path(output_file)
    if not args.overwrite and since_id is None and output_path.exists():
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    existing_messages = data
                    # Exclude comment records: their ids come from the linked
                    # discussion group, a different id space, and would poison
                    # the post-based resume cursor. Also exclude outside-window
                    # citation backfills, which are fetched by id rather than
                    # walked, so they must not move the cursor either.
                    ids = [
                        m.get("id")
                        for m in data
                        if isinstance(m, dict)
                        and "id" in m
                        and "comment_of" not in m
                        and not m.get("cited_outside_window")
                    ]
                    if ids:
                        since_id = max(ids)
                        downloader.logger.info(
                            f"Resuming: found {len(existing_messages)} existing messages "
                            f"(newest ID {since_id})"
                        )
        except Exception as e:  # pragma: no cover - just logging
            downloader.logger.warning(f"Failed to read existing file: {e}")

    if args.overwrite:
        downloader.logger.info("Overwrite mode: starting fresh download")
    elif since_id is None and not existing_messages:
        downloader.logger.info("Starting new download")

    if args.overwrite:
        part_path = downloader.get_temp_file_path(output_path)
        if part_path.exists():
            part_path.unlink()
        # Fresh start: drop any stale comments-resume checkpoint too.
        clear_comments_checkpoint(get_comments_checkpoint_path(output_path))

    download_kwargs = {
        "chat_id": chat_identifier,
        "request_limit": args.limit if args.limit > 0 else 100,
        "total_limit": args.limit if args.limit > 0 else 0,
        "output_file": output_file,
        "silent": False,
        "save_partial": not args.overwrite,
    }
    # --last-days takes priority over --min-date; N days = base_date + (N-1) preceding days (inclusive)
    if args.last_days is not None:
        base_str = args.from_date or datetime.utcnow().strftime("%Y-%m-%d")
        base_date = datetime.strptime(base_str, "%Y-%m-%d")
        download_kwargs["until_date"] = (
            base_date - timedelta(days=max(0, args.last_days - 1))
        ).strftime("%Y-%m-%d")
    elif args.until:
        download_kwargs["until_date"] = args.until
    if args.from_date:
        download_kwargs["from_date"] = args.from_date
    # Backfill against a finite --limit counts real channel posts only: saved
    # comments live in a separate id space, and outside-window citation
    # backfills are fetched by id (not walked), so neither must make the limit
    # look already satisfied (matching the post-only resume cursor above).
    existing_post_count = sum(
        1
        for m in existing_messages
        if not (
            isinstance(m, dict)
            and (m.get("comment_of") is not None or m.get("cited_outside_window"))
        )
    )
    if since_id is not None:
        # If total_limit is set and we haven't reached it yet, skip since_id
        # so the download continues backwards from the oldest existing message
        if args.limit > 0 and existing_post_count < args.limit:
            downloader.logger.info(
                f"Need {args.limit - existing_post_count} more message(s), "
                f"continuing backwards"
            )
        else:
            download_kwargs["since_id"] = since_id

    messages = await downloader.download_chat(**download_kwargs)
    downloader.logger.debug(f"Downloaded {len(messages)} messages")

    if existing_messages:
        messages = _dedup_messages(existing_messages + messages)

    # Reset any checkpoint intent left over from a previous chat (folder mode
    # reuses the downloader); fetch_channel_comments sets it when it runs.
    downloader._comments_checkpoint_state = None
    if args.comments and messages:
        # Under --media, download comment attachments into the same chat-level
        # attachments/ dir the post media uses (split-by-date files share one
        # parent dir, so this matches save_messages' attachments_dir too).
        comments_attachments_dir = (
            downloader.get_attachments_dir(Path(output_file)) if args.media else None
        )
        comments = await fetch_channel_comments(
            downloader,
            chat_identifier,
            messages,
            args,
            attachments_dir=comments_attachments_dir,
            checkpoint_path=get_comments_checkpoint_path(Path(output_file)),
        )
        if comments:
            # Dedup so a resumed run doesn't accumulate comments already saved
            # in messages.json.
            messages = _dedup_messages(messages + comments)

    # Populate citations whose target falls outside the requested date window:
    # fetch any replied-to message ids that are referenced but not present.
    if messages:
        try:
            cited = await fetch_outside_window_citations(
                downloader, chat_identifier, messages
            )
        except Exception as exc:  # pragma: no cover - best-effort enrichment
            downloader.logger.warning(f"Failed to fetch cited messages: {exc}")
            cited = []
        if cited:
            # Mark backfilled citations so the --limit resume counter and the
            # post-based since_id cursor don't treat them as downloaded chat
            # posts. They are fetched by id (replies to in-window messages) and
            # would otherwise inflate ``existing_post_count`` past ``--limit`` on
            # a resumed run, stopping real backfill. Telethon's ``to_dict()``
            # drops unknown attributes, so the marker is also re-applied in
            # ``save_messages`` to survive serialization into messages.json.
            for c in cited:
                if isinstance(c, dict):
                    c["cited_outside_window"] = True
                else:
                    try:
                        c.cited_outside_window = True
                    except (AttributeError, TypeError):
                        pass
            messages = _dedup_messages(messages + cited)

    if args.subchat:
        messages = filter_messages_by_subchat(messages, args.subchat)
        downloader.logger.info(
            f"Filtered to {len(messages)} messages in subchat {args.subchat}"
        )

    if args.keywords:
        kw_list = [k.strip() for k in args.keywords.split(",") if k.strip()]
        if kw_list:
            messages = filter_messages_by_keywords(messages, kw_list)
            downloader.logger.info(
                f"Filtered to {len(messages)} messages matching keywords: {kw_list}"
            )

    msg_dates = [
        _parse_date(
            getattr(m, "date", None) if not isinstance(m, dict) else m.get("date")
        )
        for m in messages
    ]
    msg_dates = [d for d in msg_dates if d]
    first_date = min(msg_dates).strftime("%Y-%m-%d") if msg_dates else None
    last_date = max(msg_dates).strftime("%Y-%m-%d") if msg_dates else None

    keywords_data: List[Dict[str, Any]] = []
    if args.keywords:
        kw_list = [k.strip() for k in args.keywords.split(",") if k.strip()]
        serializable = [
            downloader.make_serializable(m.to_dict() if hasattr(m, "to_dict") else m)
            for m in messages
        ]
        keywords_data = analyze_keywords(kw_list, serializable)

    if not messages:
        downloader.logger.warning("No messages to save")
        entity = await downloader.get_entity(chat_identifier)
        chat_type = "unknown"
        if isinstance(entity, User):
            chat_type = "private"
        elif isinstance(entity, Chat):
            chat_type = "group"
        elif isinstance(entity, Channel):
            chat_type = (
                "channel" if getattr(entity, "broadcast", False) else "supergroup"
            )
        return {
            "chat_id": getattr(entity, "id", chat_identifier),
            "chat_title": await downloader.get_entity_full_name(chat_identifier),
            "chat_type": chat_type,
            "args": {"limit": args.limit} if args.limit else {},
            "messages": 0,
            "from": None,
            "to": None,
            "result_json": None,
            "result_txt": None,
            "keywords": [],
        }

    full_chat_title = await downloader.get_entity_full_name(chat_identifier)

    # For forum supergroups, fetch topic titles up front so the HTML/PDF export
    # can name topics (and build tabs) even when their topic-create messages
    # fall outside a windowed download. Best-effort: a failure must not block
    # the export. save_messages() reads downloader._forum_topic_titles.
    downloader._forum_topic_titles = {}
    try:
        forum_entity = await downloader.get_entity(chat_identifier)
        if getattr(forum_entity, "forum", False):
            downloader._forum_topic_titles = await fetch_forum_topics(
                downloader, forum_entity
            )
    except Exception as e:  # pragma: no cover - network/permission dependent
        downloader.logger.debug(f"Could not fetch forum topics: {e}")

    split_messages: Dict[str, List[Any]] = {}
    topic_dirs: Dict[str, Path] = {}
    try:
        if args.split == "topics":
            if args.subchat:
                raise ValueError("--split topics is incompatible with --subchat")

            entity = await downloader.get_entity(chat_identifier)
            topics_map = await fetch_forum_topics(downloader, entity)
            grouped = group_messages_by_topic(messages, topics_map)
            output_path = Path(output_file)
            ext = output_path.suffix or ".json"

            for key, (title, msgs) in grouped.items():
                slug = (
                    GENERAL_KEY
                    if key == GENERAL_KEY
                    else slugify_topic(title, int(key))
                )
                topic_dir = output_path.parent / slug
                topic_dirs[key] = topic_dir
                split_file = topic_dir / f"messages{ext}"
                await save_messages_with_status(
                    downloader,
                    msgs,
                    str(split_file),
                    args.sort,
                    args.media,
                    export_html=args.export_html,
                    export_pdf=args.export_pdf,
                    chat_title=f"{full_chat_title} / {title}",
                    media_placeholders=args.media_placeholders,
                    html_media_links=args.html_media_links,
                    reactions=args.reactions,
                )
                downloader.logger.info(f"Saved {len(msgs)} messages to {split_file}")
            downloader.logger.info(
                f"Saved {len(topic_dirs)} topic folders in {output_path.parent}"
            )
            # save_messages() cleans up only the per-topic partials; the
            # chat-level partial created during download is never paired
            # with a save_messages() call in topic mode, so clear it here.
            chat_partial = downloader.get_temp_file_path(output_path)
            if chat_partial.exists() and not getattr(
                downloader, "_stop_requested", False
            ):
                try:
                    chat_partial.unlink()
                except OSError:
                    pass
        elif args.split:
            split_messages = split_messages_by_date(messages, args.split)
            if not split_messages:
                downloader.logger.warning(
                    "No messages with valid dates found for splitting"
                )
                await save_messages_with_status(
                    downloader,
                    messages,
                    output_file,
                    args.sort,
                    args.media,
                    export_html=args.export_html,
                    export_pdf=args.export_pdf,
                    chat_title=full_chat_title,
                    media_placeholders=args.media_placeholders,
                    html_media_links=args.html_media_links,
                    reactions=args.reactions,
                )
            else:
                output_path = Path(output_file)
                base_name = output_path.stem
                ext = output_path.suffix
                for date_key, msgs in split_messages.items():
                    split_file = output_path.with_name(f"{base_name}_{date_key}{ext}")
                    await save_messages_with_status(
                        downloader,
                        msgs,
                        str(split_file),
                        args.sort,
                        args.media,
                        export_html=args.export_html,
                        export_pdf=args.export_pdf,
                        chat_title=full_chat_title,
                        media_placeholders=args.media_placeholders,
                        html_media_links=args.html_media_links,
                        reactions=args.reactions,
                    )
                    downloader.logger.info(
                        f"Saved {len(msgs)} messages to {split_file}"
                    )
                downloader.logger.info(
                    f"Saved {len(split_messages)} split files in {output_path.parent}"
                )
        else:
            await save_messages_with_status(
                downloader,
                messages,
                output_file,
                args.sort,
                args.media,
                export_html=args.export_html,
                export_pdf=args.export_pdf,
                chat_title=full_chat_title,
                media_placeholders=args.media_placeholders,
                html_media_links=args.html_media_links,
                reactions=args.reactions,
            )
    except Exception as e:
        downloader.logger.exception(f"Failed to save messages: {e}")
        return {"chat_id": chat_identifier, "error": str(e)}

    # The comments are now durably saved above, so it is safe to advance the
    # comments-resume checkpoint (or clear it on a clean finish).
    _persist_comments_checkpoint(downloader)

    entity = await downloader.get_entity(chat_identifier)
    chat_type = "unknown"
    if isinstance(entity, User):
        chat_type = "private"
    elif isinstance(entity, Chat):
        chat_type = "group"
    elif isinstance(entity, Channel):
        chat_type = "channel" if getattr(entity, "broadcast", False) else "supergroup"

    # In split mode, list the actual per-period (or per-topic) files
    # instead of the unsuffixed base.
    if topic_dirs:
        output_path = Path(output_file)
        ext = output_path.suffix or ".json"
        json_paths = [str(d / f"messages{ext}") for d in topic_dirs.values()]
        txt_paths = [str(d / "messages.txt") for d in topic_dirs.values()]
        result_json_value = json_paths
        result_txt_value = txt_paths
    elif args.split and split_messages:
        output_path = Path(output_file)
        base_name = output_path.stem
        ext = output_path.suffix
        json_paths = [
            str(output_path.with_name(f"{base_name}_{dk}{ext}"))
            for dk in split_messages
        ]
        txt_paths = [
            str(output_path.with_name(f"{base_name}_{dk}.txt")) for dk in split_messages
        ]
        result_json_value = json_paths
        result_txt_value = txt_paths
    else:
        result_json_value = output_file
        result_txt_value = str(Path(output_file).with_suffix(".txt"))

    result = {
        "chat_id": getattr(entity, "id", chat_identifier),
        "chat_title": full_chat_title,
        "chat_type": chat_type,
        "args": {"limit": args.limit} if args.limit else {},
        "messages": len(messages),
        "from": first_date,
        "to": last_date,
        "result_json": result_json_value,
        "result_txt": result_txt_value,
        "keywords": keywords_data,
    }
    if topic_dirs:
        result["result_topics"] = [str(d) for d in topic_dirs.values()]
    if args.media:
        if topic_dirs:
            result["result_attachments"] = [
                str(d / "attachments") for d in topic_dirs.values()
            ]
        else:
            attachments_dir = downloader.get_attachments_dir(Path(output_file))
            result["result_attachments"] = str(attachments_dir)
    if args.export_html:
        if topic_dirs:
            html_paths = [
                str(d / "messages.html")
                for d in topic_dirs.values()
                if (d / "messages.html").exists()
            ]
            if html_paths:
                result["result_html"] = html_paths
        elif args.split and split_messages:
            output_path = Path(output_file)
            base_name = output_path.stem
            html_paths = [
                str(output_path.with_name(f"{base_name}_{dk}.html"))
                for dk in split_messages
                if output_path.with_name(f"{base_name}_{dk}.html").exists()
            ]
            if html_paths:
                result["result_html"] = html_paths
        else:
            html_path = Path(output_file).with_suffix(".html")
            if html_path.exists():
                result["result_html"] = str(html_path)
    if args.export_pdf:
        if topic_dirs:
            pdf_paths = [
                str(d / "messages.pdf")
                for d in topic_dirs.values()
                if (d / "messages.pdf").exists()
            ]
            if pdf_paths:
                result["result_pdf"] = pdf_paths
        elif args.split and split_messages:
            output_path = Path(output_file)
            base_name = output_path.stem
            pdf_paths = [
                str(output_path.with_name(f"{base_name}_{dk}.pdf"))
                for dk in split_messages
                if output_path.with_name(f"{base_name}_{dk}.pdf").exists()
            ]
            if pdf_paths:
                result["result_pdf"] = pdf_paths
        else:
            pdf_path = Path(output_file).with_suffix(".pdf")
            if pdf_path.exists():
                result["result_pdf"] = str(pdf_path)
    return result


async def convert(
    downloader: TelegramChatDownloader, args: CLIOptions, downloads_dir: Path
) -> Dict[str, Any]:
    """Handle JSON to TXT conversion."""
    json_path = Path(args.chat)
    if not json_path.exists() and not json_path.is_absolute():
        json_path = downloads_dir / json_path
    if not json_path.exists():
        downloader.logger.error(f"File not found: {json_path}")
        return {"error": f"File not found: {json_path}"}

    downloader.logger.debug(f"Loading messages from JSON file: {json_path}")
    with open(json_path, "r", encoding="utf-8") as f:
        messages = json.load(f)

    if isinstance(messages, dict) and "about" in messages and "chats" in messages:
        messages = downloader.convert_archive_to_messages(
            messages, user_filter=args.user
        )

    txt_path = Path(json_path).with_suffix(".txt")
    if args.user:
        user_id = (
            args.user.replace("user", "") if args.user.startswith("user") else args.user
        )
        txt_path = txt_path.with_stem(f"{txt_path.stem}_user_{user_id}")

    if args.subchat:
        messages = filter_messages_by_subchat(messages, args.subchat)
        txt_path = (
            downloads_dir
            / f"{args.subchat_name or f'{txt_path.stem}_subchat_{args.subchat}'}{txt_path.suffix}"
        )
        downloader.logger.info(
            f"Filtered to {len(messages)} messages in subchat {args.subchat}"
        )

    msg_dates = [_parse_date(m.get("date")) for m in messages]
    msg_dates = [d for d in msg_dates if d]
    first_date = min(msg_dates).strftime("%Y-%m-%d") if msg_dates else None
    last_date = max(msg_dates).strftime("%Y-%m-%d") if msg_dates else None

    keywords_data: List[Dict[str, Any]] = []
    if args.keywords:
        kw_list = [k.strip() for k in args.keywords.split(",") if k.strip()]
        keywords_data = analyze_keywords(kw_list, messages)

    split_messages: Dict[str, List[Any]] = {}
    if args.split:
        split_messages = split_messages_by_date(messages, args.split)
        if not split_messages:
            downloader.logger.warning(
                "No messages with valid dates found for splitting"
            )
            saved = await save_txt_with_status(
                downloader,
                messages,
                txt_path,
                args.sort,
                media_placeholders=args.media_placeholders,
                reactions=args.reactions,
            )
            saved_relative = get_relative_to_downloads_dir(txt_path)
            downloader.logger.info(f"Saved {saved} messages to {saved_relative}")
        else:
            base_name = txt_path.stem
            ext = txt_path.suffix
            for date_key, msgs in split_messages.items():
                split_file = txt_path.with_name(f"{base_name}_{date_key}{ext}")
                saved = await save_txt_with_status(
                    downloader,
                    msgs,
                    split_file,
                    args.sort,
                    media_placeholders=args.media_placeholders,
                    reactions=args.reactions,
                )
                saved_relative = get_relative_to_downloads_dir(split_file)
                downloader.logger.info(f"Saved {saved} messages to {saved_relative}")
            downloader.logger.info(
                f"Saved {len(split_messages)} split files in {txt_path.parent}"
            )
    else:
        saved = await save_txt_with_status(
            downloader,
            messages,
            txt_path,
            args.sort,
            media_placeholders=args.media_placeholders,
            reactions=args.reactions,
        )
        saved_relative = get_relative_to_downloads_dir(txt_path)
        downloader.logger.info(f"Saved {saved} messages to {saved_relative}")

    # HTML / PDF export
    # Use parent directory name when JSON lives inside a chat folder (covers
    # messages.json, messages_2026-04.json, messages_subchat_123.json).
    # Fall back to the file stem for standalone JSON files.
    if json_path.stem == "messages" or json_path.stem.startswith("messages_"):
        chat_title = json_path.parent.name
    else:
        chat_title = json_path.stem
    # When running from inside the chat folder (e.g. `convert messages.json`),
    # parent.name is empty — fall back to the current working directory name.
    if not chat_title:
        chat_title = Path.cwd().name
    # Derive attachments_dir relative to the output HTML/PDF location,
    # not the input JSON, so media links work when --subchat redirects output.
    output_parent = txt_path.parent
    attachments_dir = output_parent / "attachments"
    if not attachments_dir.is_dir():
        # Fall back to JSON source directory if output dir has no attachments
        attachments_dir = json_path.parent / "attachments"
        if not attachments_dir.is_dir():
            attachments_dir = None
    html_ok = False
    pdf_ok = False

    # Build list of (messages, base_path) pairs for export.
    # When --split produced per-period TXT files, generate per-period HTML/PDF too.
    if args.split and split_messages:
        base_name = txt_path.stem
        export_pairs = [
            (msgs, txt_path.with_name(f"{base_name}_{date_key}.txt"))
            for date_key, msgs in split_messages.items()
        ]
    else:
        export_pairs = [(messages, txt_path)]

    for export_msgs, export_base in export_pairs:
        if args.export_html:
            html_path = export_base.with_suffix(".html")
            try:
                downloader.render_html(
                    export_msgs,
                    html_path,
                    attachments_dir,
                    chat_title,
                    media_links=args.html_media_links,
                )
                downloader.logger.info(
                    f"Saved HTML to {get_relative_to_downloads_dir(html_path)}"
                )
                html_ok = True
            except Exception as exc:
                downloader.logger.error(f"HTML export failed: {exc}")
        if args.export_pdf:
            pdf_path = export_base.with_suffix(".pdf")
            try:
                downloader.render_pdf(
                    export_msgs, pdf_path, attachments_dir, chat_title
                )
                downloader.logger.info(
                    f"Saved PDF to {get_relative_to_downloads_dir(pdf_path)}"
                )
                pdf_ok = True
            except Exception as exc:
                downloader.logger.error(f"PDF export failed: {exc}")

    downloader.logger.debug("Conversion completed successfully")
    # In split mode, list per-period TXT files instead of the unsuffixed base.
    if args.split and split_messages:
        base_name = txt_path.stem
        txt_paths = [
            str(txt_path.with_name(f"{base_name}_{dk}.txt")) for dk in split_messages
        ]
        result_txt_value = txt_paths
    else:
        result_txt_value = str(txt_path)

    result = {
        "chat_id": None,
        "chat_title": chat_title,
        "chat_type": "json",
        "args": {},
        "messages": len(messages),
        "from": first_date,
        "to": last_date,
        "result_json": str(json_path),
        "result_txt": result_txt_value,
        "keywords": keywords_data,
    }
    if html_ok:
        if args.split and split_messages:
            base_name = txt_path.stem
            html_paths = [
                str(txt_path.with_name(f"{base_name}_{dk}.html"))
                for dk in split_messages
                if txt_path.with_name(f"{base_name}_{dk}.html").exists()
            ]
            result["result_html"] = (
                html_paths if html_paths else str(txt_path.with_suffix(".html"))
            )
        else:
            result["result_html"] = str(txt_path.with_suffix(".html"))
    if pdf_ok:
        if args.split and split_messages:
            base_name = txt_path.stem
            pdf_paths = [
                str(txt_path.with_name(f"{base_name}_{dk}.pdf"))
                for dk in split_messages
                if txt_path.with_name(f"{base_name}_{dk}.pdf").exists()
            ]
            result["result_pdf"] = (
                pdf_paths if pdf_paths else str(txt_path.with_suffix(".pdf"))
            )
        else:
            result["result_pdf"] = str(txt_path.with_suffix(".pdf"))
    return result


async def folder(
    downloader: TelegramChatDownloader, args: CLIOptions, downloads_dir: Path
) -> List[Dict[str, Any]]:
    """Handle folder download mode."""
    folder_name = args.chat.split(":", 1)[1]
    folders = await downloader.list_folders()
    target = None
    for f in folders:
        title = getattr(f, "title", "")
        if hasattr(title, "text"):
            title = title.text
        if title == folder_name:
            target = f
            break
    if not target:
        downloader.logger.error(f"Folder not found: {folder_name}")
        return []

    folder_dir = downloads_dir / folder_name
    folder_dir.mkdir(parents=True, exist_ok=True)

    peers = []
    peers.extend(getattr(target, "pinned_peers", []) or [])
    peers.extend(getattr(target, "include_peers", []) or [])

    results = []
    for peer in peers:
        results.append(await process_chat_download(downloader, peer, args, folder_dir))

    return results


async def download(
    downloader: TelegramChatDownloader, args: CLIOptions, downloads_dir: Path
) -> Dict[str, Any]:
    """Handle normal chat download."""
    return await process_chat_download(downloader, args.chat, args, downloads_dir)


__all__ = [
    "_dedup_messages",
    "split_messages_by_date",
    "filter_messages_by_subchat",
    "analyze_keywords",
    "save_messages_with_status",
    "save_txt_with_status",
    "fetch_channel_comments",
    "fetch_outside_window_citations",
    "process_chat_download",
    "convert",
    "folder",
    "download",
]

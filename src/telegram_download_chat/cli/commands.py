"""Implementation of CLI commands."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from telethon.tl.types import Channel, Chat, User

from telegram_download_chat.core import TelegramChatDownloader
from telegram_download_chat.paths import get_relative_to_downloads_dir

from .arguments import CLIOptions


def _dedup_messages(messages: List[Any]) -> List[Any]:
    """Deduplicate messages by id, preserving original order."""
    seen: set = set()
    deduped = []
    for m in messages:
        mid = m.get("id") if isinstance(m, dict) else getattr(m, "id", None)
        if mid is None or mid not in seen:
            if mid is not None:
                seen.add(mid)
            deduped.append(m)
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
    """Split messages by month or year based on message date."""

    split_messages: Dict[str, List[Dict[str, Any]]] = {}
    for msg in messages:
        raw_date = (
            msg.get("date") if isinstance(msg, dict) else getattr(msg, "date", None)
        )
        parsed_date = _parse_date(raw_date)
        if not parsed_date:
            continue

        try:
            key = parsed_date.strftime("%Y-%m" if split_by == "month" else "%Y")
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
    media_original_names: bool = False,
) -> None:
    """Save messages to JSON displaying a status message if slow."""
    return await _run_with_status(
        downloader.save_messages(
            messages, output_file, sort_order=sort_order, download_media=download_media,
            media_original_names=media_original_names,
        ),
        downloader.logger,
    )


async def save_txt_with_status(
    downloader: TelegramChatDownloader,
    messages: List[Any],
    txt_file: Path,
    sort_order: str = "asc",
) -> int:
    """Save messages to a text file with progress output."""
    return await _run_with_status(
        downloader.save_messages_as_txt(messages, txt_file, sort_order),
        downloader.logger,
    )


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
        output_file = str(output_dir / f"{safe_chat_name}.json")
        if args.subchat:
            output_file = str(
                Path(output_file).with_stem(
                    f"{Path(output_file).stem}_subchat_{args.subchat}"
                )
            )

    since_id = args.since_id
    existing_messages: List[Any] = []
    output_path = Path(output_file)
    if not args.overwrite and since_id is None and output_path.exists():
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    existing_messages = data
                    ids = [
                        m.get("id") for m in data if isinstance(m, dict) and "id" in m
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
    if since_id is not None:
        download_kwargs["since_id"] = since_id

    messages = await downloader.download_chat(**download_kwargs)
    downloader.logger.debug(f"Downloaded {len(messages)} messages")

    if existing_messages:
        messages = _dedup_messages(existing_messages + messages)

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

    try:
        if args.split:
            split_messages = split_messages_by_date(messages, args.split)
            if not split_messages:
                downloader.logger.warning(
                    "No messages with valid dates found for splitting"
                )
                await save_messages_with_status(
                    downloader, messages, output_file, args.sort, args.media,
                    args.media_original_names,
                )
            else:
                output_path = Path(output_file)
                base_name = output_path.stem
                ext = output_path.suffix
                for date_key, msgs in split_messages.items():
                    split_file = output_path.with_name(f"{base_name}_{date_key}{ext}")
                    await save_messages_with_status(
                        downloader, msgs, str(split_file), args.sort, args.media,
                        args.media_original_names,
                    )
                    downloader.logger.info(
                        f"Saved {len(msgs)} messages to {split_file}"
                    )
                downloader.logger.info(
                    f"Saved {len(split_messages)} split files in {output_path.parent}"
                )
        else:
            await save_messages_with_status(
                downloader, messages, output_file, args.sort, args.media,
                args.media_original_names,
            )
    except Exception as e:
        downloader.logger.exception(f"Failed to save messages: {e}")
        return {"chat_id": chat_identifier, "error": str(e)}

    entity = await downloader.get_entity(chat_identifier)
    chat_type = "unknown"
    if isinstance(entity, User):
        chat_type = "private"
    elif isinstance(entity, Chat):
        chat_type = "group"
    elif isinstance(entity, Channel):
        chat_type = "channel" if getattr(entity, "broadcast", False) else "supergroup"

    result = {
        "chat_id": getattr(entity, "id", chat_identifier),
        "chat_title": await downloader.get_entity_full_name(chat_identifier),
        "chat_type": chat_type,
        "args": {"limit": args.limit} if args.limit else {},
        "messages": len(messages),
        "from": first_date,
        "to": last_date,
        "result_json": output_file,
        "result_txt": str(Path(output_file).with_suffix(".txt")),
        "keywords": keywords_data,
    }
    if args.media:
        attachments_dir = downloader.get_attachments_dir(Path(output_file))
        result["result_attachments"] = str(attachments_dir)
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
        return 1

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

    if args.split:
        split_messages = split_messages_by_date(messages, args.split)
        if not split_messages:
            downloader.logger.warning(
                "No messages with valid dates found for splitting"
            )
            saved = await save_txt_with_status(
                downloader, messages, txt_path, args.sort
            )
            saved_relative = get_relative_to_downloads_dir(txt_path)
            downloader.logger.info(f"Saved {saved} messages to {saved_relative}")
        else:
            base_name = txt_path.stem
            ext = txt_path.suffix
            for date_key, msgs in split_messages.items():
                split_file = txt_path.with_name(f"{base_name}_{date_key}{ext}")
                saved = await save_txt_with_status(
                    downloader, msgs, split_file, args.sort
                )
                saved_relative = get_relative_to_downloads_dir(split_file)
                downloader.logger.info(f"Saved {saved} messages to {saved_relative}")
            downloader.logger.info(
                f"Saved {len(split_messages)} split files in {txt_path.parent}"
            )
    else:
        saved = await save_txt_with_status(downloader, messages, txt_path, args.sort)
        saved_relative = get_relative_to_downloads_dir(txt_path)
        downloader.logger.info(f"Saved {saved} messages to {saved_relative}")

    downloader.logger.debug("Conversion completed successfully")
    return {
        "chat_id": None,
        "chat_title": json_path.stem,
        "chat_type": "json",
        "args": {},
        "messages": len(messages),
        "from": first_date,
        "to": last_date,
        "result_json": str(json_path),
        "result_txt": str(txt_path),
        "keywords": keywords_data,
    }


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
    "process_chat_download",
    "convert",
    "folder",
    "download",
]

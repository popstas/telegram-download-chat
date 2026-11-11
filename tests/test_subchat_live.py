"""--subchat on a live download: Telethon messages and forum-topic fetch."""

from datetime import datetime, timezone

from telethon.tl.types import Message, MessageReplyHeader, PeerChannel

from telegram_download_chat.cli.commands import filter_messages_by_subchat

DATE = datetime(2026, 11, 11, tzinfo=timezone.utc)


def _msg(msg_id, reply_to_msg_id=None, reply_to_top_id=None):
    reply_to = None
    if reply_to_msg_id is not None:
        reply_to = MessageReplyHeader(
            reply_to_msg_id=reply_to_msg_id,
            reply_to_top_id=reply_to_top_id,
            forum_topic=True,
        )
    return Message(
        id=msg_id,
        peer_id=PeerChannel(1),
        date=DATE,
        message=f"m{msg_id}",
        reply_to=reply_to,
    )


def test_filter_accepts_telethon_messages():
    messages = [
        _msg(2853),  # topic root, no reply header
        _msg(2900, reply_to_msg_id=2853),
        _msg(2901, reply_to_msg_id=2900, reply_to_top_id=2853),
        _msg(2902, reply_to_msg_id=10),
        _msg(2903),
    ]
    filtered = filter_messages_by_subchat(messages, "https://t.me/c/2419773158/2853")
    assert [m.id for m in filtered] == [2853, 2900, 2901]


def test_filter_accepts_mixed_dicts_and_messages():
    # download_chat returns partial-file dicts next to live Message objects.
    messages = [
        {"id": 2853, "reply_to": None},
        {"id": 2950, "reply_to": {"reply_to_msg_id": 2853}},
        {"id": 2951, "reply_to": {"reply_to_msg_id": 7}},
        _msg(3000, reply_to_msg_id=2950, reply_to_top_id=2853),
    ]
    filtered = filter_messages_by_subchat(messages, "2853")
    ids = [m["id"] if isinstance(m, dict) else m.id for m in filtered]
    assert ids == [2853, 2950, 3000]

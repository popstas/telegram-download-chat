"""--unread: cursor from the dialog, per-topic forum state, CLI wiring."""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telethon.tl.functions.messages import (
    GetForumTopicsByIDRequest,
    GetForumTopicsRequest,
    GetPeerDialogsRequest,
)
from telethon.tl.types import Message, MessageReplyHeader, PeerUser

from telegram_download_chat.cli import async_main
from telegram_download_chat.cli.arguments import parse_args
from telegram_download_chat.core.unread import (
    UnreadError,
    UnreadState,
    count_unread_incoming,
    fetch_unread_state,
    filter_unread,
)

DATE = datetime(2026, 11, 12, tzinfo=timezone.utc)


def _msg(msg_id, out=False, topic=None, general_reply=None):
    reply_to = None
    if topic is not None:
        reply_to = MessageReplyHeader(reply_to_msg_id=topic, forum_topic=True)
    if general_reply is not None:
        # A reply thread inside General: top_id is the thread root, not a topic.
        reply_to = MessageReplyHeader(
            reply_to_msg_id=general_reply + 1,
            reply_to_top_id=general_reply,
            forum_topic=False,
        )
    return Message(
        id=msg_id,
        peer_id=PeerUser(1),
        date=DATE,
        message=f"m{msg_id}",
        out=out,
        reply_to=reply_to,
    )


class FakeClient:
    """Answers the read-only requests --unread makes; records them."""

    def __init__(self, dialogs=None, topics=None, topics_by_id=None):
        self.dialogs = dialogs if dialogs is not None else []
        self.topics = topics or []
        self.topics_by_id = topics_by_id or []
        self.requests = []

    async def get_input_entity(self, entity):
        return MagicMock(name="input_peer")

    async def __call__(self, request):
        self.requests.append(request)
        if isinstance(request, GetPeerDialogsRequest):
            return SimpleNamespace(dialogs=self.dialogs)
        if isinstance(request, GetForumTopicsRequest):
            return SimpleNamespace(topics=self.topics)
        if isinstance(request, GetForumTopicsByIDRequest):
            return SimpleNamespace(topics=self.topics_by_id)
        raise AssertionError(f"unexpected request {request!r}")


def _dialog(unread, cursor, mark=False):
    return SimpleNamespace(
        unread_count=unread, read_inbox_max_id=cursor, unread_mark=mark
    )


def _topic(tid, unread, cursor, title="t"):
    return SimpleNamespace(
        id=tid, unread_count=unread, read_inbox_max_id=cursor, title=title
    )


# --- arguments -------------------------------------------------------------


def test_unread_flag_parsed():
    assert parse_args(["chat", "--unread"]).unread is True
    assert parse_args(["chat"]).unread is False


def test_unread_conflicts_with_since_id():
    with pytest.raises(SystemExit):
        parse_args(["chat", "--unread", "--since-id", "5"])


def test_unread_rejects_json_input():
    with pytest.raises(SystemExit):
        parse_args(["export/messages.json", "--unread"])


@pytest.mark.asyncio
async def test_unread_conflict_rechecked_after_preset(tmp_path):
    downloader = MagicMock()
    downloader.logger = MagicMock()
    downloader.config = {
        "settings": {"save_path": str(tmp_path)},
        "presets": [{"name": "p", "args": {"since_id": 7}}],
    }
    downloader.download_chat = AsyncMock(return_value=[])
    with patch("sys.argv", ["prog", "chat", "--unread", "--preset", "p"]), patch(
        "telegram_download_chat.cli.TelegramChatDownloader", return_value=downloader
    ):
        assert await async_main() == 1
    downloader.download_chat.assert_not_called()


# --- reading the state -----------------------------------------------------


@pytest.mark.asyncio
async def test_dialog_state_for_plain_chat():
    client = FakeClient(dialogs=[_dialog(3, 120)])
    state = await fetch_unread_state(client, SimpleNamespace(forum=False))
    assert (state.unread_count, state.read_inbox_max_id) == (3, 120)
    assert [type(r) for r in client.requests] == [GetPeerDialogsRequest]


@pytest.mark.asyncio
async def test_chat_missing_from_dialogs_is_a_clear_error():
    with pytest.raises(UnreadError, match="dialog list"):
        await fetch_unread_state(FakeClient(dialogs=[]), SimpleNamespace(forum=False))


@pytest.mark.asyncio
async def test_forum_without_subchat_reads_every_unread_topic():
    client = FakeClient(
        topics=[_topic(1, 2, 50), _topic(20, 5, 40), _topic(30, 0, 10)],
        # The dialog of a forum does not match its topics; it must not be used.
        dialogs=[_dialog(999, 1)],
    )
    state = await fetch_unread_state(client, SimpleNamespace(forum=True))
    assert state.unread_count == 7
    assert state.read_inbox_max_id == 40  # the oldest unread topic's cursor
    assert state.topic_cursors == {1: 50, 20: 40}
    assert [t["id"] for t in state.topics] == [1, 20]
    assert not any(isinstance(r, GetPeerDialogsRequest) for r in client.requests)


@pytest.mark.asyncio
async def test_forum_subchat_uses_the_topic_state():
    client = FakeClient(topics_by_id=[_topic(20, 4, 300)])
    state = await fetch_unread_state(client, SimpleNamespace(forum=True), 20)
    assert (state.unread_count, state.read_inbox_max_id, state.topic_id) == (
        4,
        300,
        20,
    )


@pytest.mark.asyncio
async def test_forum_subchat_on_a_reply_thread_falls_back_to_topics():
    # A non-topic id: GetForumTopicsByID returns nothing usable, and the
    # forum's dialog counters lag its topics, so the per-topic state is used.
    client = FakeClient(
        topics_by_id=[], topics=[_topic(1, 2, 50)], dialogs=[_dialog(9, 1)]
    )
    state = await fetch_unread_state(client, SimpleNamespace(forum=True), 555)
    assert (state.unread_count, state.read_inbox_max_id) == (2, 50)
    assert state.topic_cursors == {1: 50}
    assert not any(isinstance(r, GetPeerDialogsRequest) for r in client.requests)


@pytest.mark.asyncio
async def test_channel_not_joined_is_an_error():
    # Live, Telegram answers a not-joined channel with an all-zero dialog.
    client = FakeClient(dialogs=[_dialog(0, 0)])
    with pytest.raises(UnreadError, match="member"):
        await fetch_unread_state(client, SimpleNamespace(forum=False, left=True))
    assert client.requests == []


def test_never_marks_anything_read():
    # The requests --unread may send are exactly the read-only ones above.
    import telegram_download_chat.core.unread as unread

    source = open(unread.__file__, encoding="utf-8").read()
    assert "ReadHistory" not in source
    assert "send_read_acknowledge" not in source


# --- filtering and counting ------------------------------------------------


def test_filter_keeps_outgoing_but_counts_only_incoming():
    state = UnreadState(unread_count=2, read_inbox_max_id=10)
    messages = [
        _msg(9),
        _msg(10),
        _msg(11),
        _msg(12, out=True),
        {"id": 13, "out": False},  # resumed .part dict
        {"id": 14, "cited_outside_window": True},
    ]
    kept = filter_unread(messages, state)
    ids = [m["id"] if isinstance(m, dict) else m.id for m in kept]
    assert ids == [11, 12, 13, 14]
    assert count_unread_incoming(kept, state) == 2


def test_filter_with_zero_cursor_keeps_everything():
    state = UnreadState(unread_count=2, read_inbox_max_id=0)
    assert len(filter_unread([_msg(1), _msg(2)], state)) == 2


def test_forum_filter_applies_each_topics_cursor():
    state = UnreadState(
        unread_count=3, read_inbox_max_id=40, topic_cursors={1: 50, 20: 40}
    )
    messages = [
        _msg(45),  # General, read (cursor 50)
        _msg(55),  # General, unread
        _msg(45, topic=20),  # topic 20, unread
        _msg(60, topic=30),  # topic 30 has no unread: dropped
        _msg(56, general_reply=52),  # reply thread in General: unread
        {"id": 57, "reply_to": {"reply_to_top_id": 52, "forum_topic": False}},
    ]
    kept = filter_unread(messages, state)
    ids = [m["id"] if isinstance(m, dict) else m.id for m in kept]
    assert ids == [55, 45, 56, 57]


# --- process_chat_download wiring ------------------------------------------


def _downloader(tmp_path, messages):
    d = AsyncMock()
    d.config = {"settings": {"save_path": str(tmp_path)}}
    d.logger = MagicMock()
    d.client = MagicMock()
    d.get_entity_name = AsyncMock(return_value="chat")
    d.get_entity_full_name = AsyncMock(return_value="Chat")
    d.get_entity = AsyncMock(return_value=SimpleNamespace(id=123, forum=False))
    d.download_chat = AsyncMock(return_value=messages)
    d.save_messages = AsyncMock()
    d.make_serializable = lambda x: x
    d.get_attachments_dir = MagicMock(return_value=tmp_path / "attachments")
    return d


async def _run(tmp_path, downloader, state, argv, capsys):
    with patch("sys.argv", ["prog", *argv]), patch(
        "telegram_download_chat.cli.TelegramChatDownloader", return_value=downloader
    ), patch(
        "telegram_download_chat.cli.commands.fetch_unread_state",
        AsyncMock(return_value=state),
    ), patch(
        "telegram_download_chat.cli.commands.fetch_outside_window_citations",
        AsyncMock(return_value=[]),
    ):
        code = await async_main()
    out = capsys.readouterr().out
    return code, json.loads(out)["results"][0] if out.strip() else None


@pytest.mark.asyncio
async def test_unread_sets_since_id_and_ignores_existing_output(tmp_path, capsys):
    out_file = tmp_path / "out.json"
    out_file.write_text(json.dumps([{"id": 500, "date": "2026-11-01T00:00:00"}]))
    # id 99 stands for a read message from a leftover .part file.
    d = _downloader(tmp_path, [{"id": 99}, _msg(101), _msg(102, out=True), _msg(103)])
    state = UnreadState(unread_count=2, read_inbox_max_id=100)

    code, result = await _run(
        tmp_path,
        d,
        state,
        ["chat", "--unread", "-o", str(out_file), "--limit", "10", "--results-json"],
        capsys,
    )

    assert code == 0
    kwargs = d.download_chat.call_args.kwargs
    # The dialog's cursor wins over both the existing file and --limit backfill.
    assert kwargs["since_id"] == 100
    saved = d.save_messages.call_args[0][0]
    assert [m.id for m in saved] == [101, 102, 103]  # not merged with id 500
    assert result["unread_count"] == 2
    assert result["read_inbox_max_id"] == 100
    assert result["unread_downloaded"] == 2
    assert result["messages"] == 3


@pytest.mark.asyncio
async def test_no_unread_downloads_nothing_and_exits_zero(tmp_path, capsys):
    out_file = tmp_path / "out.json"
    out_file.write_text("[]")
    d = _downloader(tmp_path, [])
    state = UnreadState(unread_count=0, read_inbox_max_id=42)

    code, result = await _run(
        tmp_path,
        d,
        state,
        ["chat", "--unread", "-o", str(out_file), "--results-json"],
        capsys,
    )

    assert code == 0
    d.download_chat.assert_not_called()
    d.save_messages.assert_not_called()
    assert out_file.read_text() == "[]"  # existing output untouched
    assert result["messages"] == 0
    assert result["unread_count"] == 0
    assert result["read_inbox_max_id"] == 42
    assert "error" not in result


@pytest.mark.asyncio
async def test_unread_state_error_is_reported(tmp_path, capsys):
    d = _downloader(tmp_path, [])
    with patch("sys.argv", ["prog", "chat", "--unread", "--results-json"]), patch(
        "telegram_download_chat.cli.TelegramChatDownloader", return_value=d
    ), patch(
        "telegram_download_chat.cli.commands.fetch_unread_state",
        AsyncMock(side_effect=UnreadError("not in dialogs")),
    ):
        code = await async_main()
    result = json.loads(capsys.readouterr().out)["results"][0]
    assert code == 1
    assert result["error"] == "not in dialogs"
    d.download_chat.assert_not_called()


@pytest.mark.asyncio
async def test_default_output_does_not_replace_full_export(tmp_path, capsys):
    chat_dir = tmp_path / "chat"
    chat_dir.mkdir()
    full = chat_dir / "messages.json"
    full.write_text(json.dumps([{"id": 1}]))
    d = _downloader(tmp_path, [_msg(101)])
    state = UnreadState(unread_count=1, read_inbox_max_id=100)

    code, result = await _run(
        tmp_path, d, state, ["chat", "--unread", "--results-json"], capsys
    )

    assert code == 0
    assert full.read_text() == json.dumps([{"id": 1}])
    saved_to = d.save_messages.call_args[0][1]
    assert Path(saved_to).name == "messages_unread.json"
    assert result["result_json"].endswith("messages_unread.json")


@pytest.mark.asyncio
async def test_forum_limit_applies_after_topic_filter(tmp_path, capsys):
    # The newest messages sit in a read topic; --limit 2 must still return
    # the two newest unread ones instead of being used up by them.
    d = _downloader(
        tmp_path,
        [
            _msg(90, topic=30),
            _msg(89, topic=30),
            _msg(60, topic=20),
            _msg(55, topic=20),
            _msg(51, topic=20),
        ],
    )
    state = UnreadState(unread_count=3, read_inbox_max_id=50, topic_cursors={20: 50})

    code, result = await _run(
        tmp_path,
        d,
        state,
        [
            "chat",
            "--unread",
            "--limit",
            "2",
            "-o",
            str(tmp_path / "o.json"),
            "--results-json",
        ],
        capsys,
    )

    assert code == 0
    assert d.download_chat.call_args.kwargs["total_limit"] == 0
    saved = d.save_messages.call_args[0][0]
    assert sorted(m.id for m in saved) == [55, 60]

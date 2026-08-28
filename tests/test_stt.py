"""Tests for Telegram Premium speech-to-text transcription (``--stt``)."""

import logging
from types import SimpleNamespace

import pytest
from telethon.errors import FloodError, FloodPremiumWaitError, FloodWaitError
from telethon.tl.types import PeerChannel, PeerChat

from telegram_download_chat.core import stt
from telegram_download_chat.core.stt import (
    TranscriptCache,
    is_transcribable,
    transcript_key,
)


def _voice_media(doc_id=111, voice=True):
    return {
        "_": "MessageMediaDocument",
        "document": {
            "_": "Document",
            "id": doc_id,
            "mime_type": "audio/ogg",
            "attributes": [
                {"_": "DocumentAttributeAudio", "duration": 3, "voice": voice},
            ],
        },
    }


def _round_video_media(doc_id=222, round_message=True):
    return {
        "_": "MessageMediaDocument",
        "document": {
            "_": "Document",
            "id": doc_id,
            "mime_type": "video/mp4",
            "attributes": [
                {
                    "_": "DocumentAttributeVideo",
                    "duration": 5,
                    "round_message": round_message,
                },
            ],
        },
    }


def test_voice_message_is_transcribable():
    assert is_transcribable({"id": 1, "media": _voice_media()}) is True


def test_round_video_note_is_transcribable():
    assert is_transcribable({"id": 1, "media": _round_video_media()}) is True


def test_plain_audio_file_is_not_transcribable():
    assert is_transcribable({"id": 1, "media": _voice_media(voice=False)}) is False


def test_plain_video_is_not_transcribable():
    media = _round_video_media(round_message=False)
    assert is_transcribable({"id": 1, "media": media}) is False


def test_photo_is_not_transcribable():
    media = {"_": "MessageMediaPhoto", "photo": {"_": "Photo", "id": 9}}
    assert is_transcribable({"id": 1, "media": media}) is False


def test_message_without_media_is_not_transcribable():
    assert is_transcribable({"id": 1, "message": "hello"}) is False


def test_is_transcribable_reads_telethon_media_object():
    """Raw Telethon messages expose media as an object, not a dict."""
    media = SimpleNamespace(to_dict=lambda: _voice_media())
    msg = SimpleNamespace(id=1, media=media)
    assert is_transcribable(msg) is True


def test_transcript_key_is_the_document_id():
    assert transcript_key({"id": 1, "media": _voice_media(doc_id=777)}) == 777


def test_transcript_key_is_none_without_media():
    assert transcript_key({"id": 1, "message": "hi"}) is None


# --- TranscriptCache -------------------------------------------------------


def test_cache_returns_none_for_unknown_key(tmp_path):
    cache = TranscriptCache(tmp_path / "stt-cache.jsonl")
    assert cache.get(123) is None


def test_cache_persists_across_instances(tmp_path):
    path = tmp_path / "stt-cache.jsonl"
    TranscriptCache(path).put(123, "привет", chat="popstas", msg_id=42)
    assert TranscriptCache(path).get(123) == "привет"


def test_cache_appends_instead_of_rewriting(tmp_path):
    path = tmp_path / "stt-cache.jsonl"
    cache = TranscriptCache(path)
    cache.put(1, "one", chat="c", msg_id=1)
    cache.put(2, "two", chat="c", msg_id=2)
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_cache_last_entry_wins(tmp_path):
    path = tmp_path / "stt-cache.jsonl"
    path.write_text(
        '{"doc_id": 5, "text": "old"}\n{"doc_id": 5, "text": "new"}\n',
        encoding="utf-8",
    )
    assert TranscriptCache(path).get(5) == "new"


def test_cache_skips_corrupt_lines(tmp_path):
    path = tmp_path / "stt-cache.jsonl"
    path.write_text(
        'not json\n{"doc_id": 5, "text": "kept"}\n{"no_doc_id": 1}\n',
        encoding="utf-8",
    )
    assert TranscriptCache(path).get(5) == "kept"


def test_cache_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "stt-cache.jsonl"
    TranscriptCache(path).put(1, "text", chat="c", msg_id=1)
    assert path.exists()


# --- transcribe_messages ---------------------------------------------------


class _FakeClient:
    """Fake Telethon client: answers TranscribeAudioRequest from a script."""

    def __init__(self, script, entity_error=None):
        # script: {(peer, msg_id): [result_or_exception, ...]} popped in order
        self.script = script
        self.calls = []
        self.entity_error = entity_error
        self.entity_calls = 0

    async def get_input_entity(self, peer):
        self.entity_calls += 1
        if self.entity_error is not None:
            raise self.entity_error
        # str(): Telethon peer objects are unhashable, so keep dict keys simple.
        return ("input", str(peer))

    async def __call__(self, request):
        key = (request.peer, request.msg_id)
        self.calls.append(key)
        outcomes = self.script.get(key)
        if not outcomes:
            raise AssertionError(f"unexpected transcribe call for {key}")
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _transcribed(text, pending=False):
    return SimpleNamespace(text=text, pending=pending, transcription_id=1)


def _make_downloader(client, premium=True):
    downloader = SimpleNamespace()
    downloader.client = client
    downloader.logger = logging.getLogger("test-stt")
    downloader._is_premium = premium

    async def _detect_premium_once():
        downloader.premium_checked = True

    downloader.premium_checked = False
    downloader._detect_premium_once = _detect_premium_once
    return downloader


def _voice_msg(msg_id, doc_id):
    return {"id": msg_id, "media": _voice_media(doc_id=doc_id)}


@pytest.fixture(autouse=True)
def _no_poll_sleep(monkeypatch):
    monkeypatch.setattr(stt, "PENDING_POLL_SECONDS", 0)


@pytest.mark.asyncio
async def test_transcribes_voice_messages(tmp_path):
    peer = ("input", "popstas")
    client = _FakeClient(
        {
            (peer, 1): [_transcribed("first")],
            (peer, 2): [_transcribed("second")],
        }
    )
    messages = [_voice_msg(1, 101), _voice_msg(2, 102), {"id": 3, "message": "text"}]

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        messages,
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert result == {101: "first", 102: "second"}
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_skips_messages_that_already_have_a_transcript(tmp_path):
    client = _FakeClient({})
    msg = _voice_msg(1, 101)
    msg["transcript"] = "already there"

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        [msg],
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert client.calls == []
    assert result == {}


@pytest.mark.asyncio
async def test_cache_hit_avoids_the_api(tmp_path):
    cache = TranscriptCache(tmp_path / "c.jsonl")
    cache.put(101, "from cache", chat="popstas", msg_id=1)
    client = _FakeClient({})

    result = await stt.transcribe_messages(
        _make_downloader(client), "popstas", [_voice_msg(1, 101)], cache=cache
    )

    assert result == {101: "from cache"}
    assert client.calls == []


@pytest.mark.asyncio
async def test_successful_transcription_is_written_to_the_cache(tmp_path):
    path = tmp_path / "c.jsonl"
    peer = ("input", "popstas")
    client = _FakeClient({(peer, 1): [_transcribed("fresh")]})

    await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        [_voice_msg(1, 101)],
        cache=TranscriptCache(path),
    )

    assert TranscriptCache(path).get(101) == "fresh"


@pytest.mark.asyncio
async def test_non_premium_account_makes_no_api_calls(tmp_path):
    cache = TranscriptCache(tmp_path / "c.jsonl")
    cache.put(101, "cached", chat="popstas", msg_id=1)
    client = _FakeClient({})

    result = await stt.transcribe_messages(
        _make_downloader(client, premium=False),
        "popstas",
        [_voice_msg(1, 101), _voice_msg(2, 102)],
        cache=cache,
    )

    # The cached one still reaches the export; the uncached one is skipped.
    assert result == {101: "cached"}
    assert client.calls == []


@pytest.mark.asyncio
async def test_premium_is_not_checked_when_everything_is_cached(tmp_path):
    cache = TranscriptCache(tmp_path / "c.jsonl")
    cache.put(101, "cached", chat="popstas", msg_id=1)
    downloader = _make_downloader(_FakeClient({}))

    await stt.transcribe_messages(
        downloader, "popstas", [_voice_msg(1, 101)], cache=cache
    )

    assert downloader.premium_checked is False


@pytest.mark.asyncio
async def test_pending_transcription_is_retried_until_ready(tmp_path):
    peer = ("input", "popstas")
    client = _FakeClient(
        {
            (peer, 1): [
                _transcribed("partial", pending=True),
                _transcribed("complete", pending=False),
            ]
        }
    )

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        [_voice_msg(1, 101)],
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert result == {101: "complete"}
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_transcription_still_pending_at_the_deadline_is_given_up(
    tmp_path, monkeypatch, caplog
):
    """Telegram is still working; the export must not stall on it forever."""
    monkeypatch.setattr(stt, "PENDING_TIMEOUT_SECONDS", 6)
    monkeypatch.setattr(stt, "PENDING_POLL_SECONDS", 2)
    peer = ("input", "popstas")
    client = _FakeClient({(peer, 1): [_transcribed("", pending=True)] * 20})

    with caplog.at_level(logging.WARNING):
        result = await stt.transcribe_messages(
            _make_downloader(client),
            "popstas",
            [_voice_msg(1, 101)],
            cache=TranscriptCache(tmp_path / "c.jsonl"),
        )

    assert result == {}
    # One kick-off plus PENDING_TIMEOUT_SECONDS / PENDING_POLL_SECONDS polls.
    assert len(client.calls) == 4
    assert "still being transcribed" in caplog.text


@pytest.mark.asyncio
async def test_fully_cached_run_says_so_instead_of_going_quiet(tmp_path, caplog):
    cache = TranscriptCache(tmp_path / "c.jsonl")
    cache.put(101, "cached")
    client = _FakeClient({})

    with caplog.at_level(logging.INFO):
        result = await stt.transcribe_messages(
            _make_downloader(client), "popstas", [_voice_msg(1, 101)], cache=cache
        )

    assert result == {101: "cached"}
    assert client.calls == []
    assert "cache" in caplog.text


@pytest.mark.asyncio
async def test_every_request_is_issued_before_any_pending_one_is_polled(tmp_path):
    """Telegram transcribes in parallel: kick all of them off, then collect."""
    peer = ("input", "popstas")
    client = _FakeClient(
        {
            (peer, 1): [_transcribed("", pending=True), _transcribed("first")],
            (peer, 2): [_transcribed("", pending=True), _transcribed("second")],
        }
    )

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        [_voice_msg(1, 101), _voice_msg(2, 102)],
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert result == {101: "first", 102: "second"}
    # Both kicked off first, and only then polled — not 1,1,2,2.
    assert client.calls == [(peer, 1), (peer, 2), (peer, 1), (peer, 2)]


@pytest.mark.asyncio
async def test_premium_flood_wait_aborts_the_pass(tmp_path):
    """FloodPremiumWaitError is a sibling of FloodWaitError, not a subclass."""
    peer = ("input", "popstas")
    client = _FakeClient(
        {
            (peer, 1): [FloodPremiumWaitError(request=None, capture=8942)],
            (peer, 2): [_transcribed("never reached")],
        }
    )

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        [_voice_msg(1, 101), _voice_msg(2, 102)],
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert result == {}
    assert client.calls == [(peer, 1)]


@pytest.mark.asyncio
async def test_rate_limit_is_reported_as_a_readable_duration(tmp_path, caplog):
    peer = ("input", "popstas")
    client = _FakeClient({(peer, 1): [FloodWaitError(request=None, capture=8942)]})

    with caplog.at_level(logging.WARNING):
        await stt.transcribe_messages(
            _make_downloader(client),
            "popstas",
            [_voice_msg(1, 101)],
            cache=TranscriptCache(tmp_path / "c.jsonl"),
        )

    assert "2h 29m" in caplog.text
    assert "8942" not in caplog.text


def _bare_flood():
    """Telegram's burst limit: a FLOOD error carrying no retry time at all."""
    return FloodError(request=None, message="FLOOD", code=420)


@pytest.mark.asyncio
async def test_rate_limit_count_excludes_permanent_failures(tmp_path, caplog):
    """A voice message Telegram refuses outright is not "waiting on the limit"."""
    peer = ("input", "popstas")
    too_long = RuntimeError("RPCError 400: MSG_VOICE_TOO_LONG")
    client = _FakeClient(
        {
            (peer, 1): [_transcribed("ok")],
            (peer, 2): [too_long],
            (peer, 3): [FloodWaitError(request=None, capture=3600)],
        }
    )
    messages = [_voice_msg(1, 101), _voice_msg(2, 102), _voice_msg(3, 103)]

    with caplog.at_level(logging.WARNING):
        await stt.transcribe_messages(
            _make_downloader(client),
            "popstas",
            messages,
            cache=TranscriptCache(tmp_path / "c.jsonl"),
        )

    assert "1 of 3 voice message(s) left untranscribed" in caplog.text


@pytest.mark.asyncio
async def test_message_is_addressed_by_its_own_peer_id(tmp_path):
    """The CLI hands over a digit *string*; Telethon reads that as a username.

    Resolving it costs an online lookup that can flood for hours, while the
    message's own peer_id resolves straight from the session cache.
    """
    msg = _voice_msg(1, 101)
    msg["peer_id"] = {"_": "PeerChat", "chat_id": 5375745951}
    peer = ("input", str(PeerChat(5375745951)))
    client = _FakeClient({(peer, 1): [_transcribed("done")]})

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "5375745951",
        [msg],
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert result == {101: "done"}


@pytest.mark.asyncio
async def test_unresolvable_peer_id_falls_back_to_the_chat_identifier(tmp_path):
    msg = _voice_msg(1, 101)
    msg["peer_id"] = {"_": "PeerUser", "user_id": 999}
    peer = ("input", "popstas")
    client = _FakeClient({(peer, 1): [_transcribed("done")]})

    async def _get_input_entity(ref):
        from telethon.tl.types import PeerUser

        if isinstance(ref, PeerUser):
            raise ValueError("Could not find the input entity")
        return ("input", str(ref))

    client.get_input_entity = _get_input_entity

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        [msg],
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert result == {101: "done"}


@pytest.mark.asyncio
async def test_flood_while_resolving_the_chat_ends_the_pass_once(tmp_path, caplog):
    """Resolving the chat can flood too; that is a rate limit, not 30 failures."""
    client = _FakeClient({}, entity_error=FloodWaitError(request=None, capture=8335))
    messages = [_voice_msg(i, 100 + i) for i in range(1, 31)]

    with caplog.at_level(logging.WARNING):
        result = await stt.transcribe_messages(
            _make_downloader(client),
            "popstas",
            messages,
            cache=TranscriptCache(tmp_path / "c.jsonl"),
        )

    assert result == {}
    assert client.entity_calls == 1
    assert caplog.text.count("rate-limited") == 1
    assert "could not be transcribed" not in caplog.text


@pytest.mark.asyncio
async def test_bare_flood_is_backed_off_and_retried(tmp_path, monkeypatch):
    """A bare FLOOD is a transient burst limit, not the end of the quota."""
    slept = []

    async def _fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(stt.asyncio, "sleep", _fake_sleep)
    peer = ("input", "popstas")
    client = _FakeClient({(peer, 1): [_bare_flood(), _transcribed("done")]})

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        [_voice_msg(1, 101)],
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert result == {101: "done"}
    assert stt.FLOOD_RETRY_BACKOFF_SECONDS[0] in slept


@pytest.mark.asyncio
async def test_persistent_bare_flood_ends_the_pass_once(tmp_path, monkeypatch, caplog):
    """One clear message beats a failure logged per message."""

    async def _fake_sleep(seconds):
        return None

    monkeypatch.setattr(stt.asyncio, "sleep", _fake_sleep)
    peer = ("input", "popstas")
    retries = len(stt.FLOOD_RETRY_BACKOFF_SECONDS)
    client = _FakeClient(
        {
            (peer, 1): [_bare_flood()] * (retries + 1),
            (peer, 2): [_transcribed("never reached")],
        }
    )

    with caplog.at_level(logging.WARNING):
        result = await stt.transcribe_messages(
            _make_downloader(client),
            "popstas",
            [_voice_msg(1, 101), _voice_msg(2, 102)],
            cache=TranscriptCache(tmp_path / "c.jsonl"),
        )

    assert result == {}
    # Message 2 is never attempted: the limit is account-wide, not per message.
    assert client.calls == [(peer, 1)] * (retries + 1)
    assert caplog.text.count("rate-limited") == 1


@pytest.mark.asyncio
async def test_rate_limit_still_collects_transcriptions_already_in_flight(
    tmp_path, monkeypatch
):
    """Audio already handed to Telegram keeps transcribing; go and fetch it."""

    async def _fake_sleep(seconds):
        return None

    monkeypatch.setattr(stt.asyncio, "sleep", _fake_sleep)
    peer = ("input", "popstas")
    client = _FakeClient(
        {
            (peer, 1): [_transcribed("", pending=True), _transcribed("first")],
            (peer, 2): [FloodWaitError(request=None, capture=3600)],
        }
    )

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        [_voice_msg(1, 101), _voice_msg(2, 102)],
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert result == {101: "first"}


@pytest.mark.asyncio
async def test_a_second_flood_in_a_row_ends_the_pass(tmp_path, monkeypatch):
    """Retries are bounded: a wait that keeps coming back ends the pass."""

    async def _fake_sleep(seconds):
        return None

    monkeypatch.setattr(stt.asyncio, "sleep", _fake_sleep)
    peer = ("input", "popstas")
    retries = len(stt.FLOOD_RETRY_BACKOFF_SECONDS)
    client = _FakeClient(
        {
            (peer, 1): [FloodWaitError(request=None, capture=5)] * (retries + 1),
            (peer, 2): [_transcribed("never reached")],
        }
    )

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        [_voice_msg(1, 101), _voice_msg(2, 102)],
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert result == {}
    assert client.calls == [(peer, 1)] * (retries + 1)


@pytest.mark.asyncio
async def test_voice_too_long_is_reported_and_not_retried(tmp_path, caplog):
    """MSG_VOICE_TOO_LONG is permanent — name it instead of failing silently."""
    peer = ("input", "popstas")
    too_long = RuntimeError("RPCError 400: MSG_VOICE_TOO_LONG")
    client = _FakeClient({(peer, 1): [too_long], (peer, 2): [_transcribed("ok")]})

    with caplog.at_level(logging.WARNING):
        result = await stt.transcribe_messages(
            _make_downloader(client),
            "popstas",
            [_voice_msg(1, 101), _voice_msg(2, 102)],
            cache=TranscriptCache(tmp_path / "c.jsonl"),
        )

    assert result == {102: "ok"}
    assert client.calls == [(peer, 1), (peer, 2)]
    assert "longer than Telegram transcribes" in caplog.text


@pytest.mark.asyncio
async def test_short_flood_wait_is_waited_out(tmp_path, monkeypatch):
    slept = []

    async def _fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(stt.asyncio, "sleep", _fake_sleep)
    peer = ("input", "popstas")
    client = _FakeClient(
        {(peer, 1): [FloodWaitError(request=None, capture=5), _transcribed("done")]}
    )

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        [_voice_msg(1, 101)],
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert result == {101: "done"}
    assert 5 in slept


@pytest.mark.asyncio
async def test_long_flood_wait_aborts_the_remaining_messages(tmp_path):
    peer = ("input", "popstas")
    client = _FakeClient(
        {
            (peer, 1): [FloodWaitError(request=None, capture=3600)],
            (peer, 2): [_transcribed("never reached")],
        }
    )

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        [_voice_msg(1, 101), _voice_msg(2, 102)],
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert result == {}
    assert client.calls == [(peer, 1)]


@pytest.mark.asyncio
async def test_error_on_one_message_does_not_stop_the_pass(tmp_path):
    peer = ("input", "popstas")
    client = _FakeClient(
        {
            (peer, 1): [RuntimeError("boom")],
            (peer, 2): [_transcribed("ok")],
        }
    )

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        [_voice_msg(1, 101), _voice_msg(2, 102)],
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert result == {102: "ok"}


@pytest.mark.asyncio
async def test_comment_is_transcribed_against_its_discussion_peer(tmp_path):
    """Comments live in the linked discussion group, under their native id."""
    comment = _voice_msg(555, 101)
    comment["id"] = 555
    comment["discussion_msg_id"] = 555
    comment["comment_of"] = 42
    comment["peer_id"] = {"_": "PeerChannel", "channel_id": 999}

    discussion_peer = ("input", str(PeerChannel(999)))
    client = _FakeClient({(discussion_peer, 555): [_transcribed("comment text")]})

    result = await stt.transcribe_messages(
        _make_downloader(client),
        "popstas",
        [comment],
        cache=TranscriptCache(tmp_path / "c.jsonl"),
    )

    assert result == {101: "comment text"}


# --- export rendering ------------------------------------------------------


def _messages_mixin():
    from unittest.mock import AsyncMock, MagicMock

    from telegram_download_chat.core.messages import MessagesMixin

    m = MessagesMixin()
    m._fetched_usernames_count = 0
    m._fetched_chatnames_count = 0
    m._get_sender_id = lambda msg: msg.get("from_id")
    m._get_recipient_id = lambda msg: None
    m._get_user_display_name = AsyncMock(return_value="Alice")
    m._save_config = MagicMock()
    return m


@pytest.mark.asyncio
async def test_txt_renders_transcript_on_its_own_line(tmp_path):
    txt_path = tmp_path / "out.txt"
    messages = [
        {
            "date": "2026-01-15T12:30:00+00:00",
            "from_id": 123,
            "text": "",
            "transcript": "привет, как дела",
        }
    ]

    await _messages_mixin().save_messages_as_txt(messages, txt_path)

    assert "[stt] привет, как дела" in txt_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_txt_keeps_caption_above_the_transcript(tmp_path):
    txt_path = tmp_path / "out.txt"
    messages = [
        {
            "date": "2026-01-15T12:30:00+00:00",
            "from_id": 123,
            "text": "caption",
            "transcript": "расшифровка",
        }
    ]

    await _messages_mixin().save_messages_as_txt(messages, txt_path)

    assert "caption\n[stt] расшифровка" in txt_path.read_text(encoding="utf-8")


def test_html_renders_the_transcript_block(tmp_path):
    from telegram_download_chat.core.render import RenderMixin

    out = tmp_path / "out.html"
    RenderMixin().render_html(
        [
            {
                "id": 1,
                "date": "2026-01-01T10:00:00+00:00",
                "from_id": {"user_id": 42},
                "user_display_name": "Alice",
                "message": "",
                "transcript": "привет из голосового",
            }
        ],
        out,
        chat_title="t",
    )

    html = out.read_text(encoding="utf-8")
    assert 'class="stt"' in html
    assert "привет из голосового" in html


def test_html_has_no_transcript_block_without_a_transcript(tmp_path):
    from telegram_download_chat.core.render import RenderMixin

    out = tmp_path / "out.html"
    RenderMixin().render_html(
        [
            {
                "id": 1,
                "date": "2026-01-01T10:00:00+00:00",
                "from_id": {"user_id": 42},
                "user_display_name": "Alice",
                "message": "plain",
            }
        ],
        out,
        chat_title="t",
    )

    assert 'class="stt"' not in out.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_save_messages_stamps_transcripts_onto_saved_json(tmp_path):
    """Telethon's to_dict() drops unknown attributes, so save_messages stamps."""
    import json
    from unittest.mock import MagicMock

    from telegram_download_chat.core import TelegramChatDownloader

    class _Voice:
        def __init__(self, mid, doc_id):
            self.id = mid
            self.media = SimpleNamespace(to_dict=lambda: _voice_media(doc_id=doc_id))

        def to_dict(self):
            return {"_": "Message", "id": self.id, "media": _voice_media(doc_id=101)}

    out = tmp_path / "messages.json"
    downloader = TelegramChatDownloader()
    downloader.logger = MagicMock()
    downloader._transcripts = {101: "распознанный текст"}

    await downloader.save_messages([_Voice(7, 101)], str(out), save_txt=False)

    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved[0]["transcript"] == "распознанный текст"


# --- CLI wiring ------------------------------------------------------------


def test_stt_flag_is_off_by_default():
    from telegram_download_chat.cli.arguments import parse_args

    assert parse_args(["popstas"]).stt is False


def test_stt_flag_is_parsed():
    from telegram_download_chat.cli.arguments import parse_args

    assert parse_args(["popstas", "--stt"]).stt is True


@pytest.mark.asyncio
async def test_apply_transcriptions_does_nothing_without_the_flag(tmp_path):
    from telegram_download_chat.cli.commands import apply_transcriptions

    client = _FakeClient({})
    downloader = _make_downloader(client)
    args = SimpleNamespace(stt=False)

    await apply_transcriptions(downloader, "popstas", [_voice_msg(1, 101)], args)

    assert client.calls == []
    assert not getattr(downloader, "_transcripts", None)


@pytest.mark.asyncio
async def test_apply_transcriptions_stores_results_on_the_downloader(
    tmp_path, monkeypatch
):
    from telegram_download_chat.cli.commands import apply_transcriptions

    monkeypatch.setattr(stt, "default_cache_path", lambda: tmp_path / "c.jsonl")
    peer = ("input", "popstas")
    client = _FakeClient({(peer, 1): [_transcribed("hello")]})
    downloader = _make_downloader(client)

    await apply_transcriptions(
        downloader, "popstas", [_voice_msg(1, 101)], SimpleNamespace(stt=True)
    )

    assert downloader._transcripts == {101: "hello"}


@pytest.mark.asyncio
async def test_apply_transcriptions_survives_a_failing_pass(tmp_path, monkeypatch):
    """Transcription is best-effort: a failure must not abort the export."""
    from telegram_download_chat.cli import commands

    async def _boom(*a, **kw):
        raise RuntimeError("telegram is down")

    monkeypatch.setattr(commands, "transcribe_messages", _boom)
    downloader = _make_downloader(_FakeClient({}))

    await commands.apply_transcriptions(
        downloader, "popstas", [_voice_msg(1, 101)], SimpleNamespace(stt=True)
    )

    assert not getattr(downloader, "_transcripts", None)


def test_pdf_renders_the_transcript(tmp_path, monkeypatch):
    pytest.importorskip("reportlab")
    import reportlab.platypus as platypus

    from telegram_download_chat.core.render import RenderMixin

    recorded = []
    real_paragraph = platypus.Paragraph

    class _RecordingParagraph(real_paragraph):
        def __init__(self, text, *args, **kwargs):
            recorded.append(text)
            super().__init__(text, *args, **kwargs)

    monkeypatch.setattr(platypus, "Paragraph", _RecordingParagraph)

    RenderMixin().render_pdf(
        [
            {
                "id": 1,
                "date": "2026-01-01T10:00:00+00:00",
                "from_id": {"user_id": 42},
                "user_display_name": "Alice",
                "message": "",
                "transcript": "привет из голосового",
            }
        ],
        tmp_path / "out.pdf",
        chat_title="t",
    )

    assert any("привет из голосового" in text for text in recorded)


def test_pdf_survives_a_transcript_longer_than_a_page(tmp_path):
    """A long voice message must not blow up the PDF export.

    Bubbles are rendered as single-row tables, and ReportLab cannot break a row
    that is taller than the frame — a several-thousand-character transcript is.
    """
    pytest.importorskip("reportlab")

    from telegram_download_chat.core.render import RenderMixin

    out = tmp_path / "out.pdf"
    RenderMixin().render_pdf(
        [
            {
                "id": 1,
                "date": "2026-01-01T10:00:00+00:00",
                "from_id": {"user_id": 42},
                "user_display_name": "Alice",
                "message": "",
                "transcript": "слово " * 2000,
            }
        ],
        out,
        chat_title="t",
    )

    assert out.exists() and out.read_bytes().startswith(b"%PDF")

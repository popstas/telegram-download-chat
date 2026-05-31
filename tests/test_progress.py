"""Tests for structured progress events (core/progress.py) and their emission.

Covers:
* the emit/parse helpers (sink, explicit stream, env-gated stdout, malformed input);
* media-download progress emission from ``download_all_media``;
* message-fetch progress emission from ``download_chat``;
* the GUI worker turning parsed events into Qt signals (when PySide6 is present).
"""

import asyncio
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from telegram_download_chat.core.media import MediaMixin
from telegram_download_chat.core.progress import (
    PROGRESS_ENV_VAR,
    PROGRESS_PREFIX,
    emit_progress,
    parse_progress_line,
)

# ---------------------------------------------------------------------------
# emit_progress / parse_progress_line
# ---------------------------------------------------------------------------


class TestEmitProgress:
    def test_sink_takes_precedence(self):
        collected = []
        emit_progress({"type": "media", "current": 1}, sink=collected.append)
        assert collected == [{"type": "media", "current": 1}]

    def test_stream_writes_prefixed_json_line(self):
        stream = io.StringIO()
        emit_progress({"type": "messages", "fetched": 5}, stream=stream)
        out = stream.getvalue()
        assert out.startswith(PROGRESS_PREFIX)
        assert out.endswith("\n")
        payload = out[len(PROGRESS_PREFIX) :].strip()
        assert json.loads(payload) == {"type": "messages", "fetched": 5}

    def test_no_sink_no_env_writes_nothing(self, monkeypatch, capsys):
        monkeypatch.delenv(PROGRESS_ENV_VAR, raising=False)
        emit_progress({"type": "media", "current": 1})
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_env_var_enables_stdout(self, monkeypatch, capsys):
        monkeypatch.setenv(PROGRESS_ENV_VAR, "1")
        emit_progress({"type": "media", "current": 2, "total": 4})
        captured = capsys.readouterr()
        assert captured.out.startswith(PROGRESS_PREFIX)
        assert parse_progress_line(captured.out.strip()) == {
            "type": "media",
            "current": 2,
            "total": 4,
        }

    def test_non_ascii_is_preserved(self):
        stream = io.StringIO()
        emit_progress({"type": "media", "file": "файл.pdf"}, stream=stream)
        assert "файл.pdf" in stream.getvalue()


class TestParseProgressLine:
    def test_round_trip(self):
        stream = io.StringIO()
        event = {"type": "media", "current": 3, "total": 9, "file": "images/x.jpg"}
        emit_progress(event, stream=stream)
        assert parse_progress_line(stream.getvalue().strip()) == event

    def test_non_progress_line_returns_none(self):
        assert parse_progress_line("2026-05-30 - INFO - Fetched: 100") is None

    def test_empty_line_returns_none(self):
        assert parse_progress_line("") is None

    def test_malformed_json_returns_none(self):
        assert parse_progress_line(PROGRESS_PREFIX + "{not json}") is None

    def test_non_dict_payload_returns_none(self):
        assert parse_progress_line(PROGRESS_PREFIX + "[1, 2, 3]") is None


# ---------------------------------------------------------------------------
# download_all_media emission
# ---------------------------------------------------------------------------


def _make_media_downloader(events):
    """A minimal MediaMixin instance wired with a progress sink."""
    d = MediaMixin.__new__(MediaMixin)
    d.logger = MagicMock()
    d._stop_requested = False
    d._progress_sink = events.append
    # Skip premium detection + fast-download resolution (cached).
    d._premium_checked = True
    d._is_premium = False
    d._fast_dl_settings = (False, 1, 0)
    # By default treat any present media as downloadable; individual tests
    # override this to exercise the non-downloadable predicate.
    d.get_filename = lambda media: "x.bin"
    return d


@pytest.mark.asyncio
async def test_download_all_media_emits_media_events(tmp_path):
    events = []
    d = _make_media_downloader(events)
    attachments_dir = tmp_path / "attachments"

    async def fake_download(msg, ad):
        mid = msg["id"]
        return ad / "images" / f"{mid}.jpg"

    d.download_message_media = AsyncMock(side_effect=fake_download)

    messages = [
        {"id": 1, "media": object()},
        {"id": 2, "media": object()},
        {"id": 3, "media": object()},
    ]
    await d.download_all_media(messages, attachments_dir)

    media_events = [e for e in events if e.get("type") == "media"]
    assert len(media_events) == 3
    # current counts up to total; total stays constant.
    currents = sorted(e["current"] for e in media_events)
    assert currents == [1, 2, 3]
    assert all(e["total"] == 3 for e in media_events)
    # Each event carries the downloaded file's relative path.
    files = {e["file"] for e in media_events}
    assert files == {"images/1.jpg", "images/2.jpg", "images/3.jpg"}


@pytest.mark.asyncio
async def test_download_all_media_file_none_on_failure(tmp_path):
    events = []
    d = _make_media_downloader(events)
    attachments_dir = tmp_path / "attachments"
    d.download_message_media = AsyncMock(return_value=None)

    await d.download_all_media([{"id": 7, "media": object()}], attachments_dir)

    media_events = [e for e in events if e.get("type") == "media"]
    assert len(media_events) == 1
    assert media_events[0]["file"] is None


@pytest.mark.asyncio
async def test_download_all_media_skips_text_only_messages(tmp_path):
    """Text-only messages must not be counted or emit media progress.

    The total reported to the GUI is media-file progress, so a chat with one
    attachment among many text messages should report 1/1, not 1/N.
    """
    events = []
    d = _make_media_downloader(events)
    attachments_dir = tmp_path / "attachments"

    async def fake_download(msg, ad):
        return ad / "images" / f"{msg['id']}.jpg"

    d.download_message_media = AsyncMock(side_effect=fake_download)

    # One media message buried in text-only messages.
    messages = [{"id": i} for i in range(1, 1000)] + [{"id": 1000, "media": object()}]
    await d.download_all_media(messages, attachments_dir)

    media_events = [e for e in events if e.get("type") == "media"]
    assert len(media_events) == 1
    assert media_events[0]["current"] == 1
    assert media_events[0]["total"] == 1
    # download_message_media is only attempted for the media-carrying message.
    assert d.download_message_media.await_count == 1


@pytest.mark.asyncio
async def test_download_all_media_skips_non_downloadable_media(tmp_path):
    """Messages whose media has no filename must not be counted.

    Non-downloadable previews such as MessageMediaWebPage(WebPageEmpty) carry a
    truthy ``media`` but yield no filename, so the downloader would save nothing.
    They must be excluded from the progress total instead of emitting a bogus
    ``media`` event with ``file: None``.
    """
    events = []
    d = _make_media_downloader(events)
    attachments_dir = tmp_path / "attachments"

    downloadable = object()
    preview = object()

    # Mirror get_filename's real behaviour: only the downloadable media yields a
    # name; the preview returns None.
    d.get_filename = lambda media: "1.jpg" if media is downloadable else None

    async def fake_download(msg, ad):
        return ad / "images" / f"{msg['id']}.jpg"

    d.download_message_media = AsyncMock(side_effect=fake_download)

    messages = [
        {"id": 1, "media": downloadable},
        {"id": 2, "media": preview},
    ]
    await d.download_all_media(messages, attachments_dir)

    media_events = [e for e in events if e.get("type") == "media"]
    assert len(media_events) == 1
    assert media_events[0]["current"] == 1
    assert media_events[0]["total"] == 1
    assert media_events[0]["file"] == "images/1.jpg"
    # The non-downloadable preview is never attempted.
    assert d.download_message_media.await_count == 1


# ---------------------------------------------------------------------------
# download_chat emission
# ---------------------------------------------------------------------------


class _FakeMsg:
    def __init__(self, msg_id, date):
        self.id = msg_id
        self.date = date


class _FakeHistory:
    def __init__(self, messages):
        self.messages = messages


@pytest.mark.asyncio
async def test_download_chat_emits_message_events():
    from telegram_download_chat.core import TelegramChatDownloader

    events = []
    d = TelegramChatDownloader.__new__(TelegramChatDownloader)
    d.logger = MagicMock()
    d._stop_requested = False
    d._stop_file = None
    d._current_entity = None
    d._progress_sink = events.append
    d.get_entity = AsyncMock(return_value=object())

    d1 = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
    batch = _FakeHistory([_FakeMsg(10, d1), _FakeMsg(9, d2)])
    empty = _FakeHistory([])
    d.client = AsyncMock(side_effect=[batch, empty])

    await d.download_chat(
        "chat", request_limit=2, output_file=None, save_partial=False, silent=False
    )

    message_events = [e for e in events if e.get("type") == "messages"]
    assert len(message_events) == 1
    ev = message_events[0]
    assert ev["fetched"] == 2
    # last_date is the oldest (frontier) message of the batch.
    assert ev["last_date"] == d2.isoformat()


@pytest.mark.asyncio
async def test_download_chat_silent_emits_no_events():
    from telegram_download_chat.core import TelegramChatDownloader

    events = []
    d = TelegramChatDownloader.__new__(TelegramChatDownloader)
    d.logger = MagicMock()
    d._stop_requested = False
    d._stop_file = None
    d._current_entity = None
    d._progress_sink = events.append
    d.get_entity = AsyncMock(return_value=object())

    batch = _FakeHistory([_FakeMsg(1, datetime(2026, 1, 1, tzinfo=timezone.utc))])
    empty = _FakeHistory([])
    d.client = AsyncMock(side_effect=[batch, empty])

    await d.download_chat(
        "chat", request_limit=1, output_file=None, save_partial=False, silent=True
    )

    assert [e for e in events if e.get("type") == "messages"] == []


# ---------------------------------------------------------------------------
# GUI worker signal translation
# ---------------------------------------------------------------------------


def test_worker_handles_progress_events():
    pytest.importorskip("PySide6")
    from telegram_download_chat.gui.worker import WorkerThread

    w = WorkerThread([], None)
    media = []
    messages = []
    progress = []
    statuses = []
    w.media_progress.connect(lambda c, t, f: media.append((c, t, f)))
    w.message_progress.connect(lambda f, d: messages.append((f, d)))
    w.progress.connect(lambda c, m: progress.append((c, m)))
    w.status_update.connect(statuses.append)

    w._handle_progress_event(
        {"type": "media", "current": 2, "total": 5, "file": "images/2.jpg"}
    )
    w._handle_progress_event(
        {"type": "messages", "fetched": 100, "last_date": "2026-05-19T12:00:00+00:00"}
    )

    assert media == [(2, 5, "images/2.jpg")]
    assert (2, 5) in progress
    assert messages == [(100, "2026-05-19T12:00:00+00:00")]
    assert any("Downloading media 2/5" == s for s in statuses)
    assert any("up to 2026-05-19" in s for s in statuses)


def test_worker_run_routes_progress_lines(monkeypatch, tmp_path):
    """A subprocess-emitted progress line is parsed, not logged as text."""
    pytest.importorskip("PySide6")
    from telegram_download_chat.gui import worker as worker_mod
    from telegram_download_chat.gui.worker import WorkerThread

    line = (
        PROGRESS_PREFIX
        + json.dumps({"type": "media", "current": 1, "total": 1, "file": "a.jpg"})
        + "\n"
    )

    class _FakeProc:
        def __init__(self):
            self._lines = [line, ""]
            self.stdout = self

        def readline(self):
            return self._lines.pop(0) if self._lines else ""

        def poll(self):
            return None if self._lines else 0

        def __iter__(self):
            return iter([])

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(worker_mod.subprocess, "Popen", lambda *a, **k: _FakeProc())

    w = WorkerThread(["chat"], None)
    logs = []
    media = []
    w.log.connect(logs.append)
    w.media_progress.connect(lambda c, t, f: media.append((c, t, f)))
    # Avoid scanning a large downloads dir; use an empty temp dir.
    w.output_dir = str(tmp_path)

    w.run()

    assert media == [(1, 1, "a.jpg")]
    # The raw sentinel line must not appear in the log output.
    assert not any(PROGRESS_PREFIX in m for m in logs)

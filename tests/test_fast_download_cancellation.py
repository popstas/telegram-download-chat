"""Tests for fast_download cancellation / timeout safety.

These cover the freeze scenario from `--media` where Telegram closes the
auxiliary download sockets and Telethon's reconnect loop spins on an
AttributeError race, hanging the per-chunk request forever.
"""

import asyncio
import logging
import time
from unittest.mock import MagicMock

import pytest

from telegram_download_chat.core import fast_download
from telegram_download_chat.core.fast_download import (
    DownloadSender,
    FastDownloadStalled,
    ParallelTransferrer,
    _ReconnectAttrErrorFilter,
    _ServerClosedRewriteFilter,
)
from telegram_download_chat.core.media import MediaMixin


@pytest.mark.asyncio
async def test_chunk_timeout_raises_fast_download_stalled(monkeypatch):
    """A request that never returns must surface FastDownloadStalled quickly."""
    monkeypatch.setattr(fast_download, "_CHUNK_TIMEOUT_SECONDS", 0.2)

    class HangingClient:
        async def _call(self, sender, request):
            await asyncio.sleep(10)  # would block forever without wait_for

    sender = DownloadSender(
        client=HangingClient(),
        sender=object(),
        file=object(),
        offset=0,
        limit=1024,
        stride=1024,
        count=5,
    )

    started = time.monotonic()
    with pytest.raises(FastDownloadStalled):
        await sender.next()
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"timeout took too long: {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_cleanup_orphans_stuck_disconnects(monkeypatch):
    """If sender.disconnect() hangs, _cleanup must bail out, not freeze."""
    monkeypatch.setattr(fast_download, "_CLEANUP_TIMEOUT_SECONDS", 0.2)

    class StuckSender:
        async def disconnect(self):
            await asyncio.sleep(10)

    transferrer = ParallelTransferrer.__new__(ParallelTransferrer)
    transferrer.senders = [StuckSender(), StuckSender(), StuckSender()]
    transferrer._log_filters = []

    started = time.monotonic()
    await transferrer._cleanup()
    elapsed = time.monotonic() - started

    assert transferrer.senders is None
    assert elapsed < 2.0, f"cleanup took too long: {elapsed:.2f}s"


def test_reconnect_attrerror_filter_drops_matching_records():
    f = _ReconnectAttrErrorFilter()
    logger = logging.getLogger("test.fast_download.filter")
    record = logger.makeRecord(
        name=logger.name,
        level=logging.ERROR,
        fn=__file__,
        lno=0,
        msg="Unexpected exception reconnecting on attempt 3",
        args=(),
        exc_info=(
            AttributeError,
            AttributeError("'NoneType' object has no attribute 'connect'"),
            None,
        ),
    )
    assert f.filter(record) is False
    assert f.warned is True

    # Same again — already warned, still dropped, no second warning.
    record2 = logger.makeRecord(
        name=logger.name,
        level=logging.ERROR,
        fn=__file__,
        lno=0,
        msg="Unexpected exception reconnecting on attempt 4",
        args=(),
        exc_info=(
            AttributeError,
            AttributeError("'NoneType' object has no attribute 'connect'"),
            None,
        ),
    )
    assert f.filter(record2) is False


def test_reconnect_attrerror_filter_lets_unrelated_records_through():
    f = _ReconnectAttrErrorFilter()
    logger = logging.getLogger("test.fast_download.filter")

    # Different message
    record = logger.makeRecord(
        name=logger.name,
        level=logging.ERROR,
        fn=__file__,
        lno=0,
        msg="Some other telethon error",
        args=(),
        exc_info=(
            AttributeError,
            AttributeError("'NoneType' object has no attribute 'connect'"),
            None,
        ),
    )
    assert f.filter(record) is True

    # Right message, but different exception type
    record = logger.makeRecord(
        name=logger.name,
        level=logging.ERROR,
        fn=__file__,
        lno=0,
        msg="Unexpected exception reconnecting on attempt 1",
        args=(),
        exc_info=(ValueError, ValueError("something else"), None),
    )
    assert f.filter(record) is True


def test_server_closed_rewrite_filter_rewrites_message():
    f = _ServerClosedRewriteFilter()
    logger = logging.getLogger("test.fast_download.connection")
    record = logger.makeRecord(
        name=logger.name,
        level=logging.WARNING,
        fn=__file__,
        lno=0,
        msg="Server closed the connection: %s",
        args=("0 bytes read on a total of 8 expected bytes",),
        exc_info=None,
    )
    # Record is kept, but its rendered message is rewritten in place.
    assert f.filter(record) is True
    assert record.getMessage() == "Rate limited by Telegram, retrying…"


def test_server_closed_rewrite_filter_leaves_unrelated_records():
    f = _ServerClosedRewriteFilter()
    logger = logging.getLogger("test.fast_download.connection")
    record = logger.makeRecord(
        name=logger.name,
        level=logging.WARNING,
        fn=__file__,
        lno=0,
        msg="Connecting to %s...",
        args=("dc 2",),
        exc_info=None,
    )
    assert f.filter(record) is True
    assert record.getMessage() == "Connecting to dc 2..."


def _make_throttle_downloader(connections: int) -> MediaMixin:
    """A minimal MediaMixin instance wired for thread-backoff tests."""
    d = MediaMixin.__new__(MediaMixin)
    d.logger = MagicMock()
    d._current_connections = connections
    d._threads_lock = asyncio.Lock()
    return d


@pytest.mark.asyncio
async def test_reduce_threads_halves_and_logs():
    d = _make_throttle_downloader(4)
    await d._reduce_threads_on_throttle(4)
    assert d._current_connections == 2
    d.logger.warning.assert_called_once_with("Decrease threads to %d", 2)


@pytest.mark.asyncio
async def test_reduce_threads_ignores_stale_generation():
    d = _make_throttle_downloader(4)
    await d._reduce_threads_on_throttle(4)  # 4 -> 2
    d.logger.warning.reset_mock()

    # A straggler that started at 4 must not trigger a second halving.
    await d._reduce_threads_on_throttle(4)
    assert d._current_connections == 2
    d.logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_reduce_threads_floors_at_one():
    d = _make_throttle_downloader(2)
    await d._reduce_threads_on_throttle(2)  # 2 -> 1
    assert d._current_connections == 1

    # Already at the floor: no further change, no log.
    d.logger.warning.reset_mock()
    await d._reduce_threads_on_throttle(1)
    assert d._current_connections == 1
    d.logger.warning.assert_not_called()

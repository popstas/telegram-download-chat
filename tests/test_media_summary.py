"""Tests for the post-``--media`` download summary.

Covers the ``MediaStats`` counters threaded through ``download_all_media``:
size/speed/cached breakdown and the retry-stats counters (expired-reference
refetch+retry and fast-download fallback to the single-stream downloader).
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon.errors import FileReferenceExpiredError

from telegram_download_chat.core.fast_download import FastDownloadStalled
from telegram_download_chat.core.media import MediaMixin, MediaStats


def _make_media_mixin() -> MediaMixin:
    """A minimal MediaMixin instance without running heavy __init__."""
    d = MediaMixin.__new__(MediaMixin)
    d.logger = MagicMock()
    d.client = MagicMock()
    d._current_entity = None
    d._stop_requested = False
    d._progress_sink = None
    d._premium_checked = True
    d._is_premium = False
    d._fast_dl_settings = (False, 1, 0)
    # Treat any present media as downloadable by default; download_message_media
    # tests below override this with their own stub.
    d.get_filename = lambda media: "x.bin"
    return d


# ---------------------------------------------------------------------------
# MediaStats value object
# ---------------------------------------------------------------------------


class TestMediaStats:
    def test_totals(self):
        s = MediaStats(
            downloaded_files=3,
            downloaded_bytes=3000,
            cached_files=2,
            cached_bytes=2000,
        )
        assert s.total_files == 5
        assert s.total_bytes == 5000

    def test_speed_excludes_cached_and_uses_downloaded_bytes(self):
        s = MediaStats(downloaded_bytes=10 * 1024 * 1024, elapsed_seconds=2.0)
        assert s.speed_mbps == pytest.approx(5.0)

    def test_speed_zero_when_no_time_or_bytes(self):
        assert MediaStats(downloaded_bytes=1000, elapsed_seconds=0).speed_mbps == 0.0
        assert MediaStats(downloaded_bytes=0, elapsed_seconds=5).speed_mbps == 0.0

    def test_to_event_shape(self):
        s = MediaStats(
            downloaded_files=1,
            downloaded_bytes=1024 * 1024,
            cached_files=1,
            cached_bytes=2048,
            failed_files=1,
            expired_reference_retries=2,
            fast_download_fallbacks=3,
            elapsed_seconds=1.0,
        )
        ev = s.to_event()
        assert ev["type"] == "media_summary"
        assert ev["total_files"] == 2
        assert ev["downloaded_files"] == 1
        assert ev["cached_files"] == 1
        assert ev["total_bytes"] == 1024 * 1024 + 2048
        assert ev["failed_files"] == 1
        assert ev["expired_reference_retries"] == 2
        assert ev["fast_download_fallbacks"] == 3
        assert ev["speed_mbps"] == pytest.approx(1.0)

    def test_summary_line_includes_retries_only_when_present(self):
        quiet = MediaStats(downloaded_files=2, downloaded_bytes=2048)
        assert "Retries" not in quiet.summary_line()

        noisy = MediaStats(
            downloaded_files=1,
            downloaded_bytes=1024,
            expired_reference_retries=1,
            fast_download_fallbacks=2,
            failed_files=1,
            elapsed_seconds=1.0,
        )
        line = noisy.summary_line()
        assert "1 expired-reference" in line
        assert "2 fast-download fallback" in line
        assert "1 failed" in line


# ---------------------------------------------------------------------------
# download_message_media recording (cached / downloaded / failed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_records_cached_file(tmp_path):
    d = _make_media_mixin()
    d._media_stats = MediaStats()
    d.get_filename = lambda media: "x.bin"
    d._get_media_category = lambda media: "documents"

    ad = tmp_path / "attachments"
    existing = ad / "documents" / "5_x.bin"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"a" * 2048)

    result = await d.download_message_media({"id": 5, "media": {"k": 1}}, ad)

    assert result == existing
    assert d._media_stats.cached_files == 1
    assert d._media_stats.cached_bytes == 2048
    assert d._media_stats.downloaded_files == 0


@pytest.mark.asyncio
async def test_records_downloaded_file(tmp_path):
    d = _make_media_mixin()
    d._media_stats = MediaStats()
    d.get_filename = lambda media: "y.bin"
    d._get_media_category = lambda media: "documents"

    def fake_synth(media, target):
        target.write_bytes(b"z" * 4096)
        return True

    d._serialize_synthetic_media = fake_synth

    ad = tmp_path / "attachments"
    await d.download_message_media({"id": 6, "media": {"k": 1}}, ad)

    assert d._media_stats.downloaded_files == 1
    assert d._media_stats.downloaded_bytes == 4096
    assert d._media_stats.cached_files == 0


@pytest.mark.asyncio
async def test_records_failed_file(tmp_path):
    d = _make_media_mixin()
    d._media_stats = MediaStats()
    d.get_filename = lambda media: "y.bin"
    d._get_media_category = lambda media: "documents"
    d._serialize_synthetic_media = lambda media, target: False
    d._download_binary_media = AsyncMock(return_value=None)

    ad = tmp_path / "attachments"
    result = await d.download_message_media({"id": 7, "media": {"k": 1}}, ad)

    assert result is None
    assert d._media_stats.failed_files == 1
    assert d._media_stats.downloaded_files == 0


# ---------------------------------------------------------------------------
# Retry counters: fast-download fallback + expired-reference refetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fast_download_fallback_counted(tmp_path, monkeypatch):
    d = _make_media_mixin()
    d._media_stats = MediaStats()
    # Fast path enabled, threshold 0 so any size qualifies.
    d._fast_dl_settings = (True, 4, 0)
    d._resolve_fast_download_settings = MagicMock(return_value=(True, 4, 0))
    d._extract_binary_object = MagicMock(return_value=(object(), 10_000_000))
    d._current_connections = 4
    d._threads_lock = asyncio.Lock()

    async def boom(*args, **kwargs):
        raise FastDownloadStalled("stall")

    monkeypatch.setattr("telegram_download_chat.core.media.fast_download_file", boom)

    download_to = tmp_path / "f.bin"

    async def fake_standard(message, file):
        Path(file).write_bytes(b"x" * 128)
        return str(file)

    d.client.download_media = AsyncMock(side_effect=fake_standard)

    result = await d._download_binary_media(object(), object(), download_to, "5")

    assert result == download_to
    assert d._media_stats.fast_download_fallbacks == 1
    assert d._media_stats.expired_reference_retries == 0


@pytest.mark.asyncio
async def test_expired_reference_retry_counted(tmp_path):
    d = _make_media_mixin()
    d._media_stats = MediaStats()
    d._resolve_fast_download_settings = MagicMock(return_value=(False, 1, 0))
    d._extract_binary_object = MagicMock(return_value=(None, None))

    fresh = MagicMock()
    fresh.media = object()
    d._refetch_message = AsyncMock(return_value=fresh)

    download_to = tmp_path / "f.bin"
    message = MagicMock()
    message.peer_id = object()

    d.client.download_media = AsyncMock(
        side_effect=[FileReferenceExpiredError(request=None), str(download_to)]
    )

    result = await d._download_binary_media(message, object(), download_to, "55")

    assert result == download_to
    assert d._media_stats.expired_reference_retries == 1
    assert d._media_stats.fast_download_fallbacks == 0


# ---------------------------------------------------------------------------
# download_all_media end-to-end summary emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_all_media_emits_summary(tmp_path):
    events = []
    d = _make_media_mixin()
    d._progress_sink = events.append
    ad = tmp_path / "attachments"

    async def fake_download(msg, attachments_dir):
        # Simulate the per-file recording the real path would do.
        d._media_stats.downloaded_files += 1
        d._media_stats.downloaded_bytes += 1000
        return attachments_dir / "images" / f"{msg['id']}.jpg"

    d.download_message_media = AsyncMock(side_effect=fake_download)

    await d.download_all_media(
        [
            {"id": 1, "media": {"k": 1}},
            {"id": 2, "media": {"k": 1}},
            {"id": 3, "media": {"k": 1}},
        ],
        ad,
    )

    summaries = [e for e in events if e.get("type") == "media_summary"]
    assert len(summaries) == 1
    ev = summaries[0]
    assert ev["downloaded_files"] == 3
    assert ev["total_files"] == 3
    assert ev["downloaded_bytes"] == 3000
    assert d._media_stats.elapsed_seconds >= 0


@pytest.mark.asyncio
async def test_download_all_media_resets_stats_between_runs(tmp_path):
    d = _make_media_mixin()
    ad = tmp_path / "attachments"

    async def fake_download(msg, attachments_dir):
        d._media_stats.cached_files += 1
        return None

    d.download_message_media = AsyncMock(side_effect=fake_download)

    await d.download_all_media([{"id": 1, "media": {"k": 1}}], ad)
    assert d._media_stats.cached_files == 1
    # Second run starts from a clean slate.
    await d.download_all_media(
        [{"id": 2, "media": {"k": 1}}, {"id": 3, "media": {"k": 1}}], ad
    )
    assert d._media_stats.cached_files == 2


# ---------------------------------------------------------------------------
# GUI worker consumption of the summary event
# ---------------------------------------------------------------------------


def test_worker_handles_media_summary_event():
    pytest.importorskip("PySide6")
    from telegram_download_chat.gui.worker import WorkerThread

    w = WorkerThread([], None)
    summaries = []
    statuses = []
    w.media_summary.connect(summaries.append)
    w.status_update.connect(statuses.append)

    event = {
        "type": "media_summary",
        "total_files": 5,
        "downloaded_files": 3,
        "cached_files": 2,
        "total_bytes": 5 * 1024 * 1024,
        "speed_mbps": 2.5,
    }
    w._handle_progress_event(event)

    assert summaries == [event]
    assert any("5 files" in s and "5.0 MB" in s for s in statuses)
    assert any("2.50 MB/s" in s for s in statuses)

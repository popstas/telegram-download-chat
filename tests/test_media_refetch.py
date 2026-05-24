"""Tests for expired-file-reference recovery in MediaMixin.

Cover the standard-downloader retry path: when a stale file reference raises
``FileReferenceExpiredError``, the message is refetched by id for a fresh
reference and the download is retried once.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon.errors import FileReferenceExpiredError

from telegram_download_chat.core.media import MediaMixin


def _make_media_mixin() -> MediaMixin:
    """A minimal MediaMixin instance without running heavy __init__."""
    d = MediaMixin.__new__(MediaMixin)
    d.logger = MagicMock()
    d.client = MagicMock()
    d._current_entity = None
    return d


@pytest.mark.asyncio
async def test_refetch_message_uses_current_entity():
    d = _make_media_mixin()
    d._current_entity = object()
    fresh = MagicMock()
    fresh.media = object()
    d.client.get_messages = AsyncMock(return_value=fresh)

    result = await d._refetch_message(MagicMock(), "42")

    assert result is fresh
    d.client.get_messages.assert_awaited_once_with(d._current_entity, ids=42)


@pytest.mark.asyncio
async def test_refetch_message_returns_none_without_entity_or_peer():
    d = _make_media_mixin()
    message = MagicMock()
    message.peer_id = None
    d.client.get_messages = AsyncMock()

    result = await d._refetch_message(message, "42")

    assert result is None
    d.client.get_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_refetch_message_falls_back_to_peer_id():
    d = _make_media_mixin()
    peer = object()
    message = MagicMock()
    message.peer_id = peer
    fresh = MagicMock()
    fresh.media = object()
    d.client.get_messages = AsyncMock(return_value=fresh)

    result = await d._refetch_message(message, "7")

    assert result is fresh
    d.client.get_messages.assert_awaited_once_with(peer, ids=7)


@pytest.mark.asyncio
async def test_refetch_message_returns_none_when_no_media():
    d = _make_media_mixin()
    d._current_entity = object()
    fresh = MagicMock()
    fresh.media = None
    d.client.get_messages = AsyncMock(return_value=fresh)

    result = await d._refetch_message(MagicMock(), "9")

    assert result is None


@pytest.mark.asyncio
async def test_refetch_message_accepts_matching_media_identity():
    d = _make_media_mixin()
    d._current_entity = object()
    original = MagicMock()
    original.media = object()
    fresh = MagicMock()
    fresh.media = object()
    d.client.get_messages = AsyncMock(return_value=fresh)
    # Same underlying document/photo id on both sides.
    d._extract_binary_object = MagicMock(return_value=(MagicMock(id=111), 10))

    result = await d._refetch_message(original, "42")

    assert result is fresh


@pytest.mark.asyncio
async def test_refetch_message_rejects_changed_media_identity():
    d = _make_media_mixin()
    d._current_entity = object()
    original = MagicMock()
    original.media = object()
    fresh = MagicMock()
    fresh.media = object()
    d.client.get_messages = AsyncMock(return_value=fresh)
    # Original document id 111, refetched message now carries a different id 222.
    d._extract_binary_object = MagicMock(
        side_effect=[(MagicMock(id=111), 10), (MagicMock(id=222), 10)]
    )

    result = await d._refetch_message(original, "42")

    assert result is None


@pytest.mark.asyncio
async def test_refetch_message_returns_none_on_failure():
    d = _make_media_mixin()
    d._current_entity = object()
    d.client.get_messages = AsyncMock(side_effect=RuntimeError("boom"))

    result = await d._refetch_message(MagicMock(), "9")

    assert result is None


@pytest.mark.asyncio
async def test_standard_path_retries_after_expired_reference(tmp_path, monkeypatch):
    d = _make_media_mixin()
    d._current_entity = object()
    # Disable fast path so we go straight to the standard downloader.
    d._resolve_fast_download_settings = MagicMock(return_value=(False, 1, 0))
    d._extract_binary_object = MagicMock(return_value=(None, None))

    fresh = MagicMock()
    fresh.media = object()
    d._refetch_message = AsyncMock(return_value=fresh)

    download_to = tmp_path / "file.bin"
    message = MagicMock()
    message.peer_id = object()

    d.client.download_media = AsyncMock(
        side_effect=[FileReferenceExpiredError(request=None), str(download_to)]
    )

    result = await d._download_binary_media(message, object(), download_to, "55")

    assert result == download_to
    assert d.client.download_media.await_count == 2
    # Second call must use the refetched message.
    second_call = d.client.download_media.await_args_list[1]
    assert second_call.args[0] is fresh
    d._refetch_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_standard_path_propagates_when_refetch_fails(tmp_path):
    d = _make_media_mixin()
    d._resolve_fast_download_settings = MagicMock(return_value=(False, 1, 0))
    d._extract_binary_object = MagicMock(return_value=(None, None))
    d._refetch_message = AsyncMock(return_value=None)

    download_to = tmp_path / "file.bin"
    message = MagicMock()

    d.client.download_media = AsyncMock(
        side_effect=FileReferenceExpiredError(request=None)
    )

    with pytest.raises(FileReferenceExpiredError):
        await d._download_binary_media(message, object(), download_to, "55")

    d._refetch_message.assert_awaited_once()
    assert d.client.download_media.await_count == 1

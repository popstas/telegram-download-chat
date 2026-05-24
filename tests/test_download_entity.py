"""Tests that download_chat stores the resolved entity for later refetch."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from telegram_download_chat.core.download import DownloadMixin


def _make_download_mixin() -> DownloadMixin:
    """Build a minimal DownloadMixin without running heavy __init__."""
    d = DownloadMixin.__new__(DownloadMixin)
    d.logger = MagicMock()
    d._stop_requested = False
    d._stop_file = None
    d._current_entity = None
    return d


def test_current_entity_defaults_to_none():
    d = _make_download_mixin()
    assert d._current_entity is None


@pytest.mark.asyncio
async def test_download_chat_stores_current_entity():
    d = _make_download_mixin()

    entity = MagicMock(name="entity")
    d.get_entity = AsyncMock(return_value=entity)

    # client() (GetHistoryRequest) returns history with no messages -> loop exits
    history = MagicMock()
    history.messages = []
    d.client = AsyncMock(return_value=history)

    result = await d.download_chat("some_chat", save_partial=False, silent=True)

    assert result == []
    d.get_entity.assert_awaited_once_with("some_chat")
    assert d._current_entity is entity

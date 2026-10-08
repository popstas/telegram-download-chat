"""QR login: token refresh loop, 2FA branch, and rendering helpers."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon.errors import SessionPasswordNeededError

from telegram_download_chat.core.qr_login import (
    QrLoginTimeout,
    qr_code_matrix,
    qr_login,
    render_qr_ascii,
)


def _qr(url="tg://login?token=abc"):
    qr = MagicMock()
    qr.url = url
    qr.recreate = AsyncMock()
    qr.wait = AsyncMock()
    return qr


def _client(qr):
    client = MagicMock()
    client.qr_login = AsyncMock(return_value=qr)
    client.sign_in = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_returns_user_when_scanned():
    user = MagicMock(username="popstas")
    qr = _qr()
    qr.wait = AsyncMock(return_value=user)
    shown = []

    assert await qr_login(_client(qr), on_code=shown.append) is user
    assert shown == ["tg://login?token=abc"]


@pytest.mark.asyncio
async def test_expired_token_is_recreated_and_shown_again():
    user = MagicMock()
    qr = _qr()
    qr.wait = AsyncMock(side_effect=[asyncio.TimeoutError(), user])
    shown = []

    assert await qr_login(_client(qr), on_code=shown.append) is user
    qr.recreate.assert_awaited_once()
    assert len(shown) == 2


@pytest.mark.asyncio
async def test_gives_up_after_the_deadline():
    qr = _qr()
    qr.wait = AsyncMock(side_effect=asyncio.TimeoutError())

    with pytest.raises(QrLoginTimeout):
        await qr_login(_client(qr), on_code=lambda url: None, timeout=0)

    assert qr.recreate.await_count == 0


@pytest.mark.asyncio
async def test_two_factor_password_is_requested_and_used():
    user = MagicMock()
    qr = _qr()
    qr.wait = AsyncMock(side_effect=SessionPasswordNeededError(request=None))
    client = _client(qr)
    client.sign_in = AsyncMock(return_value=user)

    result = await qr_login(
        client, on_code=lambda url: None, password=lambda: "hunter2"
    )

    assert result is user
    client.sign_in.assert_awaited_once_with(password="hunter2")


@pytest.mark.asyncio
async def test_two_factor_without_a_password_callback_raises():
    qr = _qr()
    qr.wait = AsyncMock(side_effect=SessionPasswordNeededError(request=None))

    with pytest.raises(SessionPasswordNeededError):
        await qr_login(_client(qr), on_code=lambda url: None)


def test_matrix_is_square_and_has_dark_modules():
    matrix = qr_code_matrix("tg://login?token=abc")

    assert len(matrix) >= 21
    assert all(len(row) == len(matrix) for row in matrix)
    assert any(any(row) for row in matrix)


def test_ascii_render_is_blocky_and_fits_the_matrix():
    art = render_qr_ascii("tg://login?token=abc")
    lines = art.splitlines()

    assert len(lines) > 10
    assert len(set(len(line) for line in lines)) == 1
    assert set(art) <= {"\n", " ", "█", "▀", "▄"}


def test_ansi_render_pins_colors_so_the_terminal_theme_cannot_invert_it():
    from telegram_download_chat.core.qr_login import render_qr_ansi

    plain = render_qr_ascii("tg://login?token=abc").splitlines()
    colored = render_qr_ansi("tg://login?token=abc").splitlines()

    assert len(colored) == len(plain)
    assert all(line.startswith("\x1b[30;107m") for line in colored)
    assert all(line.endswith("\x1b[0m") for line in colored)

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


@pytest.mark.asyncio
async def test_wrong_password_is_asked_again():
    """Telethon's own code login retries the password; the QR path must too."""
    from telethon.errors import PasswordHashInvalidError

    from telegram_download_chat.core.qr_login import qr_login as login

    user = MagicMock(username="popstas")
    qr = _qr()
    qr.wait = AsyncMock(side_effect=SessionPasswordNeededError(request=None))
    client = _client(qr)
    client.sign_in = AsyncMock(
        side_effect=[PasswordHashInvalidError(request=None), user]
    )
    typed = iter(["wrong", "right"])
    complaints = []

    result = await login(
        client,
        on_code=lambda url: None,
        password=lambda: next(typed),
        password_attempts=3,
        on_password_error=complaints.append,
    )

    assert result is user
    assert client.sign_in.await_count == 2
    assert len(complaints) == 1 and "password" in complaints[0].lower()


@pytest.mark.asyncio
async def test_exhausted_password_attempts_raise_a_readable_error():
    from telethon.errors import PasswordHashInvalidError

    from telegram_download_chat.core.qr_login import QrLoginError
    from telegram_download_chat.core.qr_login import qr_login as login

    qr = _qr()
    qr.wait = AsyncMock(side_effect=SessionPasswordNeededError(request=None))
    client = _client(qr)
    client.sign_in = AsyncMock(side_effect=PasswordHashInvalidError(request=None))

    with pytest.raises(QrLoginError) as excinfo:
        await login(
            client,
            on_code=lambda url: None,
            password=lambda: "wrong",
            password_attempts=2,
        )

    assert client.sign_in.await_count == 2
    message = str(excinfo.value)
    assert "password" in message.lower()
    assert "hash" not in message.lower()  # not Telethon's raw wording


@pytest.mark.asyncio
async def test_a_single_attempt_is_the_default_for_a_stored_password():
    """The GUI hands over one fixed value, so re-asking would just repeat it."""
    from telethon.errors import PasswordHashInvalidError

    from telegram_download_chat.core.qr_login import QrLoginError
    from telegram_download_chat.core.qr_login import qr_login as login

    qr = _qr()
    qr.wait = AsyncMock(side_effect=SessionPasswordNeededError(request=None))
    client = _client(qr)
    client.sign_in = AsyncMock(side_effect=PasswordHashInvalidError(request=None))

    with pytest.raises(QrLoginError):
        await login(client, on_code=lambda url: None, password=lambda: "wrong")

    assert client.sign_in.await_count == 1


def test_timeout_is_a_qr_login_error():
    from telegram_download_chat.core.qr_login import QrLoginError

    assert issubclass(QrLoginTimeout, QrLoginError)

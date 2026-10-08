"""QR code login.

Telegram delivers login codes to third-party clients only in limited ways, and
some accounts never receive one (issue #91). A QR code is confirmed from an
already-logged-in Telegram app instead, so it works whatever Telegram decides
about SMS. Telethon exposes the protocol via ``client.qr_login()``; this module
adds the token refresh loop, the 2FA branch and the rendering shared by the CLI
and the GUI.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Optional, Union

from telethon.errors import SessionPasswordNeededError

logger = logging.getLogger(__name__)

# Login tokens are short-lived; Telegram currently expires them after ~30 s.
DEFAULT_TOKEN_TTL_SECONDS = 30.0
# How long the whole login may take before giving up on the user scanning.
DEFAULT_TIMEOUT_SECONDS = 300.0

QR_INSTALL_HINT = (
    "QR login needs the 'qrcode' package: pip install -U telegram-download-chat"
)


class QrLoginTimeout(TimeoutError):
    """The QR code was never scanned within the allotted time."""


def qr_code_matrix(data: str) -> List[List[bool]]:
    """Encode ``data`` as a QR code matrix of dark/light modules."""
    try:
        import qrcode
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise RuntimeError(QR_INSTALL_HINT) from e

    code = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
    code.add_data(data)
    code.make(fit=True)
    return [[bool(module) for module in row] for row in code.get_matrix()]


def render_qr_ascii(data: str, *, invert: bool = False) -> str:
    """Render a QR code as text, two module rows per line of half blocks.

    By default dark modules are drawn as filled blocks, which scans on a light
    terminal background. ``invert`` swaps them for a dark background.
    """
    matrix = qr_code_matrix(data)
    glyphs = {(True, True): "█", (True, False): "▀", (False, True): "▄"}
    lines = []
    for top in range(0, len(matrix), 2):
        bottom_row = matrix[top + 1] if top + 1 < len(matrix) else [False] * len(matrix)
        line = []
        for upper, lower in zip(matrix[top], bottom_row):
            if invert:
                upper, lower = not upper, not lower
            line.append(glyphs.get((upper, lower), " "))
        lines.append("".join(line))
    return "\n".join(lines)


def render_qr_ansi(data: str) -> str:
    """Render the QR code with explicit colors, so the terminal theme can't flip it.

    Drawn as black modules on a white background: a light-on-dark terminal
    would otherwise render an inverted code that scanners may reject.
    """
    black_on_white = "\x1b[30;107m"
    reset = "\x1b[0m"
    return "\n".join(
        f"{black_on_white}{line}{reset}" for line in render_qr_ascii(data).splitlines()
    )


def _token_ttl(qr_login_obj) -> float:
    """Seconds until the current token expires, falling back to the default."""
    expires = getattr(qr_login_obj, "expires", None)
    try:
        return max((expires - datetime.now(timezone.utc)).total_seconds(), 1.0)
    except Exception:
        return DEFAULT_TOKEN_TTL_SECONDS


async def _resolve(value: Union[str, Awaitable[str]]) -> str:
    if inspect.isawaitable(value):
        return await value
    return value


async def qr_login(
    client,
    *,
    on_code: Callable[[str], None],
    password: Optional[Callable[[], Union[str, Awaitable[str]]]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
):
    """Log in by QR code, refreshing the code until it is scanned.

    Args:
        client: A connected, unauthorized Telethon client.
        on_code: Called with the ``tg://login`` URL each time a code is issued,
            so the caller can draw it. Called again after every refresh.
        password: Returns the 2FA password; required only for accounts that
            have one. May be async.
        timeout: Overall budget, in seconds, for the user to scan the code.

    Returns:
        The logged-in Telethon ``User``.

    Raises:
        QrLoginTimeout: The code was not scanned in time.
        SessionPasswordNeededError: 2FA is on and no ``password`` was given.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    qr = await client.qr_login()

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise QrLoginTimeout(
                "The QR code was not scanned in time. Please try logging in again."
            )

        on_code(qr.url)
        logger.debug(f"Waiting for the QR code to be scanned ({remaining:.0f}s left)")

        try:
            return await qr.wait(timeout=min(remaining, _token_ttl(qr)))
        except asyncio.TimeoutError:
            if deadline - loop.time() <= 0:
                raise QrLoginTimeout(
                    "The QR code was not scanned in time. Please try logging in again."
                )
            logger.debug("QR token expired, requesting a new one")
            await qr.recreate()
        except SessionPasswordNeededError:
            if password is None:
                raise
            logger.debug("QR scan accepted, 2FA password required")
            return await client.sign_in(password=await _resolve(password()))

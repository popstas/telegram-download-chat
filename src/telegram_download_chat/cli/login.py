"""The `login` command: the only place the CLI asks the user anything.

Downloads must never prompt — the GUI runs them as a subprocess without stdin,
where a prompt crashes with "lost sys.stdin" (issue #91). Logging in therefore
got its own command, with the QR flow as an alternative for accounts Telegram
never sends a code to.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
from dataclasses import dataclass
from typing import List, Optional

from telegram_download_chat.core import TelegramChatDownloader
from telegram_download_chat.core.qr_login import (
    QrLoginTimeout,
    qr_login,
    render_qr_ansi,
    render_qr_ascii,
)


@dataclass
class LoginOptions:
    qr: bool = False
    debug: bool = False
    config: Optional[str] = None
    proxy_url: Optional[str] = None


def parse_login_args(argv: List[str]) -> LoginOptions:
    """Parse the arguments of `telegram-download-chat login`."""
    parser = argparse.ArgumentParser(
        prog="telegram-download-chat login",
        description="Log in to Telegram and store the session",
    )
    parser.add_argument(
        "--qr",
        action="store_true",
        help="Log in by scanning a QR code from an app where you are logged in",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--config", help="Path to config file")
    parser.add_argument("--proxy-url", dest="proxy_url", help="Proxy URL")
    args = parser.parse_args(argv)
    return LoginOptions(
        qr=args.qr, debug=args.debug, config=args.config, proxy_url=args.proxy_url
    )


def _describe(user) -> str:
    return getattr(user, "username", None) or str(
        getattr(user, "phone", None) or getattr(user, "id", "")
    )


class NoTerminalError(RuntimeError):
    """A prompt is needed but there is no terminal to read the answer from."""


_GUI_HINT = "or log in on the Settings tab of the GUI"


def _prompt_phone() -> str:
    """Ask for the phone number, refusing to do so without a terminal."""
    if sys.stdin is None or not sys.stdin.isatty():
        raise NoTerminalError(
            "Cannot ask for the phone number: this command is not running in a "
            f"terminal. Run it in a real terminal, {_GUI_HINT}."
        )
    return input("Please enter your phone: ")


def _prompt_code() -> str:
    """Ask for the login code.

    Telethon's ``start()`` prompts for it with a plain ``input()`` when no
    ``code_callback`` is given, which dies with ``EOFError`` *after* the code
    request has already been sent.
    """
    if sys.stdin is None or not sys.stdin.isatty():
        raise NoTerminalError(
            "Cannot ask for the login code: this command is not running in a "
            f"terminal. Run it in a real terminal, {_GUI_HINT}."
        )
    return input("Please enter the code you received: ")


def _prompt_password() -> str:
    """Ask for the 2FA password.

    Without a terminal ``getpass`` either echoes the password or dies with a
    bare ``EOFError`` (seen when the QR scan was accepted and 2FA kicked in),
    so say what to do instead of leaking or crashing.
    """
    if sys.stdin is None or not sys.stdin.isatty():
        raise NoTerminalError(
            "Two-step verification is enabled, but there is no terminal to read "
            "the password from. Run this command in a real terminal, "
            f"{_GUI_HINT} (type the password into the Password field first)."
        )
    return getpass.getpass("Two-step verification password: ")


def _ansi_supported() -> bool:
    """Whether the console renders ANSI colors rather than printing them raw."""
    if not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return True
    # Legacy conhost needs virtual terminal processing turned on first.
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        return bool(
            kernel32.SetConsoleMode(
                handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            )
        )
    except Exception:
        return False


def _print_qr(url: str) -> None:
    """Draw the QR code, with the URL as a fallback for terminals that mangle it."""
    print()
    print(render_qr_ansi(url) if _ansi_supported() else render_qr_ascii(url))
    print()
    print("Scan it in Telegram: Settings -> Devices -> Link Desktop Device")
    print(f"Or open this link on a logged-in device: {url}")
    print("Waiting for the code to be scanned...", flush=True)


async def run_login(
    *,
    qr: bool = False,
    config: Optional[str] = None,
    debug: bool = False,
    proxy_url: Optional[str] = None,
) -> int:
    """Log in interactively and store the session. Returns an exit code."""
    downloader = TelegramChatDownloader(config_path=config)
    if debug:
        downloader.logger.setLevel(logging.DEBUG)
    if proxy_url:
        downloader.config.setdefault("settings", {})["proxy_url"] = proxy_url

    try:
        if await downloader.prepare_client():
            me = await downloader.client.get_me()
            print(f"Already logged in as {_describe(me)}")
            return 0

        if qr:
            user = await qr_login(
                downloader.client,
                on_code=_print_qr,
                password=_prompt_password,
            )
        else:
            phone = downloader.config.get("settings", {}).get("phone")
            await downloader.client.start(
                phone=phone or _prompt_phone,
                code_callback=_prompt_code,
                password=_prompt_password,
            )
            user = await downloader.client.get_me()

        print(f"Logged in as {_describe(user)}")
        return 0

    except (QrLoginTimeout, NoTerminalError) as e:
        print(str(e), file=sys.stderr)
        return 1
    except Exception as e:
        downloader.logger.debug("Login failed", exc_info=True)
        # EOFError and friends stringify to "", which left a bare "Login failed:".
        print(f"Login failed: {str(e) or type(e).__name__}", file=sys.stderr)
        return 1
    finally:
        await downloader.close()

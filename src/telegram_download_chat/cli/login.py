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


def _print_qr(url: str) -> None:
    """Draw the QR code, with the URL as a fallback for terminals that mangle it."""
    plain = sys.stdout.isatty() is not True
    print()
    print(render_qr_ascii(url) if plain else render_qr_ansi(url))
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
                password=lambda: getpass.getpass("Two-step verification password: "),
            )
        else:
            phone = downloader.config.get("settings", {}).get("phone")
            await downloader.client.start(
                phone=phone or (lambda: input("Please enter your phone: ")),
                password=lambda: getpass.getpass("Two-step verification password: "),
            )
            user = await downloader.client.get_me()

        print(f"Logged in as {_describe(user)}")
        return 0

    except QrLoginTimeout as e:
        print(str(e), file=sys.stderr)
        return 1
    except Exception as e:
        downloader.logger.debug("Login failed", exc_info=True)
        print(f"Login failed: {e}", file=sys.stderr)
        return 1
    finally:
        await downloader.close()

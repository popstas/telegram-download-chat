"""Telegram authentication utilities."""

import asyncio
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    PhoneNumberUnoccupiedError,
    RPCError,
    SessionPasswordNeededError,
)
from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate

logger = logging.getLogger(__name__)

MT_PROXY_TYPE = "mtproto"


class TelegramAuthError(Exception):
    """Base exception for Telegram authentication errors."""

    pass


class TelegramAuth:
    """Handles Telegram authentication and session management."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_path: Path,
        proxy_url: Optional[str] = None,
    ):
        """Initialize the Telegram authenticator.

        Args:
            api_id: Telegram API ID
            api_hash: Telegram API hash
            session_path: Path to store the session file
            proxy_url: Optional SOCKS/HTTP URL or Telegram MTProto proxy link
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = str(session_path)
        self.proxy_url = proxy_url
        self.client: Optional[TelegramClient] = None
        self._is_authenticated = False
        self.phone_code_hash: Optional[str] = None
        self._proxy_config: Optional[dict] = None

    @staticmethod
    def parse_proxy_url(proxy_url: Optional[str]) -> Optional[dict]:
        """Parse and validate proxy input for Telethon.

        Supports SOCKS4/SOCKS5/HTTP URLs plus Telegram MTProto proxy links in
        ``tg://proxy`` and ``https://t.me/proxy`` form.

        Args:
            proxy_url: Proxy URL or Telegram proxy link.

        Returns:
            Validated proxy configuration, or None when no proxy is configured.

        Raises:
            ValueError: If the proxy input is unsupported or malformed.
        """
        if not proxy_url:
            return None

        # Numeric constants compatible with both PySocks and python-socks,
        # and accepted directly by Telethon's _parse_proxy.
        SOCKS5, SOCKS4, HTTP = 2, 1, 3

        parsed = urlparse(proxy_url)
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()
        path = parsed.path.rstrip("/").lower()

        is_tg_mtproxy = scheme == "tg" and parsed.netloc.lower() == "proxy"
        is_tme_proxy_path = hostname == "t.me" and path == "/proxy"
        is_tme_mtproxy = scheme == "https" and is_tme_proxy_path

        if scheme == "http" and is_tme_proxy_path:
            raise ValueError(
                "Telegram MTProto proxy links must use https://t.me/proxy."
            )

        if is_tg_mtproxy or is_tme_mtproxy:
            query = parse_qs(parsed.query, keep_blank_values=True)
            server = query.get("server", [""])[0].strip()
            port_value = query.get("port", [""])[0].strip()
            secret = query.get("secret", [""])[0].strip()

            if not server:
                raise ValueError("MTProto proxy link is missing server.")
            if not port_value:
                raise ValueError("MTProto proxy link is missing port.")

            try:
                port = int(port_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "MTProto proxy port must be an integer between 1 and 65535."
                ) from exc

            if not 1 <= port <= 65535:
                raise ValueError(
                    "MTProto proxy port must be an integer between 1 and 65535."
                )
            if not secret:
                raise ValueError("MTProto proxy link is missing secret.")

            return {
                "proxy_type": MT_PROXY_TYPE,
                "addr": server,
                "port": port,
                "secret": secret,
            }

        scheme_map = {
            "socks5": SOCKS5,
            "socks4": SOCKS4,
            "http": HTTP,
            "https": HTTP,
        }

        proxy_type = scheme_map.get(scheme)
        if proxy_type is None:
            raise ValueError(
                f"Unsupported proxy scheme: {scheme}. "
                "Supported: socks5, socks4, http, https, tg://proxy, "
                "https://t.me/proxy"
            )

        if not parsed.hostname:
            sanitized = proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url
            raise ValueError(f"Proxy URL missing hostname: {sanitized}")

        port = parsed.port or (1080 if scheme.startswith("socks") else 8080)

        result = {
            "proxy_type": proxy_type,
            "addr": parsed.hostname,
            "port": port,
        }

        if parsed.username:
            result["username"] = unquote(parsed.username)
        if parsed.password:
            result["password"] = unquote(parsed.password)

        return result

    async def _connect_client(self) -> None:
        """Connect while preventing MTProto proxy secrets from reaching errors."""
        if not self.client:
            return

        try:
            await self.client.connect()
        except Exception:
            if (
                self._proxy_config
                and self._proxy_config.get("proxy_type") == MT_PROXY_TYPE
            ):
                # Suppress the original exception context. Some transports may
                # include proxy configuration in low-level error text, so keeping
                # the exception chain could expose the MTProto secret if a caller
                # later logs a traceback.
                raise TelegramAuthError(
                    "Failed to connect through the configured MTProto proxy."
                ) from None
            raise

    async def initialize(self) -> None:
        """Initialize the Telegram client."""
        if self.client is None:
            kwargs = {
                "device_model": "Telegram Download Chat",
                "app_version": "0.6.0",
                "system_version": "1.0.0",
                "lang_code": "en",
                "system_lang_code": "en",
            }

            proxy = self.parse_proxy_url(self.proxy_url)
            self._proxy_config = proxy
            if proxy:
                if proxy.get("proxy_type") == MT_PROXY_TYPE:
                    kwargs["connection"] = ConnectionTcpMTProxyRandomizedIntermediate
                    kwargs["proxy"] = (
                        proxy["addr"],
                        proxy["port"],
                        proxy["secret"],
                    )
                else:
                    try:
                        import python_socks  # noqa: F401
                    except ImportError:
                        raise ImportError(
                            "Proxy support requires python-socks[asyncio]. "
                            "Install with: pip install 'python-socks[asyncio]'"
                        )
                    kwargs["proxy"] = proxy

            self.client = TelegramClient(
                self.session_path,
                self.api_id,
                self.api_hash,
                **kwargs,
            )
            await self._connect_client()
            self._is_authenticated = await self.client.is_user_authorized()

    async def request_code(self, phone: str) -> Optional[str]:
        """Request a login code from Telegram.

        Args:
            phone: Phone number in international format (e.g., +1234567890)

        Raises:
            TelegramAuthError: If there's an error requesting the code
        """
        try:
            logger.debug(f"Requesting code for phone: {phone}")

            # Ensure client is properly initialized
            if not self.client:
                logger.debug("Initializing Telegram client...")
                await self.initialize()

            if not self.client.is_connected():
                logger.debug("Client not connected, connecting...")
                await self._connect_client()

            logger.debug("Sending code request...")
            result = await self.client.send_code_request(phone)
            self.phone_code_hash = getattr(result, "phone_code_hash", None)
            logger.debug(f"Code request sent successfully: {result}")
            return self.phone_code_hash

        except TelegramAuthError:
            # Connection errors from _connect_client() are already sanitized.
            # Re-raise them unchanged instead of sending them through the generic
            # traceback logger below.
            raise

        except (
            PhoneNumberInvalidError,
            PhoneNumberUnoccupiedError,
            PhoneNumberBannedError,
        ) as e:
            error_msg = f"Invalid phone number: {e}"
            logger.error(error_msg)
            raise TelegramAuthError(error_msg) from e

        except FloodWaitError as e:
            error_msg = f"Too many login attempts. Please wait {e.seconds} seconds before trying again."
            logger.error(error_msg)
            raise TelegramAuthError(error_msg) from e

        except RPCError as e:
            error_msg = f"Telegram API error: {e}"
            logger.error(error_msg)
            raise TelegramAuthError(error_msg) from e

        except Exception as e:
            error_msg = f"Unexpected error requesting code: {e}"
            logger.error(error_msg, exc_info=True)
            raise TelegramAuthError(error_msg) from e

    async def sign_in(
        self, phone: str, code: str, password: str = None, phone_code_hash: str = None
    ) -> bool:
        """Sign in with a phone number and code.

        Args:
            phone: Phone number in international format
            code: Verification code received via SMS or other means
            password: 2FA password if enabled
            phone_code_hash: The phone code hash received during code request

        Returns:
            bool: True if sign-in was successful

        Raises:
            TelegramAuthError: If there's an error during sign-in
        """
        if not self.client:
            await self.initialize()

        # Ensure we have a valid code
        if not code:
            raise TelegramAuthError("Verification code is required")

        try:
            # First try to sign in with the provided code and hash
            try:
                sign_in_kwargs = {"phone": phone, "code": code}

                # Add phone_code_hash if available
                if phone_code_hash:
                    sign_in_kwargs["phone_code_hash"] = phone_code_hash
                    logging.debug(
                        f"Attempting sign in with phone_code_hash: {phone_code_hash}"
                    )
                else:
                    logging.debug("Attempting sign in without phone_code_hash")

                # Try to sign in with the code
                await self.client.sign_in(**sign_in_kwargs)
                self._is_authenticated = True
                return True

            except SessionPasswordNeededError:
                if not password:
                    raise TelegramAuthError(
                        "2FA is enabled. Please enter your password."
                    )

                # If 2FA is enabled, handle the password
                logging.debug("2FA password required, attempting sign in with password")
                try:
                    await self.client.sign_in(password=password)
                    self._is_authenticated = True
                    return True
                except Exception as e:
                    raise TelegramAuthError(f"Invalid 2FA password: {e}") from e

        except (PhoneCodeInvalidError, PhoneCodeExpiredError, PhoneCodeEmptyError) as e:
            raise TelegramAuthError(f"Invalid or expired code: {e}") from e
        except RPCError as e:
            raise TelegramAuthError(f"Telegram API error: {e}") from e
        except Exception as e:
            logging.error(f"Unexpected error during sign in: {e}", exc_info=True)
            raise TelegramAuthError(f"Failed to sign in: {str(e)}") from e

    async def log_out(self) -> bool:
        """Log out from the current session.

        Returns:
            bool: True if logout was successful
        """
        if not self.client:
            return False

        if not self.client.is_connected():
            # Nothing to do if the client is already disconnected
            return False

        try:
            await self.client.log_out()
            self._is_authenticated = False
            return True
        except Exception as e:
            logger.error(f"Error logging out: {e}")
            return False

    async def logout_and_cleanup(self, session_path: Path) -> None:
        """Log out, close the client and remove the session file."""
        try:
            logger.debug("Starting Telegram client cleanup...")
            client = getattr(self, "client", None)
            if client:
                try:
                    if hasattr(client, "_sender") and client._sender:
                        if hasattr(client._sender, "_send_loop_task"):
                            client._sender._send_loop_task.cancel()
                        if hasattr(client._sender, "_recv_loop_task"):
                            client._sender._recv_loop_task.cancel()
                except Exception as e:  # pragma: no cover - best effort cleanup
                    logger.warning(f"Error stopping client tasks (non-critical): {e}")
                try:
                    logged_out = await self.log_out()
                    if logged_out:
                        logger.info("Successfully logged out from Telegram.")
                    else:
                        logger.debug("Client already disconnected; skipping logout.")
                except Exception as e:  # pragma: no cover - best effort cleanup
                    logger.warning(f"Error during graceful logout (non-critical): {e}")
                try:
                    await self.close()
                    logger.info("Telegram auth instance closed successfully.")
                except Exception as e:  # pragma: no cover - best effort cleanup
                    logger.warning(
                        f"Error closing Telegram auth instance (non-critical): {e}"
                    )
        except Exception as e:
            logger.error(f"Error during Telegram client cleanup: {e}", exc_info=True)
        await asyncio.sleep(1.0)
        if session_path.exists():
            max_attempts = 5
            for attempt in range(max_attempts):
                try:
                    session_path.unlink()
                    logger.info(f"Successfully deleted session file: {session_path}")
                    break
                except (PermissionError, OSError) as e:
                    if attempt == max_attempts - 1:
                        logger.error(
                            f"Failed to delete session file after {max_attempts} attempts: {e}"
                        )
                        break
                    wait_time = 0.5 * (attempt + 1)
                    logger.debug(
                        f"Retrying session file deletion in {wait_time} seconds (attempt {attempt + 1}/{max_attempts})..."
                    )
                    await asyncio.sleep(wait_time)

    def is_authenticated(self) -> bool:
        """Check if the user is authenticated.

        Returns:
            bool: True if authenticated, False otherwise
        """
        return self._is_authenticated

    async def close(self) -> None:
        """Close the Telegram client connection."""
        if self.client:
            if self.client.is_connected():
                await self.client.disconnect()
            self.client = None
            self._is_authenticated = False

    def __del__(self):
        """Ensure the client is properly closed when the object is destroyed."""
        if not getattr(self, "client", None):
            return

        import asyncio

        try:
            loop = self.client.loop
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(self.close())
        else:
            try:
                asyncio.run(self.close())
            except RuntimeError:
                # Event loop is closed or already running; best-effort cleanup
                pass

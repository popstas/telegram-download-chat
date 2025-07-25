"""Telegram authentication utilities."""
import asyncio
import logging
from pathlib import Path
from typing import Optional

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

logger = logging.getLogger(__name__)


class TelegramAuthError(Exception):
    """Base exception for Telegram authentication errors."""

    pass


class TelegramAuth:
    """Handles Telegram authentication and session management."""

    def __init__(self, api_id: int, api_hash: str, session_path: Path):
        """Initialize the Telegram authenticator.

        Args:
            api_id: Telegram API ID
            api_hash: Telegram API hash
            session_path: Path to store the session file
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = str(session_path)
        self.client: Optional[TelegramClient] = None
        self._is_authenticated = False
        self.phone_code_hash: Optional[str] = None

    async def initialize(self) -> None:
        """Initialize the Telegram client."""
        if self.client is None:
            self.client = TelegramClient(
                self.session_path,
                self.api_id,
                self.api_hash,
                device_model="Telegram Download Chat",
                app_version="0.3.0",
                system_version="1.0.0",
                lang_code="en",
                system_lang_code="en",
            )
            await self.client.connect()
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
                await self.client.connect()

            logger.debug("Sending code request...")
            result = await self.client.send_code_request(phone)
            self.phone_code_hash = getattr(result, "phone_code_hash", None)
            logger.debug(f"Code request sent successfully: {result}")
            return self.phone_code_hash

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
        if self.client and self.client.loop and self.client.loop.is_running():
            self.client.loop.create_task(self.close())
        elif self.client and not self.client.loop.is_running():
            import asyncio

            asyncio.run(self.close())

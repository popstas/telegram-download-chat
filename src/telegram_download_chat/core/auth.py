import logging
from datetime import datetime
from typing import Optional

from telethon.errors import ChatIdInvalidError
from telethon.tl.types import Channel, Chat, User

from ..paths import get_app_dir


class AuthMixin:
    async def connect(self, phone: str = None, code: str = None, password: str = None):
        """Connect to Telegram using the configured API credentials."""
        from telethon.errors import ApiIdInvalidError, PhoneNumberInvalidError

        if self.client and await self.client.is_user_authorized():
            return

        settings = self.config.get("settings", {})
        api_id = settings.get("api_id")
        api_hash = settings.get("api_hash")
        if phone is None:
            phone = settings.get("phone")

        session_file = str(get_app_dir() / "session.session")
        request_delay = settings.get("request_delay", 1)
        request_retries = settings.get("max_retries", 5)

        if not api_id or not api_hash:
            error_msg = (
                "API ID or API Hash not found in config. Please check your config file."
            )
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        self.logger.debug(f"Connecting to Telegram with API ID: {api_id}")
        self.logger.debug(f"Session file: {session_file}")
        from telegram_download_chat.core import TelegramClient

        try:
            self.client = TelegramClient(
                session=session_file,
                api_id=api_id,
                api_hash=api_hash,
                request_retries=request_retries,
                flood_sleep_threshold=request_delay,
            )

            await self.client.connect()
            is_authorized = await self.client.is_user_authorized()
            self.logger.debug(
                f"Connection status: is_authorized={is_authorized}, phone={phone}"
            )

            if phone and not code and not is_authorized:
                await self._request_code(phone)
                return

            if phone and code and not is_authorized:
                await self._perform_login(phone, code, password)
            else:
                self.logger.debug("Using existing session")

            await self._fetch_self_info()
            return True

        except ApiIdInvalidError as e:
            error_msg = "Invalid API ID or API Hash. Please check your credentials."
            self.logger.error(error_msg)
            raise ValueError(error_msg) from e
        except PhoneNumberInvalidError as e:
            error_msg = (
                f"Invalid phone number: {phone}. Please check your phone number."
            )
            self.logger.error(error_msg)
            raise ValueError(error_msg) from e
        except Exception as e:
            error_msg = f"Failed to connect to Telegram: {str(e)}"
            self.logger.error(error_msg)
            if hasattr(self, "client") and self.client:
                await self.client.disconnect()
            raise RuntimeError(error_msg) from e

    async def _request_code(self, phone: str) -> None:
        self.logger.info(f"Starting authentication for phone: {phone}")
        sent_code = await self.client.send_code_request(phone)
        self.phone_code_hash = sent_code.phone_code_hash
        self.logger.info("Verification code sent to your Telegram account")

    async def _perform_login(
        self, phone: str, code: str, password: Optional[str]
    ) -> None:
        from telethon.errors import PhoneCodeInvalidError, SessionPasswordNeededError

        if not hasattr(self, "phone_code_hash"):
            error_msg = "Please request a verification code first"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        try:
            await self.client.sign_in(
                phone=phone,
                code=code,
                phone_code_hash=self.phone_code_hash,
                password=password,
            )
            self.logger.info("Successfully authenticated with code")
        except SessionPasswordNeededError:
            if not password:
                error_msg = (
                    "2FA is enabled but no password provided. Set password parameter."
                )
                self.logger.error(error_msg)
                raise ValueError(error_msg) from None

            self.logger.info("2FA password required")
            await self.client.sign_in(password=password)
            self.logger.info("Successfully authenticated with 2FA password")
        except PhoneCodeInvalidError as e:
            error_msg = (
                "Invalid verification code. Please check your code and try again."
            )
            self.logger.error(error_msg)
            raise ValueError(error_msg) from e

    async def _fetch_self_info(self) -> None:
        self.logger.debug("Retrieving current user via get_me()")
        me = await self.client.get_me()
        self.logger.debug(f"get_me returned: {me}")
        if not me:
            raise RuntimeError("Failed to get current user after authentication")

        self._self_id = getattr(me, "id", None)
        first = getattr(me, "first_name", None)
        last = getattr(me, "last_name", None)
        name_parts = []
        if isinstance(first, str):
            name_parts.append(first)
        if isinstance(last, str):
            name_parts.append(last)
        self._self_name = " ".join(name_parts).strip() or (
            getattr(me, "username", None) or getattr(me, "phone", "")
        )

        self.logger.info(f"Successfully connected as {me.username or me.phone}")

    async def close(self) -> None:
        if self.client and self.client.is_connected():
            await self.client.disconnect()
            self.client = None

    async def list_folders(self):
        from telethon import functions, types

        if not self.client or not self.client.is_connected():
            await self.connect()

        result = await self.client(functions.messages.GetDialogFiltersRequest())

        folders = []
        for f in result.filters:
            if isinstance(f, types.DialogFilter):
                folders.append(f)

        return folders

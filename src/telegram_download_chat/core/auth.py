import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from telethon.errors import ChatIdInvalidError
from telethon.tl.types import Channel, Chat, User

from ..paths import get_app_dir
from .auth_utils import (
    CREDENTIALS_MESSAGE,
    NO_SESSION_MESSAGE,
    ConfigurationError,
    NoSessionError,
    TelegramAuth,
)


class AuthMixin:
    async def prepare_client(self) -> bool:
        """Build the Telegram client from config and report session state.

        Returns whether the stored session is already authorized. Unlike
        :meth:`connect` this never fails on a missing session, so the ``login``
        command can use the client to authenticate.
        """
        from telethon.errors import ApiIdInvalidError

        settings = self.config.get("settings", {})
        api_id = settings.get("api_id")
        api_hash = settings.get("api_hash")

        # A first run writes `YOUR_API_ID` placeholders into the config, so an
        # unedited config must say what to do rather than fail on int().
        placeholders = {str(api_id), str(api_hash)} & {"YOUR_API_ID", "YOUR_API_HASH"}
        if not api_id or not api_hash or placeholders:
            self.logger.error(CREDENTIALS_MESSAGE)
            raise ConfigurationError(CREDENTIALS_MESSAGE)

        try:
            api_id = int(str(api_id).strip())
        except (TypeError, ValueError) as e:
            message = f"{CREDENTIALS_MESSAGE} api_id must be a number, got {api_id!r}."
            self.logger.error(message)
            raise ConfigurationError(message) from e

        session_file = str(get_app_dir() / "session.session")
        self.logger.debug(f"Connecting to Telegram with API ID: {api_id}")
        self.logger.debug(f"Session file: {session_file}")

        try:
            self.telegram_auth = TelegramAuth(
                api_id=api_id,
                api_hash=api_hash,
                session_path=Path(session_file),
                proxy_url=settings.get("proxy_url") or None,
            )

            await self.telegram_auth.initialize()
            self.client = self.telegram_auth.client
            is_authorized = self.telegram_auth.is_authenticated()
            self.logger.debug(f"Connection status: is_authorized={is_authorized}")
            return is_authorized

        except ApiIdInvalidError as e:
            error_msg = "Invalid API ID or API Hash. Please check your credentials."
            self.logger.error(error_msg)
            raise ValueError(error_msg) from e
        except ValueError as e:
            # A session file written by a newer Telethon (e.g. schema v8 with the
            # tmp_auth_key column) cannot be read by an older installed Telethon,
            # which unpacks `select * from sessions` into the wrong number of
            # targets and raises "too many values to unpack". Turn the cryptic
            # error into an actionable one instead of a generic connect failure.
            if "too many values to unpack" in str(e):
                error_msg = (
                    "Your Telegram session was created by a newer version of "
                    "Telethon than the one installed. Upgrade it with: "
                    "pip install -U 'telethon>=1.43.0'"
                )
                self.logger.error(error_msg)
                if getattr(self, "client", None):
                    await self.client.disconnect()
                raise RuntimeError(error_msg) from e
            raise
        except Exception as e:
            error_msg = f"Failed to connect to Telegram: {str(e)}"
            self.logger.error(error_msg)
            if getattr(self, "client", None):
                await self.client.disconnect()
            raise RuntimeError(error_msg) from e

    async def connect(
        self,
        phone: str = None,
        code: str = None,
        password: str = None,
    ):
        """Connect to Telegram using the configured API credentials.

        A missing session raises :class:`NoSessionError`: logging in is
        interactive and belongs to the ``login`` command or the GUI, not to a
        download that may run without a terminal. ``phone`` must be passed
        explicitly to request a code — a phone left in the config never does.
        """
        from telethon.errors import ApiIdInvalidError, PhoneNumberInvalidError

        if self.client and await self.client.is_user_authorized():
            # `ensure_session` may have opened the session already, and
            # `_fetch_self_info` below this branch would then never run: own
            # messages are marked by `_self_id` and "me" resolves through it.
            if getattr(self, "_self_id", None) is None:
                await self._fetch_self_info()
            return

        is_authorized = await self.prepare_client()

        if not is_authorized and not phone:
            self.logger.error(NO_SESSION_MESSAGE)
            raise NoSessionError(NO_SESSION_MESSAGE)

        try:
            if phone and not code and not is_authorized:
                self.phone_code_hash = await self.telegram_auth.request_code(phone)
                return

            if phone and code and not is_authorized:
                await self.telegram_auth.sign_in(
                    phone,
                    code,
                    password,
                    phone_code_hash=getattr(self, "phone_code_hash", None),
                )
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

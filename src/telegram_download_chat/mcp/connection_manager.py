"""Connection manager for Telegram client with reconnection and diagnostics."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

from telethon.errors import (
    AuthKeyUnregisteredError,
    FloodWaitError,
    RPCError,
)

from ..core import DownloaderContext, TelegramChatDownloader

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ConnectionState(Enum):
    """Telegram connection states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class ConnectionStats:
    """Connection statistics for diagnostics."""

    connected_at: Optional[datetime] = None
    last_request_at: Optional[datetime] = None
    request_count: int = 0
    error_count: int = 0
    reconnect_count: int = 0
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to serializable dict."""
        return {
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "last_request_at": self.last_request_at.isoformat()
            if self.last_request_at
            else None,
            "request_count": self.request_count,
            "error_count": self.error_count,
            "reconnect_count": self.reconnect_count,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at.isoformat()
            if self.last_error_at
            else None,
        }


class TelegramConnectionManager:
    """Manages Telegram client connection with auto-reconnection."""

    MAX_RECONNECT_ATTEMPTS = 3
    INITIAL_BACKOFF_SECONDS = 1.0

    def __init__(self):
        self._downloader: Optional[TelegramChatDownloader] = None
        self._context: Optional[DownloaderContext] = None
        self._state = ConnectionState.DISCONNECTED
        self._stats = ConnectionStats()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> ConnectionState:
        """Current connection state."""
        return self._state

    @property
    def stats(self) -> ConnectionStats:
        """Connection statistics."""
        return self._stats

    @property
    def downloader(self) -> Optional[TelegramChatDownloader]:
        """Access to the downloader instance."""
        return self._downloader

    @property
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._state == ConnectionState.CONNECTED

    async def connect(self) -> bool:
        """Establish connection to Telegram.

        Returns:
            True if connection successful, False otherwise.
        """
        async with self._lock:
            if self._state == ConnectionState.CONNECTED:
                return True

            self._state = ConnectionState.CONNECTING
            logger.info("Connecting to Telegram...")

            try:
                self._downloader = TelegramChatDownloader()
                self._context = DownloaderContext(self._downloader, cli=False)
                await self._context.__aenter__()

                self._state = ConnectionState.CONNECTED
                self._stats.connected_at = datetime.now(timezone.utc)
                logger.info("Telegram client connected")
                return True

            except Exception as e:
                self._state = ConnectionState.ERROR
                self._stats.error_count += 1
                self._stats.last_error = str(e)
                self._stats.last_error_at = datetime.now(timezone.utc)
                logger.exception("Failed to connect to Telegram")
                return False

    async def disconnect(self) -> None:
        """Disconnect from Telegram."""
        async with self._lock:
            await self._disconnect_internal()

    async def _disconnect_internal(self) -> None:
        """Internal disconnect without lock (caller must hold lock)."""
        if self._context:
            logger.info("Disconnecting Telegram client...")
            try:
                await self._context.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._context = None

        self._downloader = None
        self._state = ConnectionState.DISCONNECTED
        logger.info("Telegram client disconnected")

    async def reconnect(self) -> bool:
        """Reconnect to Telegram with retry logic.

        Returns:
            True if reconnection successful, False otherwise.
        """
        async with self._lock:
            return await self._reconnect_internal()

    async def _reconnect_internal(self) -> bool:
        """Internal reconnect without lock (caller must hold lock)."""
        self._state = ConnectionState.RECONNECTING
        self._stats.reconnect_count += 1

        # Disconnect first
        await self._disconnect_internal()

        backoff = self.INITIAL_BACKOFF_SECONDS

        for attempt in range(1, self.MAX_RECONNECT_ATTEMPTS + 1):
            logger.info(f"Reconnection attempt {attempt}/{self.MAX_RECONNECT_ATTEMPTS}")

            try:
                self._downloader = TelegramChatDownloader()
                self._context = DownloaderContext(self._downloader, cli=False)
                await self._context.__aenter__()

                self._state = ConnectionState.CONNECTED
                self._stats.connected_at = datetime.now(timezone.utc)
                logger.info("Reconnection successful")
                return True

            except Exception as e:
                logger.warning(f"Reconnection attempt {attempt} failed: {e}")
                self._stats.error_count += 1
                self._stats.last_error = str(e)
                self._stats.last_error_at = datetime.now(timezone.utc)

                if attempt < self.MAX_RECONNECT_ATTEMPTS:
                    logger.info(f"Waiting {backoff}s before next attempt...")
                    await asyncio.sleep(backoff)
                    backoff *= 2  # Exponential backoff

        self._state = ConnectionState.ERROR
        logger.error("All reconnection attempts failed")
        return False

    async def ensure_connected(self) -> bool:
        """Ensure connection is active, reconnecting if needed.

        Returns:
            True if connected (or reconnected), False otherwise.
        """
        if self._state == ConnectionState.CONNECTED:
            # Verify connection is still alive
            if await self.health_check():
                return True
            # Health check failed, try to reconnect
            return await self.reconnect()

        if self._state == ConnectionState.ERROR:
            return await self.reconnect()

        if self._state == ConnectionState.DISCONNECTED:
            return await self.connect()

        # CONNECTING or RECONNECTING - wait for it
        async with self._lock:
            return self._state == ConnectionState.CONNECTED

    async def health_check(self) -> bool:
        """Verify the connection is still alive.

        Returns:
            True if connection is healthy, False otherwise.
        """
        if not self._downloader or not self._downloader.client:
            return False

        try:
            # Use Telethon's is_connected check
            return self._downloader.client.is_connected()
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

    def record_request(self) -> None:
        """Record a successful request."""
        self._stats.request_count += 1
        self._stats.last_request_at = datetime.now(timezone.utc)

    def record_error(self, error: Exception) -> None:
        """Record an error."""
        self._stats.error_count += 1
        self._stats.last_error = str(error)
        self._stats.last_error_at = datetime.now(timezone.utc)

    def get_status(self) -> dict[str, Any]:
        """Get connection status for diagnostics.

        Returns:
            Dict with state, stats, and client info.
        """
        client_info = None
        if self._downloader and self._downloader.client:
            try:
                client_info = {
                    "is_connected": self._downloader.client.is_connected(),
                }
            except Exception:
                client_info = {"is_connected": False}

        return {
            "state": self._state.value,
            "stats": self._stats.to_dict(),
            "client": client_info,
        }

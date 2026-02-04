"""Simplified connection manager for Telegram client with task queue."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ..core import DownloaderContext, TelegramChatDownloader

logger = logging.getLogger(__name__)


@dataclass
class ConnectionStats:
    """Connection statistics for diagnostics."""

    connected_at: Optional[datetime] = None
    last_request_at: Optional[datetime] = None
    request_count: int = 0
    error_count: int = 0
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
            "last_error": self.last_error,
            "last_error_at": self.last_error_at.isoformat()
            if self.last_error_at
            else None,
        }


@dataclass
class QueuedTask:
    """A task queued for execution."""

    id: str
    client_id: str
    func: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    created_at: datetime
    future: asyncio.Future[Any]


class TaskQueue:
    """Queue for serializing Telegram API calls."""

    def __init__(self):
        self._queue: asyncio.Queue[QueuedTask] = asyncio.Queue()
        self._pending: dict[str, QueuedTask] = {}
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._running = False
        self._total_processed = 0

    async def start(self) -> None:
        """Start the queue worker."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("Task queue worker started")

    async def stop(self) -> None:
        """Stop the queue worker."""
        self._running = False
        if self._worker_task:
            # Cancel any pending tasks
            for task in self._pending.values():
                if not task.future.done():
                    task.future.cancel()
            self._pending.clear()

            # Cancel the worker
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.info("Task queue worker stopped")

    async def submit(
        self,
        client_id: str,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Submit a task to the queue and wait for result.

        Args:
            client_id: Identifier of the MCP client making the request
            func: Async function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            Result from the function execution

        Raises:
            Exception: Any exception raised by the function
        """
        task_id = str(uuid.uuid4())[:8]
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()

        task = QueuedTask(
            id=task_id,
            client_id=client_id,
            func=func,
            args=args,
            kwargs=kwargs,
            created_at=datetime.now(timezone.utc),
            future=future,
        )

        self._pending[task_id] = task
        await self._queue.put(task)
        logger.debug(f"Task {task_id} queued for client {client_id}")

        try:
            return await future
        finally:
            self._pending.pop(task_id, None)

    async def _worker(self) -> None:
        """Process tasks from the queue one at a time."""
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            logger.debug(f"Processing task {task.id} from client {task.client_id}")

            try:
                result = await task.func(*task.args, **task.kwargs)
                if not task.future.done():
                    task.future.set_result(result)
                self._total_processed += 1
            except Exception as e:
                if not task.future.done():
                    task.future.set_exception(e)
                logger.warning(f"Task {task.id} failed: {e}")
            finally:
                self._queue.task_done()

    def get_queue_status(self) -> dict[str, Any]:
        """Get queue status for diagnostics."""
        pending_info = [
            {
                "id": t.id,
                "client_id": t.client_id,
                "created_at": t.created_at.isoformat(),
            }
            for t in self._pending.values()
        ]

        return {
            "running": self._running,
            "queue_size": self._queue.qsize(),
            "pending_count": len(self._pending),
            "total_processed": self._total_processed,
            "pending_tasks": pending_info,
        }


class TelegramConnectionManager:
    """Manages Telegram client connection with task queue."""

    def __init__(self):
        self._downloader: Optional[TelegramChatDownloader] = None
        self._context: Optional[DownloaderContext] = None
        self._connected: bool = False
        self._stats = ConnectionStats()
        self._queue = TaskQueue()

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
        return self._connected

    async def connect(self) -> bool:
        """Establish connection to Telegram.

        Returns:
            True if connection successful, False otherwise.
        """
        if self._connected:
            return True

        logger.info("Connecting to Telegram...")

        try:
            self._downloader = TelegramChatDownloader()
            self._context = DownloaderContext(self._downloader, cli=False)
            await self._context.__aenter__()

            self._connected = True
            self._stats.connected_at = datetime.now(timezone.utc)
            logger.info("Telegram client connected")

            # Start the task queue
            await self._queue.start()

            return True

        except Exception as e:
            self._stats.error_count += 1
            self._stats.last_error = str(e)
            self._stats.last_error_at = datetime.now(timezone.utc)
            logger.exception("Failed to connect to Telegram")
            return False

    async def disconnect(self) -> None:
        """Disconnect from Telegram."""
        # Stop the queue first
        await self._queue.stop()

        if self._context:
            logger.info("Disconnecting Telegram client...")
            try:
                await self._context.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._context = None

        self._downloader = None
        self._connected = False
        logger.info("Telegram client disconnected")

    async def execute(
        self,
        client_id: str,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute a function through the task queue.

        Args:
            client_id: Identifier of the MCP client
            func: Async function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result from the function

        Raises:
            RuntimeError: If not connected
            Exception: Any exception from the function
        """
        if not self._connected:
            raise RuntimeError("Not connected to Telegram")

        result = await self._queue.submit(client_id, func, *args, **kwargs)
        self.record_request()
        return result

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
            Dict with connection state, stats, queue info, and client info.
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
            "connected": self._connected,
            "stats": self._stats.to_dict(),
            "queue": self._queue.get_queue_status(),
            "client": client_info,
        }

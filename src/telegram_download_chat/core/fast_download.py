"""Parallel multi-connection media downloader.

Adapted from painor's FastTelethon gist
(https://gist.github.com/painor/7e74de80ae0c819d3e9abcf9989a8dd6),
which is itself derived from mautrix-telegram's parallel_file_transfer.py
(Copyright 2021 Tulir Asokan, MIT License).

Only the download path is kept, with added FloodWait retry handling so a
brief throttle on one connection does not abort the whole file. The public
entry point is :func:`download_file`.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
from typing import AsyncGenerator, BinaryIO, List, Optional, Tuple, Union

from telethon import TelegramClient, utils
from telethon.crypto import AuthKey
from telethon.errors import FloodWaitError
from telethon.network import MTProtoSender
from telethon.tl.alltlobjects import LAYER
from telethon.tl.functions import InvokeWithLayerRequest
from telethon.tl.functions.auth import (
    ExportAuthorizationRequest,
    ImportAuthorizationRequest,
)
from telethon.tl.functions.upload import GetFileRequest
from telethon.tl.types import (
    Document,
    InputDocumentFileLocation,
    InputFileLocation,
    InputPeerPhotoFileLocation,
    InputPhotoFileLocation,
)

log = logging.getLogger(__name__)

TypeLocation = Union[
    Document,
    InputDocumentFileLocation,
    InputPeerPhotoFileLocation,
    InputFileLocation,
    InputPhotoFileLocation,
]

# Hard ceiling on a single FloodWait. If Telegram asks us to wait longer than
# this on one chunk we bail out and let the caller fall back to the standard
# downloader rather than blocking the whole run.
_MAX_FLOOD_WAIT_SECONDS = 30

# If a single chunk request hasn't returned in this long, treat the parallel
# path as stalled (Telegram likely closed the auxiliary socket and Telethon's
# reconnect loop is spinning on the AttributeError race in 1.34). The caller
# falls back to the single-stream downloader.
_CHUNK_TIMEOUT_SECONDS = 60

# Hard ceiling on how long we wait for auxiliary senders to disconnect during
# cleanup. Stuck reconnect loops can keep `sender.disconnect()` pending forever;
# we'd rather orphan the tasks than freeze the process.
_CLEANUP_TIMEOUT_SECONDS = 10


class FastDownloadStalled(Exception):
    """Raised when a parallel-chunk request stalls past `_CHUNK_TIMEOUT_SECONDS`."""


class _ReconnectAttrErrorFilter(logging.Filter):
    """Drop Telethon's noisy reconnect-AttributeError tracebacks.

    Telethon 1.34 has a race where MTProtoSender._reconnect calls
    `await self._connection.connect(...)` after `_connection` was nulled by a
    concurrent disconnect, raising AttributeError. The reconnect loop catches
    and retries forever, flooding the log. We can't fix Telethon from here, but
    we can stop the spam — and log a single concise warning the first time it
    happens so a real failure is still visible.
    """

    def __init__(self) -> None:
        super().__init__()
        self.warned = False

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if not msg.startswith("Unexpected exception reconnecting on attempt"):
            return True
        exc_info = record.exc_info
        if not exc_info or not isinstance(exc_info[1], AttributeError):
            return True
        if "'NoneType' object has no attribute 'connect'" not in str(exc_info[1]):
            return True
        if not self.warned:
            self.warned = True
            log.warning(
                "Telegram closed an auxiliary parallel-download connection; "
                "Telethon's reconnect loop is racing — falling back to "
                "single-stream downloader if the file stalls."
            )
        return False


class _ServerClosedRewriteFilter(logging.Filter):
    """Rewrite Telethon's alarming "Server closed the connection: …" warnings.

    During parallel media downloads Telegram routinely drops auxiliary sockets
    as a throttling signal (e.g. "0 bytes read on a total of 8 expected bytes",
    "Connection reset by peer"). Telethon logs each at WARNING from
    `telethon.network.connection.connection`, which reads like a hard failure.
    We replace the wording in place with a clearer message and keep the record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage().startswith("Server closed the connection:"):
            record.msg = "Rate limited by Telegram, retrying…"
            record.args = ()
        return True


class _SecurityErrorFilter(logging.Filter):
    """Drop Telethon's "Security error … wrong session ID" spam.

    When Telegram throttles the cross-DC parallel senders, replies arrive
    tagged with a session ID that no longer matches, and Telethon logs
    "Security error while unpacking a received message: …" at WARNING from
    `telethon.network.mtprotosender` for every dropped packet — hundreds of
    lines during a heavily-throttled run. The packets are retried internally,
    so the noise is harmless. We suppress it, emitting one concise warning the
    first time so a genuine problem stays visible.
    """

    def __init__(self) -> None:
        super().__init__()
        self.warned = False

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.getMessage().startswith(
            "Security error while unpacking a received message"
        ):
            return True
        if not self.warned:
            self.warned = True
            log.warning(
                "Telegram is throttling the parallel-download senders "
                "(wrong session ID on replies); suppressing further "
                "security-error noise."
            )
        return False


class DownloadSender:
    """One MTProtoSender pulling a strided slice of a single file."""

    def __init__(
        self,
        client: TelegramClient,
        sender: MTProtoSender,
        file: TypeLocation,
        offset: int,
        limit: int,
        stride: int,
        count: int,
        max_retries: int = 3,
    ) -> None:
        self.client = client
        self.sender = sender
        self.request = GetFileRequest(file, offset=offset, limit=limit)
        self.stride = stride
        self.remaining = count
        self.max_retries = max_retries

    async def next(self) -> Optional[bytes]:
        if not self.remaining:
            return None
        attempt = 0
        while True:
            try:
                result = await asyncio.wait_for(
                    self.client._call(self.sender, self.request),
                    timeout=_CHUNK_TIMEOUT_SECONDS,
                )
                break
            except asyncio.TimeoutError as e:
                raise FastDownloadStalled(
                    f"Parallel chunk request exceeded {_CHUNK_TIMEOUT_SECONDS}s"
                ) from e
            except FloodWaitError as e:
                attempt += 1
                if e.seconds > _MAX_FLOOD_WAIT_SECONDS or attempt > self.max_retries:
                    raise
                log.debug(
                    "FloodWait %ss on parallel chunk (attempt %d/%d), sleeping",
                    e.seconds,
                    attempt,
                    self.max_retries,
                )
                await asyncio.sleep(e.seconds)
        self.remaining -= 1
        self.request.offset += self.stride
        return result.bytes

    def disconnect(self):
        return self.sender.disconnect()


class ParallelTransferrer:
    """Spawns N MTProtoSenders against one DC and yields chunks in order."""

    def __init__(self, client: TelegramClient, dc_id: Optional[int] = None) -> None:
        self.client = client
        self.loop = asyncio.get_event_loop()
        self.dc_id: int = dc_id or client.session.dc_id
        # Reuse the existing auth key only when the file lives in the user's home DC.
        self.auth_key: Optional[AuthKey] = (
            None if dc_id and client.session.dc_id != dc_id else client.session.auth_key
        )
        self.senders: Optional[List[DownloadSender]] = None
        # Filters scoped to the lifetime of a download(): tame the two noisy
        # Telethon loggers that fire when Telegram throttles parallel sockets.
        self._log_filters: List[Tuple[logging.Logger, logging.Filter]] = []

    def _install_log_filter(self) -> None:
        if self._log_filters:
            return
        for logger_name, filter_factory in (
            ("telethon.network.mtprotosender", _ReconnectAttrErrorFilter),
            ("telethon.network.mtprotosender", _SecurityErrorFilter),
            ("telethon.network.connection.connection", _ServerClosedRewriteFilter),
        ):
            logger = logging.getLogger(logger_name)
            log_filter = filter_factory()
            logger.addFilter(log_filter)
            self._log_filters.append((logger, log_filter))

    def _remove_log_filter(self) -> None:
        for logger, log_filter in self._log_filters:
            logger.removeFilter(log_filter)
        self._log_filters = []

    async def _cleanup(self) -> None:
        try:
            if self.senders:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(
                            *[sender.disconnect() for sender in self.senders],
                            return_exceptions=True,
                        ),
                        timeout=_CLEANUP_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    log.warning(
                        "Parallel-download cleanup exceeded %ds; orphaning %d "
                        "stuck sender(s) so the caller can proceed.",
                        _CLEANUP_TIMEOUT_SECONDS,
                        len(self.senders),
                    )
                self.senders = None
        finally:
            self._remove_log_filter()

    @staticmethod
    def _get_connection_count(
        file_size: int,
        max_count: int = 8,
        full_size: int = 100 * 1024 * 1024,
    ) -> int:
        if file_size > full_size:
            return max_count
        return max(1, math.ceil((file_size / full_size) * max_count))

    async def _create_sender(self) -> MTProtoSender:
        dc = await self.client._get_dc(self.dc_id)
        sender = MTProtoSender(self.auth_key, loggers=self.client._log)
        await sender.connect(
            self.client._connection(
                dc.ip_address,
                dc.port,
                dc.id,
                loggers=self.client._log,
                proxy=self.client._proxy,
            )
        )
        if not self.auth_key:
            log.debug("Exporting auth to DC %d for parallel download", self.dc_id)
            auth = await self.client(ExportAuthorizationRequest(self.dc_id))
            self.client._init_request.query = ImportAuthorizationRequest(
                id=auth.id, bytes=auth.bytes
            )
            req = InvokeWithLayerRequest(LAYER, self.client._init_request)
            await sender.send(req)
            self.auth_key = sender.auth_key
        return sender

    async def _create_download_sender(
        self,
        file: TypeLocation,
        index: int,
        part_size: int,
        stride: int,
        part_count: int,
    ) -> DownloadSender:
        return DownloadSender(
            self.client,
            await self._create_sender(),
            file,
            index * part_size,
            part_size,
            stride,
            part_count,
        )

    async def _init_download(
        self,
        connections: int,
        file: TypeLocation,
        part_count: int,
        part_size: int,
    ) -> None:
        minimum, remainder = divmod(part_count, connections)

        def get_part_count() -> int:
            nonlocal remainder
            if remainder > 0:
                remainder -= 1
                return minimum + 1
            return minimum

        # The first sender exports+imports the cross-DC auth, so create it
        # serially before fanning out the rest.
        first = await self._create_download_sender(
            file, 0, part_size, connections * part_size, get_part_count()
        )
        rest = await asyncio.gather(
            *[
                self._create_download_sender(
                    file, i, part_size, connections * part_size, get_part_count()
                )
                for i in range(1, connections)
            ]
        )
        self.senders = [first, *rest]

    async def download(
        self,
        file: TypeLocation,
        file_size: int,
        part_size_kb: Optional[float] = None,
        connection_count: Optional[int] = None,
    ) -> AsyncGenerator[bytes, None]:
        connection_count = connection_count or self._get_connection_count(file_size)
        part_size = (part_size_kb or utils.get_appropriated_part_size(file_size)) * 1024
        part_count = math.ceil(file_size / part_size)
        # Don't open more connections than there are parts.
        connection_count = max(1, min(connection_count, part_count))
        log.debug(
            "Parallel download: dc=%d connections=%d part_size=%d part_count=%d",
            self.dc_id,
            connection_count,
            part_size,
            part_count,
        )
        self._install_log_filter()
        try:
            await self._init_download(connection_count, file, part_count, part_size)

            part = 0
            while part < part_count:
                tasks = [
                    self.loop.create_task(sender.next()) for sender in self.senders
                ]
                # Await siblings sequentially, but make sure that on *any* exit
                # (an `await task` raising, or the `break` on a short chunk) the
                # remaining tasks are cancelled and gathered. Otherwise their
                # exceptions surface later as asyncio "Task exception was never
                # retrieved" dumps. The genuine error re-raises after `finally`.
                try:
                    for task in tasks:
                        data = await task
                        if not data:
                            break
                        yield data
                        part += 1
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self._cleanup()


async def download_file(
    client: TelegramClient,
    location: TypeLocation,
    out: BinaryIO,
    *,
    file_size: Optional[int] = None,
    connection_count: Optional[int] = None,
    progress_callback=None,
) -> BinaryIO:
    """Download `location` to the writable binary stream `out`.

    `location` may be a Telethon `Document`/`Photo` (in which case dc_id and
    size are extracted) or an already-resolved `Input*FileLocation` paired
    with `file_size`.
    """
    size = file_size if file_size is not None else getattr(location, "size", None)
    dc_id, input_location = utils.get_input_location(location)
    if size is None:
        raise ValueError("Cannot parallel-download without a known file size")

    downloader = ParallelTransferrer(client, dc_id)
    async for chunk in downloader.download(
        input_location, size, connection_count=connection_count
    ):
        out.write(chunk)
        if progress_callback:
            r = progress_callback(out.tell(), size)
            if inspect.isawaitable(r):
                await r
    return out

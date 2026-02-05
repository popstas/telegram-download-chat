"""MCP server for Telegram chat message retrieval."""

import asyncio
import atexit
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from telethon.errors import (
    AuthKeyUnregisteredError,
    FloodWaitError,
    RPCError,
)

from .connection_manager import TelegramConnectionManager

logger = logging.getLogger(__name__)


class TelegramMessage(BaseModel):
    """Single message from Telegram chat."""

    id: int = Field(description="Message ID")
    date: str = Field(description="ISO format datetime of the message")
    text: str = Field(description="Message text content")
    user_name: str = Field(description="Display name of the sender")
    reply_to_msg_id: Optional[int] = Field(
        default=None, description="ID of replied message"
    )


class TelegramMessagesResponse(BaseModel):
    """Response containing list of messages."""

    messages: list[TelegramMessage] = Field(description="List of messages")


class TelegramErrorResponse(BaseModel):
    """Error response from Telegram operations."""

    error: str = Field(description="Error message")
    code: Optional[str] = Field(default=None, description="Error code")
    retry_after: Optional[int] = Field(
        default=None, description="Seconds to wait before retry (for rate limits)"
    )
    rpc_code: Optional[int] = Field(
        default=None, description="Telegram RPC error code"
    )


# Global connection manager instance (singleton, survives client sessions)
_manager: Optional[TelegramConnectionManager] = None
_manager_lock: Optional[asyncio.Lock] = None

# Simple client ID for this session (in real MCP, would come from request context)
_session_client_id: str = str(uuid.uuid4())[:8]


def _get_lock() -> asyncio.Lock:
    """Get or create the async lock (lazy to avoid event loop issues)."""
    global _manager_lock
    if _manager_lock is None:
        _manager_lock = asyncio.Lock()
    return _manager_lock


async def _get_manager() -> TelegramConnectionManager:
    """Get or create the connection manager (lazy singleton)."""
    global _manager
    async with _get_lock():
        if _manager is None:
            _manager = TelegramConnectionManager()
            connected = await _manager.connect()
            if not connected:
                logger.warning("Initial connection failed")
        return _manager


def _shutdown_sync():
    """Synchronous shutdown for atexit."""
    global _manager
    if _manager is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_manager.shutdown())
            else:
                loop.run_until_complete(_manager.shutdown())
        except Exception as e:
            logger.warning(f"Error during atexit shutdown: {e}")
        _manager = None


atexit.register(_shutdown_sync)


mcp = FastMCP(
    "telegram_chat_mcp",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


async def _fetch_messages(
    downloader,
    chat_id: str,
    min_dt: datetime,
    max_dt: datetime,
    limit: int,
) -> list[dict]:
    """Fetch messages from Telegram (runs in queue)."""
    if not downloader.client:
        raise RuntimeError("Not authenticated")

    # Convert datetime to date strings for downloader
    # Note: downloader's from_date is upper boundary (newer), until_date is lower boundary (older)
    from_date_str = max_dt.strftime("%Y-%m-%d")  # upper boundary (max)
    until_date_str = min_dt.strftime("%Y-%m-%d")  # lower boundary (min)

    messages = await downloader.download_chat(
        chat_id=chat_id,
        from_date=from_date_str,
        until_date=until_date_str,
        total_limit=limit,
        request_limit=min(100, limit),
        save_partial=False,
        silent=True,
    )

    result_messages = []
    for msg in messages:
        msg_dict = msg.to_dict() if hasattr(msg, "to_dict") else msg
        serializable = downloader.make_serializable(msg_dict)

        # Filter by exact datetime range (inclusive)
        msg_date_str = serializable.get("date")
        if msg_date_str:
            msg_dt = datetime.fromisoformat(msg_date_str.replace("Z", "+00:00"))
            if msg_dt < min_dt or msg_dt > max_dt:
                continue

        # Extract user_id from from_id dict
        sender_from_id = serializable.get("from_id")
        user_id = None
        if isinstance(sender_from_id, dict):
            user_id = sender_from_id.get("user_id") or sender_from_id.get("channel_id")
        elif isinstance(sender_from_id, int):
            user_id = sender_from_id

        # Resolve to display name
        user_name = (
            await downloader._get_user_display_name(user_id) if user_id else "Unknown"
        )

        result_messages.append(
            {
                "id": serializable.get("id"),
                "date": serializable.get("date"),
                "text": serializable.get("message", ""),
                "user_name": user_name,
                "reply_to_msg_id": serializable.get("reply_to", {}).get(
                    "reply_to_msg_id"
                )
                if serializable.get("reply_to")
                else None,
            }
        )

    return result_messages


@mcp.tool(
    name="telegram_get_messages",
    description="Use this when you need to download messages from a Telegram chat and make a messages summary.",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
    },
)
async def telegram_get_messages(
    chat_id: str | int = Field(
        default="current",
        description="Chat ID, username, or invite link. Use 'current' for the chat context.",
    ),
    min_datetime: str = Field(
        description="Minimum datetime in ISO format (e.g., '2025-01-15T10:30:00').",
    ),
    max_datetime: Optional[str] = Field(
        default=None,
        description="Maximum datetime in ISO format (e.g., '2025-01-20T15:45:00'). Defaults to now.",
    ),
    limit: int = Field(
        default=100,
        description="Maximum number of messages to retrieve.",
    ),
) -> TelegramMessagesResponse | TelegramErrorResponse:

    # Convert chat_id to string for downloader
    chat_id_str = str(chat_id)

    try:
        manager = await _get_manager()
    except Exception as e:
        logger.exception("Failed to get connection manager")
        return TelegramErrorResponse(error=f"Connection failed: {e}")

    if not manager.is_connected:
        return TelegramErrorResponse(error="Not connected to Telegram")

    # Parse min_datetime
    try:
        min_dt = datetime.fromisoformat(min_datetime)
        if min_dt.tzinfo is None:
            min_dt = min_dt.replace(tzinfo=timezone.utc)
    except ValueError as e:
        return TelegramErrorResponse(error=f"Invalid min_datetime format: {e}")

    # Parse max_datetime (default to now if not provided)
    try:
        if max_datetime is None:
            max_dt = datetime.now(timezone.utc)
        else:
            max_dt = datetime.fromisoformat(max_datetime)
            if max_dt.tzinfo is None:
                max_dt = max_dt.replace(tzinfo=timezone.utc)
    except ValueError as e:
        return TelegramErrorResponse(error=f"Invalid max_datetime format: {e}")

    try:
        result = await manager.execute(
            _session_client_id,
            _fetch_messages,
            manager.downloader,
            chat_id_str,
            min_dt,
            max_dt,
            limit,
        )
        return TelegramMessagesResponse(
            messages=[TelegramMessage(**msg) for msg in result]
        )

    except AuthKeyUnregisteredError:
        manager.record_error(AuthKeyUnregisteredError())
        return TelegramErrorResponse(
            error="Authentication expired. Please re-authenticate via CLI or GUI.",
            code="AUTH_KEY_UNREGISTERED",
        )

    except FloodWaitError as e:
        manager.record_error(e)
        return TelegramErrorResponse(
            error=f"Rate limited by Telegram. Retry after {e.seconds} seconds.",
            code="FLOOD_WAIT",
            retry_after=e.seconds,
        )

    except RPCError as e:
        manager.record_error(e)
        logger.warning(f"Telegram API error: {e}")
        return TelegramErrorResponse(
            error=f"Telegram API error: {e.message}",
            code="RPC_ERROR",
            rpc_code=e.code if hasattr(e, "code") else None,
        )

    except RuntimeError as e:
        return TelegramErrorResponse(error=str(e))

    except Exception as e:
        manager.record_error(e)
        logger.exception("Unexpected error")
        return TelegramErrorResponse(error=str(e), code="UNKNOWN")


def main():
    """Entry point for the MCP server (stdio transport)."""
    import argparse

    parser = argparse.ArgumentParser(description="Telegram MCP Server")
    parser.add_argument(
        "--transport",
        "-t",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport type (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="HTTP host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8000,
        help="HTTP port (default: 8000)",
    )
    args = parser.parse_args()

    if args.transport == "http":
        main_http(args.host, args.port)
    else:
        mcp.run()


def main_http(host: str = "0.0.0.0", port: int = 8000):
    """Entry point for the MCP server (HTTP transport, no auth)."""
    import uvicorn

    app = mcp.streamable_http_app()
    uvicorn.run(
        app,
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )

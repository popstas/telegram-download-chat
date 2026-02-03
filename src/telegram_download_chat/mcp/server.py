"""MCP server for Telegram chat message retrieval."""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from telethon.errors import (
    AuthKeyUnregisteredError,
    FloodWaitError,
    RPCError,
)

from .connection_manager import ConnectionState, TelegramConnectionManager

logger = logging.getLogger(__name__)

# Global connection manager instance
_manager: Optional[TelegramConnectionManager] = None


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Manage Telegram client lifecycle."""
    global _manager

    _manager = TelegramConnectionManager()
    connected = await _manager.connect()

    if not connected:
        logger.warning("Initial connection failed, will retry on first request")

    try:
        yield
    finally:
        if _manager:
            await _manager.disconnect()
        _manager = None


def with_connection(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to ensure connection is active before executing request.

    Handles reconnection and specific Telethon errors.
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        global _manager

        if _manager is None:
            return json.dumps({"error": "Connection manager not initialized"})

        # Ensure we're connected
        if not await _manager.ensure_connected():
            return json.dumps(
                {
                    "error": "Failed to connect to Telegram",
                    "state": _manager.state.value,
                }
            )

        try:
            result = await func(*args, **kwargs)
            _manager.record_request()
            return result

        except AuthKeyUnregisteredError:
            _manager.record_error(AuthKeyUnregisteredError())
            _manager._state = ConnectionState.ERROR
            return json.dumps(
                {
                    "error": "Authentication expired. Please re-authenticate via CLI or GUI.",
                    "code": "AUTH_KEY_UNREGISTERED",
                }
            )

        except FloodWaitError as e:
            _manager.record_error(e)
            return json.dumps(
                {
                    "error": f"Rate limited by Telegram. Retry after {e.seconds} seconds.",
                    "code": "FLOOD_WAIT",
                    "retry_after": e.seconds,
                }
            )

        except (ConnectionError, OSError) as e:
            _manager.record_error(e)
            logger.warning(f"Connection error: {e}, attempting reconnection...")

            # Try to reconnect and retry once
            if await _manager.reconnect():
                try:
                    result = await func(*args, **kwargs)
                    _manager.record_request()
                    return result
                except Exception as retry_error:
                    _manager.record_error(retry_error)
                    return json.dumps(
                        {"error": f"Retry failed: {retry_error}", "code": "RETRY_FAILED"}
                    )

            return json.dumps(
                {"error": "Connection lost and reconnection failed", "code": "CONNECTION_LOST"}
            )

        except RPCError as e:
            _manager.record_error(e)
            logger.warning(f"Telegram API error: {e}")
            return json.dumps(
                {
                    "error": f"Telegram API error: {e.message}",
                    "code": "RPC_ERROR",
                    "rpc_code": e.code if hasattr(e, "code") else None,
                }
            )

        except Exception as e:
            _manager.record_error(e)
            logger.exception("Unexpected error")
            return json.dumps({"error": str(e), "code": "UNKNOWN"})

    return wrapper


mcp = FastMCP(
    "telegram_chat_mcp",
    lifespan=lifespan,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


@mcp.tool(
    name="telegram_get_messages",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
    },
)
@with_connection
async def telegram_get_messages(
    chat_id: str,
    min_datetime: str,
    limit: int = 100,
) -> str:
    """Get messages from a Telegram chat, from now back to a minimum datetime.

    Args:
        chat_id: Chat identifier (username, phone, or numeric ID)
        min_datetime: Stop at messages older than this datetime (ISO format, e.g., '2026-02-03 17:45:48+00:00')
        limit: Maximum number of messages to return (1-1000, default 100)

    Returns:
        JSON array of messages with id, date, text, and sender info
    """
    global _manager

    downloader = _manager.downloader

    if not downloader.client:
        return json.dumps(
            {
                "error": "Not authenticated. Please authenticate via CLI or GUI first."
            }
        )

    # Parse min_datetime
    min_dt = datetime.fromisoformat(min_datetime)
    if min_dt.tzinfo is None:
        min_dt = min_dt.replace(tzinfo=timezone.utc)

    # Use date part for until_date (downloader's date boundary)
    until_date_str = min_dt.strftime("%Y-%m-%d")

    messages = await downloader.download_chat(
        chat_id=chat_id,
        until_date=until_date_str,
        total_limit=limit,
        request_limit=min(100, limit),
        save_partial=False,
        silent=True,
    )

    result = []
    for msg in messages:
        msg_dict = msg.to_dict() if hasattr(msg, "to_dict") else msg
        serializable = downloader.make_serializable(msg_dict)

        # Filter by exact datetime
        msg_date_str = serializable.get("date")
        if msg_date_str:
            msg_dt = datetime.fromisoformat(msg_date_str.replace("Z", "+00:00"))
            if msg_dt < min_dt:
                continue  # Skip messages older than min_datetime

        result.append(
            {
                "id": serializable.get("id"),
                "date": serializable.get("date"),
                "text": serializable.get("message", ""),
                "from_id": serializable.get("from_id"),
                "reply_to_msg_id": serializable.get("reply_to", {}).get(
                    "reply_to_msg_id"
                )
                if serializable.get("reply_to")
                else None,
            }
        )

    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool(
    name="telegram_connection_status",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
    },
)
async def telegram_connection_status() -> str:
    """Get the current Telegram connection status and diagnostics.

    Returns:
        JSON object with connection state, statistics, and client info.
    """
    global _manager

    if _manager is None:
        return json.dumps(
            {
                "state": "not_initialized",
                "error": "Connection manager not initialized",
            }
        )

    return json.dumps(_manager.get_status(), indent=2)


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

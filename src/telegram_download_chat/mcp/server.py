"""MCP server for Telegram chat message retrieval."""

import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from telethon.errors import (
    AuthKeyUnregisteredError,
    FloodWaitError,
    RPCError,
)

from .connection_manager import TelegramConnectionManager

logger = logging.getLogger(__name__)

# Global connection manager instance
_manager: Optional[TelegramConnectionManager] = None

# Simple client ID for this session (in real MCP, would come from request context)
_session_client_id: str = str(uuid.uuid4())[:8]


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Manage Telegram client lifecycle."""
    global _manager

    _manager = TelegramConnectionManager()
    connected = await _manager.connect()

    if not connected:
        logger.warning("Initial connection failed")

    try:
        yield
    finally:
        if _manager:
            await _manager.disconnect()
        _manager = None


mcp = FastMCP(
    "telegram_chat_mcp",
    lifespan=lifespan,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


async def _fetch_messages(
    downloader,
    chat_id: str,
    min_dt: datetime,
    limit: int,
) -> list[dict]:
    """Fetch messages from Telegram (runs in queue)."""
    if not downloader.client:
        raise RuntimeError("Not authenticated")

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
                continue

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

    return result


@mcp.tool(
    name="telegram_get_messages",
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
    },
)
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

    if _manager is None:
        return json.dumps({"error": "Connection manager not initialized"})

    if not _manager.is_connected:
        return json.dumps({"error": "Not connected to Telegram"})

    # Parse min_datetime
    try:
        min_dt = datetime.fromisoformat(min_datetime)
        if min_dt.tzinfo is None:
            min_dt = min_dt.replace(tzinfo=timezone.utc)
    except ValueError as e:
        return json.dumps({"error": f"Invalid datetime format: {e}"})

    try:
        result = await _manager.execute(
            _session_client_id,
            _fetch_messages,
            _manager.downloader,
            chat_id,
            min_dt,
            limit,
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    except AuthKeyUnregisteredError:
        _manager.record_error(AuthKeyUnregisteredError())
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

    except RuntimeError as e:
        return json.dumps({"error": str(e)})

    except Exception as e:
        _manager.record_error(e)
        logger.exception("Unexpected error")
        return json.dumps({"error": str(e), "code": "UNKNOWN"})


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

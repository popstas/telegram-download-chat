"""MCP server for Telegram chat message retrieval."""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from ..core import DownloaderContext, TelegramChatDownloader

logger = logging.getLogger(__name__)


class GetMessagesInput(BaseModel):
    """Input parameters for telegram_get_messages tool."""

    chat_id: str = Field(
        description="Chat identifier (username, phone, or numeric ID)"
    )
    min_datetime: str = Field(
        description="Minimum message datetime in ISO format (e.g., '2026-02-03 17:45:48+00:00')"
    )
    limit: int = Field(
        default=100, description="Maximum number of messages to return", ge=1, le=1000
    )


# Global downloader instance managed by lifespan
_downloader: Optional[TelegramChatDownloader] = None
_context: Optional[DownloaderContext] = None


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Manage Telegram client lifecycle."""
    global _downloader, _context

    logger.info("Initializing Telegram client...")
    _downloader = TelegramChatDownloader()
    _context = DownloaderContext(_downloader, cli=False)

    try:
        await _context.__aenter__()
        logger.info("Telegram client connected")
        yield
    finally:
        logger.info("Disconnecting Telegram client...")
        if _context:
            await _context.__aexit__(None, None, None)
        _downloader = None
        _context = None
        logger.info("Telegram client disconnected")


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
    global _downloader

    if _downloader is None:
        return json.dumps({"error": "Telegram client not initialized"})

    if not _downloader.client:
        return json.dumps(
            {
                "error": "Not authenticated. Please authenticate via CLI or GUI first."
            }
        )

    try:
        # Parse min_datetime
        min_dt = datetime.fromisoformat(min_datetime)
        if min_dt.tzinfo is None:
            min_dt = min_dt.replace(tzinfo=timezone.utc)

        # Use date part for until_date (downloader's date boundary)
        until_date_str = min_dt.strftime("%Y-%m-%d")

        messages = await _downloader.download_chat(
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
            serializable = _downloader.make_serializable(msg_dict)

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

    except Exception as e:
        logger.exception("Error fetching messages")
        return json.dumps({"error": str(e)})


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

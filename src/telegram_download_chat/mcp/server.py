"""MCP server for Telegram chat message retrieval."""

import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from ..core import DownloaderContext, TelegramChatDownloader

logger = logging.getLogger(__name__)


class GetMessagesInput(BaseModel):
    """Input parameters for telegram_get_messages tool."""

    chat_id: str = Field(
        description="Chat identifier (username, phone, or numeric ID)"
    )
    since_id: int = Field(
        description="Stop fetching when reaching this message ID (exclusive)"
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
    since_id: int,
    limit: int = 100,
) -> str:
    """Get messages from a Telegram chat, from now back to a specific message ID.

    Args:
        chat_id: Chat identifier (username, phone, or numeric ID)
        since_id: Stop fetching when reaching this message ID (exclusive)
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
        messages = await _downloader.download_chat(
            chat_id=chat_id,
            since_id=since_id,
            total_limit=limit,
            request_limit=min(100, limit),
            save_partial=False,
            silent=True,
        )

        result = []
        for msg in messages:
            msg_dict = msg.to_dict() if hasattr(msg, "to_dict") else msg
            serializable = _downloader.make_serializable(msg_dict)

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
    """Entry point for the MCP server."""
    mcp.run()

# MCP Server Module

## Overview

This module provides an MCP (Model Context Protocol) server that exposes Telegram chat functionality to AI assistants like Claude. It allows retrieving messages from Telegram chats through standardized MCP tools.

## Architecture

```
mcp/
├── __init__.py            # Exports main, main_http, mcp
├── server.py              # FastMCP server with tools
├── connection_manager.py  # Telegram connection + task queue
└── AGENTS.md             # This file
```

### Key Components

1. **FastMCP Server** (`server.py`)
   - Uses `mcp.server.fastmcp.FastMCP` for tool registration
   - Lifecycle management via async context manager
   - Supports stdio and HTTP transports

2. **Connection Manager** (`connection_manager.py`)
   - Single persistent Telegram connection (no auto-reconnect)
   - Task queue for serializing API calls
   - Connection statistics for diagnostics

3. **Task Queue**
   - FIFO processing of requests
   - Tracks client IDs for each request
   - Prevents concurrent Telegram API calls

## Design Decisions

### Simplified Connection Model
- Connect once at startup, disconnect at shutdown
- No automatic reconnection - if connection fails, client sees error
- Rationale: Telegram connections are stable; reconnection adds complexity with little benefit

### Task Queue Pattern
- All Telegram API calls go through the queue
- One request processed at a time
- Benefits:
  - Avoids rate limiting from concurrent calls
  - Provides clear request ordering
  - Enables client tracking for diagnostics

### Error Handling
- Telethon errors (FloodWait, AuthKeyUnregistered, RPCError) converted to JSON responses
- No retries - let the client decide
- Errors recorded in stats for monitoring

## MCP Tools

| Tool | Purpose |
|------|---------|
| `telegram_get_messages` | Fetch messages from a chat with datetime filter |

## Running the Server

```bash
# stdio transport (for Claude Desktop)
python -m telegram_download_chat.mcp

# HTTP transport (for debugging/testing)
python -m telegram_download_chat.mcp -t http -p 8000
```

## Configuration

The server uses the same config file as CLI/GUI (`config.yml`). Requires:
- `api_id` and `api_hash` from https://my.telegram.org
- Valid Telethon session (authenticate via CLI or GUI first)

## Testing

No dedicated MCP tests currently. To test manually:
1. Start server: `python -m telegram_download_chat.mcp -t http`
2. Call `telegram_get_messages` with valid chat_id and min_datetime

## When Modifying This Code

- Keep connection logic simple - no reconnection complexity
- All Telegram calls must go through `_manager.execute()`
- Add new tools with `@mcp.tool()` decorator
- Include `readOnlyHint` and `idempotentHint` annotations for tools
- Return JSON strings from tools (MCP protocol requirement)

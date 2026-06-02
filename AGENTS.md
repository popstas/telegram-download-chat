# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram Download Chat is a Python CLI utility that downloads and analyzes Telegram chat history. It provides both command-line and GUI interfaces for downloading messages from chats, groups, channels, or archived exports and saving them in JSON/TXT formats.

### Key Components

- **Core Engine** (`core/` package): Contains `TelegramChatDownloader` plus helper modules (`auth`, `config`, `download`, `entities`, `media`, `messages`, `context`, `render`, `progress`, `comments`, `citations`, `reactions`, `update_checker`) built on Telethon
- **CLI Interface** (`cli.py`): Command-line interface with argument parsing and async message processing
- **GUI Interface** (`gui_app.py`): PySide6-based graphical interface with threading for async operations
- **MCP Server** (`mcp/` package): Model Context Protocol server exposing Telegram chat tools for AI assistants
- **Configuration** (`paths.py`): Handles config file management and application directories

### Architecture

The application follows a modular design:
1. **Configuration Layer**: YAML-based config with API credentials and user settings
2. **Telegram Client Layer**: Telethon wrapper for authenticated API communication
3. **Processing Layer**: Message filtering, date splitting, format conversion
4. **Interface Layer**: CLI and GUI frontends sharing the same core functionality

## Development Commands

Use `.venv` virtual environment.

### Setup Development Environment
```bash
# Install in development mode with all dependencies
pip install -e ".[dev,gui]"

# Or install from requirements
pip install -r requirements.txt
```

### Testing
```bash
# Run tests
pytest

# Run tests with async support
pytest -v

# Run specific test
pytest tests/test_telegram_download_chat.py::TestClass::test_method

# Opt-in end-to-end export tests against a live Telegram group (skipped by default).
# Requires an authenticated session and membership in the test group.
TG_E2E=1 pytest -m e2e   # override the group via TG_E2E_GROUP
```

After export/render changes, save live e2e results to the repo's `./data` directory
(gitignored; the dir is kept via `data/.gitkeep`) rather than a path outside the repo.

### Code Quality
```bash
# Format code
black src/ tests/

# Sort imports
isort src/ tests/

# Type checking
mypy src/
```

### Building
```bash
# Build package
python -m build

# Install from source
pip install .

# Build PyInstaller executables
./build_macos.sh      # macOS
./build_windows.ps1   # Windows
```

### Release
```bash
# Bump version, run tests, build, and publish
python deploy.py patch   # or: minor | major
```
- If a step fails and you re-run, skip the already-completed steps.
- To fold release fixups into the version-bump commit, amend it (`git commit --amend`).

### Running
```bash
# CLI mode
python -m telegram_download_chat username

# GUI mode  
python -m telegram_download_chat gui
# or
telegram-download-chat gui

# From source
python main.py  # Launches GUI by default
```

## Configuration

- Config file auto-created at OS-specific locations (see `paths.py`)
- Requires Telegram API credentials from https://my.telegram.org
- Example config in `config.example.yml`
- Supports optional proxy via `proxy_url` in config or `--proxy-url` CLI flag (socks5/socks4/http)
- GUI provides config editing interface

## Key Features to Understand

### Message Processing
- Downloads via Telethon's `iter_messages()` with pagination
- Supports resume from interruption using temporary files
- Can filter by date ranges, specific users, or message threads
- Outputs JSON (full metadata), TXT (human-readable), and optionally HTML/PDF formats
- Output is organized per-chat: `<chat_name>/messages.json`, `<chat_name>/messages.txt`, optionally `messages.html`/`messages.pdf`, and `<chat_name>/attachments/`

### Authentication
- Uses Telethon sessions for persistent login
- GUI handles phone/code/password flow
- CLI opens browser for authentication

### Filtering & Splitting
- `--subchat`: Extract message threads/replies
- `--split`: Split output by month/year
- `--user`: Filter by specific sender
- `--max-date`: Messages on or before this date
- `--min-date`: Messages on or after this date
- `--media-placeholders`: Insert media type indicators (e.g. `[photo]`, `[file=name.pdf]`) in TXT output
- `--media`: Download all media types with organized category directories (images/, videos/, documents/, audio/, stickers/, contacts/, locations/, polls/, etc.) and concurrent downloads (5 simultaneous). Supports photos, videos, documents, audio, stickers, contacts (VCF), geo locations (JSON), polls, dice, and games. Files above ~5 MB use parallel multi-connection MTProto chunking (FastTelethon-style, see `core/fast_download.py`); connection count auto-tunes per Premium status (Premium=4, free=2) and is overridable via `media_parallel_connections` in config. Threshold is overridable via `media_parallel_threshold_mb`. Earlier defaults (8/4 connections, 1 MB threshold) triggered Telegram's per-account throttling and stalled the run. During long throttled runs, Telegram file references can expire before a file is reached; these are automatically refetched (by message id) and the download is retried once via the standard single-stream downloader.
- `--no-fast-download`: Disable the parallel chunked downloader and fall back to single-stream Telethon for all files.

### Channel Comments
- `--comments` (broadcast-channel only): resolves the channel's linked discussion supergroup (`GetFullChannelRequest` → `linked_chat_id`) and fetches the per-post comment threads via `iter_messages(channel_entity, reply_to=post_id)` (`core/comments.py`). Each comment is normalized so the existing render logic nests it under its post: `reply_to.reply_to_msg_id` and the top-level `reply_to_msg_id` are set to the channel post id, `comment_of=<post_id>` is added, and the native discussion id is preserved as `discussion_msg_id`. Comments are appended into the same `messages.json` (then deduped). Because comments live in a separate id space, comment records (those carrying `comment_of`) are excluded from the post-based resume cursor and `_dedup_messages` keys them by `(comment_of, id)` to avoid collisions with channel post ids.
- `--comments-limit N`: caps comments fetched per post (requires `--comments`; omit/`0`/negative = unlimited). The GUI exposes this as a "Comments per post" dropdown (No limit / 10 / 50 / 100 / 500 / 1000) beside the "Download channel post comments" checkbox.
- A `type: "comments"` structured progress event (posts done/total, comments so far) is emitted per post via `core/progress.py` and surfaced by `gui/worker.py` parallel to the `media` event. Comment fetching is implicitly bounded by the posts' date window, since comments are only fetched for posts actually downloaded.
- Comment media: under `--media`, comments carrying media are downloaded into the chat's `attachments/` dir (reusing `download_all_media`) and each normalized comment dict is stamped with `attachment_path` so the saved JSON keeps it and HTML renders it inline. Comment dicts hold serialized (non-Telethon) media, so the post-media pass skips them and there is no double-download.
- Comment resume: `--comments` runs are checkpointed per post in a `<chat>/messages.comments-progress.json` sidecar (`get_comments_checkpoint_path` / `load_` / `save_` / `clear_comments_checkpoint` in `core/comments.py`). `download_post_comments` invokes an `on_post_done(post_id)` callback after each post is fully scanned (not for transient failures, so a restart retries them); a restart skips already-scanned posts. The checkpoint is cleared on clean completion and on `--overwrite`. Correctness does not depend on it — the `(comment_of, id)` dedup keeps a no-checkpoint re-scan correct, just slower.

### Citations (outside-window replies)
- `core/citations.py`: after a download, `fetch_outside_window_citations` (in `cli/commands.py`) collects reply-target ids that are referenced but not present in `messages` (`collect_missing_cited_ids`) and fetches them by id via `get_messages(ids=...)` so JSON/TXT/HTML show the quoted citation. Runs unconditionally (covers both date-window and finite-`--limit` cases) and is best-effort — failures are logged and skipped. Comment records (`comment_of is not None`) are excluded from both the present-set and the missing-set, and fetched posts can't collide with the comment id-space because dedup keys comments by `(comment_of, id)`.

### Reactions
- `core/reactions.py`: `normalize_reactions` converts Telethon `MessageReactions` into a stable list `[{emoji|custom_emoji_id, count, chosen?, recent?}]`, applied in `messages.py` (`save_messages`) and `render.py`. Idempotent on already-normalized input (resume/convert paths). `render.py` renders them as reaction pills (emoji + count, `chosen` highlighted; custom emoji show a star placeholder with the document id in the tooltip).

### Export Formats
- `--html`: Render a Telegram Web-style HTML page (uses Jinja2 templates). Channel comments render in a collapsible per-post `<details>` block (collapsed shows the comment count); the redundant parent-post citation inside each comment is suppressed.
- `--pdf`: Render a PDF document (uses ReportLab). Comments render inline (interleaved by timestamp) since the PDF path cannot collapse them.
- Both flags work alongside existing JSON/TXT output and can be combined with `--media` for inline images

### Structured GUI Progress
- The core emits machine-readable progress events (`core/progress.py`) as single JSON stdout lines prefixed with `@@TDCPROGRESS@@` (`PROGRESS_PREFIX`), gated by the `TDC_STRUCTURED_PROGRESS` env var (`PROGRESS_ENV_VAR`).
- The GUI worker sets that env var on the CLI subprocess and parses the lines (`parse_progress_line`) into Qt signals instead of scraping log text; normal CLI runs stay clean. Event types: `messages`, `media`, `media_summary`. In-process callers/tests can pass a `sink` callable to `emit_progress`.
- GUI stylesheet helpers live in `gui/utils/styles.py` (e.g. `style_checkboxes`) so unchecked checkboxes match the input background.

### Update Checker (Windows GUI)
- `core/update_checker.py` queries GitHub `releases/latest`, parses the `vX.Y.Z` tag, and compares versions. The installer download URL (`telegram-download-chat.exe`) is resolved on Windows only; other platforms open the releases page.
- Surfaced via the Settings tab "Software Update" group; stale concurrent checks are discarded via a monotonic request-id guard.

### PyInstaller Integration
- Custom hooks in `_pyinstaller/` for bundling
- Platform-specific build scripts
- GUI auto-launches when no CLI args provided

### MCP Server
- Exposes `telegram_get_messages` and `telegram_connection_status` tools
- Uses task queue for serialized API calls
- Supports stdio (Claude Desktop) and HTTP transports
- Run with: `python -m telegram_download_chat.mcp`
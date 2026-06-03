# Telegram Chat Downloader

A powerful command-line, GUI and web interface utility to download and analyze Telegram chat history in multiple formats.

## Features

- Download complete chat history from any Telegram chat, group, supergroup, channel or Telegram export archive
- Download chats folder
- Extract sub-conversations from message threads
- Save messages in JSON format with full message metadata
- Generate human and LLM readable TXT exports with user-friendly display names
- Download media attachments (photos, videos, documents, audio, etc.)
- Use presets for common option sets via `--preset`
- Cross-platform support (Windows, macOS, Linux)
- CLI-first, optional graphical user interface and web interface

## Filtering

- Filter messages by date range
- Filter messages by specific users
- Filter saved messages by keywords
- Filter messages by sub-conversations from message threads


## Usage

For the first run, you will need to log in to your Telegram account. A browser window will open for authentication.

### Basic Commands

```bash
# Download chat by username
telegram-download-chat username

# Download chat by numeric ID (negative for groups/channels)
telegram-download-chat -123456789

# Download chat by invite link
telegram-download-chat https://t.me/+invite_code

# Download chat by phone number (must be in your contacts)
telegram-download-chat +1234567890

# Download multiple chats at once
telegram-download-chat chat1,chat2,chat3
```

### Advanced Usage

```bash
# Download with a limit on number of messages
telegram-download-chat username --limit 1000

# Download all chats from folder 
telegram-download-chat folder:folder_name

# Download messages on or after a specific date (YYYY-MM-DD)
telegram-download-chat username --min-date 2025-05-01

# Download last N days of messages from a specific date
telegram-download-chat username --max-date 2025-06-05 --last-days 1

# Filter messages by specific user
telegram-download-chat group_username --user 123456

# Filter messages containing given keywords (comma-separated, case-insensitive)
telegram-download-chat username --keywords "hello,bye"

# Download messages from a specific thread/reply chain
telegram-download-chat group_username --subchat 12345

# Specify custom output file
telegram-download-chat username -o custom_output.json

# Enable debug logging
telegram-download-chat username --debug

# Download messages with media attachments (photos, videos, documents, etc.)
telegram-download-chat username --media

# Include media type indicators in TXT output (e.g. [photo], [file=report.pdf])
telegram-download-chat username --media-placeholders

# Download a channel together with the comments under each post
telegram-download-chat channel_username --comments

# Cap comments fetched per post (here: 50 per post)
telegram-download-chat channel_username --comments --comments-limit 50

# Keep only comments with at least 2 total reactions
telegram-download-chat channel_username --comments --comments-min-reactions 2

# Include each message's reactions inline in the TXT output
telegram-download-chat username --reactions

# Split output into separate files by month or year
telegram-download-chat username --split month

# Split a forum into one subdirectory per topic
telegram-download-chat group_username --split topics

# Export a Telegram-style HTML page (alongside JSON/TXT)
telegram-download-chat username --html

# Export HTML with clickable media file-path captions
telegram-download-chat username --media --html --html-media-links

# Export a PDF document (alongside JSON/TXT)
telegram-download-chat username --pdf

# Disable parallel multi-connection media downloads (use single-stream)
telegram-download-chat username --media --no-fast-download

# Show current configuration
telegram-download-chat --show-config

# Output results summary as JSON to stdout
telegram-download-chat username --results-json

# Use predefined preset
telegram-download-chat username --preset short

# Resume download starting after a specific message ID
telegram-download-chat username --since-id 5000
```

### Command Line Options

```
usage: telegram-download-chat [-h] [-o OUTPUT] [--limit LIMIT] [--max-date DATE] [--last-days DAYS]
                            [--min-date DATE] [--subchat SUBCHAT]
                            [--subchat-name NAME] [--user USER] [--config CONFIG] [--debug]
                            [--sort {asc,desc}] [--show-config] [-v]
                            [chat]

Download Telegram chat history to JSON and TXT formats.

positional arguments:
  chat                  Chat identifier (username, phone number, chat ID, or URL)

options:
  -h, --help            show this help message and exit
  -o, --output OUTPUT    Output file path (default: chat_<chat_id>.json)
  -l, --limit LIMIT     Maximum number of messages to download (default: 0 - no limit)
  --since-id SINCE_ID  Start downloading after this message ID
  --min-date DATE       Only download messages on or after this date (format: YYYY-MM-DD). Aliases: --until
  --max-date DATE       Only download messages on or before this date (format: YYYY-MM-DD). Aliases: --from
  --last-days DAYS      Number of days back from --max-date (or today) to download
  --subchat SUBCHAT     Filter messages by thread/reply chain (message ID or URL)
  --subchat-name NAME   Custom name for subchat directory
  --user USER           Filter messages by sender ID
  -c, --config CONFIG   Path to config file
  --debug               Enable debug logging
  --sort {asc,desc}     Sort messages by date (default: asc)
  --split {month,year,topics}
                        Split output: by month, by year, or by forum topic
                        (one <chat>/<topic_slug>/ subdirectory per topic)
  --show-config         Show config file location and exit
  --results-json        Output results summary as JSON to stdout
  --keywords KEYWORDS  Only save messages containing these keywords (comma-separated)
  --preset PRESET     Use preset from config
  --media               Download media attachments to a separate folder
  --no-fast-download    Disable parallel multi-connection media downloads (use single-stream Telethon downloader)
  --media-placeholders  Insert media type indicators (e.g. [photo], [file=name.pdf]) in TXT output
  --reactions           Append each message's reactions as an inline text suffix (e.g. [👍5 ❤️2]) in the TXT output
  --html                Export chat as a Telegram-style HTML file (alongside JSON/TXT)
  --html-media-links    Show clickable file path captions under each media element in HTML export
  --pdf                 Export chat as a PDF document (alongside JSON/TXT)
  --comments            Download post comments from a channel's linked discussion group (channel-only; no-op on other entities and channels without comments)
  --comments-limit N    Max comments to fetch per post (requires --comments; omit for unlimited)
  --comments-min-reactions N  Drop comments with fewer than N total reactions before saving (requires --comments; 0 = keep all; applied after --comments-limit)
  --overwrite           Replace existing output files instead of resuming
  --proxy-url URL       Proxy URL for Telegram connection (socks5://host:1080, http://host:8080)
  -v, --version         Show program's version number and exit
```

## Installation

### Prerequisites
- Python 3.8 or higher
- pip (Python package manager)

### Install from PyPI (recommended)

```bash
pip install telegram-download-chat
```

### Using uv (alternative package manager)

Run it directly without installing:

```bash
uvx telegram-download-chat username
```

Or install it as a persistent tool:

```bash
uv tool install telegram-download-chat
```

### GUI Version (Optional)

For those who prefer a graphical interface, a GUI version is available.

Windows build is available in the [releases](https://github.com/popstas/telegram-download-chat/releases/latest) page.

1. Install with GUI dependencies:
   ```bash
   pip install "telegram-download-chat[gui]"
   ```

2. Launch the GUI:
   ```bash
   telegram-download-chat gui
   ```

### Portable Windows build

A portable, no-installer Windows distribution can be produced with
`build_windows_portable.ps1`. Unlike the single-file build (`build_windows.ps1`),
this uses PyInstaller's one-directory mode and packages the result into a
versioned zip:

```powershell
.\build_windows_portable.ps1
```

Outputs:

- `dist\telegram-download-chat\` — the portable folder; run
  `telegram-download-chat.exe` from anywhere, no installation or registry
  changes.
- `dist\telegram-download-chat-portable-<version>.zip` — the distributable zip.
- `dist\telegram-download-chat\manifest.json` — a per-file SHA-256 manifest
  (also packaged via `scripts/package_portable.py`).

**Incremental updates:** the manifest enables file-level incremental updates — an
updater can compare an installed version's manifest against a new one
(`package_portable.diff_manifests`) and copy only the changed/added files,
skipping unchanged runtime DLLs and data files. *Limitation:* PyInstaller bundles
the application's own Python code together with the interpreter inside
`_internal` (the compiled `PYZ` archive), so a release that changes only our
`.py` files still rewrites that archive and it will always appear in the update
set. Cleanly separating the bundled Python runtime from the app code is out of
scope for this minimal portable build.

### Web Interface

A lightweight web interface built with Streamlit is also available.

1. Install with web dependencies:
   ```bash
   pip install "telegram-download-chat[web]"
   ```

2. Launch the web UI:
   ```bash
   telegram-download-chat-web
   ```

## AI agent plugins (Claude, Cursor, Codex)

The CLI ships as an installable skill/plugin for AI coding agents, so you can ask
your agent to "download/export this Telegram chat" and it drives the CLI for you.
All three are generated from one source of truth —
`skills/telegram-download-chat/SKILL.md` — by `scripts/gen_agent_plugins.py`
(a test fails if they drift). After editing the skill, run:

```bash
python scripts/gen_agent_plugins.py
```

- **Claude Code** — add this repo as a plugin marketplace, then install the
  plugin (bundles the skill under `skills/`):
  ```
  /plugin marketplace add popstas/telegram-download-chat
  /plugin install telegram-download-chat
  ```
  Manifests: `.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json`.

- **Cursor** — the project rule `.cursor/rules/telegram-download-chat.mdc` is
  picked up automatically when this repo is open. To use it elsewhere, copy that
  file into the target project's `.cursor/rules/`.

- **Codex** (OpenAI Codex CLI) — copy `.codex/prompts/telegram-download-chat.md`
  into `~/.codex/prompts/` to expose a `/telegram-download-chat` slash command
  (pass the chat id / username / export path as the argument).

## Configuration

### API Credentials

To use this tool, you'll need to obtain API credentials from [my.telegram.org](https://my.telegram.org):

1. Go to [API Development Tools](https://my.telegram.org/apps)
2. Log in with your phone number
   - **Important**: Do not use a VPN when obtaining API credentials
3. Create a new application
4. Copy the `api_id` and `api_hash` to your `config.yml`

### Configuration File

The configuration file is automatically created on first run in your application data directory:
- **Windows**: `%APPDATA%\telegram-download-chat\config.yml`
- **macOS**: `~/Library/Application Support/telegram-download-chat/config.yml`
- **Linux**: `~/.local/share/telegram-download-chat/config.yml`

#### Example Configuration

```yaml
# Telegram API credentials (required)
settings:
  api_id: your_api_id       # Get from https://my.telegram.org
  api_hash: your_api_hash   # Get from https://my.telegram.org
  session_name: session     # Optional: Custom session file name
  request_delay: 1          # Delay between API requests in seconds
  max_retries: 5            # Maximum number of retry attempts
  log_level: INFO           # Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  log_file: app.log        # Path to log file (relative to app dir or absolute)

# Map user IDs to display names for text exports
# Names for users and bots are automatically fetched and stored here, you can change them here.
users_map:
  123456: "Alice"
  789012: "Bob"

# Presets for frequently used argument sets
presets:
  - name: short
    args:
      limit: 100
```

You can also specify a custom config file location using the `--config` flag.

## Advanced Features

### Extract Messages from Telegram Archive

You can extract messages from a Telegram export archive (`result.json`) that you've downloaded from Telegram Desktop:

```bash
# Extract all messages from all chats
telegram-download-chat "/path/to/Telegram Desktop/DataExport/result.json"

# Extract only messages from a specific user (by their Telegram ID)
telegram-download-chat "/path/to/Telegram Desktop/DataExport/result.json" --user 123456

# Save to a custom output file
telegram-download-chat "/path/to/Telegram Desktop/DataExport/result.json" -o my_exported_chats.json
```

This feature is particularly useful for:
- Processing your full Telegram data export
- Extracting specific conversations from the export
- Converting the export to a more readable format
- Filtering messages by user or date range (using `--min-date` or `--last-days`)

The tool will process the archive and generate both JSON and TXT files with the exported messages.

### Resuming Interrupted Downloads
If the download is interrupted, you can simply run the same command again to resume from where it left off. The tool automatically saves progress to a temporary file.
You can also resume later using `--since-id` with the last downloaded message ID or let the tool read it from the existing JSON file. Use `--overwrite` to replace existing output files instead of resuming.

Interrupted `--comments` runs resume per-post via a `[chat_name]/messages.comments-progress.json` checkpoint, so a restart skips posts whose comments were already fetched. The checkpoint is cleared on clean completion and when `--overwrite` is used.

### User Mapping
Display names for users and bots are collected automatically. You can override them in the `users_map` section:

```yaml
users_map:
  123456: "Alice Smith"
  789012: "Bob Johnson"
```

### Chat Mapping
Titles for group and channel chats are fetched automatically. Use `chats_map` only if you want to override them:

```yaml
chats_map:
  100123456: "MyGroup"
```

### Keyword Filtering
Use `--keywords` to save only messages that contain at least one of the given words. This reduces output size when you need messages about specific topics.

- **Behavior**: After downloading (within your date/limit), messages are filtered; only those whose text contains at least one keyword (case-insensitive) are written to JSON and TXT.
- **Format**: Comma-separated list, e.g. `--keywords "word1,word2,@user"`.
- **Result**: The summary (and `--results-json`) still includes a `keywords` block with counts and sample messages per keyword.

```bash
# Save only messages containing "после" or "hello"
telegram-download-chat username --min-date 2026-01-01 --keywords "после,hello"
```

### Subchat Extraction
Extract conversations from specific threads or reply chains:

```bash
# Extract messages from a specific thread
telegram-download-chat group_username --subchat 12345 --subchat-name "Important Discussion"

# Or use a direct message URL
telegram-download-chat group_username --subchat "https://t.me/c/123456789/12345"
```

## Graphical User Interface (GUI)

For users who prefer a visual interface, the application includes an optional GUI that provides an intuitive way to download Telegram chats.

### Launching the GUI

```bash
# Launch the GUI application
telegram-download-chat gui
```

### Choosing What to Download (Chat Identifiers)

The large **Chat** field at the top of the Download tab accepts the same
identifiers as the CLI's positional `chat` argument (`@username, link or
chat_id`). Enter exactly one of the following, depending on what you want to
download:

| What you want to download | What to type in the Chat field | Notes |
|---------------------------|--------------------------------|-------|
| Your own **Saved Messages** | `me` | `me` always resolves to your own account, so its message history is your Saved Messages. You can also use your own `@username` or numeric user ID. |
| A **private group** you belong to | the invite link, e.g. `https://t.me/+AbCdEf123456`, or the group's numeric ID (negative, e.g. `-1001234567890`) | You must already be a member — the tool downloads through your account and cannot join on your behalf. Private groups have no public `@username`, so use the invite link or the numeric ID. |
| A **public** chat, group or channel | `@username` or its `https://t.me/username` link | Public entities can be addressed by their `@username`. |

Tips:

- The invite link is the same `t.me/+…` link you used to join the private group;
  open the group in Telegram → group name → **Invite Links** to copy it again.
- To find a numeric ID, run the CLI once with `--debug`, or check the
  `chats_map` / `users_map` entries written to your `config.yml` after a first
  download.
- All other fields (limit, dates, media, HTML/PDF, etc.) under **Settings**
  apply to whichever chat you entered.
- For broadcast channels, the **Download channel post comments** checkbox (with a
  **Comments per post** limit dropdown: No limit / 10 / 50 / 100 / 500 / 1000)
  fetches the comment threads from the channel's linked discussion group. Comments
  are merged into the same `messages.json`; in the HTML export they render in a
  collapsible per-post block (collapsed shows the comment count), and in TXT/PDF
  they nest under their parent post. Under `--media`, comment attachments are
  downloaded into the chat's `attachments/` folder and rendered inline in HTML
  like post media.

This help is also shown inside the app: click **ⓘ How to fill this?** under the
field to expand the full list. An **ⓘ** icon with a hover tooltip next to the
Chat label is also available but off by default. Toggle either via
`gui_chat_hint_tooltip` (default off) / `gui_chat_hint_help` (default on) in
`config.yml`.

### Checking for Updates

The **Settings** tab has a **Software Update** group showing the current
version. Click **Check updates** to query GitHub for the latest release. If a
newer version is available the button is replaced by **Download**: on Windows it
fetches the `telegram-download-chat.exe` asset directly, and on other platforms
it opens the releases page in your browser.

## Output Formats

The tool generates the following files for each chat:

### JSON Output (`[chat_name]/messages.json`)
Contains complete message data including metadata like:
- Message IDs and timestamps
- Sender information
- `user_display_name` from `users_map`
- Message content (including formatting)
- Reply information
- Media and file attachments
- Reactions and views
- `attachment_path` — relative path to the downloaded media file (when `--media` is used)

### Text Output (`[chat_name]/messages.txt`)
A human-readable version of the chat with:
- Formatted timestamps
- Display names from your `users_map`, `sender name` -> `recipient name`
- Message content with basic formatting
- Reply indicators
- Optional media type indicators with `--media-placeholders` (e.g. `[photo]`, `[video]`, `[file=report.pdf]`)
- Optional inline reactions with `--reactions` (e.g. `Nice post [👍5 ❤️2]`; custom/premium emoji show as `⭐`)

### Media Attachments (`[chat_name]/attachments/`)
When using the `--media` flag, media files are downloaded alongside the message files, organized by media type:

```
[chat_name]/
├── messages.json
├── messages.txt
└── attachments/
    ├── images/
    │   └── 12345_123456789000.jpg
    ├── videos/
    │   └── 12346_2937458923.mp4
    ├── documents/
    │   └── 12347_report.pdf
    ├── audio/
    ├── stickers/
    ├── archives/
    ├── contacts/
    ├── locations/
    ├── polls/
    └── other/
```

Files are named `<message_id>_<original_filename>` and sorted into category subdirectories.

### HTML / PDF Export (`[chat_name]/messages.html`, `[chat_name]/messages.pdf`)

Generated when the `--html` / `--pdf` flags are used (alongside the usual JSON/TXT output, and combinable with `--media` for inline images). Both render inline Telegram formatting — **bold**, *italic*, underline, strikethrough, `code`, spoilers, and links (only `http(s)`, `mailto`, and `tg` schemes are kept; bare domains default to `https://`; others such as `javascript:` are stripped). The HTML view additionally:

- Groups messages into reply threads separated by a thread header.
- Turns reply quotes into clickable links that jump to the cited message (when that message is part of the export).
- Renders reaction pills (emoji + count) under each message, mirroring the Telegram client; the reaction you chose is highlighted, and custom/premium emoji show a star placeholder with the document id in a tooltip.
- Renders channel-post comments as a collapsible block per post (collapsed shows "N comments").
- Shows a "top N%" comment filter bar (when the page has comments): buttons for All / Top 50% / 20% / 10% / 5%, each labeled with the computed reaction threshold and matching comment count (e.g. `Top 20%: 3+ (12)`). Clicking hides comments below that reaction count live in the browser; nothing is removed from the export.

When a downloaded reply cites a message whose date falls outside the requested `--min-date`/`--max-date` window (or a finite `--limit`), that referenced message is automatically fetched by id so the quoted citation is populated in JSON/TXT/HTML.

The TXT and JSON output is unchanged by these flags.

Supported media types:
- **Photos**: Downloaded as JPG files
- **Videos**: Including video messages and round videos
- **Documents**: PDFs, archives, office files, etc.
- **Audio**: Music files and audio messages
- **Voice messages**: Voice recordings
- **Stickers**: Including animated stickers
- **Contacts**: Saved as VCF files
- **Locations**: Geo coordinates saved as JSON
- **Polls**: Poll data saved as JSON

### Example Output Structure

```
2025-05-25 10:30:15 Alice -> MyGroup:
Hello everyone!

2025-05-25 10:31:22 Bob -> MyGroup (replying to Alice):
Hi Alice! How are you?

2025-05-25 10:32:45 Charlie -> MyGroup:
Welcome to the group!
```

## Use Cases

### Learning and Research
- Download study group discussions for offline review
- Archive Q&A sessions for future reference
- Collect data for linguistic or social research

### Team Collaboration
- Archive work-related group chats
- Document important decisions and discussions
- Create searchable knowledge bases from team conversations

### Personal Use
- Backup important personal conversations
- Organize saved messages and notes
- Analyze your own communication patterns over time

### Data Analysis
- Export chat data for sentiment analysis
- Track topic trends in community groups
- Generate statistics on message frequency and engagement

### Content Creation
- Collect discussions for content inspiration
- Reference past conversations for accuracy
- Archive community feedback and suggestions

## Troubleshooting

### Common Issues

1. **API Errors**
   - Ensure your API credentials are correct
   - Try disabling VPN if you're having connection issues
   - Check if your account is not restricted

2. **Missing Messages**
   - Some messages might be deleted or restricted
   - Check if you have the necessary permissions in the chat
   - Try with a smaller limit first

3. **Slow Downloads**
   - The tool respects Telegram's rate limits
   - Increase `request_delay` in config for more reliable downloads
   - Consider using a smaller `limit` parameter
4. **Progress bar**
   - progress show 1000 messages by default
   - when current > 1000, set max to 10000, then 50000, then 100000, etc.
5. **Session file locked on Windows**
   - Sometimes the `session.session` file cannot be deleted during logout
### Getting Help

If you encounter any issues, please:
1. Check the logs in `app.log` (by default in the application directory)
2. Run with `--debug` flag for detailed output
3. Open an issue on [GitHub](https://github.com/popstas/telegram-download-chat/issues)

## MCP Server (for AI Assistants)

The package includes an MCP (Model Context Protocol) server that allows AI assistants like Claude to retrieve messages from your Telegram chats.

### Installation

```bash
pip install "telegram-download-chat[mcp]"
```

### Running the Server

```bash
# stdio transport (for Claude Desktop)
python -m telegram_download_chat.mcp

# HTTP transport (for debugging/testing)
python -m telegram_download_chat.mcp -t http -p 8000
```

### Claude Desktop Configuration

Add to your Claude Desktop config file (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "telegram": {
      "command": "python",
      "args": ["-m", "telegram_download_chat.mcp"]
    }
  }
}
```

Or using uvx:

```json
{
  "mcpServers": {
    "telegram": {
      "command": "uvx",
      "args": ["--from", "telegram-download-chat[mcp]", "telegram-download-chat-mcp"]
    }
  }
}
```

### Available Tools

| Tool | Description |
|------|-------------|
| `telegram_get_messages` | Fetch messages from a chat with datetime filter |

### Prerequisites

Before using the MCP server, you must authenticate via CLI or GUI at least once to create a valid Telegram session.

## Testing

Run the standard test suite (fast, no network):

```bash
pytest
```

### Running the e2e suite

The end-to-end export tests (`tests/test_e2e_export.py`, marked `@pytest.mark.e2e`)
validate the HTML/PDF export against a live private Telegram group that contains
all formatting, replies, and reposts. They are **skipped by default** and are not
part of CI, because they require:

- Real API credentials in your `config.yml` (`api_id` / `api_hash`, not the
  placeholders), and
- An authenticated `session.session` for an account that is a **member** of the
  test group.

Enable them explicitly with the `TG_E2E` opt-in and the `e2e` marker:

```bash
# Run only the e2e export tests against the default test group
TG_E2E=1 pytest -m e2e

# Override the target group (must be an account you are a member of)
TG_E2E=1 TG_E2E_GROUP="https://t.me/+XXXXXXXX" pytest -m e2e
```

The e2e download uses `--overwrite` (a clean download) so the export reflects the
live group rather than a cached/resumed partial. When `TG_E2E` is unset, or the
credentials/session are missing, the tests skip with a clear reason and the
default `pytest` run is unaffected.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

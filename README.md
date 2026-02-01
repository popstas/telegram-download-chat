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


## Installation

### Prerequisites
- Python 3.8 or higher
- pip (Python package manager)

### Install from PyPI (recommended)

```bash
pip install telegram-download-chat
```

### Using uvx (alternative package manager)

```bash
uvx install git+https://github.com/popstas/telegram-download-chat.git
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
  --show-config         Show config file location and exit
  --results-json        Output results summary as JSON to stdout
  --keywords KEYWORDS  Only save messages containing these keywords (comma-separated)
  --preset PRESET     Use preset from config
  --media               Download media attachments to a separate folder
  --overwrite           Replace existing output files instead of resuming
  -v, --version         Show program's version number and exit
```

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
telegram-download-chat --gui
```

## Output Formats

The tool generates the following files for each chat:

### JSON Output (`[chat_name].json`)
Contains complete message data including metadata like:
- Message IDs and timestamps
- Sender information
- `user_display_name` from `users_map`
- Message content (including formatting)
- Reply information
- Media and file attachments
- Reactions and views

### Text Output (`[chat_name].txt`)
A human-readable version of the chat with:
- Formatted timestamps
- Display names from your `users_map`, `sender name` -> `recipient name`
- Message content with basic formatting
- Reply indicators

### Media Attachments (`[chat_name]_attachments/`)
When using the `--media` flag, media files are downloaded to a separate folder with the following structure:

```
[chat_name]_attachments/
├── 12345/                    # Message ID
│   └── 123456789000.jpg      # Downloaded media file
├── 12346/
│   └── 2937458923.pdf
└── 12347/
    └── 9832749823498723.mp4
```

Each message's media is stored in a directory named after the message ID.

Supported media types:
- **Photos**: Downloaded as JPG files
- **Videos**: Including video messages and round videos
- **Documents**: PDFs, archives, office files, etc.
- **Audio**: Music files and audio messages
- **Voice messages**: Voice recordings
- **Stickers**: Including animated stickers

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

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

# Telegram Chat Downloader

[![PyPI](https://img.shields.io/pypi/v/telegram-download-chat)](https://pypi.org/project/telegram-download-chat/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/pypi/pyversions/telegram-download-chat)](https://pypi.org/project/telegram-download-chat/)
[![Coverage Status](https://coveralls.io/repos/github/popstas/telegram-download-chat/badge.svg?branch=main)](https://coveralls.io/github/popstas/telegram-download-chat?branch=main)

A powerful command-line utility to download and analyze Telegram chat history in multiple formats.

## Features

- Download complete chat history from any Telegram chat, group, channel or Telegram export archive
- Download chats folder
- Save messages in JSON format with full message metadata
- Generate human and LLM readable TXT exports with user-friendly display names
- Filter messages by date range and specific users
- Extract sub-conversations from message threads
- Output results summary in JSON format
- Search messages for specific keywords
- Use presets for common option sets via `--preset`
- Cross-platform support (Windows, macOS, Linux)
- Optional graphical user interface (GUI) for easier interaction
- Core functionality resides under the `telegram_download_chat.core` package for easier maintenance.

## Project Structure

The codebase follows a source layout with dedicated subpackages:

```
src/telegram_download_chat/
├── core/           # Download engine and helpers
│   ├── downloader.py   # `TelegramChatDownloader` class
│   ├── auth.py         # login utilities
│   ├── config.py       # configuration loading helpers
│   ├── download.py     # chat download routines
│   ├── entities.py     # user and chat name helpers
│   ├── messages.py     # message formatting utilities
│   └── context.py      # async context manager
├── cli/            # Command line interface
├── gui/            # GUI application
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


## Installation

### Prerequisites
- Python 3.8 or higher
- pip (Python package manager)

### GUI Version (Optional)

For those who prefer a graphical interface, a GUI version is available. To use it:

1. Install with GUI dependencies:
   ```bash
   pip install "telegram-download-chat[gui]"
   ```

2. Launch the GUI:
   ```bash
   telegram-download-chat gui
   ```

The GUI provides an easy-to-use interface with the following features:
- Download chat history with configurable options
- Convert exported JSON data to other formats
- Real-time log viewing
- File preview functionality
- Browse and open downloaded files

### Streamlit Web Interface (Optional)

A lightweight web interface built with Streamlit is also available.
It provides a subset of common command line options and shows progress
while downloading.

1. Install with web dependencies:
   ```bash
   pip install "telegram-download-chat[web]"
   ```

2. Launch the web UI:
   ```bash
   telegram-download-chat-web
   ```

### Install from PyPI (recommended)

```bash
pip install telegram-download-chat
```

### Using uvx (alternative package manager)

```bash
uvx install git+https://github.com/popstas/telegram-download-chat.git
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
# Names for users and bots are automatically fetched and stored here
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

# Download messages until a specific date (YYYY-MM-DD)
telegram-download-chat username --until 2025-05-01

# Download last N days of messages from a specific date
telegram-download-chat username --from 2025-06-05 --last-days 1

# Filter messages by specific user
telegram-download-chat group_username --user 123456

# Download messages from a specific thread/reply chain
telegram-download-chat group_username --subchat 12345

# Specify custom output file
telegram-download-chat username -o custom_output.json

# Enable debug logging
telegram-download-chat username --debug

# Show current configuration
telegram-download-chat --show-config

# Output results summary as JSON
telegram-download-chat username --results-json

# Search chat for keywords
telegram-download-chat username --keywords "@user,hello"

# Use predefined preset
telegram-download-chat username --preset short
```

### Command Line Options

```
usage: telegram-download-chat [-h] [-o OUTPUT] [--limit LIMIT] [--from DATE] [--last-days DAYS]
                            [--until DATE] [--subchat SUBCHAT]
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
  --from DATE           Base date for --last-days (format: YYYY-MM-DD)
  --last-days DAYS      Number of days back from --from (or today) to download
  --until DATE          Only download messages until this date (format: YYYY-MM-DD)
  --subchat SUBCHAT     Filter messages by thread/reply chain (message ID or URL)
  --subchat-name NAME   Custom name for subchat directory
  --user USER           Filter messages by sender ID
  -c, --config CONFIG   Path to config file
  --debug               Enable debug logging
  --sort {asc,desc}     Sort messages by date (default: asc)
  --show-config         Show config file location and exit
  --results-json        Output results summary as JSON to stdout
  --keywords KEYWORDS  Comma-separated keywords to search in messages
  --preset PRESET     Use preset from config
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
- Filtering messages by user or date range (using `--until` or `--last-days`)

The tool will process the archive and generate both JSON and TXT files with the exported messages.

### Resuming Interrupted Downloads
If the download is interrupted, you can simply run the same command again to resume from where it left off. The tool automatically saves progress to a temporary file.

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

### GUI Features

The GUI provides all the functionality of the command-line interface with additional user-friendly features:

#### Main Interface
- **Chat Input**: Enter chat identifier (username, phone number, chat ID, or URL)
- **Output Directory**: Select where to save downloaded files
- **Download Options**: Configure limit, date filters, and other parameters
- **Progress Tracking**: Real-time progress bar showing download status
- **File List**: View all downloaded files with easy access

#### Advanced Options
- **Message Limit**: Set maximum number of messages to download
- **Date Filter**: Download messages only until a specific date
- **User Filter**: Filter messages by specific sender
- **Subchat Extraction**: Extract messages from specific threads
- **Debug Mode**: Enable detailed logging for troubleshooting

#### Smart Download Management
- **Pause/Resume**: Stop and resume downloads at any time
- **Message Saving**: When you stop a download, all messages that were already fetched are automatically saved
- **Progress Persistence**: Downloads can be resumed from where they left off
- **File Organization**: Downloaded files are automatically organized and displayed

#### Stop and Save Functionality
One of the key GUI features is the ability to stop downloads while preserving progress:

1. **During Download**: Click the "Stop" button to halt the current download
2. **Automatic Saving**: The application will save all messages that were already downloaded
3. **User Feedback**: You'll see a message like "Stopping download and saving messages..."
4. **File Collection**: After stopping, the GUI will display "Messages saved successfully! Found X file(s)."
5. **File Access**: All saved files are immediately available in the file list

This feature is particularly useful for:
- Large chats where you want to preview initial messages
- Testing downloads before committing to full extraction
- Situations where you need to stop due to time constraints
- Recovering partial downloads when issues occur

### GUI vs Command Line

| Feature | GUI | Command Line |
|---------|-----|--------------|
| Ease of use | Intuitive interface | Requires command knowledge |
| Progress tracking | Visual progress bar | Text-based progress |
| File management | Integrated file browser | Manual file navigation |
| Stop/Resume | One-click stop with auto-save | Manual interruption |
| Configuration | Visual forms | Manual config editing |
| Batch operations | One chat at a time | Scriptable |
| Automation | Interactive only | Fully scriptable |

## Streamlit Web Interface

In addition to the desktop GUI, a basic web interface built with
Streamlit is available for quick access from the browser. The web UI
provides controls for all CLI arguments, displays download progress and
lets you download the resulting TXT file with a small preview.

```bash
telegram-download-chat-web
```

The web interface provides a simple form to input chat identifiers and
download a limited number of messages.

## Output Formats

The tool generates the following files for each chat:

### JSON Output (`[chat_name].json`)
Contains complete message data including metadata like:
- Message IDs and timestamps
- Sender information
- Message content (including formatting)
- Reply information
- Media and file attachments
- Reactions and views

### Text Output (`[chat_name].txt`)
A human-readable version of the chat with:
- Formatted timestamps
- Display names from your `users_map`
- Message content with basic formatting
- Reply indicators

### Example Output Structure

```
2025-05-25 10:30:15 Alice -> MyGroup:
Hello everyone!

2025-05-25 10:31:22 Bob -> MyGroup (replying to Alice):
Hi Alice! How are you?

2025-05-25 10:32:45 Charlie -> MyGroup:
Welcome to the group!
```

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

For releasing a new version to PyPI, run the deploy script with a bump level:

```bash
python deploy.py patch  # or minor/major
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

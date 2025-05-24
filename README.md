# Telegram Chat Downloader

[![PyPI](https://img.shields.io/pypi/v/telegram-download-chat)](https://pypi.org/project/telegram-download-chat/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/pypi/pyversions/telegram-download-chat)](https://pypi.org/project/telegram-download-chat/)

A command-line utility to download Telegram chat history to JSON and TXT format.

## Features

- Download complete chat history from any Telegram chat, group, or channel
- Save messages in JSON format with full message metadata
- Save messages in TXT format with user-friendly display names
- Support for resuming interrupted downloads


## Usage Examples

Here are some practical use cases for the tool:

- **Learning and Research**
  - Find a Telegram group about a new topic you're studying
  - Download the entire chat history
  - Get a summary of the discussions using the generated text files

- **Social Analysis**
  - Download chat history from your friends' group
  - Analyze topics and conversations
  - Get insights about who talks about what

- **Personal Communication Analysis**
  - Download your personal chat history
  - Study the chronology of your conversations
  - Analyze communication patterns over time

- **Recent Discussions Analysis**
  - Download the last 1000 messages from a chat
  - Get a summary of recent discussions
  - Filter messages by date to analyze specific time periods

- **Saved Messages**
  - Download your saved messages (favorites)
  - Requires specifying your username
  - Useful for organizing and analyzing important conversations

**Note**: The generated text files can be loaded into Google NotebookLM for further analysis. However, loading histories larger than 10,000 messages may cause issues.


## Installation

### Using pip

```bash
pip install telegram-download-chat
```

### Using uvx

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

### Configuration File (config.yml)

```yaml
telegram_app:
  api_id: your_api_id       # Get from https://my.telegram.org
  api_hash: your_api_hash   # Get from https://my.telegram.org

# Map user IDs to display names for text exports
users_map:
  123456: "Alice"
  789012: "Bob"

# full settings: see config.example.yml
```

## Usage

For the first run, you will need to log in to your Telegram account.

### Basic Usage

```bash
telegram-download-chat target
```

Where `target` can be:

- Chat/Group/Channel/User ID (e.g., `-123456789`)
- Username (e.g., `username`)
- Group URL (e.g., `https://t.me/group_name`)
- Invite link (e.g., `https://t.me/+invite_code`)
- Phone number (e.g., `+1234567890`)

```bash
# Download chat by username
telegram-download-chat username

# Download chat by numeric ID (negative for groups/channels)
telegram-download-chat -123456789

# Download chat by invite link
telegram-download-chat https://t.me/+invite_code

# Download chat by phone number (must be in your contacts)
telegram-download-chat +1234567890
```

### Advanced Usage

```bash
# Download with a limit on number of messages
telegram-download-chat username --limit 1000

# Download messages until a specific date (YYYY-MM-DD)
telegram-download-chat username --until 2025-05-01

# Specify custom output file
telegram-download-chat username -o my_chat_history.json

# Enable debug logging
telegram-download-chat username --debug

# Download last 100 messages from channel
telegram-download-chat https://t.me/group_name --limit 100

# Convert JSON to TXT with subchat filtering and custom directory name
telegram-download-chat big_chat.json --subchat 104888 --subchat-name "my_subchat"
```


### Command Line Options

```
usage: telegram-download-chat [-h] [-o OUTPUT] [--limit LIMIT] [--until DATE] [-s] chat

Download Telegram chat history to JSON

positional arguments:
  chat                  Chat identifier (group URL, @username, phone number, or invite link)

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output JSON filename (default: chat_history.json)
  --limit LIMIT         Number of messages per API request (50-1000, default: 500)
  --until DATE          Only download messages until this date (format: YYYY-MM-DD)
  --subchat SUBCHAT     Filter messages for txt by subchat id or URL (only with --json)
  --subchat-name NAME   Name for the subchat directory (default: subchat_<subchat_id>)
  -s, --silent          Suppress progress output (default: False)
```

## Output Format

The tool generates two files for each chat:
1. `[chat_name].json` - Complete message data in JSON format
2. `[chat_name].txt` - Human-readable text version of the chat

# Telegram Chat Downloader

[![PyPI](https://img.shields.io/pypi/v/telegram-download-chat)](https://pypi.org/project/telegram-download-chat/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/pypi/pyversions/telegram-download-chat)](https://pypi.org/project/telegram-download-chat/)

A command-line utility to download Telegram chat history to JSON and TXT format.

## Features

- Download complete chat history from any Telegram chat, group, or channel
- Save messages in JSON format with full message metadata
- Save messages in TXT format with user-friendly display names
- Simple configuration with YAML config file
- Support for resuming interrupted downloads

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

```bash
# Download private chat with username
telegram-download-chat username

# Download messages from group by invite link until a specific date (exclusive)
telegram-download-chat https://t.me/+_m82VpT1ipg2f8dj --until 2025-05-01

# Download last 100 messages from channel
telegram-download-chat https://t.me/popstas_music --limit 100
```


### Command Line Options

```
usage: telegram-download-chat [-h] [-o OUTPUT] [--limit LIMIT] [--until DATE] [-s] chat

Download Telegram chat history to JSON

positional arguments:
  chat                  Chat identifier (group URL, @username, or invite link)

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output JSON filename (default: chat_history.json)
  --limit LIMIT         Number of messages per API request (50-1000, default: 500)
  --until DATE          Only download messages until this date (format: YYYY-MM-DD)
  -s, --silent          Suppress progress output (default: False)
```

## Output Format

The tool generates two files for each chat:
1. `[chat_name].json` - Complete message data in JSON format
2. `[chat_name].txt` - Human-readable text version of the chat

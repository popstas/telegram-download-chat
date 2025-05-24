
#!/usr/bin/env python3
"""telegram-download-chat.py — CLI-утилита для выгрузки всей доступной истории Telegram-чата в JSON.

Использование:
    python telegram-download-chat.py https://t.me/some_chat -o history.json

Требования:
    pip install -r requirements.txt
"""

import argparse
import asyncio
import json
import os
import re
import pickle
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import Message, PeerUser
from telethon.errors import FloodWaitError
import yaml


def load_config(config_path: str = "config.yml") -> Dict[str, Any]:
    """Load configuration from YAML file.
    
    Args:
        config_path: Path to the configuration file
        
    Returns:
        Dictionary containing the configuration
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config or {}
    except FileNotFoundError:
        print(f"Warning: Configuration file {config_path} not found, using defaults")
        return {}
    except yaml.YAMLError as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        sys.exit(1)


def get_config_value(config: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely get a value from nested dictionaries.
    
    Args:
        config: Configuration dictionary
        *keys: Nested keys to traverse
        default: Default value if key is not found
        
    Returns:
        The value if found, otherwise the default value
    """
    value = config
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    return value


def parse_args() -> argparse.Namespace:
    # Load configuration first
    config = load_config()
    
    # Get default values from config
    default_output = get_config_value(
        config, "settings", "default_output", default="chat_history.json"
    )
    default_limit = get_config_value(
        config, "settings", "fetch_limit", default=500
    )
    default_session = get_config_value(
        config, "settings", "session", "filename", default="session"
    )
    default_silent = not get_config_value(
        config, "settings", "behavior", "show_progress", default=True
    )
    default_debug = get_config_value(
        config, "settings", "behavior", "debug", default=False
    )
    
    # Get API credentials from config if not in environment
    default_api_id = os.getenv("TELEGRAM_API_ID") or get_config_value(
        config, "telegram_app", "api_id"
    )
    default_api_hash = os.getenv("TELEGRAM_API_HASH") or get_config_value(
        config, "telegram_app", "api_hash"
    )
    
    # Set up argument parser with config defaults
    parser = argparse.ArgumentParser(
        description="Dump Telegram chat history to JSON",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    
    # Required argument (but only when not using --json)
    parser.add_argument(
        "chat",
        nargs="?",
        help="Ссылка (@username) или numeric id чата/канала/группы",
    )
    
    # Optional arguments with config defaults
    save_path_prefix = get_config_value(config, "settings", "save_path", default="./data/chats")
    parser.add_argument(
        "-o", "--output",
        default=default_output,
        help="Имя выходного файла (без расширения)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Конвертировать существующий JSON-файл в TXT и выйти (без скачивания)",
    )
    parser.add_argument(
        "--subchat",
        type=str,
        help="Фильтровать сообщения по reply_to.reply_to_msg_id или reply_to.reply_to_top_id == SUBCHAT (только с --json)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=default_limit,
        help="Количество сообщений, запрашиваемых за один вызов API (50-1000)",
    )
    parser.add_argument(
        "-s", "--silent",
        action="store_true",
        default=default_silent,
        help="Не выводить прогресс на экран",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=default_debug,
        help="Выводить отладочную информацию",
    )
    
    # Hidden arguments for backward compatibility
    hidden = parser.add_argument_group('hidden arguments')
    hidden.add_argument(
        "--api-id",
        type=int,
        default=default_api_id,
        help=argparse.SUPPRESS,
    )
    hidden.add_argument(
        "--api-hash",
        default=default_api_hash,
        help=argparse.SUPPRESS,
    )
    hidden.add_argument(
        "--session",
        default=default_session,
        help=argparse.SUPPRESS,
    )
    
    args = parser.parse_args()
    
    # Prepend save_path to output if not absolute
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path(save_path_prefix) / output_path
    args.output = str(output_path)

    # If not in --json mode, chat is required
    if not getattr(args, 'json', False) and not args.chat:
        parser.error("argument chat is required unless --json is specified")

    # Validate required API credentials (only if not --json)
    if not getattr(args, 'json', False):
        if not args.api_id or not args.api_hash:
            print("Ошибка: Необходимо указать api_id и api_hash (через config.yml, переменные окружения или флаги)", file=sys.stderr)
            sys.exit(1)
    return args


def convert_datetime(obj):
    """Convert datetime objects to ISO format strings."""
    from datetime import datetime, date
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    # Return the object as-is if it's not a datetime
    return str(obj)

def make_serializable(obj):
    """Recursively make an object JSON serializable."""
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [make_serializable(x) for x in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        # Try to convert to string as a last resort
        try:
            return str(obj)
        except Exception:
            return None

def get_users_map() -> dict:
    try:
        config = load_config()
        return config.get('users_map', {})
    except Exception:
        return {}

async def save_messages_as_txt(messages: List[dict], txt_path: Path, client=None) -> int:
    """Save messages to TXT in the requested format, using users_map if available. Optionally fetch unknown usernames."""
    users_map = get_users_map()
    config_path = 'config.yml'
    config = load_config(config_path)
    fetch_limit = get_config_value(config, 'settings', 'fetch_usernames_limit', default=10)
    unknown_user_ids = set()
    # First pass: collect unknown user_ids
    for msg in messages:
        sender = msg.get('from_id') or msg.get('sender_id') or ''
        if isinstance(sender, dict):
            sender = sender.get('user_id') or sender.get('channel_id') or sender.get('chat_id') or ''
        else:
            sender = msg.get('peer_id', {}).get('user_id') or ''
        try:
            sender_id = int(sender)
        except Exception:
            continue
        if sender_id and sender_id not in users_map:
            unknown_user_ids.add(sender_id)
        if len(unknown_user_ids) >= fetch_limit:
            break
    # Fetch usernames if client is provided
    fetched_map = {}
    if client and unknown_user_ids:
        for uid in list(unknown_user_ids)[:fetch_limit]:
            try:
                user = await client.get_entity(PeerUser(uid))
                name = user.first_name or user.username or user.last_name or str(uid)
                if user.last_name and user.first_name:
                    name = f"{user.first_name} {user.last_name}"
                fetched_map[uid] = name
            except Exception as e:
                fetched_map[uid] = str(uid)
        # Update users_map in config and save
        if fetched_map:
            if 'users_map' not in config:
                config['users_map'] = {}
            for k, v in fetched_map.items():
                config['users_map'][k] = v
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config, f, allow_unicode=True)
            users_map.update(fetched_map)
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    saved = 0
    with txt_path.open("w", encoding="utf-8") as f:
        for msg in messages:
            try:
                # Parse date
                date_str = msg.get('date', '')
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.split('+')[0])
                        date_fmt = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except Exception:
                        date_fmt = date_str
                else:
                    date_fmt = ''
                # Sender
                sender = msg.get('from_id') or msg.get('sender_id') or ''
                if isinstance(sender, dict):
                    sender = sender.get('user_id') or sender.get('channel_id') or sender.get('chat_id') or ''
                else:
                    sender = msg.get('peer_id', {}).get('user_id') or ''
                try:
                    sender_id = int(sender)
                except Exception:
                    sender_id = sender
                sender_name = users_map.get(sender_id, sender_id) if sender_id else ''
                # Text
                text = msg.get('message', '')
                if text is None:
                    text = ''
                # Write
                if date_fmt or sender_name:
                    f.write(f"{date_fmt} {sender_name}:\n{text}\n\n")
                else:
                    f.write(f"{text}\n\n")
                saved += 1
            except Exception as e:
                print(f"Warning: TXT export error: {e}", file=sys.stderr)
    return saved

async def convert_json_to_txt(json_path: Path, txt_path: Path = None) -> int:
    """Convert existing JSON export to TXT format. Also updates users_map if Telegram credentials are available."""
    if not json_path.exists():
        print(f"Error: {json_path} not found", file=sys.stderr)
        return 0
    if txt_path is None:
        txt_path = json_path.with_suffix('.txt')
    with json_path.open("r", encoding="utf-8") as f:
        messages = json.load(f)
    # Try to get Telegram credentials
    config = load_config()
    api_id = get_config_value(config, "telegram_app", "api_id")
    api_hash = get_config_value(config, "telegram_app", "api_hash")
    session_dir = get_config_value(config, "settings", "session", "directory", default="./data")
    session_file = Path(session_dir) / Path(get_config_value(config, "settings", "session", "filename", default="session")).with_suffix(".session")
    client = None
    if api_id and api_hash:
        from telethon import TelegramClient
        async with TelegramClient(str(session_file), api_id, api_hash) as client:
            saved = await save_messages_as_txt(messages, txt_path, client)
    else:
        saved = await save_messages_as_txt(messages, txt_path)
    print(f"Converted {json_path} to {txt_path}. Saved {saved} messages.")
    return saved

async def dump_messages(messages: List[Message], output_file: Path, client=None):
    """
    Save messages to a JSON file and also as TXT.
    Returns the number of successfully saved messages.
    """
    if not messages:
        print("No messages to save.")
        return 0
    # Make messages serializable
    serializable_messages = []
    for msg in messages:
        try:
            msg_dict = msg.to_dict()
            serializable_messages.append(make_serializable(msg_dict))
        except Exception as e:
            print(f"Warning: Failed to serialize message: {e}", file=sys.stderr)
    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)
    # Write JSON
    with output_file.open("w", encoding="utf-8") as fp:
        json.dump(serializable_messages, fp, ensure_ascii=False, indent=2, default=convert_datetime)
    # Write TXT
    txt_path = output_file.with_suffix('.txt')
    await save_messages_as_txt(serializable_messages, txt_path, client)
    print(f"Saved {len(serializable_messages)} messages to {output_file} and {txt_path}")
    return len(serializable_messages)



def get_temp_file_path(output_file: Path) -> Path:
    """Get path for temporary file to store partial downloads."""
    return output_file.with_suffix(output_file.suffix + '.part')

def save_partial_messages(messages: List[Message], output_file: Path) -> None:
    """Save messages to a temporary file for partial downloads."""
    temp_file = get_temp_file_path(output_file)
    temp_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Convert messages to a list of dictionaries
    messages_data = [msg.to_dict() for msg in messages]
    
    # Save with pickle to preserve all message data
    with temp_file.open('wb') as f:
        pickle.dump(messages_data, f)

def load_partial_messages(output_file: Path) -> Tuple[List[Message], int]:
    """Load messages from a temporary file if it exists."""
    temp_file = get_temp_file_path(output_file)
    if not temp_file.exists():
        return [], 0
        
    try:
        with temp_file.open('rb') as f:
            messages_data = pickle.load(f)
        
        # Convert dictionaries back to Message objects
        messages = []
        for msg_data in messages_data:
            try:
                msg = Message._new(None, msg_data, None, None)
                messages.append(msg)
            except Exception as e:
                print(f"Warning: Could not load message from partial file: {e}", file=sys.stderr)
        
        last_id = messages[-1].id if messages else 0
        return messages, last_id
    except Exception as e:
        print(f"Warning: Could not load partial file: {e}", file=sys.stderr)
        return [], 0

async def fetch_history(client: TelegramClient, chat, limit: int, silent: bool, debug: bool,
                      output_file: Optional[Path] = None, save_partial: bool = False) -> List[Message]:
    """
    Fetch message history with support for partial saves and resuming.
    
    Args:
        client: Telegram client
        chat: Chat to download from
        limit: Maximum number of messages to fetch per request
        silent: If True, suppress progress output
        output_file: Path to save the final output (used for partial saves)
        save_partial: If True, save partial results to a temporary file
        
    Returns:
        List of downloaded messages
    """
    entity = await client.get_entity(chat)
    offset_id = 0
    all_messages: List[Message] = []
    
    # Check for existing partial download
    if output_file and save_partial:
        loaded_messages, last_id = load_partial_messages(output_file)
        if loaded_messages:
            all_messages = loaded_messages
            offset_id = last_id
            if not silent:
                print(f"Resuming download from message ID {offset_id}...")
    
    total_fetched = len(all_messages)
    last_save = time.time()
    save_interval = 300  # Save partial results every 5 minutes
    
    while True:
        try:
            history = await client(
                GetHistoryRequest(
                    peer=entity,
                    offset_id=offset_id,
                    offset_date=None,
                    add_offset=0,
                    limit=limit,
                    max_id=0,
                    min_id=0,
                    hash=0,
                )
            )
        except FloodWaitError as e:
            wait = e.seconds + 1
            if not silent:
                print(f"Flood-wait {wait}s, sleeping…", file=sys.stderr)
            
            # Save progress before sleeping
            if output_file and save_partial and all_messages:
                save_partial_messages(all_messages, output_file)
                
            await asyncio.sleep(wait)
            continue

        if not history.messages:
            if debug:
                print("No more messages available")
            break

        # Add only new messages to avoid duplicates
        new_messages = [msg for msg in history.messages if not any(m.id == msg.id for m in all_messages)]
        all_messages.extend(new_messages)
        
        if not new_messages:
            if not silent:
                print("No new messages found, stopping")
            break
            
        # Update offset to the oldest message we just fetched
        offset_id = min(msg.id for msg in new_messages)
        total_fetched = len(all_messages)
        
        current_time = time.time()
        
        # Save partial results periodically
        if output_file and save_partial and (current_time - last_save > save_interval or len(history.messages) < limit):
            save_partial_messages(all_messages, output_file)
            last_save = current_time

        if not silent:
            print(f"Fetched: {total_fetched} (batch: {len(new_messages)} new)")
    
    # Save final results if using partial saves
    if output_file and save_partial and all_messages:
        save_partial_messages(all_messages, output_file)

    return all_messages

    
async def get_entity_name(chat_identifier: str, client: TelegramClient) -> str:
    """Get the name of a Telegram entity using client.get_entity().
    
    Args:
        chat_identifier: Telegram entity identifier (username, URL, etc.)
            Examples:
            - @username
            - https://t.me/username
            - https://t.me/+invite_code
            
    Returns:
        Clean, filesystem-safe name of the entity
    """
    if not chat_identifier:
        return 'chat_history'
        
    try:
        # Get the entity using the client
        entity = await client.get_entity(chat_identifier)
        
        # Get the appropriate name based on entity type
        if hasattr(entity, 'title'):  # For chats/channels
            name = entity.title
        elif hasattr(entity, 'username') and entity.username:  # For users with username
            name = entity.username
        elif hasattr(entity, 'first_name') or hasattr(entity, 'last_name'):  # For users
            name = ' '.join(filter(None, [getattr(entity, 'first_name', ''), getattr(entity, 'last_name', '')]))
        else:
            name = str(entity.id)
            
        # Clean the name for filesystem use
        safe_name = re.sub(r'[^\w\-_.]', '_', name.strip())
        return safe_name or 'chat_history'
        
    except Exception as e:
        # Fallback to basic parsing if client is not available or entity not found
        chat = chat_identifier
        if chat.startswith('@'):
            chat = chat[1:]
        elif '//' in chat:
            chat = chat.split('?')[0].rstrip('/').split('/')[-1]
            if chat.startswith('+'):
                chat = 'invite_' + chat[1:]
        
        safe_name = re.sub(r'[^\w\-_.]', '_', chat)
        return safe_name or 'chat_history'

async def main() -> None:
    args = parse_args()
    config = load_config()
    
    # Get session directory from config or use current directory
    session_dir = get_config_value(config, "settings", "session", "directory", default="./data")
    session_file = Path(session_dir) / Path(args.session).with_suffix(".session")
    
    request_retries = get_config_value(config, "settings", "behavior", "max_retries", default=5)
    request_delay = get_config_value(config, "settings", "behavior", "request_delay", default=1)
    save_partial = get_config_value(config, "settings", "behavior", "save_partial", default=True)
    
    # Handle output filename with entity name if needed
    output_path = Path(args.output)
    if output_path.name == 'chat_history.json' and args.chat:
        # Create a client just for getting the entity name
        client = TelegramClient(
            str(session_file),
            args.api_id,
            args.api_hash,
            request_retries=request_retries,
            flood_sleep_threshold=request_delay
        )
        await client.start()
        try:
            safe_name = await get_entity_name(args.chat, client)
            output_path = output_path.parent / f"{safe_name}.json"
        except Exception as e:
            if not args.silent:
                print(f"Warning: Could not get entity name: {e}. Using default filename.", file=sys.stderr)
        finally:
            await client.disconnect()
    
    output_file = output_path
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Log to file if configured
    log_file = get_config_value(config, "settings", "logging", "log_file", default="")
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        import logging
        
        # Get log level safely, default to INFO
        log_level_str = get_config_value(config, "settings", "logging", "log_level", "INFO")
        log_level = getattr(logging, str(log_level_str).upper(), logging.INFO)
        
        # Configure logging
        logging.basicConfig(
            filename=log_path,
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        logging.info(f"Starting chat download for {args.chat}")
        logging.info(f"Using configuration from {os.path.abspath('config.yml')}")
    
    if not args.silent:
        print(f"Starting download of {args.chat} to {output_file}")
        if log_file:
            print(f"Logging to {log_path}")

    # Clean up any existing temporary files if not resuming
    temp_file = get_temp_file_path(output_file)
    if not save_partial and temp_file.exists():
        try:
            temp_file.unlink()
        except Exception as e:
            if not args.silent:
                print(f"Warning: Could not remove temporary file {temp_file}: {e}", file=sys.stderr)
    
    try:
        async with TelegramClient(
            str(session_file), 
            args.api_id, 
            args.api_hash,
            request_retries=request_retries,
            flood_sleep_threshold=request_delay
        ) as client:
            messages = await fetch_history(
                client, 
                args.chat, 
                args.limit, 
                args.silent,
                args.debug,
                output_file=output_file if save_partial else None,
                save_partial=save_partial
            )
            
            # Save final output
            saved_count = await dump_messages(messages, output_file, client)
            
            # Clean up temporary file after successful save
            if save_partial and temp_file.exists():
                try:
                    temp_file.unlink()
                    if args.debug:
                        print(f"Cleaned up temporary file: {temp_file}")
                except Exception as e:
                    if not args.silent:
                        print(f"Warning: Could not remove temporary file {temp_file}: {e}", file=sys.stderr)

            if not args.silent:
                print(f"Success! Fetched {len(messages)} messages, saved {saved_count} to {output_file}")
                
            # Save successful completion
            if 'logging' in locals():
                logging.info(f"Successfully processed {len(messages)} messages, saved {saved_count} to {output_file}")
                
    except Exception as e:
        error_msg = f"Error during download: {str(e)}"
        if not args.silent:
            print(error_msg, file=sys.stderr)
        if 'logging' in locals():
            logging.error(error_msg, exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    import asyncio
    import json
    from pathlib import Path
    
    args = parse_args()
    if getattr(args, 'json', False):
        # Handle JSON conversion mode
        json_path = Path(args.output)
        if json_path.suffix != '.json':
            json_path = json_path.with_suffix('.json')
        
        if getattr(args, 'subchat', None):
            # Subchat filtering mode
            subchat_id = args.subchat
            with json_path.open('r', encoding='utf-8') as f:
                messages = json.load(f)
            filtered = []
            for msg in messages:
                reply_to = msg.get('reply_to', {})
                if (reply_to.get('reply_to_msg_id') == subchat_id or 
                    reply_to.get('reply_to_top_id') == subchat_id):
                    filtered.append(msg)
            
            # Save filtered messages
            output_path = json_path.with_name(f"{json_path.stem}_subchat_{subchat_id}.json")
            with output_path.open('w', encoding='utf-8') as f:
                json.dump(filtered, f, ensure_ascii=False, indent=2)
            print(f"Filtered {len(filtered)} messages to {output_path}")
            if filtered:
                subchat_txt = output_path.with_suffix('.txt')
                asyncio.run(save_messages_as_txt(filtered, subchat_txt))
                print(f"Subchat {subchat_id}: saved {len(filtered)} messages to {output_path} and {subchat_txt}")
            else:
                print(f"No messages found for subchat {subchat_id}")
        else:
            asyncio.run(convert_json_to_txt(json_path))
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
            sys.exit(1)

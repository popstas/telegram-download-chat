"""Core functionality for the Telegram chat downloader."""

import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import yaml
from telethon import TelegramClient
from telethon.tl.custom import Message
from telethon.tl.types import PeerUser, PeerChat, PeerChannel, User, Chat, Channel, TypePeer
from telethon.errors import ChatIdInvalidError
from .paths import get_default_config, get_default_config_path, ensure_app_dirs, get_app_dir

class TelegramChatDownloader:
    """Main class for downloading Telegram chat history."""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the downloader with optional config path."""
        self.config_path = config_path
        self.config = self._load_config()
        self._setup_logging()
        self.client = None
    
    def _load_config(self) -> Dict[str, Any]:
        """
        Load configuration from YAML file or create default if not exists.
        
        Returns:
            dict: Loaded or default configuration
        """
        # Ensure app directories exist
        ensure_app_dirs()
        
        # Use default config path if none provided
        if not self.config_path:
            self.config_path = str(get_default_config_path())
        
        config_path = Path(self.config_path)
        default_config = get_default_config()
        
        # Create default config if it doesn't exist
        if not config_path.exists():
            try:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(config_path, 'w', encoding='utf-8') as f:
                    yaml.safe_dump(default_config, f, default_flow_style=False)
                logging.info(f"Created default config at {config_path}")
                print("\n" + "="*80)
                print("First run configuration:")
                print("1. Go to https://my.telegram.org/apps")
                print("2. Create a new application")
                print("3. Copy API ID and API Hash")
                print(f"4. Edit the config file at: {config_path}")
                print("5. Replace 'YOUR_API_ID' and 'YOUR_API_HASH' with your credentials")
                print("="*80 + "\n")
                return default_config
            except Exception as e:
                logging.error(f"Failed to create default config: {e}")
                return default_config
        
        # Load existing config
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                loaded_config = yaml.safe_load(f) or {}
                
            # Merge with defaults to ensure all required keys exist
            return self._merge_configs(default_config, loaded_config)
            
        except yaml.YAMLError as e:
            logging.error(f"Error loading config from {config_path}: {e}")
            return default_config
    
    def _merge_configs(self, default: Dict[str, Any], custom: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively merge two configuration dictionaries.
        
        Args:
            default: Default configuration
            custom: Custom configuration to merge over defaults
            
        Returns:
            dict: Merged configuration
        """
        result = default.copy()
        for key, value in custom.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        return result

    def _setup_logging(self) -> None:
        """Configure logging based on config."""
        log_level = self.config.get('settings', {}).get('log_level', 'INFO')
        log_file = self.config.get('settings', {}).get('log_file', get_app_dir()/'app.log')
        
        # Ensure log directory exists
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Configure root logger first
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.WARNING)  # Set default level to WARNING
        
        # Clear any existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Configure our logger
        self.logger = logging.getLogger('telegram_download_chat')
        self.logger.setLevel(getattr(logging, log_level.upper()))
        
        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        
        # Add file handler if log file is specified
        if log_file:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        
        # Add console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # Suppress Telethon's debug and info messages
        telethon_logger = logging.getLogger('telethon')
        telethon_logger.setLevel(logging.WARNING)
        
        # Suppress asyncio debug messages
        asyncio_logger = logging.getLogger('asyncio')
        asyncio_logger.setLevel(logging.WARNING)
    
    async def connect(self) -> None:
        """Connect to Telegram's servers."""
        api_id = os.getenv('TELEGRAM_API_ID') or self.config.get('settings', {}).get('api_id')
        api_hash = os.getenv('TELEGRAM_API_HASH') or self.config.get('settings', {}).get('api_hash')
        if not api_id or not api_hash or api_id == "YOUR_API_ID" or api_hash == "YOUR_API_HASH":
            raise ValueError("API ID and API hash must be provided in config or environment variables")

        session_dir = get_app_dir()
        session_file = Path(session_dir) / Path(self.config.get('settings', {}).get('session_name', 'session')).with_suffix(".session")
        

        request_delay = self.config.get('settings', {}).get('request_delay', 1)
        request_retries = self.config.get('settings', {}).get('max_retries', 5)

        self.client = TelegramClient(
            str(session_file), api_id, api_hash,
            request_retries=request_retries,
            flood_sleep_threshold=request_delay
        )
        await self.client.start()
    
    async def download_chat(self, chat_id: str, request_limit: int = 500, total_limit: int = 0, output_file: Optional[str] = None, 
                         save_partial: bool = True, silent: bool = False, until_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Download messages from a chat with support for partial downloads and resuming.
        
        Args:
            chat_id: Username, phone number, or chat ID
            request_limit: Maximum number of messages to fetch per request (50-1000)
            total_limit: Maximum total number of messages to download (0 for no limit)
            output_file: Path to save the final output (used for partial saves)
            save_partial: If True, save partial results to a temporary file
            silent: If True, suppress progress output
            until_date: Only download messages until this date (format: YYYY-MM-DD)
            
        Returns:
            List of message dictionaries
        """
        import sys
        from telethon.errors import FloodWaitError
        from telethon.tl.functions.messages import GetHistoryRequest
        
        if not self.client:
            await self.connect()
        
        entity = await self.get_entity(chat_id)
        offset_id = 0
        all_messages = []
        
        # Check for existing partial download
        output_path = Path(output_file) if output_file else None
        if output_file and save_partial:
            loaded_messages, last_id = self._load_partial_messages(output_path)
            if loaded_messages:
                all_messages = loaded_messages
                offset_id = last_id
                if not silent:
                    self.logger.info(f"Resuming download from message ID {offset_id}...")
        
        total_fetched = len(all_messages)
        last_save = asyncio.get_event_loop().time()
        save_interval = 300  # Save partial results every 5 minutes
        
        while True:
            try:
                history = await self.client(
                    GetHistoryRequest(
                        peer=entity,
                        offset_id=offset_id,
                        offset_date=None,
                        add_offset=0,
                        limit=request_limit,
                        max_id=0,
                        min_id=0,
                        hash=0,
                    )
                )
            except FloodWaitError as e:
                wait = e.seconds + 1
                if not silent:
                    self.logger.info(f"Flood-wait {wait}s, sleeping...")
                
                # Save progress before sleeping
                if output_file and save_partial and all_messages:
                    self._save_partial_messages(all_messages, output_path)
                    
                await asyncio.sleep(wait)
                continue

            if not history.messages:
                self.logger.debug("No more messages available")
                break

            # Add only new messages to avoid duplicates and filter by date if needed
            new_messages = []
            for msg in history.messages:
                # Skip if message ID already exists
                if any(m.id == msg.id for m in all_messages):
                    continue
                
                # Filter by date if until_date is provided
                if until_date and hasattr(msg, 'date') and msg.date:
                    # Convert until_date to timezone-aware datetime at start of day
                    until = datetime.strptime(until_date, '%Y-%m-%d').replace(
                        tzinfo=timezone.utc
                    )
                    
                    # Ensure msg.date is timezone-aware (in case it's not already)
                    msg_date = msg.date
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=timezone.utc)
                    
                    # Compare dates (not times)
                    if msg_date.date() < until.date():
                        if not silent:
                            self.logger.debug(f"Reached message from {msg_date} which is older than {until_date}")
                        break
                
                new_messages.append(msg)
            
            all_messages.extend(new_messages)
            
            if not new_messages:
                self.logger.debug("No new messages found, stopping")
                break
                
            # If we broke out of the loop early due to date filtering, we're done
            if until_date and len(new_messages) < len(history.messages):
                if not silent:
                    self.logger.info(f"Reached messages older than {until_date}, stopping")
                break
                
            # Update offset to the oldest message we just fetched
            offset_id = min(msg.id for msg in history.messages)
            total_fetched = len(all_messages)
            
            current_time = asyncio.get_event_loop().time()
            
            # Save partial results periodically
            if output_file and save_partial and (current_time - last_save > save_interval or len(history.messages) < limit):
                self._save_partial_messages(all_messages, output_path)
                last_save = current_time

            if not silent:
                self.logger.info(f"Fetched: {total_fetched} (batch: {len(new_messages)} new)")

            if total_limit > 0 and total_fetched >= total_limit:
                break

        # Save final results if using partial saves
        if output_file and save_partial and all_messages:
            self._save_partial_messages(all_messages, output_path)

        if total_limit > 0 and len(all_messages) >= total_limit:
            all_messages = all_messages[:total_limit]

        return all_messages
    

    async def fetch_user_name(self, user_id: int) -> str:
        """Fetch username from Telegram."""
        try:
            if not self.client:
                await self.connect()
            user = await self.client.get_entity(PeerUser(user_id))
            name = user.first_name or user.username or user.last_name or str(user_id)
            if user.last_name and user.first_name:
                name = f"{user.first_name} {user.last_name}"
            return name
        except Exception:
            return str(user_id)
    
    def _save_config(self):
        """Save the current config to the config file."""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(self.config, f, allow_unicode=True)
    
    async def _get_user_display_name(self, user_id: int) -> str:
        """Get display name from users_map or return ID as string."""
        if not user_id:
            return "Unknown"
        if user_id in self.config.get('users_map', {}):
            return self.config['users_map'][user_id]
        else:
            fetched_name = await self.fetch_user_name(user_id)
            if not self.config.get('users_map', {}):
                self.config['users_map'] = {}
            self.config['users_map'][user_id] = fetched_name
            self._save_config()
            return fetched_name

    def _get_sender_id(self, msg: Dict[str, Any]) -> Optional[int]:
        """Get sender ID from message."""
        sender = msg.get('from_id') or msg.get('sender_id') or ''
        if isinstance(sender, dict):
            sender = sender.get('user_id') or sender.get('channel_id') or sender.get('chat_id') or ''
        else:
            sender = msg.get('peer_id', {}).get('user_id') or ''
        try:
            sender_id = int(sender)
        except Exception:
            return None
        return sender_id    
    
    async def save_messages_as_txt(self, messages: List[Dict[str, Any]], txt_path: Path) -> int:
        """Save messages to a human-readable text file.
        
        Args:
            messages: List of message dictionaries
            txt_path: Path to save the text file
            
        Returns:
            Number of messages successfully saved
        """
        saved = 0
        txt_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(txt_path, 'w', encoding='utf-8') as f:
            for msg in messages:
                try:
                    # Format date
                    date_str = msg.get('date', '')
                    if date_str:
                        try:
                            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                            date_fmt = dt.strftime('%Y-%m-%d %H:%M:%S')
                        except (ValueError, TypeError):
                            date_fmt = ''
                    else:
                        date_fmt = ''
                    
                    # Get sender name
                    sender_name = ''
                    sender_id = self._get_sender_id(msg)
                    if sender_id:
                        sender_name = await self._get_user_display_name(sender_id)
                    
                    # Get message text
                    text = msg.get('text', '')
                    if not text and 'message' in msg:  # Fallback for different message formats
                        text = msg['message']
                    
                    # Format and write the message
                    if date_fmt or sender_name:
                        f.write(f"{date_fmt} {sender_name}:\n{text}\n\n")
                    else:
                        f.write(f"{text}\n\n")
                    saved += 1
                except Exception as e:
                    logging.warning(f"Error saving message to TXT: {e}")
        

        return saved
    
    def make_serializable(self, obj):
        """Recursively make an object JSON serializable."""
        if isinstance(obj, dict):
            return {k: self.make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self.make_serializable(x) for x in obj]
        elif isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        else:
            # Try to convert to string as a last resort
            try:
                return str(obj)
            except Exception:
                return None
    
    async def save_messages(self, messages: List[Message], output_file: str, save_txt: bool = True) -> None:
        """Save messages to JSON and optionally to TXT.
        
        Args:
            messages: List of message dictionaries to save
            output_file: Path to save the JSON file
            save_txt: If True, also save a TXT version of the chat
        """
        output_path = Path(output_file)
        
        # Make messages serializable
        serializable_messages = []
        for msg in messages:
            try:
                msg_dict = msg.to_dict()
                serializable_messages.append(self.make_serializable(msg_dict))
            except Exception as e:
                self.logger.warning(f"Failed to serialize message: {e}")

        # Save JSON
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(serializable_messages, f, ensure_ascii=False, indent=2)
        
        # Save TXT if requested
        if save_txt:
            txt_path = output_path.with_suffix('.txt')
            saved = await self.save_messages_as_txt(serializable_messages, txt_path)
            self.logger.info(f"Saved {saved} messages to {txt_path}")
        
        self.logger.info(f"Saved {len(messages)} messages to {output_file}")
    
    async def get_entity(self, identifier: str) -> Optional[Union[User, Chat, Channel]]:
        """Get Telegram entity by identifier (username, URL, or ID).
        
        Args:
            identifier: Telegram entity identifier
                - Username: @username
                - URL: https://t.me/username
                - ID: 123456789 or "-1001234567890" (user_id, group_id, or channel_id)
                - Phone number: +1234567890
                
        Returns:
            Telegram entity object (User, Chat, or Channel) or None if not found
        """
        try:
            if not self.client or not self.client.is_connected():
                await self.connect()
            
            self.logger.debug(f"Resolving entity: {identifier}")
            
            # Handle numeric IDs (either as int or string)
            if isinstance(identifier, (int, str)) and str(identifier).lstrip('-').isdigit():
                id_value = int(identifier)
                self.logger.debug(f"Trying to resolve numeric ID: {id_value}")
                
                # Try different peer types
                peer_types = [
                    (PeerChannel, 'channel/supergroup'),
                    (PeerChat, 'basic group'),
                    (PeerUser, 'user')
                ]
                
                for peer_cls, peer_type in peer_types:
                    try:
                        self.logger.debug(f"Trying to resolve as {peer_type}...")
                        entity = await self.client.get_entity(peer_cls(id_value))
                        self.logger.debug(f"Successfully resolved as {peer_type}")
                        return entity
                    except (ValueError, TypeError, KeyError, ChatIdInvalidError) as e:
                        self.logger.debug(f"Failed to resolve as {peer_type}: {str(e)}")
                        continue
                    except Exception as e:
                        self.logger.debug(f"Unexpected error resolving as {peer_type}: {str(e)}")
                        continue
                        
                self.logger.warning(f"Could not resolve ID {id_value} as any peer type, trying alternative methods...")
                
                # Try to get the entity by first getting all dialogs
                try:
                    self.logger.debug("Trying to find entity in dialogs...")
                    async for dialog in self.client.iter_dialogs():
                        if hasattr(dialog.entity, 'id') and dialog.entity.id == abs(id_value):
                            self.logger.debug(f"Found entity in dialogs: {dialog.entity}")
                            return dialog.entity
                except Exception as e:
                    self.logger.debug(f"Error searching in dialogs: {str(e)}")
                
                # Try to get the entity by its ID directly (sometimes works for private chats)
                try:
                    self.logger.debug("Trying direct entity access...")
                    return await self.client.get_entity(PeerChannel(abs(id_value)))
                except Exception as e:
                    self.logger.debug(f"Direct entity access failed: {str(e)}")
                
                # If we're here, we couldn't find the entity
                self.logger.warning(f"Could not find entity with ID {id_value} using any method")
                return None
            
            # For strings (usernames, URLs, phone numbers)
            self.logger.debug(f"Trying to resolve as string identifier...")
            try:
                entity = await self.client.get_entity(identifier)
                self.logger.debug(f"Successfully resolved string identifier")
                return entity
            except Exception as e:
                self.logger.debug(f"Failed to resolve string identifier: {str(e)}")
                raise
                
        except Exception as e:
            self.logger.error(f"Error getting entity {identifier}: {str(e)}")
            # Try one more time with a fresh connection
            try:
                self.logger.debug("Trying with a fresh connection...")
                await self.client.disconnect()
                await self.connect()
                return await self.client.get_entity(identifier)
            except Exception as e2:
                self.logger.error(f"Second attempt failed: {str(e2)}")
                return None

    async def get_entity_name(self, chat_identifier: str) -> str:
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
            entity = await self.get_entity(chat_identifier)
            if not entity:
                return None
                
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
    
    async def close(self) -> None:
        """Close the Telegram client connection."""
        if self.client and self.client.is_connected():
            await self.client.disconnect()
            self.client = None
    
    def get_temp_file_path(self, output_file: Path) -> Path:
        """Get path for temporary file to store partial downloads."""
        return output_file.with_name(f".{output_file.name}.part")
    
    def _save_partial_messages(self, messages: List[Dict[str, Any]], output_file: Path) -> None:
        """Save messages to a temporary file for partial downloads."""
        import json
        temp_file = self.get_temp_file_path(output_file)
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Save current messages and the ID of the last message for resuming
        data = {
            'messages': messages,
            'last_id': messages[-1]['id'] if messages else 0
        }
        
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _load_partial_messages(self, output_file: Path) -> tuple[list[Dict[str, Any]], int]:
        """Load messages from a temporary file if it exists."""
        import json
        temp_file = self.get_temp_file_path(output_file)
        
        if not temp_file.exists():
            return [], 0
            
        try:
            with open(temp_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if not isinstance(data, dict) or 'messages' not in data or 'last_id' not in data:
                return [], 0
                
            return data['messages'], data['last_id']
            
        except (json.JSONDecodeError, KeyError, IOError) as e:
            logging.warning(f"Error loading partial messages: {e}")
            return [], 0

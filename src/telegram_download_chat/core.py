"""Core functionality for the Telegram chat downloader."""

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import yaml
from telethon import TelegramClient
from telethon.tl.custom import Message
from telethon.tl.types import PeerUser, PeerChat, PeerChannel, User, Chat, Channel, TypePeer, Message, MessageService
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.errors import ChatIdInvalidError
from telegram_download_chat.paths import get_default_config, get_default_config_path, ensure_app_dirs, get_app_dir

class TelegramChatDownloader:
    """Main class for downloading Telegram chat history."""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the downloader with optional config path."""
        self.config_path = config_path
        self.config = self._load_config()
        self._setup_logging()
        self.client = None
        self.phone_code_hash = None  # Store phone code hash for authentication
        self._stop_requested = False  # Flag for graceful shutdown
        self._stop_file = None  # Path to stop file for inter-process communication
        self._fetched_usernames_count = 0  # Counter for fetched usernames
        self._fetched_chatnames_count = 0  # Counter for fetched chat names
    
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
                
            # Handle old config format (api_id/api_hash at root level)
            if 'api_id' in loaded_config or 'api_hash' in loaded_config:
                # Migrate old format to new format
                if 'settings' not in loaded_config:
                    loaded_config['settings'] = {}
                if 'api_id' in loaded_config:
                    loaded_config['settings']['api_id'] = loaded_config.pop('api_id')
                if 'api_hash' in loaded_config:
                    loaded_config['settings']['api_hash'] = loaded_config.pop('api_hash')
                
                # Save the updated config
                with open(config_path, 'w', encoding='utf-8') as f:
                    yaml.safe_dump(loaded_config, f, default_flow_style=False)
                
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
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        
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
    
    async def connect(self, phone: str = None, code: str = None, password: str = None):
        """Connect to Telegram using the configured API credentials."""
        from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, ApiIdInvalidError, PhoneNumberInvalidError
        
        if self.client and await self.client.is_user_authorized():
            return

        # Get API credentials from settings section
        settings = self.config.get('settings', {})
        api_id = settings.get('api_id')
        api_hash = settings.get('api_hash')
        phone = settings.get('phone')
        
        # Default values
        session_file = str(get_app_dir() / 'session.session')
        request_delay = settings.get('request_delay', 1)
        request_retries = settings.get('max_retries', 5)
        
        if not api_id or not api_hash:
            error_msg = "API ID or API Hash not found in config. Please check your config file."
            self.logger.error(error_msg)
            raise ValueError(error_msg)
        
        self.logger.debug(f"Connecting to Telegram with API ID: {api_id}")
        self.logger.debug(f"Session file: {session_file}")
        
        try:
            # Initialize the client
            self.client = TelegramClient(
                session=session_file,
                api_id=api_id,
                api_hash=api_hash,
                request_retries=request_retries,
                flood_sleep_threshold=request_delay
            )
            
            # Connect to Telegram
            await self.client.connect()
            
            is_authorized = await self.client.is_user_authorized()

            # send code request
            if phone and not code and not is_authorized:
                self.logger.info(f"Starting authentication for phone: {phone}")
                sent_code = await self.client.send_code_request(phone)
                self.phone_code_hash = sent_code.phone_code_hash
                self.logger.info("Verification code sent to your Telegram account")
                return
            
            # login
            if phone and code and not is_authorized:
                try:
                    if not hasattr(self, 'phone_code_hash'):
                        error_msg = "Please request a verification code first"
                        self.logger.error(error_msg)
                        raise ValueError(error_msg)
                        
                    await self.client.sign_in(
                        phone=phone,
                        code=code,
                        phone_code_hash=self.phone_code_hash,
                        password=password
                    )
                    self.logger.info("Successfully authenticated with code")
                except SessionPasswordNeededError:
                    if not password:
                        error_msg = "2FA is enabled but no password provided. Set password parameter."
                        self.logger.error(error_msg)
                        raise ValueError(error_msg) from None
                    
                    self.logger.info("2FA password required")
                    await self.client.sign_in(password=password)
                    self.logger.info("Successfully authenticated with 2FA password")
                except PhoneCodeInvalidError as e:
                    error_msg = "Invalid verification code. Please check your code and try again."
                    self.logger.error(error_msg)
                    raise ValueError(error_msg) from e
            else:
                self.logger.debug("Using existing session")
                
            # Verify connection
            me = await self.client.get_me()
            if not me:
                raise RuntimeError("Failed to get current user after authentication")
                
            self.logger.info(f"Successfully connected as {me.username or me.phone}")
            await self.client.start()
            return True
            
        except ApiIdInvalidError as e:
            error_msg = "Invalid API ID or API Hash. Please check your credentials."
            self.logger.error(error_msg)
            raise ValueError(error_msg) from e
        except PhoneNumberInvalidError as e:
            error_msg = f"Invalid phone number: {phone}. Please check your phone number."
            self.logger.error(error_msg)
            raise ValueError(error_msg) from e
        except Exception as e:
            error_msg = f"Failed to connect to Telegram: {str(e)}"
            self.logger.error(error_msg)
            if hasattr(self, 'client') and self.client:
                await self.client.disconnect()
            raise RuntimeError(error_msg) from e
    
    async def download_chat(self, chat_id: str, request_limit: int = 100, total_limit: int = 0, output_file: Optional[str] = None, 
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
        save_interval = 60  # Save partial results every 60 seconds
        
        while True:
            # Check for graceful shutdown request
            if self._stop_requested or (self._stop_file and self._stop_file.exists()):
                self._stop_requested = True
                if not silent:
                    self.logger.info("Stop requested, breaking download loop...")
                break
                
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
                # Skip if message doesn't have an ID or if it already exists
                if not hasattr(msg, 'id') or any(m.id == msg.id for m in all_messages if hasattr(m, 'id')):
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
            if output_file and save_partial and current_time - last_save > save_interval:
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
            self._fetched_usernames_count += 1
            
            # Log every 100 fetched usernames
            if self._fetched_usernames_count % 100 == 0:
                self._save_config()
                self.logger.info(f"Fetched {self._fetched_usernames_count} usernames so far")

            return fetched_name

    async def _get_peer_display_name(self, peer_id: int) -> str:
        """Get display name for a chat/channel/user."""
        if not peer_id:
            return "Unknown"
        if peer_id in self.config.get('chats_map', {}):
            return self.config['chats_map'][peer_id]
        name = await self.get_entity_name(str(peer_id))
        if not self.config.get('chats_map', {}):
            self.config['chats_map'] = {}
        self.config['chats_map'][peer_id] = name
        self._fetched_chatnames_count += 1
        if self._fetched_chatnames_count % 100 == 0:
            self._save_config()
            self.logger.info(f"Fetched {self._fetched_chatnames_count} chat names so far")
        return name

    def _get_sender_id(self, msg: Dict[str, Any]) -> Optional[int]:
        """Extract the sender ID from a message dictionary."""

        # Telegram messages can store the sender information in different
        # locations depending on how the message was obtained.  Prefer the
        # explicit ``from_id``/``sender_id`` fields when available and fall back
        # to ``peer_id`` only if those are missing.
        sender = msg.get('from_id') or msg.get('sender_id') or msg.get('peer_id')

        if isinstance(sender, dict):
            sender = (
                sender.get('user_id')
                or sender.get('channel_id')
                or sender.get('chat_id')
                or sender
            )

        try:
            return int(sender)
        except (TypeError, ValueError):
            return None

    def _get_recipient_id(self, msg: Dict[str, Any]) -> Optional[int]:
        """Extract the recipient (peer) ID from a message."""
        peer = msg.get('peer_id') or msg.get('to_id')
        if isinstance(peer, dict):
            peer = (
                peer.get('user_id')
                or peer.get('channel_id')
                or peer.get('chat_id')
                or peer
            )
        try:
            return int(peer)
        except (TypeError, ValueError):
            return None
    
    def convert_archive_to_messages(self, archive: Dict[str, Any], user_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Convert Telegram archive to list of messages.
        
        Args:
            archive: Dictionary containing the Telegram export data
            user_filter: Optional user ID to filter messages by sender (e.g., '12345' or 'user12345')
            
        Returns:
            List of formatted message dictionaries
        """
        self.logger.debug("Converting archive to messages...")
        if user_filter:
            self.logger.info(f"Filtering messages by user: {user_filter}")
            # Remove 'user' prefix if present for comparison
            user_filter = user_filter.replace('user', '') if user_filter and user_filter.startswith('user') else user_filter
            
        messages = []
        
        chats = archive.get('chats', {}).get('list', [])
        left_chats = archive.get('left_chats', {}).get('list', [])
        chats.extend(left_chats)

        self.logger.info(f"Found {len(chats)} chats, including {len(left_chats)} left chats")
        for chat in chats:
            chat_id = chat.get('id')
            if not chat_id:
                continue
                
            for message in chat.get('messages', []):
                # Skip non-message types
                if message.get('type') != 'message':
                    continue
                    
                # Handle text content (can be string, list of strings/objects, or None)
                text = message.get('text', '')
                if isinstance(text, list):
                    text_parts = []
                    for part in text:
                        if isinstance(part, str):
                            text_parts.append(part)
                        elif isinstance(part, dict):
                            text_parts.append(part.get('text', ''))
                    text = ''.join(text_parts)
                elif not isinstance(text, str):
                    text = str(text)
                    
                # Get user ID from from_id (handling both 'user123' format and direct IDs)
                from_id = message.get('from_id', '')
                if isinstance(from_id, str) and from_id.startswith('user'):
                    try:
                        user_id = int(from_id[4:])  # Remove 'user' prefix
                    except (ValueError, TypeError):
                        user_id = from_id  # Fallback to original if conversion fails
                else:
                    user_id = from_id
                    
                # Skip if user filter is set and doesn't match
                if user_filter and str(user_id) != user_filter:
                    continue
                    
                # Format the message
                formatted = {
                    'id': message.get('id'),
                    'peer_id': {
                        '_': 'PeerChat' if chat.get('type') == 'group' else 'PeerChannel',
                        'channel_id' if chat.get('type') in ['channel', 'public_supergroup'] 
                            else 'user_id': chat_id
                    },
                    'date': message.get('date'),
                    'message': text,
                    'from_id': {
                        '_': 'PeerUser',
                        'user_id': user_id
                    }
                }
                
                # Add reply info if exists
                if 'reply_to_message_id' in message:
                    formatted['reply_to_msg_id'] = message['reply_to_message_id']
                    
                messages.append(formatted)
        
        return messages
    
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

        self.logger.info(f"Saving {len(messages)} messages to {txt_path}")
        
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
                    
                    # Get recipient name
                    recipient_name = ""
                    recipient_id = self._get_recipient_id(msg)
                    if recipient_id:
                        recipient_name = await self._get_peer_display_name(recipient_id)

                    # Format and write the message
                    if date_fmt or sender_name:
                        if recipient_name:
                            f.write(f"{date_fmt} {sender_name} -> {recipient_name}:\n{text}\n\n")
                        else:
                            f.write(f"{date_fmt} {sender_name}:\n{text}\n\n")
                    else:
                        f.write(f"{text}\n\n")
                    saved += 1
                except Exception as e:
                    logging.warning(f"Error saving message to TXT: {e}")
        
        if self._fetched_usernames_count > 0 or self._fetched_chatnames_count > 0:
            self._save_config()

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

        self.logger.info(f"Saving {len(messages)} messages to {output_path}")
        
        # Make messages serializable
        serializable_messages = []
        for msg in messages:
            try:
                msg_dict = msg.to_dict() if hasattr(msg, 'to_dict') else msg
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
        
        partial = self.get_temp_file_path(output_path)
        if partial.exists() and not self._stop_requested:
            self.logger.info(f"Removing partial file: {partial}")
            partial.unlink()
        
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
        """Get path for temporary file to store partial downloads.
        
        Args:
            output_file: The target output file path
            
        Returns:
            Path: Temporary file path with .part.jsonl extension
        """
        # Return path with .part.jsonl extension
        return output_file.with_suffix('.part.jsonl')
    
    def _save_partial_messages(self, messages: List[Dict[str, Any]], output_file: Path) -> None:
        """Save messages to a temporary file for partial downloads using JSONL format.
        
        Each line is a separate JSON object with two fields:
        - 'm': message data
        - 'i': message ID (for resuming)
        
        Only new messages (not already in the file) are appended.
        Check only last 10000 messages.
        """
        import json
        import time
        
        start_time = time.time()
        temp_file = self.get_temp_file_path(output_file)
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing message IDs to avoid duplicates (only last 10k lines for performance)
        existing_ids = set()
        if temp_file.exists():
            try:
                with open(temp_file, 'r', encoding='utf-8') as f:
                    # Read all lines first, then take only the last 10k
                    all_lines = f.readlines()
                    last_10k_lines = all_lines[-10000:] if len(all_lines) > 10000 else all_lines
                    
                    for line in last_10k_lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            if isinstance(data, dict) and 'i' in data:
                                existing_ids.add(data['i'])
                        except json.JSONDecodeError:
                            continue
            except IOError:
                pass
        
        # Append only new messages in JSONL format
        new_saved_count = 0
        with open(temp_file, 'a', encoding='utf-8') as f:
            for msg in messages[-10000:]:
                try:
                    # Convert message to serializable format
                    msg_dict = msg.to_dict() if hasattr(msg, 'to_dict') else msg
                    serialized = self.make_serializable(msg_dict)
                    # Get message ID, defaulting to 0 if not found
                    msg_id = msg_dict.get('id') if hasattr(msg_dict, 'get') else getattr(msg_dict, 'id', 0)
                    
                    # Only append if this message ID is not already in the file
                    if msg_id not in existing_ids:
                        # Write as a single line
                        json.dump({'m': serialized, 'i': msg_id}, f, ensure_ascii=False)
                        f.write('\n')  # Add newline for JSONL format
                        existing_ids.add(msg_id)  # Track this ID to avoid duplicates in this batch
                        new_saved_count += 1
                except Exception as e:
                    self.logger.warning(f"Failed to serialize message: {e}")
        
        save_time = time.time() - start_time
        self.logger.info(f"Saved {new_saved_count} new messages to partial file in {save_time:.2f}s")
    
    def _load_partial_messages(self, output_file: Path) -> tuple[list[Dict[str, Any]], int]:
        """Load messages from a temporary JSONL file if it exists.
        
        Returns:
            tuple: (list of messages, last message ID)
        """
        import json
        temp_file = self.get_temp_file_path(output_file)
        
        if not temp_file.exists():
            return [], 0
            
        messages = []
        last_id = 0
        
        try:
            with open(temp_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                        
                    try:
                        data = json.loads(line)
                        if isinstance(data, dict) and 'm' in data:
                            messages.append(data['m'])
                            last_id = data.get('i', last_id)  # Update last_id if present
                    except json.JSONDecodeError as e:
                        logging.warning(f"Skipping invalid JSON line: {e}")
                        continue
                        
            return messages, last_id
            
        except (IOError, json.JSONDecodeError) as e:
            logging.warning(f"Error loading partial messages: {e}")
            return [], 0

    def stop(self) -> None:
        """Set the stop flag for graceful shutdown."""
        self._stop_requested = True
        # Also create stop file if it was set up
        if self._stop_file:
            try:
                self._stop_file.touch()
            except Exception:
                pass  # Ignore errors creating stop file

    def set_stop_file(self, stop_file_path: str) -> None:
        """Set up file-based stop communication."""
        self._stop_file = Path(stop_file_path)
        # Clean up any existing stop file
        if self._stop_file.exists():
            try:
                self._stop_file.unlink()
            except Exception:
                pass

    def cleanup_stop_file(self) -> None:
        """Clean up the stop file."""
        if self._stop_file and self._stop_file.exists():
            try:
                self._stop_file.unlink()
            except Exception:
                pass

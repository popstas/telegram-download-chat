#!/usr/bin/env python3
"""CLI interface for telegram-download-chat package."""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import traceback

from . import __version__
from .core import TelegramChatDownloader
from .paths import get_default_config_path, get_app_dir


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Download Telegram chat history to JSON"
    )
    
    parser.add_argument(
        'chat',
        nargs="?",
        help="Chat identifier (username, phone number, or chat ID)"
    )
    parser.add_argument(
        '-o', '--output',
        help="Output file path (default: chat_history_<chat_id>.json)",
        default=None
    )
    parser.add_argument(
        '-l', '--limit',
        type=int,
        default=0,
        help="Maximum number of messages to download (default: 0 - no limit)"
    )
    parser.add_argument(
        '-c', '--config',
        default=None,
        help="Path to config file (default: OS-specific location)"
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help="Enable debug logging"
    )
    parser.add_argument(
        '--show-config',
        action='store_true',
        help="Show the current configuration file location and exit"
    )
    parser.add_argument(
        '--subchat',
        type=str,
        help="Filter messages for txt by subchat id or URL (only for JSON to TXT conversion)"
    )
    parser.add_argument(
        '--subchat-name',
        type=str,
        help="Name for the subchat directory (default: subchat_<subchat_id>)"
    )
    parser.add_argument(
        '--user',
        type=str,
        help="Filter messages by sender ID (e.g., 12345 or user12345)"
    )
    parser.add_argument(
        '--until',
        type=str,
        help="Only download messages until this date (format: YYYY-MM-DD)"
    )
    parser.add_argument(
        '--split',
        choices=['month', 'year'],
        help="Split output files by month or year"
    )
    parser.add_argument(
        '-v', '--version',
        action='version',
        version=f'%(prog)s {__version__}'
    )
    
    return parser.parse_args()


def split_messages_by_date(messages: List[Dict[str, Any]], split_by: str) -> Dict[str, List[Dict[str, Any]]]:
    """Split messages by month or year based on message date.
    
    Args:
        messages: List of message dictionaries
        split_by: Either 'month' or 'year' to determine how to split
        
    Returns:
        Dictionary with keys as date strings (YYYY-MM or YYYY) and values as message lists
    """
    from datetime import datetime
    
    split_messages = {}
    
    for msg in messages:
        if not msg.get('date'):
            continue
            
        try:
            # Parse the date string to datetime object
            dt = datetime.strptime(msg['date'].split('.')[0], '%Y-%m-%dT%H:%M:%S')
            
            # Create the key based on split type
            if split_by == 'month':
                key = dt.strftime('%Y-%m')  # YYYY-MM format
            else:  # year
                key = dt.strftime('%Y')  # YYYY format
                
            # Add message to the appropriate group
            if key not in split_messages:
                split_messages[key] = []
            split_messages[key].append(msg)
            
        except (ValueError, AttributeError) as e:
            continue
            
    return split_messages


def filter_messages_by_subchat(messages: List[Dict[str, Any]], subchat_id: str) -> List[Dict[str, Any]]:
    """Filter messages by reply_to_msg_id or reply_to_top_id.
    
    Args:
        messages: List of message dictionaries
        subchat_id: Message ID to filter by (as string)
        
    Returns:
        Filtered list of messages
    """
    # Convert subchat_id to int for comparison, or extract from URL
    if subchat_id.startswith('https://t.me/c/'):
        # Extract message ID from URL format: https://t.me/c/CHANNEL_ID/MESSAGE_ID
        parts = subchat_id.strip('/').split('/')
        if len(parts) >= 3:
            try:
                target_id = int(parts[-1])  # Take the last part as message ID
            except ValueError:
                raise ValueError(f"Invalid message ID in URL: {subchat_id}")
        else:
            raise ValueError(f"Invalid Telegram chat URL format: {subchat_id}")
    else:
        try:
            target_id = int(subchat_id)
        except ValueError:
            raise ValueError(f"Invalid message ID format: {subchat_id}")
    
    filtered = []
    for msg in messages:
        reply_to = msg.get('reply_to')
        if not reply_to:
            continue
            
        # Check both reply_to_msg_id and reply_to_top_id
        if (str(reply_to.get('reply_to_msg_id')) == str(target_id) or
            str(reply_to.get('reply_to_top_id')) == str(target_id)):
            filtered.append(msg)
    
    return filtered

async def async_main():
    """Main async function."""
    args = parse_args()
    
    # Initialize downloader with config
    downloader = TelegramChatDownloader(config_path=args.config)
    
    # Show config path and exit if requested
    if args.show_config:
        config_path = Path(args.config) if args.config else get_default_config_path()
        downloader.logger.info(f"Configuration file: {config_path}")
        if config_path.exists():
            downloader.logger.info("\nCurrent configuration:")
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    downloader.logger.info(f.read())
            except Exception as e:
                downloader.logger.error(f"\nError reading config file: {e}")
        else:
            downloader.logger.info("\nConfiguration file does not exist yet. It will be created on first run.")
        return 0
    
    # Set debug log level if requested
    if args.debug:
        downloader.logger.setLevel(logging.DEBUG)
        downloader.logger.debug("Debug logging enabled")
    
    try:
        if not args.chat:
            downloader.logger.error("Chat identifier is required")
            return 1
            
        # Connect to Telegram
        try:
            await downloader.connect()
        except Exception as e:
            downloader.logger.error(f"Failed to connect to Telegram: {e}")
            downloader.logger.info("\nPlease make sure you have entered your API credentials in the config file.")
            downloader.logger.info("You can edit the config file at: %s", get_default_config_path())
            return 1

        # Get downloads directory from config
        downloads_dir = Path(downloader.config.get('settings', {}).get('save_path', get_app_dir() / 'downloads'))
        downloads_dir.mkdir(parents=True, exist_ok=True)
        
        # Handle JSON conversion mode if --subchat is provided without --json
        if args.subchat and not args.output and not args.chat.endswith('.json'):
            downloader.logger.error("--subchat requires an existing JSON file as input")
            return 1
            
        # Check if we're in JSON conversion mode
        if args.chat.endswith('.json'):
            json_path = Path(args.chat)

            if not json_path.exists() and not json_path.is_absolute():
                json_path = downloads_dir / json_path

            if not json_path.exists():
                downloader.logger.error(f"File not found: {json_path}")
                return 1
                
            downloader.logger.debug(f"Loading messages from JSON file: {json_path}")
                
            with open(json_path, 'r', encoding='utf-8') as f:
                messages = json.load(f)
                
            # Check if messages is a dictionary with 'about' and 'chats' keys
            if isinstance(messages, dict) and 'about' in messages and 'chats' in messages:
                messages = downloader.convert_archive_to_messages(messages, user_filter=args.user)
                
            txt_path = Path(json_path).with_suffix('.txt')
            
            # If user filter is specified, add it to the filename
            if args.user:
                user_id = args.user.replace('user', '') if args.user.startswith('user') else args.user
                txt_path = txt_path.with_stem(f"{txt_path.stem}_user_{user_id}")

            # Apply subchat filter if specified
            if args.subchat:
                messages = filter_messages_by_subchat(messages, args.subchat)
                # Use subchat_name directly in filename
                txt_path = downloads_dir / f"{args.subchat_name or f'{txt_path.stem}_subchat_{args.subchat}'}{txt_path.suffix}"
                downloader.logger.info(f"Filtered to {len(messages)} messages in subchat {args.subchat}")
            
            # Handle message splitting if requested
            if args.split:
                split_messages = split_messages_by_date(messages, args.split)
                if not split_messages:
                    downloader.logger.warning("No messages with valid dates found for splitting")
                    saved = await downloader.save_messages_as_txt(messages, txt_path)
                    downloader.logger.info(f"Saved {saved} messages to {txt_path}")
                else:
                    # Save each group to a separate file
                    base_name = txt_path.stem
                    ext = txt_path.suffix
                    total_saved = 0
                    
                    for date_key, msgs in split_messages.items():
                        split_file = txt_path.with_name(f"{base_name}_{date_key}{ext}")
                        saved = await downloader.save_messages_as_txt(msgs, split_file)
                        total_saved += saved
                        downloader.logger.info(f"Saved {saved} messages to {split_file}")
                    
                    downloader.logger.info(f"Saved {total_saved} total messages in {len(split_messages)} files to {txt_path.parent}")
            else:
                saved = await downloader.save_messages_as_txt(messages, txt_path)
                downloader.logger.info(f"Saved {saved} messages to {txt_path}")
                
            downloader.logger.debug("Conversion completed successfully")
            return 0
            
        # Normal chat download mode
        downloader.logger.debug("Connecting to Telegram...")
        await downloader.connect()
        
        safe_chat_name = await downloader.get_entity_name(args.chat)
        if not safe_chat_name:
            downloader.logger.error(f"Failed to get entity name for chat: {args.chat}")
            return 1

        # Download chat history
        downloader.logger.info(f"Downloading messages from chat: {args.chat} ({safe_chat_name})")
        downloader.logger.debug(f"Using limit: {args.limit}")
        
        # Parse until_date if provided
        until_date = None
        if args.until:
            try:
                # Validate the date format
                datetime.strptime(args.until, '%Y-%m-%d')
                until_date = args.until
                downloader.logger.info(f"Downloading messages until {until_date}")
            except ValueError:
                downloader.logger.error("Invalid date format. Please use YYYY-MM-DD")
                return 1

        # Determine output file
        output_file = args.output
        if not output_file:
            # Get safe filename from entity name
            try:
                downloader.logger.debug(f"Using entity name for output: {safe_chat_name}")
            except Exception as e:
                downloader.logger.warning(f"Could not get entity name: {e}, using basic sanitization")
                safe_chat_name = "".join(c if c.isalnum() else "_" for c in args.chat)
            
            output_file = str(downloads_dir / f"{safe_chat_name}.json")
            
            if args.subchat:
                output_file = str(Path(output_file).with_stem(f"{Path(output_file).stem}_subchat_{args.subchat}"))
        
        # Download messages
        download_kwargs = {
            'chat_id': args.chat,
            'request_limit': args.limit if args.limit > 0 else 100,
            'total_limit': args.limit if args.limit > 0 else 0,
            'output_file': output_file,
            'silent': False
        }
        if until_date:
            download_kwargs['until_date'] = until_date
            
        messages = await downloader.download_chat(**download_kwargs)
        
        downloader.logger.debug(f"Downloaded {len(messages)} messages")
        
        # Apply subchat filter if specified
        if args.subchat:
            messages = filter_messages_by_subchat(messages, args.subchat)
            downloader.logger.info(f"Filtered to {len(messages)} messages in subchat {args.subchat}")
            
        if not messages:
            downloader.logger.warning("No messages to save")
            return 0
        
        try:
            if args.split:
                # Split messages by date
                split_messages = split_messages_by_date(messages, args.split)
                
                if not split_messages:
                    downloader.logger.warning("No messages with valid dates found for splitting")
                    await downloader.save_messages(messages, output_file)
                else:
                    # Save each group to a separate file
                    output_path = Path(output_file)
                    base_name = output_path.stem
                    ext = output_path.suffix
                    
                    for date_key, msgs in split_messages.items():
                        split_file = output_path.with_name(f"{base_name}_{date_key}{ext}")
                        await downloader.save_messages(msgs, str(split_file))
                        downloader.logger.info(f"Saved {len(msgs)} messages to {split_file}")
                    
                    downloader.logger.info(f"Saved {len(split_messages)} split files in {output_path.parent}")
            else:
                await downloader.save_messages(messages, output_file)
                
        except Exception as e:
            downloader.logger.error(f"Failed to save messages: {e}", exc_info=args.debug)
            return 1
        
    except Exception as e:
        downloader.logger.error(f"An error occurred: {e}", exc_info=args.debug)
        downloader.logger.error(traceback.format_exc())
        return 1
    finally:
        await downloader.close()
    
    return 0


def main() -> int:
    """Main entry point."""
    # Support GUI mode: `telegram-download-chat gui`
    if (len(sys.argv) >= 2 and sys.argv[1] == 'gui') or len(sys.argv) == 1:
        try:
            from .gui_app import main as gui_main
            gui_main()
            return 0
        except ImportError as e:
            print("GUI dependencies not installed. Please install with: pip install 'telegram-download-chat[gui]'")
            print(e)
            return 1
        except Exception as e:
            print(f"Error starting GUI: {e}")
            print(e)
            return 1
            
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        print("Operation cancelled by user")
        return 1
    except Exception as e:
        print(f"Unhandled exception: {e}")
        return 1


if __name__ == "__main__":
    main()

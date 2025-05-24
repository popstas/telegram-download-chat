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
        help="Filter messages by reply_to_msg_id or reply_to_top_id (only with --json)"
    )
    parser.add_argument(
        '--until',
        type=str,
        help="Only download messages until this date (format: YYYY-MM-DD)"
    )
    parser.add_argument(
        '-v', '--version',
        action='version',
        version=f'%(prog)s {__version__}'
    )
    
    return parser.parse_args()


def filter_messages_by_subchat(messages: List[Dict[str, Any]], subchat_id: str) -> List[Dict[str, Any]]:
    """Filter messages by reply_to_msg_id or reply_to_top_id.
    
    Args:
        messages: List of message dictionaries
        subchat_id: Message ID to filter by (as string)
        
    Returns:
        Filtered list of messages
    """
    try:
        # Try to convert subchat_id to int for comparison
        target_id = int(subchat_id)
    except (ValueError, TypeError):
        # If conversion fails, try string comparison
        target_id = subchat_id
    
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
                
            txt_path = Path(json_path).with_suffix('.txt')

            # Apply subchat filter if specified
            if args.subchat:
                messages = filter_messages_by_subchat(messages, args.subchat)
                txt_path = txt_path.with_name(f"{txt_path.stem}_subchat_{args.subchat}{txt_path.suffix}")
                downloader.logger.info(f"Filtered to {len(messages)} messages in subchat {args.subchat}")
                
            saved = await downloader.save_messages_as_txt(messages, txt_path)
            downloader.logger.info(f"Saved {saved} messages to {txt_path}")
            downloader.logger.debug(f"Conversion completed successfully")
            return 0
            
        # Normal chat download mode
        downloader.logger.debug("Connecting to Telegram...")
        await downloader.connect()
        
        # Download chat history
        downloader.logger.info(f"Downloading messages from chat: {args.chat}")
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

        # Download messages
        download_kwargs = {
            'chat_id': args.chat,
            'request_limit': args.limit if args.limit > 0 else 500,
            'total_limit': args.limit if args.limit > 0 else 0,
            'output_file': args.output,
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
        
        # Determine output file
        output_file = args.output
        if not output_file:
            # Get safe filename from entity name
            try:
                safe_chat_name = await downloader.get_entity_name(args.chat)
                downloader.logger.debug(f"Using entity name for output: {safe_chat_name}")
            except Exception as e:
                downloader.logger.warning(f"Could not get entity name: {e}, using basic sanitization")
                safe_chat_name = "".join(c if c.isalnum() else "_" for c in args.chat)
            
            output_file = str(downloads_dir / f"{safe_chat_name}.json")
            
            if args.subchat:
                output_file = str(Path(output_file).with_stem(f"{Path(output_file).stem}_subchat_{args.subchat}"))
        
        try:
            await downloader.save_messages(messages, output_file)
        except Exception as e:
            downloader.logger.error(f"Failed to save messages: {e}", exc_info=args.debug)
            return 1
        
    except Exception as e:
        downloader.logger.error(f"An error occurred: {e}", exc_info=args.debug)
        return 1
    finally:
        await downloader.close()
    
    return 0


def main() -> int:
    """Main entry point."""
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

"""Command line argument parsing for telegram-download-chat."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import List, Optional

from telegram_download_chat import __version__


@dataclass
class CLIOptions:
    """Parsed command line options."""

    chat: Optional[str] = None
    chats: List[str] = field(default_factory=list)
    output: Optional[str] = None
    limit: int = 0
    since_id: Optional[int] = None
    config: Optional[str] = None
    debug: bool = False
    show_config: bool = False
    subchat: Optional[str] = None
    subchat_name: Optional[str] = None
    user: Optional[str] = None
    from_date: Optional[str] = None
    last_days: Optional[int] = None
    until: Optional[str] = None
    split: Optional[str] = None
    sort: str = "asc"
    results_json: bool = False
    keywords: Optional[str] = None
    preset: Optional[str] = None


def parse_args(argv: Optional[list[str]] = None) -> CLIOptions:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Download Telegram chat history to JSON"
    )

    parser.add_argument(
        "chat", nargs="?", help="Chat identifier (username, phone number, or chat ID)"
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file path (default: <chat_name>.json)",
        default=None,
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=0,
        help="Maximum number of messages to download (default: 0 - no limit)",
    )
    parser.add_argument(
        "--since-id",
        type=int,
        help="Start downloading after the specified message ID",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="Path to config file (default: OS-specific location)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Show the current configuration file location and exit",
    )
    parser.add_argument(
        "--subchat",
        type=str,
        help="Filter messages for txt by subchat id or URL (only for JSON to TXT conversion)",
    )
    parser.add_argument(
        "--subchat-name",
        type=str,
        help="Name for the subchat directory (default: subchat_<subchat_id>)",
    )
    parser.add_argument(
        "--user",
        type=str,
        help="Filter messages by sender ID (e.g., 12345 or user12345)",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        type=str,
        help="Base date for --last-days calculation (format: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--last-days",
        dest="last_days",
        type=int,
        help="Number of days back from --from (or today) to download",
    )
    parser.add_argument(
        "--until",
        type=str,
        help="Only download messages until this date (format: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--split", choices=["month", "year"], help="Split output files by month or year"
    )
    parser.add_argument(
        "--sort",
        choices=["asc", "desc"],
        default="asc",
        help="Sort messages by date (default: asc)",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--results-json",
        action="store_true",
        help="Output results summary as JSON to stdout",
    )
    parser.add_argument(
        "--keywords",
        type=str,
        help="Comma-separated keywords to search in messages",
    )
    parser.add_argument(
        "--preset",
        type=str,
        help="Name of preset from config to use",
    )

    args = parser.parse_args(argv)

    chat_list: List[str] = []
    if args.chat:
        chat_list = [c.strip() for c in args.chat.split(",") if c.strip()]
        args.chat = chat_list[0]

    args_dict = vars(args)
    args_dict["chats"] = chat_list
    return CLIOptions(**args_dict)


__all__ = ["CLIOptions", "parse_args"]

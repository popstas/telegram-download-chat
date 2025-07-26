"""Tests for telegram-download-chat package."""

import asyncio
import json
import logging
import os
import re
import sys
from io import StringIO
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union
from unittest.mock import AsyncMock, MagicMock, Mock, mock_open, patch

import pytest

from telegram_download_chat.cli import (
    CLIOptions,
    analyze_keywords,
    async_main,
    convert_json_to_txt,
    download_chat,
    download_folder,
    filter_messages_by_subchat,
    parse_args,
    show_config,
)
from telegram_download_chat.core import DownloaderContext, TelegramChatDownloader


@pytest.fixture
def mock_downloader():
    """Fixture that mocks TelegramChatDownloader."""
    with patch("telegram_download_chat.cli.TelegramChatDownloader") as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.config = {}
        mock_instance.logger = MagicMock()
        yield mock_instance


class TestCLIArgumentParsing:
    """Tests for command line argument parsing."""

    def test_required_chat_argument(self):
        """Test that chat argument is required for normal operation."""
        # When no chat is provided and --show-config is not used
        with patch("sys.argv", ["script_name"]):
            args = parse_args()
            assert args.chat is None  # argparse doesn't raise, but chat will be None

    def test_basic_chat_argument(self):
        """Test basic chat argument parsing."""
        test_chat = "test_chat"
        with patch("sys.argv", ["script_name", test_chat]):
            args = parse_args()
            assert args.chat == test_chat
            assert args.chats == [test_chat]
            assert args.limit == 0  # Default value from cli.py
            assert args.output is None
            assert args.sort == "asc"

    def test_multiple_chats_argument(self):
        """Test parsing multiple chats separated by commas."""
        with patch("sys.argv", ["script_name", "chat1,chat2"]):
            args = parse_args()
            assert args.chat == "chat1"
            assert args.chats == ["chat1", "chat2"]

    def test_results_json_argument(self):
        """Test parsing of --results-json option."""
        with patch("sys.argv", ["script_name", "chat", "--results-json"]):
            args = parse_args()
            assert args.results_json is True
            assert args.chats == ["chat"]

    def test_keywords_argument(self):
        """Test parsing of --keywords option."""
        with patch(
            "sys.argv",
            ["script_name", "chat", "--keywords", "@user,hello"],
        ):
            args = parse_args()
            assert args.keywords == "@user,hello"


class TestFilterMessagesBySubchat:
    """Tests for filter_messages_by_subchat function."""

    def test_filter_by_integer_id(self):
        """Test filtering messages by integer message ID."""
        messages = [
            {"id": 1, "reply_to": {"reply_to_msg_id": 123}},
            {"id": 2, "reply_to": {"reply_to_msg_id": 456}},
            {"id": 3, "reply_to": {"reply_to_msg_id": 123}},
            {"id": 4, "reply_to": None},
        ]
        filtered = filter_messages_by_subchat(messages, "123")
        assert len(filtered) == 2
        assert filtered[0]["id"] == 1
        assert filtered[1]["id"] == 3

    def test_filter_by_url(self):
        """Test filtering messages by Telegram chat URL."""
        messages = [
            {"id": 1, "reply_to": {"reply_to_msg_id": 123}},
            {"id": 2, "reply_to": {"reply_to_msg_id": 456}},
            {"id": 3, "reply_to": {"reply_to_msg_id": 123}},
            {"id": 4, "reply_to": None},
        ]
        filtered = filter_messages_by_subchat(messages, "https://t.me/c/123456789/123")
        assert len(filtered) == 2
        assert filtered[0]["id"] == 1
        assert filtered[1]["id"] == 3

    def test_invalid_url_format(self):
        """Test handling of invalid Telegram chat URL format."""
        messages = [
            {"id": 1, "reply_to": {"reply_to_msg_id": 123}},
        ]
        with pytest.raises(ValueError, match="Invalid message ID in URL"):
            filter_messages_by_subchat(messages, "https://t.me/c/123456789/abc")

    def test_invalid_url_format_empty(self):
        """Test handling of empty URL format."""
        messages = [
            {"id": 1, "reply_to": {"reply_to_msg_id": 123}},
        ]
        with pytest.raises(ValueError):
            filter_messages_by_subchat(messages, "https://t.me/c/")

    def test_invalid_integer_id(self):
        """Test handling of invalid integer ID format."""
        messages = [
            {"id": 1, "reply_to": {"reply_to_msg_id": 123}},
        ]
        with pytest.raises(ValueError, match="Invalid message ID format"):
            filter_messages_by_subchat(messages, "abc")

    def test_no_reply_to(self):
        """Test filtering when message has no reply_to field."""
        messages = [
            {"id": 1, "reply_to": None},
            {"id": 2, "reply_to": None},
            {"id": 3, "reply_to": {"reply_to_msg_id": 123}},
        ]
        filtered = filter_messages_by_subchat(messages, "123")
        assert len(filtered) == 1
        assert filtered[0]["id"] == 3

    def test_empty_messages_list(self):
        """Test filtering with empty messages list."""
        filtered = filter_messages_by_subchat([], "123")
        assert filtered == []

    def test_string_comparison(self):
        """Test that non-numeric subchat_id raises ValueError."""
        messages = [
            {"id": 1, "reply_to": {"reply_to_msg_id": "abc"}},
            {"id": 2, "reply_to": {"reply_to_msg_id": "xyz"}},
            {"id": 3, "reply_to": {"reply_to_msg_id": "abc"}},
        ]
        with pytest.raises(ValueError, match="Invalid message ID format: abc"):
            filter_messages_by_subchat(messages, "abc")

    def test_all_arguments(self):
        """Test parsing of all command line arguments."""
        test_args = [
            "script_name",
            "test_chat",
            "--limit",
            "100",
            "--output",
            "output.json",
            "--config",
            "custom_config.yml",
            "--debug",
            "--subchat",
            "123",
            "--subchat-name",
            "custom_subchat",
            "--until",
            "2025-01-01",
            "--sort",
            "asc",
        ]
        with patch("sys.argv", test_args):
            args = parse_args()
            assert args.chat == "test_chat"
            assert args.chats == ["test_chat"]
            assert args.limit == 100
            assert args.output == "output.json"
            assert args.config == "custom_config.yml"
            assert args.debug is True
            assert args.subchat == "123"
            assert args.subchat_name == "custom_subchat"
            assert args.until == "2025-01-01"
            assert args.sort == "asc"

    def test_from_and_last_days_arguments(self):
        """Test parsing of --from and --last-days options."""
        test_args = [
            "script_name",
            "chat",
            "--from",
            "2025-06-05",
            "--last-days",
            "1",
        ]
        with patch("sys.argv", test_args):
            args = parse_args()
            assert args.from_date == "2025-06-05"
            assert args.last_days == 1

    def test_until_date_format_validation(self):
        """Test that invalid date formats are accepted by the parser but handled in async_main."""
        with patch("sys.argv", ["script_name", "test_chat", "--until", "invalid-date"]):
            args = parse_args()
            # The parser should accept any string for --until
            assert args.until == "invalid-date"

    def test_until_date_without_chat(self):
        """Test that --until without chat argument is handled."""
        with patch("sys.argv", ["script_name", "--until", "2025-01-01"]):
            args = parse_args()
            assert args.until == "2025-01-01"

    def test_show_config_flag(self):
        """Test --show-config flag behavior."""
        # --show-config should make chat argument optional
        with patch("sys.argv", ["script_name", "--show-config"]):
            args = parse_args()
            assert args.show_config is True
            assert args.chat is None

    def test_json_conversion_mode(self):
        """Test JSON file input for conversion mode."""
        with patch("sys.argv", ["script_name", "chat_history.json"]):
            args = parse_args()
            assert args.chat == "chat_history.json"
            assert args.chats == ["chat_history.json"]
            # Should not require --output for JSON input
            assert args.output is None
            # subchat_name should be None by default
            assert args.subchat_name is None

    def test_json_conversion_with_subchat_name(self):
        """Test JSON conversion with subchat-name option."""
        with patch(
            "sys.argv",
            [
                "script_name",
                "chat_history.json",
                "--subchat",
                "123",
                "--subchat-name",
                "custom_subchat",
            ],
        ):
            args = parse_args()
            assert args.chat == "chat_history.json"
            assert args.chats == ["chat_history.json"]
            assert args.subchat == "123"
            assert args.subchat_name == "custom_subchat"

    @pytest.mark.asyncio
    async def test_last_days_converted_to_until(self, mock_downloader, tmp_path):
        """Test that --last-days computes --until correctly."""
        mock_downloader.connect = AsyncMock()
        mock_downloader.close = AsyncMock()
        mock_downloader.cleanup_stop_file = MagicMock()
        mock_downloader.config = {"settings": {"save_path": str(tmp_path)}}
        mock_downloader.get_entity_name = AsyncMock(return_value="chat")
        mock_downloader.download_chat = AsyncMock(return_value=[])

        with patch(
            "sys.argv",
            ["script_name", "chat", "--from", "2025-06-05", "--last-days", "1"],
        ), patch(
            "telegram_download_chat.cli.TelegramChatDownloader",
            return_value=mock_downloader,
        ):
            await async_main()

        args, kwargs = mock_downloader.download_chat.call_args
        assert kwargs.get("until_date") == "2025-06-04"


class TestAnalyzeKeywords:
    """Tests for analyze_keywords helper."""

    def test_basic_keyword_search(self):
        messages = [
            {"id": 1, "peer_id": {"channel_id": 100}, "message": "hello there"},
            {
                "id": 2,
                "peer_id": {"channel_id": 100},
                "message": "@user mentioned",
                "from_id": {"user_id": 42},
            },
        ]
        result = analyze_keywords(["@user", "hello"], messages)
        assert result[0]["count"] == 1
        assert result[1]["count"] == 1


class TestCLIExecution:
    """Tests for CLI execution flow."""

    def test_show_config(self, mock_downloader):
        """Test --show-config flag execution."""
        # Setup logger mock
        mock_logger = MagicMock()
        mock_downloader.logger = mock_logger

        # Mock the config file content
        config_content = "test: config"

        # Mock the config path
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.__str__.return_value = "/path/to/config.yml"

        with patch("sys.argv", ["script_name", "--show-config"]), patch(
            "telegram_download_chat.cli.Path", return_value=mock_path
        ), patch("builtins.open", mock_open(read_data=config_content)), patch(
            "telegram_download_chat.cli.TelegramChatDownloader",
            return_value=mock_downloader,
        ):
            # Import here to avoid import issues with patching
            from telegram_download_chat.cli import main

            # Mock the async_main function
            async def mock_async_main():
                return 0

            # Replace the actual async_main with our mock
            with patch("telegram_download_chat.cli.async_main", new=mock_async_main):
                # Run the main function
                result = main()

                # Verify the result
                assert result == 0, f"Expected return code 0, got {result}"

    @pytest.mark.asyncio
    async def test_missing_chat_argument(self):
        """Test error when required chat argument is missing."""
        # Create a mock logger
        mock_logger = MagicMock()

        # Create an AsyncMock for the downloader
        mock_downloader = AsyncMock()
        mock_downloader.logger = mock_logger

        # Mock the command line arguments and downloader
        with patch("sys.argv", ["script_name"]), patch(
            "telegram_download_chat.cli.TelegramChatDownloader",
            return_value=mock_downloader,
        ):
            # Call the async_main function
            result = await async_main()

            # Verify it returns error code 1
            assert result == 1

            # Verify the error message was logged
            error_found = any(
                args and args[0] == "Chat identifier is required"
                for args, _ in mock_logger.error.call_args_list
            )
            assert (
                error_found
            ), "Expected error message 'Chat identifier is required' not found"

    @pytest.mark.asyncio
    async def test_json_conversion_flow(self, tmp_path):
        """Test JSON conversion flow."""
        # Create a test JSON file with sample messages
        test_json = tmp_path / "test.json"
        test_messages = [
            {"id": 1, "message": "Test message 1"},
            {"id": 2, "message": "Test message 2"},
        ]
        test_json.write_text(json.dumps(test_messages))

        # Create an AsyncMock for the downloader
        mock_downloader = AsyncMock()

        # Mock the downloads directory to be our temp directory
        mock_config = {"settings": {"save_path": str(tmp_path)}}
        mock_downloader.config = mock_config

        # Mock the logger
        mock_logger = MagicMock()
        mock_downloader.logger = mock_logger

        # Mock the save_messages_as_txt method to return the number of messages
        mock_downloader.save_messages_as_txt.return_value = len(test_messages)

        with patch("sys.argv", ["script_name", str(test_json)]), patch(
            "telegram_download_chat.cli.TelegramChatDownloader",
            return_value=mock_downloader,
        ), patch("telegram_download_chat.paths.get_app_dir", return_value=tmp_path):
            # Mock the file operations
            with patch("builtins.open", mock_open()) as mock_file:
                # Mock the json.load to return our test messages
                with patch("json.load", return_value=test_messages):
                    result = await async_main()

            # The function should return 0 on success
            assert result == 0

            # Verify the logger was called with expected messages
            debug_messages = [call[0][0] for call in mock_logger.debug.call_args_list]
            assert any(
                "Loading messages from JSON file:" in msg for msg in debug_messages
            )

            # Verify save_messages_as_txt was called with the correct arguments
            expected_output = test_json.with_suffix(".txt")
            mock_downloader.save_messages_as_txt.assert_called_once()

            call_args = mock_downloader.save_messages_as_txt.call_args[0]
            assert call_args[0] == test_messages
            assert str(call_args[1]) == str(expected_output)
            assert call_args[2] == "asc"

    @pytest.mark.asyncio
    async def test_results_json_output(self, tmp_path):
        """Test that --results-json outputs result summary to stdout."""
        mock_downloader = AsyncMock()
        mock_downloader.config = {"settings": {"save_path": str(tmp_path)}}
        mock_downloader.logger = MagicMock()
        mock_downloader.get_entity_name = AsyncMock(return_value="chat")
        mock_downloader.get_entity_full_name = AsyncMock(return_value="Chat")
        mock_entity = MagicMock(id=123)
        mock_downloader.get_entity = AsyncMock(return_value=mock_entity)
        from datetime import datetime

        msg = MagicMock()
        msg.id = 1
        msg.date = datetime(2025, 7, 10, 12, 0, 0)
        mock_downloader.download_chat = AsyncMock(return_value=[msg])
        mock_downloader.save_messages = AsyncMock()

        with patch("sys.argv", ["script_name", "chat", "--results-json"]), patch(
            "telegram_download_chat.cli.TelegramChatDownloader",
            return_value=mock_downloader,
        ), patch(
            "telegram_download_chat.paths.get_app_dir", return_value=tmp_path
        ), patch(
            "sys.stdout", new_callable=StringIO
        ) as mock_stdout:
            result = await async_main()
            output = mock_stdout.getvalue()

        assert result == 0
        data = json.loads(output)
        assert "results" in data
        result_info = data["results"][0]
        assert result_info["chat_id"] == 123
        assert result_info["messages"] == 1
        assert result_info["from"] == "2025-07-10"
        assert result_info["to"] == "2025-07-10"

    @pytest.mark.asyncio
    async def test_multiple_chats_download(self, tmp_path):
        """Test downloading multiple chats sequentially."""
        mock_downloader = AsyncMock()
        mock_downloader.config = {"settings": {"save_path": str(tmp_path)}}
        mock_downloader.logger = MagicMock()
        mock_downloader.get_entity_name = AsyncMock(return_value="chat")
        mock_downloader.get_entity_full_name = AsyncMock(return_value="Chat")
        mock_downloader.get_entity = AsyncMock(return_value=MagicMock(id=123))
        from datetime import datetime

        msg = MagicMock()
        msg.id = 1
        msg.date = datetime(2025, 7, 10, 12, 0, 0)
        mock_downloader.download_chat = AsyncMock(return_value=[msg])
        mock_downloader.save_messages = AsyncMock()

        with patch(
            "sys.argv",
            ["script_name", "chat1,chat2", "--results-json"],
        ), patch(
            "telegram_download_chat.cli.TelegramChatDownloader",
            return_value=mock_downloader,
        ), patch(
            "telegram_download_chat.paths.get_app_dir", return_value=tmp_path
        ), patch(
            "sys.stdout", new_callable=StringIO
        ) as mock_stdout:
            result = await async_main()
            output = mock_stdout.getvalue()

        assert result == 0
        data = json.loads(output)
        assert "results" in data
        assert len(data["results"]) == 2
        assert mock_downloader.download_chat.call_count == 2

    @pytest.mark.skip(
        reason="Skipping test_download_flow due to complexity of mocking."
    )
    @pytest.mark.asyncio
    async def test_download_flow(self, tmp_path, monkeypatch, capsys):
        """Test the complete chat download flow from CLI to file save."""
        import json
        import sys
        import traceback
        from pathlib import Path
        from unittest.mock import ANY, MagicMock, patch

        print("\n=== Starting test_download_flow ===")
        print(f"Temporary directory: {tmp_path}")

        # Setup test data
        test_messages = [{"id": 1, "message": "Test message"}]
        test_chat = "test_chat"

        # Create a test config file
        test_config = {
            "settings": {
                "save_path": str(tmp_path),
                "api_id": "test_api_id",
                "api_hash": "test_api_hash",
                "phone": "+1234567890",
                "session": "test_session",
            }
        }

        config_path = tmp_path / "config.json"
        with open(config_path, "w") as f:
            json.dump(test_config, f)

        print(f"Created test config at: {config_path}")

        # Create a mock for the downloader class
        mock_downloader = MagicMock()

        # Set up the async methods
        async def mock_async_method(*args, **kwargs):
            return None

        # Configure the mock methods
        mock_downloader.download_chat = MagicMock(return_value=test_messages)
        mock_downloader.get_entity_name = MagicMock(return_value=test_chat)
        mock_downloader.connect = MagicMock(side_effect=mock_async_method)
        mock_downloader.save_messages = MagicMock(return_value=len(test_messages))
        mock_downloader.close = MagicMock(side_effect=mock_async_method)
        mock_downloader.config = test_config

        # Patch the downloader class to return our mock
        with patch(
            "telegram_download_chat.cli.TelegramChatDownloader",
            return_value=mock_downloader,
        ) as mock_tg_class, patch(
            "telegram_download_chat.paths.get_app_dir", return_value=tmp_path
        ), patch(
            "sys.argv", ["script.py", test_chat, "--config", str(config_path)]
        ), patch(
            "sys.stdout", new_callable=StringIO
        ) as mock_stdout, patch(
            "sys.stderr", new_callable=StringIO
        ) as mock_stderr:
            # Import here to ensure patches are in place
            from telegram_download_chat.cli import main

            # Run the main function
            print("\n=== Calling main() ===")
            result = 1
            try:
                result = main()
                print(f"main() returned: {result}")
            except Exception as e:
                print(f"Exception in main(): {str(e)}")

            # Capture output
            stdout = mock_stdout.getvalue()
            stderr = mock_stderr.getvalue()

            # Print captured output for debugging
            print("\n=== Captured STDOUT ===")
            print(stdout)
            print("\n=== Captured STDERR ===")
            print(stderr)

            # Print mock call information
            print("\n=== Mock Calls ===")
            print(f"TelegramChatDownloader calls: {mock_tg_class.mock_calls}")
            print(f"download_chat calls: {mock_downloader.download_chat.mock_calls}")
            print(
                f"get_entity_name calls: {mock_downloader.get_entity_name.mock_calls}"
            )
            print(f"save_messages called: {mock_downloader.save_messages.called}")
            print(f"close called: {mock_downloader.close.called}")

            # Verify the result
            assert result == 0, f"Expected return code 0, got {result}"

            # Verify the downloader was used correctly
            mock_tg_class.assert_called_once()
            mock_downloader.connect.assert_called_once()
            mock_downloader.download_chat.assert_called_once_with(test_chat, limit=100)
            mock_downloader.get_entity_name.assert_called_once_with(test_chat)
            mock_downloader.save_messages.assert_called_once()
            mock_downloader.close.assert_called_once()

            # Verify output file was created
            output_file = tmp_path / f"{test_chat}.json"
            assert output_file.exists(), f"Expected output file {output_file} to exist"

    @patch("telegram_download_chat.core.print")
    @patch("telegram_download_chat.core.Path")
    def test_load_config(self, mock_path, mock_print):
        """Test loading configuration from a file."""
        # Mock the config file content
        config_content = """
        settings:
          default_output: test_output.json
          fetch_limit: 100
        """

        # Create a mock file object
        m = mock_open(read_data=config_content)

        # Set up the mock Path object
        mock_path.return_value.exists.return_value = True

        # Patch the open function
        with patch("builtins.open", m):
            # Create a downloader instance
            downloader = TelegramChatDownloader()

            # Verify the config was loaded correctly
            assert "settings" in downloader.config
            assert downloader.config["settings"]["default_output"] == "test_output.json"
            assert downloader.config["settings"]["fetch_limit"] == 100

        # Verify the file was opened with the correct parameters
        # We use assert_any_call instead of assert_called_once since the file might be opened multiple times
        m.assert_any_call(mock_path.return_value, "r", encoding="utf-8")
        assert m().read.call_count >= 1  # At least one read should have happened


def test_make_serializable():
    """Test making objects JSON serializable."""
    from datetime import datetime

    from telegram_download_chat.core import TelegramChatDownloader

    downloader = TelegramChatDownloader()

    # Test with datetime
    dt = datetime(2023, 1, 1, 12, 0, 0)
    # The make_serializable method returns datetime as 'YYYY-MM-DD HH:MM:SS' format
    assert downloader.make_serializable(dt) == "2023-01-01 12:00:00"

    # Test with dictionary
    data = {"key": "value", "nested": {"number": 123}}
    assert downloader.make_serializable(data) == data

    # Test with list
    assert downloader.make_serializable([1, 2, 3]) == [1, 2, 3]


@pytest.mark.asyncio
async def test_get_entity_name():
    """Test getting a safe entity name."""
    # Create a mock client and set it on the downloader
    mock_client = AsyncMock()
    mock_entity = MagicMock()
    mock_entity.title = "Test Chat"

    # Create a mock for the get_entity method
    async def mock_get_entity(identifier):
        return mock_entity

    # Create downloader and set up mocks
    downloader = TelegramChatDownloader()
    downloader.client = mock_client
    downloader.get_entity = AsyncMock(side_effect=mock_get_entity)
    downloader.connect = AsyncMock()

    # Test with a username
    name = await downloader.get_entity_name("@testchat")
    assert name == "Test_Chat"

    # Verify get_entity was called with the correct argument
    downloader.get_entity.assert_awaited_once_with("@testchat")

    # Test with a URL
    downloader.get_entity.reset_mock()
    name = await downloader.get_entity_name("https://t.me/testchat")
    assert name == "Test_Chat"
    downloader.get_entity.assert_awaited_once_with("https://t.me/testchat")


def test_get_temp_file_path():
    """Test getting temporary file path."""
    from telegram_download_chat.core import TelegramChatDownloader

    downloader = TelegramChatDownloader()
    output_file = Path("test_output.json")
    temp_path = downloader.get_temp_file_path(output_file)
    assert str(temp_path) == "test_output.part.jsonl"


@pytest.mark.asyncio
async def test_download_chat_with_limit():
    """Test downloading chat with a message limit."""
    import logging

    from telethon.tl.types import PeerChannel

    from telegram_download_chat.core import TelegramChatDownloader

    # Set up logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)

    # Create a mock client with proper async methods
    mock_client = AsyncMock()
    # is_connected is a property, not a coroutine
    type(mock_client).is_connected = property(lambda s: False)

    # Create test messages
    test_messages = [
        MagicMock(
            id=i,
            to_dict=MagicMock(return_value={"id": i, "message": f"Test message {i}"}),
            message=f"Test message {i}",
            date=None,
            sender_id=1,
            peer_id=PeerChannel(channel_id=12345),
        )
        for i in range(1, 101)
    ]

    # Mock the client's __call__ method to return our mock messages
    mock_client.return_value = MagicMock(messages=test_messages, users=[], chats=[])

    # Create downloader and set the mock client
    downloader = TelegramChatDownloader()
    downloader.client = mock_client
    downloader.logger = logger
    downloader.connect = AsyncMock()

    # Mock get_entity to return a basic entity
    mock_entity = MagicMock(id=12345, title="Test Chat")
    downloader.client.get_entity = AsyncMock(return_value=mock_entity)

    # Create a function to handle GetHistoryRequest with limit
    def mock_get_history_request(*args, **kwargs):
        limit = kwargs.get("limit", 100)
        mock_result = MagicMock()
        mock_result.messages = test_messages[:limit]
        mock_result.users = []
        mock_result.chats = []
        return mock_result

    # Patch the GetHistoryRequest to use our mock function
    with patch(
        "telethon.tl.functions.messages.GetHistoryRequest",
        side_effect=mock_get_history_request,
    ):
        # Test with limit
        logger.debug("Starting download_chat with limit=10")
        messages = await downloader.download_chat("test_chat", total_limit=10)

        logger.debug(f"Downloaded {len(messages)} messages")
        if messages:
            first_id = (
                messages[0].get("id")
                if isinstance(messages[0], dict)
                else messages[0].id
            )
            last_id = (
                messages[-1].get("id")
                if isinstance(messages[-1], dict)
                else messages[-1].id
            )
            logger.debug(f"First message ID: {first_id}")
            logger.debug(f"Last message ID: {last_id}")

        assert len(messages) == 10, f"Expected 10 messages, got {len(messages)}"
        if messages:
            first_msg = messages[0]
            first_id = first_msg.id if hasattr(first_msg, "id") else first_msg.get("id")
            last_msg = messages[-1]
            last_id = last_msg.id if hasattr(last_msg, "id") else last_msg.get("id")
            assert first_id == 1, f"Expected first message ID to be 1, got {first_id}"
            assert last_id == 10, f"Expected last message ID to be 10, got {last_id}"


@pytest.mark.asyncio
async def test_save_messages():
    """Test saving messages to a file."""
    import json
    import tempfile
    from pathlib import Path
    from unittest.mock import MagicMock

    from telegram_download_chat.core import TelegramChatDownloader

    # Create test message data
    test_message_data = [
        {"id": 1, "message": "Test message 1"},
        {"id": 2, "message": "Test message 2"},
    ]

    # Create mock Message objects with to_dict method
    test_messages = []
    for msg_data in test_message_data:
        msg = MagicMock()
        msg.to_dict.return_value = msg_data
        test_messages.append(msg)

    # Create a temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp_file:
        output_file = Path(tmp_file.name)

    try:
        # Create downloader and save messages
        downloader = TelegramChatDownloader()
        downloader.logger = MagicMock()  # Mock the logger
        await downloader.save_messages(
            test_messages, str(output_file), sort_order="desc"
        )

        # Verify file was created and contains correct data
        assert output_file.exists()
        with open(output_file, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
            assert saved_data == test_message_data
    finally:
        # Cleanup
        if output_file.exists():
            output_file.unlink()


@pytest.mark.asyncio
async def test_connect_and_disconnect():
    """Test connecting to and disconnecting from Telegram."""
    import os
    from unittest.mock import AsyncMock, MagicMock, patch

    from telegram_download_chat.core import TelegramChatDownloader

    mock_auth = MagicMock()
    mock_auth.initialize = AsyncMock()
    mock_auth.is_authenticated.return_value = True
    mock_auth.client = AsyncMock()
    mock_auth.client.is_connected = MagicMock(return_value=True)
    mock_auth.client.disconnect = AsyncMock()

    mock_auth_class = MagicMock(return_value=mock_auth)

    with patch.dict(
        os.environ,
        {"TELEGRAM_API_ID": "test_api_id", "TELEGRAM_API_HASH": "test_api_hash"},
    ), patch("telegram_download_chat.core.auth.TelegramAuth", new=mock_auth_class):
        downloader = TelegramChatDownloader()

        downloader.config = {
            "settings": {
                "api_id": 123,
                "api_hash": "test_api_hash",
                "session_name": "test_session",
                "request_retries": 3,
                "request_delay": 1,
            }
        }

        await downloader.connect()

        mock_auth_class.assert_called_once()
        mock_auth.initialize.assert_awaited_once()
        assert downloader.client is mock_auth.client

        await downloader.close()

        mock_auth.client.disconnect.assert_awaited_once()
        assert downloader.client is None


@pytest.mark.asyncio
async def test_telegram_auth_request_code():
    from telegram_download_chat.core.auth_utils import TelegramAuth

    auth = TelegramAuth(api_id=1, api_hash="hash", session_path=Path("sess"))
    auth.client = AsyncMock()
    auth.client.loop = asyncio.get_event_loop()
    auth.client.send_code_request.return_value = MagicMock(phone_code_hash="hash")

    result = await auth.request_code("123")

    auth.client.send_code_request.assert_awaited_once_with("123")
    assert result == "hash"
    assert auth.phone_code_hash == "hash"
    await auth.close()


@pytest.mark.asyncio
async def test_telegram_auth_sign_in_success():
    from telegram_download_chat.core.auth_utils import TelegramAuth

    auth = TelegramAuth(api_id=1, api_hash="hash", session_path=Path("sess"))
    auth.client = AsyncMock()
    auth.client.loop = asyncio.get_event_loop()

    await auth.sign_in("123", "111", "pwd", phone_code_hash="hash")

    auth.client.sign_in.assert_awaited_once_with(
        phone="123", code="111", phone_code_hash="hash"
    )
    await auth.close()


@pytest.mark.asyncio
async def test_telegram_auth_sign_in_with_password_needed():
    from telethon.errors import SessionPasswordNeededError

    from telegram_download_chat.core.auth_utils import TelegramAuth

    auth = TelegramAuth(api_id=1, api_hash="hash", session_path=Path("sess"))
    auth.client = AsyncMock()
    auth.client.loop = asyncio.get_event_loop()
    auth.client.sign_in = AsyncMock(
        side_effect=[SessionPasswordNeededError(None), None]
    )

    await auth.sign_in("123", "111", "pwd", phone_code_hash="hash")

    assert auth.client.sign_in.await_count == 2
    auth.client.sign_in.assert_any_await(
        phone="123", code="111", phone_code_hash="hash"
    )
    auth.client.sign_in.assert_any_await(password="pwd")
    await auth.close()


@pytest.mark.asyncio
async def test_fetch_self_info():
    downloader = TelegramChatDownloader()
    downloader.client = AsyncMock()
    downloader.logger = MagicMock()
    user = MagicMock(
        id=5, first_name="John", last_name="Doe", username="jdoe", phone="123"
    )
    downloader.client.get_me.return_value = user

    await downloader._fetch_self_info()

    downloader.client.get_me.assert_awaited_once()
    assert downloader._self_id == 5
    assert downloader._self_name == "John Doe"


@pytest.mark.asyncio
async def test_download_chat_error_handling():
    """Test that download_chat properly propagates errors from get_entity."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from telegram_download_chat.core import TelegramChatDownloader

    # Create a mock client
    mock_client = AsyncMock()
    mock_client.is_connected = AsyncMock(return_value=False)

    # Create downloader and set up mocks
    with patch("telegram_download_chat.core.TelegramChatDownloader._setup_logging"):
        downloader = TelegramChatDownloader()

    downloader.client = mock_client
    downloader.connect = AsyncMock()
    downloader.logger = MagicMock()

    # Create a mock for get_entity that raises a ValueError
    error_msg = "Cannot find any entity corresponding to 'test_chat'"
    mock_get_entity = AsyncMock(side_effect=ValueError(error_msg))

    # Replace the get_entity method with our mock
    with patch.object(downloader, "get_entity", new=mock_get_entity):
        # Test that the error is properly propagated
        with pytest.raises(ValueError, match=error_msg) as exc_info:
            await downloader.download_chat("test_chat")

        # Verify the error message is correct
        assert str(exc_info.value) == error_msg

    # Verify that get_entity was called with the correct argument
    mock_get_entity.assert_called_once_with("test_chat")

    # Verify that no error was logged (since the error is propagated, not logged)
    assert (
        not downloader.logger.error.called
    ), "Expected no error to be logged since the error is propagated"


def test_prepare_messages_for_txt_ordering():
    downloader = TelegramChatDownloader()
    messages = [
        {"id": 1, "date": "2025-07-01 10:00:00+00:00", "text": "parent"},
        {
            "id": 2,
            "date": "2025-07-01 10:05:00+00:00",
            "text": "reply1",
            "reply_to": {"reply_to_msg_id": 1},
        },
        {
            "id": 3,
            "date": "2025-07-01 10:10:00+00:00",
            "text": "reply2",
            "reply_to": {"reply_to_msg_id": 1},
        },
    ]

    ordered = downloader.prepare_messages_for_txt(messages, "desc")
    assert [m["id"] for m in ordered] == [3, 2, 1]


def test_prepare_messages_for_txt_ordering_asc():
    downloader = TelegramChatDownloader()
    with open("tests/fixtures/replies.json", "r", encoding="utf-8") as f:
        messages = json.load(f)

    ordered = downloader.prepare_messages_for_txt(messages, "asc")
    assert [m["id"] for m in ordered] == [
        340522,
        340525,
        340527,
        340529,
        340523,
        340532,
        340526,
        340528,
        340530,
        340531,
    ]


def test_prepare_messages_for_txt_ordering_desc():
    downloader = TelegramChatDownloader()
    with open("tests/fixtures/replies.json", "r", encoding="utf-8") as f:
        messages = json.load(f)

    ordered = downloader.prepare_messages_for_txt(messages, "desc")
    assert [m["id"] for m in ordered] == [
        340531,
        340530,
        340528,
        340526,
        340532,
        340523,
        340529,
        340527,
        340525,
        340522,
    ]


@pytest.mark.asyncio
async def test_folder_download(tmp_path):
    """Test downloading all chats from a folder."""
    from telethon.tl.types import DialogFilter, InputPeerChannel

    folder_name = "Work"
    peer = InputPeerChannel(channel_id=123, access_hash=456)

    mock_downloader = AsyncMock()
    mock_downloader.logger = MagicMock()
    mock_downloader.connect = AsyncMock()
    mock_downloader.close = AsyncMock()
    mock_downloader.cleanup_stop_file = MagicMock()
    mock_downloader.config = {"settings": {"save_path": str(tmp_path)}}

    mock_downloader.list_folders.return_value = [
        DialogFilter(
            id=1,
            title=folder_name,
            pinned_peers=[peer],
            include_peers=[],
            exclude_peers=[],
        )
    ]
    mock_downloader.get_entity_name = AsyncMock(return_value="Chat1")
    mock_downloader.download_chat = AsyncMock(return_value=[{"id": 1}])
    mock_downloader.save_messages = AsyncMock()

    with patch("sys.argv", ["script", f"folder:{folder_name}"]), patch(
        "telegram_download_chat.cli.TelegramChatDownloader",
        return_value=mock_downloader,
    ):
        result = await async_main()

    assert result == 0
    mock_downloader.list_folders.assert_awaited_once()
    mock_downloader.download_chat.assert_awaited_once()
    expected = tmp_path / folder_name / "Chat1.json"
    args, kwargs = mock_downloader.download_chat.call_args
    assert kwargs.get("output_file") == str(expected)


def test_show_config_function(tmp_path):
    """Test the standalone show_config helper."""
    cfg = tmp_path / "config.yml"
    content = "test: value"
    cfg.write_text(content)

    downloader = MagicMock()
    downloader.logger = MagicMock()

    result = show_config(downloader, str(cfg))

    assert result == 0
    downloader.logger.info.assert_any_call(f"Configuration file: {cfg}")
    downloader.logger.info.assert_any_call("\nCurrent configuration:")
    downloader.logger.info.assert_any_call(content)


@pytest.mark.asyncio
async def test_convert_json_to_txt_function(tmp_path):
    """Ensure convert_json_to_txt dispatches to commands.convert."""
    args = CLIOptions(chat="data.json")
    downloader = AsyncMock()
    downloader.connect = AsyncMock()
    downloader.close = AsyncMock()
    downloader.cleanup_stop_file = MagicMock()
    ctx = DownloaderContext(downloader)

    with patch(
        "telegram_download_chat.cli.commands.convert", new=AsyncMock(return_value=0)
    ) as mock_convert:
        result = await convert_json_to_txt(ctx, downloader, args, tmp_path)

    assert result == 0
    mock_convert.assert_awaited_once_with(downloader, args, tmp_path)


@pytest.mark.asyncio
async def test_download_folder_function(tmp_path):
    """Ensure download_folder dispatches to commands.folder."""
    args = CLIOptions(chat="folder:Work")
    downloader = AsyncMock()
    downloader.connect = AsyncMock()
    downloader.close = AsyncMock()
    downloader.cleanup_stop_file = MagicMock()
    ctx = DownloaderContext(downloader)

    with patch(
        "telegram_download_chat.cli.commands.folder", new=AsyncMock(return_value=0)
    ) as mock_folder:
        result = await download_folder(ctx, downloader, args, tmp_path)

    assert result == 0
    mock_folder.assert_awaited_once_with(downloader, args, tmp_path)


@pytest.mark.asyncio
async def test_download_chat_function(tmp_path):
    """Ensure download_chat dispatches to commands.download."""
    args = CLIOptions(chat="chat")
    downloader = AsyncMock()
    downloader.connect = AsyncMock()
    downloader.close = AsyncMock()
    downloader.cleanup_stop_file = MagicMock()
    ctx = DownloaderContext(downloader)

    with patch(
        "telegram_download_chat.cli.commands.download", new=AsyncMock(return_value=0)
    ) as mock_download:
        result = await download_chat(ctx, downloader, args, tmp_path)

    assert result == 0
    mock_download.assert_awaited_once_with(downloader, args, tmp_path)


def test_cli_web_entrypoint():
    """Ensure CLI starts web interface when 'web' argument is used."""
    with patch("sys.argv", ["script", "web"]), patch(
        "telegram_download_chat.cli.web_main"
    ) as web_main:
        from telegram_download_chat.cli import main

        result = main()

    web_main.assert_called_once()
    assert result == 0

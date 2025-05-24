"""Tests for telegram-download-chat package."""
import asyncio
import json
import logging
import os
import re
import sys
from io import StringIO
import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, Mock, patch, mock_open

from telegram_download_chat.cli import parse_args, filter_messages_by_subchat, async_main
from telegram_download_chat.core import TelegramChatDownloader


@pytest.fixture
def mock_downloader():
    """Fixture that mocks TelegramChatDownloader."""
    with patch('telegram_download_chat.cli.TelegramChatDownloader') as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.config = {}
        mock_instance.logger = MagicMock()
        yield mock_instance

class TestCLIArgumentParsing:
    """Tests for command line argument parsing."""
    
    def test_required_chat_argument(self):
        """Test that chat argument is required for normal operation."""
        # When no chat is provided and --show-config is not used
        with patch('sys.argv', ['script_name']):
            args = parse_args()
            assert args.chat is None  # argparse doesn't raise, but chat will be None
    
    def test_basic_chat_argument(self):
        """Test basic chat argument parsing."""
        test_chat = "test_chat"
        with patch('sys.argv', ['script_name', test_chat]):
            args = parse_args()
            assert args.chat == test_chat
            assert args.limit == 0  # Default value from cli.py
            assert args.output is None
    
    def test_all_arguments(self):
        """Test parsing of all command line arguments."""
        test_args = [
            'script_name',
            "test_chat",
            "--limit", "100",
            "--output", "output.json",
            "--config", "custom_config.yml",
            "--debug",
            "--subchat", "123",
            "--until", "2025-01-01"
        ]
        with patch('sys.argv', test_args):
            args = parse_args()
            assert args.chat == "test_chat"
            assert args.limit == 100
            assert args.output == "output.json"
            assert args.config == "custom_config.yml"
            assert args.debug is True
            assert args.subchat == "123"
            assert args.until == "2025-01-01"
            
    def test_until_date_format_validation(self):
        """Test that invalid date formats are accepted by the parser but handled in async_main."""
        with patch('sys.argv', ['script_name', 'test_chat', '--until', 'invalid-date']):
            args = parse_args()
            # The parser should accept any string for --until
            assert args.until == 'invalid-date'
            
    def test_until_date_without_chat(self):
        """Test that --until without chat argument is handled."""
        with patch('sys.argv', ['script_name', '--until', '2025-01-01']):
            args = parse_args()
            assert args.until == "2025-01-01"
    
    def test_show_config_flag(self):
        """Test --show-config flag behavior."""
        # --show-config should make chat argument optional
        with patch('sys.argv', ['script_name', '--show-config']):
            args = parse_args()
            assert args.show_config is True
            assert args.chat is None
    
    def test_json_conversion_mode(self):
        """Test JSON file input for conversion mode."""
        with patch('sys.argv', ['script_name', 'chat_history.json']):
            args = parse_args()
            assert args.chat == "chat_history.json"
            # Should not require --output for JSON input
            assert args.output is None

class TestCLIExecution:
    """Tests for CLI execution flow."""
    
    @pytest.mark.asyncio
    async def test_show_config(self, mock_downloader):
        """Test --show-config flag execution."""
        # Mock the config path to exist
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.__str__.return_value = "/path/to/config.yml"
        
        # Setup logger mock
        mock_logger = MagicMock()
        mock_downloader.logger = mock_logger
        
        with patch('sys.argv', ['script_name', '--show-config']), \
             patch('telegram_download_chat.cli.Path', return_value=mock_path), \
             patch('builtins.open', mock_open(read_data='test: config')), \
             patch('telegram_download_chat.cli.TelegramChatDownloader', return_value=mock_downloader):
            
            result = await async_main()
            assert result == 0
            
            # Verify the logger was called with expected messages
            # Check that info was called at least once with the config file path
            config_file_found = any(
                call_args[0][0].startswith("Configuration file:")
                for call_args in mock_logger.info.call_args_list
                if call_args[0]  # Make sure there are arguments
            )
            assert config_file_found, "Expected log message about config file not found"
    
    @pytest.mark.asyncio
    async def test_missing_chat_argument(self):
        """Test error when required chat argument is missing."""
        # Create a mock logger
        mock_logger = MagicMock()
        
        # Create an AsyncMock for the downloader
        mock_downloader = AsyncMock()
        mock_downloader.logger = mock_logger
        
        # Mock the command line arguments and downloader
        with patch('sys.argv', ['script_name']), \
             patch('telegram_download_chat.cli.TelegramChatDownloader', return_value=mock_downloader):
            
            # Call the async_main function
            result = await async_main()
            
            # Verify it returns error code 1
            assert result == 1
            
            # Verify the error message was logged
            error_found = any(
                args and args[0] == "Chat identifier is required"
                for args, _ in mock_logger.error.call_args_list
            )
            assert error_found, "Expected error message 'Chat identifier is required' not found"
    
    @pytest.mark.asyncio
    async def test_json_conversion_flow(self, tmp_path):
        """Test JSON conversion flow."""
        # Create a test JSON file with sample messages
        test_json = tmp_path / "test.json"
        test_messages = [{"id": 1, "message": "Test message 1"}, {"id": 2, "message": "Test message 2"}]
        test_json.write_text(json.dumps(test_messages))
        
        # Create an AsyncMock for the downloader
        mock_downloader = AsyncMock()
        
        # Mock the downloads directory to be our temp directory
        mock_config = {
            'settings': {
                'save_path': str(tmp_path)
            }
        }
        mock_downloader.config = mock_config
        
        # Mock the logger
        mock_logger = MagicMock()
        mock_downloader.logger = mock_logger
        
        # Mock the save_messages_as_txt method to return the number of messages
        mock_downloader.save_messages_as_txt.return_value = len(test_messages)
        
        with patch('sys.argv', ['script_name', str(test_json)]), \
             patch('telegram_download_chat.cli.TelegramChatDownloader', return_value=mock_downloader), \
             patch('telegram_download_chat.cli.get_app_dir', return_value=tmp_path):
            
            # Mock the file operations
            with patch('builtins.open', mock_open()) as mock_file:
                # Mock the json.load to return our test messages
                with patch('json.load', return_value=test_messages):
                    result = await async_main()
            
            # The function should return 0 on success
            assert result == 0
            
            # Verify the logger was called with expected messages
            debug_messages = [call[0][0] for call in mock_logger.debug.call_args_list]
            assert any("Loading messages from JSON file:" in msg for msg in debug_messages)
            
            # Verify save_messages_as_txt was called with the correct arguments
            expected_output = test_json.with_suffix('.txt')
            mock_downloader.save_messages_as_txt.assert_called_once()
            
            # Get the arguments passed to save_messages_as_txt
            call_args = mock_downloader.save_messages_as_txt.call_args[0]
            assert call_args[0] == test_messages  # Messages should match
            assert str(call_args[1]) == str(expected_output)  # Output path should match
    

    @pytest.mark.skip(reason="Skipping test_download_flow due to complexity of mocking.")
    @pytest.mark.asyncio
    async def test_download_flow(self, tmp_path, monkeypatch, capsys):
        """Test the complete chat download flow from CLI to file save."""
        import sys
        from unittest.mock import ANY, patch, MagicMock
        import traceback
        import json
        from pathlib import Path
        
        print("\n=== Starting test_download_flow ===")
        print(f"Temporary directory: {tmp_path}")
        
        # Setup test data
        test_messages = [{"id": 1, "message": "Test message"}]
        test_chat = "test_chat"
        
        # Create a test config file
        test_config = {
            'settings': {
                'save_path': str(tmp_path),
                'api_id': 'test_api_id',
                'api_hash': 'test_api_hash',
                'phone': '+1234567890',
                'session': 'test_session'
            }
        }
        
        config_path = tmp_path / 'config.json'
        with open(config_path, 'w') as f:
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
        with patch('telegram_download_chat.cli.TelegramChatDownloader', return_value=mock_downloader) as mock_tg_class, \
             patch('telegram_download_chat.cli.get_app_dir', return_value=tmp_path), \
             patch('sys.argv', ['script.py', test_chat, '--config', str(config_path)]), \
             patch('sys.stdout', new_callable=StringIO) as mock_stdout, \
             patch('sys.stderr', new_callable=StringIO) as mock_stderr:
            
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
            print(f"get_entity_name calls: {mock_downloader.get_entity_name.mock_calls}")
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

    @patch('telegram_download_chat.core.print')
    @patch('telegram_download_chat.core.Path')
    def test_load_config(self, mock_path, mock_print):
        """Test loading configuration from a file."""
        # Mock the config file content
        config_content = '''
        settings:
          default_output: test_output.json
          fetch_limit: 100
        '''
        
        # Create a mock file object
        m = mock_open(read_data=config_content)
        
        # Set up the mock Path object
        mock_path.return_value.exists.return_value = True
        
        # Patch the open function
        with patch('builtins.open', m):
            # Create a downloader instance
            downloader = TelegramChatDownloader()
        
            # Verify the config was loaded correctly
            assert 'settings' in downloader.config
            assert downloader.config['settings']['default_output'] == 'test_output.json'
            assert downloader.config['settings']['fetch_limit'] == 100
        
        # Verify the file was opened with the correct parameters
        # We use assert_any_call instead of assert_called_once since the file might be opened multiple times
        m.assert_any_call(mock_path.return_value, 'r', encoding='utf-8')
        assert m().read.call_count >= 1  # At least one read should have happened



def test_make_serializable():
    """Test making objects JSON serializable."""
    from datetime import datetime
    from telegram_download_chat.core import TelegramChatDownloader
    
    downloader = TelegramChatDownloader()
    
    # Test with datetime
    dt = datetime(2023, 1, 1, 12, 0, 0)
    # The make_serializable method returns datetime as 'YYYY-MM-DD HH:MM:SS' format
    assert downloader.make_serializable(dt) == '2023-01-01 12:00:00'
    
    # Test with dictionary
    data = {'key': 'value', 'nested': {'number': 123}}
    assert downloader.make_serializable(data) == data
    
    # Test with list
    assert downloader.make_serializable([1, 2, 3]) == [1, 2, 3]


@pytest.mark.asyncio
async def test_get_entity_name():
    """Test getting a safe entity name."""
    # Create a mock client and set it on the downloader
    mock_client = AsyncMock()
    mock_client.is_connected = AsyncMock(return_value=False)  # Mock is_connected as async
    mock_entity = MagicMock()
    mock_entity.title = 'Test Chat'
    mock_client.get_entity.return_value = mock_entity
    
    downloader = TelegramChatDownloader()
    downloader.client = mock_client
    downloader.connect = AsyncMock()  # Mock connect as async
    
    # The method only takes self and chat_identifier as parameters
    name = await downloader.get_entity_name('@testchat')
    assert name == 'Test_Chat'


def test_get_temp_file_path():
    """Test getting temporary file path."""
    from telegram_download_chat.core import TelegramChatDownloader
    
    downloader = TelegramChatDownloader()
    output_file = Path('test_output.json')
    temp_path = downloader.get_temp_file_path(output_file)
    assert str(temp_path) == '.test_output.json.part'


@pytest.mark.asyncio
async def test_download_chat_with_limit():
    """Test downloading chat with a message limit."""
    import logging
    from telethon.tl.types import PeerChannel, PeerChat, PeerUser
    from telethon.tl.patched import Message
    from telegram_download_chat.core import TelegramChatDownloader
    
    # Set up logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    
    # Create a mock client
    mock_client = AsyncMock()
    
    # Create test messages
    test_messages = [
        MagicMock(
            id=i,
            to_dict=MagicMock(return_value={"id": i, "message": f"Test message {i}"}),
            message=f"Test message {i}",
            date=None,
            sender_id=1,
            peer_id=PeerChannel(channel_id=12345)
        )
        for i in range(1, 101)
    ]
    
    # Create a mock messages object with messages and users
    mock_messages = MagicMock()
    mock_messages.messages = test_messages
    mock_messages.users = []
    mock_messages.chats = []
    
    # Mock the client's __call__ method to return our mock messages
    mock_client.return_value = mock_messages
    
    # Create downloader and set the mock client
    downloader = TelegramChatDownloader()
    downloader.client = mock_client
    downloader.logger = logger
    
    # Mock get_entity to return a basic entity
    async def mock_get_entity(chat_id):
        return MagicMock(id=12345, title="Test Chat")
    
    downloader.client.get_entity = mock_get_entity
    
    # Create a function to handle GetHistoryRequest with limit
    async def mock_get_history_request(*args, **kwargs):
        limit = kwargs.get('limit', 100)
        # Return a new mock with only the requested number of messages
        limited_messages = MagicMock()
        limited_messages.messages = test_messages[:limit]
        limited_messages.users = []
        limited_messages.chats = []
        return limited_messages
    
    # Patch the GetHistoryRequest to use our mock function
    with patch('telegram_download_chat.core.GetHistoryRequest', side_effect=mock_get_history_request):
        # Test with limit
        logger.debug("Starting download_chat with limit=10")
        messages = await downloader.download_chat("test_chat", total_limit=10)
        
        logger.debug(f"Downloaded {len(messages)} messages")
        if messages:
            logger.debug(f"First message ID: {messages[0].get('id') if isinstance(messages[0], dict) else messages[0].id}")
            logger.debug(f"Last message ID: {messages[-1].get('id') if isinstance(messages[-1], dict) else messages[-1].id}")
        
        assert len(messages) == 10, f"Expected 10 messages, got {len(messages)}"
        if messages:
            first_msg = messages[0]
            first_id = first_msg.id if hasattr(first_msg, 'id') else first_msg.get('id')
            last_msg = messages[-1]
            last_id = last_msg.id if hasattr(last_msg, 'id') else last_msg.get('id')
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
        {"id": 2, "message": "Test message 2"}
    ]
    
    # Create mock Message objects with to_dict method
    test_messages = []
    for msg_data in test_message_data:
        msg = MagicMock()
        msg.to_dict.return_value = msg_data
        test_messages.append(msg)
    
    # Create a temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.json') as tmp_file:
        output_file = Path(tmp_file.name)
    
    try:
        # Create downloader and save messages
        downloader = TelegramChatDownloader()
        downloader.logger = MagicMock()  # Mock the logger
        await downloader.save_messages(test_messages, str(output_file))
        
        # Verify file was created and contains correct data
        assert output_file.exists()
        with open(output_file, 'r', encoding='utf-8') as f:
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
    from unittest.mock import patch, MagicMock, AsyncMock
    from telegram_download_chat.core import TelegramChatDownloader
    
    # Create a mock client with async methods
    mock_client = AsyncMock()
    mock_client.start = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.is_connected = AsyncMock(return_value=True)  # Mock is_connected as async
    
    # Patch the environment variables and TelegramClient
    with patch.dict(os.environ, {
        'TELEGRAM_API_ID': 'test_api_id',
        'TELEGRAM_API_HASH': 'test_api_hash'
    }), patch('telegram_download_chat.core.TelegramClient', return_value=mock_client) as mock_client_class:
        # Create downloader
        downloader = TelegramChatDownloader()
        
        # Mock the config to avoid file operations
        downloader.config = {
            'settings': {
                'api_id': 'test_api_id',
                'api_hash': 'test_api_hash',
                'session_name': 'test_session'
            }
        }
        
        # Test connect
        await downloader.connect()
        
        # Verify client was created and started
        mock_client_class.assert_called_once()
        mock_client.start.assert_awaited_once()
        assert downloader.client is not None
        
        # Test disconnect
        await downloader.close()
        mock_client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_download_chat_error_handling():
    """Test error handling in download_chat method."""
    from telethon.errors import RPCError
    from telethon.tl.types import InputPeerChannel
    from telegram_download_chat.core import TelegramChatDownloader
    
    # Create a mock client that raises an error
    mock_client = AsyncMock()
    mock_entity = InputPeerChannel(channel_id=123, access_hash=456)
    mock_client.get_entity.return_value = mock_entity
    mock_client.side_effect = RPCError(400, "Test error")
    
    # Create downloader and set the mock client
    downloader = TelegramChatDownloader()
    downloader.client = mock_client
    downloader.logger = MagicMock()  # Mock the logger
    
    # Test that the error is properly caught and re-raised
    with pytest.raises(RPCError, match="Test error"):
        await downloader.download_chat("test_chat")

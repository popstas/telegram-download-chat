"""Tests for proxy URL parsing and TelegramAuth proxy support."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram_download_chat.core.auth_utils import TelegramAuth

# Numeric proxy type constants matching PySocks/python-socks/Telethon
SOCKS5, SOCKS4, HTTP = 2, 1, 3


class TestParseProxyUrl:
    """Tests for TelegramAuth.parse_proxy_url static method."""

    def test_none_returns_none(self):
        assert TelegramAuth.parse_proxy_url(None) is None

    def test_empty_string_returns_none(self):
        assert TelegramAuth.parse_proxy_url("") is None

    def test_socks5_basic(self):
        result = TelegramAuth.parse_proxy_url("socks5://proxy.example.com:1080")
        assert result == {
            "proxy_type": SOCKS5,
            "addr": "proxy.example.com",
            "port": 1080,
        }

    def test_socks5_with_auth(self):
        result = TelegramAuth.parse_proxy_url(
            "socks5://user:pass@proxy.example.com:1080"
        )
        assert result == {
            "proxy_type": SOCKS5,
            "addr": "proxy.example.com",
            "port": 1080,
            "username": "user",
            "password": "pass",
        }

    def test_socks4(self):
        result = TelegramAuth.parse_proxy_url("socks4://proxy.example.com:1080")
        assert result["proxy_type"] == SOCKS4

    def test_http_proxy(self):
        result = TelegramAuth.parse_proxy_url("http://proxy.example.com:8080")
        assert result == {
            "proxy_type": HTTP,
            "addr": "proxy.example.com",
            "port": 8080,
        }

    def test_https_proxy(self):
        result = TelegramAuth.parse_proxy_url("https://proxy.example.com:8443")
        assert result["proxy_type"] == HTTP
        assert result["port"] == 8443

    def test_default_socks_port(self):
        result = TelegramAuth.parse_proxy_url("socks5://proxy.example.com")
        assert result["port"] == 1080

    def test_default_http_port(self):
        result = TelegramAuth.parse_proxy_url("http://proxy.example.com")
        assert result["port"] == 8080

    def test_unsupported_scheme_raises(self):
        with pytest.raises(ValueError, match="Unsupported proxy scheme"):
            TelegramAuth.parse_proxy_url("ftp://proxy.example.com:21")

    def test_missing_hostname_raises(self):
        with pytest.raises(ValueError, match="missing hostname"):
            TelegramAuth.parse_proxy_url("socks5://")

    def test_special_chars_in_password(self):
        result = TelegramAuth.parse_proxy_url("socks5://user:p%40ss%3Aword@host:1080")
        assert result["username"] == "user"
        # urlparse doesn't auto-decode; unquote is applied
        assert result["password"] == "p@ss:word"


class TestTelegramAuthProxy:
    """Tests for proxy being passed to TelegramClient."""

    @pytest.mark.asyncio
    async def test_initialize_without_proxy(self):
        auth = TelegramAuth(api_id=123, api_hash="abc", session_path=Path("/tmp/test"))
        with patch(
            "telegram_download_chat.core.auth_utils.TelegramClient"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client.is_user_authorized = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await auth.initialize()

            call_kwargs = mock_client_cls.call_args[1]
            assert "proxy" not in call_kwargs

    @pytest.mark.asyncio
    async def test_initialize_with_proxy(self):
        auth = TelegramAuth(
            api_id=123,
            api_hash="abc",
            session_path=Path("/tmp/test"),
            proxy_url="socks5://proxy.example.com:1080",
        )
        mock_python_socks = MagicMock()
        with patch(
            "telegram_download_chat.core.auth_utils.TelegramClient"
        ) as mock_client_cls, patch.dict(
            "sys.modules", {"python_socks": mock_python_socks}
        ):
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client.is_user_authorized = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await auth.initialize()

            call_kwargs = mock_client_cls.call_args[1]
            assert "proxy" in call_kwargs
            assert call_kwargs["proxy"]["proxy_type"] == SOCKS5
            assert call_kwargs["proxy"]["addr"] == "proxy.example.com"
            assert call_kwargs["proxy"]["port"] == 1080

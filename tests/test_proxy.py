"""Tests for proxy URL parsing and TelegramAuth proxy support."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate

from telegram_download_chat.core.auth_utils import TelegramAuth, TelegramAuthError

# Numeric proxy type constants matching PySocks/python-socks/Telethon
SOCKS5, SOCKS4, HTTP = 2, 1, 3
MT_SECRET = "dd0123456789abcdef0123456789abcdef"


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

    def test_tg_mtproto_proxy(self):
        result = TelegramAuth.parse_proxy_url(
            "tg://proxy?server=mtproxy.example.com&port=443&secret=" + MT_SECRET
        )
        assert result == {
            "proxy_type": "mtproto",
            "addr": "mtproxy.example.com",
            "port": 443,
            "secret": MT_SECRET,
        }

    def test_tme_mtproto_proxy(self):
        result = TelegramAuth.parse_proxy_url(
            "https://t.me/proxy?server=1.2.3.4&port=8443&secret=" + MT_SECRET
        )
        assert result == {
            "proxy_type": "mtproto",
            "addr": "1.2.3.4",
            "port": 8443,
            "secret": MT_SECRET,
        }

    def test_http_tme_mtproto_link_rejected(self):
        with pytest.raises(ValueError, match="must use https://t.me/proxy"):
            TelegramAuth.parse_proxy_url(
                "http://t.me/proxy?server=1.2.3.4&port=443&secret=" + MT_SECRET
            )

    def test_mtproto_missing_server_raises(self):
        with pytest.raises(ValueError, match="missing server"):
            TelegramAuth.parse_proxy_url("tg://proxy?port=443&secret=" + MT_SECRET)

    def test_mtproto_invalid_port_raises(self):
        with pytest.raises(ValueError, match="port must be an integer"):
            TelegramAuth.parse_proxy_url(
                "tg://proxy?server=mtproxy.example.com&port=invalid&secret=" + MT_SECRET
            )

    @pytest.mark.parametrize("port", ["0", "65536"])
    def test_mtproto_out_of_range_port_raises(self, port):
        with pytest.raises(ValueError, match="between 1 and 65535"):
            TelegramAuth.parse_proxy_url(
                f"tg://proxy?server=mtproxy.example.com&port={port}&secret=" + MT_SECRET
            )

    def test_mtproto_missing_secret_raises(self):
        with pytest.raises(ValueError, match="missing secret"):
            TelegramAuth.parse_proxy_url(
                "tg://proxy?server=mtproxy.example.com&port=443"
            )

    def test_mtproto_error_does_not_include_secret(self):
        url = "tg://proxy?server=mtproxy.example.com&port=invalid&secret=" + MT_SECRET
        with pytest.raises(ValueError) as exc_info:
            TelegramAuth.parse_proxy_url(url)

        assert MT_SECRET not in str(exc_info.value)

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
            mock_client.is_connected.return_value = False
            mock_client.is_user_authorized = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await auth.initialize()

            call_kwargs = mock_client_cls.call_args[1]
            assert "proxy" not in call_kwargs
            assert "connection" not in call_kwargs
            await auth.close()

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
            mock_client.is_connected.return_value = False
            mock_client.is_user_authorized = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await auth.initialize()

            call_kwargs = mock_client_cls.call_args[1]
            assert "proxy" in call_kwargs
            assert call_kwargs["proxy"]["proxy_type"] == SOCKS5
            assert call_kwargs["proxy"]["addr"] == "proxy.example.com"
            assert call_kwargs["proxy"]["port"] == 1080
            assert "connection" not in call_kwargs
            await auth.close()

    @pytest.mark.asyncio
    async def test_initialize_with_mtproto_proxy(self):
        auth = TelegramAuth(
            api_id=123,
            api_hash="abc",
            session_path=Path("/tmp/test"),
            proxy_url=(
                "https://t.me/proxy?server=mtproxy.example.com&port=443&secret="
                + MT_SECRET
            ),
        )
        with patch(
            "telegram_download_chat.core.auth_utils.TelegramClient"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client.is_connected.return_value = False
            mock_client.is_user_authorized = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await auth.initialize()

            call_kwargs = mock_client_cls.call_args[1]
            assert (
                call_kwargs["connection"] is ConnectionTcpMTProxyRandomizedIntermediate
            )
            assert call_kwargs["proxy"] == ("mtproxy.example.com", 443, MT_SECRET)
            await auth.close()

    @pytest.mark.asyncio
    async def test_mtproto_connect_error_does_not_include_secret(self):
        auth = TelegramAuth(
            api_id=123,
            api_hash="abc",
            session_path=Path("/tmp/test"),
            proxy_url=(
                "tg://proxy?server=mtproxy.example.com&port=443&secret=" + MT_SECRET
            ),
        )
        with patch(
            "telegram_download_chat.core.auth_utils.TelegramClient"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock(
                side_effect=RuntimeError("proxy failed with secret " + MT_SECRET)
            )
            mock_client.is_connected.return_value = False
            mock_client_cls.return_value = mock_client

            with pytest.raises(TelegramAuthError) as exc_info:
                await auth.initialize()

            assert MT_SECRET not in str(exc_info.value)
            assert exc_info.value.__cause__ is None
            assert exc_info.value.__suppress_context__ is True
            await auth.close()

    @pytest.mark.asyncio
    async def test_request_code_reconnect_error_does_not_log_secret(self, caplog):
        auth = TelegramAuth(
            api_id=123,
            api_hash="abc",
            session_path=Path("/tmp/test"),
            proxy_url=(
                "tg://proxy?server=mtproxy.example.com&port=443&secret=" + MT_SECRET
            ),
        )
        auth._proxy_config = TelegramAuth.parse_proxy_url(auth.proxy_url)

        mock_client = MagicMock()
        mock_client.is_connected.return_value = False
        mock_client.connect = AsyncMock(
            side_effect=RuntimeError("reconnect failed with secret " + MT_SECRET)
        )
        mock_client.send_code_request = AsyncMock()
        auth.client = mock_client

        caplog.set_level(logging.DEBUG, logger="telegram_download_chat.core.auth_utils")
        with pytest.raises(TelegramAuthError) as exc_info:
            await auth.request_code("+10000000000")

        assert MT_SECRET not in str(exc_info.value)
        assert MT_SECRET not in caplog.text
        mock_client.send_code_request.assert_not_awaited()
        await auth.close()

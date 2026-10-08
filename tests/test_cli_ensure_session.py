"""A download may offer an interactive login, but only on a real terminal.

The GUI runs downloads with ``stdin=DEVNULL`` and the console-less Windows
build has no stdin at all; prompting there is what killed the download with
"lost sys.stdin" (issue #91). A terminal, on the other hand, is exactly where
a login prompt belongs.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram_download_chat.cli.login import ensure_session


def _downloader(authorized: bool):
    downloader = MagicMock()
    downloader.logger = MagicMock()
    downloader.prepare_client = AsyncMock(return_value=authorized)
    downloader.close = AsyncMock()
    downloader.config = {"settings": {}}
    downloader.client = MagicMock()
    downloader.client.start = AsyncMock()
    downloader.client.get_me = AsyncMock(return_value=MagicMock(username="popstas"))
    return downloader


def _tty(answer: str):
    """A terminal that answers the login question with ``answer``."""
    stdin = MagicMock()
    stdin.isatty.return_value = True
    return patch("sys.stdin", stdin), patch("builtins.input", return_value=answer)


@pytest.mark.asyncio
async def test_an_existing_session_asks_nothing():
    downloader = _downloader(authorized=True)

    with patch("builtins.input", side_effect=AssertionError("must not prompt")):
        assert await ensure_session(downloader) is True

    downloader.client.start.assert_not_called()


@pytest.mark.asyncio
async def test_without_a_terminal_it_reports_instead_of_prompting():
    downloader = _downloader(authorized=False)

    with patch("sys.stdin", None):
        with patch("builtins.input", side_effect=AssertionError("must not prompt")):
            assert await ensure_session(downloader) is False

    message = downloader.logger.error.call_args[0][0]
    assert "login" in message


@pytest.mark.asyncio
async def test_declining_the_offer_keeps_the_instruction():
    downloader = _downloader(authorized=False)
    stdin_patch, input_patch = _tty("n")

    with stdin_patch, input_patch:
        assert await ensure_session(downloader) is False

    downloader.client.start.assert_not_called()
    assert "login" in downloader.logger.error.call_args[0][0]
    # The client opened by the session check must not hold the session file.
    downloader.close.assert_awaited()


@pytest.mark.asyncio
async def test_accepting_logs_in_with_a_code(capsys):
    downloader = _downloader(authorized=False)
    stdin_patch, input_patch = _tty("")  # bare Enter accepts

    with stdin_patch, input_patch:
        assert await ensure_session(downloader) is True

    kwargs = downloader.client.start.await_args.kwargs
    from telegram_download_chat.cli import login as login_mod

    assert kwargs["code_callback"] is login_mod._prompt_code
    assert "popstas" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_q_logs_in_by_qr_code():
    downloader = _downloader(authorized=False)
    stdin_patch, input_patch = _tty("q")
    user = MagicMock(username="popstas")
    seen = {}

    async def fake_qr_login(client, *, on_code, **kwargs):
        seen["called"] = True
        return user

    with stdin_patch, input_patch:
        with patch("telegram_download_chat.cli.login.qr_login", new=fake_qr_login):
            assert await ensure_session(downloader) is True

    assert seen["called"]
    downloader.client.start.assert_not_called()


@pytest.mark.asyncio
async def test_a_failed_login_is_reported_as_a_line(capsys):
    from telegram_download_chat.core.qr_login import QrLoginError

    downloader = _downloader(authorized=False)
    stdin_patch, input_patch = _tty("q")

    async def fake_qr_login(client, **kwargs):
        raise QrLoginError("The QR code was not scanned in time.")

    with stdin_patch, input_patch:
        with patch("telegram_download_chat.cli.login.qr_login", new=fake_qr_login):
            assert await ensure_session(downloader) is False

    assert "not scanned" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_an_interrupted_question_is_a_refusal():
    downloader = _downloader(authorized=False)
    stdin = MagicMock()
    stdin.isatty.return_value = True

    with patch("sys.stdin", stdin):
        with patch("builtins.input", side_effect=EOFError):
            assert await ensure_session(downloader) is False

    downloader.client.start.assert_not_called()


@pytest.mark.asyncio
async def test_a_download_stops_when_no_session_can_be_had():
    from telegram_download_chat import cli

    downloader = _downloader(authorized=False)
    downloader.set_stop_file = MagicMock()
    downloader.cleanup_stop_file = MagicMock()

    with patch("sys.argv", ["telegram-download-chat", "popstas"]):
        with patch.object(cli, "TelegramChatDownloader", return_value=downloader):
            with patch.object(
                cli, "ensure_session", new=AsyncMock(return_value=False)
            ) as ensure:
                assert await cli.async_main() == 1

    ensure.assert_awaited_once_with(downloader)


@pytest.mark.asyncio
async def test_converting_a_json_file_needs_no_session():
    """`chat.json` is read from disk, so it must not ask about logging in."""
    from telegram_download_chat import cli

    downloader = _downloader(authorized=False)
    downloader.set_stop_file = MagicMock()
    downloader.cleanup_stop_file = MagicMock()

    with patch("sys.argv", ["telegram-download-chat", "chat.json"]):
        with patch.object(cli, "TelegramChatDownloader", return_value=downloader):
            with patch.object(cli, "ensure_session", new=AsyncMock()) as ensure:
                with patch.object(
                    cli, "convert_json_to_txt", new=AsyncMock(return_value={})
                ):
                    await cli.async_main()

    ensure.assert_not_awaited()

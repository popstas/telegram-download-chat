"""The `login` command is the only place the CLI may prompt (issue #91)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telegram_download_chat.cli.login import parse_login_args, run_login
from telegram_download_chat.core.qr_login import QrLoginTimeout


def _downloader(authorized: bool):
    downloader = MagicMock()
    downloader.logger = MagicMock()
    downloader.prepare_client = AsyncMock(return_value=authorized)
    downloader.close = AsyncMock()
    downloader.client = MagicMock()
    downloader.client.start = AsyncMock()
    downloader.client.get_me = AsyncMock(
        return_value=MagicMock(username="popstas", phone="41791234567")
    )
    downloader.client.is_user_authorized = AsyncMock(return_value=True)
    downloader.config = {"settings": {}}
    return downloader


def test_parse_login_args():
    assert parse_login_args([]).qr is False
    assert parse_login_args(["--qr"]).qr is True
    assert parse_login_args(["--qr", "--debug"]).debug is True
    assert parse_login_args(["--config", "/tmp/c.yml"]).config == "/tmp/c.yml"


def test_main_dispatches_login_to_run_login():
    from telegram_download_chat import cli

    with patch.object(cli, "asyncio") as aio:
        with patch("sys.argv", ["telegram-download-chat", "login", "--qr"]):
            cli.main()

    coro = aio.run.call_args[0][0]
    assert coro.cr_code.co_name == "run_login"
    coro.close()


@pytest.mark.asyncio
async def test_already_logged_in_does_not_prompt(capsys):
    downloader = _downloader(authorized=True)

    with patch(
        "telegram_download_chat.cli.login.TelegramChatDownloader",
        return_value=downloader,
    ):
        assert await run_login(qr=False) == 0

    assert "popstas" in capsys.readouterr().out
    downloader.client.start.assert_not_called()


@pytest.mark.asyncio
async def test_qr_login_renders_the_code_and_reports_success(capsys):
    downloader = _downloader(authorized=False)
    user = MagicMock(username="popstas")

    async def fake_qr_login(client, *, on_code, password=None, **kwargs):
        on_code("tg://login?token=abc")
        return user

    with patch(
        "telegram_download_chat.cli.login.TelegramChatDownloader",
        return_value=downloader,
    ):
        with patch("telegram_download_chat.cli.login.qr_login", new=fake_qr_login):
            assert await run_login(qr=True) == 0

    out = capsys.readouterr().out
    assert "█" in out  # the QR code itself
    assert "tg://login?token=abc" in out  # pasteable fallback
    assert "popstas" in out
    downloader.client.start.assert_not_called()
    downloader.close.assert_awaited()


@pytest.mark.asyncio
async def test_qr_timeout_reports_failure(capsys):
    downloader = _downloader(authorized=False)

    async def fake_qr_login(client, **kwargs):
        raise QrLoginTimeout("not scanned")

    with patch(
        "telegram_download_chat.cli.login.TelegramChatDownloader",
        return_value=downloader,
    ):
        with patch("telegram_download_chat.cli.login.qr_login", new=fake_qr_login):
            assert await run_login(qr=True) == 1

    assert "not scanned" in capsys.readouterr().err
    downloader.close.assert_awaited()


@pytest.mark.asyncio
async def test_code_login_uses_telethon_interactive_start():
    downloader = _downloader(authorized=False)

    with patch(
        "telegram_download_chat.cli.login.TelegramChatDownloader",
        return_value=downloader,
    ):
        assert await run_login(qr=False) == 0

    downloader.client.start.assert_awaited_once()
    kwargs = downloader.client.start.await_args.kwargs
    assert callable(kwargs["phone"])  # prompts only here
    assert callable(kwargs["password"])


@pytest.mark.asyncio
async def test_code_login_prefills_phone_from_config():
    downloader = _downloader(authorized=False)
    downloader.config = {"settings": {"phone": "+41791234567"}}

    with patch(
        "telegram_download_chat.cli.login.TelegramChatDownloader",
        return_value=downloader,
    ):
        await run_login(qr=False)

    assert downloader.client.start.await_args.kwargs["phone"] == "+41791234567"


def test_qr_is_drawn_plain_when_ansi_is_not_supported(capsys):
    from telegram_download_chat.cli import login as login_mod

    with patch.object(login_mod, "_ansi_supported", return_value=False):
        login_mod._print_qr("tg://login?token=abc")

    out = capsys.readouterr().out
    assert "\x1b[" not in out
    assert "█" in out and "tg://login?token=abc" in out


def test_qr_uses_ansi_when_supported(capsys):
    from telegram_download_chat.cli import login as login_mod

    with patch.object(login_mod, "_ansi_supported", return_value=True):
        login_mod._print_qr("tg://login?token=abc")

    assert "\x1b[30;107m" in capsys.readouterr().out


def test_ansi_not_claimed_without_a_terminal():
    from telegram_download_chat.cli import login as login_mod

    with patch("sys.stdout.isatty", return_value=False):
        assert login_mod._ansi_supported() is False


def test_password_prompt_without_a_terminal_explains_itself():
    """No tty means no password prompt: getpass would echo it or raise EOFError."""
    from telegram_download_chat.cli import login as login_mod

    with patch("sys.stdin") as stdin:
        stdin.isatty.return_value = False
        with pytest.raises(login_mod.NoTerminalError) as excinfo:
            login_mod._prompt_password()

    message = str(excinfo.value)
    assert "terminal" in message and "GUI" in message


def test_phone_prompt_without_a_terminal_explains_itself():
    from telegram_download_chat.cli import login as login_mod

    with patch("sys.stdin", None):
        with pytest.raises(login_mod.NoTerminalError):
            login_mod._prompt_phone()


@pytest.mark.asyncio
async def test_failure_without_a_message_still_names_the_error(capsys):
    """EOFError and friends stringify to "", which printed a bare "Login failed:"."""
    downloader = _downloader(authorized=False)

    async def fake_qr_login(client, **kwargs):
        raise EOFError()

    with patch(
        "telegram_download_chat.cli.login.TelegramChatDownloader",
        return_value=downloader,
    ):
        with patch("telegram_download_chat.cli.login.qr_login", new=fake_qr_login):
            assert await run_login(qr=True) == 1

    assert "EOFError" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_no_terminal_error_is_reported_without_a_traceback_prefix(capsys):
    from telegram_download_chat.cli import login as login_mod

    downloader = _downloader(authorized=False)

    async def fake_qr_login(client, *, on_code, password=None, **kwargs):
        password()

    with patch(
        "telegram_download_chat.cli.login.TelegramChatDownloader",
        return_value=downloader,
    ):
        with patch("telegram_download_chat.cli.login.qr_login", new=fake_qr_login):
            with patch("sys.stdin", None):
                assert await run_login(qr=True) == 1

    err = capsys.readouterr().err
    assert "Login failed" not in err  # it is guidance, not a crash
    assert "terminal" in err


def test_code_prompt_without_a_terminal_explains_itself():
    """Telethon's own `start()` would prompt for the code with a bare input()."""
    from telegram_download_chat.cli import login as login_mod

    with patch("sys.stdin", None):
        with pytest.raises(login_mod.NoTerminalError):
            login_mod._prompt_code()


@pytest.mark.asyncio
async def test_code_login_owns_the_code_prompt():
    downloader = _downloader(authorized=False)

    with patch(
        "telegram_download_chat.cli.login.TelegramChatDownloader",
        return_value=downloader,
    ):
        await run_login(qr=False)

    from telegram_download_chat.cli import login as login_mod

    kwargs = downloader.client.start.await_args.kwargs
    assert kwargs["code_callback"] is login_mod._prompt_code

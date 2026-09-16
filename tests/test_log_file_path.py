"""A relative ``log_file`` resolves against the app dir, not the working dir.

The README documents ``log_file`` as "relative to app dir or absolute", but a
relative value used to be handed straight to ``FileHandler``, so the log landed
in whatever directory the terminal happened to be in (issue #91).
"""

import logging
from pathlib import Path

import pytest

from telegram_download_chat.core import TelegramChatDownloader


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    app = tmp_path / "app"
    monkeypatch.setattr("telegram_download_chat.core.config.get_app_dir", lambda: app)
    return app


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


def _file_handler_paths(settings):
    downloader = TelegramChatDownloader.__new__(TelegramChatDownloader)
    downloader.config = {"settings": settings}
    downloader._setup_logging()
    handlers = [
        h for h in downloader.logger.handlers if isinstance(h, logging.FileHandler)
    ]
    paths = [Path(h.baseFilename) for h in handlers]
    for h in list(downloader.logger.handlers):
        h.close()
        downloader.logger.removeHandler(h)
    return paths


def test_default_log_file_in_app_dir(app_dir, cwd):
    assert _file_handler_paths({}) == [app_dir / "app.log"]


def test_relative_log_file_resolves_against_app_dir(app_dir, cwd):
    assert _file_handler_paths({"log_file": "logs/tdc.log"}) == [
        app_dir / "logs" / "tdc.log"
    ]
    assert (app_dir / "logs" / "tdc.log").exists()
    assert not (cwd / "logs").exists()


def test_absolute_log_file_kept(app_dir, cwd, tmp_path):
    target = tmp_path / "elsewhere" / "tdc.log"
    assert _file_handler_paths({"log_file": str(target)}) == [target]


def test_empty_log_file_disables_file_logging(app_dir, cwd):
    assert _file_handler_paths({"log_file": ""}) == []

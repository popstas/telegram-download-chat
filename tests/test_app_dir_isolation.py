"""The suite must never write into the developer's real application directory."""

from pathlib import Path

from telegram_download_chat.paths import get_app_dir, get_default_config_path


def test_app_dir_is_isolated(isolated_app_dir):
    assert Path(get_app_dir()).is_relative_to(isolated_app_dir)
    assert Path(get_default_config_path()).is_relative_to(isolated_app_dir)
    assert Path.home() == Path(isolated_app_dir)

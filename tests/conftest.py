"""Test-wide isolation of the application directory.

The GUI builds a real ``ConfigManager``, and widgets save settings on close.
With the developer's own ``$HOME`` in place that wrote an empty config over
``~/.local/share/telegram-download-chat/config.yml`` — API credentials and all —
during a plain ``pytest`` run. Every test now gets a throwaway home, so nothing
can touch the real session, config or downloads.
"""

import os

import pytest

_HOME_VARS = ("HOME", "USERPROFILE", "APPDATA", "XDG_DATA_HOME", "XDG_CONFIG_HOME")


@pytest.fixture(autouse=True, scope="session")
def isolated_app_dir(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    (home / ".local" / "share").mkdir(parents=True, exist_ok=True)

    saved = {name: os.environ.get(name) for name in _HOME_VARS}
    os.environ["HOME"] = str(home)
    os.environ["USERPROFILE"] = str(home)
    os.environ["APPDATA"] = str(home / "AppData" / "Roaming")
    os.environ.pop("XDG_DATA_HOME", None)
    os.environ.pop("XDG_CONFIG_HOME", None)

    yield home

    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

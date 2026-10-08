"""`python -m telegram_download_chat` must exit non-zero on failure.

The GUI starts downloads as `sys.executable -m telegram_download_chat` and now
reports a non-zero exit code as a failure. `__main__` used to call `main()` and
drop its return value, so every failure exited 0 and the GUI called a crashed
download "completed" (issue #91).
"""

import os
import subprocess
import sys
from pathlib import Path

CONFIG = "settings:\n  api_id: 12345\n  api_hash: 0123456789abcdef0123456789abcdef\n"


def _home(tmp_path: Path) -> Path:
    for app_dir in (
        tmp_path / ".local" / "share" / "telegram-download-chat",
        tmp_path / "AppData" / "Roaming" / "telegram-download-chat",
    ):
        app_dir.mkdir(parents=True)
        (app_dir / "config.yml").write_text(CONFIG)
    return tmp_path


def _run(home: Path, *args: str) -> subprocess.CompletedProcess:
    # Repoint the same variables tests/conftest.py does, so the subprocess
    # cannot reach the developer's own app dir on any platform. Windows needs
    # the inherited environment (SYSTEMROOT) for Python to start at all.
    env = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData" / "Roaming"),
    }
    env.pop("XDG_DATA_HOME", None)
    env.pop("XDG_CONFIG_HOME", None)
    return subprocess.run(
        [sys.executable, "-m", "telegram_download_chat", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_module_entry_point_propagates_a_failure(tmp_path):
    # --subchat without a JSON input fails before any network call.
    result = _run(_home(tmp_path), "somechat", "--subchat", "1")

    assert result.returncode == 1, result.stdout + result.stderr


def test_module_entry_point_reports_success(tmp_path):
    result = _run(_home(tmp_path), "--version")

    assert result.returncode == 0, result.stdout + result.stderr

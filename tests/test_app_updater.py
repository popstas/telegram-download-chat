"""Tests for runtime in-app self-update (core/app_updater.py).

The shipped package owns the runtime half of the two-part build: detecting an
embeddable install, downloading ``app-<version>.zip``, and atomically swapping
the ``app/`` directory. (Build-time ``build_app_zip`` lives in
``scripts/package_embed.py``.)
"""

import zipfile
from pathlib import Path

import pytest

from telegram_download_chat.core import app_updater


def _make_app_zip(zip_path: Path, version: str) -> Path:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("telegram_download_chat/__init__.py", f"__version__='{version}'\n")
        zf.writestr("telegram_download_chat/core/__init__.py", "")
        zf.writestr("telegram_download_chat/_version.py", f"version='{version}'\n")
        zf.writestr("version.txt", version)
    return zip_path


def _install(tmp_path: Path, version: str, extra: dict | None = None) -> Path:
    app = tmp_path / "install" / "app" / "telegram_download_chat"
    app.mkdir(parents=True)
    (app / "__init__.py").write_text("old\n", encoding="utf-8")
    for rel, content in (extra or {}).items():
        (app / rel).write_text(content, encoding="utf-8")
    (tmp_path / "install" / "app" / "version.txt").write_text(version, encoding="utf-8")
    return tmp_path / "install"


# ── apply_app_update / read_installed_version ───────────────────────────────


def test_read_installed_version(tmp_path):
    install = _install(tmp_path, "1.0.0")
    assert app_updater.read_installed_version(install) == "1.0.0"
    assert app_updater.read_installed_version(tmp_path / "nope") is None


def test_apply_app_update_replaces_app(tmp_path):
    zip_path = _make_app_zip(tmp_path / "dist" / "app-2.0.0.zip", "2.0.0")
    install = _install(tmp_path, "1.0.0", extra={"stale.py": "x\n"})

    version = app_updater.apply_app_update(zip_path, install)

    assert version == "2.0.0"
    assert app_updater.read_installed_version(install) == "2.0.0"
    pkg = install / "app" / "telegram_download_chat"
    assert (pkg / "core" / "__init__.py").exists()
    assert not (pkg / "stale.py").exists()
    assert [p.name for p in install.iterdir()] == ["app"]


def test_apply_app_update_bad_sha_leaves_install_intact(tmp_path):
    zip_path = _make_app_zip(tmp_path / "dist" / "app-2.0.0.zip", "2.0.0")
    install = _install(tmp_path, "1.0.0")
    with pytest.raises(ValueError):
        app_updater.apply_app_update(zip_path, install, expected_sha256="deadbeef")
    assert app_updater.read_installed_version(install) == "1.0.0"
    assert [p.name for p in install.iterdir()] == ["app"]


def test_apply_app_update_invalid_payload_rolls_back(tmp_path):
    bad = tmp_path / "dist" / "bad.zip"
    bad.parent.mkdir(parents=True)
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("version.txt", "9.9.9")  # no package payload
    install = _install(tmp_path, "1.0.0")
    with pytest.raises(ValueError):
        app_updater.apply_app_update(bad, install)
    assert app_updater.read_installed_version(install) == "1.0.0"
    assert (install / "app" / "telegram_download_chat" / "__init__.py").exists()


# ── find_app_install_dir ────────────────────────────────────────────────────


def test_find_app_install_dir_detects_embeddable(tmp_path):
    # Layout: <install>/app/telegram_download_chat/__init__.py + <install>/runtime
    pkg_init = tmp_path / "install" / "app" / "telegram_download_chat" / "__init__.py"
    pkg_init.parent.mkdir(parents=True)
    pkg_init.write_text("", encoding="utf-8")
    (tmp_path / "install" / "runtime").mkdir()

    found = app_updater.find_app_install_dir(pkg_file=pkg_init)
    assert found == tmp_path / "install"


def test_find_app_install_dir_none_when_not_embeddable(tmp_path):
    # A normal dev/pip layout (no app/ + runtime/ wrappers).
    pkg_init = tmp_path / "site-packages" / "telegram_download_chat" / "__init__.py"
    pkg_init.parent.mkdir(parents=True)
    pkg_init.write_text("", encoding="utf-8")
    assert app_updater.find_app_install_dir(pkg_file=pkg_init) is None


# ── download + orchestration ────────────────────────────────────────────────


def test_download_app_zip_via_file_url(tmp_path):
    src = _make_app_zip(tmp_path / "src" / "app-3.0.0.zip", "3.0.0")
    dest = tmp_path / "dl" / "app.zip"
    out = app_updater.download_app_zip(src.as_uri(), dest)
    assert out == dest
    assert dest.read_bytes() == src.read_bytes()


def test_perform_app_update_downloads_and_applies(tmp_path):
    src = _make_app_zip(tmp_path / "src" / "app-2.5.0.zip", "2.5.0")
    install = _install(tmp_path, "1.0.0")

    version = app_updater.perform_app_update(src.as_uri(), install_dir=install)

    assert version == "2.5.0"
    assert app_updater.read_installed_version(install) == "2.5.0"


def test_perform_app_update_raises_without_install_dir(tmp_path):
    src = _make_app_zip(tmp_path / "src" / "app-2.5.0.zip", "2.5.0")
    # No install_dir and not running from an embeddable install -> refuse.
    with pytest.raises(RuntimeError):
        app_updater.perform_app_update(
            src.as_uri(), install_dir=None, _install_finder=lambda: None
        )

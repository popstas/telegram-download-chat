"""Runtime in-app self-update for the two-part embeddable Windows build.

The shipped app is the ``app/`` half of the distribution (see
``docs/superpowers/specs/2026-06-04-windows-two-part-embed-build-design.md`` and
``scripts/package_embed.py``). This module — which ships *inside* that app — knows
how to update it: detect the embeddable install, download ``app-<version>.zip``,
and atomically swap the ``app/`` directory.

Everything here is cross-platform and dependency-free (stdlib only) so it can be
unit-tested on any OS and called from the GUI's "Update now" action. The heavy
``runtime/`` base (embeddable CPython + all packages) is never touched by an
update.

Manual use on an installed system::

    runtime\\python\\python.exe -m telegram_download_chat.core.app_updater \\
        apply app-<version>.zip <install-dir>
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

APP_DIRNAME = "app"
APP_PACKAGE = "telegram_download_chat"
VERSION_FILE = "version.txt"
_HASH_CHUNK = 1024 * 1024
_USER_AGENT = "telegram-download-chat-updater/1.0"


def compute_file_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of ``path``."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_installed_version(install_dir: Path) -> Optional[str]:
    """Return the installed app version from ``install_dir/app/version.txt``."""
    vfile = Path(install_dir) / APP_DIRNAME / VERSION_FILE
    if not vfile.is_file():
        return None
    return vfile.read_text(encoding="utf-8").strip()


def find_app_install_dir(pkg_file: Optional[Path] = None) -> Optional[Path]:
    """Return the embeddable install root, or ``None`` when not applicable.

    A two-part install lays the package out as
    ``<install>/app/telegram_download_chat/`` next to ``<install>/runtime/``.
    Returns ``<install>`` only when that exact shape is present; otherwise
    ``None`` (dev checkout, pip install, PyInstaller bundle) so self-update is
    only offered where it can actually work.
    """
    if pkg_file is None:
        pkg_file = Path(__file__)
    parts = Path(pkg_file).resolve().parts
    # Find the telegram_download_chat package dir; its parent must be "app" with
    # a sibling "runtime" for this to be an embeddable two-part install.
    if APP_PACKAGE not in parts:
        return None
    pkg_root = Path(*parts[: parts.index(APP_PACKAGE) + 1])
    app_dir = pkg_root.parent
    if app_dir.name != APP_DIRNAME:
        return None
    install = app_dir.parent
    if not (install / "runtime").is_dir():
        return None
    return install


def _validate_payload(payload_dir: Path) -> str:
    """Ensure an extracted app payload is well-formed; return its version."""
    pkg_init = payload_dir / APP_PACKAGE / "__init__.py"
    vfile = payload_dir / VERSION_FILE
    if not pkg_init.is_file() or not vfile.is_file():
        raise ValueError(
            f"Invalid app payload: missing {APP_PACKAGE}/__init__.py or {VERSION_FILE}"
        )
    return vfile.read_text(encoding="utf-8").strip()


def apply_app_update(
    zip_path: Path, install_dir: Path, *, expected_sha256: Optional[str] = None
) -> str:
    """Atomically replace ``install_dir/app`` from ``zip_path``; return the version.

    The existing install is never left broken: the zip is verified and extracted
    to a temp directory first, and the directory swap restores the previous
    ``app/`` if anything fails. Temp/backup directories are always cleaned up.
    """
    zip_path = Path(zip_path)
    install_dir = Path(install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)

    if expected_sha256 is not None:
        actual = compute_file_hash(zip_path)
        if actual.lower() != expected_sha256.lower():
            raise ValueError(
                f"Checksum mismatch for {zip_path.name}: "
                f"expected {expected_sha256}, got {actual}"
            )

    app_dir = install_dir / APP_DIRNAME
    staging = install_dir / f".{APP_DIRNAME}.new"
    backup = install_dir / f".{APP_DIRNAME}.bak"
    for stale in (staging, backup):
        if stale.exists():
            shutil.rmtree(stale)

    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(staging)
        version = _validate_payload(staging)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    had_existing = app_dir.exists()
    try:
        if had_existing:
            app_dir.rename(backup)
        staging.rename(app_dir)
    except Exception:
        if had_existing and backup.exists() and not app_dir.exists():
            backup.rename(app_dir)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)

    return version


def download_app_zip(url: str, dest: Path, *, timeout: float = 60) -> Path:
    """Download ``url`` to ``dest`` and return ``dest``."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response, dest.open(
        "wb"
    ) as fh:
        shutil.copyfileobj(response, fh)
    return dest


def perform_app_update(
    zip_url: str,
    *,
    install_dir: Optional[Path] = None,
    expected_sha256: Optional[str] = None,
    timeout: float = 60,
    _install_finder: Callable[[], Optional[Path]] = find_app_install_dir,
) -> str:
    """Download ``zip_url`` and install it onto the current embeddable install.

    Resolves the install dir (``install_dir`` or :func:`find_app_install_dir`),
    refusing with ``RuntimeError`` when this isn't an embeddable install. Returns
    the newly installed version.
    """
    target = Path(install_dir) if install_dir is not None else _install_finder()
    if target is None:
        raise RuntimeError(
            "In-app update is only available for the portable embeddable install."
        )
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = download_app_zip(
            zip_url, Path(tmp) / "app-update.zip", timeout=timeout
        )
        return apply_app_update(zip_path, target, expected_sha256=expected_sha256)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Apply a two-part app update.")
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("apply", help="Apply an app-<version>.zip onto an install")
    a.add_argument("zip", type=Path, help="app-<version>.zip to install")
    a.add_argument("install_dir", type=Path, help="Install root containing app/")
    a.add_argument("--sha256", default=None, help="Expected SHA-256 of the zip")
    args = parser.parse_args(argv)
    version = apply_app_update(args.zip, args.install_dir, expected_sha256=args.sha256)
    print(f"Installed app version {version} into {args.install_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

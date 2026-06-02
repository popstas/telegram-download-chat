#!/usr/bin/env python3
"""Package a PyInstaller ``--onedir`` build into a portable distribution.

The Windows "installer" we ship is portable-only: there is no MSI/registry
footprint. The user downloads a single ``.zip``, extracts it anywhere, and runs
``telegram-download-chat.exe`` from the extracted folder.

This helper is intentionally cross-platform (no Windows-only APIs) so the
packaging logic can be unit-tested on any OS. ``build_windows_portable.ps1``
calls it after PyInstaller produces ``dist/telegram-download-chat/``.

Incremental updates
-------------------
Alongside the zip we emit a ``manifest.json`` describing every file in the
distribution (relative path -> SHA-256 + size). Given the manifest of an
already-installed version and the manifest of a new version, :func:`diff_manifests`
reports exactly which files changed, were added, or were removed. An updater can
use that to copy only the changed files instead of re-extracting the whole tree.

Limitation: PyInstaller bundles the application's Python code together with the
interpreter and third-party packages inside ``_internal`` (the compiled ``PYZ``
archive and shared libraries), so the bundled runtime is not cleanly separable
from the app code. A version bump that only touches our own ``.py`` files still
rewrites the ``PYZ`` archive, so the manifest diff will list that archive as
changed. Incremental updates therefore avoid re-downloading the *unchanged*
files (icons, data files, most DLLs), but the main code archive is always part
of an update. True app-only-vs-runtime separation would require shipping the app
as plain source on top of an embeddable Python, which is out of scope here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Dict

MANIFEST_NAME = "manifest.json"
_HASH_CHUNK = 1024 * 1024


def compute_file_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_manifest(dist_dir: Path, version: str) -> dict:
    """Build a manifest describing every file under ``dist_dir``.

    The manifest itself (``manifest.json``) is skipped if already present so the
    function is idempotent across repeated runs.
    """
    dist_dir = Path(dist_dir)
    files: Dict[str, dict] = {}
    for path in sorted(dist_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(dist_dir).as_posix()
        if rel == MANIFEST_NAME:
            continue
        files[rel] = {
            "sha256": compute_file_hash(path),
            "size": path.stat().st_size,
        }
    return {"version": version, "files": files}


def write_manifest(dist_dir: Path, version: str) -> Path:
    """Write ``manifest.json`` into ``dist_dir`` and return its path."""
    dist_dir = Path(dist_dir)
    manifest = compute_manifest(dist_dir, version)
    manifest_path = dist_dir / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest_path


def create_portable_zip(dist_dir: Path, output_zip: Path) -> Path:
    """Zip the contents of ``dist_dir`` into ``output_zip``.

    Files are stored under a top-level folder named after ``dist_dir`` so the
    user gets a self-contained directory on extraction.
    """
    dist_dir = Path(dist_dir)
    output_zip = Path(output_zip)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    root = dist_dir.name
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(dist_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(dist_dir).as_posix()
            archive.write(path, f"{root}/{rel}")
    return output_zip


def diff_manifests(old: dict, new: dict) -> dict:
    """Compare two manifests and report file-level changes for incremental updates.

    Returns a dict with ``changed`` (added or modified relative paths) and
    ``removed`` (paths gone in ``new``). A file is "changed" when its SHA-256
    differs or it is new.
    """
    old_files = (old or {}).get("files", {})
    new_files = (new or {}).get("files", {})
    changed = sorted(
        rel
        for rel, meta in new_files.items()
        if old_files.get(rel, {}).get("sha256") != meta.get("sha256")
    )
    removed = sorted(rel for rel in old_files if rel not in new_files)
    return {"changed": changed, "removed": removed}


def package(dist_dir: Path, output_dir: Path, version: str) -> dict:
    """Write the manifest and build the portable zip.

    Returns a dict with the ``manifest`` and ``zip`` paths.
    """
    dist_dir = Path(dist_dir)
    if not dist_dir.is_dir():
        raise FileNotFoundError(f"Distribution directory not found: {dist_dir}")
    output_dir = Path(output_dir)
    manifest_path = write_manifest(dist_dir, version)
    zip_path = output_dir / f"{dist_dir.name}-portable-{version}.zip"
    create_portable_zip(dist_dir, zip_path)
    return {"manifest": manifest_path, "zip": zip_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dist_dir",
        type=Path,
        help="PyInstaller --onedir output directory (e.g. dist/telegram-download-chat)",
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Version string embedded in the manifest and zip name",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist"),
        help="Where to write the portable zip (default: dist)",
    )
    args = parser.parse_args(argv)

    result = package(args.dist_dir, args.output_dir, args.version)
    print(f"Manifest: {result['manifest']}")
    print(f"Portable zip: {result['zip']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

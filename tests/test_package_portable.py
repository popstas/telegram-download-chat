"""Tests for the portable Windows packaging helper.

The PyInstaller build itself is Windows-only, but ``scripts/package_portable.py``
is deliberately cross-platform so its manifest/zip/diff logic can be exercised on
any OS. These tests stand in for the (Windows-only, manual) packaging step.
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "package_portable.py"
BUILD_SCRIPT = REPO_ROOT / "build_windows_portable.ps1"


def _load_packager():
    spec = importlib.util.spec_from_file_location("package_portable", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PKG = _load_packager()


def _make_dist(tmp_path: Path) -> Path:
    """Create a fake PyInstaller --onedir layout."""
    dist = tmp_path / "telegram-download-chat"
    (dist / "_internal").mkdir(parents=True)
    (dist / "telegram-download-chat.exe").write_bytes(b"MZ fake exe")
    (dist / "_internal" / "base_library.zip").write_bytes(b"runtime")
    (dist / "_internal" / "icon.ico").write_bytes(b"icon-bytes")
    return dist


def test_compute_manifest_lists_all_files(tmp_path):
    dist = _make_dist(tmp_path)
    manifest = PKG.compute_manifest(dist, "1.2.3")

    assert manifest["version"] == "1.2.3"
    files = manifest["files"]
    assert set(files) == {
        "telegram-download-chat.exe",
        "_internal/base_library.zip",
        "_internal/icon.ico",
    }
    for meta in files.values():
        assert len(meta["sha256"]) == 64
        assert meta["size"] > 0


def test_write_manifest_is_idempotent(tmp_path):
    dist = _make_dist(tmp_path)
    PKG.write_manifest(dist, "1.0.0")
    first = json.loads((dist / PKG.MANIFEST_NAME).read_text())
    # Re-running must not include manifest.json itself in the file list.
    PKG.write_manifest(dist, "1.0.0")
    second = json.loads((dist / PKG.MANIFEST_NAME).read_text())

    assert PKG.MANIFEST_NAME not in first["files"]
    assert first == second


def test_create_portable_zip_has_top_level_folder(tmp_path):
    dist = _make_dist(tmp_path)
    zip_path = tmp_path / "out" / "portable.zip"
    PKG.create_portable_zip(dist, zip_path)

    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    assert "telegram-download-chat/telegram-download-chat.exe" in names
    assert "telegram-download-chat/_internal/base_library.zip" in names


def test_package_emits_manifest_and_versioned_zip(tmp_path):
    dist = _make_dist(tmp_path)
    out = tmp_path / "release"
    result = PKG.package(dist, out, "0.13.0")

    assert result["manifest"] == dist / PKG.MANIFEST_NAME
    assert result["zip"] == out / "telegram-download-chat-portable-0.13.0.zip"
    assert result["manifest"].exists()
    assert result["zip"].exists()


def test_package_missing_dist_raises(tmp_path):
    try:
        PKG.package(tmp_path / "nope", tmp_path, "1.0.0")
    except FileNotFoundError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected FileNotFoundError for missing dist dir")


def test_diff_manifests_reports_changed_added_removed(tmp_path):
    dist = _make_dist(tmp_path)
    old = PKG.compute_manifest(dist, "1.0.0")

    # Modify one file, add one, remove one -> simulate a new release.
    (dist / "telegram-download-chat.exe").write_bytes(b"MZ NEW exe bytes")
    (dist / "_internal" / "new_plugin.dll").write_bytes(b"new")
    (dist / "_internal" / "icon.ico").unlink()
    new = PKG.compute_manifest(dist, "1.1.0")

    diff = PKG.diff_manifests(old, new)
    assert "telegram-download-chat.exe" in diff["changed"]
    assert "_internal/new_plugin.dll" in diff["changed"]
    assert "_internal/icon.ico" in diff["removed"]
    # Unchanged runtime file must NOT be in the incremental update set.
    assert "_internal/base_library.zip" not in diff["changed"]


def test_diff_manifests_identical_is_empty(tmp_path):
    dist = _make_dist(tmp_path)
    manifest = PKG.compute_manifest(dist, "1.0.0")
    diff = PKG.diff_manifests(manifest, manifest)
    assert diff == {"changed": [], "removed": []}


def test_build_script_uses_onedir_and_packager():
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "--onedir" in text
    assert "scripts\\package_portable.py" in text

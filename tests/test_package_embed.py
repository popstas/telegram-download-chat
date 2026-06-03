"""Tests for the two-part Windows build packager (Variant A).

``scripts/package_embed.py`` is the cross-platform half of the embeddable-Python
distribution: it builds the tiny ``app-<version>.zip`` (our source only) and
applies it onto an installed tree by atomically swapping the ``app/`` directory.
The heavy ``runtime/`` base (embeddable CPython + all deps) is produced by
``build_windows_embed.ps1`` and is out of scope for these unit tests.
"""

import importlib.util
import zipfile
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "package_embed",
    Path(__file__).resolve().parents[1] / "scripts" / "package_embed.py",
)
PKG = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(PKG)


def _make_src_pkg(tmp_path: Path) -> Path:
    """Create a minimal telegram_download_chat source package to bundle."""
    pkg = tmp_path / "src" / "telegram_download_chat"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("__version__ = '0.0.0'\n", encoding="utf-8")
    (pkg / "cli.py").write_text("def main():\n    pass\n", encoding="utf-8")
    sub = pkg / "core"
    sub.mkdir()
    (sub / "__init__.py").write_text("", encoding="utf-8")
    # Stale bytecode that must NOT be bundled.
    cache = pkg / "__pycache__"
    cache.mkdir()
    (cache / "cli.cpython-312.pyc").write_bytes(b"stale")
    return pkg


def test_build_app_zip_contents(tmp_path):
    pkg = _make_src_pkg(tmp_path)
    out = tmp_path / "dist"
    zip_path = PKG.build_app_zip(pkg, out, "1.2.3")

    assert zip_path == out / "app-1.2.3.zip"
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert "telegram_download_chat/__init__.py" in names
        assert "telegram_download_chat/core/__init__.py" in names
        assert "telegram_download_chat/_version.py" in names
        assert "version.txt" in names
        # No bytecode bundled.
        assert not any(n.endswith(".pyc") for n in names)
        assert not any("__pycache__" in n for n in names)
        # Generated marker files carry the version.
        assert zf.read("version.txt").decode().strip() == "1.2.3"
        assert "1.2.3" in zf.read("telegram_download_chat/_version.py").decode()


def test_build_script_uses_embeddable_python_and_packager():
    text = (Path(__file__).resolve().parents[1] / "build_windows_embed.ps1").read_text(
        encoding="utf-8"
    )
    assert "embed" in text.lower()
    assert "--target" in text
    assert "._pth" in text
    assert "package_embed.py" in text
    assert "build-app" in text

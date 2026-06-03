"""Guard the app icon against the "broken icon" regression.

A single 256x256 (PNG-compressed) ICO renders blank/broken in Windows contexts
that need small icons (Start Menu, taskbar, shortcuts). The shipped icon must
carry the standard small sizes so Inno Setup shortcuts and the setup.exe look
correct.
"""

import struct
from pathlib import Path

ICON = Path(__file__).resolve().parents[1] / "assets" / "icon.ico"


def _ico_sizes(path: Path):
    b = path.read_bytes()
    assert b[:4] == b"\x00\x00\x01\x00", "not a valid ICO file"
    count = struct.unpack("<H", b[4:6])[0]
    sizes = set()
    off = 6
    for _ in range(count):
        w = b[off] or 256
        h = b[off + 1] or 256
        sizes.add((w, h))
        off += 16
    return sizes


import importlib.util

_ROOT = Path(__file__).resolve().parents[1]
PKG_ICON = _ROOT / "src" / "telegram_download_chat" / "gui" / "assets" / "icon.ico"


def test_icon_has_standard_small_sizes():
    sizes = _ico_sizes(ICON)
    # Small sizes Windows actually uses for shortcuts/taskbar must be present.
    for required in [(16, 16), (32, 32), (48, 48)]:
        assert required in sizes, f"icon.ico missing {required}; has {sorted(sizes)}"
    # And keep a high-res frame.
    assert (256, 256) in sizes


def test_icon_shipped_inside_package_for_runtime_resolution():
    # gui.main.get_icon_path() searches `<gui>/assets/icon.ico`; the icon must
    # live there so the running app finds it in the embeddable / pip layouts
    # (where the repo-root assets/ dir is not shipped).
    assert PKG_ICON.exists(), f"missing packaged icon: {PKG_ICON}"
    assert _ico_sizes(PKG_ICON) >= {(16, 16), (32, 32), (48, 48), (256, 256)}


def test_app_zip_bundles_the_icon():
    # The two-part embeddable app zip must carry the packaged icon so the GUI
    # has a window/taskbar icon after an in-app update / fresh install.
    spec = importlib.util.spec_from_file_location(
        "package_embed", _ROOT / "scripts" / "package_embed.py"
    )
    pe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pe)
    import tempfile
    import zipfile

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = pe.build_app_zip(
            _ROOT / "src" / "telegram_download_chat", Path(tmp), "9.9.9"
        )
        names = set(zipfile.ZipFile(zip_path).namelist())
    assert "telegram_download_chat/gui/assets/icon.ico" in names

"""Update checker that queries GitHub releases for newer versions.

Modelled after talks-reducer's ``update_checker``: it follows the
``releases/latest`` redirect to learn the published version, compares it to the
running version, and resolves the Windows download URL. Fetching/comparison work
on any platform (useful for the GUI's "Check updates" button), while the
download/install path is Windows-only.
"""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
from typing import Optional, Tuple

GITHUB_OWNER = "popstas"
GITHUB_REPO = "telegram-download-chat"
RELEASES_LATEST_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
# Windows release asset name (see .github/workflows/build.yml).
WINDOWS_ASSET_NAME = "telegram-download-chat.exe"

_USER_AGENT = "telegram-download-chat-update-checker/1.0"
_TAG_RE = re.compile(r"/releases/tag/v?([0-9][0-9A-Za-z.\-]*)")


def is_windows() -> bool:
    """Return True if running on Windows."""
    return sys.platform == "win32"


def get_current_version() -> str:
    """Return the running package version."""
    from telegram_download_chat import __version__

    return __version__


def fetch_latest_version(
    url: str = RELEASES_LATEST_URL,
    timeout: float = 10,
) -> Tuple[Optional[str], Optional[str]]:
    """Fetch the latest released version from GitHub.

    Returns a ``(version, error)`` tuple. On success ``version`` is the parsed
    version string (e.g. ``"0.10.4"``) and ``error`` is ``None``; on failure
    ``version`` is ``None`` and ``error`` holds a human-readable message.
    """
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", _USER_AGENT)

        with urllib.request.urlopen(req, timeout=timeout) as response:
            # The /releases/latest URL redirects to /releases/tag/vX.Y.Z.
            final_url = response.geturl()
            match = _TAG_RE.search(final_url or "")
            if match:
                return match.group(1), None

            # Fallback: parse the version from the HTML body.
            html = response.read().decode("utf-8", errors="ignore")
            match = _TAG_RE.search(html)
            if match:
                return match.group(1), None

            return None, "Could not parse version from GitHub releases page"

    except urllib.error.URLError as exc:
        return None, f"Network error: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return None, f"Error checking for updates: {exc}"


def _version_parts(version: str) -> list[int]:
    """Split a version string into a list of integer components."""
    cleaned = version.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.split("."):
        match = re.match(r"\d+", chunk)
        if match is None:
            raise ValueError(f"Non-numeric version component: {chunk!r}")
        parts.append(int(match.group(0)))
    if not parts:
        raise ValueError(f"Empty version string: {version!r}")
    return parts


def compare_versions(current: str, latest: str) -> bool:
    """Return True when ``latest`` is strictly newer than ``current``."""
    try:
        current_parts = _version_parts(current)
        latest_parts = _version_parts(latest)

        max_len = max(len(current_parts), len(latest_parts))
        current_parts.extend([0] * (max_len - len(current_parts)))
        latest_parts.extend([0] * (max_len - len(latest_parts)))

        for cur, lat in zip(current_parts, latest_parts):
            if lat > cur:
                return True
            if lat < cur:
                return False
        return False
    except (ValueError, AttributeError):
        # Fall back to a lexicographic comparison if parsing fails.
        return str(latest) > str(current)


def get_installer_url(version: str) -> str:
    """Construct the Windows download URL for the given version."""
    tag = version if version.startswith("v") else f"v{version}"
    return (
        f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
        f"/releases/download/{tag}/{WINDOWS_ASSET_NAME}"
    )


def get_releases_page_url() -> str:
    """Return the releases page URL."""
    return RELEASES_PAGE_URL


def check_for_update(
    current_version: Optional[str] = None,
    url: str = RELEASES_LATEST_URL,
    timeout: float = 10,
) -> dict:
    """Check GitHub for a newer release.

    Returns a dict with keys: ``current``, ``latest``, ``update_available``,
    ``download_url`` (Windows installer URL when an update is available, else
    ``None``), and ``error`` (message string or ``None``).
    """
    current = current_version or get_current_version()
    latest, error = fetch_latest_version(url=url, timeout=timeout)
    if error is not None or latest is None:
        return {
            "current": current,
            "latest": None,
            "update_available": False,
            "download_url": None,
            "error": error or "Unknown error",
        }

    update_available = compare_versions(current, latest)
    return {
        "current": current,
        "latest": latest,
        "update_available": update_available,
        "download_url": get_installer_url(latest) if update_available else None,
        "error": None,
    }

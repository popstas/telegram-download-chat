"""Opt-in end-to-end export validation against the live test group (#80).

These tests perform a *clean* download (``--overwrite``) of a private Telegram
group that intentionally contains every export-relevant construct — inline
formatting (bold/italic/underline/strikethrough/code/links), reply threads,
reposts/forwards, and media — then download media (``--media``), render the
result to HTML and PDF, and assert the output reflects that content.

They are **opt-in**: marked ``@pytest.mark.e2e`` and skipped by default. They
require an authenticated Telethon session and real API credentials for an
account that is a member of the private group, so they are *not* part of the
default ``pytest`` run / CI. See ``README.md`` ("Running the e2e suite") for how
to enable them.

Enable with::

    TG_E2E=1 pytest -m e2e

The group can be overridden with ``TG_E2E_GROUP`` (defaults to the documented
test group invite link).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from telegram_download_chat.paths import get_app_dir, get_default_config_path

# The dedicated live validation group (contains all formatting, replies, reposts).
DEFAULT_E2E_GROUP = "https://t.me/+5GOZOYpeK-hlMzUy"

# Process-level timeout for the live download+render so a hung session cannot
# wedge the suite indefinitely.
E2E_TIMEOUT_SECONDS = 600


def _has_real_credentials() -> bool:
    """Return True when the config holds non-placeholder API credentials."""
    config_path = get_default_config_path()
    if not config_path.exists():
        return False
    try:
        import yaml

        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    settings = data.get("settings", {}) or {}
    api_id = str(settings.get("api_id", "")).strip()
    api_hash = str(settings.get("api_hash", "")).strip()
    if not api_id or not api_hash:
        return False
    if api_id in {"YOUR_API_ID"} or api_hash in {"YOUR_API_HASH"}:
        return False
    return True


def _has_session() -> bool:
    """Return True when an authenticated Telethon session file is present."""
    return (get_app_dir() / "session.session").exists()


def _e2e_enabled() -> bool:
    """E2E runs only when explicitly opted-in *and* the prerequisites exist."""
    if not os.environ.get("TG_E2E"):
        return False
    return _has_real_credentials() and _has_session()


def _skip_reason() -> str:
    if not os.environ.get("TG_E2E"):
        return "e2e disabled (set TG_E2E=1 to enable)"
    missing = []
    if not _has_real_credentials():
        missing.append("API credentials in config.yml")
    if not _has_session():
        missing.append("authenticated session.session")
    return "e2e prerequisites missing: " + ", ".join(missing)


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not _e2e_enabled(), reason=_skip_reason()),
]


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    """Clean-download the test group and render HTML + PDF once for the module."""
    group = os.environ.get("TG_E2E_GROUP", DEFAULT_E2E_GROUP)
    out_dir = tmp_path_factory.mktemp("e2e_export")
    json_out = out_dir / "messages.json"

    cmd = [
        sys.executable,
        "-m",
        "telegram_download_chat",
        group,
        "--overwrite",  # clean download — reflect the live group, not a cache
        "--media",  # download media so the export can render it inline
        "--html",
        "--pdf",
        "-o",
        str(json_out),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=E2E_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        pytest.fail(
            "e2e download/render failed "
            f"(exit {result.returncode})\nSTDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    html_path = json_out.with_suffix(".html")
    pdf_path = json_out.with_suffix(".pdf")
    attachments_dir = out_dir / "attachments"
    assert json_out.exists(), "expected messages.json from the download"
    assert html_path.exists(), "expected rendered HTML output"
    assert pdf_path.exists(), "expected rendered PDF output"

    return {
        "json": json_out,
        "html": html_path,
        "pdf": pdf_path,
        "attachments_dir": attachments_dir,
        "html_text": html_path.read_text(encoding="utf-8"),
        "pdf_bytes": pdf_path.read_bytes(),
    }


def test_e2e_html_inline_formatting(exported):
    """The rendered HTML carries inline entity formatting from the group."""
    html = exported["html_text"]
    # The group contains bold/italic/underline/strikethrough/code/links; require
    # that several distinct inline-formatting constructs survived into the HTML.
    inline_tags = ["<b>", "<i>", "<u>", "<s>", "<code>", "<a href="]
    present = [tag for tag in inline_tags if tag in html]
    assert len(present) >= 3, f"too few inline-formatting tags in HTML: {present}"


def test_e2e_html_reply_anchors(exported):
    """Reply citations link to in-export bubble anchors."""
    html = exported["html_text"]
    assert 'id="msg-' in html, "message bubbles should carry id anchors"
    assert 'href="#msg-' in html, "replies should anchor to the parent bubble"


def test_e2e_html_thread_headers(exported):
    """Thread headers are injected when the reply-thread changes."""
    html = exported["html_text"]
    assert 'class="threadsep"' in html, "expected thread header separators"


def test_e2e_html_reposts(exported):
    """Reposted / forwarded messages are surfaced in the export."""
    html = exported["html_text"]
    assert (
        "Forwarded from" in html or 'class="fwd"' in html
    ), "expected forwarded/reposted message markers"


def test_e2e_pdf_rendered(exported):
    """The PDF render is a non-empty, well-formed PDF document."""
    pdf_bytes = exported["pdf_bytes"]
    assert pdf_bytes.startswith(b"%PDF"), "PDF output should start with %PDF"
    assert len(pdf_bytes) > 1024, "PDF output looks suspiciously small"


def test_e2e_media_downloaded_and_rendered(exported):
    """``--media`` downloads attachments and the HTML embeds/references them."""
    attachments_dir = exported["attachments_dir"]
    assert attachments_dir.is_dir(), "expected an attachments/ directory from --media"
    media_files = [p for p in attachments_dir.rglob("*") if p.is_file()]
    assert media_files, "expected at least one downloaded media file"
    # The HTML export should reference the downloaded media via the
    # attachments/ prefix (inline <img>/<video>/<audio> src or a doc link).
    html = exported["html_text"]
    assert (
        "attachments/" in html
    ), "expected the HTML export to reference downloaded media"

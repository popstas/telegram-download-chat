"""Structured progress events shared between the core/CLI and the GUI.

The GUI runs the CLI as a subprocess and reads its combined stdout/stderr.
Rather than scraping human-readable log text, the core emits machine-readable
progress events as single JSON lines prefixed with :data:`PROGRESS_PREFIX`. The
GUI worker parses those lines back into structured Qt signals.

Emission is opt-in so that normal CLI terminal output stays clean:

* if a ``sink`` callable is supplied, the event is handed to it directly (used
  by tests and in-process consumers);
* otherwise, the event is written to stdout only when an explicit ``stream`` is
  given or the :data:`PROGRESS_ENV_VAR` environment variable is set (the GUI
  worker sets it on the subprocess);
* otherwise nothing is emitted.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, Dict, Optional, TextIO

#: Sentinel that prefixes every structured progress line on stdout.
PROGRESS_PREFIX = "@@TDCPROGRESS@@"

#: Environment variable the GUI sets to request structured progress on stdout.
PROGRESS_ENV_VAR = "TDC_STRUCTURED_PROGRESS"


def emit_progress(
    event: Dict[str, Any],
    *,
    sink: Optional[Callable[[Dict[str, Any]], Any]] = None,
    stream: Optional[TextIO] = None,
) -> None:
    """Emit a single structured progress event.

    Args:
        event: A JSON-serializable dict describing the event. By convention it
            carries a ``"type"`` key (e.g. ``"media"`` or ``"messages"``).
        sink: Optional callable invoked with ``event`` instead of writing to a
            stream. Takes precedence over stream/stdout output.
        stream: Optional text stream to write to. When omitted, stdout is used
            only if :data:`PROGRESS_ENV_VAR` is set.

    Progress reporting must never break a download, so all write failures are
    swallowed.
    """
    if sink is not None:
        sink(event)
        return

    if stream is None:
        if not os.environ.get(PROGRESS_ENV_VAR):
            return
        stream = sys.stdout

    try:
        stream.write(PROGRESS_PREFIX + json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()
    except Exception:
        # Never let progress reporting interfere with the actual work.
        pass


def parse_progress_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single stdout line into a progress event dict, or ``None``.

    Returns ``None`` for lines that are not progress events and for malformed
    payloads, so the caller can fall back to treating them as plain log text.
    """
    if not line or not line.startswith(PROGRESS_PREFIX):
        return None
    payload = line[len(PROGRESS_PREFIX) :].strip()
    try:
        event = json.loads(payload)
    except (ValueError, TypeError):
        return None
    return event if isinstance(event, dict) else None

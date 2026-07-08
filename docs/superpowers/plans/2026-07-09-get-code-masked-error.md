# Fix Masked "Get Code" Error (issue #86) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the GUI "Get Code" flow from masking the real error with `'SettingsTab' object has no attribute 'downloader'` when a failure occurs before the downloader is created.

**Architecture:** In `settings_tab.py`, `self.downloader` is only assigned inside the `try` of `_request_code_async`, but the `finally` reads it unconditionally. Initialize the attribute in `__init__` and harden the `finally` cleanup so it never raises, letting the original exception propagate to the user.

**Tech Stack:** Python, PySide6 (Qt), pytest (offscreen Qt).

## Global Constraints

- Use the `.venv` virtual environment for all commands.
- Follow the existing GUI test pattern in `tests/test_gui_update.py` (offscreen Qt fixture, `_make_tab()` patching `_load_settings`).

---

### Task 1: Reproduce the bug with a failing test, then fix it

**Files:**
- Modify: `src/telegram_download_chat/gui/tabs/settings_tab.py` (`__init__` ~line 68-74; `_request_code_async` `finally` block ~line 638-643)
- Test: `tests/test_gui_get_code_error.py` (create)

**Interfaces:**
- Consumes: `SettingsTab()` constructed with `_load_settings` patched out (so `api_id_edit`/`api_hash_edit` are empty); `SettingsTab._request_code_async(phone)` is an async coroutine that raises on validation failure.
- Produces: after the fix, `SettingsTab.__init__` sets `self.downloader = None`; `_request_code_async` propagates the original `ValueError` (not `AttributeError`) when API credentials are missing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gui_get_code_error.py`:

```python
"""Regression test for issue #86.

Clicking "Get Code" without API credentials must surface the real error
("API ID and API Hash are required"), not the AttributeError raised by the
finally block when `self.downloader` was never assigned.
"""

import asyncio
import os

import pytest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    for widget in app.allWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()


def _make_tab():
    from telegram_download_chat.gui.tabs.settings_tab import SettingsTab

    with patch.object(SettingsTab, "_load_settings", lambda self: None):
        return SettingsTab()


def test_missing_credentials_raises_original_error(qapp):
    tab = _make_tab()
    # Ensure credential fields are empty and a phone is present so the
    # failure happens at credential validation, before `self.downloader`
    # would ever be assigned.
    tab.api_id_edit.setText("")
    tab.api_hash_edit.setText("")
    tab.phone_edit.setText("+10000000000")

    with pytest.raises(Exception) as excinfo:
        asyncio.run(tab._request_code_async("+10000000000"))

    message = str(excinfo.value)
    assert "API ID and API Hash are required" in message
    assert "has no attribute 'downloader'" not in message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_gui_get_code_error.py -v`
Expected: FAIL — the raised error is `AttributeError: 'SettingsTab' object has no attribute 'downloader'`, so the `"API ID and API Hash are required"` assertion fails.

- [ ] **Step 3: Initialize `self.downloader` in `__init__`**

In `src/telegram_download_chat/gui/tabs/settings_tab.py`, in `__init__`, add the attribute next to the other instance-state init:

```python
        super().__init__(parent)
        self.config = ConfigManager()
        self.session_manager = SessionManager(self)
        self.telegram_auth = None
        self.downloader = None
        self._setup_ui()
        self._connect_signals()
        self._load_settings()
```

- [ ] **Step 4: Harden the `finally` cleanup in `_request_code_async`**

Replace the existing `finally` block (currently `if self.downloader: try: await self.downloader.close() finally: self.downloader = None`) with:

```python
        finally:
            downloader = getattr(self, "downloader", None)
            if downloader is not None:
                try:
                    await downloader.close()
                finally:
                    self.downloader = None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_gui_get_code_error.py -v`
Expected: PASS — the raised error now carries `"API ID and API Hash are required"` and no `AttributeError`.

- [ ] **Step 6: Run the wider GUI test suite for regressions**

Run: `.venv/bin/pytest tests/test_gui_update.py tests/test_gui_get_code_error.py -v`
Expected: PASS (no regressions in existing SettingsTab tests).

- [ ] **Step 7: Commit**

```bash
git add src/telegram_download_chat/gui/tabs/settings_tab.py tests/test_gui_get_code_error.py
git commit -m "fix(gui): surface real Get Code error instead of missing downloader AttributeError (#86)"
```

---

## Self-Review

- **Spec coverage:** Both spec fixes (init `self.downloader = None`; harden `finally`) are Steps 3 and 4. The spec's testing requirement (empty credentials → original `ValueError`, not `AttributeError`) is Step 1. Out-of-scope items (button enablement, auth-flow audit) are excluded.
- **Placeholder scan:** No TBD/TODO; all code shown in full.
- **Type consistency:** `self.downloader`, `_request_code_async(phone)`, `api_id_edit`/`api_hash_edit`/`phone_edit` all match `settings_tab.py`.

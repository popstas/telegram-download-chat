# Fix masked error in GUI "Get Code" flow (issue #86)

## Problem

When a user clicks **Get Code** in *Settings → Telegram Session* without valid API
credentials, the GUI shows a confusing error:

```
Failed to request verification code: 'SettingsTab' object has no attribute 'downloader'
```

instead of the real cause (e.g. missing API ID / API Hash).

## Root cause

In `src/telegram_download_chat/gui/tabs/settings_tab.py`, `_request_code_async`
assigns `self.downloader` only inside its `try` block:

```python
self.downloader = TelegramChatDownloader()   # line ~588
```

`self.downloader` is **never initialized in `__init__`**. The method's `finally`
block unconditionally reads it:

```python
finally:
    if self.downloader:            # AttributeError if never assigned
        await self.downloader.close()
```

So any exception raised *before* the assignment — most commonly the input
validation `raise ValueError("API ID and API Hash are required")` when
credentials are missing — causes the `finally` to raise
`AttributeError: 'SettingsTab' object has no attribute 'downloader'`, which
replaces (masks) the original, meaningful exception. `code_request_error` then
surfaces the AttributeError to the user.

## Fix

Scope: **fix the masking only** (surface the real error). No changes to button
enablement or the wider auth flow.

Two changes in `settings_tab.py`:

1. Initialize the attribute in `__init__` so it always exists:

   ```python
   self.downloader = None
   ```

2. Harden the `finally` block so it can never raise on cleanup:

   ```python
   finally:
       downloader = getattr(self, "downloader", None)
       if downloader is not None:
           try:
               await downloader.close()
           finally:
               self.downloader = None
   ```

## Result

The `finally` no longer crashes. The original exception propagates, so a user
with missing credentials correctly sees:

```
Failed to request verification code: API ID and API Hash are required
```

## Testing

Add a unit test that invokes `_request_code_async` with empty API ID / API Hash
so it fails validation *before* `self.downloader` is assigned, and asserts the
raised error is the original `ValueError` (message mentions "API ID and API
Hash") — **not** `AttributeError`. This reproduces issue #86 and guards against
regression.

## Out of scope

- Disabling / guarding the "Get Code" button when credentials are absent.
- Broader audit of the `_request_code` / `session_manager` auth path.

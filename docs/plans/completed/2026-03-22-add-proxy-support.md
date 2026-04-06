# Add Proxy Support

## Overview

Add optional HTTP proxy support for Telegram connections. Configured via `proxy_url` in config.yml settings or `--proxy-url` CLI flag. Default is no proxy (direct connection).

## Context

- Files involved: `src/telegram_download_chat/core/auth_utils.py`, `src/telegram_download_chat/core/auth.py`, `src/telegram_download_chat/cli/arguments.py`, `src/telegram_download_chat/cli/commands.py`, `config.example.yml`, `src/telegram_download_chat/paths.py`
- Related patterns: settings are read from config dict in auth.py and passed to TelegramAuth
- Dependencies: `python-socks[asyncio]` (already a Telethon dependency for proxy support)

## Development Approach

- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Add proxy support to TelegramAuth and config

**Files:**
- Modify: `src/telegram_download_chat/core/auth_utils.py`
- Modify: `src/telegram_download_chat/core/auth.py`
- Modify: `src/telegram_download_chat/paths.py`
- Modify: `config.example.yml`

- [x] Add `proxy_url` parameter to `TelegramAuth.__init__()` (default None)
- [x] In `TelegramAuth.initialize()`, parse `proxy_url` (extract scheme, host, port, username, password using `urllib.parse.urlparse`) and pass as `proxy` parameter to `TelegramClient`
- [x] In `auth.py` `AuthMixin.connect()`, read `proxy_url` from `settings` dict and pass it to `TelegramAuth`
- [x] Add `proxy_url` to default config in `paths.py` `get_default_config()` (empty string default)
- [x] Add commented `proxy_url` example to `config.example.yml`
- [x] Write tests for proxy URL parsing and TelegramClient proxy parameter construction
- [x] Run project test suite - must pass before task 2

### Task 2: Add --proxy-url CLI argument

**Files:**
- Modify: `src/telegram_download_chat/cli/arguments.py`
- Modify: `src/telegram_download_chat/cli/commands.py`

- [x] Add `proxy_url` field to `CLIOptions` dataclass (default None)
- [x] Add `--proxy-url` argument to argparse
- [x] Pass `proxy_url` from CLI args to downloader config (override config file value if provided)
- [x] Write tests for CLI argument parsing with --proxy-url
- [x] Run project test suite - must pass before task 3

### Task 3: Verify acceptance criteria

- [x] Manual test: set proxy_url in config.yml and verify connection works through proxy
- [x] Manual test: use --proxy-url CLI flag and verify it overrides config
- [x] Run full test suite: pytest
- [x] Run linter: black src/ tests/ --check && isort src/ tests/ --check

### Task 4: Update documentation

- [x] Update config.example.yml (done in task 1)
- [x] Move this plan to `docs/plans/completed/`

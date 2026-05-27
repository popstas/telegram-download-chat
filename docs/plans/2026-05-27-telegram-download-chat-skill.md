# Telegram-Download-Chat Agent SKILL.md

## Overview

Create `skills/telegram-download-chat/SKILL.md` — a Claude Code **agent operational skill** that teaches an agent how to drive the `telegram-download-chat` CLI on the user's behalf: download/export Telegram chats, convert existing JSON exports, filter by date/user/keyword, download media, and extract subchats.

- **Problem it solves**: the repo has a mature CLI (30+ flags, multiple modes) but no agent-facing skill, so agents can't reliably invoke it.
- **Format**: modeled on the installed ralphex SKILL.md (`~/.claude/plugins/marketplaces/ralphex/assets/claude/skills/ralphex/SKILL.md`) — YAML frontmatter (`description`, `argument-hint`, `allowed-tools`), a bold `SCOPE` line, a numbered Step algorithm, and a `Constraints` section.
- **Source of truth** for all flags: `src/telegram_download_chat/cli/arguments.py` (verified during planning).
- This is a **documentation artifact** — no project source code changes. "Tests" below are **verification steps** (flag cross-check + running harmless real commands), since a SKILL.md has no unit tests.

## Context (from discovery)

- Files/components involved:
  - NEW: `skills/telegram-download-chat/SKILL.md` (top-level `skills/` dir does not yet exist)
  - READ-ONLY references: `src/telegram_download_chat/cli/arguments.py` (argparse), `cli/commands.py`, `cli/__init__.py`, `paths.py`, `config.example.yml`, `CLAUDE.md`, `README.md`
- Format template: ralphex SKILL.md (frontmatter keys, SCOPE line, numbered steps, Constraints).
- TODO source: `docs/TODO.md` line — "add skill to skills/telegram-download-chat/SKILL.md — Describe all cli usage with examples."

## Development Approach

- **Testing approach**: Regular — write the doc, then verify. This is a documentation task; the "tests" are verification steps:
  - cross-check every documented flag against `src/telegram_download_chat/cli/arguments.py`
  - run harmless real commands (`telegram-download-chat --help`, `--show-config`) to confirm documented invocations are real
- Complete each task fully before the next.
- Keep scope minimal (YAGNI): document the CLI; mention GUI/MCP/web only in passing as out-of-scope-for-agent.
- Single file — no backward-compatibility concerns.

## Testing Strategy

- **Verification (in place of unit tests)**: after writing each section, confirm the flags/examples in it match `arguments.py` exactly. Run `--help` once to confirm the live flag set matches the doc.
- **No e2e tests**: project has no UI e2e harness relevant to a doc file. Live download/login is interactive (needs a real terminal) and is NOT part of automated verification.

## Progress Tracking

- Mark completed items with `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix; blockers with ⚠️ prefix.

## What Goes Where

- Implementation Steps (checkboxes): create the file, fill sections, verify against source.
- Post-Completion (no checkboxes): commit, optional `docs/TODO.md` line removal.

## Implementation Steps

### Task 1: Scaffold the skill file with frontmatter and SCOPE
- [x] create `skills/telegram-download-chat/SKILL.md` with YAML frontmatter: `name: telegram-download-chat`; `description` covering download/export/convert/filter/media/subchat with trigger phrases ("download telegram chat", "export telegram", "скачать чат телеграм", "telegram-download-chat"); `argument-hint: 'optional chat id, username, or json export path'`; `allowed-tools: [Bash, Read, AskUserQuestion, Glob]`
- [x] add `# telegram-download-chat` title and a bold **SCOPE** line stating the skill drives the CLI and does not modify project code
- [x] verify frontmatter is valid YAML (`python -c "import yaml,sys; yaml.safe_load(open('skills/telegram-download-chat/SKILL.md').read().split('---')[1])"`)

### Task 2: Write the Step algorithm (Step 0 → Step 5)
- [x] Step 0 — verify CLI available (`which telegram-download-chat`); if missing offer `pipx install telegram-download-chat`, `uvx telegram-download-chat`, or `pip install -e ".[dev,gui]"` from a clone
- [x] Step 1 — verify credentials via `telegram-download-chat --show-config` (api_id/api_hash from https://my.telegram.org); note first live download triggers interactive phone/code login that must run in a real terminal (`! <cmd>`)
- [x] Step 2 — mode detection from the target: username/@/phone/numeric/`-100…` → live download; `*.json` path → convert existing export (no Telegram); `folder:Name` → all chats in folder; none/`gui` → GUI (out of scope, mention only)
- [x] Step 3/4/5 — build command from intent, run (foreground for short; suggest `! `/background for long live downloads), report output paths (prefer `--results-json` to parse results)
- [x] verify each documented invocation form is real by running `telegram-download-chat --help`

### Task 3: Write the full CLI flag reference
- [x] document positional `CHAT` (username/@user/phone/numeric/`-100…`/`.json` path/`folder:Name`/comma-separated list)
- [x] document all flags grouped: Output (`-o/--output`, `--split {month,year,topics}`, `--overwrite`, `--results-json`); Limits/range (`-l/--limit`, `--since-id`, `--max-date/--from`, `--min-date/--until`, `--last-days`); Filtering (`--user`, `--keywords`, `--subchat`, `--subchat-name`); Sort (`--sort {asc,desc}`); Media (`--media`, `--no-fast-download`, `--media-placeholders`); Export (`--html`, `--html-media-links`, `--pdf`); Config/debug (`-c/--config`, `--show-config`, `--debug`, `--preset`, `--proxy-url`); Info (`-v/--version`, `-h`)
- [x] cross-check the reference line-by-line against `src/telegram_download_chat/cli/arguments.py` — every flag, choice list, and default must match (this is the doc's "test")

### Task 4: Write Scenarios and Constraints
- [x] add worked Scenarios (runnable command + one-line "when"): basic download; limited count + custom output; date range/`--last-days`; split by month + media; keyword search + `--results-json`; JSON→TXT conversion with `--user`/`--sort`; subchat extraction from JSON; folder download; HTML/PDF export; proxy + preset
- [x] add Constraints / When-to-stop-and-ask: confirm before large/long downloads; never invent api_id/api_hash; live login needs a real terminal; respect user-set `--proxy-url`; don't modify project code
- [x] final verification: re-read the whole file; confirm `skills/` path matches the TODO verbatim; run `telegram-download-chat --show-config` to confirm that example works

### Task 5: [Final] Sync docs
- [x] remove the completed line from `docs/TODO.md` (or note it done)
- [x] confirm no other docs reference a skills/ path that needs updating

## Technical Details

- Frontmatter keys mirror ralphex: `description`, `argument-hint`, `allowed-tools` (plus `name`).
- Config locations (per `paths.py`): Windows `%APPDATA%\telegram-download-chat\config.yml`; macOS `~/Library/Application Support/telegram-download-chat/config.yml`; Linux `~/.local/share/telegram-download-chat/config.yml`.
- `--show-config` prints location + contents and exits; safe to run without credentials.
- `--results-json` emits a structured summary (chat_id, title, type, counts, from/to, result_json/txt/html/pdf/attachments paths, keywords) — the preferred machine-readable output for an agent.

## Post-Completion

*Items requiring manual intervention or external systems — informational only*

**Commit** (manual): `docs(skill): add telegram-download-chat agent skill` (normal code-commit prefix; `task:` prefix is reserved for `docs/TODO.md` edits — that edit can be a separate `task:` commit).

**Manual verification** (optional, needs credentials + terminal):
- Run an actual small live download (e.g. `telegram-download-chat @somechannel -l 5`) following a documented scenario to confirm end-to-end behavior matches the doc. Requires interactive Telegram login, so not part of automated checks.

**Execution note**: ralphex CLI is installed at `/home/popstas/go/bin/ralphex` (not in PATH). To run this plan autonomously: `~/go/bin/ralphex docs/plans/2026-05-27-telegram-download-chat-skill.md`, or add `~/go/bin` to PATH first.

# Telegram Download Chat backlog: comments polish, citations, reactions, GUI & packaging

## Overview

This plan works through the open backlog in `docs/TODO.md` for the Telegram Download Chat utility, plus a few issues found while using the new `--comments` flag. It covers: an `./data` directory convention for e2e output, fetching cited messages that fall outside the requested date window, three refinements to the recently shipped channel-comments feature (suppress the parent-post citation in comments, download/render comment media, and make comment fetching resumable across restarts), collecting and rendering message reactions, two GUI touch-ups (version in the title, more visual progress bars), a minimal portable Windows installer, and documenting CLI flags that exist in `--help` but are missing from the README.

The tasks are largely independent and are sequenced so the `./data` output convention lands first — all subsequent e2e verification writes there.

## Context

- Adopted from `docs/TODO.md` (generic task-list, 8 open items), plus two issues found while using the `--comments` flag (comment media not downloaded/rendered; restart re-scans all posts).
- Core engine lives in the `core/` package (`comments`, `media`, `messages`, `render`, `download`, `progress`, etc.) built on Telethon; CLI in `cli/`, GUI in `gui/` (PySide6).
- Channel comments shipped recently: comments are merged into the same `messages.json`, each normalized with `comment_of=<post_id>` and `reply_to_msg_id`/`reply_to.reply_to_msg_id` pointed at the parent channel post; the native discussion id is preserved as `discussion_msg_id`. Tasks 3 and 4 refine this path.
- Export formats: JSON (full metadata), TXT (human-readable), optional HTML (Jinja2, Telegram Web-style) and PDF (ReportLab). Reaction rendering (Task 6) targets the HTML renderer.
- E2E verification target for this work: channel `@seeallochnaya` (channel-with-comments). Method: live CLI run with `--comments --media --html`, then inspect `messages.json` and rendered HTML. Results copied to `./data` (per Task 1).

## Development Approach

- Testing approach: regular (write/extend unit tests per task; live-CLI e2e for the data-shape tasks).
- Complete each task fully before moving to the next.
- Use `.venv` for the Python environment.
- Update this plan when scope changes during implementation.

## Testing Strategy

- Unit tests required for every code-changing Task (`pytest`).
- Run `pytest` after each Task before proceeding; format with `black` and `isort`.
- For comments/citations/media/reactions tasks, additionally verify via a live CLI run against `@seeallochnaya` and inspect the output, copying results to `./data`.

## Technical Details

- **Reactions (Task 6)**: inspect Telethon's `message.reactions` (`MessageReactions`) — `results` is a list of `ReactionCount`, each with a `reaction` that is either `ReactionEmoji` (standard `.emoticon`) or `ReactionCustomEmoji` (`.document_id`) plus a `count`; `recent_reactions` (when present) carries who reacted. Define a stable normalized shape stored in each message's JSON, e.g. a `reactions` list of `{emoji|custom_emoji_id, count, chosen?, recent?: [peer ids]}`. Render reaction pills (emoji + count) under each message in HTML, mirroring the Telegram client UI.
- **Cited-outside-window (Task 2)**: a downloaded message may `reply_to` a message id whose date is outside the requested `--min-date`/`--max-date` window, leaving the citation empty. Fetch the referenced message by id (e.g. `client.get_messages(entity, ids=[...])`) and merge it so the citation is populated; dedup against existing ids.
- **Comment-post citation (Task 3)**: comment records carry `comment_of`; the render path nests them under the parent post. Suppress rendering the parent channel-post as a *quoted citation* inside each comment (only for channel comments), since the nesting already conveys the relationship.
- **Comment media (Task 4)**: observed with `--comments` — comment media *references* appear in the JSON and TXT output, but under `--media` the attachments are **not downloaded**, and the references are **not rendered in HTML**. Expected: comment messages participate in media download and HTML media rendering the same way regular/post messages do.
- **Comments resume (Task 5)**: observed with `--comments` — restarting an interrupted job **re-scans every post** for comments rather than resuming. Comment records carry `comment_of` and live in a separate id space, so they are excluded from the post-based resume cursor; the fix is to checkpoint which posts have already had their comments fetched so a restart skips them.
- **README flags (Task 10)**: `--split {month,year,topics}`, `--no-fast-download`, `--html`, `--html-media-links`, and `--pdf` are present in `--help` but undocumented in the README; document them.

## Implementation Steps

### Task 1: Add ./data e2e output directory convention

- [x] Create a `./data` directory at the repo root (e.g. add a tracked `.gitkeep` so the dir exists)
- [x] Add `/data/` to `.gitignore` so e2e output is not committed
- [x] Update `CLAUDE.md` so the e2e workflow saves results to `./data` instead of `~/tmp/e2e-tdc`
- [x] run project tests - must pass before next task

### Task 2: Fetch cited/replied messages outside the date window

- [x] When a downloaded message references a `reply_to` message id outside the requested date window, fetch the referenced message by id
- [x] Merge fetched referenced messages into the message list and dedup so citations are populated in JSON/TXT/HTML
- [x] write tests for the outside-window citation fetch and dedup behavior
- [x] run project tests - must pass before next task
- [x] e2e: live CLI run against `@seeallochnaya` confirming a previously-empty citation is now populated; copy results to `./data` (skipped - requires live authenticated Telethon session, not automatable here)

### Task 3: Suppress channel-post citation inside comment messages

- [ ] In the render path, do not render the parent channel post as a quoted citation inside comment messages (those carrying `comment_of`); apply only to channel comments
- [ ] write tests verifying a comment nests under its post without a redundant post citation, while non-comment citations are unaffected
- [ ] run project tests - must pass before next task

### Task 4: Download and render media for comment messages

- [ ] Under `--media`, download attachments for comment messages (currently comment media references appear in JSON/TXT but the attachments are not downloaded)
- [ ] Render comment media references inline in HTML output (currently missing from HTML even though present in JSON/TXT)
- [ ] write tests for comment media download and HTML render
- [ ] run project tests - must pass before next task
- [ ] e2e: live CLI run against `@seeallochnaya` with `--comments --media --html`, confirm comment attachments download and references render in HTML; copy results to `./data`

### Task 5: Make comment fetching resumable across restarts

- [ ] Checkpoint which posts have already had their comments fetched so restarting an interrupted `--comments` job does not re-scan every post
- [ ] Ensure the resume logic coexists with the existing post-based resume cursor and comment dedup (`comment_of`-keyed)
- [ ] write tests verifying a restarted run skips posts whose comments were already fetched
- [ ] run project tests - must pass before next task
- [ ] e2e: interrupt and restart a `--comments` run against `@seeallochnaya`, confirm previously-scanned posts are skipped; copy results to `./data`

### Task 6: Collect and render message reactions

- [ ] Inspect Telethon's reactions structures and define a stable normalized reactions shape to store in the saved JSON
- [ ] Capture reactions (standard emoji + custom-emoji + counts, and who reacted where available) for posts, comments, and regular chat messages
- [ ] Render reaction pills (emoji + count) under each message in HTML, reproducing the Telegram client UI
- [ ] write tests for reactions normalization and HTML pill rendering
- [ ] run project tests - must pass before next task
- [ ] e2e: live CLI run against a channel/post with reactions, verify reactions in JSON and pills in HTML; copy results to `./data`

### Task 7: Add application version to the GUI window title

- [ ] Add the application version number to the GUI window title
- [ ] write tests asserting the window title includes the version
- [ ] run project tests - must pass before next task

### Task 8: More visual GUI progress bars

- [ ] Change the GUI progress bar color from red to green and/or draw a progress line for clearer progress indication
- [ ] write tests/manual-check notes for the progress bar styling change where testable
- [ ] run project tests - must pass before next task

### Task 9: Minimal Windows installer (portable-only)

- [ ] Add a minimal Windows installer producing the portable distribution
- [ ] Support incremental updates if feasible (so only changed app files update, not the bundled Python runtime); document the limitation if not feasible now
- [ ] run project tests - must pass before next task

### Task 10: Document missing CLI flags in README

- [ ] Document the flags present in `--help` but missing from the README: `--split {month,year,topics}`, `--no-fast-download`, `--html`, `--html-media-links`, `--pdf`
- [ ] run project tests - must pass before next task

### Task 11: Verify acceptance criteria

- [ ] Run a full live CLI e2e against `@seeallochnaya` with `--comments --media --html`; inspect `messages.json` + HTML for populated citations, comment media, suppressed post-citation in comments, and reaction pills; copy results to `./data`
- [ ] verify all requirements from Overview are implemented
- [ ] run full project test suite (`pytest`)
- [ ] run project linters (`black`, `isort`, `mypy`) - all issues must be fixed

## Post-Completion

*Items requiring manual intervention - no checkboxes, informational only*

- The Windows installer (Task 9) must be built and smoke-tested on a real Windows environment via the project's `build_windows.ps1` flow.
- Live e2e requires an authenticated Telethon session and access to `@seeallochnaya`.

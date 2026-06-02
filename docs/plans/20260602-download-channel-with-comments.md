# Download a Channel Together With Its Comments

## Overview

Add the ability to download a broadcast channel together with the comment threads its posts accumulate. A broadcast channel's comments live in a linked discussion supergroup. When the new opt-in `--comments` flag is set, the tool resolves that linked group and downloads the per-post comment threads alongside the channel posts, merging everything into the same `messages.json` so existing TXT/HTML exports render comments nested under their posts. Default behavior for channel downloads is unchanged.

An optional `--comments-limit N` caps how many comments are fetched per post (default: unlimited). The GUI exposes this as a dropdown with presets: No limit (default), 10, 50, 100, 500, 1000. This keeps runs bounded on high-traffic posts.

Date windowing already works via the existing `--last-days` / `--min-date` / `--max-date` flags (`cli/commands.py`); since comments are fetched only for the posts that were actually downloaded, limiting posts to a date window (e.g. `--last-days 7`) automatically limits comment fetching to that same window. No new date-limit code is required — the e2e run uses `--last-days 7` against `@seeallochnaya` to keep it fast and to exercise the date+comments interaction.

## Context

- Impacted components: `core/comments.py` (new), `core/download.py` / downloader flow, `cli/commands.py` (`process_chat_download`), `cli/arguments.py` (`CLIOptions`), `gui/tabs/download_tab.py`, `gui/worker.py`, `core/progress.py`.
- Comments are merged into the existing combined `messages.json`. Each comment is normalized to point at its parent channel-post id (`reply_to.reply_to_msg_id` and top-level `reply_to_msg_id` set to the post id, `comment_of=<post_id>` marker, native discussion id preserved as `discussion_msg_id`) so the existing reply-thread + anchor logic nests them with zero export changes.
- Fetch strategy is approach A: per-post `client.iter_messages(channel_entity, reply_to=post_id)`. Telethon resolves the linked discussion group and id-mapping internally; supplying the post id makes parent linkage exact.
- Existing patterns to mirror: `core/topics.py` (focused fetch-then-annotate module), `core/download.py` `FloodWaitError` sleep-retry and `_stop_requested` handling, the `--media` checkbox wiring in `gui/tabs/download_tab.py`, and the `media` structured progress event in `core/progress.py` / `gui/worker.py`.
- The flag is channel-only: a no-op with an info log on non-broadcast entities and when a channel has no linked discussion group (posts are still saved).
- Adopted from `docs/TODO.md` (generic task-list).

## Development Approach

- Testing approach: regular
- Complete each task fully before moving to the next
- Update this plan when scope changes during implementation

## Testing Strategy

- Unit tests required for every code-changing Task
- Run project tests after each Task before proceeding
- Final acceptance includes a live end-to-end run against a real channel-with-comments

## Progress Tracking

- Mark completed items with `[x]` immediately when done
- Update plan if implementation deviates from original scope

## Technical Details

- `get_linked_discussion(downloader, entity)`: run `GetFullChannelRequest`, return `linked_chat_id` or `None`.
- `download_post_comments(downloader, channel_entity, post_ids, *, silent, stop_check, limit=None) -> list[dict]`: for each post id, page `client.iter_messages(channel_entity, reply_to=post_id)`; stamp each comment with parent-id normalization (`reply_to.reply_to_msg_id` + top-level `reply_to_msg_id` = channel post id, `comment_of=<post_id>`, native id preserved as `discussion_msg_id`). When `limit` is a positive int, stop after collecting `limit` comments for that post before moving to the next; `limit=None`/`0` means unlimited. Handle `MsgIdInvalidError` / comments-disabled per post (skip that post, continue). Handle `FloodWaitError` with sleep-retry mirroring `download_chat`. Respect `_stop_requested` between posts.
- Download-flow wiring: in `process_chat_download`, when `args.comments` is set and the resolved entity is a `broadcast` channel with a linked group, fetch comments (passing `limit=args.comments_limit`) for the downloaded post ids and append them to the message list before save/dedup/render. No linked group → info log, skip, posts still saved.
- CLI: `--comments` flag plus `comments: bool = False` in `CLIOptions`; `--comments-limit N` (int, default `None` = unlimited) plus `comments_limit: Optional[int] = None` in `CLIOptions`; help text notes channel-only and that `--comments-limit` requires `--comments`.
- GUI: a "Download comments" `QCheckBox` modeled on `media_chk`, plus a "Comments per post" `QComboBox` next to it with presets No limit (default) / 10 / 50 / 100 / 500 / 1000. Checkbox + combo: definition, settings load, settings collect, command build (`--comments`, and `--comments-limit N` only when a numeric preset is selected), and save/restore. The combo is enabled only when the checkbox is checked. The worker appends both args to the subprocess command accordingly.
- Progress: emit a structured `type: "comments"` event per post (posts done/total, comments so far) via `core/progress.py`; the GUI worker surfaces it parallel to the existing `media` event handling.

## Implementation Steps

### Task 1: Add core/comments.py — linked group resolution and per-post comment fetch

- [x] Create `core/comments.py` with `get_linked_discussion(downloader, entity)` running `GetFullChannelRequest` and returning `linked_chat_id` (or `None`)
- [x] Add `download_post_comments(downloader, channel_entity, post_ids, *, silent, stop_check, limit=None) -> list[dict]` paging `client.iter_messages(channel_entity, reply_to=post_id)` per post
- [x] Enforce the per-post `limit`: when `limit` is a positive int, stop collecting after `limit` comments for that post; `None`/`0` means unlimited
- [x] Normalize each fetched comment: set `reply_to.reply_to_msg_id` and top-level `reply_to_msg_id` to the channel post id, add `comment_of=<post_id>`, preserve the native discussion id as `discussion_msg_id`
- [x] Handle `MsgIdInvalidError` / comments-disabled per post (skip and continue) and `FloodWaitError` (sleep-retry mirroring `download_chat`); respect `_stop_requested` between posts
- [x] write tests: parent-id normalization (comment under post P has `reply_to_msg_id == P`, `comment_of == P`, native id preserved as `discussion_msg_id`); per-post `limit` caps the count (e.g. limit=10 → at most 10 comments/post) while `None`/`0` returns all; no-linked-group path returns cleanly; comments-disabled post is skipped
- [x] run project tests - must pass before next task

### Task 2: Wire --comments into the download flow and CLI

- [ ] Add `--comments` to `cli/arguments.py` and `comments: bool = False` to `CLIOptions`; help text notes channel-only
- [ ] Add `--comments-limit N` (int, default `None`) to `cli/arguments.py` and `comments_limit: Optional[int] = None` to `CLIOptions`; help text notes it requires `--comments` and that omitting it means unlimited
- [ ] In `process_chat_download` (`cli/commands.py`), when `args.comments` and the resolved entity is a `broadcast` channel with a linked group, fetch comments (passing `limit=args.comments_limit`) for the downloaded post ids and append them to the message list before save/dedup/render
- [ ] On non-broadcast entities or channels with no linked group, log an info message and skip comments while still saving posts
- [ ] write tests: integration — the combined list (posts + normalized comments) threads correctly through the existing TXT/HTML ordering so each comment nests under its post; `--comments-limit` is forwarded into `download_post_comments` and caps per-post comments; no-linked-group path saves posts only
- [ ] run project tests - must pass before next task

### Task 3: Add GUI checkbox and structured comments progress

- [ ] Add a "Download comments" `QCheckBox` in `gui/tabs/download_tab.py` modeled on `media_chk` — checkbox definition, settings load, settings collect, `cmd_args.append("--comments")`, and save/restore
- [ ] Add a "Comments per post" `QComboBox` next to the checkbox with presets No limit (default) / 10 / 50 / 100 / 500 / 1000; enable it only when the checkbox is checked; append `--comments-limit N` to the command only when a numeric preset is selected; include it in settings load/collect/save/restore
- [ ] Emit a structured `type: "comments"` progress event per post (posts done/total, comments so far) via `core/progress.py`
- [ ] Surface the `comments` progress event in `gui/worker.py` parallel to the existing `media` event handling
- [ ] write tests: parsing/handling of the `comments` progress event; GUI command-build includes `--comments` when checked and `--comments-limit N` only when a numeric preset is selected (and neither when "No limit")
- [ ] run project tests - must pass before next task

### Task 4: Verify acceptance criteria

- [ ] verify all requirements from Overview are implemented (opt-in flag, per-post `--comments-limit`, channel-only, combined output, nested rendering, default behavior unchanged)
- [ ] run e2e against a real channel-with-comments limited to the last 7 days: `python -m telegram_download_chat https://t.me/seeallochnaya --comments --comments-limit 50 --last-days 7 --html`; verify only posts within the 7-day window are downloaded, each post has at most 50 comments, comments appear nested under posts in `messages.json` and the rendered HTML; copy results to `~/tmp/e2e-tdc`
- [ ] run full project test suite
- [ ] run project linter (`black`, `isort`) - all issues must be fixed

## Post-Completion

*Items requiring manual intervention - no checkboxes, informational only*

- The e2e step requires an authenticated Telethon session with access to the test channel `@seeallochnaya`.

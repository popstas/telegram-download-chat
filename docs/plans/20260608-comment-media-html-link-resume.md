# Channel comments: fix media HTML link on resume + single-pass discussion download (issue #80)

## Overview
Two related improvements to `--comments`, driven by issue #80 (ksandigo) and verified live against the `ecceverbum` channel.

**Part A — comment media HTML link missing on resume (the reported bug).**
- **Symptom**: with `--comments --media --html --html-media-links`, a comment's media (e.g. a PDF on comment 9240 / post 5477) downloads to disk, but the HTML shows **no media link**. The same file rendered from the discussion supergroup directly works.
- **Root cause** (empirically confirmed): the render path is correct and a *fresh* run renders comment media fine. On a **resume** run, `_dedup_messages` (`cli/commands.py:60-79`) merges `existing_messages` (from `messages.json`) *first* (`commands.py:583`) and fresh `comments` *second* (`commands.py:606`); on a `(comment_of, id)` collision it keeps the first (stale) copy — the only replace branch fires for citation markers. So a comment saved without `attachment_path` (pre-v0.13 export, or a run where that file's media download failed) can **never** gain its link on resume, even though the media re-downloads every run.
- **Verified**: feeding the real `Ecce_Verbum/messages.json` with comment `attachment_path` stripped through the real merge path reproduces `attachment_path → None`; the planned `_has_attachment` replace rule recovers both PDFs with no duplicate records.
- **Fix**: let a freshly-fetched comment carrying `attachment_path` replace a same-key stale comment that lacks it (mirroring the citation-replace precedent). View-only render code is unchanged.

**Part B — single-pass discussion download instead of per-post scanning (the perf complaint).**
- **Symptom**: a `--comments` run issues **one `iter_messages(channel, reply_to=post_id)` request per post** (`comments.py:229-247`), even for posts with no comments. Live run: **173 posts, only 20 had comments → 153 wasted round-trips**; at full scale (3733 posts) ≈ the reporter's ~60 minutes.
- **Approach**: download the linked discussion supergroup **once** (paginated by id/date, bounded by the in-window posts' date floor), then map each discussion message to its parent channel post via the auto-forwarded thread root, instead of one request per post. Turns ~3700 requests into a few dozen.

**Benefit**: resume runs finally surface comment media (Part A), and the whole comment fetch drops from ~60 min to minutes (Part B). Part A is small and independently shippable; Part B is a larger, riskier rewrite and is sequenced after A.

## Context (from discovery + live verification)
- Live check performed: `ecceverbum --media --html --html-media-links --media-placeholders --comments --limit 150` (account `popstas`). Export saved to `~/www/telegram-download-chat.pc-virt.popstas.pro/chats/Ecce_Verbum/`. Fresh run renders comment PDFs (9240/post 5477, 9131/post 5445) as `media-file` links; bug confirmed resume-only; fix validated on the real data.
- Files/components involved:
  - **Part A**: `src/telegram_download_chat/cli/commands.py` — `_dedup_messages` (lines 35-79); merge order at lines 583, 606. Single small production change.
  - **Part B**: `src/telegram_download_chat/core/comments.py` — `download_post_comments` (lines 156-323, per-post loop), `_normalize_comment` (117-149), `_download_comment_media` (326-363), checkpoint helpers (28-83); `src/telegram_download_chat/cli/commands.py` — `fetch_channel_comments` (317-427), `_persist_comments_checkpoint` (430-448); `src/telegram_download_chat/gui/worker.py` — parses the `comments` progress event.
  - Tests: `tests/test_comments_command.py` (dedup + fetch), `tests/test_comments.py`, `tests/test_comment_media.py`, `tests/test_comments_resume.py`, `tests/test_gui_comments.py`.
  - `CLAUDE.md` — "Channel Comments" section documents both the dedup keying and the per-post fetch.
- Telegram discussion-group structure (basis for Part B mapping, to be confirmed in Task B1):
  - The linked discussion id comes from `get_linked_discussion` (`comments.py:86`) → here `1619992925`.
  - Each channel post is auto-forwarded into the discussion group as a **thread root** message carrying `fwd_from.channel_post` = the original channel post id.
  - A comment replies within that thread: `reply_to.reply_to_top_id` (nested replies) or `reply_to.reply_to_msg_id` (direct replies to the post) points at the thread root's discussion id.
  - Mapping: `root_discussion_id → channel_post_id` (from forwarded roots); then `comment.post_id = root_to_post[top_or_reply_id]`.
- Dependencies identified: none new for Part A. Part B reuses `downloader.get_entity`, the existing message-iteration/partial-file machinery, `_normalize_comment`, and `_download_comment_media`. No new packages.

## Development Approach
- **Testing approach**: TDD (tests first) for both parts — write the failing test, watch it fail, then implement.
- Complete each task fully before the next. **Land Part A (Tasks A1–A3) before starting Part B** — it ships the reported bug independently and de-risks the larger rewrite.
- **CRITICAL: every task with code changes MUST include new/updated tests** (success + error/edge cases), listed as separate checklist items.
- **CRITICAL: all tests must pass before starting the next task.** The existing dedup tests (`test_comments_command.py:171-215`) must keep passing unchanged through Part A.
- Make small, focused changes; run tests after each. Maintain backward compatibility of the export format (comment dicts keep `comment_of`, `discussion_msg_id`, `attachment_path`).

## Testing Strategy
- **Unit tests**: required every task. Part A in `tests/test_comments_command.py`; Part B mapping in `tests/test_comments.py` / `tests/test_comments_command.py` with synthetic discussion-message fixtures (no network).
- **E2E**: opt-in live suite (`TG_E2E=1 pytest -m e2e`) is not required; both behaviors are reproducible at unit level. Live manual verification against `ecceverbum` is listed under Post-Completion.
- Run full `pytest` before declaring done; run `black`/`isort`/`mypy`.

## Progress Tracking
- Mark completed items `[x]` immediately. Add ➕ for newly discovered tasks, ⚠️ for blockers. Keep this plan in sync with actual work.

## What Goes Where
- **Implementation Steps** (`[ ]`): code, tests, docs in this repo.
- **Post-Completion** (no checkboxes): live manual verification by the maintainer.

## Implementation Steps

### Part A — fix comment media HTML link on resume

### Task A1: Failing regression tests for resume dedup dropping `attachment_path`
- [x] In `tests/test_comments_command.py`, add `test_dedup_fresh_comment_attachment_path_replaces_stale()`: stale `{"id": 9240, "comment_of": 5477, "message": "c"}` (no `attachment_path`) then fresh same-key with `attachment_path="documents/9240_x.pdf"`; assert `_dedup_messages([stale, fresh])` yields one record with that `attachment_path`.
- [x] Add `test_dedup_does_not_demote_comment_with_attachment_path()`: order `[with_path, without_path]` keeps the path (order-independence, never demote).
- [x] Add `test_dedup_keeps_first_when_neither_comment_has_attachment_path()`: guards the unchanged no-media collapse behavior.
- [x] Run `pytest tests/test_comments_command.py -k dedup` — bug-demonstrating test FAILS (red); the demote test PASSES (dedup's keep-first already protects the with-path copy at order `[with_path, without_path]`, so it's green from the start) and the keep-first test PASSES, all four pre-existing dedup tests still PASS.

### Task A2: Implement the attachment-aware replace rule in `_dedup_messages`
- [x] Add a `_has_attachment(m)` helper (dict/attr safe, mirroring `_is_citation`) → bool of non-empty `attachment_path`.
- [x] Extend the collision branch (`commands.py:76-78`) with `elif comment_of is not None and not _has_attachment(deduped[seen[key]]) and _has_attachment(m): deduped[seen[key]] = m`. Scope to comment records; only replace when kept lacks a path and the new one has one (never demote, never touch non-comment ids).
- [x] Update the `_dedup_messages` docstring to document the new rule.
- [x] Run `pytest tests/test_comments_command.py -k dedup` — all dedup tests PASS (green).
- [x] Run `pytest tests/test_comment_media.py tests/test_comments_command.py tests/test_comments_resume.py` — PASS (no regression).

### Task A3: Verify Part A acceptance
- [x] Confirm a stale-then-fresh comment list yields a record with `attachment_path` that `render.py` renders as a link (cross-check `test_html_renders_comment_media_inline`). Added `test_resume_dedup_then_render_surfaces_comment_media_link` in `tests/test_comment_media.py`: resume merge order (stale, fresh) → `_dedup_messages` → `render_html` emits the `media-img` link.
- [x] Run full `pytest`; run `black src/ tests/`, `isort src/ tests/`, `mypy src/` and fix any issues from the change. Full suite: 444 passed, 9 skipped. black/isort clean on the changed file; mypy errors are all pre-existing (telethon stubs, unrelated files) — none from this change.
- [x] Confirm the four original dedup tests are unmodified and passing. `test_comments_command.py:171-216` (collide / collapse / citation-replace / citation-keep / real-post-first) unchanged and green.

### Part B — single discussion-group download mapped to posts

### Task B1: Confirm the discussion mapping fields against live data (spike + fixtures)
- [x] Added the one-off spike `scripts/spike_discussion_mapping.py` (not in the suite): connects, resolves the linked discussion id (or takes `--discussion-id 1619992925`), fetches ~50 messages, prints `fwd_from.channel_post` for forwarded roots and `reply_to_top_id`/`reply_to_msg_id` for replies, then reconstructs `root_to_post` + `top_id` mapping and prints `comment <id> -> post <id>`. (The live run itself is a manual maintainer step requiring an authenticated session — Post-Completion; the script is the committed deliverable.)
- [x] Captured representative serialized discussion messages as `tests/fixtures/discussion_messages.json` (documented in `tests/fixtures/discussion_messages.README.md`): two forwarded roots (`fwd_from.channel_post` 5477/5445), two direct replies carrying PDFs (9240→5477, 9131→5445), a nested reply (9241 maps to 5477 via `reply_to_top_id=9230`), and an out-of-window reply (9300, root never seen → dropped). Validated that `root_to_post` + `(reply_to_top_id or reply_to_msg_id)` reconstructs `9240→5477` / `9131→5445`, matching the per-post path.
- [x] ⚠️ Live structure matches the documented assumption (`fwd_from.channel_post` on roots, `reply_to_top_id`/`reply_to_msg_id` on replies); fixtures are derived from it, so no plan mapping-design change is needed. (If the maintainer's live spike run later contradicts this, revisit before B2/B3.)

### Task B2: Add a pure mapping function (discussion messages → normalized comments)
- [x] In `core/comments.py`, add `map_discussion_to_comments(downloader, discussion_messages, post_ids, *, limit, min_reactions)` that: builds `root_to_post` from forwarded roots (`fwd_from.channel_post`), skips root/service messages, maps each comment via `reply_to_top_id or reply_to_msg_id`, keeps only comments whose post is in `post_ids` (in-window), normalizes via `_normalize_comment`, then applies per-post `limit` (group-by-post cap) and `min_reactions`. Returns `(comments, raw_media_messages)`. Added `_attr_or_key` helper so field access works on both live Telethon objects and serialized dict fixtures.
- [x] Comments whose root can't be mapped to an in-window post are skipped with a debug log (documented fallback).
- [x] Write unit tests using the Task B1 fixtures: direct reply maps to its post; nested reply maps via `reply_to_top_id`; a reply to an out-of-window post is dropped (plus an in-window-post-filtered case); `limit` caps per post; `min_reactions` filters (and excludes dropped comments' media); forwarded roots are not emitted as comments.
- [x] Run `pytest tests/test_comments.py -k map_discussion` — PASS (7 passed).

### Task B3: Add the single-pass discussion fetch and wire it into `download_post_comments`
- [ ] In `core/comments.py`, add `fetch_discussion_messages(downloader, linked_id, *, min_date, stop_check)` that resolves the discussion entity (`downloader.get_entity`) and pages it once (reuse existing iteration/partial-file machinery), bounded by `min_date` (the floor of the in-window posts' dates, since a comment is always newer than its post). Handle `FloodWaitError` and stop requests as the current loop does.
- [ ] Rewrite `download_post_comments` to: compute `min_date` from the posts, call `fetch_discussion_messages`, then `map_discussion_to_comments`, then `_download_comment_media` (unchanged) on the collected raw media. Preserve the function's return contract (flat list of normalized comment dicts) and the `comments` progress event (emit per-batch scanned instead of per-post).
- [ ] Update `fetch_channel_comments` (`commands.py:415-424`) for the new call shape; pass `post_ids` and the date floor.
- [ ] Write tests with a fake `downloader` whose discussion iteration yields the Task B1 fixtures; assert the same comments + `attachment_path` result as the old per-post path for an equivalent input.
- [ ] Run `pytest tests/test_comments.py tests/test_comments_command.py tests/test_comment_media.py` — PASS.

### Task B4: Retire the per-post checkpoint; rely on discussion resume + dedup
- [ ] Remove (or repurpose) the per-post `*.comments-progress.json` checkpoint path now that a single discussion download resumes via the standard partial-file mechanism and `(comment_of, id)` dedup keeps re-mapping correct: drop `on_post_done`/`load`/`save`/`clear_comments_checkpoint` usage from `fetch_channel_comments` and `_persist_comments_checkpoint`, or keep the helpers but stop calling them. Decide duplication-vs-removal with the maintainer if the helpers are referenced elsewhere.
- [ ] Update `tests/test_comments_resume.py` to assert the new resume behavior (resume re-maps from the resumed discussion download and dedup avoids duplicates; no per-post checkpoint file is required for correctness).
- [ ] Run `pytest tests/test_comments_resume.py tests/test_gui_comments.py` — PASS.

### Task B5: Verify acceptance criteria (both parts)
- [ ] Confirm Part A: resume over a stale JSON yields comment records with `attachment_path` (regression tests green).
- [ ] Confirm Part B: with synthetic fixtures the mapping reproduces the per-post path's comments and `comment_of` values; no extra requests per empty post in the new path.
- [ ] Run full `pytest`; run `black src/ tests/`, `isort src/ tests/`, `mypy src/` — all clean.
- [ ] Verify test coverage of the new `core/comments.py` functions meets the project standard.

### Task B6: [Final] Update documentation
- [ ] Update the "Channel Comments" section of `CLAUDE.md`: (1) Part A — a re-fetched comment carrying `attachment_path` replaces a same-key stale comment lacking one, so resume runs render comment media; (2) Part B — comments are now fetched via a single date-bounded download of the linked discussion group, mapped to posts by thread root (`fwd_from.channel_post` + `reply_to_top_id`), replacing the per-post `iter_messages(reply_to=post_id)` scan and its per-post checkpoint.

*Note: ralphex automatically moves completed plans to `docs/plans/completed/`.*

## Technical Details
- **Part A replace semantics**: wholesale dict replacement (same as citation-replace). Fires only for `comment_of is not None`, only when kept lacks `attachment_path` and the new one has it; never demotes; two comments that both have a path keep the first (out of scope). Merge order is unchanged (`commands.py:583`, `606`).
- **Part B mapping**: `root_to_post[discussion_id] = fwd_from.channel_post` for forwarded roots; `comment.post_id = root_to_post.get(reply_to_top_id or reply_to_msg_id)`. Date floor bounds the discussion download because a comment's date ≥ its post's date. `--comments-limit` is applied per mapped post (group-then-cap) to preserve current semantics; `--comments-min-reactions` per comment as today. Media reuses `_download_comment_media` (keyed by `discussion_msg_id == raw msg id`).
- **Guardrails**: comments mapping to out-of-window posts are skipped (matches today's in-window-only coverage). If Task B1 reveals the channel doesn't expose `fwd_from.channel_post` on roots, fall back to keeping the per-post path behind a flag and re-scope with the maintainer (recorded as a ⚠️ in the plan).

## Post-Completion
*Manual verification by the maintainer — informational, no checkboxes.*

**Live verification against `ecceverbum`**:
- Part A: re-run the issue command as a **resume** over an export whose `messages.json` has comments saved without `attachment_path`; confirm post 5477 / comment 9240's PDF now renders a link in `messages.html` without `--overwrite`. Spot-check comment image/video/audio links too.
- Part B: re-run on the full channel and confirm the comment fetch completes in minutes (not ~60), with the same comments mapped to the same posts as before; confirm the linked discussion id used is `1619992925`.

**Out of scope (separate issue scope)**:
- Issue #80's broader title ("Formatting and Replies in HTML" — bold/italics/hyperlinks, threaded sub-comments) is a distinct feature, not covered here.

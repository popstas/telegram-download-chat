# Fix media download: recover expired file references, silence task-exception spam & wrong-session noise

## Overview

A `--media --html` run over a heavily-throttled channel ran for ~2 hours and surfaced three failure modes. This plan fixes all three:

1. **`FileReferenceExpiredError` on standard (non-self-destructing) media.** Telegram file references embedded in `Message` objects are short-lived. Because Telegram throttled the parallel download so hard, the run took ~2h and references for most files expired *before* download. There is **no recovery**: the fast path catches the error and falls back to `client.download_media(message, ...)` (`media.py:372`), which carries the *same stale reference* and re-raises. Result: only 7 of 74 files downloaded; the rest logged `Failed to download media for message …`. Fix: refetch the message by id for a fresh reference and retry once via the standard downloader.

2. **`Task exception was never retrieved` traceback spam.** In `fast_download.py` `ParallelTransferrer.download()` (lines 337–347), each loop iteration spawns one `sender.next()` task per connection but awaits them sequentially. When `await task` raises (e.g. `FileReferenceExpiredError`, `FastDownloadStalled`) or the loop `break`s on a short chunk, sibling tasks are never awaited; their exceptions later surface as asyncio "Task exception was never retrieved" dumps. Fix: drain (cancel + gather) siblings on every loop exit.

3. **Hundreds of `Security error … Server replied with a wrong session ID` lines.** Telethon-internal noise from the cross-DC parallel senders being throttled. The existing log filters don't cover this message. Fix: extend the filter to rewrite/suppress it.

**Benefits:** previously-failing files actually download; the log stays readable under throttling. Backward compatible — no behavior change when `_current_entity` is unset (archive-only flows).

## Context (from discovery)

- Files/components involved:
  - `src/telegram_download_chat/core/download.py` — `download_chat()` resolves entity at ~line 35 (`entity = await self.get_entity(chat_id)`); entity is a local var, not stored.
  - `src/telegram_download_chat/core/media.py` — `MediaMixin`: `download_message_media()` (256–314, catch-all logs failures), `_download_binary_media()` (316–373; fast path 331–368 catches all and falls through; standard path at line 372), `download_all_media()` (476–570).
  - `src/telegram_download_chat/core/fast_download.py` — `ParallelTransferrer.download()` (314–349; task loop 337–347), `_install_log_filter()`/`_remove_log_filter()` (193–208), existing `_ReconnectAttrErrorFilter`/`_ServerClosedRewriteFilter` (71–119).
  - `tests/test_fast_download_cancellation.py` — existing patterns: `_make_throttle_downloader` builds a minimal `MediaMixin` via `__new__`; filter tests use `logger.makeRecord`.
- Related patterns found: log-filter classes installed per-`download()` lifetime; mixin instances built with `MediaMixin.__new__` + MagicMock logger in tests.
- Dependencies: Telethon (`telethon.errors.FileReferenceExpiredError`, `client.get_messages(entity, ids=<int>)` returns a single `Message` with fresh `file_reference`).
- Decisions confirmed with user: fix all three; after refetch retry via standard single-stream downloader only; regular (code-then-tests) approach.

## Development Approach
- **Testing approach**: Regular (code first, then tests).
- Complete each task fully before moving to the next; small focused changes.
- Every task includes new/updated unit tests with mocked Telethon client/exceptions (success + error cases).
- All tests must pass (`pytest`, using `.venv`) before starting the next task.
- Match existing style (filter-class pattern, mixin structure). Maintain backward compatibility.

## Testing Strategy
- **Unit tests**: required for every task; mock the Telethon client and inject exceptions.
- **E2E tests**: project has no UI e2e suite; not applicable. Live `--media` smoke test is manual (Post-Completion).

## Progress Tracking
- Mark completed items with `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix; blockers with ⚠️ prefix.
- Keep this plan in sync with actual work.

## Implementation Steps

### Task 1: Store the resolved chat entity for refetch
- [x] In `core/download.py` `download_chat()`, right after `entity = await self.get_entity(chat_id)`, set `self._current_entity = entity`.
- [x] Initialize `self._current_entity = None` alongside other run-state attrs (or read via `getattr` elsewhere) so archive-only/no-fetch flows don't `AttributeError`.
- [x] Write test: `download_chat` with mocked `get_entity`/history stores `self._current_entity`.
- [x] Run `pytest` — must pass before Task 2.

### Task 2: Add refetch helper + retry on expired reference in media.py
- [ ] Import `FileReferenceExpiredError` from `telethon.errors` at the top of `core/media.py`.
- [ ] Add `async def _refetch_message(self, message, message_id) -> Optional[Any]` to `MediaMixin`:
  - Resolve target entity: prefer `getattr(self, "_current_entity", None)`; else fall back to `getattr(message, "peer_id", None)`. Return `None` if neither available.
  - `fresh = await self.client.get_messages(entity, ids=int(message_id))` (scalar id → single `Message`).
  - Return `fresh` only if it has `.media`, else `None`. Wrap in try/except → return `None` on failure. Emit one concise `warning` ("File reference expired for message %s; refetching…").
- [ ] In `_download_binary_media()` standard path (currently `media.py:372`), wrap the `client.download_media` call: on `FileReferenceExpiredError`, `fresh = await self._refetch_message(message, message_id)`; if `None`, re-raise; else retry `await self.client.download_media(fresh, file=download_to)` once. (Fast-path expired refs already fall through to this standard path, so they're covered.)
- [ ] Write tests (`tests/test_media_refetch.py`, minimal `MediaMixin` + mock client):
  - `_refetch_message` returns fresh message via `_current_entity`; returns `None` when no entity and message lacks `peer_id`.
  - Standard path: first `download_media` raises `FileReferenceExpiredError`, refetch returns fresh, second succeeds → path returned; `get_messages` called once with the id.
  - Refetch yields `None` → original `FileReferenceExpiredError` propagates.
- [ ] Run `pytest` — must pass before Task 3.

### Task 3: Drain orphaned sender tasks in fast_download.download()
- [ ] In `ParallelTransferrer.download()` (`fast_download.py:337–347`), wrap the per-iteration `for task in tasks` loop in `try/finally`. In `finally`: cancel any not-`done()` task, then `await asyncio.gather(*tasks, return_exceptions=True)`. Let the original exception from `await task` propagate after draining (so `media.py` still sees `FileReferenceExpiredError`/`FastDownloadStalled`).
- [ ] Confirm early-`break` on short/empty chunk still ends the generator cleanly and drains siblings; outer `finally: await self._cleanup()` unchanged.
- [ ] Write test (extend `tests/test_fast_download_cancellation.py`): patch `_init_download` with fake senders whose `next()` raises after the first yield; run the generator to exception and assert all created tasks end `done()` with exceptions consumed (no "never retrieved" warning — e.g. via a custom asyncio exception handler).
- [ ] Run `pytest` — must pass before Task 4.

### Task 4: Filter the "wrong session ID" / "Security error" noise
- [ ] In `core/fast_download.py`, handle records whose message starts with `Security error while unpacking a received message`: either add a branch to `_ServerClosedRewriteFilter` (rewrite to `"Rate limited by Telegram, retrying…"`) or add a dedicated `_SecurityErrorFilter` on the `telethon.network.mtprotosender` logger. Match existing docstring style.
- [ ] If adding a new filter class, register it in `_install_log_filter()` and ensure `_remove_log_filter()` clears it (already iterates `self._log_filters`).
- [ ] Write test mirroring `test_server_closed_rewrite_filter_rewrites_message`: a record with msg `"Security error while unpacking a received message: %s"` is rewritten/dropped as designed; an unrelated record passes through unchanged.
- [ ] Run `pytest` — must pass before Task 5.

### Task 5: Verify acceptance criteria
- [ ] Verify all three Overview problems are addressed: refetch retries once via standard downloader; fast-path failures fall back then refetch; orphaned tasks drained; session-ID noise filtered.
- [ ] Verify no behavior change when `_current_entity` is unset.
- [ ] Run full `pytest` — all green.
- [ ] Run `black src/ tests/` and `isort src/ tests/`; run `mypy src/` if it currently passes.

### Task 6: [Final] Update documentation
- [ ] Update `CLAUDE.md` "Message Processing" / `--media` notes: one sentence that expired file references are automatically refetched during long throttled runs.

## Technical Details
- **Telethon API:** `client.get_messages(entity, ids=<int>)` → single `Message` with fresh `file_reference`; `ids=[<int>]` → list. Use the scalar form.
- **Why standard-only retry:** expired references only manifested after throttling already forced fast→standard fallback; re-attempting the parallel path adds code for negligible gain.
- **Task-drain correctness:** `gather(*tasks, return_exceptions=True)` over a mix of done + freshly-cancelled tasks is safe — done tasks return stored result/exception, cancelled tasks return `CancelledError`; all "retrieved", so asyncio emits no warning. The genuine error re-raises after `finally` and reaches `media.py`.
- **Filter scope:** filters are installed only for a `download()`'s lifetime via `_install_log_filter`/`_remove_log_filter`; global logging untouched.

## Post-Completion
*Items requiring manual intervention or external systems*

**Manual verification** (requires live Telegram account + a throttling-prone media chat):
- Re-run a `--media` download; confirm (a) previously-failing files now download (refetch warning then success, not `Failed to download media`), (b) no `Task exception was never retrieved` blocks, (c) `Security error … wrong session ID` lines collapsed/suppressed.
- Full long-run `--media` against a large media chat to confirm the 2-hour reference-decay scenario recovers mid-run.

**Out of scope / future consideration:**
- The root cause of the multi-hour throttling is the cross-DC parallel fan-out (exported-auth senders) itself. A deeper mitigation (disable parallel for cross-DC files, or cap fan-out further) is a separate design decision, not included here.

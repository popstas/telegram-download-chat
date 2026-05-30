# Telegram Download Chat — Docs, Export, and GUI Enhancements

## Overview

This plan bundles the outstanding work queued in `docs/TODO.md` for the
telegram-download-chat utility: small documentation fixes, a substantial HTML/PDF
export feature (inline entity formatting and reply threads, issue #80), GUI
improvements for structured progress reporting and Windows auto-update, and a
post-media-download summary. The goal is to ship clearer docs, richer exports,
and a more informative GUI without regressing existing JSON/TXT output.

## Context

- Impacted components: `README.md`, GUI docs, `core/render.py` (export rendering),
  GUI (`gui_app.py`) and the core/CLI progress emission path, and the media
  download summary surfaced after `--media`.
- Constraints: TXT output must stay unchanged; #80 export changes are on by
  default with no new flags; HTML uses Jinja2 templates, PDF uses ReportLab.
- Reference talks-reducer's `~/projects/python/talks-reducer/talks_reducer/gui/update_checker.py`
  as the model for the Windows auto-update checker.
- E2E export validation uses a dedicated live test group,
  https://t.me/+5GOZOYpeK-hlMzUy, which contains all formatting, replies, and
  reposts. The e2e download must be a clean download (the `--overwrite` flag —
  the user referred to it as `--rewrite`) so the export reflects the live group
  rather than a cached/resumed partial.
- Adopted from `docs/TODO.md` (generic task-list). One already-completed item
  (telegram-download-chat skill) is excluded as done.

## Development Approach

- Testing approach: regular
- Complete each task fully before moving to the next
- Update this plan when scope changes during implementation

## Testing Strategy

- Unit tests required for every code-changing Task (export, progress, summary)
- Run project tests (`pytest`) after each Task before proceeding
- Doc-only Tasks: verify by inspection; no new tests required
- E2E tests for the #80 export run against the live test group
  (https://t.me/+5GOZOYpeK-hlMzUy) with a clean download (`--overwrite`). They are
  opt-in: marked (e.g. `@pytest.mark.e2e`) and skipped by default when Telegram
  credentials/session are absent, since they require an authenticated account
  that is a member of the private group. They are not part of the default
  `pytest` run / CI.

## Technical Details

### #80 HTML/PDF export — inline formatting + reply threads

- Scope: inline formatting (bold/italic/underline/strikethrough/code/links from
  `entities`) in **HTML and PDF**; thread headers + reply anchors in **HTML
  only**; TXT unchanged; on by default (no new flags). All changes in
  `core/render.py` + tests in `test_telegram_download_chat.py`.
- `format_entities(text, entities, dialect)` helper: map Telegram UTF-16
  `offset`/`length` to Python indices, wrap overlapping spans segment-by-segment
  (well-formed nesting), emit html or ReportLab-pdf tags, sanitize hrefs (scheme
  allowlist drops `javascript:`); html keeps `\n`, pdf uses `<br/>`. Also add
  `first_line(text, limit=60)` helper.
- HTML text: register Jinja `fmt_entities` filter, change `{{ msg.text | e }}` →
  `{{ msg.text | fmt_entities(msg.entities) }}`; carry raw `entities` through
  `_preprocess_messages`.
- PDF text: replace `_xml_escape(text)` body construction with
  `format_entities(text, entities, "pdf")`.
- Reply citation: cite the replied-to message's first line as an anchor
  `href="#msg-<parent_id>"` (parent must be in export, else fall back to existing
  `quote_text`); add `id="msg-<id>"` to each bubble.
- Thread headers (HTML only, `_preprocess_messages(..., with_threads=True)` from
  `render_html`): keep chronological order; compute each message's thread =
  reply-chain root (walk `reply_to_msg_id`, cycle-guarded); inject `--- name ---`
  header on thread change; name = first line of root msg, fallback
  `Thread #<id>`; standalone messages get no header. PDF stays unaffected.

### GUI structured progress

- Have the core/CLI emit structured progress events (media download
  current/total + per-file, and the date of the last downloaded message) that
  the GUI consumes instead of scraping raw log text.

### Windows auto-update

- Core checker (model after talks-reducer's `update_checker.py`): query GitHub
  `releases/latest`, parse the version tag, compare to the running version, and
  resolve the installer/portable download URL. Windows-only for the
  download/install path.
- GUI: add a **"Check updates"** button to the Settings tab
  (`gui/tabs/settings_tab.py`, in its own group alongside the existing API/session
  groups). On click, fetch the latest version and show it (e.g. "Latest: x.y.z" /
  "You're up to date"). The button is **not** disabled after the check — it can be
  clicked again. When an update is available, replace the "Check updates" button
  with a **"Download"** button that opens/downloads the new build (mirroring
  talks-reducer's installer/portable URL behavior).

## Implementation Steps

### Task 1: Reorder README sections

- [x] Move the Usage section above the Installation section in `README.md`
- [x] Verify all internal links/anchors and the table of contents still resolve
- [x] run project tests - must pass before next task

### Task 2: Document GUI entity identifiers

- [x] Explain entity identifiers in the GUI docs: how to download your own Saved
      Messages and a private group (which identifier to use for each)
- [x] Verify the instructions match the actual GUI fields/behavior
- [x] run project tests - must pass before next task

### Task 3: HTML/PDF export — inline entity formatting (#80)

- [x] Add `format_entities(text, entities, dialect)` helper in `core/render.py`
      (UTF-16 offset mapping, segment-by-segment span wrapping, html/pdf tag
      emission, href scheme allowlist dropping `javascript:`)
- [x] Add `first_line(text, limit=60)` helper in `core/render.py`
- [x] HTML: register Jinja `fmt_entities` filter, switch `{{ msg.text | e }}` →
      `{{ msg.text | fmt_entities(msg.entities) }}`, carry raw `entities` through
      `_preprocess_messages`
- [x] PDF: replace `_xml_escape(text)` body construction with
      `format_entities(text, entities, "pdf")`
- [x] write tests: `format_entities` unit tests (both dialects, UTF-16 emoji
      offset, overlap, `javascript:` dropped); PDF smoke run
- [x] run project tests (`pytest`), `black`, `isort` - must pass before next task

### Task 4: HTML export — reply anchors + thread headers (#80)

- [x] Add `id="msg-<id>"` to each message bubble; cite the replied-to message's
      first line as `href="#msg-<parent_id>"`, falling back to existing
      `quote_text` when the parent is not in the export
- [x] Add thread headers via `_preprocess_messages(..., with_threads=True)` from
      `render_html`: chronological order, reply-chain root computation
      (cycle-guarded), inject `--- name ---` on thread change, name = first line
      of root msg (fallback `Thread #<id>`), no header for standalone messages;
      PDF unaffected
- [x] write tests: HTML integration (thread headers only on change, none for
      standalone, recurrence, bubble anchors, reply-anchor + fallback)
- [x] run project tests (`pytest`), `black`, `isort` - must pass before next task

### Task 5: Structured GUI progress events

- [x] Emit structured progress events from core/CLI: media download progress
      (current/total, per-file) and the date of the last downloaded message
- [x] Consume the structured events in the GUI and surface them, replacing raw
      log-text scraping
- [x] write tests for the structured progress event emission
- [x] run project tests - must pass before next task

### Task 6: Windows app auto-update

- [x] Add a core update checker (model after talks-reducer's
      `update_checker.py`): query GitHub `releases/latest`, parse the version tag,
      compare to the running version, resolve installer/portable download URL
      (Windows-only download/install)
- [x] Add a "Check updates" button to the Settings tab
      (`gui/tabs/settings_tab.py`) in its own group; on click, fetch and show the
      latest version (up-to-date vs. newer). Do NOT disable the button after the
      check — it stays clickable
- [x] When an update is available, replace the "Check updates" button with a
      "Download" button that downloads/opens the new build, mirroring
      talks-reducer's behavior
- [x] write tests for version comparison / update-available detection (GUI button
      swap logic tested where feasible)
- [x] run project tests - must pass before next task

### Task 7: Post-`--media` download summary (size, speed, cached, retries)

- [x] After a `--media` download, show the count of media files and their total
      size
- [x] Break the count into **actually downloaded** vs. **cached** (already present
      from a previous run and skipped — the skip path at `media.py` ~line 288)
- [x] Compute and show **average speed in MB/sec** = total downloaded size /
      (finish_time − media-download start_time). Count only actually downloaded
      bytes/files — exclude cached files from both the size and the elapsed-time
      basis
- [x] Track and report retry stats in the summary: number of files that needed a
      retry, broken down by cause — expired file-reference refetch+retry
      (`FileReferenceExpiredError`, `media.py`) and fast-download fallback to the
      single-stream downloader (`FastDownloadStalled`/`FloodWaitError`); count
      files that ultimately failed after retry, if any
- [x] Thread the counters (downloaded, cached, bytes, timing, retries) through
      `download_all_media` results so both CLI and GUI summaries can consume them
- [x] write tests for the size/speed/cached breakdown and the retry-stats counters
      (expired-reference retry path and fast-download fallback path)
- [x] run project tests - must pass before next task

### Task 8: GUI checkbox styling — gray when unchecked

- [x] Style the GUI checkboxes (`download_tab.py`: debug/overwrite/media/html/pdf,
      and any others) so the unchecked indicator is gray, matching the input
      (QLineEdit) background color; checked state keeps its normal appearance
- [x] Apply consistently (prefer a shared stylesheet/helper over per-widget
      duplication) so all checkboxes match
- [x] Verify appearance by inspection in the running GUI (checked vs. unchecked) (skipped - not automatable; covered by unit tests asserting the unchecked-indicator stylesheet)
- [x] run project tests - must pass before next task

### Task 9: E2E export validation against live test group (#80)

- [x] Add an opt-in e2e test (e.g. `@pytest.mark.e2e`, skipped when no Telegram
      session/credentials) that performs a clean download (`--overwrite`) of the
      test group https://t.me/+5GOZOYpeK-hlMzUy
- [x] Render the downloaded export to HTML and PDF
- [x] Assert the HTML/PDF output reflects the group's content: inline formatting
      (bold/italic/underline/strikethrough/code/links), reply anchors + thread
      headers, and reposts/forwarded messages
- [x] Document how to run the e2e suite (required auth + group membership, marker
      selection) in the test docs or README
- [x] run project tests - default run must still pass with e2e skipped

### Task 10: Verify acceptance criteria

- [ ] Verify all requirements from Overview are implemented (docs reordered, GUI
      entity docs added, #80 HTML/PDF formatting + reply threads, structured GUI
      progress, Windows auto-update with Settings "Check updates"/"Download"
      button, media summary with size/speed/cached/retry stats, GUI checkbox
      styling, e2e export validation)
- [ ] Confirm TXT output is unchanged and no new CLI flags were introduced for #80
- [ ] run full project test suite (`pytest`)
- [ ] run project linter (`black`, `isort`, `mypy`) - all issues must be fixed

## Post-Completion

*Items requiring manual intervention - no checkboxes, informational only*

- Windows auto-update behavior should be smoke-tested on an actual Windows build
  (download/install path cannot be fully exercised by the test suite).
- After merging, mark the corresponding items as completed in `docs/TODO.md`.

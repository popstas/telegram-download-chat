# TODO

- [x] **(do first)** Create directory `./data`, add it to `.gitignore`, and update `CLAUDE.md` so e2e results are saved to `./data` (instead of `~/tmp/e2e-tdc`). All e2e in subsequent tasks writes to `./data`.

- [x] Download replied/cited messages that fall outside the requested window. Example: downloading the last 7 days — message 1 (2026-05-01) was replied to by message 2 (2026-06-01). Current behavior: when message 2 is downloaded, the cited message 1 is empty because it's outside the date range. Expected: also fetch the referenced message 1 (by its id) so the citation is populated.

- [x] Don't cite channel post in comment messages. Only for channel comments.
- [x] Also download and render comment messages media, if not. Observed with `--comments`: comment media references appear in JSON and TXT, but the attachments are not downloaded under `--media` and the references are not rendered in HTML.
- [x] Make `--comments` resumable: restarting an interrupted job currently re-scans every post for comments instead of resuming. Checkpoint which posts already had comments fetched so a restart skips them (comment records live in a separate id space and are excluded from the post-based resume cursor).

- [x] Collect reactions for posts, comments, and regular chat messages (channels and other chats). Capture each message's reactions (emoji/custom-emoji + counts, and where available who reacted) into the saved JSON. Clarify the reactions data format first (inspect Telethon's `message.reactions` / `ReactionCount` / `MessageReactions`: standard emoji vs `ReactionCustomEmoji`, per-emoji counts, `recent_reactions`/`results`), then define a stable normalized shape to store. HTML render should reproduce Telegram's UI reactions — show the reaction pills (emoji + count) under each message the way the Telegram client does. Verify via e2e on a channel/post with reactions.

- [x] Add the application version number to the GUI window title.

- [x] Add a minimal Windows installer — portable version only for now. Support incremental updates if possible (most of the distribution is the Python runtime, so only the changed app files should need updating).

- [x] Make the GUI progress bars more visual: change the color from red to green and/or draw a progress line.

- [x] Document CLI flags present in `--help` but missing from the README: `--split {month,year,topics}`, `--no-fast-download`, `--html`, `--html-media-links`, `--pdf`.

- [x] Make html render comments collapsible. Only for channel comments. Collapsed shows comment count, expanded shows the comment text.

## Reactions follow-ups

- [x] Add optional text reactions: render each message's reactions as an inline text suffix in `messages.txt`, behind a `--reactions` flag (off by default).
- [x] Add HTML render filter for channel comments by minimum reactions — percentile buttons (All / Top 50% / 20% / 10% / 5%), each showing the computed reaction threshold and matching comment count (e.g. "Top 20%: 3+ (12)"); client-side, hides comments below the threshold.
- [x] Add optional channel comments filter by min reactions: `--comments-min-reactions N` drops comments whose total reaction count is below N before they are saved (and before their media is downloaded).

## Windows build

- [x] Replace the onedir+manifest portable build with a two-part embeddable-Python distribution (Variant A): an immutable `runtime/` base (embeddable CPython + all third-party packages + launchers) installed once, and a tiny `app/` part (our source only) replaced wholesale on each release via `app-<version>.zip`. Drop `package_portable.py` / `diff_manifests`; add `scripts/package_embed.py` (`build_app_zip`, `apply_app_update`) and `build_windows_embed.ps1`. See `docs/superpowers/specs/2026-06-04-windows-two-part-embed-build-design.md`.
- [x] Wire in-app update into the GUI: `core/app_updater.py` (`find_app_install_dir`, `download_app_zip`, `perform_app_update`) + a Settings "Update now" button that downloads `app-<version>.zip` and atomically swaps `app/`, then offers a restart. Falls back to the browser when not running from an embeddable install.

## E2E verification (applies to comments/citations/media/reactions tasks)

- Target channel: `@seeallochnaya` (channel-with-comments).
- Method: **live CLI run + inspect output** — run the real CLI with `--comments --media --html`, then inspect `messages.json` and the rendered HTML to confirm citations are populated, comment media is downloaded/rendered, channel-post citations are suppressed in comments, and reaction pills appear.
- Copy results to `./data` (per task #1, done first).

# TODO

- [x] add skill to skills/telegram-download-chat/SKILL.md — Describe all cli usage with examples. (done)
- [ ] Move the Usage section above the Installation section in README.
- [ ] Explain entity identifiers in the GUI: how to download my Saved Messages and a private group.
- [ ] [#80] HTML export: preserve message formatting (bold, italics, underline, hyperlinks) and render threads/replies (sub-comments). JSON already has this info, and media in sub-comments is downloaded. https://github.com/popstas/telegram-download-chat/issues/80
- [ ] Improve GUI: parse more structured info from the download log and surface it in the GUI — media download progress (current/total, per-file) and the date of the last downloaded message. Have the core/CLI emit structured progress events the GUI can consume instead of scraping raw log text.
- [ ] Add Windows app auto-update: on startup check GitHub releases/latest, compare to the running version, and offer to download/install the new build. Model after `~/projects/python/talks-reducer/talks_reducer/gui/update_checker.py` (queries `releases/latest`, parses the version tag, compares versions, Windows-only).

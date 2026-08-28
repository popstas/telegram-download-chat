# TODO

## E2E verification (applies to comments/citations/media/reactions tasks)

- Target channel: `@seeallochnaya` (channel-with-comments).
- Method: **live CLI run + inspect output** — run the real CLI with `--comments --media --html`, then inspect `messages.json` and the rendered HTML to confirm citations are populated, comment media is downloaded/rendered, channel-post citations are suppressed in comments, and reaction pills appear.
- Copy results to `./data` (gitignored, kept via `data/.gitkeep`).

# Reactions in TXT, percentile comment filter in HTML, CLI comment reaction filter

Date: 2026-06-04
Branch: `tdc-backlog-comments-citations-reactions-gui` (extends PR #84 — all three
features build directly on the unmerged reactions/comments code).

## Overview

Three follow-ups to the reactions/comments work:

1. Optionally render each message's reactions as an inline text suffix in
   `messages.txt`.
2. A client-side percentile filter for channel comments in the rendered HTML.
3. A CLI flag that drops low-reaction channel comments before they are saved.

A message's **reaction count** is the **sum of all reaction counts**
(`👍5 + ❤️2 = 7`). This metric is shared by the CLI filter and the HTML filter.

## Shared helpers — `core/reactions.py`

Add two helpers next to `normalize_reactions` / `reaction_key`:

- `total_reaction_count(reactions) -> int`
  Normalizes defensively (accepts raw Telethon dict or already-normalized list),
  returns the sum of every entry's `count` (0 when none).
- `format_reactions_text(reactions) -> str`
  Returns `"👍5 ❤️2 ⭐3"` — standard emoji as their glyph, custom emoji as the
  `⭐` placeholder (matching the HTML pill placeholder). Returns `""` when there
  are no reactions.

Both are exported via `__all__`.

## Task 1 — Reactions in `messages.txt` (opt-in, inline suffix)

- New CLI flag `--reactions` (`store_true`, default `False`) and `reactions: bool
  = False` on the Args dataclass (`cli/arguments.py`).
- Thread the flag: `cli/commands.py` passes it to
  `save_messages(..., reactions=False)`, which forwards it to
  `save_messages_as_txt(..., reactions=False)` (`core/messages.py`).
- In `save_messages_as_txt`, after the existing media-placeholder handling and
  before composing `line`: when `reactions` is on and the message has reactions,
  append the suffix to `text`:
  - text present → `text = f"{text} [{suffix}]"`
  - no text → `text = f"[{suffix}]"`
  where `suffix = format_reactions_text(msg.get("reactions"))` (skip when empty).
- Applies to all messages (posts, comments, regular). Off by default → output
  byte-identical to today.

## Task 3 — `--comments-min-reactions N` (CLI, filters saved data)

- New flag `--comments-min-reactions N` (int, default `0` = no filter). It only
  has effect with `--comments`. `comments_min_reactions: int = 0` on the Args
  dataclass.
- `download_post_comments(..., min_reactions: int = 0)` (`core/comments.py`):
  after a comment is normalized and **before** its media is downloaded, drop it
  when `total_reaction_count(comment.get("reactions")) < min_reactions`. This
  guarantees no media is fetched for dropped comments.
- `fetch_channel_comments` (`cli/commands.py`) passes
  `min_reactions=getattr(args, "comments_min_reactions", 0)`.
- Interaction with `--comments-limit`: the limit still caps how many comments are
  *fetched* per post (paging cap); this filter is a quality gate applied to what
  was fetched. Documented in the flag help and CLAUDE.md.
- Filtered comments never reach `messages.json` / `.txt` / `.html`.

## Task 2 — HTML percentile filter for channel comments (client-side JS)

Server side (`core/render.py`):
- Compute `reactions_total = total_reaction_count(raw reactions)` alongside the
  existing `reactions` pills in the items pipeline, and stash it on the rendered
  msg dict.
- Add `data-reactions="{{ msg.reactions_total }}"` to every message `.msg`
  element in the `render_group` macro. The filter scope is the comment `.msg`
  elements, i.e. `.comments .msg` (comments already render inside
  `<details class="comments">`).
- Render a filter bar at the top of the page **only when the page contains
  channel comments** (a template flag `has_comments`). Buttons:
  `All / Top 50% / Top 20% / Top 10% / Top 5%`, each carrying its percentile as a
  data attribute.

Client side (vanilla JS in the template, no deps):
- On load, collect the `data-reactions` integers of all `.comments .msg`.
- For each percentile `p` (50/20/10/5), compute the threshold = the value at the
  `(1 - p)` quantile of the distribution, and `count` = number of comments with
  `sum >= threshold`. Label the button `Top 20%: 3+ (12)` (threshold `3+`
  reactions, `12` comments). `All` shows the total comment count.
- Clicking a button hides every comment `.msg` whose `data-reactions <
  threshold`, updates each `<details class="comments">` summary to its visible
  count, and hides comment blocks that become empty. `All` resets everything.

## Testing

Unit (`pytest`):
- `total_reaction_count` and `format_reactions_text`: emoji + custom-emoji +
  empty cases.
- TXT: `--reactions` on appends the expected suffix; off (default) leaves output
  unchanged; a no-reactions message is untouched; a no-text message becomes just
  the bracket.
- CLI filter: comments below the threshold are dropped before media download;
  `0`/unset keeps all; interaction with `--comments-limit`.
- HTML render: `data-reactions` attributes present on comment messages; the
  percentile bar renders with the correct threshold/count labels for a known
  distribution; the bar is absent when there are no comments.

E2E (per `./data` convention, opt-in):
`--comments --media --html --reactions --comments-min-reactions 2` against
`@seeallochnaya`; inspect `messages.txt` for suffixes, `messages.json` for the
absence of <2-reaction comments, and the HTML for the percentile bar; copy
results to `./data`.

## Out of scope (YAGNI)

- No per-post percentile recomputation (thresholds are page-global).
- No reactions in PDF output.
- No GUI control for the new flags in this iteration.

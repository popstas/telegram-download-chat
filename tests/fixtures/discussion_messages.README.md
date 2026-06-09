# `discussion_messages.json`

Synthetic-but-faithful serialized discussion-group messages for the Part B
mapping unit tests (plan `docs/plans/20260608-comment-media-html-link-resume.md`,
Tasks B1–B3). Each entry mirrors a real Telethon `Message.to_dict()` run through
`make_serializable` (dates as strings), captured from the linked discussion group
`1619992925` (`ecceverbum`) structure confirmed by `scripts/spike_discussion_mapping.py`.

Representative cases (covers the Task B1 "2–3 representative messages" requirement):

| id    | role                | key fields                                            | maps to post |
|-------|---------------------|-------------------------------------------------------|--------------|
| 9230  | forwarded root      | `fwd_from.channel_post = 5477`                         | — (not a comment) |
| 9120  | forwarded root      | `fwd_from.channel_post = 5445`                         | — (not a comment) |
| 9240  | direct reply + PDF  | `reply_to_msg_id = 9230`, `reply_to_top_id = null`    | 5477 |
| 9131  | direct reply + PDF  | `reply_to_msg_id = 9120`, `reply_to_top_id = null`    | 5445 |
| 9241  | nested reply        | `reply_to_msg_id = 9240`, `reply_to_top_id = 9230`    | 5477 (via top_id) |
| 9300  | out-of-window reply | `reply_to_msg_id = 9299` (root never seen)            | dropped (unmapped) |

Mapping rule under test: build `root_to_post[disc_id] = fwd_from.channel_post`
from forwarded roots, then `comment.post_id = root_to_post[reply_to_top_id or
reply_to_msg_id]`. Posts 5477/5445 and comments 9240/9131 match the live data the
per-post path produced; comment media (the PDFs) is what Part A surfaces on resume.

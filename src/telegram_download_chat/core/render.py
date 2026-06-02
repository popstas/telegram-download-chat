"""HTML and PDF chat export rendering — Telegram Web light-theme style."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AVATAR_COLORS = ["#c03d33", "#4fad2d", "#d09306", "#168acd", "#8544d6", "#cd4073"]

ACTION_LABELS: Dict[str, str] = {
    "MessageActionChatAddUser": "joined the group",
    "MessageActionChatDeleteUser": "left the group",
    "MessageActionChatJoinedByLink": "joined via invite link",
    "MessageActionChatEditTitle": "changed the group name",
    "MessageActionChatEditPhoto": "updated the group photo",
    "MessageActionChatCreate": "created the group",
    "MessageActionPinMessage": "pinned a message",
    "MessageActionChatMigrateTo": "group was upgraded to a supergroup",
    "MessageActionChannelCreate": "created the channel",
    "MessageActionPhoneCall": "Phone call",
    "MessageActionGroupCall": "Group call",
    "MessageActionInviteToGroupCall": "was invited to a voice chat",
    "MessageActionContactSignUp": "joined Telegram",
    "MessageActionHistoryClear": "cleared the history",
    "MessageActionSetMessagesTTL": "changed the auto-delete timer",
    "MessageActionScreenshotTaken": "took a screenshot",
}

# ---------------------------------------------------------------------------
# Jinja2 HTML template — self-contained, no external CDN dependencies
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ chat_title | e }}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;
  background:#eae6da;color:#111;font-size:14px;line-height:1.45;min-height:100vh}
a{color:#168acd;text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:900px;margin:0 auto;display:flex;flex-direction:column;min-height:100vh;background:inherit}
/* Header */
.hdr{background:#fff;border-bottom:1px solid #ddd;padding:12px 16px;
  display:flex;align-items:center;gap:12px;position:static;
  box-shadow:0 1px 3px rgba(0,0,0,0.08)}
.hdr-av{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-weight:700;font-size:18px;color:#fff;
  background:#168acd;flex-shrink:0}
.hdr-info .name{font-weight:600;font-size:16px}
.hdr-info .sub{font-size:12px;color:#999;margin-top:2px}
/* Topic tabs */
.tabs{position:sticky;top:0;z-index:9;display:flex;gap:6px;flex-wrap:wrap;
  background:#f0f2f5;padding:8px 14px;border-bottom:1px solid #d8dce0}
.topic-tab{border:none;background:#e1e6eb;color:#3a4a5a;border-radius:14px;
  padding:5px 12px;font-size:12px;font-weight:600;cursor:pointer;line-height:1.3}
.topic-tab:hover{background:#d4dae0}
.topic-tab.active{background:#168acd;color:#fff}
/* Messages area */
.msgs{flex:1;padding:16px 12px 32px;display:flex;flex-direction:column;gap:1px}
/* Date separator */
.datesep{text-align:center;margin:14px 0 10px;user-select:none}
.datesep span{background:rgba(0,0,0,0.22);color:#fff;border-radius:14px;
  padding:5px 14px;font-size:12px;font-weight:500}
/* Thread separator */
.threadsep{text-align:center;margin:16px 0 8px;user-select:none}
.threadsep span{display:inline-block;max-width:80%;color:#5a6b7b;font-size:12px;
  font-weight:600;letter-spacing:.02em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* Spoiler */
.spoiler{background:#1f2c33;color:transparent;border-radius:4px;padding:0 2px;
  cursor:pointer;transition:color .15s ease,background .15s ease}
.spoiler:hover{background:rgba(0,0,0,0.06);color:inherit}
/* Service message */
.svc{text-align:center;margin:8px auto;user-select:none}
.svc span{background:rgba(0,0,0,0.16);color:#fff;border-radius:12px;
  padding:4px 12px;font-size:12px;display:inline-block}
/* Message group */
.grp{display:flex;align-items:flex-end;gap:6px;margin-bottom:2px;max-width:100%}
.grp.out{flex-direction:row-reverse}
/* Avatar */
.av{width:34px;height:34px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-weight:700;font-size:13px;color:#fff;
  flex-shrink:0;align-self:flex-end}
.av-ph{width:34px;flex-shrink:0}
/* Bubble column */
.bubbles{display:flex;flex-direction:column;gap:2px;max-width:72%;min-width:80px}
.grp.out .bubbles{align-items:flex-end}
/* Sender name */
.sname{font-size:13px;font-weight:600;margin-bottom:3px;padding-left:14px}
/* Bubble */
.bbl{background:#fff;border-radius:18px;padding:8px 12px 6px;
  box-shadow:0 1px 2px rgba(0,0,0,0.14);position:relative;word-break:break-word;max-width:100%;
  scroll-margin-top:60px}
.grp.out .bbl{background:#d9fdd3}
/* Squarish inner corners for consecutive bubbles */
.grp:not(.out) .bbl{border-bottom-left-radius:5px}
.grp:not(.out) .bbl:first-child{border-top-left-radius:18px}
.grp:not(.out) .bbl:last-child{border-bottom-left-radius:18px}
.grp.out .bbl{border-bottom-right-radius:5px}
.grp.out .bbl:first-child{border-top-right-radius:18px}
.grp.out .bbl:last-child{border-bottom-right-radius:18px}
/* Tails on last bubble only */
.grp:not(.out) .bbl:last-child::before{content:'';position:absolute;
  bottom:8px;left:-7px;border:7px solid transparent;
  border-right-color:#fff;border-left-width:0}
.grp.out .bbl:last-child::before{content:'';position:absolute;
  bottom:8px;right:-7px;border:7px solid transparent;
  border-left-color:#d9fdd3;border-right-width:0}
/* Forward header */
.fwd{border-left:3px solid #00a884;padding-left:8px;margin-bottom:6px;
  color:#00a884;font-size:13px;font-weight:600}
/* Reply quote */
.rq{background:rgba(0,0,0,0.05);border-left:3px solid #00a884;border-radius:6px;
  padding:5px 8px;margin-bottom:6px;font-size:12.5px;color:#555;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;max-height:64px}
/* Collapsible channel-post comments */
.comments{margin:2px 0 8px 40px}
.comments-sum{cursor:pointer;color:#168acd;font-size:13px;font-weight:600;
  list-style:none;user-select:none;padding:4px 0}
.comments-sum::-webkit-details-marker{display:none}
.comments-sum::before{content:'\\25B8\\00a0'}
.comments[open]>.comments-sum::before{content:'\\25BE\\00a0'}
.comments-body{margin-top:4px;display:flex;flex-direction:column;gap:1px}
/* Media */
.media-img,.media-stk,.media-vid{display:block;border-radius:10px;margin-bottom:4px}
.media-img{max-width:100%;max-height:340px;object-fit:contain}
.media-stk{max-width:160px;max-height:160px}
.media-vid{max-width:100%;max-height:280px;width:100%}
.media-aud{width:260px;max-width:100%;margin-bottom:4px;display:block}
.media-file{display:flex;align-items:center;gap:10px;background:rgba(0,0,0,0.04);text-decoration:none;color:inherit;
  border-radius:10px;padding:8px 10px;margin-bottom:4px}
.media-file .ico{font-size:26px;line-height:1;flex-shrink:0}
.media-file .fname{font-size:13px;font-weight:500;color:#333;word-break:break-all}
.media-loc{margin-bottom:4px;font-size:13px}
.media-ref{display:block;margin-top:-2px;margin-bottom:4px;font-size:11px;color:#8b8b8b;word-break:break-all}
.media-ref a{color:inherit;text-decoration:none}
.media-ref a:hover{text-decoration:underline}
.poll-wrap{margin-bottom:4px}
.poll-q{font-weight:600;margin-bottom:5px;font-size:13.5px}
.poll-opt{display:flex;justify-content:space-between;align-items:center;
  border-left:3px solid #168acd;padding:2px 0 2px 8px;margin-bottom:3px;font-size:13px}
.poll-opt .votes{font-size:11px;color:#888;flex-shrink:0;margin-left:8px}
.poll-total{font-size:11px;color:#888;margin-top:3px}
/* Text */
.txt{white-space:pre-wrap;font-size:14px;color:#111}
/* Meta */
.meta{display:flex;justify-content:flex-end;align-items:center;
  gap:5px;font-size:11px;color:#8a8a8a;margin-top:4px;user-select:none}
.meta .edited{font-style:italic}
.meta .tick{color:#53bdeb;font-size:13px}
/* Print */
@media print{
  .hdr{position:static;box-shadow:none}
  .tabs{display:none}
  .bbl,.grp{break-inside:avoid;page-break-inside:avoid}
}
</style>
</head>
<body>
<div class="wrap">
<div class="hdr">
  <div class="hdr-av">{{ (chat_title[0:1] or "?") | upper | e }}</div>
  <div class="hdr-info">
    <div class="name">{{ chat_title | e }}</div>
    <div class="sub">{{ message_count }} messages &middot; Exported by telegram-download-chat</div>
  </div>
</div>
{%- if topics %}
<div class="tabs">
  <button class="topic-tab active" data-topic="all">All</button>
  {%- for t in topics %}
  <button class="topic-tab" data-topic="{{ t.id }}">{{ t.name | e }}</button>
  {%- endfor %}
</div>
{%- endif %}
{%- macro render_group(item) %}
<div class="grp{% if item.is_outgoing %} out{% endif %}" data-topic="{{ item.topic if item.topic is not none else 'none' }}">
  {%- if not item.is_outgoing %}
  <div class="av" style="background:{{ item.sender_color }}">{{ item.initials | e }}</div>
  {%- else %}
  <div class="av-ph"></div>
  {%- endif %}
  <div class="bubbles">
    {%- if not item.is_outgoing %}
    <div class="sname" style="color:{{ item.sender_color }}">{{ item.sender_name | e }}</div>
    {%- endif %}
    {%- for msg in item.messages %}
    <div class="bbl"{% if msg.id is not none %} id="msg-{{ msg.id }}"{% endif %}>
      {%- if msg.fwd_from_name %}
      <div class="fwd">&#8627; Forwarded from {{ msg.fwd_from_name | e }}</div>
      {%- endif %}
      {%- if msg.reply_text %}
      <div class="rq">{% if msg.reply_to_id is not none %}<a href="#msg-{{ msg.reply_to_id }}">{{ msg.reply_text | e }}</a>{% else %}{{ msg.reply_text | e }}{% endif %}</div>
      {%- endif %}
      {%- if msg.attachment_path %}
        {%- set src = (media_prefix + msg.attachment_path) | urlencode_path %}
        {%- if msg.media_category == "stickers" %}
        <img class="media-stk" src="{{ src }}" alt="sticker" loading="lazy">
        {%- if media_links %}<span class="media-ref"><a href="{{ src }}" target="_blank" rel="noopener">{{ msg.attachment_path | e }}</a></span>{% endif %}
        {%- elif msg.media_category == "images" %}
        <img class="media-img" src="{{ src }}" alt="" loading="lazy">
        {%- if media_links %}<span class="media-ref"><a href="{{ src }}" target="_blank" rel="noopener">{{ msg.attachment_path | e }}</a></span>{% endif %}
        {%- elif msg.media_category == "videos" %}
        <video class="media-vid" controls preload="none" src="{{ src }}"></video>
        {%- if media_links %}<span class="media-ref"><a href="{{ src }}" target="_blank" rel="noopener">{{ msg.attachment_path | e }}</a></span>{% endif %}
        {%- elif msg.media_category == "audio" %}
        <audio class="media-aud" controls preload="none" src="{{ src }}"></audio>
        {%- if media_links %}<span class="media-ref"><a href="{{ src }}" target="_blank" rel="noopener">{{ msg.attachment_path | e }}</a></span>{% endif %}
        {%- elif msg.media_category in ("documents", "archives") %}
        <a class="media-file" href="{{ src }}" target="_blank" rel="noopener">
          <div class="ico">{% if msg.media_category == "archives" %}&#128736;{% else %}&#128196;{% endif %}</div>
          <div class="fname">{{ msg.attachment_filename | e }}</div>
        </a>
        {%- elif msg.media_category == "contacts" %}
        <a class="media-file" href="{{ src }}" target="_blank" rel="noopener"><div class="ico">&#128100;</div><div class="fname">{{ msg.attachment_filename | e }}</div></a>
        {%- elif msg.media_category == "locations" %}
        <div class="media-loc">&#128205; <a href="https://maps.google.com/?q={{ msg.location_lat }},{{ msg.location_lng }}" target="_blank" rel="noopener">View on map</a></div>
        {%- elif msg.media_category == "polls" and msg.poll_data %}
        <div class="poll-wrap">
          <div class="poll-q">&#128202; {{ msg.poll_data.question | default('', true) | e }}</div>
          {%- for ans in msg.poll_data.answers | default([], true) %}
          <div class="poll-opt"><span>{{ ans.text | default('', true) | e }}</span>{% if ans.voters is not none %}<span class="votes">{{ ans.voters }}</span>{% endif %}</div>
          {%- endfor %}
          {%- if msg.poll_data.total_voters is not none %}
          <div class="poll-total">{{ msg.poll_data.total_voters }} total votes</div>
          {%- endif %}
        </div>
        {%- else %}
        <a class="media-file" href="{{ src }}" target="_blank" rel="noopener">
          <div class="ico">&#128206;</div>
          <div class="fname">{{ msg.attachment_filename | e }}</div>
        </a>
        {%- if media_links %}<span class="media-ref"><a href="{{ src }}" target="_blank" rel="noopener">{{ msg.attachment_path | e }}</a></span>{% endif %}
        {%- endif %}
      {%- endif %}
      {%- if msg.text %}
      <div class="txt">{{ msg.text | fmt_entities(msg.entities) }}</div>
      {%- endif %}
      <div class="meta">
        {%- if msg.edited %}<span class="edited">edited</span>{%- endif %}
        <span>{{ msg.time }}</span>
        {%- if item.is_outgoing %}<span class="tick">&#10003;&#10003;</span>{%- endif %}
      </div>
    </div>
    {%- endfor %}
  </div>
</div>
{%- endmacro %}
<div class="msgs">
{%- for item in items %}
{%- if item.type == "date_sep" %}
<div class="datesep" data-topic="__date__"><span>{{ item.label | e }}</span></div>
{%- elif item.type == "thread" %}
<div class="threadsep" data-topic="{{ item.topic if item.topic is not none else 'none' }}"><span>&mdash; {{ item.name | e }} &mdash;</span></div>
{%- elif item.type == "service" %}
<div class="svc" data-topic="{{ item.topic if item.topic is not none else 'none' }}"><span>{{ item.text | e }}</span></div>
{%- elif item.type == "group" %}
{{ render_group(item) }}
{%- elif item.type == "comments" %}
<details class="comments" data-topic="none">
<summary class="comments-sum">{{ item.count }} comment{{ '' if item.count == 1 else 's' }}</summary>
<div class="comments-body">
{%- for g in item.groups %}{{ render_group(g) }}{%- endfor %}
</div>
</details>
{%- endif %}
{%- endfor %}
</div>
</div>
{%- if topics %}
<script>
(function(){
  var msgs = document.querySelector('.msgs');
  var tabs = document.querySelectorAll('.topic-tab');
  if(!msgs || !tabs.length) return;
  function apply(topic){
    var items = msgs.children, i, el, t;
    for(i=0;i<items.length;i++){
      el = items[i]; t = el.getAttribute('data-topic');
      if(el.classList.contains('datesep')){ el.style.display=''; continue; }
      if(topic==='all'){ el.style.display=''; }
      else if(el.classList.contains('threadsep')){ el.style.display='none'; }
      else { el.style.display = (t===topic) ? '' : 'none'; }
    }
    // Hide date separators with no visible content before the next separator.
    if(topic!=='all'){
      var seen=false;
      for(i=items.length-1;i>=0;i--){
        el = items[i];
        if(el.classList.contains('datesep')){ el.style.display = seen ? '' : 'none'; seen=false; }
        else if(el.style.display!=='none'){ seen=true; }
      }
    }
    for(i=0;i<tabs.length;i++){
      tabs[i].classList.toggle('active', tabs[i].getAttribute('data-topic')===topic);
    }
  }
  for(var k=0;k<tabs.length;k++){
    tabs[k].addEventListener('click', function(){ apply(this.getAttribute('data-topic')); });
  }
})();
</script>
{%- endif %}
</body>
</html>"""


class RenderMixin:
    """Mixin that adds HTML and PDF chat export to TelegramChatDownloader."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render_html(
        self,
        messages: List[Dict[str, Any]],
        output_file: Path,
        attachments_dir: Optional[Path] = None,
        chat_title: str = "Chat",
        media_links: bool = False,
    ) -> None:
        """Render messages as a Telegram Web-style self-contained HTML file."""
        try:
            from jinja2 import BaseLoader, Environment
        except ImportError:
            raise ImportError(
                "jinja2 is required for HTML export. "
                "Install it with: pip install telegram-download-chat[export]"
            )

        # Compute relative path from the HTML file to the attachments directory
        media_prefix = "attachments/"
        if attachments_dir:
            try:
                rel = os.path.relpath(attachments_dir, output_file.parent)
                media_prefix = rel.replace("\\", "/") + "/"
            except ValueError:
                # Cross-drive on Windows — use absolute file:// URI
                media_prefix = Path(attachments_dir).resolve().as_uri() + "/"

        from markupsafe import Markup

        items = self._preprocess_messages(messages, attachments_dir, with_threads=True)
        # Ordered, de-duplicated forum topics for the tab bar (first appearance).
        topics: List[Dict[str, Any]] = []
        seen_topics: set = set()
        for item in items:
            tid = item.get("topic")
            if tid is not None and tid not in seen_topics:
                seen_topics.add(tid)
                topics.append({"id": tid, "name": item.get("topic_name") or str(tid)})
        env = Environment(loader=BaseLoader(), autoescape=True)
        env.filters["urlencode_path"] = lambda s: quote(str(s), safe="/")
        env.filters["fmt_entities"] = lambda text, entities: Markup(
            format_entities(text, entities, "html")
        )
        tmpl = env.from_string(HTML_TEMPLATE)
        html = tmpl.render(
            chat_title=chat_title,
            message_count=len(messages),
            items=items,
            topics=topics,
            media_prefix=media_prefix,
            media_links=media_links,
        )
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(html, encoding="utf-8")

    def render_pdf(
        self,
        messages: List[Dict[str, Any]],
        output_file: Path,
        attachments_dir: Optional[Path] = None,
        chat_title: str = "Chat",
    ) -> None:
        """Render messages as a PDF document using ReportLab."""
        _render_pdf_reportlab(self, messages, output_file, attachments_dir, chat_title)

    # ------------------------------------------------------------------
    # Message preprocessing — shared by HTML and PDF
    # ------------------------------------------------------------------

    def _preprocess_messages(
        self,
        messages: List[Dict[str, Any]],
        attachments_dir: Optional[Path],
        with_threads: bool = False,
    ) -> List[Dict[str, Any]]:
        """Convert flat message list into structured render items.

        When ``with_threads`` is True (HTML only), a ``thread`` item is injected
        whenever the conversation switches to a different reply-chain thread, so
        the reader can follow interleaved threads. Standalone messages (threads
        of a single message) produce no header.
        """
        items: List[Dict[str, Any]] = []
        current_group: Optional[Dict[str, Any]] = None
        prev_date: Optional[str] = None
        prev_sender_id: Any = None
        prev_msg_time: Optional[datetime] = None
        prev_thread_id: Any = None

        _epoch = datetime.min.replace(tzinfo=timezone.utc)
        sorted_msgs = sorted(
            messages, key=lambda m: _parse_dt(m.get("date") or "") or _epoch
        )

        # ── Message index ────────────────────────────────────────────────
        # Map message id -> message so reply citations can resolve an anchor
        # to the parent bubble when the parent is present in the export.
        id_to_msg: Dict[Any, Dict[str, Any]] = {}
        for m in sorted_msgs:
            mid = m.get("id")
            if mid is None:
                continue
            # A channel comment keeps its native discussion id, which can collide
            # with a real channel post id. Reply citations only ever target posts,
            # so never let a comment shadow a post already indexed under that id.
            if mid in id_to_msg and m.get("comment_of") is not None:
                continue
            id_to_msg[mid] = m

        # Thread/topic headers (and root-citation suppression) only make sense in
        # forum supergroups, which actually have topics. In private chats and
        # regular groups a reply is just a quote, so render it via the inline
        # reply citation only — no "--- name ---" topic separators.
        is_forum = with_threads and _is_forum(sorted_msgs)

        # Forum topic grouping: every message maps to its forum topic id (not its
        # reply-chain root), so a windowed download whose topic-create messages
        # fall outside the range still groups cleanly. Names come from an
        # in-window topic-create title or the stored forum_topic_title, falling
        # back to "Thread #<id>".
        topic_of: Dict[Any, Any] = {}
        topic_titles: Dict[Any, str] = {}
        if is_forum:
            for m in sorted_msgs:
                mid = m.get("id")
                tid = _forum_topic_id(m)
                if mid is not None:
                    topic_of[mid] = tid
                if tid is not None and tid not in topic_titles:
                    name = _forum_topic_title(m)
                    if name:
                        topic_titles[tid] = name
            for tid in set(topic_of.values()):
                if tid is None or tid in topic_titles:
                    continue
                # No fetched/created title. If the topic id is an in-window
                # message, name it by that message's first line; else Thread #id.
                root_msg = id_to_msg.get(tid)
                line = (
                    first_line(root_msg.get("message"))
                    if isinstance(root_msg, dict)
                    else ""
                )
                topic_titles[tid] = line or f"Thread #{tid}"

        def _topic_for(m: Dict[str, Any]) -> tuple:
            """(topic_id, topic_name) for a message in the current export."""
            if not is_forum:
                return (None, None)
            tid = topic_of.get(m.get("id"))
            return (tid, topic_titles.get(tid) if tid is not None else None)

        def flush() -> None:
            nonlocal current_group
            if current_group is not None:
                items.append(current_group)
                current_group = None

        self_id = getattr(self, "_self_id", None)

        for msg in sorted_msgs:
            date_str = msg.get("date") or ""
            msg_dt = _parse_dt(date_str)
            # Use local timezone for grouping, consistent with display formatting
            msg_date = msg_dt.astimezone().strftime("%Y-%m-%d") if msg_dt else None

            # ── Date separator ──────────────────────────────────────
            if msg_date and msg_date != prev_date:
                flush()
                items.append({"type": "date_sep", "label": _fmt_date_sep(date_str)})
                prev_date = msg_date

            # ── Service / action message ─────────────────────────────
            action = msg.get("action")
            if action and isinstance(action, dict) and action.get("_"):
                flush()
                svc = _service_text(action, msg)
                if svc:
                    svc_topic, svc_topic_name = _topic_for(msg)
                    items.append(
                        {
                            "type": "service",
                            "text": svc,
                            "topic": svc_topic,
                            "topic_name": svc_topic_name,
                        }
                    )
                prev_sender_id = None
                prev_msg_time = None
                continue

            # ── Sender identity ──────────────────────────────────────
            from_id = msg.get("from_id") or {}
            if isinstance(from_id, dict):
                sender_id: Any = (
                    from_id.get("user_id")
                    or from_id.get("channel_id")
                    or from_id.get("chat_id")
                    or 0
                )
            elif isinstance(from_id, int):
                sender_id = from_id
            else:
                sender_id = 0

            is_outgoing = bool(msg.get("out")) or (
                self_id is not None and sender_id == self_id
            )
            sender_name = msg.get("user_display_name") or (
                str(sender_id) if sender_id else "Unknown"
            )

            # Channel comments carry ``comment_of`` (their parent post id); it
            # bounds a sender group so a group never mixes a post with comments
            # (or comments of two different posts), keeping the collapsible
            # comment block per-post when folded below.
            comment_of = msg.get("comment_of")

            # ── Topic header (HTML, forum supergroups only) ──────────
            msg_topic, msg_topic_name = _topic_for(msg)
            if is_forum:
                if msg_topic is not None and msg_topic != prev_thread_id:
                    flush()
                    items.append(
                        {
                            "type": "thread",
                            "name": msg_topic_name or f"Thread #{msg_topic}",
                            "topic": msg_topic,
                            "topic_name": msg_topic_name,
                        }
                    )
                    # New topic block starts a fresh sender group.
                    prev_sender_id = None
                    prev_msg_time = None
                prev_thread_id = msg_topic

            # ── Grouping ─────────────────────────────────────────────
            # A message's forum topic also bounds a sender group, so a topic
            # boundary never merges into the previous group (which would
            # mislabel it for the topic tabs).
            same_group = (
                current_group is not None
                and prev_sender_id == sender_id
                and current_group.get("topic") == msg_topic
                and current_group.get("comment_of") == comment_of
                and prev_msg_time is not None
                and msg_dt is not None
                and abs((msg_dt - prev_msg_time).total_seconds()) < 120
            )
            if not same_group:
                flush()
                current_group = {
                    "type": "group",
                    "is_outgoing": is_outgoing,
                    "sender_id": sender_id,
                    "sender_name": sender_name,
                    "sender_color": _sender_color(sender_name),
                    "initials": _sender_initials(sender_name),
                    "topic": msg_topic,
                    "topic_name": msg_topic_name,
                    "comment_of": comment_of,
                    "messages": [],
                }

            # ── Per-message render data ──────────────────────────────
            att_path = msg.get("attachment_path")
            att_cat: Optional[str] = None
            att_filename: Optional[str] = None
            poll_data: Optional[Dict[str, Any]] = None
            loc_lat: float = 0.0
            loc_lng: float = 0.0

            if att_path:
                # Normalize Windows backslashes to forward slashes
                att_path = att_path.replace("\\", "/")
                # Reject paths with traversal segments unconditionally
                if (
                    ".." in Path(att_path).parts
                    or Path(att_path).is_absolute()
                    or ":" in att_path
                ):
                    att_path = None
                # Also validate resolved path stays within attachments directory
                elif attachments_dir:
                    resolved = (attachments_dir / att_path).resolve()
                    try:
                        resolved.relative_to(attachments_dir.resolve())
                    except ValueError:
                        att_path = None
                if att_path:
                    parts_split = att_path.split("/")
                    att_cat = parts_split[0] if parts_split else None
                    att_filename = Path(att_path).name
                else:
                    att_cat = None
                    att_filename = None

            if att_path and att_cat:
                if att_cat == "polls" and attachments_dir:
                    poll_file = attachments_dir / att_path
                    if poll_file.exists():
                        try:
                            poll_data = json.loads(
                                poll_file.read_text(encoding="utf-8")
                            )
                        except Exception:
                            pass

                if att_cat == "locations" and att_filename:
                    try:
                        # filename: location_LAT_LNG.json or live_location_LAT_LNG.json
                        stem = att_filename.replace(".json", "")
                        coords = stem.rsplit("_", 2)
                        if len(coords) >= 3:
                            loc_lat = float(coords[-2])
                            loc_lng = float(coords[-1])
                    except Exception:
                        pass

            reply_text: Optional[str] = None
            reply_to_id: Optional[Any] = None
            parent_id = _reply_parent_id(msg)
            parent_msg = id_to_msg.get(parent_id) if parent_id is not None else None
            # Don't cite a parent that is the message's own topic root: the
            # forum topic header already shows it, so the citation is redundant.
            # Only applies to forums — elsewhere there is no header, so the root
            # reply is cited normally. Nested replies (parent != topic) still
            # cite their immediate parent.
            parent_is_thread_root = (
                is_forum and parent_id is not None and parent_id == msg_topic
            )
            # A channel comment is normalized to point at its parent post
            # (``comment_of``), and the render path already nests it under that
            # post. Citing the post inside every comment is redundant, so
            # suppress it — but only for channel comments, and only when the
            # cited parent is the post itself (a comment quoting another comment
            # is left untouched).
            parent_is_comment_post = (
                comment_of is not None
                and parent_id is not None
                and parent_id == comment_of
            )
            if parent_is_thread_root or parent_is_comment_post:
                # Suppress the citation; the topic header / comment nesting
                # already carries the parent's context.
                pass
            elif parent_msg is not None and parent_msg is not msg:
                # Parent is in the export: cite its first line and anchor to it.
                cited = first_line(parent_msg.get("message"))
                reply_to = msg.get("reply_to")
                if not cited and isinstance(reply_to, dict):
                    qt = reply_to.get("quote_text")
                    if qt:
                        cited = str(qt)[:150]
                reply_text = cited or f"Message #{parent_id}"
                reply_to_id = parent_id
            else:
                # Parent not in export: fall back to the stored quote text.
                reply_to = msg.get("reply_to")
                if isinstance(reply_to, dict):
                    qt = reply_to.get("quote_text")
                    if qt:
                        reply_text = str(qt)[:150]

            fwd_name: Optional[str] = None
            fwd_from = msg.get("fwd_from")
            if isinstance(fwd_from, dict):
                fwd_name = fwd_from.get("from_name") or "Unknown"

            current_group["messages"].append(
                {  # type: ignore[index]
                    "id": msg.get("id"),
                    "text": msg.get("message") or "",
                    "entities": msg.get("entities") or [],
                    "time": _fmt_time(date_str),
                    "edited": bool(msg.get("edit_date")),
                    "reply_text": reply_text,
                    "reply_to_id": reply_to_id,
                    "fwd_from_name": fwd_name,
                    "attachment_path": att_path,
                    "attachment_filename": att_filename,
                    "media_category": att_cat,
                    "poll_data": poll_data,
                    "location_lat": loc_lat,
                    "location_lng": loc_lng,
                }
            )

            prev_sender_id = sender_id
            prev_msg_time = msg_dt

        flush()

        # HTML only: fold channel-comment groups into collapsible blocks placed
        # right after their parent post. PDF (with_threads=False) keeps comments
        # inline since it cannot collapse them.
        if with_threads:
            items = _fold_comment_groups(items)
        return items


# ---------------------------------------------------------------------------
# Module-level pure helpers (no self needed)
# ---------------------------------------------------------------------------


def _fold_comment_groups(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fold channel-comment groups into collapsible per-post ``comments`` items.

    Each ``group`` item tagged with ``comment_of`` is a block of comments on a
    channel post. They are removed from the inline flow and re-emitted as a
    single ``comments`` item (carrying the comment count and the comment groups)
    placed right after the bubble group that contains the parent post. Comments
    whose parent post is absent from the export are appended at the end. Date
    separators left empty by the move are dropped.
    """
    comment_groups: Dict[Any, List[Dict[str, Any]]] = {}
    main_items: List[Dict[str, Any]] = []
    for it in items:
        if it.get("type") == "group" and it.get("comment_of") is not None:
            comment_groups.setdefault(it["comment_of"], []).append(it)
        else:
            main_items.append(it)

    if not comment_groups:
        return items

    def _block(post_id: Any, groups: List[Dict[str, Any]]) -> Dict[str, Any]:
        count = sum(len(g.get("messages", [])) for g in groups)
        return {
            "type": "comments",
            "post_id": post_id,
            "count": count,
            "groups": groups,
        }

    result: List[Dict[str, Any]] = []
    placed: set = set()
    for it in main_items:
        result.append(it)
        if it.get("type") != "group":
            continue
        for msg in it.get("messages", []):
            pid = msg.get("id")
            if pid in comment_groups and pid not in placed:
                result.append(_block(pid, comment_groups[pid]))
                placed.add(pid)

    # Parent post not present in the export — keep the comments at the end.
    for pid, groups in comment_groups.items():
        if pid not in placed:
            result.append(_block(pid, groups))
            placed.add(pid)

    return _drop_empty_date_separators(result)


def _drop_empty_date_separators(
    items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Remove date separators that no longer precede any visible content.

    Relocating comment groups can orphan a date separator that only headed
    comments; drop any separator with no group/service/comments/thread item
    before the next separator.
    """
    out: List[Dict[str, Any]] = []
    n = len(items)
    content = {"group", "service", "comments", "thread"}
    for i, it in enumerate(items):
        if it.get("type") == "date_sep":
            has_content = False
            for j in range(i + 1, n):
                t = items[j].get("type")
                if t == "date_sep":
                    break
                if t in content:
                    has_content = True
                    break
            if not has_content:
                continue
        out.append(it)
    return out


def _log(obj: Any) -> logging.Logger:
    return getattr(obj, "logger", logging.getLogger(__name__))


def _sender_color(name: str) -> str:
    idx = int(
        hashlib.md5(
            name.encode("utf-8", errors="replace"), usedforsecurity=False
        ).hexdigest(),
        16,
    )
    return AVATAR_COLORS[idx % len(AVATAR_COLORS)]


def _sender_initials(name: str) -> str:
    parts = name.strip().split()
    if not parts:
        return "?"
    first = parts[0][0] if parts[0] else ""
    last = parts[-1][0] if len(parts) > 1 and parts[-1] else ""
    return (first + last).upper() or "?"


def _parse_dt(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
    except Exception:
        return None


def _fmt_time(date_str: str) -> str:
    dt = _parse_dt(date_str)
    if not dt:
        return ""
    return dt.astimezone().strftime("%H:%M")


def _fmt_date_sep(date_str: str) -> str:
    dt = _parse_dt(date_str)
    if not dt:
        return date_str or ""
    # Convert to local timezone to stay consistent with _fmt_time
    dt = dt.astimezone()
    # "March 5, 2024" — no leading zero on day
    return dt.strftime("%B {day}, %Y").format(day=dt.day)


def _service_text(action: Dict[str, Any], msg: Dict[str, Any]) -> Optional[str]:
    action_type = action.get("_", "")
    label = ACTION_LABELS.get(action_type)
    if not label:
        return None
    sender = msg.get("user_display_name") or "Someone"
    if action_type == "MessageActionChatEditTitle":
        new_title = action.get("title") or action.get("new_title") or ""
        if new_title:
            label = f"changed the group name to \u201c{new_title}\u201d"
    return f"{sender} {label}"


def _xml_escape(text: str) -> str:
    """Escape for ReportLab Paragraph XML content."""
    # Strip control characters (except \n, \t) that break ReportLab's XML parser
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(text))
    return (
        cleaned.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# Inline entity formatting (#80) — shared by HTML and PDF
# ---------------------------------------------------------------------------

# URL schemes permitted in links; anything else (e.g. javascript:, data:) is
# dropped and the link text is rendered as plain text.
_ALLOWED_URL_SCHEMES = {"http", "https", "mailto", "tg"}

_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")


def _reply_parent_id(msg: Dict[str, Any]) -> Optional[Any]:
    """Return the id of the message this one replies to, or None."""
    reply_to = msg.get("reply_to")
    if isinstance(reply_to, dict):
        pid = reply_to.get("reply_to_msg_id")
        if pid is not None:
            return pid
    return msg.get("reply_to_msg_id")


def _thread_root(
    msg_id: Any,
    parent_of: Dict[Any, Any],
    id_to_msg: Dict[Any, Dict[str, Any]],
) -> Any:
    """Walk the reply chain to its root, following only in-export parents.

    Cycle-guarded: a reply loop stops at the first repeated id.
    """
    seen: set = set()
    cur = msg_id
    while True:
        if cur in seen:
            break
        seen.add(cur)
        parent = parent_of.get(cur)
        if parent is None or parent == cur or parent not in id_to_msg:
            break
        cur = parent
    return cur


def first_line(text: Optional[str], limit: int = 60) -> str:
    """Return the first non-empty line of ``text``, truncated to ``limit`` chars."""
    if not text:
        return ""
    line = str(text).split("\n", 1)[0].strip()
    if len(line) > limit:
        line = line[:limit].rstrip() + "…"
    return line


# Telegram service actions that carry a forum-topic title.
_TOPIC_TITLE_ACTIONS = ("MessageActionTopicCreate", "MessageActionTopicEdit")


def _forum_topic_id(msg: Dict[str, Any]) -> Optional[Any]:
    """Return the forum topic id a message belongs to, or None.

    Mirrors ``core/topics.py::_extract_topic_id``: prefer ``reply_to_top_id``,
    then ``reply_to_msg_id`` when the reply header is ``forum_topic``. A
    topic-create service message is its own topic. Grouping by this id — rather
    than the reply chain — keeps topics intact even when the topic-create
    message falls outside a windowed (e.g. ``--last-days``) download.
    """
    reply_to = msg.get("reply_to")
    # Only ``forum_topic`` replies identify a real forum topic. A bare
    # ``reply_to_top_id`` without ``forum_topic`` is a discussion sub-thread
    # (its top id is an ordinary message, not a topic), so it must NOT be
    # treated as a topic — those messages belong to the General topic.
    if isinstance(reply_to, dict) and reply_to.get("forum_topic"):
        top = reply_to.get("reply_to_top_id")
        if top is not None:
            return top
        rmid = reply_to.get("reply_to_msg_id")
        if rmid is not None:
            return rmid
    action = msg.get("action")
    if isinstance(action, dict) and action.get("_") in _TOPIC_TITLE_ACTIONS:
        return msg.get("id")
    return None


def _forum_topic_title(msg: Dict[str, Any]) -> str:
    """Best topic title known *from this message*: the stored
    ``forum_topic_title`` (fetched at download time), else a topic-create
    action title. Empty string when neither is available."""
    title = msg.get("forum_topic_title")
    if title:
        return first_line(title)
    action = msg.get("action")
    if isinstance(action, dict) and action.get("_") in _TOPIC_TITLE_ACTIONS:
        return first_line(action.get("title"))
    return ""


def _is_forum(messages: List[Dict[str, Any]]) -> bool:
    """True when the export comes from a forum supergroup (has topics).

    Detected by a topic-create/-edit service message or any reply header
    marked ``forum_topic``. Only forums show thread/topic headers; private
    chats and regular groups render replies via the inline citation alone.
    """
    for m in messages:
        if not isinstance(m, dict):
            continue
        action = m.get("action")
        if isinstance(action, dict) and action.get("_") in _TOPIC_TITLE_ACTIONS:
            return True
        reply_to = m.get("reply_to")
        if isinstance(reply_to, dict) and reply_to.get("forum_topic"):
            return True
    return False


def _thread_name(root_msg: Optional[Dict[str, Any]], root_id: Any) -> str:
    """Best display name for a reply-thread / forum-topic root.

    A forum topic's title lives on its ``MessageActionTopicCreate`` service
    message, not in any message text — prefer it. Otherwise fall back to the
    root message's first line, then ``Thread #<id>``.
    """
    if root_msg is not None:
        action = root_msg.get("action")
        if isinstance(action, dict) and action.get("_") in _TOPIC_TITLE_ACTIONS:
            title = first_line(action.get("title"))
            if title:
                return title
        line = first_line(root_msg.get("message"))
        if line:
            return line
    return f"Thread #{root_id}"


def _message_topic(
    mid: Any,
    thread_root: Dict[Any, Any],
    id_to_msg: Dict[Any, Dict[str, Any]],
) -> tuple:
    """Return ``(topic_id, topic_name)`` when the message belongs to a forum
    topic, else ``(None, None)``.

    A message belongs to a topic when its reply-chain root is a
    ``MessageActionTopicCreate`` service message (the topic id is that root's id
    and the name is its title). Messages outside any topic — the General topic
    or non-forum chats — return ``(None, None)``.
    """
    if mid is None:
        return (None, None)
    root = thread_root.get(mid, mid)
    root_msg = id_to_msg.get(root)
    if isinstance(root_msg, dict):
        action = root_msg.get("action")
        if isinstance(action, dict) and action.get("_") in _TOPIC_TITLE_ACTIONS:
            return (root, _thread_name(root_msg, root))
    return (None, None)


def _html_escape(text: str) -> str:
    """Escape text for HTML body content (keeps newlines intact)."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _escape_segment(text: str, dialect: str) -> str:
    """Escape a plain-text segment for the given dialect."""
    if dialect == "pdf":
        return _xml_escape(text).replace("\n", "<br/>")
    return _html_escape(text)


def _safe_href(url: Optional[str]) -> Optional[str]:
    """Return ``url`` if its scheme is allowlisted, else None (link is dropped)."""
    if not url:
        return None
    candidate = str(url).strip()
    if not candidate:
        return None
    # Reject embedded ASCII control characters (incl. the tab/newline/CR that
    # browsers strip when parsing a URL). Without this, "java\nscript:alert(1)"
    # has no scheme our regex can see, slips past the allowlist, and is emitted
    # as an href that the browser collapses back to "javascript:alert(1)".
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in candidate):
        return None
    match = _SCHEME_RE.match(candidate)
    if match and match.group(1).lower() not in _ALLOWED_URL_SCHEMES:
        return None
    return candidate


def _normalize_link_href(url: Optional[str]) -> Optional[str]:
    """Sanitize a link target for an ``href``.

    Telegram marks bare domains (e.g. ``example.com``) without a scheme; a
    schemeless href resolves relative to the local export file instead of
    opening the site, so default those to ``https://``. The result is then run
    through the scheme allowlist (:func:`_safe_href`).
    """
    if not url:
        return None
    candidate = str(url).strip()
    if not candidate:
        return None
    if not _SCHEME_RE.match(candidate):
        candidate = "https://" + candidate
    return _safe_href(candidate)


def _escape_attr(value: str, dialect: str) -> str:
    """Escape an attribute value (href) for the given dialect."""
    if dialect == "pdf":
        return _xml_escape(value)
    return _html_escape(value)


def _entity_tags(
    etype: str, ent: Dict[str, Any], dialect: str, span_text: str
) -> Optional[tuple]:
    """Map a Telegram entity type to (open_tag, close_tag) for the dialect.

    Returns ``None`` to skip the entity (unsupported, or a link with a
    disallowed scheme).
    """
    if etype == "MessageEntityBold":
        return ("<b>", "</b>")
    if etype == "MessageEntityItalic":
        return ("<i>", "</i>")
    if etype == "MessageEntityUnderline":
        return ("<u>", "</u>")
    if etype in ("MessageEntityStrike", "MessageEntityStrikethrough"):
        return ("<s>", "</s>") if dialect == "html" else ("<strike>", "</strike>")
    if etype in ("MessageEntityCode", "MessageEntityPre"):
        if dialect == "html":
            return ("<code>", "</code>")
        return (f'<font face="{_pdf_mono_font_face()}">', "</font>")
    if etype == "MessageEntitySpoiler":
        if dialect == "html":
            return ('<span class="spoiler">', "</span>")
        return ("", "")
    if etype == "MessageEntityTextUrl":
        href = _normalize_link_href(ent.get("url"))
        if not href:
            return None
        return (f'<a href="{_escape_attr(href, dialect)}">', "</a>")
    if etype in ("MessageEntityUrl", "MessageEntityEmail"):
        if etype == "MessageEntityEmail":
            href = _safe_href("mailto:" + span_text.strip())
        else:
            href = _normalize_link_href(span_text)
        if not href:
            return None
        return (f'<a href="{_escape_attr(href, dialect)}">', "</a>")
    # Unsupported entity types (mentions, hashtags, etc.) carry no formatting.
    return None


def _utf16_boundaries(text: str) -> Dict[int, int]:
    """Map UTF-16 code-unit offsets to Python string indices.

    Telegram entity offsets/lengths are measured in UTF-16 code units, so a
    character outside the BMP (e.g. an emoji) counts as 2.
    """
    boundaries: Dict[int, int] = {}
    u = 0
    for i, ch in enumerate(text):
        boundaries[u] = i
        u += 1 if ord(ch) <= 0xFFFF else 2
    boundaries[u] = len(text)
    return boundaries


def format_entities(
    text: Optional[str],
    entities: Optional[List[Dict[str, Any]]],
    dialect: str = "html",
) -> str:
    """Render ``text`` with inline Telegram ``entities`` for HTML or PDF.

    ``dialect`` is ``"html"`` or ``"pdf"``. Overlapping spans are wrapped
    segment-by-segment to guarantee well-formed nesting. HTML keeps literal
    ``\\n`` (the bubble uses ``white-space:pre-wrap``); PDF converts ``\\n``
    to ``<br/>``.
    """
    body = text or ""
    if dialect not in ("html", "pdf"):
        dialect = "html"
    if not entities:
        return _escape_segment(body, dialect)

    boundaries = _utf16_boundaries(body)
    n = len(body)
    spans: List[tuple] = []
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        etype = ent.get("_") or ent.get("type") or ""
        off = ent.get("offset")
        length = ent.get("length")
        if not isinstance(off, int) or not isinstance(length, int) or length <= 0:
            continue
        start = boundaries.get(off)
        # Clamp an entity that runs past the text end (Telethon offsets are
        # normally exact, but be defensive) to the last boundary rather than
        # dropping the whole span.
        end = boundaries.get(off + length, n)
        if start is None or start >= end:
            continue
        tags = _entity_tags(etype, ent, dialect, body[start:end])
        if tags is None:
            continue
        spans.append((start, end, tags[0], tags[1]))

    if not spans:
        return _escape_segment(body, dialect)

    points = sorted({0, n} | {s for s, _, _, _ in spans} | {e for _, e, _, _ in spans})
    out: List[str] = []
    for a, b in zip(points, points[1:]):
        if a >= b:
            continue
        segment = _escape_segment(body[a:b], dialect)
        active = [sp for sp in spans if sp[0] <= a and sp[1] >= b]
        # Outer (longer) spans wrap inner ones: sort by start asc, end desc.
        active.sort(key=lambda sp: (sp[0], -sp[1]))
        open_tags = "".join(sp[2] for sp in active)
        close_tags = "".join(sp[3] for sp in reversed(active))
        out.append(open_tags + segment + close_tags)
    return "".join(out)


# ---------------------------------------------------------------------------
# PDF rendering — module-level to keep RenderMixin clean
# ---------------------------------------------------------------------------


def _find_unicode_ttf() -> Optional[str]:
    """Find a Unicode-capable TTF font on the system.

    Prefers fonts with broad Unicode coverage (CJK, Cyrillic, emoji)
    over narrower fonts like DejaVu Sans.
    """
    candidates = [
        # Noto Sans CJK — best CJK + broad Unicode coverage
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
        # Noto Sans — good Unicode coverage (Cyrillic, Latin, Greek, etc.)
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        # DejaVu Sans — common on Linux, good Cyrillic but no CJK
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        # Liberation Sans
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/liberation-sans/LiberationSans-Regular.ttf",
        # macOS — Arial Unicode first (has CJK), then Helvetica (no CJK)
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        # Windows — CJK-capable fonts first
        "C:/Windows/Fonts/msyh.ttc",  # Microsoft YaHei — CJK
        "C:/Windows/Fonts/msgothic.ttc",  # MS Gothic — CJK
        "C:/Windows/Fonts/malgun.ttf",  # Malgun Gothic — Korean
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return path
    return None


def _find_unicode_ttf_bold() -> Optional[str]:
    """Find a bold variant of a Unicode-capable TTF font."""
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return path
    return None


def _find_unicode_ttf_oblique() -> Optional[str]:
    """Find an oblique/italic variant of a Unicode-capable TTF font."""
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSans-Italic.ttf",
        "/usr/share/fonts/noto/NotoSans-Italic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Oblique.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
        "/usr/share/fonts/liberation-sans/LiberationSans-Italic.ttf",
        "C:/Windows/Fonts/ariali.ttf",
        "C:/Windows/Fonts/segoeuii.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return path
    return None


def _find_unicode_mono_ttf() -> Optional[str]:
    """Find a Unicode-capable monospace TTF for PDF code spans.

    Built-in ReportLab ``Courier`` has no Cyrillic glyphs, so code spans with
    Cyrillic render as tofu. Prefer a real Unicode mono font when present.
    """
    candidates = [
        # DejaVu Sans Mono — broad Cyrillic/Latin coverage, common on Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        # Noto Sans Mono
        "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
        "/usr/share/fonts/noto/NotoSansMono-Regular.ttf",
        # Liberation Mono
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/liberation-mono/LiberationMono-Regular.ttf",
        # macOS
        "/System/Library/Fonts/Menlo.ttc",
        "/Library/Fonts/Courier New.ttf",
        # Windows — Consolas / Courier New both carry Cyrillic
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/cour.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return path
    return None


_font_cache: Optional[Dict[str, str]] = None

# Font face used for PDF code/pre spans. Defaults to the built-in ``Courier``
# (no Cyrillic) and is upgraded to a registered Unicode mono font by
# ``_register_unicode_fonts`` when one is available on the system.
_pdf_mono_face: str = "Courier"


def _pdf_mono_font_face() -> str:
    """Return the font face to use for PDF monospace (code) spans."""
    return _pdf_mono_face


def _register_unicode_fonts() -> Dict[str, str]:
    """Register Unicode TTF fonts with ReportLab. Returns font name mapping."""
    global _font_cache
    if _font_cache is not None:
        return _font_cache

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    logger = logging.getLogger(__name__)

    regular = _find_unicode_ttf()
    if not regular:
        logger.warning(
            "No Unicode TTF font found on system; PDF will use Helvetica "
            "(CJK, Cyrillic and emoji characters may render as tofu). "
            "Install fonts-noto or fonts-noto-cjk for full Unicode support."
        )
        _font_cache = {
            "regular": "Helvetica",
            "bold": "Helvetica-Bold",
            "oblique": "Helvetica-Oblique",
        }
        return _font_cache

    # Warn if the selected font has limited Unicode coverage (no CJK/emoji)
    _limited_fonts = {
        "DejaVuSans",
        "LiberationSans",
        "Helvetica",
        "arial",
        "segoeui",
    }
    font_basename = Path(regular).stem.replace("-Regular", "")
    if font_basename in _limited_fonts:
        logger.warning(
            f"Using {font_basename} for PDF — this font lacks CJK and emoji glyphs. "
            "Install fonts-noto-cjk for full Unicode support."
        )

    pdfmetrics.registerFont(TTFont("UnicodeSans", regular))
    font_map: Dict[str, str] = {
        "regular": "UnicodeSans",
        "bold": "UnicodeSans",
        "oblique": "UnicodeSans",
    }

    bold = _find_unicode_ttf_bold()
    if bold:
        pdfmetrics.registerFont(TTFont("UnicodeSans-Bold", bold))
        font_map["bold"] = "UnicodeSans-Bold"

    oblique = _find_unicode_ttf_oblique()
    if oblique:
        pdfmetrics.registerFont(TTFont("UnicodeSans-Oblique", oblique))
        font_map["oblique"] = "UnicodeSans-Oblique"

    # Monospace font for code/pre spans — Courier lacks Cyrillic glyphs.
    global _pdf_mono_face
    mono = _find_unicode_mono_ttf()
    if mono:
        pdfmetrics.registerFont(TTFont("UnicodeMono", mono))
        font_map["mono"] = "UnicodeMono"
        _pdf_mono_face = "UnicodeMono"
    else:
        font_map["mono"] = "Courier"
        _pdf_mono_face = "Courier"

    _font_cache = font_map
    return _font_cache


def _render_pdf_reportlab(
    mixin: Any,
    messages: List[Dict[str, Any]],
    output_file: Path,
    attachments_dir: Optional[Path],
    chat_title: str,
) -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import Image as RLImage
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        raise ImportError(
            "reportlab is required for PDF export. "
            "Install it with: pip install telegram-download-chat[export]"
        )

    fonts = _register_unicode_fonts()
    FONT = fonts["regular"]
    FONT_BOLD = fonts["bold"]
    FONT_OBLIQUE = fonts["oblique"]

    OWN_BG = colors.Color(0.851, 0.992, 0.827)  # #d9fdd3
    OTHER_BG = colors.white
    FWD_COLOR = colors.Color(0, 0.659, 0.518)  # #00a884
    PAGE_W, _ = A4
    MARGIN = 10 * mm
    USABLE_W = PAGE_W - 2 * MARGIN
    AV_COL_W = 10 * mm
    BUBBLE_MAX_W = USABLE_W * 0.72

    def style(**kw) -> ParagraphStyle:
        base = dict(fontSize=11, fontName=FONT, leading=14)
        base.update(kw)
        return ParagraphStyle("_", **base)

    s_title = style(fontSize=16, fontName=FONT_BOLD, spaceAfter=2)
    s_subtitle = style(fontSize=9, textColor=colors.grey, spaceAfter=8)
    s_datesep = style(
        fontSize=9,
        textColor=colors.grey,
        alignment=TA_CENTER,
        spaceBefore=6,
        spaceAfter=2,
    )
    s_service = style(
        fontSize=9,
        fontName=FONT_OBLIQUE,
        textColor=colors.grey,
        alignment=TA_CENTER,
        spaceAfter=2,
    )
    s_text = style(fontSize=11, spaceAfter=0)
    s_meta = style(fontSize=8, textColor=colors.grey, alignment=TA_RIGHT)
    s_fwd = style(fontSize=10, fontName=FONT_BOLD, textColor=FWD_COLOR, spaceAfter=2)
    s_reply = style(
        fontSize=9, fontName=FONT_OBLIQUE, textColor=colors.grey, spaceAfter=2
    )
    s_fname = style(fontSize=10, textColor=colors.darkblue)

    _sender_style_cache: Dict[str, ParagraphStyle] = {}
    _av_bg_cache: Dict[str, colors.Color] = {}

    def sender_style(hex_color: str) -> ParagraphStyle:
        if hex_color not in _sender_style_cache:
            hx = hex_color.lstrip("#")
            r, g, b = (
                int(hx[0:2], 16) / 255,
                int(hx[2:4], 16) / 255,
                int(hx[4:6], 16) / 255,
            )
            _sender_style_cache[hex_color] = style(
                fontSize=10,
                fontName=FONT_BOLD,
                textColor=colors.Color(r, g, b),
                spaceAfter=1,
            )
        return _sender_style_cache[hex_color]

    def av_bg_color(hex_color: str) -> colors.Color:
        if hex_color not in _av_bg_cache:
            hx = hex_color.lstrip("#")
            r, g, b = (
                int(hx[0:2], 16) / 255,
                int(hx[2:4], 16) / 255,
                int(hx[4:6], 16) / 255,
            )
            _av_bg_cache[hex_color] = colors.Color(r, g, b)
        return _av_bg_cache[hex_color]

    output_file.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_file),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )

    items = mixin._preprocess_messages(messages, attachments_dir)
    story = [
        Paragraph(_xml_escape(chat_title), s_title),
        Paragraph(
            f"{len(messages)} messages \u00b7 Exported by telegram-download-chat",
            s_subtitle,
        ),
    ]

    for item in items:
        if item["type"] == "date_sep":
            story.append(Spacer(1, 3 * mm))
            story.append(Paragraph(_xml_escape(item["label"]), s_datesep))

        elif item["type"] == "service":
            story.append(Paragraph(_xml_escape(item["text"]), s_service))
            story.append(Spacer(1, 1 * mm))

        elif item["type"] == "group":
            is_out: bool = item["is_outgoing"]
            bubble_bg = OWN_BG if is_out else OTHER_BG
            av_col = av_bg_color(item["sender_color"])

            for idx, msg_data in enumerate(item["messages"]):
                parts: List[Any] = []

                # Sender name (first incoming bubble in group only)
                if idx == 0 and not is_out:
                    parts.append(
                        Paragraph(
                            _xml_escape(item["sender_name"]),
                            sender_style(item["sender_color"]),
                        )
                    )

                if msg_data.get("fwd_from_name"):
                    parts.append(
                        Paragraph(
                            f"\u21b3 Forwarded from {_xml_escape(msg_data['fwd_from_name'])}",
                            s_fwd,
                        )
                    )

                if msg_data.get("reply_text"):
                    parts.append(
                        Paragraph(
                            _xml_escape(str(msg_data["reply_text"])[:100]).replace(
                                "\n", "<br/>"
                            ),
                            s_reply,
                        )
                    )

                # Media
                att_path = msg_data.get("attachment_path")
                att_cat = msg_data.get("media_category")
                if att_path and attachments_dir:
                    abs_path = attachments_dir / att_path
                    if att_cat in ("images", "stickers") and abs_path.exists():
                        try:
                            max_w = min(BUBBLE_MAX_W - 10 * mm, 110 * mm)
                            img = RLImage(
                                str(abs_path),
                                width=max_w,
                                height=max_w,
                                kind="proportional",
                            )
                            img.hAlign = "LEFT"
                            parts.append(img)
                        except Exception as exc:
                            _log(mixin).warning(
                                "Failed to load image %s: %s", abs_path, exc
                            )
                            parts.append(
                                Paragraph(
                                    f"[Image: {_xml_escape(msg_data.get('attachment_filename',''))}]",
                                    s_fname,
                                )
                            )
                    elif att_cat in (
                        "documents",
                        "archives",
                        "audio",
                        "videos",
                        "contacts",
                    ):
                        icons = {
                            "archives": "[ZIP]",
                            "audio": "[Audio]",
                            "videos": "[Video]",
                            "contacts": "[Contact]",
                        }
                        icon = icons.get(att_cat, "[File]")
                        parts.append(
                            Paragraph(
                                f"{icon} {_xml_escape(msg_data.get('attachment_filename',''))}",
                                s_fname,
                            )
                        )
                    elif att_cat == "locations":
                        parts.append(
                            Paragraph(
                                f"[Location] ({msg_data.get('location_lat',0):.4f}, "
                                f"{msg_data.get('location_lng',0):.4f})",
                                s_text,
                            )
                        )
                    elif att_cat == "polls" and msg_data.get("poll_data"):
                        pd = msg_data["poll_data"]
                        parts.append(
                            Paragraph(
                                f"[Poll] <b>{_xml_escape(pd.get('question',''))}</b>",
                                s_text,
                            )
                        )
                        for ans in pd.get("answers", []):
                            voters = (
                                f" ({ans['voters']})"
                                if ans.get("voters") is not None
                                else ""
                            )
                            parts.append(
                                Paragraph(
                                    f"  \u2022 {_xml_escape(ans.get('text',''))}{voters}",
                                    s_text,
                                )
                            )
                    else:
                        parts.append(
                            Paragraph(
                                f"[Attachment] {_xml_escape(msg_data.get('attachment_filename',''))}",
                                s_fname,
                            )
                        )

                text = msg_data.get("text") or ""
                if text:
                    parts.append(
                        Paragraph(
                            format_entities(text, msg_data.get("entities"), "pdf"),
                            s_text,
                        )
                    )

                tick = " \u2713\u2713" if is_out else ""
                edited = " (edited)" if msg_data.get("edited") else ""
                parts.append(Paragraph(f"{msg_data['time']}{edited}{tick}", s_meta))

                # Avatar cell — only shown on first message in group (incoming)
                if idx == 0 and not is_out:
                    av_cell: Any = Paragraph(
                        f"<b>{_xml_escape(item['initials'])}</b>",
                        style(
                            fontSize=9,
                            fontName=FONT_BOLD,
                            textColor=colors.white,
                            alignment=TA_CENTER,
                        ),
                    )
                    av_bg = av_col
                else:
                    av_cell = ""
                    av_bg = colors.white

                if is_out:
                    data = [["", parts]]
                    col_widths = [USABLE_W - BUBBLE_MAX_W, BUBBLE_MAX_W]
                    ts = TableStyle(
                        [
                            ("BACKGROUND", (1, 0), (1, 0), bubble_bg),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (1, 0), (1, 0), 8),
                            ("RIGHTPADDING", (1, 0), (1, 0), 8),
                            ("TOPPADDING", (1, 0), (1, 0), 6),
                            ("BOTTOMPADDING", (1, 0), (1, 0), 5),
                            ("LEFTPADDING", (0, 0), (0, 0), 0),
                            ("RIGHTPADDING", (0, 0), (0, 0), 0),
                        ]
                    )
                else:
                    data = [[av_cell, parts]]
                    col_widths = [AV_COL_W + 3 * mm, BUBBLE_MAX_W]
                    ts = TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (0, 0), av_bg),
                            ("BACKGROUND", (1, 0), (1, 0), bubble_bg),
                            ("VALIGN", (0, 0), (0, 0), "BOTTOM"),
                            ("VALIGN", (1, 0), (1, 0), "TOP"),
                            ("LEFTPADDING", (1, 0), (1, 0), 8),
                            ("RIGHTPADDING", (1, 0), (1, 0), 8),
                            ("TOPPADDING", (1, 0), (1, 0), 6),
                            ("BOTTOMPADDING", (1, 0), (1, 0), 5),
                            ("LEFTPADDING", (0, 0), (0, 0), 1),
                            ("RIGHTPADDING", (0, 0), (0, 0), 2),
                            ("TOPPADDING", (0, 0), (0, 0), 2),
                            ("BOTTOMPADDING", (0, 0), (0, 0), 2),
                        ]
                    )

                tbl = Table(data, colWidths=col_widths)
                tbl.setStyle(ts)
                story.append(tbl)
                story.append(Spacer(1, 1.5 * mm))

    doc.build(story)

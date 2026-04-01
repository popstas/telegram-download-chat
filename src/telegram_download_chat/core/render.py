"""HTML and PDF chat export rendering — Telegram Web light-theme style."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import BaseLoader, Environment

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
    "MessageActionPhoneCall": "\U0001f4de Phone call",
    "MessageActionGroupCall": "\U0001f4de Group call",
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
  display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:10;
  box-shadow:0 1px 3px rgba(0,0,0,0.08)}
.hdr-av{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-weight:700;font-size:18px;color:#fff;
  background:#168acd;flex-shrink:0}
.hdr-info .name{font-weight:600;font-size:16px}
.hdr-info .sub{font-size:12px;color:#999;margin-top:2px}
/* Messages area */
.msgs{flex:1;padding:16px 12px 32px;display:flex;flex-direction:column;gap:1px}
/* Date separator */
.datesep{text-align:center;margin:14px 0 10px;user-select:none}
.datesep span{background:rgba(0,0,0,0.22);color:#fff;border-radius:14px;
  padding:5px 14px;font-size:12px;font-weight:500}
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
  box-shadow:0 1px 2px rgba(0,0,0,0.14);position:relative;word-break:break-word;max-width:100%}
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
/* Media */
.media-img,.media-stk,.media-vid{display:block;border-radius:10px;margin-bottom:4px}
.media-img{max-width:100%;max-height:340px;object-fit:contain}
.media-stk{max-width:160px;max-height:160px}
.media-vid{max-width:100%;max-height:280px;width:100%}
.media-aud{width:260px;max-width:100%;margin-bottom:4px;display:block}
.media-file{display:flex;align-items:center;gap:10px;background:rgba(0,0,0,0.04);
  border-radius:10px;padding:8px 10px;margin-bottom:4px}
.media-file .ico{font-size:26px;line-height:1;flex-shrink:0}
.media-file .fname{font-size:13px;font-weight:500;color:#333;word-break:break-all}
.media-loc{margin-bottom:4px;font-size:13px}
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
  .bbl,.grp{break-inside:avoid;page-break-inside:avoid}
}
</style>
</head>
<body>
<div class="wrap">
<div class="hdr">
  <div class="hdr-av">{{ chat_title[0] | upper | e }}</div>
  <div class="hdr-info">
    <div class="name">{{ chat_title | e }}</div>
    <div class="sub">{{ message_count }} messages &middot; Exported by telegram-download-chat</div>
  </div>
</div>
<div class="msgs">
{%- for item in items %}
{%- if item.type == "date_sep" %}
<div class="datesep"><span>{{ item.label | e }}</span></div>
{%- elif item.type == "service" %}
<div class="svc"><span>{{ item.text | e }}</span></div>
{%- elif item.type == "group" %}
<div class="grp{% if item.is_outgoing %} out{% endif %}">
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
    <div class="bbl">
      {%- if msg.fwd_from_name %}
      <div class="fwd">&#8627; Forwarded from {{ msg.fwd_from_name | e }}</div>
      {%- endif %}
      {%- if msg.reply_text %}
      <div class="rq">{{ msg.reply_text | e }}</div>
      {%- endif %}
      {%- if msg.attachment_path %}
        {%- set src = "attachments/" + msg.attachment_path %}
        {%- if msg.media_category == "stickers" %}
        <img class="media-stk" src="{{ src }}" alt="sticker" loading="lazy">
        {%- elif msg.media_category == "images" %}
        <img class="media-img" src="{{ src }}" alt="" loading="lazy">
        {%- elif msg.media_category == "videos" %}
        <video class="media-vid" controls preload="none" src="{{ src }}"></video>
        {%- elif msg.media_category == "audio" %}
        <audio class="media-aud" controls preload="none" src="{{ src }}"></audio>
        {%- elif msg.media_category in ("documents", "archives") %}
        <div class="media-file">
          <div class="ico">{% if msg.media_category == "archives" %}&#128736;{% else %}&#128196;{% endif %}</div>
          <div class="fname">{{ msg.attachment_filename | e }}</div>
        </div>
        {%- elif msg.media_category == "contacts" %}
        <div class="media-file"><div class="ico">&#128100;</div><div class="fname">{{ msg.attachment_filename | e }}</div></div>
        {%- elif msg.media_category == "locations" %}
        <div class="media-loc">&#128205; <a href="https://maps.google.com/?q={{ msg.location_lat }},{{ msg.location_lng }}" target="_blank" rel="noopener">View on map</a></div>
        {%- elif msg.media_category == "polls" and msg.poll_data %}
        <div class="poll-wrap">
          <div class="poll-q">&#128202; {{ msg.poll_data.question | e }}</div>
          {%- for ans in msg.poll_data.answers %}
          <div class="poll-opt"><span>{{ ans.text | e }}</span>{% if ans.voters is not none %}<span class="votes">{{ ans.voters }}</span>{% endif %}</div>
          {%- endfor %}
          {%- if msg.poll_data.total_voters is not none %}
          <div class="poll-total">{{ msg.poll_data.total_voters }} total votes</div>
          {%- endif %}
        </div>
        {%- endif %}
      {%- endif %}
      {%- if msg.text %}
      <div class="txt">{{ msg.text | e }}</div>
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
{%- endif %}
{%- endfor %}
</div>
</div>
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
    ) -> None:
        """Render messages as a Telegram Web-style self-contained HTML file."""
        items = self._preprocess_messages(messages, attachments_dir)
        env = Environment(loader=BaseLoader(), autoescape=False)
        tmpl = env.from_string(HTML_TEMPLATE)
        html = tmpl.render(
            chat_title=chat_title,
            message_count=len(messages),
            items=items,
        )
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(html, encoding="utf-8")
        _log(self).info(f"Saved HTML export → {output_file.name}")

    def render_pdf(
        self,
        messages: List[Dict[str, Any]],
        output_file: Path,
        attachments_dir: Optional[Path] = None,
        chat_title: str = "Chat",
    ) -> None:
        """Render messages as a PDF document using ReportLab."""
        try:
            _render_pdf_reportlab(self, messages, output_file, attachments_dir, chat_title)
        except Exception as exc:
            _log(self).error(f"PDF export failed: {exc}")
            raise

    # ------------------------------------------------------------------
    # Message preprocessing — shared by HTML and PDF
    # ------------------------------------------------------------------

    def _preprocess_messages(
        self,
        messages: List[Dict[str, Any]],
        attachments_dir: Optional[Path],
    ) -> List[Dict[str, Any]]:
        """Convert flat message list into structured render items."""
        items: List[Dict[str, Any]] = []
        current_group: Optional[Dict[str, Any]] = None
        prev_date: Optional[str] = None
        prev_sender_id: Any = None
        prev_msg_time: Optional[datetime] = None

        sorted_msgs = sorted(messages, key=lambda m: m.get("date") or "")

        def flush() -> None:
            nonlocal current_group
            if current_group is not None:
                items.append(current_group)
                current_group = None

        self_id = getattr(self, "_self_id", None)

        for msg in sorted_msgs:
            date_str = msg.get("date") or ""
            msg_dt = _parse_dt(date_str)
            msg_date = msg_dt.strftime("%Y-%m-%d") if msg_dt else None

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
                    items.append({"type": "service", "text": svc})
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
            else:
                sender_id = 0

            is_outgoing = bool(msg.get("out")) or (
                self_id is not None and sender_id == self_id
            )
            sender_name = msg.get("user_display_name") or str(sender_id) or "Unknown"

            # ── Grouping ─────────────────────────────────────────────
            same_group = (
                current_group is not None
                and prev_sender_id == sender_id
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
                parts = att_path.split("/")
                att_cat = parts[0] if parts else None
                att_filename = Path(att_path).name

                if att_cat == "polls" and attachments_dir:
                    poll_file = attachments_dir / att_path
                    if poll_file.exists():
                        try:
                            poll_data = json.loads(poll_file.read_text(encoding="utf-8"))
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
            reply_to = msg.get("reply_to")
            if isinstance(reply_to, dict):
                qt = reply_to.get("quote_text")
                if qt:
                    reply_text = str(qt)[:150]

            fwd_name: Optional[str] = None
            fwd_from = msg.get("fwd_from")
            if isinstance(fwd_from, dict):
                fwd_name = fwd_from.get("from_name") or "Unknown"

            current_group["messages"].append({  # type: ignore[index]
                "id": msg.get("id"),
                "text": msg.get("message") or "",
                "time": _fmt_time(date_str),
                "edited": bool(msg.get("edit_date")),
                "reply_text": reply_text,
                "fwd_from_name": fwd_name,
                "attachment_path": att_path,
                "attachment_filename": att_filename,
                "media_category": att_cat,
                "poll_data": poll_data,
                "location_lat": loc_lat,
                "location_lng": loc_lng,
            })

            prev_sender_id = sender_id
            prev_msg_time = msg_dt

        flush()
        return items

    # ------------------------------------------------------------------
    # Private helpers (instance methods for color/initials)
    # ------------------------------------------------------------------

    def _sender_color(self, name: str) -> str:
        return _sender_color(name)

    def _sender_initials(self, name: str) -> str:
        return _sender_initials(name)


# ---------------------------------------------------------------------------
# Module-level pure helpers (no self needed)
# ---------------------------------------------------------------------------

def _log(obj: Any) -> logging.Logger:
    return getattr(obj, "logger", logging.getLogger(__name__))


def _sender_color(name: str) -> str:
    idx = int(hashlib.md5(name.encode("utf-8", errors="replace")).hexdigest(), 16)
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
    return dt.astimezone(timezone.utc).strftime("%H:%M")


def _fmt_date_sep(date_str: str) -> str:
    dt = _parse_dt(date_str)
    if not dt:
        return date_str or ""
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
            label = f'changed the group name to \u201c{new_title}\u201d'
    return f"{sender} {label}"


def _xml_escape(text: str) -> str:
    """Escape for ReportLab Paragraph XML content."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# PDF rendering — module-level to keep RenderMixin clean
# ---------------------------------------------------------------------------

def _render_pdf_reportlab(
    mixin: Any,
    messages: List[Dict[str, Any]],
    output_file: Path,
    attachments_dir: Optional[Path],
    chat_title: str,
) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image as RLImage,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    OWN_BG = colors.Color(0.851, 0.992, 0.827)   # #d9fdd3
    OTHER_BG = colors.white
    FWD_COLOR = colors.Color(0, 0.659, 0.518)     # #00a884
    PAGE_W, _ = A4
    MARGIN = 10 * mm
    USABLE_W = PAGE_W - 2 * MARGIN
    AV_COL_W = 10 * mm
    BUBBLE_MAX_W = USABLE_W * 0.72

    def style(**kw) -> ParagraphStyle:
        base = dict(fontSize=11, fontName="Helvetica", leading=14)
        base.update(kw)
        return ParagraphStyle("_", **base)

    s_title = style(fontSize=16, fontName="Helvetica-Bold", spaceAfter=2)
    s_subtitle = style(fontSize=9, textColor=colors.grey, spaceAfter=8)
    s_datesep = style(fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceBefore=6, spaceAfter=2)
    s_service = style(fontSize=9, fontName="Helvetica-Oblique", textColor=colors.grey, alignment=TA_CENTER, spaceAfter=2)
    s_text = style(fontSize=11, spaceAfter=0)
    s_meta = style(fontSize=8, textColor=colors.grey, alignment=TA_RIGHT)
    s_fwd = style(fontSize=10, fontName="Helvetica-Bold", textColor=FWD_COLOR, spaceAfter=2)
    s_reply = style(fontSize=9, fontName="Helvetica-Oblique", textColor=colors.grey, spaceAfter=2)
    s_fname = style(fontSize=10, textColor=colors.darkblue)

    def sender_style(hex_color: str) -> ParagraphStyle:
        hx = hex_color.lstrip("#")
        r, g, b = int(hx[0:2], 16) / 255, int(hx[2:4], 16) / 255, int(hx[4:6], 16) / 255
        return style(fontSize=10, fontName="Helvetica-Bold", textColor=colors.Color(r, g, b), spaceAfter=1)

    def av_bg_color(hex_color: str) -> colors.Color:
        hx = hex_color.lstrip("#")
        r, g, b = int(hx[0:2], 16) / 255, int(hx[2:4], 16) / 255, int(hx[4:6], 16) / 255
        return colors.Color(r, g, b)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_file), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
    )

    items = mixin._preprocess_messages(messages, attachments_dir)
    story = [
        Paragraph(_xml_escape(chat_title), s_title),
        Paragraph(f"{len(messages)} messages \u00b7 Exported by telegram-download-chat", s_subtitle),
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
                    parts.append(Paragraph(_xml_escape(item["sender_name"]), sender_style(item["sender_color"])))

                if msg_data.get("fwd_from_name"):
                    parts.append(Paragraph(
                        f"\u21b3 Forwarded from {_xml_escape(msg_data['fwd_from_name'])}", s_fwd))

                if msg_data.get("reply_text"):
                    parts.append(Paragraph(_xml_escape(str(msg_data["reply_text"])[:100]), s_reply))

                # Media
                att_path = msg_data.get("attachment_path")
                att_cat = msg_data.get("media_category")
                if att_path and attachments_dir:
                    abs_path = attachments_dir / att_path
                    if att_cat in ("images", "stickers") and abs_path.exists():
                        try:
                            max_w = min(BUBBLE_MAX_W - 10 * mm, 110 * mm)
                            img = RLImage(str(abs_path), width=max_w, height=max_w * 0.6)
                            img.hAlign = "LEFT"
                            parts.append(img)
                        except Exception:
                            parts.append(Paragraph(
                                f"[Image: {_xml_escape(msg_data.get('attachment_filename',''))}]", s_fname))
                    elif att_cat in ("documents", "archives", "audio", "videos", "contacts"):
                        icons = {"archives": "\U0001f5dc", "audio": "\U0001f3b5",
                                 "videos": "\U0001f3ac", "contacts": "\U0001f464"}
                        icon = icons.get(att_cat, "\U0001f4c4")
                        parts.append(Paragraph(
                            f"{icon} {_xml_escape(msg_data.get('attachment_filename',''))}", s_fname))
                    elif att_cat == "locations":
                        parts.append(Paragraph(
                            f"\U0001f4cd Location ({msg_data.get('location_lat',0):.4f}, "
                            f"{msg_data.get('location_lng',0):.4f})", s_text))
                    elif att_cat == "polls" and msg_data.get("poll_data"):
                        pd = msg_data["poll_data"]
                        parts.append(Paragraph(
                            f"\U0001f4ca <b>{_xml_escape(pd.get('question',''))}</b>", s_text))
                        for ans in pd.get("answers", []):
                            voters = f" ({ans['voters']})" if ans.get("voters") is not None else ""
                            parts.append(Paragraph(
                                f"  \u2022 {_xml_escape(ans.get('text',''))}{voters}", s_text))

                text = msg_data.get("text") or ""
                if text:
                    parts.append(Paragraph(_xml_escape(text), s_text))

                tick = " \u2713\u2713" if is_out else ""
                edited = " (edited)" if msg_data.get("edited") else ""
                parts.append(Paragraph(f"{msg_data['time']}{edited}{tick}", s_meta))

                if not parts:
                    parts.append(Spacer(1, 2 * mm))

                # Avatar cell — only shown on first message in group (incoming)
                if idx == 0 and not is_out:
                    av_cell: Any = Paragraph(
                        f"<b>{_xml_escape(item['initials'])}</b>",
                        style(fontSize=9, fontName="Helvetica-Bold",
                              textColor=colors.white, alignment=TA_CENTER)
                    )
                    av_bg = av_col
                else:
                    av_cell = ""
                    av_bg = colors.white

                if is_out:
                    data = [["", parts]]
                    col_widths = [USABLE_W - BUBBLE_MAX_W, BUBBLE_MAX_W]
                    ts = TableStyle([
                        ("BACKGROUND", (1, 0), (1, 0), bubble_bg),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (1, 0), (1, 0), 8),
                        ("RIGHTPADDING", (1, 0), (1, 0), 8),
                        ("TOPPADDING", (1, 0), (1, 0), 6),
                        ("BOTTOMPADDING", (1, 0), (1, 0), 5),
                        ("LEFTPADDING", (0, 0), (0, 0), 0),
                        ("RIGHTPADDING", (0, 0), (0, 0), 0),
                    ])
                else:
                    data = [[av_cell, parts]]
                    col_widths = [AV_COL_W + 3 * mm, BUBBLE_MAX_W]
                    ts = TableStyle([
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
                    ])

                tbl = Table(data, colWidths=col_widths)
                tbl.setStyle(ts)
                story.append(tbl)
                story.append(Spacer(1, 1.5 * mm))

    doc.build(story)
    _log(mixin).info(f"Saved PDF export \u2192 {output_file.name}")

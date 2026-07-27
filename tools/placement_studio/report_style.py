"""Turning the studio's plain-text panels into something readable at a glance.

The Inspector and the pending-changes list were both a wall of monospaced text. Everything
in them is useful, but nothing in them is *findable*: a socket name, its parent bone, the
rows that use it and the warnings all render identically, so reading either means reading
all of it.

These helpers add the structure the text always implied — headings, indentation, and colour
carrying meaning rather than decoration. Only three colours are used, and each one means one
thing: a name, a number, or a problem.
"""

from __future__ import annotations

from html import escape
from typing import Iterable, List

#: Deliberately few. Colour that means nothing is noise, and these panels are read against
#: both the dark and light palettes the app can run under.
NAME = "#7fb2e8"      # a socket, a bone, a file — something you could look up
VALUE = "#c9a3e8"     # a count or a measurement
WARN = "#e8a33c"      # something that needs attention
GOOD = "#78dc8c"      # something confirmed fine
MUTED = "#98a2b3"     # commentary

#: Qt's rich-text engine supports only a small CSS subset and ignores class selectors in a
#: <style> block, so every colour is written onto the element itself. Verified by reading
#: `toHtml()` back: with classes, none of the colours survived.
_PATH = f"color:{NAME}; font-weight:bold;"
_OP = f"color:{MUTED}; margin-left:18px;"
_TIER = f"color:{VALUE}; font-weight:bold;"
_WARN = f"color:{WARN};"
_KEY = f"color:{MUTED};"
_VAL = f"color:{VALUE};"
_STYLE = ""


def _tier_of(line: str) -> str:
    """The `[B]`/`[A2]` marker a plan line opens with, if any."""

    stripped = line.strip()
    if stripped.startswith("[") and "]" in stripped:
        return stripped[1:stripped.index("]")]
    return ""


def pending_changes_html(header: Iterable[str], lines: Iterable[str]) -> str:
    """The pending-changes panel: one block per file, its operations indented beneath.

    `EditSession.diff` already emits a file path followed by its indented operations; this
    keeps that shape and makes it visible, so the answer to "what am I about to write?" is
    the list of bold paths rather than a paragraph.
    """

    out: List[str] = [_STYLE]
    summary = [escape(item) for item in header if item.strip()]
    if summary:
        head, *rest = summary
        out.append(f"<p><span style='{_VAL}'>{head}</span>")
        for item in rest:
            out.append(f"<br><span style='{_KEY}'>{item}</span>")
        out.append("</p>")
    body: List[str] = []
    for line in lines:
        if not line.strip():
            continue
        if not line.startswith(" "):
            body.append(f"<p style='{_PATH}'>{escape(line)}</p>")
            continue
        tier = _tier_of(line)
        text = escape(line.strip())
        if tier:
            text = text.replace(
                f"[{tier}]", f"<span style='{_TIER}'>[{tier}]</span>", 1
            )
        body.append(f"<div style='{_OP}'>{text}</div>")
    if not body:
        body.append(f"<p style='{_KEY}'>Nothing has been changed yet.</p>")
    out.extend(body)
    return "".join(out)


def inspector_html(text: str) -> str:
    """The Inspector: headings for its sections, and `key: value` split into two colours.

    The panel is generated as plain text elsewhere and that stays the source of truth — this
    only formats it, so a change to what the Inspector *says* needs no change here.
    """

    out: List[str] = [_STYLE]
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            out.append("<div style='height:6px'></div>")
            continue
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith(("warning", "dangling", "no ", "not ")):
            out.append(f"<div style='{_WARN}'>{escape(stripped)}</div>")
            continue
        # A line with no leading space and no colon reads as a heading.
        if not line.startswith(" ") and ":" not in stripped:
            out.append(f"<h3 style='{_PATH}'>{escape(stripped)}</h3>")
            continue
        if ":" in stripped:
            key, _sep, value = stripped.partition(":")
            indent = "margin-left:18px;" if line.startswith(" ") else ""
            out.append(
                f"<div style='{indent}'><span style='{_KEY}'>{escape(key)}:</span> "
                f"<span style='{_VAL}'>{escape(value.strip())}</span></div>"
            )
            continue
        out.append(f"<div style='{_KEY} margin-left:18px'>{escape(stripped)}</div>")
    return "".join(out)

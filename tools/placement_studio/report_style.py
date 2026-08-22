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


def operation_scope_html(operations, loose_count: int = 0) -> str:
    """The pending-changes panel's own account of *which operation* each change belongs to.

    The panel listed files and edits, so a session with three operations in it read as one
    undifferentiated set of pending changes — which is exactly the reading that made packaging
    the whole session look reasonable. One block per operation, newest last, with the counts
    the review and the package report use, and the free-form edits called out as never packaged.
    """

    out: List[str] = []
    operations = list(operations)
    if not operations and not loose_count:
        return ""
    out.append(f"<p style='{_PATH}'>Operations</p>")
    for operation in operations:
        label = escape(operation.label or operation.kind)
        out.append(f"<div style='{_OP}'><span style='{_TIER}'>{label}</span>")
        detail = ", ".join(
            f"{count} {name}" for name, count in operation.counts().items() if count
        )
        if detail:
            out.append(f"<br><span style='{_KEY}'>{escape(detail)}</span>")
        if operation.warnings_accepted:
            for warning in operation.warnings_accepted:
                out.append(f"<br><span style='{_WARN}'>{escape(warning)}</span>")
        out.append("</div>")
    if loose_count:
        out.append(
            f"<div style='{_OP}'><span style='{_WARN}'>"
            f"{loose_count} free-form edit(s) outside any operation</span>"
            f"<br><span style='{_KEY}'>never packaged; use Start clean operation to drop them"
            f"</span></div>"
        )
    return "".join(out)


def package_scope_html(summary, errors=(), warnings=()) -> str:
    """A package scope summary, its blockers and its confirmations, as one readable block.

    The same facts `PackageScopeSummary.render` prints, laid out so a blocker is findable: an
    error a reviewer has to scan a paragraph for is an error they will not read.
    """

    out: List[str] = [_STYLE]
    errors, warnings = list(errors), list(warnings)
    if errors:
        out.append(f"<p style='{_PATH}'>Package blocked</p>")
        for item in errors:
            text = item.describe() if hasattr(item, "describe") else str(item)
            out.append(f"<div style='{_OP}'><span style='{_WARN}'>{escape(text)}</span></div>")
    if warnings:
        out.append(f"<p style='{_PATH}'>Confirm before continuing</p>")
        for item in warnings:
            text = item.describe() if hasattr(item, "describe") else str(item)
            out.append(f"<div style='{_OP}'><span style='{_WARN}'>{escape(text)}</span></div>")
    if summary is None:
        return "".join(out)

    def row(key: str, value: object) -> None:
        out.append(
            f"<div style='{_OP}'><span style='{_KEY}'>{escape(key)}:</span> "
            f"<span style='{_VAL}'>{escape(str(value) or '-')}</span></div>"
        )

    out.append(f"<p style='{_PATH}'>Package scope</p>")
    row("Operations", ", ".join(summary.operations) or "-")
    row("Equipment", ", ".join(summary.equipment_units) or "-")
    row("Linked parts", ", ".join(summary.linked_parts) or "-")
    row("Destination", summary.destination or "-")
    row("Descriptor rows changed", len(summary.descriptor_parts))
    row("Socket files changed", len(summary.socket_files_changed))
    row("New child sockets", len(summary.created_sockets))
    row("Shared sockets modified in place", len(summary.shared_sockets_modified))
    if summary.animation_targets:
        out.append(f"<p style='{_PATH}'>Animation target families</p>")
        for name, count in summary.animation_targets.items():
            row(name, count)
    if summary.animation_donors:
        out.append(f"<p style='{_PATH}'>Animation donor families</p>")
        for name, count in summary.animation_donors.items():
            row(name, count)
    if summary.borrowed_count or summary.mounted_count:
        row("Borrowed-character clips", summary.borrowed_count)
        row("Mounted clips", summary.mounted_count)
    if summary.orientation_sources:
        out.append(f"<p style='{_PATH}'>Orientation sources</p>")
        for name, source in summary.orientation_sources:
            row(name, source)
    row("Excluded earlier operations", len(summary.excluded_operations))
    if summary.loose_edits:
        row("Excluded free-form edits", summary.loose_edits)
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

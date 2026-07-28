"""What can I actually mod, and where in this app do I do it?

The capability manifest answers the first half precisely — 141 formats, each with how
far it is read, how far it is written, and what is left. But it is a JSON file in a
schemas directory, so the person it would help most has never seen it.

This module turns it into rows a modder can act on, and adds the part the manifest does
not carry: which tool in the app handles a format. A row that says `.paloc` is
read/write is only useful next to "Translation Studio".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "schemas" / "archive_content_capabilities.v1.json"

#: Where a format is edited. Keyed by extension; the manifest deliberately does not
#: carry this, because it is a property of the app rather than of the format.
TOOLS: Mapping[str, str] = {
    ".paloc": "Translation Studio",
    ".dds": "Texture Workflow",
    ".png": "Texture Workflow",
    ".pac": "Mesh Editor",
    ".pam": "Mesh Editor",
    ".pamlod": "Mesh Editor",
    ".pac_xml": "Material sidecar editor",
    ".pam_xml": "Material sidecar editor",
    ".pamlod_xml": "Material sidecar editor",
    ".pami": "Material sidecar editor",
    ".prefab": "Prefab Inspector",
    ".hkx": "HKX editor",
    ".hkt": "HKX editor",
    ".paa": "Placement & Animation Studio",
    ".pab": "Placement & Animation Studio",
    ".paac": "Placement & Animation Studio",
    ".papr": "Placement Studio - Driven bones",
    ".wem": "Archive Browser (audio replace)",
}

#: Formats edited as plain text through any editor, once extracted.
_TEXT_TOOL = "Any text editor (extract, edit, repack)"
_NO_TOOL = "No tool yet"

#: How the manifest's decode/write words read to someone who has not seen the rubric.
READ_WORDS = {
    "full": "Fully read",
    "partial": "Partly read",
    "surface": "Names only",
    "none": "Not read",
}
WRITE_WORDS = {
    "full": "Can write",
    "constrained": "Limited edits",
    "none": "Read-only",
}


@dataclass(frozen=True)
class FormatRow:
    extension: str
    files: int
    group: str
    role: str
    decode: str
    write: str
    priority: str
    origin: str
    evidence: str
    remaining: str
    tool: str

    @property
    def read_label(self) -> str:
        return READ_WORDS.get(self.decode, self.decode)

    @property
    def write_label(self) -> str:
        return WRITE_WORDS.get(self.write, self.write)

    @property
    def moddable(self) -> bool:
        """Something a modder can change today, in a format the game actually ships."""

        return self.files > 0 and self.write in ("full", "constrained")

    @property
    def shipped(self) -> bool:
        return self.files > 0


def _tool_for(entry: Mapping[str, object]) -> str:
    extension = str(entry["extension"])
    if extension in TOOLS:
        return TOOLS[extension]
    if entry["write"] == "full" and entry["container"] == "text":
        return _TEXT_TOOL
    return _NO_TOOL


def load_rows(manifest: Optional[Path] = None) -> Tuple[FormatRow, ...]:
    document = json.loads((manifest or MANIFEST).read_text(encoding="utf-8"))
    rows = []
    for entry in document["extensions"]:
        rows.append(FormatRow(
            extension=str(entry["extension"]),
            files=int(entry["archive_files"]),
            group=str(entry["group"]),
            role=str(entry["role"]),
            decode=str(entry["decode"]),
            write=str(entry["write"]),
            priority=str(entry["priority"]),
            origin=str(entry["origin"]),
            evidence=str(entry["evidence"]),
            remaining=str(entry["remaining"]),
            tool=_tool_for(entry),
        ))
    # Most files first: that is the order in which a format matters to a modder.
    rows.sort(key=lambda row: (-row.files, row.extension))
    return tuple(rows)


def headline(rows: Sequence[FormatRow]) -> str:
    """One sentence a modder can act on, computed rather than written down."""

    shipped = [row for row in rows if row.shipped]
    editable = [row for row in shipped if row.moddable]
    files_total = sum(row.files for row in shipped)
    files_editable = sum(row.files for row in editable)
    share = (100.0 * files_editable / files_total) if files_total else 0.0
    return (
        f"The game ships {len(shipped)} file formats and {files_total:,} files. "
        f"{len(editable)} of those formats can be edited today, covering "
        f"{files_editable:,} files ({share:.0f}% of everything in the archives)."
    )


def filter_rows(
    rows: Sequence[FormatRow],
    needle: str = "",
    *,
    editable_only: bool = False,
    shipped_only: bool = True,
    group: Optional[str] = None,
) -> Tuple[FormatRow, ...]:
    wanted = needle.strip().casefold()
    out = []
    for row in rows:
        if shipped_only and not row.shipped:
            continue
        if editable_only and not row.moddable:
            continue
        if group and row.group != group:
            continue
        if wanted and wanted not in (
            f"{row.extension} {row.group} {row.role} {row.tool} {row.evidence}".casefold()
        ):
            continue
        out.append(row)
    return tuple(out)


def groups(rows: Sequence[FormatRow]) -> Tuple[str, ...]:
    return tuple(sorted({row.group for row in rows}))

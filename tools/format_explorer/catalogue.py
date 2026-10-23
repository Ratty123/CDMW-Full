"""Archive inventory and current application workflows for Format Explorer.

Archive fields retain the manifest's meaning. Application-only formats and operation
guidance are added to immutable display rows without changing runtime archive rules.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence, Tuple

from .workflows import FormatWorkflow, workflow_for

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "schemas" / "archive_content_capabilities.v1.json"


def detail_text_segments(text: str) -> tuple[str, ...]:
    """Keep long research notes within the language-file key limit.

    Preserve every space so the English text and source evidence stay intact.
    Ordinary labels and paragraphs keep their existing single catalog key.
    """
    if len(text) <= 3500:
        return (text,)
    pieces = []
    while len(text) > 800:
        stops = [match.end() for match in re.finditer(r"[.!?] +", text[:800])]
        cut = stops[-1] if stops else text.rfind(" ", 0, 800) + 1
        if not cut:
            cut = 800
        pieces.append(text[:cut])
        text = text[cut:]
    pieces.append(text)
    return tuple(pieces)

#: Where a format is edited, as a path a person can follow: every segment is the
#: label the interface actually draws — a tab name, or a context-menu action under
#: Archive Browser. Keyed by extension; the manifest deliberately does not carry
#: this, because it is a property of the app rather than of the format.
#: Update these paths when renaming a tool or an action in the interface.
TOOLS: Mapping[str, str] = {
    ".paloc": "Utilities > Edit Translations",
    ".dds": "Textures",
    ".png": "Textures",
    ".pac": "Mesh Editor",
    ".pam": "Mesh Editor",
    ".pamlod": "Mesh Editor",
    ".prefab": "Browse Archives > Open Prefab Inspector...",
    ".hkx": "Browse Archives > Edit HKX...",
    ".hkt": "Browse Archives > Edit HKX...",
    ".paa": "Placement & Animations",
    ".pab": "Placement & Animations",
    ".paac": "Placement & Animations",
    ".papr": "Placement & Animations > Driven bones",
    ".wem": "Browse Archives > Import WAV + Patch to Game...",
    ".paseq": "Browse Archives > Edit Structured Data Safely...",
    ".paseqc": "Browse Archives > Edit Structured Data Safely...",
    ".pastage": "Browse Archives > Edit Structured Data Safely...",
    ".pabgh": "Browse Archives > Edit Structured Data Safely...",
    ".pae": "Create New Item > Effects",
    ".paem": "Create New Item > Effects",
    ".pappt": "Create New Item",
    ".pathc": "Create New Item",
    ".pabgb": "Create New Item",
    ".fbx": "Create New Item / Mesh Editor",
    ".glb": "Mesh Editor / Create New Item",
    ".gltf": "Mesh Editor / Create New Item",
    ".obj": "Mesh Editor / Create New Item",
    ".dae": "Mesh Editor / Create New Item",
    ".cditem": "Create New Item / Mod Management",
}

#: Formats edited as plain text through any editor, once extracted.
_TEXT_TOOL = "Any text editor (extract, edit, repack)"
_NO_TOOL = "No tool yet"
NO_REMAINING_NOTE = "No additional limits recorded here."
_HEADLINE = (
    "Browse {count} formats from the stored archive inventory. "
    "Include application and non-shipped formats to see other supported workflows. "
    "Counts are not a live installation scan."
)

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
    files: int | None
    group: str
    role: str
    decode: str
    write: str
    priority: str
    origin: str
    evidence: str
    remaining: str
    tool: str
    workflow: FormatWorkflow = FormatWorkflow()

    @property
    def read_label(self) -> str:
        return self.workflow.read_label or READ_WORDS.get(self.decode, self.decode)

    @property
    def write_label(self) -> str:
        return self.workflow.write_label or WRITE_WORDS.get(self.write, self.write)

    @property
    def moddable(self) -> bool:
        """A supported edit route, independent of presence in the stored inventory."""

        if self.workflow.editable is not None:
            return self.workflow.editable
        return self.write in ("full", "constrained")

    @property
    def shipped(self) -> bool:
        return self.files is not None and self.files > 0


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
            workflow=workflow_for(str(entry["extension"])),
        ))
    # A package is not an archive entry. None means the count does not apply;
    # zero remains the known absence of an archive extension in the inventory.
    if not any(row.extension == ".cditem" for row in rows):
        rows.append(FormatRow(
            extension=".cditem", files=None, group="application_packages",
            role="Independent item / mod package (Experimental)",
            decode="none", write="none", priority="none", origin="application",
            evidence=(
                "cdmw/services/independent_item_package.py and independent_mod_package.py: "
                "bounded v1/v2 package admission. Equipment defaults remain v1; extended settings and usable-item recipes require v2. "
                "Mod Management > Mods adds packages for the current loader workflow."
            ),
            remaining="Package compatibility and required capabilities are checked on admission; game and save compatibility need separate validation.",
            tool=TOOLS[".cditem"], workflow=workflow_for(".cditem"),
        ))
    rows.sort(key=lambda row: (-(row.files or 0), row.extension))
    return tuple(rows)


def headline(rows: Sequence[FormatRow]) -> str:
    """Inventory size without treating format-level write flags as asset guarantees."""

    return _HEADLINE.format(count=sum(row.shipped for row in rows))


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
            f"{row.extension} {row.group} {row.role} {row.tool} {row.evidence} "
            f"{row.remaining} {row.workflow.prerequisites} "
            f"{' '.join(operation.description for operation in row.workflow.operations)} "
            f"{' '.join(row.workflow.limits)}"
        ).casefold():
            continue
        out.append(row)
    return tuple(out)


def groups(rows: Sequence[FormatRow]) -> Tuple[str, ...]:
    return tuple(sorted({row.group for row in rows}))

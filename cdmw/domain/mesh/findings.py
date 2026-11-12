"""One model for mesh problems: what, how bad, where, and what fixes it.

Import, cloth guides, Fit to body and export describe a problem the same way.
A finding has a kind (its ``code``), a severity, the part and LOD it concerns,
the elements concerned (faces, vertices, edges or guides; capped, with the full
count kept) and the fix it suggests as a command id with arguments.

This is the issue type export validation has always used, extended; it is not
a second structure. ``cdmw.domain.mesh.export_validation.MeshExportValidationIssue``
is this same class, and every field it had keeps its name, order and default,
so existing callers and positional construction keep working.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

SEVERITY_BLOCKER = "blocker"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

ELEMENT_FACE = "face"
ELEMENT_VERTEX = "vertex"
ELEMENT_EDGE = "edge"
ELEMENT_GUIDE = "guide"

#: A finding keeps at most this many element indices; ``element_count`` keeps the total.
MAX_FINDING_ELEMENTS = 256

# Suggested fixes, as command ids of the Mesh Editor's registry context
# (`mesh_editor.<helper id>`). P17 stage 3 registers the dedicated ones; until
# a command exists, `fix_fallback_command` names the page that holds the control.
FIX_CLEAN_UP_MESH = "mesh_editor.cleanup.clean_up_mesh"
FIX_CLOTH_SOURCE_LOD = "mesh_editor.cloth.choose_source_lod"
FIX_CLOTH_REDUCE_SKINNING = "mesh_editor.cloth.reduce_skinning"
FIX_CLOTH_PINS = "mesh_editor.cloth.edit_pins"
FIX_CLOTH_FEWER_PARTS = "mesh_editor.cloth.choose_parts"
_FIX_FALLBACKS = {
    FIX_CLEAN_UP_MESH: "mesh_editor.page.cleanup",
    FIX_CLOTH_SOURCE_LOD: "mesh_editor.page.cloth",
    FIX_CLOTH_REDUCE_SKINNING: "mesh_editor.page.cloth",
    FIX_CLOTH_PINS: "mesh_editor.page.cloth",
    FIX_CLOTH_FEWER_PARTS: "mesh_editor.page.cloth",
}


def fix_fallback_command(command: str) -> str:
    """The existing command that opens the control a suggested fix needs."""

    return _FIX_FALLBACKS.get(str(command or ""), "")


@dataclass(frozen=True, slots=True)
class MeshFinding:
    severity: str
    code: str
    message: str
    category: str = "general"
    expected: object | None = None
    actual: object | None = None
    lod_index: int = -1
    submesh_index: int = -1
    vertex_index: int = -1
    face_index: int = -1
    #: The part's name as the user sees it; ``submesh_index`` is its index.
    part: str = ""
    #: What ``elements`` index: ``face``, ``vertex``, ``edge`` (vertex pairs, flattened) or ``guide``.
    element_kind: str = ""
    #: The first ``MAX_FINDING_ELEMENTS`` elements concerned, in ascending order.
    elements: tuple[int, ...] = ()
    #: How many elements are concerned in all; may exceed ``len(elements)``.
    element_count: int = 0
    #: The registry command that fixes it, or "" when no fix exists.
    fix_command: str = ""
    #: Arguments for ``fix_command`` as sorted (name, value) pairs.
    fix_arguments: tuple[tuple[str, object], ...] = ()

    @property
    def kind(self) -> str:
        return self.code

    @property
    def is_blocker(self) -> bool:
        return self.severity == SEVERITY_BLOCKER

    @property
    def count(self) -> int:
        """Elements concerned in all, whether or not every index was kept."""

        return max(int(self.element_count or 0), len(self.elements))

    @property
    def fix(self) -> tuple[str, dict[str, object]] | None:
        if not self.fix_command:
            return None
        return self.fix_command, dict(self.fix_arguments)


def mesh_finding(
    severity: str,
    code: str,
    message: str,
    *,
    category: str = "general",
    part: str = "",
    lod: int = -1,
    submesh: int = -1,
    element_kind: str = "",
    elements: Iterable[int] = (),
    element_count: int | None = None,
    fix_command: str = "",
    fix_arguments: Mapping[str, object] | None = None,
) -> MeshFinding:
    """A finding with its elements capped and sorted, and the full count kept."""

    unique = sorted({int(value) for value in elements})
    total = len(unique) if element_count is None else max(int(element_count), len(unique))
    return MeshFinding(
        severity, code, message, category,
        lod_index=int(lod), submesh_index=int(submesh), part=str(part or ""),
        element_kind=str(element_kind or ""), elements=tuple(unique[:MAX_FINDING_ELEMENTS]),
        element_count=total, fix_command=str(fix_command or ""),
        fix_arguments=tuple(sorted((str(key), value) for key, value in (fix_arguments or {}).items())),
    )


def blocking_findings(findings: Iterable[MeshFinding]) -> tuple[MeshFinding, ...]:
    return tuple(finding for finding in findings if finding.is_blocker)


def raise_for_blockers(findings: Iterable[MeshFinding]) -> None:
    """Refuse with the first blocker's own message, so a refusal and its earlier check cannot disagree.

    The error carries every finding, blockers and warnings, for a caller that
    shows them all.
    """

    findings = tuple(findings)
    if blocking_findings(findings):
        raise MeshFindingError(findings)


class MeshFindingError(ValueError):
    """A refusal made from findings; its text is the first blocker's message."""

    def __init__(self, findings: Iterable[MeshFinding]):
        self.findings = tuple(findings)
        self.blockers = blocking_findings(self.findings)
        super().__init__(self.blockers[0].message if self.blockers else "")


__all__ = [
    "ELEMENT_EDGE",
    "ELEMENT_FACE",
    "ELEMENT_GUIDE",
    "ELEMENT_VERTEX",
    "FIX_CLEAN_UP_MESH",
    "FIX_CLOTH_FEWER_PARTS",
    "FIX_CLOTH_PINS",
    "FIX_CLOTH_REDUCE_SKINNING",
    "FIX_CLOTH_SOURCE_LOD",
    "MAX_FINDING_ELEMENTS",
    "MeshFinding",
    "MeshFindingError",
    "SEVERITY_BLOCKER",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "blocking_findings",
    "fix_fallback_command",
    "mesh_finding",
    "raise_for_blockers",
]

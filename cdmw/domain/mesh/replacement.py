"""Immutable output intent for the optional archive replacement workflow.

Editable parts keep their geometry. Inclusion is interpreted only by the
replacement writer; it has no relationship to viewport visibility.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReplacementFile:
    path: str
    data: bytes
    # Archive location, when this file replaces an existing archive member.
    archive_location: tuple[str, str, int, int, int, int, int] | None = None


@dataclass(frozen=True, slots=True)
class ReplacementPart:
    part_id: str
    target_index: int
    source_part_ids: tuple[str, ...] = ()
    included: bool = True
    material_choice: str = "original"
    source_label: str = ""
    import_positions: tuple[tuple[float, float, float], ...] = ()
    # None identifies older drafts that did not retain the imported normal frame.
    import_normals: tuple[tuple[float, float, float], ...] | None = None


@dataclass(frozen=True, slots=True)
class MeshReplacementState:
    target_path: str
    target_sha256: str
    parts: tuple[ReplacementPart, ...]
    revision: int = 0
    target_location: tuple[str, str, int, int, int, int, int] | None = None
    dependencies: tuple[ReplacementFile, ...] = ()
    companion_files: tuple[ReplacementFile, ...] = ()


PART_ID_ATTRIBUTE = "_cdmw_replacement_part_id"
REPLACEMENT_POLICY = "replacement_game_asset"


def bound_part_indices(mesh, state: MeshReplacementState) -> dict[str, int]:
    """Resolve stable identities, refusing a lost/duplicated identity."""
    actual = [str(getattr(part, PART_ID_ATTRIBUTE, "")) for part in mesh.submeshes]
    expected = {part.part_id for part in state.parts}
    if len(actual) != len(expected) or len(set(actual)) != len(actual) or set(actual) != expected:
        raise ValueError("Replacement part identities changed. Undo the part operation before exporting.")
    return {part_id: index for index, part_id in enumerate(actual)}

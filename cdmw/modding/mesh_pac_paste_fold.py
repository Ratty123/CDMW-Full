"""Fold pasted Geometry Layer copies back into the game Parts they came from.

Exact PAC output keeps the source file's Part list, so a pasted layer cannot be
written as a Part of its own. Each pasted vertex still names the original LOD0
record it was copied from (``source_vertex_offsets``), so the exact topology
writer can append it to that record's own Part as a direct copy: skin, cloth and
every protected byte come from the record, and only position, UV and normal are
authored. Lower LODs stay unchanged, as for every exact topology edit.

Anything that is not such a copy is refused with a reason rather than guessed:
vertices from two Parts, a vertex without an original record, a face no original
face explains, edited weights, another material, or a copy outside the Part's
stored bounds.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from dataclasses import replace

from cdmw.domain.mesh.export_validation import MeshExportValidationIssue, MeshExportValidationReport
from cdmw.domain.mesh.operations import mesh_edit_operations_from_dicts
from cdmw.domain.mesh.topology import (
    TOPOLOGY_MAX_PAC_VERTEX_COUNT,
    TOPOLOGY_METADATA_RESULT_REVISION,
    TOPOLOGY_OPERATION_PASTE_COPIES,
    TOPOLOGY_PROVENANCE_VERSION,
    TOPOLOGY_REBUILDABLE_OPERATIONS,
    SubmeshTopologyProvenance,
    VertexOrigin,
    identity_topology_provenance,
    topology_operation_metadata,
)

from .mesh_pac_topology_builder import _bounds_blockers
from .mesh_parser import ParsedMesh, SubMesh

PASTE_FOLD_OPERATION_SOURCE = "cdmw_geometry_layer_fold"
PASTE_FOLD_BLOCKER = "pasted_copy_not_exact"

_VERTEX_CHANNELS = (
    "uvs", "normals", "tangents", "bone_indices", "bone_weights", "shader_masks", "vertex_colors",
)
_VERTEX_CHANNEL_MAPS = ("uv_sets", "morph_targets", "morph_normals", "morph_tangents")


class PastedPartFoldBlocked(ValueError):
    """A pasted Part cannot be written into its source Part exactly."""


def fold_pasted_parts(
    original_mesh: ParsedMesh,
    edited_mesh: ParsedMesh,
    operations: Iterable[object] = (),
) -> tuple[ParsedMesh, tuple[dict[str, object], ...]]:
    """Return ``edited_mesh`` with every Part beyond the source list folded in.

    The result is a new mesh; ``edited_mesh`` and its Parts are not changed. The
    returned operations drop rows for the folded Parts and record one
    ``paste_copies_topology`` row per receiving Part, continuing the recorded
    topology revisions.
    """
    original_parts = tuple(getattr(original_mesh, "submeshes", ()) or ())
    edited_parts = tuple(getattr(edited_mesh, "submeshes", ()) or ())
    source_count = len(original_parts)
    rows = [operation.to_dict() for operation in mesh_edit_operations_from_dicts(operations)]
    if not original_parts or len(edited_parts) <= source_count:
        return edited_mesh, tuple(rows)

    owners: dict[int, tuple[int, int]] = {}
    for part_index, part in enumerate(original_parts):
        for vertex_index, offset in enumerate(tuple(getattr(part, "source_vertex_offsets", ()) or ())):
            owners[int(offset)] = (part_index, vertex_index)
    copies: dict[int, list[tuple[SubMesh, tuple[int, ...], tuple[int, ...]]]] = {}
    for pasted in edited_parts[source_count:]:
        source, parents = _copy_parents(pasted, owners, original_parts)
        original = original_parts[source]
        _require_exact_copy(pasted, parents, original)
        copies.setdefault(source, []).append((pasted, parents, _copy_face_origins(pasted, parents, original)))

    folded_parts = list(edited_parts[:source_count])
    kept_rows = [row for row in rows if int(row.get("submesh_index", -1)) < source_count]
    revision = 0
    for row in kept_rows:
        metadata = row.get("metadata")
        if row.get("operation") in TOPOLOGY_REBUILDABLE_OPERATIONS and isinstance(metadata, dict):
            revision = max(revision, int(metadata.get(TOPOLOGY_METADATA_RESULT_REVISION, 0) or 0))
    for source in sorted(copies):
        current = folded_parts[source]
        merged = _merged_part(current, original_parts[source], copies[source])
        folded_parts[source] = merged
        kept_rows.append(
            {
                "operation": TOPOLOGY_OPERATION_PASTE_COPIES,
                "lod_index": 0,
                "submesh_index": source,
                "vertex_count": len(merged.vertices),
                "source": PASTE_FOLD_OPERATION_SOURCE,
                "created_by": "CDMW Edit Mesh",
                "metadata": topology_operation_metadata(
                    input_vertex_count=len(current.vertices),
                    input_face_count=len(current.faces),
                    output_vertex_count=len(merged.vertices),
                    output_face_count=len(merged.faces),
                    source_revision=revision,
                    result_revision=revision + 1,
                ),
            }
        )
        revision += 1

    folded = copy.copy(edited_mesh)
    levels = list(getattr(edited_mesh, "lod_levels", ()) or ())
    if levels:
        matches = [
            index for index, level in enumerate(levels)
            if level is edited_mesh.submeshes
            or (len(level) == len(edited_parts) and all(left is right for left, right in zip(level, edited_parts)))
        ]
        if len(matches) != 1:
            raise PastedPartFoldBlocked(
                "Pasted layers can only be written into the LOD they were pasted at."
            )
        levels[matches[0]] = folded_parts
        folded.lod_levels = levels
    folded.submeshes = folded_parts
    folded.total_vertices = sum(len(part.vertices) for part in folded_parts)
    folded.total_faces = sum(len(part.faces) for part in folded_parts)
    setattr(folded, "_cdmw_edit_operations", tuple(kept_rows))
    return folded, tuple(kept_rows)


def exact_output_with_folded_copies(
    original_mesh: ParsedMesh | None,
    mesh: ParsedMesh,
    operations: Iterable[object] = (),
) -> tuple[ParsedMesh, tuple[object, ...], str]:
    """``(mesh, operations, refusal)`` for exact validation and output.

    A refusal leaves the mesh and operations as they were, so validation still
    reports the Part count alongside the reason the copies could not fold.
    """
    operations = tuple(operations or ())
    if original_mesh is None or len(mesh.submeshes) <= len(original_mesh.submeshes):
        return mesh, operations, ""
    try:
        folded, rows = fold_pasted_parts(original_mesh, mesh, operations)
    except PastedPartFoldBlocked as exc:
        return mesh, operations, str(exc)
    return folded, rows, ""


def with_paste_fold_refusal(report: MeshExportValidationReport, refusal: str) -> MeshExportValidationReport:
    """Put the fold's reason ahead of the Part-count blocker it explains."""
    if not refusal:
        return report
    issue = MeshExportValidationIssue("blocker", PASTE_FOLD_BLOCKER, refusal, "topology")
    return replace(report, issues=(issue, *report.issues))


def _copy_parents(
    pasted: SubMesh,
    owners: dict[int, tuple[int, int]],
    original_parts: Sequence[SubMesh],
) -> tuple[int, tuple[int, ...]]:
    offsets = tuple(getattr(pasted, "source_vertex_offsets", ()) or ())
    if not pasted.vertices or len(offsets) != len(pasted.vertices):
        raise PastedPartFoldBlocked(
            f"'{pasted.name}' is not a copy of game vertices, so Exact output cannot write it. "
            "Delete its layer or choose Free Edit."
        )
    located = [owners.get(int(offset)) for offset in offsets]
    if any(owner is None for owner in located):
        raise PastedPartFoldBlocked(
            f"'{pasted.name}' contains vertices that are not copies of game vertices, so Exact output "
            "cannot write it. Delete its layer or choose Free Edit."
        )
    sources = {owner[0] for owner in located if owner is not None}
    if len(sources) != 1:
        raise PastedPartFoldBlocked(
            f"'{pasted.name}' copies vertices from more than one game Part, so Exact output cannot "
            "write it into one of them. Delete its layer or choose Free Edit."
        )
    source = sources.pop()
    if not 0 <= source < len(original_parts):
        raise PastedPartFoldBlocked(f"'{pasted.name}' names a game Part this file does not contain.")
    return source, tuple(owner[1] for owner in located if owner is not None)


def _copy_face_origins(pasted: SubMesh, parents: Sequence[int], original: SubMesh) -> tuple[int, ...]:
    by_corners: dict[tuple[int, int, int], int] = {}
    for face_index, face in enumerate(tuple(getattr(original, "faces", ()) or ())):
        by_corners.setdefault(tuple(sorted(int(value) for value in face[:3])), face_index)
    origins: list[int] = []
    for face in tuple(getattr(pasted, "faces", ()) or ()):
        try:
            corners = tuple(sorted(parents[int(value)] for value in face[:3]))
        except (IndexError, TypeError, ValueError):
            corners = ()
        origin = by_corners.get(corners) if len(corners) == 3 else None
        if origin is None:
            raise PastedPartFoldBlocked(
                f"'{pasted.name}' has faces that are not copies of faces in '{original.name}', so Exact "
                "output cannot write it. Undo the topology change on the copy or choose Free Edit."
            )
        origins.append(origin)
    if not origins:
        raise PastedPartFoldBlocked(f"'{pasted.name}' has no faces to write.")
    return tuple(origins)


def _require_exact_copy(pasted: SubMesh, parents: Sequence[int], original: SubMesh) -> None:
    if str(pasted.material or "") != str(original.material or ""):
        raise PastedPartFoldBlocked(
            f"'{pasted.name}' no longer uses the material of '{original.name}', so Exact output cannot "
            "write it into that Part."
        )
    if any(original.bone_indices or ()):
        indices = tuple(getattr(pasted, "bone_indices", ()) or ())
        weights = tuple(getattr(pasted, "bone_weights", ()) or ())
        if len(indices) != len(parents) or len(weights) != len(parents) or any(
            tuple(indices[index]) != tuple(original.bone_indices[parent])
            or tuple(weights[index]) != tuple(original.bone_weights[parent])
            for index, parent in enumerate(parents)
        ):
            raise PastedPartFoldBlocked(
                f"Weights on '{pasted.name}' differ from the game vertices it was copied from. Exact "
                "output keeps those vertices' weights; undo the weight edit or choose Free Edit."
            )
    if _bounds_blockers(original, pasted):
        raise PastedPartFoldBlocked(
            f"'{pasted.name}' extends outside the bounds of '{original.name}'. Exact output cannot "
            "enlarge a game Part's bounds; move the copy back inside it or choose Free Edit."
        )


def _merged_part(
    current: SubMesh,
    original: SubMesh,
    copies: Sequence[tuple[SubMesh, tuple[int, ...], tuple[int, ...]]],
) -> SubMesh:
    provenance = getattr(current, "topology_provenance", None)
    if provenance is None:
        if len(current.vertices) != len(original.vertices) or len(current.faces) != len(original.faces):
            raise PastedPartFoldBlocked(
                f"'{current.name}' changed shape without a recorded topology edit, so pasted copies "
                "cannot be added to it."
            )
        provenance = identity_topology_provenance(len(original.vertices), len(original.faces))
    if not isinstance(provenance, SubmeshTopologyProvenance):
        raise PastedPartFoldBlocked(f"'{current.name}' carries an unreadable topology record.")

    merged = copy.copy(current)
    vertex_count = len(current.vertices)
    merged.vertices = list(current.vertices)
    merged.faces = list(current.faces)
    for channel in _VERTEX_CHANNELS:
        setattr(merged, channel, _merged_channel(current, copies, channel))
    for channel in _VERTEX_CHANNEL_MAPS:
        setattr(merged, channel, _merged_channel_map(current, copies, channel))
    merged.source_vertex_map = list(current.source_vertex_map or ())
    merged.source_vertex_offsets = list(current.source_vertex_offsets or ())
    origins = list(provenance.vertex_origins)
    face_origins = list(provenance.face_origins)
    for pasted, parents, pasted_face_origins in copies:
        merged.vertices.extend(pasted.vertices)
        merged.faces.extend(
            (int(face[0]) + vertex_count, int(face[1]) + vertex_count, int(face[2]) + vertex_count)
            for face in pasted.faces
        )
        merged.source_vertex_map.extend(parents)
        merged.source_vertex_offsets.extend(int(value) for value in pasted.source_vertex_offsets)
        origins.extend(VertexOrigin((parent,), (1.0,)) for parent in parents)
        face_origins.extend(pasted_face_origins)
        vertex_count += len(pasted.vertices)
    if vertex_count > TOPOLOGY_MAX_PAC_VERTEX_COUNT:
        raise PastedPartFoldBlocked(
            f"'{current.name}' would hold {vertex_count:,} vertices with its pasted copies; a game Part "
            f"holds at most {TOPOLOGY_MAX_PAC_VERTEX_COUNT:,}."
        )
    merged.source_vertex_map_authority = "topology"
    merged.vertex_count = vertex_count
    merged.face_count = len(merged.faces)
    merged.topology_provenance = SubmeshTopologyProvenance(
        version=TOPOLOGY_PROVENANCE_VERSION,
        original_vertex_count=provenance.original_vertex_count,
        original_face_count=provenance.original_face_count,
        vertex_origins=tuple(origins),
        face_origins=tuple(face_origins),
    )
    return merged


def _merged_channel(current: SubMesh, copies: Sequence[tuple[SubMesh, object, object]], channel: str) -> list:
    base = list(getattr(current, channel, ()) or ())
    if len(base) != len(current.vertices):
        # The receiving Part does not author this channel, so neither do its
        # copies; the copied records keep their stored bytes.
        return [] if not base else base
    for pasted, _parents, _faces in copies:
        values = list(getattr(pasted, channel, ()) or ())
        if len(values) != len(pasted.vertices):
            raise PastedPartFoldBlocked(
                f"'{pasted.name}' is missing {channel.replace('_', ' ')} that '{current.name}' has, so "
                "Exact output cannot write it into that Part."
            )
        base.extend(values)
    return base


def _merged_channel_map(
    current: SubMesh,
    copies: Sequence[tuple[SubMesh, object, object]],
    channel: str,
) -> dict:
    merged: dict = {}
    for key, values in dict(getattr(current, channel, {}) or {}).items():
        if len(values) != len(current.vertices):
            continue
        combined = list(values)
        for pasted, _parents, _faces in copies:
            pasted_values = list((getattr(pasted, channel, {}) or {}).get(key, ()) or ())
            if len(pasted_values) != len(pasted.vertices):
                raise PastedPartFoldBlocked(
                    f"'{pasted.name}' is missing {channel.replace('_', ' ')} '{key}' that "
                    f"'{current.name}' has, so Exact output cannot write it into that Part."
                )
            combined.extend(pasted_values)
        merged[key] = combined
    return merged


__all__ = [
    "PASTE_FOLD_BLOCKER",
    "PASTE_FOLD_OPERATION_SOURCE",
    "PastedPartFoldBlocked",
    "exact_output_with_folded_copies",
    "fold_pasted_parts",
    "with_paste_fold_refusal",
]

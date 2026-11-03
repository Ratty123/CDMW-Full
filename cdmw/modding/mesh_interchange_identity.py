"""Fold the copies Blender writes of one source vertex back into that vertex.

A returned Part names each vertex's source through `source_vertex_map`, built
from its CDMW vertex id (the `_CDMW_VERTEX_ID` attribute in GLB, the identity UV
layer in FBX, the `v` line in OBJ). Blender's exporters write one vertex per
distinct corner, so a shared vertex whose corner normals disagree comes back
more than once. Same-count edit operations copy channels by position, and the
importer names only Parts that kept their source count, so an uncollapsed Part
used to be rebuilt from its original vertices without a word.

A copy may differ only in its normal. Blender's glTF importer shades a face
flat when its vertex normals equal the face normal, so an edit that tilts one
face of a flat region gives each shared vertex one normal per face. When one
copy still carries the source normal the Part keeps it. Otherwise copies within
Blender's own sharp-edge default of 30 degrees are one smooth surface and their
mean is the edited normal; copies further apart are a hard edge, which needs a
vertex the game mesh does not have.
"""

from __future__ import annotations

import copy
import math

from cdmw.domain.mesh.operations import (
    MeshEditOperation,
    mesh_edit_operations_from_dicts,
    mesh_edit_operations_to_dicts,
)

__all__ = [
    "collapse_split_vertices",
    "declare_recovered_operations",
    "recover_returned_vertex_splits",
    "require_returned_part_counts",
]

#: PAC normal packing and Blender's custom-normal compression round a near-zero
#: component away; a copy within about 0.1 degree of the source carries it.
_SOURCE_NORMAL_TOLERANCE = 2e-3
#: Blender's default Smooth by Angle limit: corners closer than this are one surface.
_COPY_NORMAL_TOLERANCE = 2.0 * math.sin(math.radians(30.0) / 2.0)

_SAME_ROWS = ("vertices", "uvs", "tangents", "tangent_signs", "bone_indices", "bone_weights", "source_vertex_offsets")
_SAME_ROW_MAPS = ("uv_sets", "morph_targets")


def is_companion_return(mesh: object) -> bool:
    """Whether `mesh` was read back from a CDMW package with its companion."""

    return bool(getattr(mesh, "_cdmw_imported_from_obj", False)) and bool(
        getattr(mesh, "_cdmw_obj_sidecar_present", False))


def collapse_split_vertices(part, donor, reference, label: str = "") -> bool:
    """Recover the donor's vertex slots for a Part Blender split, when proven.

    `reference` holds the normals the returned Part was exported with, in donor
    order. Returns False when the Part lacks the identity to prove anything;
    raises ValueError, naming the Part, when copies disagree beyond a split.
    """

    count, actual = len(donor.vertices), len(part.vertices)
    source_map = list(part.source_vertex_map)
    if (len(source_map) != actual or set(source_map) != set(range(count))
            or len(part.normals) != actual or len(reference.normals) != count):
        return False
    name = label or str(getattr(donor, "name", "") or getattr(part, "name", "") or "")
    groups = [[] for _ in range(count)]
    for index, source_index in enumerate(source_map):
        groups[source_index].append(index)
    order = [indices[0] for indices in groups]
    for source_index, indices in enumerate(groups):
        if len(indices) == 1:
            continue
        # New UV seams, displaced copies, or changed protected channels cannot
        # be collapsed into the PAC's one record per vertex.
        for attr in _SAME_ROWS:
            values = getattr(part, attr, ()) or ()
            if values and (len(values) != actual or any(values[i] != values[indices[0]] for i in indices)):
                raise ValueError(f"Part '{name}': split vertex {source_index} changes {attr}; use topology replacement.")
        for attr in _SAME_ROW_MAPS:
            for key, values in (getattr(part, attr, None) or {}).items():
                if len(values) == actual and any(values[i] != values[indices[0]] for i in indices):
                    raise ValueError(f"Part '{name}': split vertex {source_index} changes {attr} {key}; "
                                     "use topology replacement.")
        part.normals[indices[0]] = _split_normal(part, indices, reference.normals[source_index], name, source_index)
    for attr in ("normals", *_SAME_ROWS):
        values = getattr(part, attr, ()) or ()
        if len(values) == actual:
            setattr(part, attr, [values[index] for index in order])
    from .mesh_deformer import _remap_interchange_vertex_channels
    _remap_interchange_vertex_channels(part, {old: new for new, old in enumerate(order)}, actual, include_uvs=False)
    part.faces = [tuple(source_map[index] for index in face) for face in part.faces]
    part.source_vertex_map = list(range(count))
    part.vertex_count = count
    return True


def _split_normal(part, indices, source_normal, name, source_index):
    source_direction = _direction(source_normal)
    copies = [_direction(part.normals[i]) for i in indices]
    if any(math.dist(direction, source_direction) <= _SOURCE_NORMAL_TOLERANCE for direction in copies):
        return source_normal
    reversed_direction = tuple(-value for value in source_direction)
    if any(math.dist(direction, reversed_direction) <= _SOURCE_NORMAL_TOLERANCE for direction in copies):
        return tuple(-value for value in source_normal)
    if all(math.dist(left, right) <= _COPY_NORMAL_TOLERANCE for left in copies for right in copies):
        return _direction(tuple(sum(axis) / len(copies) for axis in zip(*copies)))
    raise ValueError(f"Part '{name}': split vertex {source_index} has no matching source normal, and its corners "
                     "differ by more than 30 degrees, a hard edge the game mesh cannot hold. Shade it smooth in "
                     "Blender, or use topology replacement.")


def _direction(values):
    length = math.hypot(*values)
    return tuple(value / length for value in values) if length > 1e-12 else tuple(values)


def declare_recovered_operations(mesh, part_indices, source: str) -> None:
    """Name the channels of Parts recovered after import, which named only same-count Parts."""

    operations = list(mesh_edit_operations_from_dicts(getattr(mesh, "_cdmw_edit_operations", ()) or ()))
    existing = {(op.operation, op.lod_index, op.submesh_index) for op in operations}
    for index in part_indices:
        part = mesh.submeshes[index]
        for channel, attr in (("positions", "vertices"), ("normals", "normals"), ("uv0", "uvs")):
            name = f"replace_{channel}_same_count"
            if len(getattr(part, attr)) == len(part.vertices) and (name, 0, index) not in existing:
                operations.append(MeshEditOperation(name, lod_index=0, submesh_index=index,
                                                    vertex_count=len(part.vertices), source=source))
        if (getattr(part, "_cdmw_verified_skin_mapping", False) and getattr(part, "_cdmw_skin_weights_changed", False)
                and ("replace_skin_weights_same_count", 0, index) not in existing):
            from cdmw.domain.mesh.skin_weight_edits import (
                SKIN_ROW_FINGERPRINTS,
                skin_row_fingerprints,
            )
            operations.append(MeshEditOperation(
                "replace_skin_weights_same_count", lod_index=0, submesh_index=index,
                vertex_count=len(part.vertices), source=source,
                metadata={"palette_size": int(part._cdmw_source_palette_size),
                          SKIN_ROW_FINGERPRINTS: skin_row_fingerprints(part)}))
    mesh._cdmw_edit_operations = mesh_edit_operations_to_dicts(operations)


def require_returned_part_counts(mesh, original) -> None:
    """Refuse a returned Part that still differs from its source in vertex count.

    Same-count operations are the only way its edits reach the game mesh, so
    letting it through rebuilt the Part from the original vertices.
    """

    if not is_companion_return(mesh) or _topology_may_change(mesh):
        return
    parts, donors = tuple(mesh.submeshes), tuple(original.submeshes)
    if len(parts) != len(donors):
        return
    for part, donor in zip(parts, donors):
        actual, expected = len(part.vertices), len(donor.vertices)
        # A Part the companion did not match carries no source map and replaces the mesh outright.
        if actual != expected and getattr(part, "source_vertex_map", None):
            name = str(donor.name or part.name or "")
            raise ValueError(
                f"Part '{name}' came back with {actual} vertices; the game mesh has {expected}, so its edits "
                "cannot be matched vertex for vertex. Blender drops vertices that no face uses, and adding, "
                "deleting or splitting geometry changes the count; use a replacement import for those."
            )


def recover_returned_vertex_splits(mesh, original):
    """Collapse Blender's splits in a returned mesh, name them, and refuse the rest.

    Returns `mesh` unchanged when it is not a companion return or carries a
    topology contract; otherwise a recovered copy.
    """

    from .mesh_importer import _has_topology_contract

    if not is_companion_return(mesh) or _has_topology_contract(mesh) or _topology_may_change(mesh):
        return mesh
    if len(mesh.submeshes) != len(original.submeshes):
        return mesh
    recovered_mesh, recovered = mesh, []
    for index, (part, donor) in enumerate(zip(mesh.submeshes, original.submeshes)):
        if len(part.vertices) <= len(donor.vertices):
            continue
        if recovered_mesh is mesh:
            recovered_mesh = copy.deepcopy(mesh)
        if collapse_split_vertices(recovered_mesh.submeshes[index], donor, donor):
            recovered.append(index)
    if recovered:
        declare_recovered_operations(recovered_mesh, recovered, "split-vertex recovery")
    require_returned_part_counts(recovered_mesh, original)
    return recovered_mesh


def _topology_may_change(mesh) -> bool:
    rules = getattr(mesh, "_cdmw_sidecar_import_rules", None)
    return isinstance(rules, dict) and bool(rules.get("allow_topology_change"))

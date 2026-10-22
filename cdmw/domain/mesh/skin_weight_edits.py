"""Proof of explicitly authored skin rows through direct-record cleanup."""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Iterable, Mapping

from .operations import TOPOLOGY_MESH_EDIT_OPERATIONS, mesh_edit_operations_from_dicts
from .topology import (
    SubmeshTopologyProvenance,
    TOPOLOGY_OPERATION_REMOVE_DOUBLES,
    validate_topology_operation_history,
    validate_topology_provenance,
)


SKIN_ROW_FINGERPRINTS = "skin_row_fingerprints"


def _skin_row_fingerprint(indices, weights) -> str:
    if len(indices) != len(weights) or any(type(index) is not int for index in indices):
        raise ValueError("Invalid skin row fingerprint input.")
    if any(not math.isfinite(float(weight)) for weight in weights):
        raise ValueError("Skin row fingerprint requires finite weights.")
    data = struct.pack("<I", len(indices))
    data += b"".join(struct.pack("<qd", index, float(weight)) for index, weight in zip(indices, weights))
    return hashlib.sha256(data).hexdigest()


def skin_row_fingerprints(submesh: object, vertex_indices: Iterable[int] | None = None) -> dict[str, str]:
    """Record accepted rows by their immutable original vertex identity."""
    indices = getattr(submesh, "bone_indices")
    weights = getattr(submesh, "bone_weights")
    sources = getattr(submesh, "source_vertex_map")
    vertices = range(len(indices)) if vertex_indices is None else vertex_indices
    return {str(sources[index]): _skin_row_fingerprint(indices[index], weights[index]) for index in vertices}


def skin_weight_cleanup_sources(
    submesh: object,
    original: object | None,
    operations: Iterable[object],
    submesh_index: int,
    original_data: bytes | None,
) -> tuple[int, ...] | None:
    """Admit recorded skin edits followed only by proven Remove Doubles.

    This does not authorize blending, new vertices, bone remapping or edits made
    after cleanup. Every survivor retains either its original row or the exact
    row the weight editor accepted for that original donor record.
    """
    provenance = getattr(submesh, "topology_provenance", None)
    if original is None or not original_data or not isinstance(provenance, SubmeshTopologyProvenance):
        return None
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    faces = tuple(getattr(submesh, "faces", ()) or ())
    original_count = len(tuple(getattr(original, "vertices", ()) or ()))
    original_faces = len(tuple(getattr(original, "faces", ()) or ()))
    if (validate_topology_provenance(provenance, output_vertex_count=len(vertices), output_face_count=len(faces))
            or provenance.original_vertex_count != original_count
            or provenance.original_face_count != original_faces
            or provenance.derived_vertex_count):
        return None
    parents = tuple(origin.direct_parent for origin in provenance.vertex_origins)
    original_offsets = tuple(getattr(original, "source_vertex_offsets", ()) or ())
    if (len(set(parents)) != len(parents) or len(original_offsets) != original_count
            or tuple(getattr(original, "source_vertex_map", ()) or ()) != tuple(range(original_count))
            or getattr(submesh, "source_vertex_map_authority", "") != "topology"
            or tuple(getattr(submesh, "source_vertex_map", ()) or ()) != parents
            or tuple(getattr(submesh, "source_vertex_offsets", ()) or ()) != tuple(original_offsets[p] for p in parents)
            or getattr(submesh, "source_descriptor_offset", None) != getattr(original, "source_descriptor_offset", None)):
        return None
    normalized = mesh_edit_operations_from_dicts(operations)
    if validate_topology_operation_history(normalized):
        return None
    recorded: dict[str, str] = {}
    cleaned = False
    vertex_count, face_count = original_count, original_faces
    for operation in normalized:
        if (operation.lod_index, operation.submesh_index) != (0, submesh_index):
            continue
        metadata = operation.metadata
        if operation.operation in TOPOLOGY_MESH_EDIT_OPERATIONS:
            if (operation.operation != TOPOLOGY_OPERATION_REMOVE_DOUBLES
                    or type(metadata.get("input_vertex_count")) is not int
                    or type(metadata.get("input_face_count")) is not int
                    or metadata.get("input_vertex_count") != vertex_count
                    or metadata.get("input_face_count") != face_count
                    or metadata.get("output_vertex_count") != operation.vertex_count):
                return None
            next_vertices, next_faces = metadata.get("output_vertex_count"), metadata.get("output_face_count")
            if (type(next_vertices) is not int or type(next_faces) is not int
                    or not 0 <= next_vertices <= vertex_count or not 0 <= next_faces <= face_count):
                return None
            vertex_count, face_count = next_vertices, next_faces
            cleaned = True
        elif operation.operation == "replace_skin_weights_same_count":
            rows = metadata.get(SKIN_ROW_FINGERPRINTS)
            if cleaned or operation.vertex_count != original_count or not isinstance(rows, Mapping) or not rows:
                return None
            for key, digest in rows.items():
                if (not isinstance(key, str) or len(key) > len(str(original_count))
                        or not key.isdecimal() or str(int(key)) != key
                        or not 0 <= int(key) < original_count or not isinstance(digest, str)
                        or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)):
                    return None
            recorded.update(rows)
    if not cleaned or not recorded or (vertex_count, face_count) != (len(vertices), len(faces)):
        return None
    try:
        current_indices = tuple(getattr(submesh, "bone_indices", ()) or ())
        current_weights = tuple(getattr(submesh, "bone_weights", ()) or ())
        if len(current_indices) != len(parents) or len(current_weights) != len(parents):
            return None
        for index, parent in enumerate(parents):
            offset = original_offsets[parent]
            if type(offset) is not int or offset < 0 or offset + 40 > len(original_data):
                return None
            capacity = 6 if original_data[offset + 39] & 63 == 63 else 4
            if not 1 <= len(current_indices[index]) <= capacity:
                return None
            expected = recorded.get(str(parent)) or _skin_row_fingerprint(
                original.bone_indices[parent], original.bone_weights[parent],
            )
            if _skin_row_fingerprint(current_indices[index], current_weights[index]) != expected:
                return None
    except (AttributeError, IndexError, TypeError, ValueError, OverflowError, struct.error):
        return None
    return parents

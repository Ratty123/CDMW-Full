from __future__ import annotations

from array import array
import ctypes
import dataclasses
from importlib import import_module
import json
import math
import os
import queue
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from uuid import uuid4

from cdmw.modding.mesh_deformer import MeshFaceDeleteResult, MeshPartSplitResult, _EXTRA_SUBMESH_ATTRS
from cdmw.modding.mesh_native_core_constants import (
    Face,
    NATIVE_MESH_CORE_BACKEND_ID,
    NATIVE_MESH_CORE_BINARY_NAME,
    NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR,
    Vec2,
    Vec3,
    _NATIVE_MATERIAL_REPORT_ATTRS,
    _NATIVE_MESH_EDITOR_NORMAL_OPERATIONS,
    _NATIVE_MESH_SESSION_TOKEN_ATTR,
    _NATIVE_PREVIEW_MATERIAL_OVERRIDE_KEYS,
    _TRANSIENT_NATIVE_SUBMESH_ATTRS,
)
from cdmw.domain.mesh.topology import (
    SubmeshTopologyProvenance,
    TOPOLOGY_PROVENANCE_VERSION,
    TopologyProvenanceError,
    VertexOrigin,
    canonical_vertex_origin,
    topology_source_vertex_map,
    validate_topology_provenance,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.mesh_skinning import SOURCE_VERTEX_MAP_TOPOLOGY
from cdmw.models import RunCancelled


def _proxy(name: str):
    def call(*args, **kwargs):
        return getattr(import_module("cdmw.modding.mesh_native_core"), name)(*args, **kwargs)

    return call

_i32_range_report_values = _proxy("_i32_range_report_values")
_i32_stride_range_report_values = _proxy("_i32_stride_range_report_values")
_index = _proxy("_index")
_native_binary_descriptor = _proxy("_native_binary_descriptor")
_native_job_kwargs = _proxy("_native_job_kwargs")
_read_bone_binary_report_payloads = _proxy("_read_bone_binary_report_payloads")
_read_f64_binary_report_payload = _proxy("_read_f64_binary_report_payload")
_read_face_binary_report_payload = _proxy("_read_face_binary_report_payload")
_read_i32_binary_report_payload = _proxy("_read_i32_binary_report_payload")
_read_vec2_binary_report_payload = _proxy("_read_vec2_binary_report_payload")
_read_vec3_binary_report_payload = _proxy("_read_vec3_binary_report_payload")
_run_native_mesh_core_service_job = _proxy("_run_native_mesh_core_service_job")
_vec3 = _proxy("_vec3")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")


def dispose_native_mesh_sparse_vertex_snapshot(
    snapshot: Mapping[str, object] | object,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 2.0,
) -> bool:
    if isinstance(snapshot, Mapping):
        handle = snapshot.get("handle") if isinstance(snapshot.get("handle"), Mapping) else snapshot
        snapshot_id = str(
            handle.get("native_sparse_snapshot_id")  # type: ignore[union-attr]
            or handle.get("sparse_snapshot_id")  # type: ignore[union-attr]
            or handle.get("id")  # type: ignore[union-attr]
            or ""
        ).strip()
    else:
        snapshot_id = str(snapshot or "").strip()
    if not snapshot_id:
        return False
    binary = find_native_mesh_core_binary()
    if binary is None:
        return False
    try:
        report = _run_native_mesh_core_service_job(
            binary,
            "snapshot-vertices-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "clear_sparse_snapshot",
                "sparse_snapshot_id": snapshot_id,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return False
    return isinstance(report, Mapping) and str(report.get("status") or "").strip().lower() == "ok"

def _mesh_snapshot_metadata(mesh: ParsedMesh) -> dict[str, object]:
    return {
        "path": str(getattr(mesh, "path", "") or ""),
        "format": str(getattr(mesh, "format", "") or ""),
        "bbox_min": _vec3(getattr(mesh, "bbox_min", (0.0, 0.0, 0.0)), fallback=0.0),
        "bbox_max": _vec3(getattr(mesh, "bbox_max", (0.0, 0.0, 0.0)), fallback=0.0),
    }

def _submesh_snapshot_metadata(submesh: object) -> dict[str, object]:
    metadata: dict[str, object] = {
        "name": str(getattr(submesh, "name", "") or ""),
        "material": str(getattr(submesh, "material", "") or ""),
        "texture": str(getattr(submesh, "texture", "") or ""),
        "source_index_offset": int(getattr(submesh, "source_index_offset", -1) or -1),
        "source_index_count": int(getattr(submesh, "source_index_count", 0) or 0),
        "source_vertex_stride": int(getattr(submesh, "source_vertex_stride", 0) or 0),
        "source_descriptor_offset": int(getattr(submesh, "source_descriptor_offset", -1) or -1),
        "source_bbox_min": _vec3(getattr(submesh, "source_bbox_min", (0.0, 0.0, 0.0)), fallback=0.0),
        "source_bbox_extent": _vec3(getattr(submesh, "source_bbox_extent", (0.0, 0.0, 0.0)), fallback=0.0),
        "source_lod_count": int(getattr(submesh, "source_lod_count", 0) or 0),
    }
    extra_attrs: dict[str, object] = {}
    for attr_name in _EXTRA_SUBMESH_ATTRS:
        if attr_name in _TRANSIENT_NATIVE_SUBMESH_ATTRS:
            continue
        if hasattr(submesh, attr_name):
            extra_attrs[attr_name] = _snapshot_metadata_value(getattr(submesh, attr_name))
    if extra_attrs:
        metadata["extra_attrs"] = extra_attrs
    return metadata

def _snapshot_metadata_value(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _snapshot_metadata_value(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _snapshot_metadata_value(item) for key, item in value.items()}
    if isinstance(value, (list, set, tuple)):
        return [_snapshot_metadata_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

def _native_submesh_snapshot_item(
    item: Mapping[str, object],
    *,
    metadata: Mapping[str, object],
    expected_vertices: int,
    expected_faces: int,
) -> dict[str, object] | None:
    submesh_index = _index(item.get("index"))
    vertex_count = _index(item.get("vertex_count"))
    face_count = _index(item.get("face_count"))
    if submesh_index is None or vertex_count != expected_vertices or face_count != expected_faces:
        return None
    vertices_binary = _native_binary_descriptor(item.get("vertices_binary"), expected_count=vertex_count, components=3, kind="f64")
    faces_binary = _native_binary_descriptor(item.get("faces_binary"), expected_count=face_count, components=3, kind="i32")
    if vertices_binary is None or faces_binary is None:
        return None
    result: dict[str, object] = {
        "index": submesh_index,
        "session_id": str(item.get("session_id") or "").strip(),
        "metadata": dict(metadata),
        "vertex_count": vertex_count,
        "face_count": face_count,
        "vertices_binary": vertices_binary,
        "faces_binary": faces_binary,
    }
    _copy_snapshot_descriptor(result, item, "source_face_indices_binary", expected_count=face_count, components=1, kind="i32")
    _copy_snapshot_i32_range(result, item, "source_face_start", "source_face_count", expected_count=face_count)
    for key, components, kind in (
        ("normals_binary", 3, "f64"),
        ("uvs_binary", 2, "f64"),
        ("tangents_binary", 3, "f64"),
        ("tangent_signs_binary", 1, "f64"),
        ("source_vertex_map_binary", 1, "i32"),
        ("source_vertex_offsets_binary", 1, "i32"),
        ("bone_counts_binary", 1, "i32"),
    ):
        _copy_snapshot_descriptor(result, item, key, expected_count=vertex_count, components=components, kind=kind)
    _copy_snapshot_i32_range(result, item, "source_vertex_map_start", "source_vertex_map_count", expected_count=vertex_count)
    _copy_snapshot_i32_stride_range(result, item, expected_count=vertex_count)
    raw_bone_indices = item.get("bone_indices_binary")
    raw_bone_weights = item.get("bone_weights_binary")
    bone_index_count = _index(raw_bone_indices.get("count")) if isinstance(raw_bone_indices, Mapping) else None
    bone_weight_count = _index(raw_bone_weights.get("count")) if isinstance(raw_bone_weights, Mapping) else None
    if bone_index_count is not None and bone_weight_count == bone_index_count:
        _copy_snapshot_descriptor(result, item, "bone_indices_binary", expected_count=bone_index_count, components=1, kind="i32")
        _copy_snapshot_descriptor(result, item, "bone_weights_binary", expected_count=bone_index_count, components=1, kind="f64")
    _copy_snapshot_topology_provenance(result, item, expected_vertices=vertex_count, expected_faces=face_count)
    return result


def _copy_snapshot_topology_provenance(
    target: dict[str, object],
    source: Mapping[str, object],
    *,
    expected_vertices: int,
    expected_faces: int,
) -> None:
    """Carry the CSR contract only when all three descriptors agree.

    A partial set is dropped whole. Half a contract decodes into something that
    looks like lineage without being it, which is worse than no lineage at all.
    """
    if not bool(source.get("topology_rebuild_valid")):
        return
    offsets = _native_binary_descriptor(
        source.get("vertex_origin_offsets_binary"),
        expected_count=expected_vertices + 1,
        components=1,
        kind="i32",
    )
    raw_parents = source.get("vertex_origin_parents_binary")
    parent_count = _index(raw_parents.get("count")) if isinstance(raw_parents, Mapping) else None
    if offsets is None or parent_count is None or parent_count <= 0:
        return
    parents = _native_binary_descriptor(raw_parents, expected_count=parent_count, components=1, kind="i32")
    weights = _native_binary_descriptor(
        source.get("vertex_origin_weights_binary"), expected_count=parent_count, components=1, kind="f64"
    )
    if parents is None or weights is None:
        return
    original_vertex_count = _index(source.get("topology_original_vertex_count"))
    original_face_count = _index(source.get("topology_original_face_count"))
    if original_vertex_count is None or original_face_count is None:
        return
    if original_vertex_count <= 0 or original_face_count <= 0 or expected_faces <= 0:
        return
    target["vertex_origin_offsets_binary"] = offsets
    target["vertex_origin_parents_binary"] = parents
    target["vertex_origin_weights_binary"] = weights
    target["topology_contract"] = str(source.get("topology_contract") or "")
    target["topology_rebuild_valid"] = True
    target["topology_original_vertex_count"] = original_vertex_count
    target["topology_original_face_count"] = original_face_count

def _copy_snapshot_descriptor(
    target: dict[str, object],
    source: Mapping[str, object],
    key: str,
    *,
    expected_count: int,
    components: int,
    kind: str,
) -> None:
    descriptor = _native_binary_descriptor(source.get(key), expected_count=expected_count, components=components, kind=kind)
    if descriptor is not None:
        target[key] = descriptor

def _copy_snapshot_i32_range(
    target: dict[str, object],
    source: Mapping[str, object],
    start_key: str,
    count_key: str,
    *,
    expected_count: int,
) -> None:
    start = _index(source.get(start_key))
    count = _index(source.get(count_key))
    if start is not None and start >= 0 and count == expected_count:
        target[start_key] = start
        target[count_key] = count

def _copy_snapshot_i32_stride_range(target: dict[str, object], source: Mapping[str, object], *, expected_count: int) -> None:
    start = _index(source.get("source_vertex_offsets_start"))
    count = _index(source.get("source_vertex_offsets_count"))
    stride = _index(source.get("source_vertex_offsets_stride"))
    if start is not None and start >= 0 and count == expected_count and stride is not None and stride > 0:
        target["source_vertex_offsets_start"] = start
        target["source_vertex_offsets_count"] = count
        target["source_vertex_offsets_stride"] = stride

def _submesh_from_native_snapshot_item(item: Mapping[str, object]) -> SubMesh | None:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    vertex_count = _index(item.get("vertex_count"))
    face_count = _index(item.get("face_count"))
    if vertex_count is None or face_count is None or vertex_count < 0 or face_count < 0:
        return None
    if vertex_count:
        vertices = _read_vec3_binary_report_payload(item.get("vertices_binary"), expected_count=vertex_count)
        faces = _read_face_binary_report_payload(item.get("faces_binary"), expected_count=face_count, vertex_count=vertex_count)
        if vertices is None or faces is None:
            return None
    else:
        vertices = []
        faces = []
    normals = _read_vec3_binary_report_payload(item.get("normals_binary"), expected_count=vertex_count) or []
    uvs = _read_vec2_binary_report_payload(item.get("uvs_binary"), expected_count=vertex_count) or []
    tangents = _read_vec3_binary_report_payload(item.get("tangents_binary"), expected_count=vertex_count) or []
    tangent_signs = _read_f64_binary_report_payload(item.get("tangent_signs_binary"), expected_count=vertex_count) or []
    bones = None
    if item.get("bone_counts_binary") is not None:
        bones = _read_bone_binary_report_payloads(
            item.get("bone_counts_binary"),
            item.get("bone_indices_binary"),
            item.get("bone_weights_binary"),
            expected_count=vertex_count,
        )
        if bones is None:
            return None
    source_vertex_map = _read_i32_binary_report_payload(item.get("source_vertex_map_binary"), expected_count=vertex_count) or []
    if not source_vertex_map:
        source_vertex_map = list(
            _i32_range_report_values(
                item,
                start_key="source_vertex_map_start",
                count_key="source_vertex_map_count",
                max_count=1 << 30,
            )
            or ()
        )
        if source_vertex_map and len(source_vertex_map) != vertex_count:
            return None
    source_vertex_offsets = _read_i32_binary_report_payload(item.get("source_vertex_offsets_binary"), expected_count=vertex_count) or []
    if not source_vertex_offsets:
        source_vertex_offsets = list(_i32_stride_range_report_values(item, max_count=vertex_count) or ())
        if source_vertex_offsets and len(source_vertex_offsets) != vertex_count:
            return None
    submesh = SubMesh(
        name=str(metadata.get("name") or ""),
        material=str(metadata.get("material") or ""),
        texture=str(metadata.get("texture") or ""),
        vertices=list(vertices),
        uvs=list(uvs),
        normals=list(normals),
        tangents=list(tangents),
        faces=list(faces),
        bone_indices=list(bones[0]) if bones is not None else [],
        bone_weights=list(bones[1]) if bones is not None else [],
        source_vertex_map=list(source_vertex_map),
        vertex_count=len(vertices),
        face_count=len(faces),
        source_vertex_offsets=list(source_vertex_offsets),
        source_index_offset=int(metadata.get("source_index_offset") or -1),
        source_index_count=int(metadata.get("source_index_count") or 0),
        source_vertex_stride=int(metadata.get("source_vertex_stride") or 0),
        source_descriptor_offset=int(metadata.get("source_descriptor_offset") or -1),
        source_bbox_min=_vec3(metadata.get("source_bbox_min"), fallback=0.0),
        source_bbox_extent=_vec3(metadata.get("source_bbox_extent"), fallback=0.0),
        source_lod_count=int(metadata.get("source_lod_count") or 0),
    )
    if tangent_signs:
        setattr(submesh, "tangent_signs", list(tangent_signs))
    extra_attrs = metadata.get("extra_attrs")
    if isinstance(extra_attrs, Mapping):
        for raw_name, value in extra_attrs.items():
            attr_name = str(raw_name or "").strip()
            if attr_name and attr_name not in _TRANSIENT_NATIVE_SUBMESH_ATTRS:
                setattr(submesh, attr_name, _snapshot_metadata_value(value))
    provenance = _topology_provenance_from_native_snapshot_item(
        item, vertex_count=vertex_count, face_count=face_count
    )
    if provenance is None:
        # A clone re-exports from a session stored without provenance, so the
        # contract arrives through the cloned attribute instead of the binary
        # descriptors. Either way it is validated against this submesh before it
        # is trusted.
        restored = getattr(submesh, "topology_provenance", None)
        if isinstance(restored, SubmeshTopologyProvenance) and not validate_topology_provenance(
            restored, output_vertex_count=vertex_count, output_face_count=face_count
        ):
            provenance = restored
    submesh.topology_provenance = provenance
    if provenance is not None:
        # With a contract in hand the legacy map is its view, not a separate
        # claim: the single original index for a direct vertex, -1 where the
        # vertex was derived. Declaring the authority is what stops the PAC skin
        # path reading those -1 entries as donor lineage.
        submesh.source_vertex_map = list(topology_source_vertex_map(provenance))
        submesh.source_vertex_map_authority = SOURCE_VERTEX_MAP_TOPOLOGY
    return submesh


def _topology_provenance_from_native_snapshot_item(
    item: Mapping[str, object],
    *,
    vertex_count: int,
    face_count: int,
) -> object | None:
    """Rebuild the contract from its binary descriptors, or return nothing.

    Python validates the decoded arrays itself rather than trusting the report:
    a short, stale, or mismatched payload produces no contract, and the ordinary
    same-count blockers then apply.
    """
    if not bool(item.get("topology_rebuild_valid")) or vertex_count <= 0 or face_count <= 0:
        return None
    if str(item.get("topology_contract") or "") != TOPOLOGY_PROVENANCE_VERSION:
        return None
    original_vertex_count = _index(item.get("topology_original_vertex_count"))
    original_face_count = _index(item.get("topology_original_face_count"))
    if not original_vertex_count or not original_face_count:
        return None
    offsets = _read_i32_binary_report_payload(
        item.get("vertex_origin_offsets_binary"), expected_count=vertex_count + 1
    )
    if not offsets or len(offsets) != vertex_count + 1:
        return None
    parent_total = int(offsets[-1])
    if offsets[0] != 0 or parent_total <= 0:
        return None
    parents = _read_i32_binary_report_payload(item.get("vertex_origin_parents_binary"), expected_count=parent_total)
    weights = _read_f64_binary_report_payload(item.get("vertex_origin_weights_binary"), expected_count=parent_total)
    if not parents or not weights or len(parents) != parent_total or len(weights) != parent_total:
        return None
    origins: list[VertexOrigin] = []
    for index in range(vertex_count):
        start = int(offsets[index])
        end = int(offsets[index + 1])
        if start < 0 or end <= start or end > parent_total:
            return None
        try:
            origins.append(
                canonical_vertex_origin(
                    parents[start:end],
                    weights[start:end],
                    original_vertex_count=original_vertex_count,
                )
            )
        except TopologyProvenanceError:
            return None
    # Face origins index the *original* faces, so the contiguous-range form is
    # bounded by the original face count, not by the output face count. A Face
    # Delete that removes face 0 leaves origins 1..N-1, whose end value exceeds
    # the surviving face count and would otherwise be rejected as out of range.
    source_face_indices = _read_i32_binary_report_payload(
        item.get("source_face_indices_binary"), expected_count=face_count
    ) or list(
        _i32_range_report_values(
            item,
            start_key="source_face_start",
            count_key="source_face_count",
            max_count=original_face_count,
        )
        or ()
    )
    if len(source_face_indices) != face_count:
        return None
    if any(int(value) < 0 or int(value) >= original_face_count for value in source_face_indices):
        return None
    provenance = SubmeshTopologyProvenance(
        version=TOPOLOGY_PROVENANCE_VERSION,
        original_vertex_count=original_vertex_count,
        original_face_count=original_face_count,
        vertex_origins=tuple(origins),
        face_origins=tuple(int(value) for value in source_face_indices),
    )
    if validate_topology_provenance(
        provenance, output_vertex_count=vertex_count, output_face_count=face_count
    ):
        return None
    return provenance

def _mesh_session_item_from_native_snapshot(item: Mapping[str, object]) -> dict[str, object] | None:
    submesh_index = _index(item.get("index"))
    if submesh_index is None:
        return None
    session_item: dict[str, object] = {"index": submesh_index}
    for key in (
        "vertices_binary",
        "faces_binary",
        "source_face_indices_binary",
        "normals_binary",
        "uvs_binary",
        "tangents_binary",
        "tangent_signs_binary",
        "bone_counts_binary",
        "bone_indices_binary",
        "bone_weights_binary",
        "source_vertex_map_binary",
        "source_vertex_offsets_binary",
        # The contract travels with the geometry. A store that dropped it would
        # leave the next edit composing against nothing, which reads as a lost
        # rebuild rather than as the transport gap it is.
        "vertex_origin_offsets_binary",
        "vertex_origin_parents_binary",
        "vertex_origin_weights_binary",
    ):
        if isinstance(item.get(key), Mapping):
            session_item[key] = item[key]
    if all(
        key in session_item
        for key in ("vertex_origin_offsets_binary", "vertex_origin_parents_binary", "vertex_origin_weights_binary")
    ):
        session_item["topology_contract"] = str(item.get("topology_contract") or "")
        session_item["topology_original_vertex_count"] = _index(item.get("topology_original_vertex_count")) or 0
        session_item["topology_original_face_count"] = _index(item.get("topology_original_face_count")) or 0
    if "source_face_indices_binary" not in session_item:
        source_face_start = _index(item.get("source_face_start"))
        source_face_count = _index(item.get("source_face_count"))
        if source_face_start is not None and source_face_start >= 0 and source_face_count is not None and source_face_count >= 0:
            session_item["source_face_start"] = source_face_start
            session_item["source_face_count"] = source_face_count
    if "source_vertex_map_binary" not in session_item:
        source_vertex_map_start = _index(item.get("source_vertex_map_start"))
        source_vertex_map_count = _index(item.get("source_vertex_map_count"))
        if (
            source_vertex_map_start is not None
            and source_vertex_map_start >= 0
            and source_vertex_map_count is not None
            and source_vertex_map_count >= 0
        ):
            session_item["source_vertex_map_start"] = source_vertex_map_start
            session_item["source_vertex_map_count"] = source_vertex_map_count
    if "source_vertex_offsets_binary" not in session_item:
        source_vertex_offsets_start = _index(item.get("source_vertex_offsets_start"))
        source_vertex_offsets_count = _index(item.get("source_vertex_offsets_count"))
        source_vertex_offsets_stride = _index(item.get("source_vertex_offsets_stride"))
        if (
            source_vertex_offsets_start is not None
            and source_vertex_offsets_start >= 0
            and source_vertex_offsets_count is not None
            and source_vertex_offsets_count >= 0
            and source_vertex_offsets_stride is not None
            and source_vertex_offsets_stride > 0
        ):
            session_item["source_vertex_offsets_start"] = source_vertex_offsets_start
            session_item["source_vertex_offsets_count"] = source_vertex_offsets_count
            session_item["source_vertex_offsets_stride"] = source_vertex_offsets_stride
    return session_item if "vertices_binary" in session_item and "faces_binary" in session_item else None

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
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.models import RunCancelled


def _proxy(name: str):
    def call(*args, **kwargs):
        return getattr(import_module("cdmw.modding.mesh_native_core"), name)(*args, **kwargs)

    return call

_ensure_native_mesh_session_submesh = _proxy("_ensure_native_mesh_session_submesh")
_finite_float_sequence = _proxy("_finite_float_sequence")
_index = _proxy("_index")
_native_preview_delta_output_path = _proxy("_native_preview_delta_output_path")
_put_selected_vertices_payload = _proxy("_put_selected_vertices_payload")
_put_source_vertex_map_payload = _proxy("_put_source_vertex_map_payload")
_read_bone_binary_report_payloads = _proxy("_read_bone_binary_report_payloads")
_read_face_binary_report_payload = _proxy("_read_face_binary_report_payload")
_read_i32_binary_report_payload = _proxy("_read_i32_binary_report_payload")
_read_vec2_binary_report_payload = _proxy("_read_vec2_binary_report_payload")
_read_vec3_binary_report_payload = _proxy("_read_vec3_binary_report_payload")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_selected_vertex_values = _proxy("_selected_vertex_values")
_snapshot_metadata_value = _proxy("_snapshot_metadata_value")
_source_part_adjustment_payload = _proxy("_source_part_adjustment_payload")
_source_part_adjustment_pivot_vertices = _proxy("_source_part_adjustment_pivot_vertices")
_vec3 = _proxy("_vec3")
_write_bone_binary_payloads = _proxy("_write_bone_binary_payloads")
_write_face_binary_payload = _proxy("_write_face_binary_payload")
_write_vec2_binary_payload = _proxy("_write_vec2_binary_payload")
_write_vec3_binary_payload = _proxy("_write_vec3_binary_payload")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")


def _iter_valid_face_triples(faces: object) -> Iterable[tuple[int, int, int]]:
    for face in faces or ():
        if not isinstance(face, (tuple, list)) or len(face) != 3:
            continue
        try:
            yield (int(face[0]), int(face[1]), int(face[2]))
        except (TypeError, ValueError, OverflowError):
            continue

def _count_valid_face_triples(faces: object) -> int:
    return sum(1 for _face in _iter_valid_face_triples(faces))

def summarize_native_mesh_submesh_metadata(
    submeshes: Sequence[SubMesh],
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_metadata_"))
    try:
        native_items: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(submeshes or ()):
            vertices = getattr(submesh, "vertices", ()) or ()
            faces = getattr(submesh, "faces", ()) or ()
            uvs = getattr(submesh, "uvs", ()) or ()
            item: dict[str, object] = {
                "index": submesh_index,
                "vertex_count": len(vertices),
                "face_count": len(faces),
                "uv_count": len(uvs),
                "has_uvs": bool(uvs),
            }
            if vertices:
                prefix = sidecar_root / f"metadata_{submesh_index}"
                item["vertices_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_vertices.bin"),
                    vertices,
                )
            native_items.append(item)
        report = _run_native_mesh_core_job(
            binary,
            "mesh-metadata-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "mesh_metadata",
                "submeshes": native_items,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "mesh_metadata":
        return None
    return dict(report)

def summarize_native_mesh_selection_bounds(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]],
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_selection_bounds_"))
    try:
        native_items: list[dict[str, object]] = []
        for raw_submesh_index, raw_vertices in (selected_vertices_by_submesh or {}).items():
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(submesh.vertices)
            selected = _selected_vertex_values(raw_vertices, vertex_count)
            if not selected:
                continue
            prefix = sidecar_root / f"selection_bounds_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
            }
            _put_selected_vertices_payload(item, prefix, selected, max_count=vertex_count)
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                item["vertices_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_vertices.bin"),
                    submesh.vertices,
                )
            native_items.append(item)
        if not native_items:
            return {
                "operation": "selection_bounds",
                "selected_vertex_count": 0,
                "has_bounds": False,
                "bbox_min": [0.0, 0.0, 0.0],
                "bbox_max": [0.0, 0.0, 0.0],
                "submeshes": [],
            }
        report = _run_native_mesh_core_job(
            binary,
            "selection-bounds-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "selection_bounds",
                "submeshes": native_items,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "selection_bounds":
        return None
    return dict(report)

def merge_native_mesh_submeshes(
    submeshes: Sequence[SubMesh],
    *,
    timeout_seconds: float = 5.0,
) -> SubMesh | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_merge_submeshes_"))
    try:
        native_items: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(submeshes or ()):
            vertices = getattr(submesh, "vertices", ()) or ()
            faces = getattr(submesh, "faces", ()) or ()
            prefix = sidecar_root / f"merge_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertices_binary": _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices),
                "faces_binary": _write_face_binary_payload(
                    prefix.with_name(prefix.name + "_faces.bin"),
                    _iter_valid_face_triples(faces),
                ),
            }
            normals = getattr(submesh, "normals", ()) or ()
            if len(normals) == len(vertices):
                item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), normals)
            uvs = getattr(submesh, "uvs", ()) or ()
            if len(uvs) == len(vertices):
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
            native_items.append(item)
        report = _run_native_mesh_core_job(
            binary,
            "merge-submeshes-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "merge_submeshes",
                "vertices_output_path": _native_preview_delta_output_path("_merge_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_merge_faces.bin"),
                "normals_output_path": _native_preview_delta_output_path("_merge_normals.bin"),
                "uvs_output_path": _native_preview_delta_output_path("_merge_uvs.bin"),
                "submeshes": native_items,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "merge_submeshes":
        return None
    vertex_count = _index(report.get("vertex_count"))
    face_count = _index(report.get("face_count"))
    if vertex_count is None or face_count is None or vertex_count < 0 or face_count < 0:
        return None
    vertices = _read_vec3_binary_report_payload(report.get("vertices_binary"), expected_count=vertex_count)
    faces = _read_face_binary_report_payload(report.get("faces_binary"), expected_count=face_count, vertex_count=vertex_count)
    normals = _read_vec3_binary_report_payload(report.get("normals_binary"), expected_count=vertex_count) or []
    uvs = _read_vec2_binary_report_payload(report.get("uvs_binary"), expected_count=vertex_count) or []
    if vertices is None or faces is None:
        return None
    return SubMesh(
        vertices=list(vertices),
        faces=list(faces),
        normals=list(normals),
        uvs=list(uvs),
        vertex_count=vertex_count,
        face_count=face_count,
    )

def decimate_native_mesh_preview_submeshes(
    submeshes: list[SubMesh],
    max_faces: int,
    *,
    timeout_seconds: float = 5.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    try:
        face_limit = int(max_faces)
    except (TypeError, ValueError):
        return None
    if face_limit <= 0:
        return set()
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_preview_decimate_"))
    try:
        native_items: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(submeshes or ()):
            vertices = getattr(submesh, "vertices", ()) or ()
            faces = getattr(submesh, "faces", ()) or ()
            try:
                face_count = len(faces)
            except TypeError:
                face_count = _count_valid_face_triples(faces)
            if not vertices or face_count <= face_limit:
                continue
            prefix = sidecar_root / f"decimate_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "max_faces": face_limit,
                "vertices_binary": _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices),
                "faces_binary": _write_face_binary_payload(
                    prefix.with_name(prefix.name + "_faces.bin"),
                    _iter_valid_face_triples(faces),
                ),
                "vertices_output_path": _native_preview_delta_output_path("_preview_decimate_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_preview_decimate_faces.bin"),
                "uvs_output_path": _native_preview_delta_output_path("_preview_decimate_uvs.bin"),
                "normals_output_path": _native_preview_delta_output_path("_preview_decimate_normals.bin"),
                "bone_counts_output_path": _native_preview_delta_output_path("_preview_decimate_bone_counts.bin"),
                "bone_indices_output_path": _native_preview_delta_output_path("_preview_decimate_bone_indices.bin"),
                "bone_weights_output_path": _native_preview_delta_output_path("_preview_decimate_bone_weights.bin"),
                "source_vertex_map_output_path": _native_preview_delta_output_path("_preview_decimate_source_map.bin"),
            }
            uvs = getattr(submesh, "uvs", ()) or ()
            if len(uvs) == len(vertices):
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
            normals = getattr(submesh, "normals", ()) or ()
            if len(normals) == len(vertices):
                item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), normals)
            bone_payloads = _write_bone_binary_payloads(
                prefix,
                getattr(submesh, "bone_indices", None),
                getattr(submesh, "bone_weights", None),
            )
            if bone_payloads is not None:
                item.update(bone_payloads)
            source_vertex_map = getattr(submesh, "source_vertex_map", ()) or ()
            if len(source_vertex_map) == len(vertices):
                _put_source_vertex_map_payload(item, prefix, source_vertex_map)
            native_items.append(item)
        if not native_items:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "preview-decimate-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "preview_decimate",
                "submeshes": native_items,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "preview_decimate":
        return None
    raw_items = report.get("submeshes")
    if not isinstance(raw_items, list):
        return None
    from .static_mesh_clone import _clone_submesh_fast

    changed: set[int] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        submesh_index = _index(raw_item.get("index"))
        vertex_count = _index(raw_item.get("vertex_count"))
        face_count = _index(raw_item.get("face_count"))
        if (
            submesh_index is None
            or vertex_count is None
            or face_count is None
            or not 0 <= submesh_index < len(submeshes)
            or vertex_count <= 0
            or face_count <= 0
        ):
            continue
        vertices = _read_vec3_binary_report_payload(raw_item.get("vertices_binary"), expected_count=vertex_count)
        faces = _read_face_binary_report_payload(raw_item.get("faces_binary"), expected_count=face_count, vertex_count=vertex_count)
        if vertices is None or faces is None:
            return None
        source = submeshes[submesh_index]
        preview = _clone_submesh_fast(source)
        preview.vertices = list(vertices)
        preview.faces = list(faces)
        preview.uvs = _read_vec2_binary_report_payload(raw_item.get("uvs_binary"), expected_count=vertex_count) or []
        preview.normals = _read_vec3_binary_report_payload(raw_item.get("normals_binary"), expected_count=vertex_count) or []
        bones = _read_bone_binary_report_payloads(
            raw_item.get("bone_counts_binary"),
            raw_item.get("bone_indices_binary"),
            raw_item.get("bone_weights_binary"),
            expected_count=vertex_count,
        )
        if bones is None:
            preview.bone_indices = []
            preview.bone_weights = []
        else:
            preview.bone_indices = list(bones[0])
            preview.bone_weights = list(bones[1])
        preview.source_vertex_map = (
            _read_i32_binary_report_payload(raw_item.get("source_vertex_map_binary"), expected_count=vertex_count) or []
        )
        preview.vertex_count = len(preview.vertices)
        preview.face_count = len(preview.faces)
        preview.source_vertex_offsets = []
        preview.source_index_offset = -1
        preview.source_index_count = len(preview.faces) * 3
        submeshes[submesh_index] = preview
        changed.add(submesh_index)
    return changed

def apply_native_mesh_affine_transform_submeshes(
    submeshes: Sequence[SubMesh],
    *,
    position_matrices_by_index: Mapping[int, Sequence[float]] | None = None,
    normal_matrices_by_index: Mapping[int, Sequence[float]] | None = None,
    source_part_adjustments_by_index: Mapping[int, object] | None = None,
    reverse_face_winding_by_index: Mapping[int, bool] | None = None,
    mirror_x_around_bounds_center_by_index: Mapping[int, bool] | None = None,
    timeout_seconds: float = 5.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    position_matrices = position_matrices_by_index or {}
    normal_matrices = normal_matrices_by_index or {}
    source_part_adjustments = source_part_adjustments_by_index or {}
    reverse_faces = reverse_face_winding_by_index or {}
    mirror_x = mirror_x_around_bounds_center_by_index or {}
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_affine_transform_"))
    try:
        native_items: list[dict[str, object]] = []
        requested_indices = {
            raw_index
            for mapping in (position_matrices, source_part_adjustments, mirror_x)
            for raw_index in mapping.keys()
        }
        for raw_submesh_index in sorted(requested_indices, key=lambda value: str(value)):
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(submeshes):
                continue
            matrix: tuple[float, ...] | None = None
            if raw_submesh_index in position_matrices or submesh_index in position_matrices:
                raw_matrix = position_matrices.get(raw_submesh_index, position_matrices.get(submesh_index))
                matrix = _finite_float_sequence(raw_matrix, expected_count=12)
            raw_adjustment = source_part_adjustments.get(raw_submesh_index, source_part_adjustments.get(submesh_index))
            adjustment_payload = _source_part_adjustment_payload(raw_adjustment)
            if matrix is None and adjustment_payload is None:
                return None
            submesh = submeshes[submesh_index]
            vertices = getattr(submesh, "vertices", ()) or ()
            if not vertices:
                continue
            prefix = sidecar_root / f"affine_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertices_binary": _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices),
                "vertices_output_path": _native_preview_delta_output_path("_affine_vertices.bin"),
            }
            if matrix is not None:
                item["position_matrix"] = list(matrix)
            if adjustment_payload is not None:
                pivot_vertices = _source_part_adjustment_pivot_vertices(raw_adjustment)
                if pivot_vertices:
                    adjustment_payload["pivot_vertices_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_pivot_vertices.bin"),
                        pivot_vertices,
                    )
                item["source_part_adjustment"] = adjustment_payload
            mirror_after_transform = bool(mirror_x.get(raw_submesh_index, mirror_x.get(submesh_index, False)))
            if mirror_after_transform:
                item["mirror_x_around_bounds_center"] = True
            normals = getattr(submesh, "normals", ()) or ()
            normal_matrix = _finite_float_sequence(normal_matrices.get(submesh_index), expected_count=9)
            if len(normals) == len(vertices) and (normal_matrix is not None or adjustment_payload is not None):
                if normal_matrix is not None:
                    item["normal_matrix"] = list(normal_matrix)
                item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), normals)
                item["normals_output_path"] = _native_preview_delta_output_path("_affine_normals.bin")
            if mirror_after_transform or bool(reverse_faces.get(submesh_index, reverse_faces.get(str(submesh_index), False))):
                faces = getattr(submesh, "faces", ()) or ()
                if faces:
                    item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                    item["faces_output_path"] = _native_preview_delta_output_path("_affine_faces.bin")
                    if bool(reverse_faces.get(submesh_index, reverse_faces.get(str(submesh_index), False))):
                        item["reverse_face_winding"] = True
            native_items.append(item)
        if not native_items:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "affine-transform-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "affine_transform",
                "submeshes": native_items,
            },
            timeout_seconds=timeout_seconds,
        )
    except (IndexError, OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "affine_transform":
        return None
    raw_items = report.get("submeshes")
    if not isinstance(raw_items, list):
        return None
    changed: set[int] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        submesh_index = _index(raw_item.get("index"))
        vertex_count = _index(raw_item.get("vertex_count"))
        if submesh_index is None or vertex_count is None or not 0 <= submesh_index < len(submeshes):
            continue
        submesh = submeshes[submesh_index]
        vertices = _read_vec3_binary_report_payload(raw_item.get("vertices_binary"), expected_count=vertex_count)
        if vertices is None:
            return None
        submesh.vertices = list(vertices)
        submesh.vertex_count = len(vertices)
        normals = _read_vec3_binary_report_payload(raw_item.get("normals_binary"), expected_count=vertex_count)
        if normals is not None:
            submesh.normals = list(normals)
        face_count = _index(raw_item.get("face_count"))
        if face_count is not None:
            faces = _read_face_binary_report_payload(
                raw_item.get("faces_binary"),
                expected_count=face_count,
                vertex_count=vertex_count,
            )
            if faces is None:
                return None
            submesh.faces = list(faces)
            submesh.face_count = len(faces)
        else:
            submesh.face_count = len(getattr(submesh, "faces", ()) or ())
        changed.add(submesh_index)
    return changed

def clone_native_mesh_affine_transformed_submesh(
    submesh: object,
    *,
    source_part_adjustment: object | None = None,
    position_matrix: Sequence[float] | None = None,
    normal_matrix: Sequence[float] | None = None,
    reverse_face_winding: bool = False,
    mirror_x_around_bounds_center: bool = False,
    timeout_seconds: float = 5.0,
) -> SubMesh | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    adjustment_payload = _source_part_adjustment_payload(source_part_adjustment)
    parsed_position_matrix = _finite_float_sequence(position_matrix, expected_count=12)
    parsed_normal_matrix = _finite_float_sequence(normal_matrix, expected_count=9)
    if adjustment_payload is None and parsed_position_matrix is None:
        return None
    vertices = getattr(submesh, "vertices", ()) or ()
    if not vertices:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_affine_clone_"))
    try:
        prefix = sidecar_root / "affine_clone_0"
        item: dict[str, object] = {
            "index": 0,
            "vertices_binary": _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices),
            "vertices_output_path": _native_preview_delta_output_path("_affine_clone_vertices.bin"),
        }
        if parsed_position_matrix is not None:
            item["position_matrix"] = list(parsed_position_matrix)
        if adjustment_payload is not None:
            item["source_part_adjustment"] = adjustment_payload
            pivot_vertices = _source_part_adjustment_pivot_vertices(source_part_adjustment)
            if pivot_vertices:
                adjustment_payload["pivot_vertices_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_pivot_vertices.bin"),
                    pivot_vertices,
                )
        normals = getattr(submesh, "normals", ()) or ()
        if len(normals) == len(vertices) and (adjustment_payload is not None or parsed_normal_matrix is not None):
            item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), normals)
            item["normals_output_path"] = _native_preview_delta_output_path("_affine_clone_normals.bin")
            if parsed_normal_matrix is not None:
                item["normal_matrix"] = list(parsed_normal_matrix)
        faces = getattr(submesh, "faces", ()) or ()
        if faces:
            item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            item["faces_output_path"] = _native_preview_delta_output_path("_affine_clone_faces.bin")
            if reverse_face_winding:
                item["reverse_face_winding"] = True
        if mirror_x_around_bounds_center:
            item["mirror_x_around_bounds_center"] = True
        report = _run_native_mesh_core_job(
            binary,
            "affine-transform-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "affine_transform",
                "submeshes": [item],
            },
            timeout_seconds=timeout_seconds,
        )
    except (IndexError, OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "affine_transform":
        return None
    raw_items = report.get("submeshes")
    if not isinstance(raw_items, list) or not raw_items or not isinstance(raw_items[0], Mapping):
        return None
    raw_item = raw_items[0]
    vertex_count = _index(raw_item.get("vertex_count"))
    if vertex_count is None:
        return None
    transformed_vertices = _read_vec3_binary_report_payload(raw_item.get("vertices_binary"), expected_count=vertex_count)
    if transformed_vertices is None:
        return None
    transformed_normals = _read_vec3_binary_report_payload(raw_item.get("normals_binary"), expected_count=vertex_count)
    normals = list(transformed_normals) if transformed_normals is not None else list(getattr(submesh, "normals", ()) or ())
    face_count = _index(raw_item.get("face_count"))
    transformed_faces = None
    if face_count is not None:
        transformed_faces = _read_face_binary_report_payload(
            raw_item.get("faces_binary"),
            expected_count=face_count,
            vertex_count=vertex_count,
        )
        if transformed_faces is None:
            return None
    source_faces = getattr(submesh, "faces", ()) or ()
    cloned = SubMesh(
        name=str(getattr(submesh, "name", "") or ""),
        material=str(getattr(submesh, "material", "") or ""),
        texture=str(getattr(submesh, "texture", "") or ""),
        vertices=list(transformed_vertices),
        uvs=list(getattr(submesh, "uvs", ()) or ()),
        normals=normals,
        tangents=list(getattr(submesh, "tangents", ()) or ()),
        faces=[tuple(face) for face in (transformed_faces if transformed_faces is not None else source_faces)],
        bone_indices=list(getattr(submesh, "bone_indices", ()) or ()),
        bone_weights=list(getattr(submesh, "bone_weights", ()) or ()),
        source_vertex_map=list(getattr(submesh, "source_vertex_map", ()) or ()),
        vertex_count=len(transformed_vertices),
        face_count=len(transformed_faces) if transformed_faces is not None else len(source_faces),
        source_vertex_offsets=list(getattr(submesh, "source_vertex_offsets", ()) or ()),
        source_index_offset=int(getattr(submesh, "source_index_offset", -1) or -1),
        source_index_count=int(getattr(submesh, "source_index_count", 0) or 0),
        source_vertex_stride=int(getattr(submesh, "source_vertex_stride", 0) or 0),
        source_descriptor_offset=int(getattr(submesh, "source_descriptor_offset", -1) or -1),
        source_bbox_min=_vec3(getattr(submesh, "source_bbox_min", (0.0, 0.0, 0.0)), fallback=0.0),
        source_bbox_extent=_vec3(getattr(submesh, "source_bbox_extent", (0.0, 0.0, 0.0)), fallback=0.0),
        source_lod_count=int(getattr(submesh, "source_lod_count", 0) or 0),
    )
    for attr_name in _EXTRA_SUBMESH_ATTRS:
        if hasattr(submesh, attr_name):
            setattr(cloned, attr_name, _snapshot_metadata_value(getattr(submesh, attr_name)))
    return cloned

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

from cdmw.modding.mesh_deformer import MeshFaceDeleteResult, MeshPartSplitResult
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

_changed_vertices_for_report = _proxy("_changed_vertices_for_report")
_changed_vertices_from_report_item = _proxy("_changed_vertices_from_report_item")
_ensure_native_mesh_session_submesh = _proxy("_ensure_native_mesh_session_submesh")
_face_json = _proxy("_face_json")
_finite_float = _proxy("_finite_float")
_index = _proxy("_index")
_invalidate_native_mesh_session_submeshes = _proxy("_invalidate_native_mesh_session_submeshes")
_mark_native_mesh_session_submeshes_current = _proxy("_mark_native_mesh_session_submeshes_current")
_native_binary_descriptor = _proxy("_native_binary_descriptor")
_put_selected_vertices_payload = _proxy("_put_selected_vertices_payload")
_put_source_vertex_map_payload = _proxy("_put_source_vertex_map_payload")
_read_bone_binary_report_payloads = _proxy("_read_bone_binary_report_payloads")
_read_vec3_binary_report_payload = _proxy("_read_vec3_binary_report_payload")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_selected_vertex_values = _proxy("_selected_vertex_values")
_vec3 = _proxy("_vec3")
_vec3_json = _proxy("_vec3_json")
_write_bone_binary_payloads = _proxy("_write_bone_binary_payloads")
_write_face_binary_payload = _proxy("_write_face_binary_payload")
_write_int_binary_payload = _proxy("_write_int_binary_payload")
_write_vec3_binary_payload = _proxy("_write_vec3_binary_payload")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")
write_native_preview_geometry_blob = _proxy("write_native_preview_geometry_blob")


def _apply_native_skin_weight_report(
    mesh: ParsedMesh,
    report: Mapping[str, object],
    expected_counts: Mapping[int, int],
    transfer_report: dict[str, object] | None = None,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]]:
    raw_reports = report.get("submeshes")
    if not isinstance(raw_reports, list):
        raise ValueError("invalid native skin weight reports")
    transfer_metrics: list[dict[str, object]] = []
    for item in raw_reports:
        if not isinstance(item, Mapping) or "transfer_distance_p95" not in item:
            continue
        try:
            distance_p95 = float(item.get("transfer_distance_p95") or 0.0)
            distance_limit = float(item.get("transfer_distance_limit") or 0.0)
        except (TypeError, ValueError, OverflowError):
            distance_p95 = distance_limit = 0.0
        transfer_metrics.append({
            "index": _index(item.get("index")),
            "distance_p95": distance_p95,
            "distance_limit": distance_limit,
            "distance_warning": bool(item.get("transfer_distance_warning")),
        })
    if transfer_report is not None:
        transfer_report.clear()
        transfer_report.update({
            "backend": str(report.get("backend") or NATIVE_MESH_CORE_BACKEND_ID),
            "submeshes": transfer_metrics,
            "distance_warning": any(bool(item["distance_warning"]) for item in transfer_metrics),
        })
    if any(bool(item["distance_warning"]) for item in transfer_metrics):
        raise ValueError("native skin weight transfer exceeds the 5% source-bounds distance limit")
    affected: set[int] = set()
    changed_vertices_by_submesh: dict[int, Sequence[int] | set[int]] = {}
    for raw_item in raw_reports:
        if not isinstance(raw_item, Mapping):
            raise ValueError("invalid native skin weight report")
        submesh_index = _index(raw_item.get("index"))
        if submesh_index is None or submesh_index not in expected_counts:
            raise ValueError("invalid native skin weight submesh")
        vertex_count = _index(raw_item.get("vertex_count"))
        if vertex_count is None or vertex_count != expected_counts[submesh_index]:
            raise ValueError("invalid native skin weight vertex count")
        changed_count = _index(raw_item.get("changed_count"))
        if changed_count is None or changed_count < 0:
            raise ValueError("invalid native skin weight changed count")
        changed_vertices = _changed_vertices_from_report_item(raw_item, vertex_count)
        if (
            changed_vertices is None
            or len(changed_vertices) != changed_count
        ):
            raise ValueError("invalid native skin weight changed vertices")
        bones = _read_bone_binary_report_payloads(
            raw_item.get("bone_counts_binary"),
            raw_item.get("bone_indices_binary"),
            raw_item.get("bone_weights_binary"),
            expected_count=vertex_count,
        )
        if bones is None:
            raise ValueError("invalid native skin weight bones")
        bone_indices, bone_weights = bones
        submesh = mesh.submeshes[submesh_index]
        submesh.bone_indices = list(bone_indices)
        submesh.bone_weights = list(bone_weights)
        affected.add(submesh_index)
        changed_vertices_by_submesh[submesh_index] = _changed_vertices_for_report(changed_vertices)
    if affected:
        _mark_native_mesh_session_submeshes_current(mesh, affected)
    return affected, changed_vertices_by_submesh

def _native_pose_preview_bones_payload(skeleton: object) -> list[dict[str, object]]:
    bones: list[dict[str, object]] = []
    for ordinal, bone in enumerate(tuple(getattr(skeleton, "bones", ()) or ())):
        index = _index(getattr(bone, "index", ordinal))
        if index is None or index < 0:
            index = ordinal
        parent_index = _index(getattr(bone, "parent_index", -1))
        if parent_index is None:
            parent_index = -1
        item: dict[str, object] = {
            "index": int(index),
            "parent_index": int(parent_index),
            "position": _vec3_json(getattr(bone, "position", (0.0, 0.0, 0.0))),
        }
        bind_matrix = _native_pose_preview_matrix_payload(getattr(bone, "bind_matrix", ()))
        if bind_matrix is not None:
            item["bind_matrix"] = bind_matrix
        inv_bind_matrix = _native_pose_preview_matrix_payload(getattr(bone, "inv_bind_matrix", ()))
        if inv_bind_matrix is not None:
            item["inv_bind_matrix"] = inv_bind_matrix
        bones.append(item)
    return bones

def _native_pose_preview_matrix_payload(value: object) -> list[float] | None:
    try:
        raw = tuple(float(component) for component in value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    if len(raw) != 16 or any(not math.isfinite(component) for component in raw):
        return None
    if not any(abs(component) > 1e-12 for component in raw):
        return None
    return list(raw)

def _native_pose_preview_rotations_payload(
    pose_rotations: Mapping[int, Sequence[object]] | Mapping[object, object] | None,
) -> list[dict[str, object]]:
    rotations: list[dict[str, object]] = []
    for raw_index, raw_rotation in dict(pose_rotations or {}).items():
        index = _index(raw_index)
        if index is None or index < 0:
            continue
        rotation = _vec3(raw_rotation)
        if not any(abs(component) > 1e-6 for component in rotation):
            continue
        rotations.append({"bone_index": int(index), "rotation_degrees": [rotation[0], rotation[1], rotation[2]]})
    return rotations

def apply_native_mesh_pose_preview(
    mesh: ParsedMesh,
    skeleton: object | None,
    pose_rotations: Mapping[int, Sequence[object]] | Mapping[object, object] | None,
    *,
    timeout_seconds: float = 20.0,
) -> dict[int, tuple[Vec3, ...]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None or not isinstance(mesh, ParsedMesh) or skeleton is None:
        return None
    bones = _native_pose_preview_bones_payload(skeleton)
    rotations = _native_pose_preview_rotations_payload(pose_rotations)
    if not bones or not rotations:
        return {}

    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_pose_preview_"))
    sent_indices: set[int] = set()
    expected_counts: dict[int, int] = {}
    try:
        submeshes: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0:
                continue
            if (
                len(getattr(submesh, "bone_indices", ()) or ()) != vertex_count
                or len(getattr(submesh, "bone_weights", ()) or ()) != vertex_count
            ):
                continue
            prefix = sidecar_root / f"submesh_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertex_count": vertex_count,
                "vertices_output_path": str(prefix.with_name(prefix.name + "_vertices.bin")),
                "changed_vertices_output_path": str(prefix.with_name(prefix.name + "_changed_vertices.bin")),
            }
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
                    prefix.with_name(prefix.name + "_input_vertices.bin"),
                    getattr(submesh, "vertices", ()) or (),
                )
                bone_payload = _write_bone_binary_payloads(
                    prefix,
                    getattr(submesh, "bone_indices", ()) or (),
                    getattr(submesh, "bone_weights", ()) or (),
                )
                if bone_payload is None:
                    continue
                item.update(bone_payload)
            submeshes.append(item)
            sent_indices.add(submesh_index)
            expected_counts[submesh_index] = vertex_count
        if not submeshes:
            return {}

        report = _run_native_mesh_core_job(
            binary,
            "pose-preview-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "bones": bones,
                "rotations": rotations,
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            _invalidate_native_mesh_session_submeshes(mesh, sent_indices)
            return None
        raw_reports = report.get("submeshes")
        if not isinstance(raw_reports, list):
            return None
        deformed: dict[int, tuple[Vec3, ...]] = {}
        for raw_item in raw_reports:
            if not isinstance(raw_item, Mapping):
                return None
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or submesh_index not in expected_counts:
                return None
            vertex_count = _index(raw_item.get("vertex_count"))
            if vertex_count is None or vertex_count != expected_counts[submesh_index]:
                return None
            changed_count = _index(raw_item.get("changed_count"))
            changed_vertices = _changed_vertices_from_report_item(raw_item, vertex_count)
            if changed_count is None or changed_vertices is None or len(changed_vertices) != changed_count:
                return None
            vertices = _read_vec3_binary_report_payload(raw_item.get("vertices_binary"), expected_count=vertex_count)
            if vertices is None:
                return None
            deformed[submesh_index] = tuple(vertices)
        return deformed
    except (OSError, OverflowError, RuntimeError, ValueError):
        _invalidate_native_mesh_session_submeshes(mesh, sent_indices)
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def write_native_pose_preview_geometry_blob(
    output_path: Path | str,
    *,
    mesh: ParsedMesh,
    skeleton: object | None,
    pose_rotations: Mapping[int, Sequence[object]] | Mapping[object, object] | None,
    identity_output_path: Path | str | None = None,
    timeout_seconds: float = 20.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None or not isinstance(mesh, ParsedMesh) or skeleton is None:
        return None
    bones = _native_pose_preview_bones_payload(skeleton)
    rotations = _native_pose_preview_rotations_payload(pose_rotations)
    if not bones or not rotations:
        return None
    path = Path(output_path)
    pose_sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_pose_preview_geometry_"))
    sent_indices: set[int] = set()
    try:
        pose_submeshes: list[dict[str, object]] = []
        session_ids: dict[int, str] = {}
        expected_counts: dict[int, int] = {}
        for submesh_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0:
                continue
            if (
                len(getattr(submesh, "bone_indices", ()) or ()) != vertex_count
                or len(getattr(submesh, "bone_weights", ()) or ()) != vertex_count
            ):
                continue
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                _invalidate_native_mesh_session_submeshes(mesh, (submesh_index,))
                return None
            prefix = pose_sidecar_root / f"submesh_{submesh_index}"
            pose_submeshes.append(
                {
                    "index": submesh_index,
                    "vertex_count": vertex_count,
                    "session_id": session_id,
                    "vertices_output_path": str(prefix.with_name(prefix.name + "_vertices.bin")),
                    "changed_vertices_output_path": str(prefix.with_name(prefix.name + "_changed_vertices.bin")),
                }
            )
            session_ids[submesh_index] = session_id
            expected_counts[submesh_index] = vertex_count
            sent_indices.add(submesh_index)
        if not pose_submeshes:
            return None
        pose_report = _run_native_mesh_core_job(
            binary,
            "pose-preview-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "bones": bones,
                "rotations": rotations,
                "submeshes": pose_submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if pose_report is None:
            _invalidate_native_mesh_session_submeshes(mesh, sent_indices)
            return None
        raw_reports = pose_report.get("submeshes")
        if not isinstance(raw_reports, list):
            return None
        preview_meshes: list[dict[str, object]] = []
        for raw_item in raw_reports:
            if not isinstance(raw_item, Mapping):
                return None
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or submesh_index not in expected_counts:
                return None
            vertex_count = _index(raw_item.get("vertex_count"))
            if vertex_count is None or vertex_count != expected_counts[submesh_index]:
                return None
            positions_binary = _native_binary_descriptor(
                raw_item.get("vertices_binary"),
                expected_count=vertex_count,
                components=3,
                kind="f64",
            )
            if positions_binary is None:
                return None
            preview_meshes.append(
                {
                    "index": submesh_index,
                    "source_submesh_index": submesh_index,
                    "session_id": session_ids[submesh_index],
                    "positions_binary": positions_binary,
                    "color": (0.25, 0.55, 0.85),
                }
            )
        if not preview_meshes:
            return None
        return write_native_preview_geometry_blob(
            path,
            meshes=preview_meshes,
            identity_output_path=identity_output_path,
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        _invalidate_native_mesh_session_submeshes(mesh, sent_indices)
        return None
    finally:
        shutil.rmtree(pose_sidecar_root, ignore_errors=True)

def apply_native_mesh_skin_weights(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Mapping[object, object],
    *,
    operation: str,
    bone_index: int = -1,
    delta: float = 0.0,
    timeout_seconds: float = 20.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    operation = str(operation or "").strip().lower()
    if operation not in {"adjust", "normalize"}:
        return None
    if operation == "adjust" and int(bone_index) < 0:
        return None
    if not isinstance(mesh, ParsedMesh):
        return None

    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_skin_weights_"))
    sent_indices: set[int] = set()
    try:
        submeshes: list[dict[str, object]] = []
        expected_counts: dict[int, int] = {}
        for raw_submesh_index, raw_vertices in (selected_vertices_by_submesh or {}).items():
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0:
                continue
            selected = _selected_vertex_values(raw_vertices, vertex_count)
            if not selected:
                continue
            prefix = sidecar_root / f"submesh_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertex_count": vertex_count,
                "changed_vertices_output_path": str(prefix.with_name(prefix.name + "_changed_vertices.bin")),
                "bone_counts_output_path": str(prefix.with_name(prefix.name + "_bone_counts.bin")),
                "bone_indices_output_path": str(prefix.with_name(prefix.name + "_bone_indices.bin")),
                "bone_weights_output_path": str(prefix.with_name(prefix.name + "_bone_weights.bin")),
            }
            _put_selected_vertices_payload(item, prefix, selected, max_count=vertex_count)
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                _invalidate_native_mesh_session_submeshes(mesh, (submesh_index,))
                return None
            item["session_id"] = session_id
            submeshes.append(item)
            sent_indices.add(submesh_index)
            expected_counts[submesh_index] = vertex_count
        if not submeshes:
            return set(), {}

        report = _run_native_mesh_core_job(
            binary,
            "skin-weights-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": operation,
                "bone_index": int(bone_index),
                "delta": _finite_float(delta, 0.0),
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            _invalidate_native_mesh_session_submeshes(mesh, sent_indices)
            return None
        return _apply_native_skin_weight_report(mesh, report, expected_counts)
    except (OSError, OverflowError, RuntimeError, ValueError):
        _invalidate_native_mesh_session_submeshes(mesh, sent_indices)
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def _native_skin_transfer_selection(
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Mapping[object, object],
    selected_all_submeshes: Iterable[int],
) -> tuple[Mapping[object, object], set[int], set[int]]:
    selected_map = selected_vertices_by_submesh if isinstance(selected_vertices_by_submesh, Mapping) else {}
    selected_all = {
        index
        for value in (selected_all_submeshes if selected_all_submeshes is not None else ())
        if (index := _index(value)) is not None
    }
    target_indices = set(selected_all)
    target_indices.update(index for raw in selected_map if (index := _index(raw)) is not None)
    return selected_map, selected_all, target_indices

def transfer_native_mesh_skin_weights_from_source(
    target_mesh: ParsedMesh,
    source_mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Mapping[object, object],
    selected_all_submeshes: Iterable[int] = (),
    *,
    bone_remap: Mapping[int, int] | None = None,
    source_vertex_map_is_donor_lineage: bool = True,
    transfer_report: dict[str, object] | None = None,
    timeout_seconds: float = 20.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if transfer_report is not None:
        transfer_report.clear()
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    if not isinstance(target_mesh, ParsedMesh) or not isinstance(source_mesh, ParsedMesh):
        return None

    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_skin_transfer_"))
    sent_indices: set[int] = set()
    try:
        selected_map, selected_all, target_indices = _native_skin_transfer_selection(selected_vertices_by_submesh, selected_all_submeshes)
        submeshes: list[dict[str, object]] = []
        expected_counts: dict[int, int] = {}
        for submesh_index in sorted(target_indices):
            if not 0 <= submesh_index < len(target_mesh.submeshes):
                continue
            if not 0 <= submesh_index < len(source_mesh.submeshes):
                continue
            target = target_mesh.submeshes[submesh_index]
            source = source_mesh.submeshes[submesh_index]
            target_vertices = getattr(target, "vertices", ()) or ()
            source_vertices = getattr(source, "vertices", ()) or ()
            target_vertex_count = len(target_vertices)
            source_vertex_count = len(source_vertices)
            if target_vertex_count <= 0 or source_vertex_count <= 0:
                continue
            source_bone_indices = list(getattr(source, "bone_indices", ()) or ())
            source_bone_weights = list(getattr(source, "bone_weights", ()) or ())
            if not source_bone_indices or not source_bone_weights:
                continue
            if len(source_bone_indices) < source_vertex_count:
                source_bone_indices.extend([()] * (source_vertex_count - len(source_bone_indices)))
            if len(source_bone_weights) < source_vertex_count:
                source_bone_weights.extend([()] * (source_vertex_count - len(source_bone_weights)))
            source_bone_indices = source_bone_indices[:source_vertex_count]
            source_bone_weights = source_bone_weights[:source_vertex_count]

            if submesh_index in selected_all:
                selected_all_vertices = True
            else:
                selected_all_vertices = False
                raw_values = selected_map.get(submesh_index, selected_map.get(str(submesh_index), ()))
                selected = _selected_vertex_values(raw_values, target_vertex_count)
                if not selected:
                    continue

            prefix = sidecar_root / f"submesh_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertex_count": target_vertex_count,
                "source_vertices_binary": _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_source_vertices.bin"),
                    source_vertices,
                ),
                "source_faces_binary": _write_face_binary_payload(prefix.with_name(prefix.name + "_source_faces.bin"), getattr(source, "faces", ()) or ()),
                "changed_vertices_output_path": str(prefix.with_name(prefix.name + "_changed_vertices.bin")),
                "bone_counts_output_path": str(prefix.with_name(prefix.name + "_bone_counts.bin")),
                "bone_indices_output_path": str(prefix.with_name(prefix.name + "_bone_indices.bin")),
                "bone_weights_output_path": str(prefix.with_name(prefix.name + "_bone_weights.bin")),
            }
            source_bone_payload = _write_bone_binary_payloads(
                prefix.with_name(prefix.name + "_source"),
                source_bone_indices,
                source_bone_weights,
            )
            if source_bone_payload is None:
                continue
            item["source_bone_counts_binary"] = source_bone_payload["bone_counts_binary"]
            item["source_bone_indices_binary"] = source_bone_payload["bone_indices_binary"]
            item["source_bone_weights_binary"] = source_bone_payload["bone_weights_binary"]
            if selected_all_vertices:
                item["selected_all_vertices"] = True
            else:
                _put_selected_vertices_payload(item, prefix, selected, max_count=target_vertex_count)
            if bone_remap is not None:
                pairs = sorted(
                    (int(source_bone), int(target_bone))
                    for source_bone, target_bone in dict(bone_remap).items()
                    if int(source_bone) >= 0 and int(target_bone) >= 0
                )
                item["bone_remap_enabled"] = True
                item["bone_remap_source_binary"] = _write_int_binary_payload(
                    prefix.with_name(prefix.name + "_bone_remap_source.bin"),
                    [source_bone for source_bone, _target_bone in pairs],
                )
                item["bone_remap_target_binary"] = _write_int_binary_payload(
                    prefix.with_name(prefix.name + "_bone_remap_target.bin"),
                    [target_bone for _source_bone, target_bone in pairs],
                )
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                target_mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                _invalidate_native_mesh_session_submeshes(target_mesh, (submesh_index,))
                return None
            item["session_id"] = session_id
            item["source_vertex_map_is_donor_lineage"] = bool(source_vertex_map_is_donor_lineage)
            if source_vertex_map_is_donor_lineage:
                source_vertex_map = getattr(target, "source_vertex_map", ()) or ()
                if len(source_vertex_map) == target_vertex_count:
                    _put_source_vertex_map_payload(item, prefix, source_vertex_map)
            submeshes.append(item)
            sent_indices.add(submesh_index)
            expected_counts[submesh_index] = target_vertex_count
        if not submeshes:
            return set(), {}

        report = _run_native_mesh_core_job(
            binary,
            "skin-weights-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "transfer",
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            _invalidate_native_mesh_session_submeshes(target_mesh, sent_indices)
            return None
        return _apply_native_skin_weight_report(target_mesh, report, expected_counts, transfer_report)
    except (OSError, OverflowError, RuntimeError, ValueError) as exc:
        if transfer_report is not None:
            transfer_report.setdefault("error", str(exc))
        _invalidate_native_mesh_session_submeshes(target_mesh, sent_indices)
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def build_native_region_volume_delta(
    base_mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]] | Iterable[int],
    amount: float,
    feather: int,
    *,
    timeout_seconds: float = 20.0,
) -> tuple[tuple[Vec3, ...], ...] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    if not isinstance(base_mesh, ParsedMesh):
        return None
    selected_map: Mapping[object, object]
    if isinstance(selected_vertices_by_submesh, Mapping):
        selected_map = selected_vertices_by_submesh
    else:
        selected_map = {0: selected_vertices_by_submesh}
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_region_volume_"))

    def selected_for_submesh(submesh_index: int, vertex_count: int) -> Sequence[int]:
        raw_values = selected_map.get(submesh_index, selected_map.get(str(submesh_index), ()))
        return _selected_vertex_values(raw_values, vertex_count)

    try:
        submeshes: list[dict[str, object]] = []
        expected_counts: dict[int, int] = {}
        for submesh_index, submesh in enumerate(base_mesh.submeshes):
            vertices = getattr(submesh, "vertices", ()) or ()
            vertex_count = len(vertices)
            expected_counts[submesh_index] = vertex_count
            if vertex_count <= 0:
                continue
            prefix = sidecar_root / f"submesh_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "deltas_output_path": str(prefix.with_name(prefix.name + "_deltas.bin")),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                base_mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                faces = _face_json(getattr(submesh, "faces", ()) or (), vertex_count)
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            selected = selected_for_submesh(submesh_index, vertex_count)
            if selected:
                _put_selected_vertices_payload(item, prefix, selected, max_count=vertex_count)
            submeshes.append(item)
        if not submeshes:
            return None
        report = _run_native_mesh_core_job(
            binary,
            "region-volume-delta-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "region_volume_delta",
                "amount": _finite_float(amount, 0.0),
                "feather": max(0, int(_finite_float(feather, 0.0))),
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            return None
        raw_reports = report.get("submeshes")
        if not isinstance(raw_reports, list):
            return None
        outputs: list[tuple[Vec3, ...]] = [tuple() for _submesh in base_mesh.submeshes]
        seen: set[int] = set()
        for raw_item in raw_reports:
            if not isinstance(raw_item, Mapping):
                return None
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or not 0 <= submesh_index < len(outputs):
                return None
            vertex_count = _index(raw_item.get("vertex_count"))
            if vertex_count is None or vertex_count != expected_counts.get(submesh_index, -1):
                return None
            deltas = _read_vec3_binary_report_payload(raw_item.get("deltas_binary"), expected_count=vertex_count)
            if deltas is None:
                return None
            outputs[submesh_index] = tuple(deltas)
            seen.add(submesh_index)
        expected_non_empty = {index for index, count in expected_counts.items() if count > 0}
        if seen != expected_non_empty:
            return None
        return tuple(outputs)
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

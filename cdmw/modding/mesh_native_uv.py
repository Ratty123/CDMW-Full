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

_apply_auto_uv_report = _proxy("_apply_auto_uv_report")
_apply_uv_transform_report = _proxy("_apply_uv_transform_report")
_ensure_native_mesh_session_submesh = _proxy("_ensure_native_mesh_session_submesh")
_face_json = _proxy("_face_json")
_finite_float = _proxy("_finite_float")
_index = _proxy("_index")
_invalidate_native_mesh_session_submeshes = _proxy("_invalidate_native_mesh_session_submeshes")
_mark_native_mesh_session_submeshes_current = _proxy("_mark_native_mesh_session_submeshes_current")
_native_mesh_session_id = _proxy("_native_mesh_session_id")
_native_preview_delta_output_path = _proxy("_native_preview_delta_output_path")
_native_uv_transform_payload = _proxy("_native_uv_transform_payload")
_put_selected_edit_domain_payload = _proxy("_put_selected_edit_domain_payload")
_put_source_vertex_map_payload = _proxy("_put_source_vertex_map_payload")
_put_source_vertex_offsets_payload = _proxy("_put_source_vertex_offsets_payload")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_run_native_mesh_core_service_job = _proxy("_run_native_mesh_core_service_job")
_vec2 = _proxy("_vec2")
_write_bone_binary_payloads = _proxy("_write_bone_binary_payloads")
_write_f64_binary_payload = _proxy("_write_f64_binary_payload")
_write_face_binary_payload = _proxy("_write_face_binary_payload")
_write_vec2_binary_payload = _proxy("_write_vec2_binary_payload")
_write_vec3_binary_payload = _proxy("_write_vec3_binary_payload")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")


def release_native_temporary_mesh_sessions(
    mesh: ParsedMesh,
    submesh_indices: object,
    *,
    timeout_seconds: float = 2.0,
) -> None:
    if not str(getattr(mesh, _NATIVE_MESH_SESSION_TOKEN_ATTR, "") or ""):
        return
    indices = sorted(
        index
        for raw_index in tuple(submesh_indices or ())
        for index in (_index(raw_index),)
        if index is not None and 0 <= index < len(mesh.submeshes)
    )
    if not indices:
        return
    binary = find_native_mesh_core_binary()
    try:
        if binary is not None:
            for index in indices:
                try:
                    _run_native_mesh_core_service_job(
                        binary,
                        "mesh-session-json",
                        {
                            "version": 1,
                            "backend": NATIVE_MESH_CORE_BACKEND_ID,
                            "operation": "clear",
                            "session_id": _native_mesh_session_id(mesh, index),
                        },
                        timeout_seconds=timeout_seconds,
                    )
                except (OSError, OverflowError, RuntimeError, ValueError):
                    pass
    finally:
        _invalidate_native_mesh_session_submeshes(mesh, indices)


def native_mesh_auto_uv_report(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    resolution: int = 0,
    padding: int = 0,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_auto_uv_"))
    try:
        cancellation_kwargs = {"stop_event": stop_event} if stop_event is not None else {}
        submeshes = []
        for submesh_index in sorted(submesh_indices):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(submesh.vertices)
            if vertex_count <= 0:
                continue
            prefix = sidecar_root / f"auto_uv_{submesh_index}"
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                **cancellation_kwargs,
                timeout_seconds=timeout_seconds,
            )
            item: dict[str, object] = {
                "index": submesh_index,
                "vertices_output_path": _native_preview_delta_output_path("_auto_uv_vertices.bin"),
                "vertex_remap_output_path": _native_preview_delta_output_path("_auto_uv_vertex_remap.bin"),
                "faces_output_path": _native_preview_delta_output_path("_auto_uv_faces.bin"),
                "uvs_output_path": _native_preview_delta_output_path("_auto_uv_uvs.bin"),
                "changed_vertices_output_path": _native_preview_delta_output_path("_auto_uv_changed_vertices.bin"),
                "normals_output_path": _native_preview_delta_output_path("_auto_uv_normals.bin"),
            }
            if session_id:
                item["session_id"] = session_id
            else:
                faces = _face_json(submesh.faces, vertex_count)
                if not faces:
                    continue
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            if not session_id and len(submesh.normals) == vertex_count:
                item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), submesh.normals)
            if len(getattr(submesh, "tangents", ()) or ()) == vertex_count:
                if not session_id:
                    item["tangents_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_tangents.bin"),
                        tuple(getattr(submesh, "tangents", ()) or ()),
                    )
                item["tangents_output_path"] = _native_preview_delta_output_path("_auto_uv_tangents.bin")
            if len(getattr(submesh, "tangent_signs", ()) or ()) == vertex_count:
                if not session_id:
                    item["tangent_signs_binary"] = _write_f64_binary_payload(
                        prefix.with_name(prefix.name + "_tangent_signs.bin"),
                        tuple(getattr(submesh, "tangent_signs", ()) or ()),
                        fallback=1.0,
                    )
                item["tangent_signs_output_path"] = _native_preview_delta_output_path("_auto_uv_tangent_signs.bin")
            has_bones = (
                len(getattr(submesh, "bone_indices", ()) or ()) == vertex_count
                and len(getattr(submesh, "bone_weights", ()) or ()) == vertex_count
            )
            if has_bones:
                if not session_id:
                    bone_payload = _write_bone_binary_payloads(
                        prefix,
                        getattr(submesh, "bone_indices", ()) or (),
                        getattr(submesh, "bone_weights", ()) or (),
                    )
                    if bone_payload is None:
                        has_bones = False
                    else:
                        item.update(bone_payload)
            if has_bones:
                item["bone_counts_output_path"] = _native_preview_delta_output_path("_auto_uv_bone_counts.bin")
                item["bone_indices_output_path"] = _native_preview_delta_output_path("_auto_uv_bone_indices.bin")
                item["bone_weights_output_path"] = _native_preview_delta_output_path("_auto_uv_bone_weights.bin")
            if len(getattr(submesh, "source_vertex_map", ()) or ()) == vertex_count:
                if not session_id:
                    _put_source_vertex_map_payload(item, prefix, getattr(submesh, "source_vertex_map", ()) or ())
                item["source_vertex_map_output_path"] = _native_preview_delta_output_path("_auto_uv_source_vertex_map.bin")
            if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == vertex_count:
                if not session_id:
                    _put_source_vertex_offsets_payload(item, prefix, getattr(submesh, "source_vertex_offsets", ()) or ())
                item["source_vertex_offsets_output_path"] = _native_preview_delta_output_path("_auto_uv_source_vertex_offsets.bin")
            submeshes.append(item)
        if not submeshes:
            return {"status": "ok", "backend": NATIVE_MESH_CORE_BACKEND_ID, "operation": "auto_uv", "unwrap_backend": "xatlas", "submeshes": []}

        return _run_native_mesh_core_job(
            binary,
            "auto-uv-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "auto_uv",
                "auto_uv": {
                    "resolution": max(0, _index(resolution) or 0),
                    "padding": max(0, _index(padding) or 0),
                },
                "submeshes": submeshes,
            },
            **cancellation_kwargs,
            timeout_seconds=timeout_seconds,
        )
    except RunCancelled:
        raise
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def native_scene_import_report(
    source_path: Path | str,
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    source = Path(source_path).expanduser()
    if not source.is_file():
        return None
    return _run_native_mesh_core_job(
        binary,
        "import-scene-json",
        {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "import_scene",
            "source_path": str(source),
        },
        timeout_seconds=timeout_seconds,
    )

def native_mesh_optimization_report(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    simplify_ratio: float = 1.0,
    target_error: float = 0.01,
    timeout_seconds: float = 15.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_optimize_"))
    try:
        submeshes = []
        for submesh_index in sorted(submesh_indices):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            if not submesh.vertices:
                continue
            prefix = sidecar_root / f"optimize_{submesh_index}"
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            item: dict[str, object] = {"index": submesh_index}
            if session_id:
                item["session_id"] = session_id
            else:
                faces = _face_json(submesh.faces, len(submesh.vertices))
                if not faces:
                    continue
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            submeshes.append(item)
        if not submeshes:
            return {
                "status": "ok",
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "optimize",
                "optimization_backend": "meshoptimizer",
                "topology_changed": False,
                "totals": {
                    "input_vertex_count": 0,
                    "referenced_vertex_count": 0,
                    "input_index_count": 0,
                    "output_index_count": 0,
                    "input_triangle_count": 0,
                    "output_triangle_count": 0,
                },
                "submeshes": [],
            }

        return _run_native_mesh_core_job(
            binary,
            "optimize-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "optimize",
                "optimize": {
                    "simplify_ratio": max(0.0, min(1.0, _finite_float(simplify_ratio, 1.0))),
                    "target_error": max(0.0, _finite_float(target_error, 0.01)),
                },
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def apply_native_mesh_auto_uv(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    resolution: int = 0,
    padding: int = 0,
    allow_topology_change: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    report = native_mesh_auto_uv_report(
        mesh,
        submesh_indices,
        resolution=resolution,
        padding=padding,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )
    if report is None:
        return None
    if bool(report.get("topology_changed")) and not allow_topology_change:
        return None
    return _apply_auto_uv_report(mesh, report)


def _uv_transform_target_indices(
    mesh: ParsedMesh,
    vertices_by_submesh: Mapping[int, object],
    selected_edges_by_submesh: Mapping[int, object],
    selected_faces_by_submesh: Mapping[int, object],
    source_indices: Sequence[int],
) -> tuple[set[int], set[int]]:
    requested_sources = {
        parsed
        for raw_index in source_indices or ()
        for parsed in (_index(raw_index),)
        if parsed is not None and 0 <= parsed < len(mesh.submeshes)
    }
    target_indices = set(requested_sources)
    for mapping in (vertices_by_submesh, selected_edges_by_submesh, selected_faces_by_submesh):
        target_indices.update(parsed for raw_index in mapping if (parsed := _index(raw_index)) is not None)
    return requested_sources, target_indices


def apply_native_mesh_uv_transform(
    mesh: ParsedMesh,
    vertices_by_submesh: Mapping[int, Sequence[int] | set[int]] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    selected_faces_by_submesh: Mapping[int, set[int]] | None = None,
    source_indices: Sequence[int] = (),
    offset: Vec2,
    scale: Vec2,
    rotate_degrees: float,
    flip_u: bool = False,
    flip_v: bool = False,
    pivot: Vec2 = (0.0, 0.0),
    projection: str = "",
    plane: str = "",
    axis: str = "",
    normalize: bool = False,
    target_min: Vec2 = (0.0, 0.0),
    target_max: Vec2 = (1.0, 1.0),
    pack: bool = False,
    pack_columns: int = 0,
    padding: float = 0.02,
    align_u: object = None,
    align_v: object = None,
    snap_step: Vec2 = (0.0, 0.0),
    initialize_missing_uvs: bool = False,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    vertices_by_submesh = vertices_by_submesh or {}
    selected_edges_by_submesh = selected_edges_by_submesh or {}
    selected_faces_by_submesh = selected_faces_by_submesh or {}
    requested_sources, target_indices = _uv_transform_target_indices(
        mesh, vertices_by_submesh,
        selected_edges_by_submesh,
        selected_faces_by_submesh,
        source_indices,
    )
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_uv_transform_"))
    try:
        submeshes = []
        transform_payload = _native_uv_transform_payload(
            {
                "offset": offset,
                "scale": scale,
                "rotate": rotate_degrees,
                "flip_u": flip_u,
                "flip_v": flip_v,
                "pivot": pivot,
                "projection": projection,
                "plane": plane,
                "axis": axis,
                "normalize": normalize,
                "target_min": target_min,
                "target_max": target_max,
                "pack": pack,
                "pack_columns": pack_columns,
                "padding": padding,
                "align_u": align_u,
                "align_v": align_v,
                "snap_step": snap_step,
                "initialize_missing_uvs": initialize_missing_uvs,
            }
        )
        if transform_payload is None:
            return None
        needs_projection = bool(str(projection or "").strip())
        needs_missing_uv_init = bool(initialize_missing_uvs or needs_projection)
        needs_faces = bool(pack)
        needs_normals = str(projection or "").strip().lower() in {"box", "cube"}
        for submesh_index in sorted(target_indices):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(submesh.vertices)
            face_count = len(submesh.faces or ())
            if len(submesh.uvs) != vertex_count and not needs_missing_uv_init:
                continue
            prefix = sidecar_root / f"uv_transform_{submesh_index}"
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            item: dict[str, object] = {
                "index": submesh_index,
                "uvs_output_path": _native_preview_delta_output_path("_uv_transform_uvs.bin"),
                "changed_vertices_output_path": _native_preview_delta_output_path("_uv_transform_changed_vertices.bin"),
            }
            if not _put_selected_edit_domain_payload(
                item,
                prefix,
                selected_vertices=vertices_by_submesh.get(submesh_index, ()),
                selected_edges=selected_edges_by_submesh.get(submesh_index, ()),
                selected_faces=selected_faces_by_submesh.get(submesh_index, ()),
                selected_all_vertices=submesh_index in requested_sources,
                vertex_count=vertex_count,
                face_count=face_count,
            ):
                continue
            if session_id:
                item["session_id"] = session_id
            else:
                item["vertex_count"] = vertex_count
                uvs = submesh.uvs if len(submesh.uvs) == vertex_count else [(0.0, 0.0)] * vertex_count
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
            if not session_id and needs_projection:
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
            if not session_id and (needs_faces or selected_edges_by_submesh.get(submesh_index) or selected_faces_by_submesh.get(submesh_index)):
                item["faces_binary"] = _write_face_binary_payload(
                    prefix.with_name(prefix.name + "_faces.bin"),
                    _face_json(submesh.faces, vertex_count),
                )
            if not session_id and needs_normals and len(submesh.normals) == vertex_count:
                item["normals_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_normals.bin"),
                    submesh.normals,
                    fallback=0.0,
                )
            submeshes.append(item)
        if not submeshes:
            return {}

        report = _run_native_mesh_core_job(
            binary,
            "uv-transform-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "uv_transform",
                "uv_transform": transform_payload,
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_uv_transform_report(mesh, report)
    if changed:
        _mark_native_mesh_session_submeshes_current(mesh, changed.keys())
    return changed

def apply_native_mesh_uv_transform_submeshes(
    submeshes: Sequence[SubMesh],
    transforms_by_index: Mapping[int, Mapping[str, object]],
    *,
    timeout_seconds: float = 5.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_submesh_uv_transform_"))
    try:
        native_items: list[dict[str, object]] = []
        for raw_submesh_index, raw_transform in sorted((transforms_by_index or {}).items()):
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(submeshes):
                continue
            transform_payload = _native_uv_transform_payload(raw_transform)
            if transform_payload is None:
                return None
            submesh = submeshes[submesh_index]
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0 or len(getattr(submesh, "uvs", ()) or ()) != vertex_count:
                continue
            prefix = sidecar_root / f"submesh_uv_transform_{submesh_index}"
            native_items.append(
                {
                    "index": submesh_index,
                    "vertex_count": vertex_count,
                    "selected_all_vertices": True,
                    "uvs_binary": _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs),
                    "uvs_output_path": _native_preview_delta_output_path("_submesh_uv_transform_uvs.bin"),
                    "changed_vertices_output_path": _native_preview_delta_output_path("_submesh_uv_transform_changed_vertices.bin"),
                    "uv_transform": transform_payload,
                }
            )
        if not native_items:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "uv-transform-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "uv_transform",
                "uv_transform": _native_uv_transform_payload({}) or {},
                "submeshes": native_items,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "uv_transform":
        return None
    for raw_item in tuple(report.get("submeshes") or ()):
        if not isinstance(raw_item, Mapping):
            continue
        status = str(raw_item.get("status") or "ok").strip().lower()
        if status and status != "ok":
            raw_uv = raw_item.get("invalid_uv")
            invalid_uv = _vec2(raw_uv) if raw_uv is not None else (0.0, 0.0)
            raise ValueError(str(raw_item.get("error") or status), invalid_uv)
    mesh = ParsedMesh(path="", format="", submeshes=list(submeshes))
    changed = _apply_uv_transform_report(mesh, report)
    if changed is None:
        return None
    processed: set[int] = set()
    for raw_item in tuple(report.get("submeshes") or ()):
        if not isinstance(raw_item, Mapping):
            continue
        submesh_index = _index(raw_item.get("index"))
        if submesh_index is not None and 0 <= submesh_index < len(submeshes):
            processed.add(submesh_index)
    return processed

def apply_native_mesh_uv_atlas_submesh(
    submesh: SubMesh,
    *,
    offset: Vec2,
    scale: Vec2,
    timeout_seconds: float = 5.0,
) -> bool | None:
    processed = apply_native_mesh_uv_transform_submeshes(
        [submesh],
        {
            0: {
                "offset": offset,
                "scale": scale,
                "input_bounds_min": (-1.0e-4, -1.0e-4),
                "input_bounds_max": (1.0001, 1.0001),
                "clamp_input_uv": True,
                "input_clamp_min": (0.0, 0.0),
                "input_clamp_max": (1.0, 1.0),
            }
        },
        timeout_seconds=timeout_seconds,
    )
    if processed is None:
        return None
    return 0 in processed

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

_apply_mesh_edit_report = _proxy("_apply_mesh_edit_report")
_ensure_native_mesh_session_submesh = _proxy("_ensure_native_mesh_session_submesh")
_finite_float = _proxy("_finite_float")
_index = _proxy("_index")
_mark_native_mesh_session_submeshes_current = _proxy("_mark_native_mesh_session_submeshes_current")
_native_job_kwargs = _proxy("_native_job_kwargs")
_native_preview_delta_output_path = _proxy("_native_preview_delta_output_path")
_put_source_vertex_map_payload = _proxy("_put_source_vertex_map_payload")
_put_source_vertex_offsets_payload = _proxy("_put_source_vertex_offsets_payload")
_recompute_normals_native_or_fallback = _proxy("_recompute_normals_native_or_fallback")
_refresh_mesh_totals = _proxy("_refresh_mesh_totals")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_sorted_unique_valid_submesh_indices = _proxy("_sorted_unique_valid_submesh_indices")
_topology_edit_submeshes = _proxy("_topology_edit_submeshes")
_write_bone_binary_payloads = _proxy("_write_bone_binary_payloads")
_write_f64_binary_payload = _proxy("_write_f64_binary_payload")
_write_vec2_binary_payload = _proxy("_write_vec2_binary_payload")
_write_vec3_binary_payload = _proxy("_write_vec3_binary_payload")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")


def _native_loop_cut_edit(params: Mapping[str, object] | None) -> dict[str, object]:
    edit: dict[str, object] = {"operation": "loop_cut"}
    if not isinstance(params, Mapping):
        return edit
    for key in ("cuts", "count", "segments"):
        if key not in params:
            continue
        value = _index(params.get(key))
        if value is not None:
            edit[key] = value
            break
    for key in ("factor", "position"):
        if key in params:
            edit[key] = _finite_float(params.get(key), 0.5)
            break
    return edit

def apply_native_mesh_loop_cut(
    mesh: ParsedMesh,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    params: Mapping[str, object] | None = None,
    *,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if not selected_edges_by_submesh:
        return set(), {}
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            {},
            {},
            selected_edges_by_submesh,
            set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set(), {}
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "loop_cut",
                "edit": _native_loop_cut_edit(params),
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected, changed_vertices

def apply_native_mesh_merge(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            all_faces_by_submesh or set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set(), {}
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "merge",
                "edit": {"operation": "merge"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected, changed_vertices

def apply_native_mesh_weld(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    *,
    threshold: float,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh or {},
            selected_edges_by_submesh or {},
            all_faces_by_submesh or set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set(), {}
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "weld",
                "edit": {"operation": "weld", "threshold": _finite_float(threshold, 1e-5)},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected, changed_vertices

def _display_face_json(faces: object) -> list[list[object]]:
    if not isinstance(faces, list):
        return []
    return [list(face) for face in faces if isinstance(face, (tuple, list))]

def apply_native_mesh_triangulate_display(
    mesh: ParsedMesh,
    submesh_indices: object = None,
    *,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    target_indices = _sorted_unique_valid_submesh_indices(mesh, submesh_indices, all_when_none=True)
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes: list[dict[str, object]] = []
        for submesh_index in target_indices:
            submesh = mesh.submeshes[submesh_index]
            display_faces = _display_face_json(submesh.faces)
            if not submesh.vertices or not display_faces:
                continue
            prefix = sidecar_root / f"triangulate_{submesh_index}"
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            item: dict[str, object] = {
                "index": submesh_index,
                "display_faces": display_faces,
                "changed_vertices_output_path": _native_preview_delta_output_path("_topology_changed_vertices.bin"),
                "vertices_output_path": _native_preview_delta_output_path("_topology_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_topology_faces.bin"),
                "preview_triangle_output_path": _native_preview_delta_output_path("_triangles.bin"),
                "suppress_vertex_remap_report": True,
            }
            if not recompute_normals and len(submesh.normals) == len(submesh.vertices):
                item["normals_output_path"] = _native_preview_delta_output_path("_topology_normals.bin")
            if len(submesh.uvs) == len(submesh.vertices):
                item["uvs_output_path"] = _native_preview_delta_output_path("_topology_uvs.bin")
            if len(getattr(submesh, "tangents", ()) or ()) == len(submesh.vertices):
                item["tangents_output_path"] = _native_preview_delta_output_path("_topology_tangents.bin")
            if len(getattr(submesh, "tangent_signs", ()) or ()) == len(submesh.vertices):
                item["tangent_signs_output_path"] = _native_preview_delta_output_path("_topology_tangent_signs.bin")
            if (
                len(getattr(submesh, "bone_indices", ()) or ()) == len(submesh.vertices)
                and len(getattr(submesh, "bone_weights", ()) or ()) == len(submesh.vertices)
            ):
                item["bone_counts_output_path"] = _native_preview_delta_output_path("_topology_bone_counts.bin")
                item["bone_indices_output_path"] = _native_preview_delta_output_path("_topology_bone_indices.bin")
                item["bone_weights_output_path"] = _native_preview_delta_output_path("_topology_bone_weights.bin")
            if len(getattr(submesh, "source_vertex_map", ()) or ()) == len(submesh.vertices):
                item["source_vertex_map_output_path"] = _native_preview_delta_output_path("_topology_source_vertex_map.bin")
            if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == len(submesh.vertices):
                item["source_vertex_offsets_output_path"] = _native_preview_delta_output_path("_topology_source_vertex_offsets.bin")
            if session_id:
                item["session_id"] = session_id
            else:
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                if not recompute_normals and len(submesh.normals) == len(submesh.vertices):
                    item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), submesh.normals)
                if len(submesh.uvs) == len(submesh.vertices):
                    item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs)
                if len(getattr(submesh, "tangents", ()) or ()) == len(submesh.vertices):
                    item["tangents_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_tangents.bin"),
                        getattr(submesh, "tangents", ()) or (),
                    )
                if len(getattr(submesh, "tangent_signs", ()) or ()) == len(submesh.vertices):
                    item["tangent_signs_binary"] = _write_f64_binary_payload(
                        prefix.with_name(prefix.name + "_tangent_signs.bin"),
                        getattr(submesh, "tangent_signs", ()) or (),
                    )
                if (
                    len(getattr(submesh, "bone_indices", ()) or ()) == len(submesh.vertices)
                    and len(getattr(submesh, "bone_weights", ()) or ()) == len(submesh.vertices)
                ):
                    bone_payload = _write_bone_binary_payloads(
                        prefix,
                        getattr(submesh, "bone_indices", ()) or (),
                        getattr(submesh, "bone_weights", ()) or (),
                    )
                    if bone_payload is not None:
                        item.update(bone_payload)
                if len(getattr(submesh, "source_vertex_map", ()) or ()) == len(submesh.vertices):
                    _put_source_vertex_map_payload(item, prefix, getattr(submesh, "source_vertex_map", ()) or ())
                if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == len(submesh.vertices):
                    _put_source_vertex_offsets_payload(item, prefix, getattr(submesh, "source_vertex_offsets", ()) or ())
            submeshes.append(item)
        if not submeshes:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "triangulate_display",
                "edit": {"operation": "triangulate_display"},
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, _changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected

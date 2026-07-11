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
from cdmw.modding.mesh_native_session_state import (
    _native_mesh_core_session_cache,
    _native_mesh_core_session_cache_lock,
)
from cdmw.models import RunCancelled


def _proxy(name: str):
    def call(*args, **kwargs):
        return getattr(import_module("cdmw.modding.mesh_native_core"), name)(*args, **kwargs)

    return call

_index = _proxy("_index")
_invalidate_native_mesh_session_submeshes = _proxy("_invalidate_native_mesh_session_submeshes")
_mesh_session_item_from_native_snapshot = _proxy("_mesh_session_item_from_native_snapshot")
_mesh_snapshot_metadata = _proxy("_mesh_snapshot_metadata")
_native_job_kwargs = _proxy("_native_job_kwargs")
_native_mesh_session_cache_key = _proxy("_native_mesh_session_cache_key")
_native_mesh_session_id = _proxy("_native_mesh_session_id")
_native_mesh_session_signature = _proxy("_native_mesh_session_signature")
_native_preview_delta_output_path = _proxy("_native_preview_delta_output_path")
_native_submesh_snapshot_item = _proxy("_native_submesh_snapshot_item")
_run_native_mesh_core_service_job = _proxy("_run_native_mesh_core_service_job")
_submesh_from_native_snapshot_item = _proxy("_submesh_from_native_snapshot_item")
_vec3 = _proxy("_vec3")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")
snapshot_native_mesh_submeshes = _proxy("snapshot_native_mesh_submeshes")


def restore_native_mesh_submesh_snapshot(
    mesh: ParsedMesh,
    snapshot: Mapping[str, object],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> bool:
    if not isinstance(snapshot, Mapping) or snapshot.get("kind") != "native_submesh_snapshot":
        return False
    restored_native_sessions = _restore_native_submesh_snapshot_handle_sessions(
        snapshot,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )
    raw_submeshes = snapshot.get("submeshes")
    if not isinstance(raw_submeshes, list):
        return False
    payloads_available = all(
        int(raw_item.get("vertex_count") or 0) <= 0
        or (
            isinstance(raw_item.get("vertices_binary"), Mapping)
            and isinstance(raw_item.get("faces_binary"), Mapping)
            and Path(str(raw_item["vertices_binary"].get("path") or "")).is_file()
            and Path(str(raw_item["faces_binary"].get("path") or "")).is_file()
        )
        for raw_item in raw_submeshes
        if isinstance(raw_item, Mapping)
    )
    if not payloads_available:
        exported_snapshot = _export_native_submesh_snapshot_handle(
            snapshot,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if exported_snapshot is None:
            return False
        snapshot = exported_snapshot
        raw_submeshes = snapshot.get("submeshes")
        if not isinstance(raw_submeshes, list):
            return False
    new_submeshes: list[SubMesh] = []
    session_items_by_id: dict[str, list[dict[str, object]]] = {}
    for raw_item in raw_submeshes:
        if not isinstance(raw_item, Mapping):
            return False
        submesh = _submesh_from_native_snapshot_item(raw_item)
        if submesh is None:
            return False
        new_submeshes.append(submesh)
        session_id = str(raw_item.get("session_id") or "").strip()
        if session_id and submesh.vertices:
            session_item = _mesh_session_item_from_native_snapshot(raw_item)
            if session_item is not None:
                session_items_by_id.setdefault(session_id, []).append(session_item)
    mesh_meta = snapshot.get("mesh") if isinstance(snapshot.get("mesh"), Mapping) else {}
    mesh.path = str(mesh_meta.get("path") or getattr(mesh, "path", "") or "")
    mesh.format = str(mesh_meta.get("format") or getattr(mesh, "format", "") or "")
    mesh.bbox_min = _vec3(mesh_meta.get("bbox_min"), fallback=0.0)
    mesh.bbox_max = _vec3(mesh_meta.get("bbox_max"), fallback=0.0)
    mesh.submeshes = new_submeshes
    mesh.lod_levels = []
    mesh.total_vertices = sum(len(submesh.vertices or ()) for submesh in new_submeshes)
    mesh.total_faces = sum(len(submesh.faces or ()) for submesh in new_submeshes)
    mesh.has_uvs = any(len(submesh.uvs or ()) == len(submesh.vertices or ()) and submesh.vertices for submesh in new_submeshes)
    mesh.has_bones = any(bool(submesh.bone_indices) or bool(submesh.bone_weights) for submesh in new_submeshes)

    restored_indices = range(len(new_submeshes))
    stored_native = False
    binary = find_native_mesh_core_binary()
    if restored_native_sessions:
        stored_native = True
    elif binary is not None and session_items_by_id:
        stored_native = True
        for session_id, session_items in session_items_by_id.items():
            report = _run_native_mesh_core_service_job(
                binary,
                "mesh-session-json",
                {
                    "version": 1,
                    "backend": NATIVE_MESH_CORE_BACKEND_ID,
                    "operation": "store",
                    "session_id": session_id,
                    "submeshes": session_items,
                },
                **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
            )
            if report is None:
                stored_native = False
                break
    if stored_native:
        with _native_mesh_core_session_cache_lock:
            for session_id, session_items in session_items_by_id.items():
                for session_item in session_items:
                    submesh_index = _index(session_item.get("index"))
                    if submesh_index is not None and 0 <= submesh_index < len(mesh.submeshes):
                        _native_mesh_core_session_cache[_native_mesh_session_cache_key(mesh, submesh_index)] = (
                            _native_mesh_session_signature(mesh.submeshes[submesh_index]),
                            session_id,
                        )
    else:
        _invalidate_native_mesh_session_submeshes(mesh, restored_indices)
    return True

def _shared_native_submesh_indices(
    target_mesh: ParsedMesh,
    source_mesh: ParsedMesh,
    submesh_indices: Iterable[int],
) -> tuple[int, ...]:
    try:
        raw_indices = iter(submesh_indices)
    except TypeError:
        return ()
    limit = min(len(target_mesh.submeshes), len(source_mesh.submeshes))
    result: list[int] = []
    seen: set[int] = set()
    for raw in raw_indices:
        index = _index(raw)
        if index is not None and index not in seen and 0 <= index < limit:
            result.append(index)
            seen.add(index)
    return tuple(result)

def restore_native_mesh_submeshes_from_mesh(
    target_mesh: ParsedMesh,
    source_mesh: ParsedMesh,
    submesh_indices: Iterable[int],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return False
    if getattr(target_mesh, "lod_levels", None) or getattr(source_mesh, "lod_levels", None):
        return False
    target_submeshes = list(getattr(target_mesh, "submeshes", ()) or ())
    requested = _shared_native_submesh_indices(target_mesh, source_mesh, submesh_indices)
    if not requested:
        return False
    seen = set(requested)

    snapshot = snapshot_native_mesh_submeshes(
        source_mesh,
        requested,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(snapshot, Mapping):
        return False
    try:
        raw_snapshot_items = snapshot.get("submeshes")
        if not isinstance(raw_snapshot_items, list):
            return False
        target_items: list[dict[str, object]] = []
        target_sessions: dict[int, str] = {}
        for raw_item in raw_snapshot_items:
            if not isinstance(raw_item, Mapping):
                return False
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or submesh_index not in seen:
                return False
            item = dict(raw_item)
            session_id = _native_mesh_session_id(target_mesh, submesh_index)
            item["session_id"] = session_id
            target_items.append(item)
            vertex_count = _index(item.get("vertex_count"))
            if vertex_count is not None and vertex_count > 0:
                target_sessions[submesh_index] = session_id
        if {int(item["index"]) for item in target_items} != seen:
            return False

        target_snapshot = {
            **dict(snapshot),
            "mesh": _mesh_snapshot_metadata(target_mesh),
            "submeshes": target_items,
        }
        restored_native_sessions = _restore_native_submesh_snapshot_handle_sessions(
            target_snapshot,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        exported_snapshot = _export_native_submesh_snapshot_handle(
            target_snapshot,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        restore_items = (
            exported_snapshot.get("submeshes")
            if isinstance(exported_snapshot, Mapping) and isinstance(exported_snapshot.get("submeshes"), list)
            else target_items
        )
        if not isinstance(restore_items, list):
            return False
        restored_indices: set[int] = set()
        for raw_item in restore_items:
            if not isinstance(raw_item, Mapping):
                return False
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or submesh_index not in seen:
                return False
            submesh = _submesh_from_native_snapshot_item(raw_item)
            if submesh is None:
                return False
            target_submeshes[submesh_index] = submesh
            restored_indices.add(submesh_index)
        if restored_indices != seen:
            return False

        target_mesh.submeshes = target_submeshes
        target_mesh.total_vertices = sum(len(submesh.vertices or ()) for submesh in target_submeshes)
        target_mesh.total_faces = sum(len(submesh.faces or ()) for submesh in target_submeshes)
        target_mesh.has_uvs = any(
            len(submesh.uvs or ()) == len(submesh.vertices or ()) and bool(submesh.vertices)
            for submesh in target_submeshes
        )
        target_mesh.has_bones = any(
            bool(getattr(submesh, "bone_indices", None)) or bool(getattr(submesh, "bone_weights", None))
            for submesh in target_submeshes
        )

        stored_native = restored_native_sessions
        if not stored_native and target_sessions:
            binary = find_native_mesh_core_binary()
            stored_native = binary is not None
            if binary is not None:
                for raw_item in restore_items:
                    if not isinstance(raw_item, Mapping):
                        stored_native = False
                        break
                    submesh_index = _index(raw_item.get("index"))
                    if submesh_index is None or submesh_index not in target_sessions:
                        continue
                    session_item = _mesh_session_item_from_native_snapshot(raw_item)
                    if session_item is None:
                        stored_native = False
                        break
                    report = _run_native_mesh_core_service_job(
                        binary,
                        "mesh-session-json",
                        {
                            "version": 1,
                            "backend": NATIVE_MESH_CORE_BACKEND_ID,
                            "operation": "store",
                            "session_id": target_sessions[submesh_index],
                            "submeshes": [session_item],
                        },
                        **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
                    )
                    if report is None:
                        stored_native = False
                        break
        if stored_native:
            with _native_mesh_core_session_cache_lock:
                for submesh_index, session_id in target_sessions.items():
                    _native_mesh_core_session_cache[_native_mesh_session_cache_key(target_mesh, submesh_index)] = (
                        _native_mesh_session_signature(target_mesh.submeshes[submesh_index]),
                        session_id,
                    )
        else:
            _invalidate_native_mesh_session_submeshes(target_mesh, restored_indices)
        return True
    finally:
        dispose_native_mesh_submesh_snapshot(
            snapshot,
            stop_event=stop_event,
            timeout_seconds=min(float(timeout_seconds or 5.0), 2.0),
        )

def _restore_native_submesh_snapshot_handle_sessions(
    snapshot: Mapping[str, object],
    *,
    stop_event: threading.Event | None,
    timeout_seconds: float,
) -> bool:
    handle = snapshot.get("handle")
    if not isinstance(handle, Mapping):
        return False
    snapshot_id = str(handle.get("id") or "").strip()
    if not snapshot_id:
        return False
    raw_submeshes = snapshot.get("submeshes")
    if not isinstance(raw_submeshes, list):
        return False
    requested: list[dict[str, object]] = []
    for raw_item in raw_submeshes:
        if not isinstance(raw_item, Mapping):
            return False
        submesh_index = _index(raw_item.get("index"))
        vertex_count = _index(raw_item.get("vertex_count"))
        session_id = str(raw_item.get("session_id") or "").strip()
        if submesh_index is None or vertex_count is None:
            return False
        if vertex_count <= 0:
            continue
        if not session_id:
            return False
        requested.append({"index": submesh_index, "session_id": session_id})
    if not requested:
        return False
    binary = find_native_mesh_core_binary()
    if binary is None:
        return False
    try:
        report = _run_native_mesh_core_service_job(
            binary,
            "snapshot-submeshes-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "restore_snapshot",
                "snapshot_id": snapshot_id,
                "submeshes": requested,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return False
    if not isinstance(report, Mapping) or str(report.get("status") or "").strip().lower() != "ok":
        return False
    return _index(report.get("restored_submesh_count")) == len(requested)

def _native_submesh_snapshot_handle(report: object, snapshot_id: str) -> dict[str, object] | None:
    if not isinstance(report, Mapping):
        return None
    raw_handle = report.get("snapshot_handle")
    if not isinstance(raw_handle, Mapping):
        return None
    raw_id = str(raw_handle.get("id") or "").strip()
    if raw_id != snapshot_id:
        return None
    return {
        "id": raw_id,
        "submesh_count": int(_index(raw_handle.get("submesh_count")) or 0),
        "vertex_count": int(_index(raw_handle.get("vertex_count")) or 0),
        "face_count": int(_index(raw_handle.get("face_count")) or 0),
    }

def _export_native_submesh_snapshot_handle(
    snapshot: Mapping[str, object],
    *,
    stop_event: threading.Event | None,
    timeout_seconds: float,
) -> dict[str, object] | None:
    handle = snapshot.get("handle")
    if not isinstance(handle, Mapping):
        return None
    snapshot_id = str(handle.get("id") or "").strip()
    if not snapshot_id:
        return None
    raw_submeshes = snapshot.get("submeshes")
    if not isinstance(raw_submeshes, list):
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    requested: list[dict[str, object]] = []
    metadata_by_index: dict[int, tuple[dict[str, object], int, int]] = {}
    empty_items: dict[int, dict[str, object]] = {}
    for raw_item in raw_submeshes:
        if not isinstance(raw_item, Mapping):
            return None
        submesh_index = _index(raw_item.get("index"))
        vertex_count = _index(raw_item.get("vertex_count"))
        face_count = _index(raw_item.get("face_count"))
        if submesh_index is None or vertex_count is None or face_count is None:
            return None
        metadata = dict(raw_item.get("metadata") or {}) if isinstance(raw_item.get("metadata"), Mapping) else {}
        if vertex_count <= 0:
            empty_items[submesh_index] = dict(raw_item)
            continue
        requested.append(
            {
                "index": submesh_index,
                "session_id": str(raw_item.get("session_id") or "").strip(),
                "vertices_output_path": _native_preview_delta_output_path("_snapshot_handle_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_snapshot_handle_faces.bin"),
                "source_face_indices_output_path": _native_preview_delta_output_path("_snapshot_handle_source_faces.bin"),
                "normals_output_path": _native_preview_delta_output_path("_snapshot_handle_normals.bin"),
                "uvs_output_path": _native_preview_delta_output_path("_snapshot_handle_uvs.bin"),
                "tangents_output_path": _native_preview_delta_output_path("_snapshot_handle_tangents.bin"),
                "tangent_signs_output_path": _native_preview_delta_output_path("_snapshot_handle_tangent_signs.bin"),
                "bone_counts_output_path": _native_preview_delta_output_path("_snapshot_handle_bone_counts.bin"),
                "bone_indices_output_path": _native_preview_delta_output_path("_snapshot_handle_bone_indices.bin"),
                "bone_weights_output_path": _native_preview_delta_output_path("_snapshot_handle_bone_weights.bin"),
                "source_vertex_map_output_path": _native_preview_delta_output_path("_snapshot_handle_source_vertex_map.bin"),
                "source_vertex_offsets_output_path": _native_preview_delta_output_path("_snapshot_handle_source_vertex_offsets.bin"),
            }
        )
        metadata_by_index[submesh_index] = (metadata, vertex_count, face_count)
    if not requested:
        return None
    report = _run_native_mesh_core_service_job(
        binary,
        "snapshot-submeshes-json",
        {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "export_snapshot",
            "snapshot_id": snapshot_id,
            "submeshes": requested,
        },
        **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
    )
    if report is None:
        return None
    exported_items = dict(empty_items)
    for raw_exported in tuple(report.get("submeshes") or ()) if isinstance(report, Mapping) else ():
        if not isinstance(raw_exported, Mapping):
            continue
        submesh_index = _index(raw_exported.get("index"))
        if submesh_index is None or submesh_index not in metadata_by_index:
            continue
        metadata, expected_vertices, expected_faces = metadata_by_index[submesh_index]
        exported_item = _native_submesh_snapshot_item(
            raw_exported,
            metadata=metadata,
            expected_vertices=expected_vertices,
            expected_faces=expected_faces,
        )
        if exported_item is None:
            return None
        exported_items[submesh_index] = exported_item
    if len(exported_items) != len(raw_submeshes):
        return None
    return {
        "kind": "native_submesh_snapshot",
        "mesh": dict(snapshot.get("mesh") or {}) if isinstance(snapshot.get("mesh"), Mapping) else {},
        "handle": dict(handle),
        "submeshes": [exported_items[index] for index in sorted(exported_items)],
    }

def dispose_native_mesh_submesh_snapshot(
    snapshot: Mapping[str, object] | object,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 2.0,
) -> bool:
    if not isinstance(snapshot, Mapping) or snapshot.get("kind") != "native_submesh_snapshot":
        return False
    handle = snapshot.get("handle")
    if not isinstance(handle, Mapping):
        return False
    snapshot_id = str(handle.get("id") or "").strip()
    if not snapshot_id:
        return False
    binary = find_native_mesh_core_binary()
    if binary is None:
        return False
    try:
        report = _run_native_mesh_core_service_job(
            binary,
            "snapshot-submeshes-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "clear_snapshot",
                "snapshot_id": snapshot_id,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return False
    return isinstance(report, Mapping) and str(report.get("status") or "").strip().lower() == "ok"

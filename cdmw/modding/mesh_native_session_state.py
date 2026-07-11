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

_iter_valid_submesh_indices = _proxy("_iter_valid_submesh_indices")
_native_mesh_core_service_enabled = _proxy("_native_mesh_core_service_enabled")
_native_mesh_core_service_known_for_binary = _proxy("_native_mesh_core_service_known_for_binary")
_native_mesh_core_service_running = _proxy("_native_mesh_core_service_running")
_put_i32_range_or_binary_payload = _proxy("_put_i32_range_or_binary_payload")
_put_source_vertex_map_payload = _proxy("_put_source_vertex_map_payload")
_put_source_vertex_offsets_payload = _proxy("_put_source_vertex_offsets_payload")
_run_native_mesh_core_service_job = _proxy("_run_native_mesh_core_service_job")
_snapshot_metadata_value = _proxy("_snapshot_metadata_value")
_write_bone_binary_payloads = _proxy("_write_bone_binary_payloads")
_write_f64_binary_payload = _proxy("_write_f64_binary_payload")
_write_face_binary_payload_with_source_indices = _proxy("_write_face_binary_payload_with_source_indices")
_write_vec2_binary_payload = _proxy("_write_vec2_binary_payload")
_write_vec3_binary_payload = _proxy("_write_vec3_binary_payload")


_native_mesh_core_session_cache_lock = threading.RLock()
_native_mesh_core_session_cache: dict[tuple[str, int], tuple[tuple[object, ...], str]] = {}


def _clear_native_mesh_core_session_cache() -> None:
    with _native_mesh_core_session_cache_lock:
        _native_mesh_core_session_cache.clear()

def _native_mesh_session_token(mesh: ParsedMesh) -> str:
    token = getattr(mesh, _NATIVE_MESH_SESSION_TOKEN_ATTR, "")
    if isinstance(token, str) and token:
        return token
    token = f"py-mesh-{uuid4().hex}"
    try:
        setattr(mesh, _NATIVE_MESH_SESSION_TOKEN_ATTR, token)
    except Exception:
        return f"py-mesh-{uuid4().hex}"
    return token

def _native_mesh_session_cache_key(mesh: ParsedMesh, submesh_index: int) -> tuple[str, int]:
    return (_native_mesh_session_token(mesh), int(submesh_index))

def _native_mesh_session_id(mesh: ParsedMesh, submesh_index: int) -> str:
    return f"{_native_mesh_session_token(mesh)}-{int(submesh_index)}"

def _cached_native_mesh_session_submesh(mesh: ParsedMesh, submesh_index: int) -> str | None:
    if not 0 <= int(submesh_index) < len(getattr(mesh, "submeshes", ()) or ()):
        return None
    signature = _native_mesh_session_signature(mesh.submeshes[int(submesh_index)])
    cache_key = _native_mesh_session_cache_key(mesh, int(submesh_index))
    with _native_mesh_core_session_cache_lock:
        cached = _native_mesh_core_session_cache.get(cache_key)
    if cached is None or cached[0] != signature:
        return None
    return str(cached[1] or "").strip() or None

def _native_mesh_session_signature(submesh: object) -> tuple[object, ...]:
    vertices = getattr(submesh, "vertices", ()) or ()
    faces = getattr(submesh, "faces", ()) or ()
    normals = getattr(submesh, "normals", ()) or ()
    uvs = getattr(submesh, "uvs", ()) or ()
    tangents = getattr(submesh, "tangents", ()) or ()
    tangent_signs = getattr(submesh, "tangent_signs", ()) or ()
    bone_indices = getattr(submesh, "bone_indices", ()) or ()
    bone_weights = getattr(submesh, "bone_weights", ()) or ()
    source_vertex_map = getattr(submesh, "source_vertex_map", ()) or ()
    source_vertex_offsets = getattr(submesh, "source_vertex_offsets", ()) or ()
    extra_attrs = tuple(
        (attr_name, _snapshot_metadata_value(getattr(submesh, attr_name)))
        for attr_name in _EXTRA_SUBMESH_ATTRS
        if hasattr(submesh, attr_name)
    )
    return (
        str(getattr(submesh, "name", "") or ""),
        str(getattr(submesh, "material", "") or ""),
        str(getattr(submesh, "texture", "") or ""),
        extra_attrs,
        len(vertices),
        len(faces),
        id(vertices),
        id(faces),
        len(normals),
        id(normals),
        len(uvs),
        id(uvs),
        len(tangents),
        id(tangents),
        len(tangent_signs),
        id(tangent_signs),
        len(bone_indices),
        id(bone_indices),
        len(bone_weights),
        id(bone_weights),
        len(source_vertex_map),
        id(source_vertex_map),
        len(source_vertex_offsets),
        id(source_vertex_offsets),
    )

def _mark_native_mesh_session_submeshes_current(mesh: ParsedMesh, submesh_indices: object) -> None:
    with _native_mesh_core_session_cache_lock:
        for index in _iter_valid_submesh_indices(mesh, submesh_indices):
            key = _native_mesh_session_cache_key(mesh, index)
            cached = _native_mesh_core_session_cache.get(key)
            if cached is None:
                continue
            _old_signature, session_id = cached
            _native_mesh_core_session_cache[key] = (_native_mesh_session_signature(mesh.submeshes[index]), session_id)

def _invalidate_native_mesh_session_submeshes(mesh: ParsedMesh, submesh_indices: object) -> None:
    with _native_mesh_core_session_cache_lock:
        for index in _iter_valid_submesh_indices(mesh, submesh_indices):
            _native_mesh_core_session_cache.pop(_native_mesh_session_cache_key(mesh, index), None)

def invalidate_native_mesh_session_submeshes(mesh: ParsedMesh, submesh_indices: object) -> None:
    _invalidate_native_mesh_session_submeshes(mesh, submesh_indices)

def _native_mesh_session_store_item(submesh: SubMesh, submesh_index: int, prefix: Path) -> dict[str, object] | None:
    if not submesh.vertices:
        return None
    vertex_count = len(submesh.vertices)
    faces_binary, source_face_indices = _write_face_binary_payload_with_source_indices(
        prefix.with_name(prefix.name + "_faces.bin"),
        submesh.faces,
        vertex_count,
    )
    item: dict[str, object] = {
        "index": submesh_index,
        "name": str(getattr(submesh, "name", "") or ""),
        "material": str(getattr(submesh, "material", "") or ""),
        "texture": str(getattr(submesh, "texture", "") or ""),
        "vertices_binary": _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices),
        "faces_binary": faces_binary,
    }
    extra_attrs = {
        attr_name: _snapshot_metadata_value(getattr(submesh, attr_name))
        for attr_name in _EXTRA_SUBMESH_ATTRS
        if hasattr(submesh, attr_name)
    }
    if extra_attrs:
        item["extra_attrs"] = extra_attrs
    _put_i32_range_or_binary_payload(
        item,
        values=source_face_indices,
        start_key="source_face_start",
        count_key="source_face_count",
        binary_key="source_face_indices_binary",
        binary_path=prefix.with_name(prefix.name + "_source_faces.bin"),
        max_count=len(submesh.faces),
    )
    if len(submesh.normals) == len(submesh.vertices):
        item["normals_binary"] = _write_vec3_binary_payload(
            prefix.with_name(prefix.name + "_normals.bin"),
            submesh.normals,
            fallback=0.0,
        )
    if len(submesh.uvs) == len(submesh.vertices):
        item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs)
    if len(getattr(submesh, "tangents", ()) or ()) == len(submesh.vertices):
        item["tangents_binary"] = _write_vec3_binary_payload(
            prefix.with_name(prefix.name + "_tangents.bin"),
            getattr(submesh, "tangents", ()) or (),
            fallback=0.0,
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
    return item

def _ensure_native_mesh_session_submesh(
    binary: Path,
    mesh: ParsedMesh,
    submesh_index: int,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float,
) -> str | None:
    if not _native_mesh_core_service_enabled(stop_event=stop_event):
        return None
    if not _native_mesh_core_service_running(binary):
        _clear_native_mesh_core_session_cache()
    if not 0 <= submesh_index < len(mesh.submeshes):
        return None
    submesh = mesh.submeshes[submesh_index]
    signature = _native_mesh_session_signature(submesh)
    cache_key = _native_mesh_session_cache_key(mesh, submesh_index)
    with _native_mesh_core_session_cache_lock:
        cached = _native_mesh_core_session_cache.get(cache_key)
        if cached is not None and cached[0] == signature:
            return cached[1]
    session_id = _native_mesh_session_id(mesh, submesh_index)
    try:
        with tempfile.TemporaryDirectory(prefix="cdmw_mesh_core_session_") as sidecar_root_raw:
            sidecar_root = Path(sidecar_root_raw)
            prefix = sidecar_root / f"session_{submesh_index}"
            item = _native_mesh_session_store_item(submesh, submesh_index, prefix)
            if item is None:
                return None
            service_kwargs: dict[str, object] = {"timeout_seconds": timeout_seconds}
            if stop_event is not None:
                service_kwargs["stop_event"] = stop_event
            report = _run_native_mesh_core_service_job(
                binary,
                "mesh-session-json",
                {
                    "version": 1,
                    "backend": NATIVE_MESH_CORE_BACKEND_ID,
                    "operation": "store",
                    "session_id": session_id,
                    "submeshes": [item],
                },
                **service_kwargs,
            )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    if report is None:
        return None
    if _native_mesh_core_service_known_for_binary(binary) and not _native_mesh_core_service_running(binary):
        return None
    with _native_mesh_core_session_cache_lock:
        _native_mesh_core_session_cache[cache_key] = (signature, session_id)
    return session_id

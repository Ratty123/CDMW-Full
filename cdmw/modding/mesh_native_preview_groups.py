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

_changed_vertex_range = _proxy("_changed_vertex_range")
_changed_vertices_binary_descriptor = _proxy("_changed_vertices_binary_descriptor")
_ensure_native_mesh_session_submesh = _proxy("_ensure_native_mesh_session_submesh")
_index = _proxy("_index")
_invalidate_native_mesh_session_submeshes = _proxy("_invalidate_native_mesh_session_submeshes")
_iter_valid_changed_vertex_indices = _proxy("_iter_valid_changed_vertex_indices")
_native_preview_delta_output_path = _proxy("_native_preview_delta_output_path")
_native_preview_triangle_group = _proxy("_native_preview_triangle_group")
_native_preview_vertex_update_group = _proxy("_native_preview_vertex_update_group")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_write_int_binary_payload = _proxy("_write_int_binary_payload")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")


def build_native_mesh_preview_triangle_groups(
    mesh: ParsedMesh,
    source_indices: Sequence[int] | None = None,
    *,
    timeout_seconds: float = 5.0,
    _retry_missing: bool = True,
) -> list[dict[str, object]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    if source_indices is None:
        requested = range(len(mesh.submeshes))
    else:
        requested = (
            index
            for raw_index in source_indices or ()
            if (index := _index(raw_index)) is not None and 0 <= index < len(mesh.submeshes)
        )
    requested_indices = tuple(requested)
    submeshes: list[dict[str, object]] = []
    passthrough: list[dict[str, object]] = []
    for submesh_index in requested_indices:
        submesh = mesh.submeshes[submesh_index]
        if not (getattr(submesh, "vertices", ()) or ()) or not (getattr(submesh, "faces", ()) or ()):
            passthrough.append(
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": submesh_index,
                    "source_vertex_indices": [],
                    "source_face_indices": [],
                    "positions": [],
                    "normals": [],
                    "uvs": [],
                    "indices": [],
                }
            )
            continue
        session_id = _ensure_native_mesh_session_submesh(
            binary,
            mesh,
            submesh_index,
            timeout_seconds=timeout_seconds,
        )
        if not session_id:
            return None
        submeshes.append(
            {
                "index": submesh_index,
                "source_submesh_index": submesh_index,
                "session_id": session_id,
                "preview_triangle_output_path": _native_preview_delta_output_path("_triangles.bin"),
            }
        )
    if not submeshes:
        return passthrough
    report = _run_native_mesh_core_job(
        binary,
        "preview-triangle-groups-json",
        {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "preview_triangle_groups",
            "submeshes": submeshes,
        },
        timeout_seconds=timeout_seconds,
    )
    if report is None:
        _invalidate_native_mesh_session_submeshes(mesh, requested_indices)
        if _retry_missing:
            return build_native_mesh_preview_triangle_groups(
                mesh,
                source_indices=requested_indices,
                timeout_seconds=timeout_seconds,
                _retry_missing=False,
            )
        return None
    raw_groups = report.get("groups")
    if not isinstance(raw_groups, list):
        _invalidate_native_mesh_session_submeshes(mesh, requested_indices)
        if _retry_missing:
            return build_native_mesh_preview_triangle_groups(
                mesh,
                source_indices=requested_indices,
                timeout_seconds=timeout_seconds,
                _retry_missing=False,
            )
        return None
    groups = list(passthrough)
    expected = {int(item["source_submesh_index"]) for item in submeshes}
    seen: set[int] = set()
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping):
            continue
        submesh_index = _index(raw_group.get("source_submesh_index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        group = _native_preview_triangle_group(raw_group, submesh_index)
        if group is None:
            return None
        groups.append(group)
        seen.add(submesh_index)
    missing = expected - seen
    if missing:
        _invalidate_native_mesh_session_submeshes(mesh, missing)
        if _retry_missing:
            return build_native_mesh_preview_triangle_groups(
                mesh,
                source_indices=requested_indices,
                timeout_seconds=timeout_seconds,
                _retry_missing=False,
            )
        return None
    return groups

def build_native_mesh_preview_vertex_update_groups(
    mesh: ParsedMesh,
    changed_vertices_by_submesh: Mapping[int, object],
    *,
    timeout_seconds: float = 5.0,
) -> list[dict[str, object]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    submeshes: list[dict[str, object]] = []
    for raw_submesh_index, raw_indices in (changed_vertices_by_submesh or {}).items():
        submesh_index = _index(raw_submesh_index)
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        vertex_count = len(getattr(submesh, "vertices", ()) or ())
        changed_descriptor = _changed_vertices_binary_descriptor(raw_indices, vertex_count)
        changed_range = _changed_vertex_range(raw_indices, vertex_count)
        changed_all_vertices = (
            changed_range is not None
            and changed_range[0] == 0
            and changed_range[1] == vertex_count
        )
        if changed_all_vertices:
            changed_vertices: tuple[int, ...] = ()
        elif changed_range is not None:
            changed_vertices = ()
        elif changed_descriptor is not None:
            changed_vertices = ()
        session_id = _ensure_native_mesh_session_submesh(
            binary,
            mesh,
            submesh_index,
            timeout_seconds=timeout_seconds,
        )
        if not session_id:
            return None
        item: dict[str, object] = {
            "index": submesh_index,
            "source_submesh_index": submesh_index,
            "session_id": session_id,
            "preview_vertex_output_path": _native_preview_delta_output_path("_preview_vertices.bin"),
        }
        if changed_all_vertices:
            item["changed_all_vertices"] = True
        elif changed_range is not None:
            item["changed_vertex_start"] = int(changed_range[0])
            item["changed_vertex_count"] = int(changed_range[1])
        elif changed_descriptor is not None:
            item["changed_vertices_binary"] = changed_descriptor
        else:
            indices_path = Path(_native_preview_delta_output_path("_preview_vertex_indices.bin"))
            written_descriptor = _write_int_binary_payload(
                indices_path,
                _iter_valid_changed_vertex_indices(raw_indices, vertex_count),
            )
            if _index(written_descriptor.get("count")) is None or int(written_descriptor["count"]) <= 0:
                try:
                    indices_path.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            item["changed_vertices_binary"] = written_descriptor
        submeshes.append(item)
    if not submeshes:
        return []
    report = _run_native_mesh_core_job(
        binary,
        "preview-vertex-update-groups-json",
        {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "preview_vertex_update_groups",
            "submeshes": submeshes,
        },
        timeout_seconds=timeout_seconds,
    )
    if report is None:
        return None
    raw_groups = report.get("groups")
    if not isinstance(raw_groups, list):
        return None
    groups: list[dict[str, object]] = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping):
            continue
        submesh_index = _index(raw_group.get("source_submesh_index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        group = _native_preview_vertex_update_group(raw_group, submesh_index)
        if group is None:
            return None
        groups.append(group)
    return groups

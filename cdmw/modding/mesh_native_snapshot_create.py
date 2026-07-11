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

_changed_vertices_from_report_item = _proxy("_changed_vertices_from_report_item")
_ensure_native_mesh_session_submesh = _proxy("_ensure_native_mesh_session_submesh")
_face_count_json = _proxy("_face_count_json")
_index = _proxy("_index")
_iter_valid_submesh_indices = _proxy("_iter_valid_submesh_indices")
_mesh_snapshot_metadata = _proxy("_mesh_snapshot_metadata")
_native_history_delta_vertex_payload = _proxy("_native_history_delta_vertex_payload")
_native_history_vertex_delta = _proxy("_native_history_vertex_delta")
_native_job_kwargs = _proxy("_native_job_kwargs")
_native_preview_delta_output_path = _proxy("_native_preview_delta_output_path")
_native_submesh_snapshot_handle = _proxy("_native_submesh_snapshot_handle")
_native_submesh_snapshot_item = _proxy("_native_submesh_snapshot_item")
_new_native_sparse_vertex_snapshot_id = _proxy("_new_native_sparse_vertex_snapshot_id")
_put_vertex_indices_payload = _proxy("_put_vertex_indices_payload")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_run_native_mesh_core_service_job = _proxy("_run_native_mesh_core_service_job")
_submesh_snapshot_metadata = _proxy("_submesh_snapshot_metadata")
_vertex_indices_from_history_descriptor = _proxy("_vertex_indices_from_history_descriptor")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")


def snapshot_native_mesh_sparse_vertex_positions(
    mesh: ParsedMesh,
    vertex_indices_by_submesh: Mapping[object, object],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, dict[str, object]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    if not isinstance(vertex_indices_by_submesh, Mapping) or not vertex_indices_by_submesh:
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_sparse_snapshot_"))
    try:
        submeshes: list[dict[str, object]] = []
        vertex_counts: dict[int, int] = {}
        snapshot_id = _new_native_sparse_vertex_snapshot_id("snapshot")
        for raw_submesh_index, raw_positions_by_vertex in sorted(
            vertex_indices_by_submesh.items(),
            key=lambda item: str(item[0]),
        ):
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
                continue
            if not isinstance(raw_positions_by_vertex, Mapping):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0:
                continue
            indices: list[int] = []
            seen_indices: set[int] = set()
            raw_groups = raw_positions_by_vertex.get("groups")
            if isinstance(raw_groups, (tuple, list)) and raw_groups:
                raw_index_groups = (
                    _vertex_indices_from_history_descriptor(group, vertex_count)
                    for group in raw_groups
                    if isinstance(group, Mapping)
                )
            else:
                raw_index_groups = (raw_positions_by_vertex.keys(),)
            for raw_group_indices in raw_index_groups:
                if raw_group_indices is None:
                    continue
                for raw_vertex_index in raw_group_indices:
                    vertex_index = _index(raw_vertex_index)
                    if vertex_index is None or vertex_index < 0 or vertex_index >= vertex_count or vertex_index in seen_indices:
                        continue
                    indices.append(vertex_index)
                    seen_indices.add(vertex_index)
            if not indices:
                continue
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                return None
            prefix = sidecar_root / f"snapshot_{submesh_index}_{len(submeshes)}"
            item: dict[str, object] = {
                "index": submesh_index,
                "session_id": session_id,
                "vertex_count": vertex_count,
                "changed_vertices_output_path": _native_preview_delta_output_path("_snapshot_vertices.bin"),
                "before_positions_output_path": _native_preview_delta_output_path("_snapshot_positions.bin"),
            }
            _put_vertex_indices_payload(item, prefix, indices, max_count=vertex_count)
            submeshes.append(item)
            vertex_counts[submesh_index] = vertex_count
        if not submeshes:
            return {}
        report = _run_native_mesh_core_job(
            binary,
            "snapshot-vertices-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "snapshot_vertices",
                "sparse_snapshot_id": snapshot_id,
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        result: dict[int, dict[str, object]] = {}
        for item in tuple(report.get("submeshes") or ()) if isinstance(report, Mapping) else ():
            if not isinstance(item, Mapping):
                continue
            submesh_index = _index(item.get("index"))
            if submesh_index is None or submesh_index not in vertex_counts:
                continue
            changed_vertices = _changed_vertices_from_report_item(item, vertex_counts[submesh_index])
            if changed_vertices is None:
                return None
            delta = _native_history_vertex_delta(item, submesh_index, changed_vertices)
            if delta is None:
                return None
            result[submesh_index] = {
                "groups": [
                    {
                        **_native_history_delta_vertex_payload(delta),
                        "native_sparse_snapshot_id": delta.get("native_sparse_snapshot_id", snapshot_id),
                        "before_positions_binary": delta["before_positions_binary"],
                    }
                ]
            }
        return result
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def snapshot_native_mesh_submeshes(
    mesh: ParsedMesh,
    submesh_indices: Sequence[int] | None = None,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    if getattr(mesh, "lod_levels", None):
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    requested = tuple(_iter_valid_submesh_indices(mesh, submesh_indices, all_when_none=True))
    if len(requested) != len(set(requested)):
        return None
    snapshot_items: dict[int, dict[str, object]] = {}
    job_submeshes: list[dict[str, object]] = []
    snapshot_id = f"py-submesh-snapshot-{uuid4().hex}"
    try:
        for submesh_index in requested:
            submesh = mesh.submeshes[submesh_index]
            metadata = _submesh_snapshot_metadata(submesh)
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            face_count = _face_count_json(getattr(submesh, "faces", ()) or (), vertex_count)
            if vertex_count <= 0:
                snapshot_items[submesh_index] = {
                    "index": submesh_index,
                    "metadata": metadata,
                    "vertex_count": 0,
                    "face_count": 0,
                }
                continue
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                session_id = _ensure_native_mesh_session_submesh(
                    binary,
                    mesh,
                    submesh_index,
                    stop_event=stop_event,
                    timeout_seconds=timeout_seconds,
                )
            if not session_id:
                return None
            job_submeshes.append(
                {
                    "index": submesh_index,
                    "session_id": session_id,
                    "vertices_output_path": _native_preview_delta_output_path("_snapshot_vertices.bin"),
                    "faces_output_path": _native_preview_delta_output_path("_snapshot_faces.bin"),
                    "source_face_indices_output_path": _native_preview_delta_output_path("_snapshot_source_faces.bin"),
                    "normals_output_path": _native_preview_delta_output_path("_snapshot_normals.bin"),
                    "uvs_output_path": _native_preview_delta_output_path("_snapshot_uvs.bin"),
                    "tangents_output_path": _native_preview_delta_output_path("_snapshot_tangents.bin"),
                    "tangent_signs_output_path": _native_preview_delta_output_path("_snapshot_tangent_signs.bin"),
                    "bone_counts_output_path": _native_preview_delta_output_path("_snapshot_bone_counts.bin"),
                    "bone_indices_output_path": _native_preview_delta_output_path("_snapshot_bone_indices.bin"),
                    "bone_weights_output_path": _native_preview_delta_output_path("_snapshot_bone_weights.bin"),
                    "source_vertex_map_output_path": _native_preview_delta_output_path("_snapshot_source_vertex_map.bin"),
                    "source_vertex_offsets_output_path": _native_preview_delta_output_path("_snapshot_source_vertex_offsets.bin"),
                    "_metadata": metadata,
                    "_vertex_count": vertex_count,
                    "_face_count": face_count,
                }
            )
        if job_submeshes:
            report = _run_native_mesh_core_service_job(
                binary,
                "snapshot-submeshes-json",
                {
                    "version": 1,
                    "backend": NATIVE_MESH_CORE_BACKEND_ID,
                    "operation": "snapshot_submeshes",
                    "snapshot_id": snapshot_id,
                    "submeshes": [
                        {key: value for key, value in item.items() if not str(key).startswith("_")}
                        for item in job_submeshes
                    ],
                },
                **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
            )
            if report is None:
                return None
            metadata_by_index = {
                int(item["index"]): (dict(item["_metadata"]), int(item["_vertex_count"]), int(item["_face_count"]))
                for item in job_submeshes
            }
            for raw_item in tuple(report.get("submeshes") or ()) if isinstance(report, Mapping) else ():
                if not isinstance(raw_item, Mapping):
                    continue
                submesh_index = _index(raw_item.get("index"))
                if submesh_index is None or submesh_index not in metadata_by_index:
                    continue
                metadata, expected_vertices, expected_faces = metadata_by_index[submesh_index]
                snapshot_item = _native_submesh_snapshot_item(
                    raw_item,
                    metadata=metadata,
                    expected_vertices=expected_vertices,
                    expected_faces=expected_faces,
                )
                if snapshot_item is None:
                    return None
                snapshot_items[submesh_index] = snapshot_item
        if set(snapshot_items) != set(requested):
            return None
        return {
            "kind": "native_submesh_snapshot",
            "mesh": _mesh_snapshot_metadata(mesh),
            "handle": _native_submesh_snapshot_handle(report if job_submeshes else None, snapshot_id),
            "submeshes": [snapshot_items[index] for index in sorted(snapshot_items)],
        }
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None

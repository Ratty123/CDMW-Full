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

_apply_selection_report = _proxy("_apply_selection_report")
_ensure_native_mesh_session_submesh = _proxy("_ensure_native_mesh_session_submesh")
_face_json = _proxy("_face_json")
_face_json_with_source_indices = _proxy("_face_json_with_source_indices")
_index = _proxy("_index")
_native_job_kwargs = _proxy("_native_job_kwargs")
_native_preview_delta_output_path = _proxy("_native_preview_delta_output_path")
_native_report_metrics = _proxy("_native_report_metrics")
_native_selection_preview_group = _proxy("_native_selection_preview_group")
_put_i32_range_or_binary_payload = _proxy("_put_i32_range_or_binary_payload")
_put_source_face_indices_payload = _proxy("_put_source_face_indices_payload")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_vec2_json = _proxy("_vec2_json")
_write_edge_binary_payload = _proxy("_write_edge_binary_payload")
_write_face_binary_payload = _proxy("_write_face_binary_payload")
_write_vec2_binary_payload = _proxy("_write_vec2_binary_payload")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")


def apply_native_mesh_selection(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, set[int]],
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    selected_faces_by_submesh: Mapping[int, set[int]] | None = None,
    source_indices: Sequence[int] = (),
    operation: str,
    iterations: int = 1,
    stop_event: threading.Event | None = None,
    metrics_out: dict[str, float] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    normalized_operation = str(operation or "").strip().lower()
    if normalized_operation not in {"grow", "shrink", "smooth", "invert", "all"}:
        return None
    selected_edges_by_submesh = selected_edges_by_submesh or {}
    selected_faces_by_submesh = selected_faces_by_submesh or {}
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_selection_"))
    try:
        submeshes = []
        requested_sources = {
            parsed
            for raw in source_indices or ()
            for parsed in (_index(raw),)
            if parsed is not None and 0 <= parsed < len(mesh.submeshes)
        }
        target_indices = set(requested_sources)
        for mapping in (selected_vertices_by_submesh, selected_edges_by_submesh, selected_faces_by_submesh):
            for raw_index in mapping:
                parsed = _index(raw_index)
                if parsed is not None:
                    target_indices.add(parsed)
        for submesh_index in sorted(target_indices):
            if not 0 <= int(submesh_index) < len(mesh.submeshes):
                continue
            submesh_index = int(submesh_index)
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(submesh.vertices)
            face_count = len(submesh.faces or ())
            kept = sorted(
                index
                for raw_index in selected_vertices_by_submesh.get(submesh_index, set())
                for index in (_index(raw_index),)
                if index is not None and 0 <= index < vertex_count
            )
            kept_edges = sorted(
                (min(left, right), max(left, right))
                for raw_edge in selected_edges_by_submesh.get(submesh_index, set())
                if isinstance(raw_edge, (tuple, list)) and len(raw_edge) >= 2
                for left in (_index(raw_edge[0]),)
                for right in (_index(raw_edge[1]),)
                if left is not None and right is not None and 0 <= left < vertex_count and 0 <= right < vertex_count and left != right
            )
            kept_faces = sorted(
                index
                for raw_index in selected_faces_by_submesh.get(submesh_index, set())
                for index in (_index(raw_index),)
                if index is not None and 0 <= index < face_count
            )
            selected_all_vertices = normalized_operation != "invert" and submesh_index in requested_sources
            invert_scope = normalized_operation == "invert" and submesh_index in requested_sources
            if vertex_count <= 0 or (face_count <= 0 and not selected_all_vertices) or not (kept or kept_edges or kept_faces or selected_all_vertices or invert_scope):
                continue
            prefix = sidecar_root / f"selection_{submesh_index}"
            item: dict[str, object] = {"index": submesh_index}
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                faces = _face_json(submesh.faces, vertex_count)
                if not faces:
                    continue
                item["vertex_count"] = vertex_count
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            if kept:
                _put_i32_range_or_binary_payload(
                    item,
                    values=kept,
                    start_key="selected_vertex_start",
                    count_key="selected_vertex_count",
                    binary_key="selected_vertices_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected.bin"),
                    max_count=vertex_count,
                )
            if kept_edges:
                item["selected_edges_binary"] = _write_edge_binary_payload(prefix.with_name(prefix.name + "_selected_edges.bin"), kept_edges)
            if kept_faces:
                _put_i32_range_or_binary_payload(
                    item,
                    values=kept_faces,
                    start_key="selected_face_start",
                    count_key="selected_face_count",
                    binary_key="selected_faces_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"),
                    max_count=face_count,
                )
            if selected_all_vertices:
                item["selected_all_vertices"] = True
            item["selected_vertices_output_path"] = _native_preview_delta_output_path("_selection_vertices.bin")
            submeshes.append(item)
        if not submeshes:
            return {}
        report = _run_native_mesh_core_job(
            binary,
            "selection-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "selection",
                "selection": {
                    "operation": normalized_operation,
                    "iterations": max(0, _index(iterations) or 0),
                },
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
    if metrics_out is not None:
        metrics_out.update(_native_report_metrics(report))
    return _apply_selection_report(mesh, report)

def build_native_mesh_selection_groups(
    mesh: ParsedMesh,
    *,
    vertices_by_submesh: Mapping[int, set[int]],
    edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    faces_by_submesh: Mapping[int, set[int]],
    source_indices: Sequence[int] = (),
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> list[dict[str, object]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_selection_preview_"))
    try:
        requested_sources = {
            int(index)
            for index in source_indices or ()
            if isinstance(index, int) and 0 <= int(index) < len(mesh.submeshes)
        }
        target_indices = set(vertices_by_submesh) | set(edges_by_submesh) | set(faces_by_submesh) | requested_sources
        submeshes = []
        for submesh_index in sorted(target_indices):
            if not 0 <= int(submesh_index) < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[int(submesh_index)]
            vertex_count = len(submesh.vertices or [])
            selected_vertices = sorted(index for index in vertices_by_submesh.get(int(submesh_index), set()) if 0 <= index < vertex_count)
            selected_edges = sorted(
                (min(int(left), int(right)), max(int(left), int(right)))
                for left, right in edges_by_submesh.get(int(submesh_index), set())
                if 0 <= int(left) < vertex_count and 0 <= int(right) < vertex_count and int(left) != int(right)
            )
            selected_faces = sorted(
                face_index
                for raw_index in faces_by_submesh.get(int(submesh_index), set())
                if (face_index := _index(raw_index)) is not None and face_index >= 0
            )
            selected_all_vertices = int(submesh_index) in requested_sources
            if vertex_count <= 0 or not (selected_vertices or selected_edges or selected_faces or selected_all_vertices):
                continue
            prefix = sidecar_root / f"selection_preview_{submesh_index}"
            item: dict[str, object] = {
                "index": int(submesh_index),
                "selection_preview_output_path": _native_preview_delta_output_path("_selection.bin"),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                int(submesh_index),
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                faces, source_face_indices = _face_json_with_source_indices(submesh.faces, vertex_count)
                item["vertex_count"] = vertex_count
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                _put_source_face_indices_payload(item, prefix, source_face_indices)
            if selected_vertices:
                _put_i32_range_or_binary_payload(
                    item,
                    values=selected_vertices,
                    start_key="selected_vertex_start",
                    count_key="selected_vertex_count",
                    binary_key="selected_vertices_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_vertices.bin"),
                    max_count=vertex_count,
                )
            if selected_edges:
                item["selected_edges_binary"] = _write_edge_binary_payload(prefix.with_name(prefix.name + "_selected_edges.bin"), selected_edges)
            if selected_faces:
                _put_i32_range_or_binary_payload(
                    item,
                    values=selected_faces,
                    start_key="selected_face_start",
                    count_key="selected_face_count",
                    binary_key="selected_faces_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"),
                )
            if selected_all_vertices:
                item["selected_all_vertices"] = True
            submeshes.append(item)
        if not submeshes:
            return []
        report = _run_native_mesh_core_job(
            binary,
            "selection-preview-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "selection_preview",
                "submeshes": submeshes,
            },
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
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
            source_submesh_index = _index(raw_group.get("source_submesh_index"))
            if source_submesh_index is None or not 0 <= source_submesh_index < len(mesh.submeshes):
                continue
            group = _native_selection_preview_group(raw_group, source_submesh_index)
            if group is None:
                continue
            groups.append(group)
        return groups
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def select_native_mesh_uv_vertices(
    mesh: ParsedMesh,
    *,
    mode: str,
    uv_min: Sequence[object] = (0.0, 0.0),
    uv_max: Sequence[object] = (0.0, 0.0),
    points: Sequence[Sequence[object]] = (),
    timeout_seconds: float = 5.0,
) -> dict[int, set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    selection_mode = str(mode or "region").strip().lower()
    if selection_mode not in {"region", "lasso"}:
        return None
    polygon = [_vec2_json(point) for point in points or ()]
    if selection_mode == "lasso" and len(polygon) < 3:
        return {}
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_uv_selection_"))
    try:
        submeshes: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(mesh.submeshes or ()):
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0:
                continue
            prefix = sidecar_root / f"uv_selection_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "selected_vertices_output_path": _native_preview_delta_output_path("_uv_selected_vertices.bin"),
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
                uvs = getattr(submesh, "uvs", ()) or ()
                if len(uvs) != vertex_count:
                    continue
                item["vertex_count"] = vertex_count
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
            submeshes.append(item)
        if not submeshes:
            return {}
        report = _run_native_mesh_core_job(
            binary,
            "uv-selection-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "uv_selection",
                "mode": selection_mode,
                "uv_min": _vec2_json(uv_min),
                "uv_max": _vec2_json(uv_max),
                "points": polygon,
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
    return _apply_selection_report(mesh, report)

def summarize_native_mesh_uvs(
    mesh: ParsedMesh,
    selection: object | None = None,
    *,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    selected_vertices_by_submesh: Mapping[int, set[int]] = {}
    selected_faces_by_submesh: Mapping[int, set[int]] = {}
    selected_source_indices: set[int] = set()
    if selection is not None:
        try:
            selected_vertices_by_submesh = selection.vertex_map()  # type: ignore[assignment,union-attr]
            selected_faces_by_submesh = selection.face_map()  # type: ignore[assignment,union-attr]
            selected_source_indices = {
                index
                for raw_index in getattr(selection, "source_indices", ()) or ()
                if (index := _index(raw_index)) is not None and index >= 0
            }
        except AttributeError:
            selected_vertices_by_submesh = {}
            selected_faces_by_submesh = {}
            selected_source_indices = set()
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_uv_summary_"))
    try:
        submeshes: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(mesh.submeshes or ()):
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            if vertex_count <= 0:
                continue
            prefix = sidecar_root / f"uv_summary_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "part_name": str(getattr(submesh, "name", "") or f"part_{submesh_index}"),
                "material": str(getattr(submesh, "material", "") or ""),
                "texture": str(getattr(submesh, "texture", "") or ""),
                "source_selected": submesh_index in selected_source_indices,
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
                uvs = getattr(submesh, "uvs", ()) or ()
                raw_faces = getattr(submesh, "faces", ()) or ()
                if len(uvs) != vertex_count or not raw_faces:
                    continue
                faces, source_face_indices = _face_json_with_source_indices(raw_faces, vertex_count)
                if not faces:
                    continue
                item["vertex_count"] = vertex_count
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                _put_source_face_indices_payload(item, prefix, source_face_indices)
            selected_vertices = sorted(
                index
                for raw_index in selected_vertices_by_submesh.get(submesh_index, set())
                if (index := _index(raw_index)) is not None and 0 <= index < vertex_count
            )
            selected_faces = sorted(
                index
                for raw_index in selected_faces_by_submesh.get(submesh_index, set())
                if (index := _index(raw_index)) is not None and index >= 0
            )
            if selected_vertices:
                _put_i32_range_or_binary_payload(
                    item,
                    values=selected_vertices,
                    start_key="selected_vertex_start",
                    count_key="selected_vertex_count",
                    binary_key="selected_vertices_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_vertices.bin"),
                    max_count=vertex_count,
                )
            if selected_faces:
                _put_i32_range_or_binary_payload(
                    item,
                    values=selected_faces,
                    start_key="selected_face_start",
                    count_key="selected_face_count",
                    binary_key="selected_faces_binary",
                    binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"),
                )
            submeshes.append(item)
        if not submeshes:
            return {"status": "ok", "operation": "uv_summary", "island_count": 0, "selected_island_count": 0, "islands": []}
        report = _run_native_mesh_core_job(
            binary,
            "uv-summary-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "uv_summary",
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if not isinstance(report, dict):
        return None
    if str(report.get("operation") or "") != "uv_summary":
        return None
    return report

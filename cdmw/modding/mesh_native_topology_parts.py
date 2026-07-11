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

_append_native_duplicate_report_submeshes = _proxy("_append_native_duplicate_report_submeshes")
_apply_mesh_edit_report = _proxy("_apply_mesh_edit_report")
_finite_float = _proxy("_finite_float")
_index = _proxy("_index")
_mark_native_mesh_session_submeshes_current = _proxy("_mark_native_mesh_session_submeshes_current")
_native_job_kwargs = _proxy("_native_job_kwargs")
_recompute_normals_native_or_fallback = _proxy("_recompute_normals_native_or_fallback")
_refresh_mesh_totals = _proxy("_refresh_mesh_totals")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_topology_edit_submeshes = _proxy("_topology_edit_submeshes")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")


def apply_native_mesh_duplicate(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, int]] | None:
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
            preserve_normals=True,
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
                "operation": "duplicate",
                "edit": {"operation": "duplicate"},
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
    appended = _append_native_duplicate_report_submeshes(
        mesh,
        report,
        recompute_normals=recompute_normals,
        copy_extra_attrs=True,
    )
    if appended is None:
        return None
    _refresh_mesh_totals(mesh)
    return set(appended), appended

def apply_native_mesh_mirror(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    *,
    axis: object = "x",
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    axis_text = str(axis or "x").strip().lower()
    if axis_text not in {"x", "y", "z"}:
        axis_text = "x"
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
                "operation": "mirror",
                "edit": {"operation": "mirror", "axis": axis_text},
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
    appended = _append_native_duplicate_report_submeshes(
        mesh,
        report,
        recompute_normals=recompute_normals,
        copy_extra_attrs=True,
    )
    if appended is None:
        return None
    _refresh_mesh_totals(mesh)
    return set(appended), appended

def apply_native_mesh_separate(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> MeshPartSplitResult | None:
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
            set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return MeshPartSplitResult()
        if len(submeshes) != 1:
            return None
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "separate",
                "edit": {"operation": "separate"},
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
    raw_items = report.get("submeshes")
    if not isinstance(raw_items, list):
        return None
    source_items = [item for item in raw_items if isinstance(item, Mapping) and not bool(item.get("append_submesh"))]
    append_items = [item for item in raw_items if isinstance(item, Mapping) and bool(item.get("append_submesh"))]
    if not source_items and not append_items:
        return MeshPartSplitResult()
    source_report = dict(report)
    source_report["submeshes"] = source_items
    changed = _apply_mesh_edit_report(mesh, source_report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, _changed_vertices = changed
    append_report = dict(report)
    append_report["submeshes"] = append_items
    appended = _append_native_duplicate_report_submeshes(
        mesh,
        append_report,
        recompute_normals=False,
        copy_extra_attrs=True,
        reset_source_descriptors=True,
    )
    if appended is None:
        return None
    new_index = min(appended) if appended else -1
    source_index = appended.get(new_index, -1) if new_index >= 0 else (min(affected) if affected else -1)
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        normal_targets = set(affected) | set(appended)
        _recompute_normals_native_or_fallback(mesh, normal_targets, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    moved_face_count = 0
    moved_vertex_count = 0
    if append_items:
        moved_face_count = _index(append_items[0].get("added_faces")) or 0
        moved_vertex_count = _index(append_items[0].get("added_vertices")) or 0
    return MeshPartSplitResult(
        source_submesh_index=source_index,
        new_submesh_index=new_index,
        moved_face_count=moved_face_count,
        moved_vertex_count=moved_vertex_count,
    )

def apply_native_mesh_bridge(
    mesh: ParsedMesh,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]],
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
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            {},
            {},
            selected_edges_by_submesh or {},
            set(),
            preserve_normals=not recompute_normals,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if not submeshes:
            return set()
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "bridge",
                "edit": {"operation": "bridge"},
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

def apply_native_mesh_split(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]] | None = None,
    params: Mapping[str, object] | None = None,
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
                "operation": "split",
                "edit": {"operation": "split"},
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

def apply_native_mesh_subdivide(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    selected_vertices_by_submesh: Mapping[int, set[int]],
    params: Mapping[str, object],
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    all_faces_by_submesh: set[int] | None = None,
    refine: bool = False,
    recompute_normals: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 15.0,
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    operation = "refine_smooth" if refine else "subdivide"
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_topology_"))
    try:
        submeshes = _topology_edit_submeshes(
            mesh,
            selected_faces_by_submesh,
            selected_vertices_by_submesh,
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
                "operation": operation,
                "edit": {
                    "operation": operation,
                    "max_faces_per_submesh": max(1, _index(params.get("max_faces_per_submesh", 256)) or 256),
                    "smooth_strength": max(0.0, min(1.0, _finite_float(params.get("smooth_strength", params.get("strength", 0.5)), 0.5))),
                    "smooth_iterations": max(1, min(12, _index(params.get("smooth_iterations", params.get("iterations", 2))) or 2)),
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
    changed = _apply_mesh_edit_report(mesh, report, skip_topology_normals=recompute_normals)
    if changed is None:
        return None
    affected, changed_vertices = changed
    _mark_native_mesh_session_submeshes_current(mesh, affected)
    if recompute_normals:
        _recompute_normals_native_or_fallback(mesh, affected, timeout_seconds=timeout_seconds)
    _refresh_mesh_totals(mesh)
    return affected, changed_vertices

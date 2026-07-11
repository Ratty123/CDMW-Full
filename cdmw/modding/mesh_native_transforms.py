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

_apply_transform_report = _proxy("_apply_transform_report")
_contiguous_i32_range = _proxy("_contiguous_i32_range")
_ensure_native_mesh_session_submesh = _proxy("_ensure_native_mesh_session_submesh")
_finite_float = _proxy("_finite_float")
_index = _proxy("_index")
_mark_native_mesh_session_submeshes_current = _proxy("_mark_native_mesh_session_submeshes_current")
_mirror_pairs_json = _proxy("_mirror_pairs_json")
_native_binary_descriptor = _proxy("_native_binary_descriptor")
_native_existing_binary_descriptor = _proxy("_native_existing_binary_descriptor")
_native_i32_range_descriptor = _proxy("_native_i32_range_descriptor")
_native_job_kwargs = _proxy("_native_job_kwargs")
_native_preview_delta_output_path = _proxy("_native_preview_delta_output_path")
_new_native_sparse_vertex_snapshot_id = _proxy("_new_native_sparse_vertex_snapshot_id")
_put_i32_range_or_binary_payload = _proxy("_put_i32_range_or_binary_payload")
_put_selected_vertices_payload = _proxy("_put_selected_vertices_payload")
_put_vertex_indices_payload = _proxy("_put_vertex_indices_payload")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_selection_domain_submesh_items = _proxy("_selection_domain_submesh_items")
_vec3_json = _proxy("_vec3_json")
_vertex_indices_from_history_descriptor = _proxy("_vertex_indices_from_history_descriptor")
_write_int_binary_payload = _proxy("_write_int_binary_payload")
_write_vec3_binary_payload = _proxy("_write_vec3_binary_payload")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")


def apply_native_mesh_transform(
    mesh: ParsedMesh,
    vertices_by_submesh: Mapping[int, set[int]],
    *,
    translate: Vec3,
    scale: Vec3,
    rotate: Vec3,
    pivot: Vec3 | None,
    snap: float = 0.0,
    mirror_x: bool = False,
    mirror_pairs_by_submesh: Mapping[int, Mapping[int, int]] | None = None,
    history_delta: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root: Path | None = None
    try:
        sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_transform_"))
        submeshes = []
        for submesh_index, selected in sorted(vertices_by_submesh.items()):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            kept = sorted(index for index in selected if 0 <= index < len(submesh.vertices))
            if not kept:
                continue
            item: dict[str, object] = {"index": submesh_index}
            prefix = sidecar_root / f"transform_{submesh_index}"
            item["changed_vertices_output_path"] = _native_preview_delta_output_path("_changed_vertices.bin")
            item["changed_positions_output_path"] = _native_preview_delta_output_path("_positions.bin")
            if history_delta:
                item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
                item["sparse_output"] = True
                _put_i32_range_or_binary_payload(
                    item,
                    values=kept,
                    start_key="selected_vertex_start",
                    count_key="selected_vertex_count",
                    binary_key="selected_vertices_binary",
                    binary_path=prefix.with_name(prefix.name + "_indices.bin"),
                    max_count=len(submesh.vertices),
                )
                mirror_pairs = _mirror_pairs_json(mirror_pairs_by_submesh, submesh_index) if mirror_x else []
                if mirror_pairs:
                    item["mirror_pairs"] = mirror_pairs
            elif mirror_x:
                _put_selected_vertices_payload(item, prefix, kept, max_count=len(submesh.vertices))
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                mirror_pairs = _mirror_pairs_json(mirror_pairs_by_submesh, submesh_index)
                if mirror_pairs:
                    item["mirror_pairs"] = mirror_pairs
            else:
                item["vertex_count"] = len(submesh.vertices)
                compact_range = _contiguous_i32_range(kept, max_count=len(submesh.vertices))
                if compact_range is not None:
                    item["selected_vertex_start"] = compact_range[0]
                    item["selected_vertex_count"] = compact_range[1]
                    item["vertex_index_start"] = compact_range[0]
                    item["vertex_index_count"] = compact_range[1]
                else:
                    selected_descriptor = _write_int_binary_payload(prefix.with_name(prefix.name + "_indices.bin"), kept)
                    item["selected_vertices_binary"] = selected_descriptor
                    item["vertex_indices_binary"] = selected_descriptor
                item["vertex_positions_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_positions.bin"),
                    (submesh.vertices[index] for index in kept),
                )
            submeshes.append(item)
        if not submeshes:
            return {}

        payload: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "transform",
            "transform": {
                "translate": _vec3_json(translate),
                "scale": _vec3_json(scale, fallback=1.0),
                "rotate": _vec3_json(rotate),
                "pivot": _vec3_json(pivot or (0.0, 0.0, 0.0)),
                "pivot_from_selection": pivot is None,
                "snap": _finite_float(snap, 0.0),
                "mirror_x": bool(mirror_x),
            },
            "submeshes": submeshes,
        }
        if history_delta:
            payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("transform")
        report = _run_native_mesh_core_job(
            binary,
            "transform-json",
            payload,
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        changed = _apply_transform_report(mesh, report)
        if changed:
            _mark_native_mesh_session_submeshes_current(mesh, changed.keys())
        return changed
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        if sidecar_root is not None:
            shutil.rmtree(sidecar_root, ignore_errors=True)

def apply_native_mesh_transform_selection(
    mesh: ParsedMesh,
    *,
    vertices_by_submesh: Mapping[int, set[int]],
    edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    faces_by_submesh: Mapping[int, set[int]],
    source_indices: Sequence[int],
    translate: Vec3,
    scale: Vec3,
    rotate: Vec3,
    pivot: Vec3 | None,
    snap: float = 0.0,
    mirror_x: bool = False,
    mirror_pairs_by_submesh: Mapping[int, Mapping[int, int]] | None = None,
    history_delta: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_transform_selection_"))
    try:
        submeshes = _selection_domain_submesh_items(
            mesh,
            vertices_by_submesh=vertices_by_submesh,
            edges_by_submesh=edges_by_submesh,
            faces_by_submesh=faces_by_submesh,
            source_indices=source_indices,
            binary=binary,
            sidecar_root=sidecar_root,
            stop_event=stop_event,
            timeout_seconds=timeout_seconds,
        )
        if submeshes is None:
            return None
        if not submeshes:
            return {}
        for item in submeshes:
            item["sparse_output"] = True
            submesh_index = _index(item.get("index"))
            if submesh_index is not None:
                item["changed_vertices_output_path"] = _native_preview_delta_output_path("_changed_vertices.bin")
                item["changed_positions_output_path"] = _native_preview_delta_output_path("_positions.bin")
                if history_delta:
                    item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")
            mirror_pairs = _mirror_pairs_json(mirror_pairs_by_submesh, int(item["index"])) if mirror_x else []
            if mirror_pairs:
                item["mirror_pairs"] = mirror_pairs
        payload: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "transform",
            "transform": {
                "translate": _vec3_json(translate),
                "scale": _vec3_json(scale, fallback=1.0),
                "rotate": _vec3_json(rotate),
                "pivot": _vec3_json(pivot or (0.0, 0.0, 0.0)),
                "pivot_from_selection": pivot is None,
                "snap": _finite_float(snap, 0.0),
                "mirror_x": bool(mirror_x),
            },
            "submeshes": submeshes,
        }
        if history_delta:
            payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("transform-selection")
        report = _run_native_mesh_core_job(
            binary,
            "transform-json",
            payload,
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        changed = _apply_transform_report(mesh, report)
        if changed:
            _mark_native_mesh_session_submeshes_current(mesh, changed.keys())
        return changed
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def apply_native_mesh_transform_binary_selection(
    mesh: ParsedMesh,
    *,
    selected_vertices_binary_by_submesh: Mapping[object, object],
    translate: Vec3,
    scale: Vec3,
    rotate: Vec3,
    pivot: Vec3 | None,
    snap: float = 0.0,
    mirror_x: bool = False,
    mirror_pairs_by_submesh: Mapping[int, Mapping[int, int]] | None = None,
    history_delta: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if not selected_vertices_binary_by_submesh:
        return None
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    try:
        submeshes: list[dict[str, object]] = []
        for raw_submesh_index, raw_descriptor in sorted(selected_vertices_binary_by_submesh.items(), key=lambda item: str(item[0])):
            submesh_index = _index(raw_submesh_index)
            if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
                continue
            selected_descriptor = _native_existing_binary_descriptor(
                raw_descriptor,
                components=1,
                kinds={"i32"},
            )
            vertex_count = len(getattr(mesh.submeshes[submesh_index], "vertices", ()) or ())
            selected_range = _native_i32_range_descriptor(raw_descriptor, max_count=vertex_count)
            if selected_descriptor is None and selected_range is None:
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
            item: dict[str, object] = {
                "index": submesh_index,
                "session_id": session_id,
                "sparse_output": True,
                "changed_vertices_output_path": _native_preview_delta_output_path("_changed_vertices.bin"),
                "changed_positions_output_path": _native_preview_delta_output_path("_positions.bin"),
            }
            if selected_descriptor is not None:
                item["selected_vertices_binary"] = selected_descriptor
            elif selected_range is not None:
                item["selected_vertex_start"] = selected_range[0]
                item["selected_vertex_count"] = selected_range[1]
            if history_delta:
                item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")
            mirror_pairs = _mirror_pairs_json(mirror_pairs_by_submesh, submesh_index) if mirror_x else []
            if mirror_pairs:
                item["mirror_pairs"] = mirror_pairs
            submeshes.append(item)
        if not submeshes:
            return {}
        payload: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "transform",
            "transform": {
                "translate": _vec3_json(translate),
                "scale": _vec3_json(scale, fallback=1.0),
                "rotate": _vec3_json(rotate),
                "pivot": _vec3_json(pivot or (0.0, 0.0, 0.0)),
                "pivot_from_selection": pivot is None,
                "snap": _finite_float(snap, 0.0),
                "mirror_x": bool(mirror_x),
            },
            "submeshes": submeshes,
        }
        if history_delta:
            payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("transform-binary")
        report = _run_native_mesh_core_job(
            binary,
            "transform-json",
            payload,
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        changed = _apply_transform_report(mesh, report)
        if changed:
            _mark_native_mesh_session_submeshes_current(mesh, changed.keys())
        return changed
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None

def apply_native_mesh_sparse_vertex_restore(
    mesh: ParsedMesh,
    before_positions_by_submesh: Mapping[object, object],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
    history_delta: bool = False,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    if not isinstance(before_positions_by_submesh, Mapping) or not before_positions_by_submesh:
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_sparse_restore_"))
    try:
        submeshes: list[dict[str, object]] = []
        for raw_submesh_index, raw_positions_by_vertex in sorted(
            before_positions_by_submesh.items(),
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
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
            if not session_id:
                return None
            raw_groups = raw_positions_by_vertex.get("groups") if isinstance(raw_positions_by_vertex, Mapping) else None
            restore_groups = tuple(raw_groups) if isinstance(raw_groups, (tuple, list)) and raw_groups else (raw_positions_by_vertex,)
            for raw_group in restore_groups:
                if not isinstance(raw_group, Mapping):
                    continue
                restore_items: list[tuple[int, Vec3]] = []
                raw_descriptor = dict(raw_group)
                raw_sparse_snapshot_id = str(
                    raw_descriptor.get("native_sparse_snapshot_id")
                    or raw_descriptor.get("sparse_snapshot_id")
                    or ""
                ).strip()
                raw_positions_binary = raw_descriptor.get("before_positions_binary")
                descriptor_indices = _vertex_indices_from_history_descriptor(raw_descriptor, vertex_count)
                descriptor_positions_binary = None
                if isinstance(raw_positions_binary, Mapping) and descriptor_indices is not None:
                    descriptor_positions_binary = _native_binary_descriptor(
                        raw_positions_binary,
                        expected_count=len(descriptor_indices),
                        components=3,
                        kind="f64",
                    )
                    if descriptor_positions_binary is None and not raw_sparse_snapshot_id:
                        return None
                if descriptor_indices is None:
                    for raw_vertex_index, raw_position in raw_descriptor.items():
                        vertex_index = _index(raw_vertex_index)
                        if vertex_index is None or vertex_index < 0 or vertex_index >= vertex_count:
                            continue
                        try:
                            position = (
                                float(raw_position[0]),  # type: ignore[index]
                                float(raw_position[1]),  # type: ignore[index]
                                float(raw_position[2]),  # type: ignore[index]
                            )
                        except (TypeError, ValueError, OverflowError, IndexError):
                            continue
                        if not all(math.isfinite(component) for component in position):
                            continue
                        restore_items.append((vertex_index, position))
                    if not restore_items:
                        continue
                    restore_items.sort(key=lambda item: item[0])
                prefix = sidecar_root / f"restore_{submesh_index}_{len(submeshes)}"
                item = {
                    "index": submesh_index,
                    "session_id": session_id,
                    "vertex_count": vertex_count,
                    "changed_vertices_output_path": _native_preview_delta_output_path("_changed_vertices.bin"),
                    "changed_positions_output_path": _native_preview_delta_output_path("_positions.bin"),
                }
                _put_vertex_indices_payload(
                    item,
                    prefix,
                    descriptor_indices if descriptor_indices is not None else [item[0] for item in restore_items],
                    max_count=vertex_count,
                )
                if raw_sparse_snapshot_id:
                    item["native_sparse_snapshot_id"] = raw_sparse_snapshot_id
                if descriptor_positions_binary is not None:
                    item["vertex_positions_binary"] = descriptor_positions_binary
                elif raw_sparse_snapshot_id:
                    pass
                else:
                    item["vertex_positions_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_positions.bin"),
                        [item[1] for item in restore_items],
                    )
                if history_delta:
                    item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")
                submeshes.append(item)
        if not submeshes:
            return {}
        payload: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "restore_vertices",
            "submeshes": submeshes,
        }
        if history_delta:
            payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("restore")
        report = _run_native_mesh_core_job(
            binary,
            "restore-vertices-json",
            payload,
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        changed = _apply_transform_report(mesh, report)
        if changed is None:
            return None
        if changed:
            _mark_native_mesh_session_submeshes_current(mesh, changed.keys())
        return changed
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

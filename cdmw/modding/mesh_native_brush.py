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
_face_json = _proxy("_face_json")
_finite_float = _proxy("_finite_float")
_index = _proxy("_index")
_mark_native_mesh_session_submeshes_current = _proxy("_mark_native_mesh_session_submeshes_current")
_mirror_pairs_json = _proxy("_mirror_pairs_json")
_native_existing_binary_descriptor = _proxy("_native_existing_binary_descriptor")
_native_i32_range_descriptor = _proxy("_native_i32_range_descriptor")
_native_job_kwargs = _proxy("_native_job_kwargs")
_native_preview_delta_output_path = _proxy("_native_preview_delta_output_path")
_new_native_sparse_vertex_snapshot_id = _proxy("_new_native_sparse_vertex_snapshot_id")
_put_selected_vertices_payload = _proxy("_put_selected_vertices_payload")
_recompute_normals_native_or_fallback = _proxy("_recompute_normals_native_or_fallback")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_selection_domain_submesh_items = _proxy("_selection_domain_submesh_items")
_vec3_json = _proxy("_vec3_json")
_vertex_weights_json = _proxy("_vertex_weights_json")
_write_face_binary_payload = _proxy("_write_face_binary_payload")
_write_f64_binary_payload = _proxy("_write_f64_binary_payload")
_write_int_binary_payload = _proxy("_write_int_binary_payload")
_write_vec2_binary_payload = _proxy("_write_vec2_binary_payload")
_write_vec3_binary_payload = _proxy("_write_vec3_binary_payload")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")


def _vertex_weights_binary_payloads(sidecar_root: Path | None, value: object) -> dict[str, object] | None:
    if sidecar_root is None or value is None:
        return None
    items = value.items() if isinstance(value, Mapping) else value
    try:
        iterator = iter(items)  # type: ignore[arg-type]
    except TypeError:
        return None
    indices: list[int] = []
    weights: list[float] = []
    for item in iterator:
        try:
            raw_index, raw_weight = item  # type: ignore[misc]
        except (TypeError, ValueError):
            continue
        index = _index(raw_index)
        if index is None or index < 0:
            continue
        indices.append(index)
        weights.append(max(0.0, min(1.0, _finite_float(raw_weight, 0.0))))
    if not indices:
        return None
    prefix = sidecar_root / "brush_vertex_weights"
    return {
        "vertex_weight_indices_binary": _write_int_binary_payload(
            prefix.with_name(prefix.name + "_indices.bin"), indices
        ),
        "vertex_weights_binary": _write_f64_binary_payload(
            prefix.with_name(prefix.name + "_weights.bin"), weights, fallback=0.0
        ),
    }


def _native_brush_edit_payload(params: Mapping[str, object], sidecar_root: Path | None = None) -> dict[str, object]:
    edit_payload: dict[str, object] = {
        "operation": "brush",
        "tool": str(params.get("tool", "grab") or "grab"),
        "center": _vec3_json(params.get("center", (0.0, 0.0, 0.0))),
        "radius": max(0.0, _finite_float(params.get("radius", 1.0), 1.0)),
        "strength": max(0.0, min(1.0, _finite_float(params.get("strength", 1.0), 1.0))),
        "drag_delta": _vec3_json(params.get("drag_delta", params.get("delta", (0.0, 0.0, 0.0)))),
        "amount": _finite_float(params.get("amount", 0.0), 0.0),
        "falloff": str(params.get("falloff", "smooth") or "smooth"),
        "mirror_x": bool(params.get("mirror_x", False)),
        "invert": bool(params.get("invert", False)),
        "iterations": max(1, _index(params.get("iterations", 1)) or 1),
        "sparse_output": True,
    }
    weight_sidecars = _vertex_weights_binary_payloads(sidecar_root, params.get("vertex_weights"))
    if weight_sidecars is not None:
        edit_payload.update(weight_sidecars)
    else:
        vertex_weights = _vertex_weights_json(params.get("vertex_weights"))
        if vertex_weights:
            edit_payload["vertex_weights"] = vertex_weights
    return edit_payload

def apply_native_mesh_brush(
    mesh: ParsedMesh,
    vertices_by_submesh: Mapping[int, set[int] | None],
    params: Mapping[str, object],
    *,
    history_delta: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="cdmw_mesh_core_brush_") as sidecar_root_raw:
            sidecar_root = Path(sidecar_root_raw)
            submeshes = []
            for submesh_index, selected in sorted(vertices_by_submesh.items()):
                if not 0 <= submesh_index < len(mesh.submeshes):
                    continue
                submesh = mesh.submeshes[submesh_index]
                vertex_count = len(submesh.vertices)
                if vertex_count <= 0:
                    continue
                prefix = sidecar_root / f"submesh_{submesh_index}"
                item: dict[str, object] = {
                    "index": submesh_index,
                    "selection_restricts_vertices": selected is not None,
                    "changed_vertices_output_path": _native_preview_delta_output_path("_changed_vertices.bin"),
                    "changed_positions_output_path": _native_preview_delta_output_path("_positions.bin"),
                }
                if history_delta:
                    item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")
                session_id = _ensure_native_mesh_session_submesh(
                    binary,
                    mesh,
                    submesh_index,
                    timeout_seconds=timeout_seconds,
                ) if stop_event is None else None
                if session_id:
                    item["session_id"] = session_id
                    item["sparse_output"] = True
                    mirror_pairs = _mirror_pairs_json(params.get("mirror_pairs_by_submesh"), submesh_index)
                    if mirror_pairs:
                        item["mirror_pairs"] = mirror_pairs
                else:
                    faces = _face_json(submesh.faces, vertex_count)
                    item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                    item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                    item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), submesh.normals, fallback=0.0)
                    item["mirror_pairs"] = _mirror_pairs_json(params.get("mirror_pairs_by_submesh"), submesh_index)
                    if len(submesh.uvs) == len(submesh.vertices):
                        item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs)
                if selected is not None:
                    kept = sorted(index for index in selected if 0 <= index < vertex_count)
                    if not kept:
                        continue
                    _put_selected_vertices_payload(item, prefix, kept, max_count=vertex_count)
                submeshes.append(item)
            if not submeshes:
                return {}

            payload: dict[str, object] = {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "brush",
                "edit": _native_brush_edit_payload(params, sidecar_root),
                "submeshes": submeshes,
            }
            if history_delta:
                payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("brush")
            report = _run_native_mesh_core_job(
                binary,
                "edit-json",
                payload,
                **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
            )
            if report is None:
                return None
            changed = _apply_mesh_edit_report(mesh, report)
            if changed is None:
                return None
            _mark_native_mesh_session_submeshes_current(mesh, changed[0])
            if bool(params.get("recompute_normals", True)):
                _recompute_normals_native_or_fallback(mesh, changed[0], timeout_seconds=timeout_seconds)
            return changed[1]
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None

def apply_native_mesh_brush_binary_selection(
    mesh: ParsedMesh,
    *,
    selected_vertices_binary_by_submesh: Mapping[object, object],
    vertex_weights_binary_by_submesh: Mapping[object, object] | None,
    params: Mapping[str, object],
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
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_brush_binary_selection_"))
    try:
        submeshes: list[dict[str, object]] = []
        weight_descriptors: dict[int, dict[str, object]] = {}
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
                "selection_restricts_vertices": True,
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
            mirror_pairs = _mirror_pairs_json(params.get("mirror_pairs_by_submesh"), submesh_index)
            if mirror_pairs:
                item["mirror_pairs"] = mirror_pairs
            raw_weight_descriptor = (
                vertex_weights_binary_by_submesh.get(submesh_index, vertex_weights_binary_by_submesh.get(str(submesh_index)))
                if isinstance(vertex_weights_binary_by_submesh, Mapping)
                else None
            )
            weight_descriptor = (
                _native_existing_binary_descriptor(
                    raw_weight_descriptor,
                    components=1,
                    kinds={"f32", "f64"},
                    expected_count=int(selected_descriptor["count"]),
                )
                if selected_descriptor is not None
                else None
            )
            if weight_descriptor is not None:
                weight_descriptors[submesh_index] = weight_descriptor
            submeshes.append(item)
        if not submeshes:
            return {}
        if weight_descriptors and len(submeshes) != 1:
            return None
        edit_payload = _native_brush_edit_payload(params, sidecar_root)
        if weight_descriptors:
            submesh_index = int(submeshes[0]["index"])
            edit_payload["vertex_weight_indices_binary"] = submeshes[0]["selected_vertices_binary"]
            edit_payload["vertex_weights_binary"] = weight_descriptors[submesh_index]
            edit_payload.pop("vertex_weights", None)

        payload: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "brush",
            "edit": edit_payload,
            "submeshes": submeshes,
        }
        if history_delta:
            payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("brush-binary")
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            payload,
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        changed = _apply_mesh_edit_report(mesh, report)
        if changed is None:
            return None
        _mark_native_mesh_session_submeshes_current(mesh, changed[0])
        if bool(params.get("recompute_normals", True)):
            _recompute_normals_native_or_fallback(mesh, changed[0], timeout_seconds=timeout_seconds)
        return changed[1]
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def apply_native_mesh_brush_selection(
    mesh: ParsedMesh,
    *,
    vertices_by_submesh: Mapping[int, set[int]],
    edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    faces_by_submesh: Mapping[int, set[int]],
    source_indices: Sequence[int],
    params: Mapping[str, object],
    history_delta: bool = False,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_brush_selection_"))
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
            item["selection_restricts_vertices"] = True
            item["sparse_output"] = True
            submesh_index = _index(item.get("index"))
            if submesh_index is not None:
                item["changed_vertices_output_path"] = _native_preview_delta_output_path("_changed_vertices.bin")
                item["changed_positions_output_path"] = _native_preview_delta_output_path("_positions.bin")
                if history_delta:
                    item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")
            mirror_pairs = _mirror_pairs_json(params.get("mirror_pairs_by_submesh"), int(item["index"]))
            if mirror_pairs:
                item["mirror_pairs"] = mirror_pairs
        payload: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "brush",
            "edit": _native_brush_edit_payload(params, sidecar_root),
            "submeshes": submeshes,
        }
        if history_delta:
            payload["sparse_snapshot_id"] = _new_native_sparse_vertex_snapshot_id("brush-selection")
        report = _run_native_mesh_core_job(
            binary,
            "edit-json",
            payload,
            **_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds),
        )
        if report is None:
            return None
        changed = _apply_mesh_edit_report(mesh, report)
        if changed is None:
            return None
        _mark_native_mesh_session_submeshes_current(mesh, changed[0])
        if bool(params.get("recompute_normals", True)):
            _recompute_normals_native_or_fallback(mesh, changed[0], timeout_seconds=timeout_seconds)
        return changed[1]
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

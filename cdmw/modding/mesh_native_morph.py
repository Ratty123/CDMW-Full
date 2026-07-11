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

_ensure_native_mesh_session_submesh = _proxy("_ensure_native_mesh_session_submesh")
_face_json = _proxy("_face_json")
_finite_float = _proxy("_finite_float")
_index = _proxy("_index")
_invalidate_native_mesh_session_submeshes = _proxy("_invalidate_native_mesh_session_submeshes")
_read_i32_binary_report_payload = _proxy("_read_i32_binary_report_payload")
_read_vec3_binary_payload = _proxy("_read_vec3_binary_payload")
_read_vec3_binary_report_payload = _proxy("_read_vec3_binary_report_payload")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_write_face_binary_payload = _proxy("_write_face_binary_payload")
_write_vec3_binary_payload = _proxy("_write_vec3_binary_payload")
dispose_native_mesh_submesh_snapshot = _proxy("dispose_native_mesh_submesh_snapshot")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")
restore_native_mesh_submesh_snapshot = _proxy("restore_native_mesh_submesh_snapshot")
snapshot_native_mesh_submeshes = _proxy("snapshot_native_mesh_submeshes")


def _morph_submesh_values(raw: object, submesh_index: int) -> object:
    if raw is None:
        return ()
    try:
        if isinstance(raw, Mapping):
            return raw.get(submesh_index, ())
        return raw[submesh_index]  # type: ignore[index]
    except Exception:
        return ()


def apply_native_morph_slider_values(
    base_mesh: ParsedMesh,
    deltas: Sequence[object],
    values: Mapping[str, float],
    post_edit_deltas: object = None,
    *,
    timeout_seconds: float = 20.0,
) -> ParsedMesh | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_morph_apply_"))

    try:
        submeshes: list[dict[str, object]] = []
        for submesh_index, submesh in enumerate(base_mesh.submeshes):
            prefix = sidecar_root / f"submesh_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "output_vertices_path": str(prefix.with_name(prefix.name + "_out_vertices.bin")),
                "output_normals_path": str(prefix.with_name(prefix.name + "_out_normals.bin")),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                base_mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                vertices = submesh.vertices or ()
                faces = _face_json(submesh.faces, len(vertices))
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            post_values = _morph_submesh_values(post_edit_deltas, submesh_index) or ()
            if post_values:
                item["post_edit_deltas_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_post_edit_deltas.bin"),
                    post_values,
                    fallback=0.0,
                )
            submeshes.append(item)
        if not submeshes:
            return None

        native_deltas: list[dict[str, object]] = []
        for delta_index, delta in enumerate(deltas or ()):
            slider_id = str(getattr(delta, "slider_id", "") or "")
            default_percent = _finite_float(getattr(delta, "default_percent", 0.0), 0.0)
            raw_percent = values.get(slider_id, default_percent) if isinstance(values, Mapping) else default_percent
            percent = _finite_float(raw_percent, default_percent)
            min_percent = _finite_float(getattr(delta, "min_percent", -100.0), -100.0)
            max_percent = _finite_float(getattr(delta, "max_percent", 100.0), 100.0)
            if min_percent > max_percent:
                min_percent, max_percent = max_percent, min_percent
            factor = max(min_percent, min(max_percent, percent)) / 100.0
            if abs(factor) <= 1e-15:
                continue
            delta_submeshes: list[dict[str, object]] = []
            for submesh_index, raw_submesh_deltas in enumerate(getattr(delta, "deltas", ()) or ()):
                if not 0 <= submesh_index < len(base_mesh.submeshes):
                    continue
                prefix = sidecar_root / f"delta_{delta_index}_{submesh_index}"
                delta_submeshes.append(
                    {
                        "index": submesh_index,
                        "deltas_binary": _write_vec3_binary_payload(
                            prefix.with_name(prefix.name + "_deltas.bin"),
                            raw_submesh_deltas,
                            fallback=0.0,
                        ),
                    }
                )
            native_deltas.append({"slider_id": slider_id, "factor": factor, "submeshes": delta_submeshes})

        report = _run_native_mesh_core_job(
            binary,
            "morph-apply-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "morph_apply",
                "submeshes": submeshes,
                "deltas": native_deltas,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            return None
        raw_reports = report.get("submeshes")
        if not isinstance(raw_reports, list):
            return None
        outputs: dict[int, tuple[list[Vec3], list[Vec3]]] = {}
        for raw_item in raw_reports:
            if not isinstance(raw_item, Mapping):
                return None
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or not 0 <= submesh_index < len(base_mesh.submeshes):
                return None
            vertex_count = _index(raw_item.get("vertex_count"))
            normal_count = _index(raw_item.get("normal_count"))
            if vertex_count is None or normal_count is None:
                return None
            vertices_path = Path(str(raw_item.get("vertices_binary") or ""))
            normals_path = Path(str(raw_item.get("normals_binary") or ""))
            vertices = _read_vec3_binary_payload(vertices_path, expected_count=vertex_count)
            normals = _read_vec3_binary_payload(normals_path, expected_count=normal_count)
            if vertices is None or normals is None or len(normals) != len(vertices):
                return None
            if len(vertices) != len(base_mesh.submeshes[submesh_index].vertices):
                return None
            outputs[submesh_index] = (vertices, normals)
        if len(outputs) != len(base_mesh.submeshes):
            return None

        from cdmw.modding.scene_importer import refresh_parsed_mesh_totals

        base_snapshot = snapshot_native_mesh_submeshes(base_mesh, timeout_seconds=timeout_seconds)
        if not isinstance(base_snapshot, Mapping):
            return None
        result = ParsedMesh()
        try:
            if not restore_native_mesh_submesh_snapshot(result, base_snapshot, timeout_seconds=timeout_seconds):
                return None
        finally:
            dispose_native_mesh_submesh_snapshot(
                base_snapshot,
                timeout_seconds=min(float(timeout_seconds or 20.0), 2.0),
            )
        if len(result.submeshes) != len(base_mesh.submeshes):
            return None
        for submesh_index, (vertices, normals) in outputs.items():
            submesh = result.submeshes[submesh_index]
            submesh.vertices = vertices
            submesh.normals = normals
            submesh.vertex_count = len(vertices)
            submesh.face_count = len(submesh.faces)
        _invalidate_native_mesh_session_submeshes(result, range(len(result.submeshes)))
        refresh_parsed_mesh_totals(result)
        return result
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def build_native_morph_post_edit_deltas(
    working_mesh: object,
    slider_only_mesh: object,
    *,
    timeout_seconds: float = 20.0,
) -> list[list[Vec3]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    working_submeshes = getattr(working_mesh, "submeshes", ()) or ()
    slider_submeshes = getattr(slider_only_mesh, "submeshes", ()) or ()
    if not working_submeshes or not slider_submeshes:
        return []
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_morph_post_delta_"))
    try:
        submeshes: list[dict[str, object]] = []
        expected_counts: dict[int, int] = {}
        for submesh_index, (working_submesh, slider_submesh) in enumerate(zip(working_submeshes, slider_submeshes)):
            working_vertices = getattr(working_submesh, "vertices", ()) or ()
            slider_vertices = getattr(slider_submesh, "vertices", ()) or ()
            if len(working_vertices) != len(slider_vertices):
                return None
            prefix = sidecar_root / f"submesh_{submesh_index}"
            expected_counts[submesh_index] = len(working_vertices)
            submeshes.append(
                {
                    "index": submesh_index,
                    "working_vertices_binary": _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_working_vertices.bin"),
                        working_vertices,
                    ),
                    "slider_vertices_binary": _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_slider_vertices.bin"),
                        slider_vertices,
                    ),
                    "deltas_output_path": str(prefix.with_name(prefix.name + "_deltas.bin")),
                }
            )
        if not submeshes:
            return []
        report = _run_native_mesh_core_job(
            binary,
            "morph-post-edit-delta-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "morph_post_edit_delta",
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            return None
        raw_reports = report.get("submeshes")
        if not isinstance(raw_reports, list):
            return None
        outputs: list[list[Vec3]] = [[] for _submesh in submeshes]
        seen: set[int] = set()
        for raw_item in raw_reports:
            if not isinstance(raw_item, Mapping):
                return None
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or submesh_index not in expected_counts:
                return None
            vertex_count = _index(raw_item.get("vertex_count"))
            if vertex_count is None or vertex_count != expected_counts[submesh_index]:
                return None
            if bool(raw_item.get("zero_delta")):
                outputs[submesh_index] = []
                seen.add(submesh_index)
                continue
            deltas = _read_vec3_binary_report_payload(raw_item.get("deltas_binary"), expected_count=vertex_count)
            if deltas is None:
                return None
            outputs[submesh_index] = deltas
            seen.add(submesh_index)
        if seen != set(expected_counts):
            return None
        return outputs
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def build_native_morph_target_delta(
    base_mesh: ParsedMesh,
    target_mesh: ParsedMesh,
    *,
    timeout_seconds: float = 20.0,
) -> tuple[tuple[Vec3, ...], ...] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    if not isinstance(base_mesh, ParsedMesh) or not isinstance(target_mesh, ParsedMesh):
        return None
    base_submeshes = getattr(base_mesh, "submeshes", ()) or ()
    target_submeshes = getattr(target_mesh, "submeshes", ()) or ()
    if len(base_submeshes) != len(target_submeshes):
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_morph_target_delta_"))
    try:
        submeshes: list[dict[str, object]] = []
        expected_counts: dict[int, int] = {}
        for submesh_index, (base_submesh, target_submesh) in enumerate(zip(base_submeshes, target_submeshes)):
            base_vertices = getattr(base_submesh, "vertices", ()) or ()
            target_vertices = getattr(target_submesh, "vertices", ()) or ()
            if len(base_vertices) != len(target_vertices):
                return None
            base_faces = _face_json(getattr(base_submesh, "faces", ()) or (), len(base_vertices))
            target_faces = _face_json(getattr(target_submesh, "faces", ()) or (), len(target_vertices))
            prefix = sidecar_root / f"submesh_{submesh_index}"
            expected_counts[submesh_index] = len(base_vertices)
            submeshes.append(
                {
                    "index": submesh_index,
                    "base_vertices_binary": _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_base_vertices.bin"),
                        base_vertices,
                    ),
                    "target_vertices_binary": _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_target_vertices.bin"),
                        target_vertices,
                    ),
                    "base_faces_binary": _write_face_binary_payload(
                        prefix.with_name(prefix.name + "_base_faces.bin"),
                        base_faces,
                    ),
                    "target_faces_binary": _write_face_binary_payload(
                        prefix.with_name(prefix.name + "_target_faces.bin"),
                        target_faces,
                    ),
                    "deltas_output_path": str(prefix.with_name(prefix.name + "_deltas.bin")),
                }
            )
        report = _run_native_mesh_core_job(
            binary,
            "morph-target-delta-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "morph_target_delta",
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            return None
        raw_reports = report.get("submeshes")
        if not isinstance(raw_reports, list):
            return None
        outputs: list[tuple[Vec3, ...]] = [tuple() for _submesh in submeshes]
        seen: set[int] = set()
        for raw_item in raw_reports:
            if not isinstance(raw_item, Mapping):
                return None
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is None or submesh_index not in expected_counts:
                return None
            vertex_count = _index(raw_item.get("vertex_count"))
            if vertex_count is None or vertex_count != expected_counts[submesh_index]:
                return None
            deltas = _read_vec3_binary_report_payload(raw_item.get("deltas_binary"), expected_count=vertex_count)
            if deltas is None:
                return None
            outputs[submesh_index] = tuple(deltas)
            seen.add(submesh_index)
        if seen != set(expected_counts):
            return None
        return tuple(outputs)
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def build_native_static_donor_indices(
    original_submesh: SubMesh,
    new_submesh: SubMesh,
    *,
    timeout_seconds: float = 20.0,
) -> list[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    original_vertices = getattr(original_submesh, "vertices", ()) or ()
    new_vertices = getattr(new_submesh, "vertices", ()) or ()
    if not new_vertices:
        return []
    if not original_vertices:
        return [0] * len(new_vertices)
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_static_donor_"))
    try:
        prefix = sidecar_root / "submesh_0"
        report = _run_native_mesh_core_job(
            binary,
            "static-donor-indices-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "static_donor_indices",
                "submeshes": [
                    {
                        "index": 0,
                        "original_vertices_binary": _write_vec3_binary_payload(
                            prefix.with_name(prefix.name + "_original_vertices.bin"),
                            original_vertices,
                        ),
                        "new_vertices_binary": _write_vec3_binary_payload(
                            prefix.with_name(prefix.name + "_new_vertices.bin"),
                            new_vertices,
                        ),
                        "donor_indices_output_path": str(prefix.with_name(prefix.name + "_donor_indices.bin")),
                    }
                ],
            },
            timeout_seconds=timeout_seconds,
        )
        if report is None:
            return None
        raw_reports = report.get("submeshes")
        if not isinstance(raw_reports, list) or len(raw_reports) != 1:
            return None
        raw_item = raw_reports[0]
        if not isinstance(raw_item, Mapping):
            return None
        if _index(raw_item.get("index")) != 0:
            return None
        if _index(raw_item.get("new_vertex_count")) != len(new_vertices):
            return None
        donor_indices = _read_i32_binary_report_payload(
            raw_item.get("donor_indices_binary"),
            expected_count=len(new_vertices),
        )
        if donor_indices is None:
            return None
        if any(index < 0 or index >= len(original_vertices) for index in donor_indices):
            return None
        return donor_indices
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

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
_face_json_with_source_indices = _proxy("_face_json_with_source_indices")
_finite_float = _proxy("_finite_float")
_finite_vec2_list_or_none = _proxy("_finite_vec2_list_or_none")
_finite_vec3_list_or_none = _proxy("_finite_vec3_list_or_none")
_index = _proxy("_index")
_native_binary_descriptor = _proxy("_native_binary_descriptor")
_native_preview_delta_output_path = _proxy("_native_preview_delta_output_path")
_put_i32_range_or_binary_payload = _proxy("_put_i32_range_or_binary_payload")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_vec3 = _proxy("_vec3")
_vec3_json = _proxy("_vec3_json")
_write_edge_binary_payload = _proxy("_write_edge_binary_payload")
_write_face_binary_payload = _proxy("_write_face_binary_payload")
_write_vec2_binary_payload = _proxy("_write_vec2_binary_payload")
_write_vec3_binary_payload = _proxy("_write_vec3_binary_payload")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")


def _native_fbx_bone_payloads(skeleton: object) -> list[dict[str, object]]:
    raw_bones = tuple(getattr(skeleton, "bones", ()) or ())
    result: list[dict[str, object]] = []
    for fallback_index, bone in enumerate(raw_bones):
        index = _index(getattr(bone, "index", fallback_index))
        if index is None:
            index = fallback_index
        parent_index = _index(getattr(bone, "parent_index", -1))
        if parent_index is None:
            parent_index = -1
        result.append(
            {
                "index": index,
                "name": str(getattr(bone, "name", "") or f"Bone_{index}"),
                "parent_index": parent_index,
                "position": list(_vec3(getattr(bone, "position", (0.0, 0.0, 0.0)), fallback=0.0)),
            }
        )
    return result

def build_native_preview_model_in_original_frame(
    parsed_mesh: object,
    *,
    normalization_center: Sequence[object],
    normalization_scale: object,
    source_indices: Sequence[int] | None = None,
    timeout_seconds: float = 20.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_preview_model_"))
    try:
        submeshes = []
        raw_source_indices = source_indices or ()
        for submesh_position, submesh in enumerate(getattr(parsed_mesh, "submeshes", ()) or ()):
            raw_vertices = getattr(submesh, "vertices", ()) or ()
            raw_faces = getattr(submesh, "faces", ()) or ()
            if not raw_vertices or not raw_faces:
                continue
            try:
                source_submesh_index = int(raw_source_indices[submesh_position]) if submesh_position < len(raw_source_indices) else int(submesh_position)
            except (TypeError, ValueError, OverflowError):
                return None
            prefix = sidecar_root / f"preview_model_{submesh_position}"
            item: dict[str, object] = {
                "index": int(submesh_position),
                "source_submesh_index": source_submesh_index,
                "positions_output_path": _native_preview_delta_output_path("_preview_model_positions.bin"),
                "texture_coordinates_output_path": _native_preview_delta_output_path("_preview_model_uvs.bin"),
                "normals_output_path": _native_preview_delta_output_path("_preview_model_normals.bin"),
                "indices_output_path": _native_preview_delta_output_path("_preview_model_indices.bin"),
                "source_vertex_indices_output_path": _native_preview_delta_output_path("_preview_model_source_vertices.bin"),
                "source_face_indices_output_path": _native_preview_delta_output_path("_preview_model_source_faces.bin"),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                parsed_mesh,
                submesh_position,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                vertices = _finite_vec3_list_or_none(raw_vertices)
                if vertices is None:
                    return None
                faces, _source_face_indices = _face_json_with_source_indices(raw_faces, len(vertices))
                if len(faces) != len(raw_faces):
                    return None
                uvs = _finite_vec2_list_or_none(getattr(submesh, "uvs", ()) or ())
                normals = _finite_vec3_list_or_none(getattr(submesh, "normals", ()) or ())
                if uvs is None or normals is None:
                    return None
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs[: len(vertices)])
                item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), normals[: len(vertices)])
            submeshes.append(item)
        if not submeshes:
            return {"status": "ok", "backend": NATIVE_MESH_CORE_BACKEND_ID, "operation": "preview_model", "mesh_count": 0, "vertex_count": 0, "face_count": 0, "meshes": []}
        report = _run_native_mesh_core_job(
            binary,
            "preview-model-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "preview_model",
                "normalization_center": _vec3_json(normalization_center),
                "normalization_scale": _finite_float(normalization_scale, 1.0),
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        return _hydrate_native_preview_model_report(report)
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def _hydrate_native_preview_model_report(report: object) -> dict[str, object] | None:
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "preview_model":
        return None
    raw_meshes = report.get("meshes")
    if not isinstance(raw_meshes, list):
        return None
    hydrated_report = dict(report)
    hydrated_meshes: list[dict[str, object]] = []
    for raw_mesh in raw_meshes:
        if not isinstance(raw_mesh, Mapping):
            return None
        mesh = dict(raw_mesh)
        vertex_count = _index(mesh.get("vertex_count"))
        face_count = _index(mesh.get("face_count"))
        positions_binary = mesh.get("positions_binary")
        source_face_indices_binary = mesh.get("source_face_indices_binary")
        if vertex_count is None and isinstance(positions_binary, Mapping):
            vertex_count = _index(positions_binary.get("count"))
        if face_count is None and isinstance(source_face_indices_binary, Mapping):
            face_count = _index(source_face_indices_binary.get("count"))
        if vertex_count is None and isinstance(mesh.get("positions"), list):
            vertex_count = len(mesh["positions"])  # type: ignore[arg-type]
        if face_count is None and isinstance(mesh.get("indices"), list):
            face_count = len(mesh["indices"]) // 3  # type: ignore[arg-type]
        if vertex_count is None or vertex_count < 0 or face_count is None or face_count < 0:
            return None

        positions_binary = _native_binary_descriptor(mesh.get("positions_binary"), expected_count=vertex_count, components=3, kind="f64")
        if positions_binary is not None:
            mesh["positions_binary"] = positions_binary
            mesh.pop("positions", None)
        elif "positions_binary" in mesh:
            return None
        elif not isinstance(mesh.get("positions"), list):
            return None

        uvs_binary = mesh.get("texture_coordinates_binary")
        uv_count = _index(uvs_binary.get("count")) if isinstance(uvs_binary, Mapping) else vertex_count
        if uv_count is None or uv_count < 0 or uv_count > vertex_count:
            return None
        texture_coordinates_binary = _native_binary_descriptor(uvs_binary, expected_count=uv_count, components=2, kind="f64")
        if texture_coordinates_binary is not None:
            mesh["texture_coordinates_binary"] = texture_coordinates_binary
            mesh.pop("texture_coordinates", None)
        elif "texture_coordinates_binary" in mesh:
            return None

        normals_binary = mesh.get("normals_binary")
        normal_count = _index(normals_binary.get("count")) if isinstance(normals_binary, Mapping) else vertex_count
        if normal_count is None or normal_count < 0 or normal_count > vertex_count:
            return None
        normals_binary_descriptor = _native_binary_descriptor(normals_binary, expected_count=normal_count, components=3, kind="f64")
        if normals_binary_descriptor is not None:
            mesh["normals_binary"] = normals_binary_descriptor
            mesh.pop("normals", None)
        elif "normals_binary" in mesh:
            return None

        indices_binary = _native_binary_descriptor(mesh.get("indices_binary"), expected_count=face_count * 3, components=1, kind="i32")
        if indices_binary is not None:
            mesh["indices_binary"] = indices_binary
            mesh.pop("indices", None)
        elif "indices_binary" in mesh:
            return None
        elif not isinstance(mesh.get("indices"), list):
            return None

        source_vertex_indices_binary = _native_binary_descriptor(
            mesh.get("source_vertex_indices_binary"),
            expected_count=vertex_count,
            components=1,
            kind="i32",
        )
        if source_vertex_indices_binary is not None:
            mesh["source_vertex_indices_binary"] = source_vertex_indices_binary
            mesh.pop("source_vertex_indices", None)
        elif "source_vertex_indices_binary" in mesh:
            return None

        source_face_indices_binary = _native_binary_descriptor(
            mesh.get("source_face_indices_binary"),
            expected_count=face_count,
            components=1,
            kind="i32",
        )
        if source_face_indices_binary is not None:
            mesh["source_face_indices_binary"] = source_face_indices_binary
            mesh.pop("source_face_indices", None)
        elif "source_face_indices_binary" in mesh:
            return None

        hydrated_meshes.append(mesh)
    hydrated_report["meshes"] = hydrated_meshes
    return hydrated_report

def _selection_domain_submesh_items(
    mesh: ParsedMesh,
    *,
    vertices_by_submesh: Mapping[int, set[int]],
    edges_by_submesh: Mapping[int, set[tuple[int, int]]],
    faces_by_submesh: Mapping[int, set[int]],
    source_indices: Sequence[int],
    binary: Path,
    sidecar_root: Path,
    stop_event: threading.Event | None = None,
    timeout_seconds: float,
) -> list[dict[str, object]] | None:
    requested_sources = {
        parsed
        for raw in source_indices or ()
        for parsed in (_index(raw),)
        if parsed is not None and 0 <= parsed < len(mesh.submeshes)
    }
    target_indices = set(requested_sources)
    for mapping in (vertices_by_submesh, edges_by_submesh, faces_by_submesh):
        for raw_index in mapping:
            parsed = _index(raw_index)
            if parsed is not None:
                target_indices.add(parsed)
    submeshes: list[dict[str, object]] = []
    for raw_submesh_index in sorted(target_indices):
        submesh_index = _index(raw_submesh_index)
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        vertex_count = len(submesh.vertices or ())
        if vertex_count <= 0:
            continue
        selected_vertices = sorted(
            parsed
            for raw in vertices_by_submesh.get(submesh_index, set()) or ()
            for parsed in (_index(raw),)
            if parsed is not None and 0 <= parsed < vertex_count
        )
        selected_edges = sorted(
            (min(left, right), max(left, right))
            for raw_edge in edges_by_submesh.get(submesh_index, set()) or ()
            if isinstance(raw_edge, (tuple, list)) and len(raw_edge) >= 2
            for left in (_index(raw_edge[0]),)
            for right in (_index(raw_edge[1]),)
            if left is not None and right is not None and 0 <= left < vertex_count and 0 <= right < vertex_count and left != right
        )
        selected_faces = sorted(
            parsed
            for raw in faces_by_submesh.get(submesh_index, set()) or ()
            for parsed in (_index(raw),)
            if parsed is not None and parsed >= 0
        )
        selected_all_vertices = submesh_index in requested_sources
        if not (selected_vertices or selected_edges or selected_faces or selected_all_vertices):
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
        prefix = sidecar_root / f"selection_domain_{submesh_index}"
        item: dict[str, object] = {"index": submesh_index, "session_id": session_id}
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
    return submeshes

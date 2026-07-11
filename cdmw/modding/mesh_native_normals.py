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

_apply_cleanup_report = _proxy("_apply_cleanup_report")
_apply_generate_tangents_report = _proxy("_apply_generate_tangents_report")
_apply_recalculate_normals_report = _proxy("_apply_recalculate_normals_report")
_ensure_native_mesh_session_submesh = _proxy("_ensure_native_mesh_session_submesh")
_face_json = _proxy("_face_json")
_finite_float = _proxy("_finite_float")
_index = _proxy("_index")
_mark_native_mesh_session_submeshes_current = _proxy("_mark_native_mesh_session_submeshes_current")
_native_mesh_core_count_hint = _proxy("_native_mesh_core_count_hint")
_native_preview_delta_output_path = _proxy("_native_preview_delta_output_path")
_put_i32_range_or_binary_payload = _proxy("_put_i32_range_or_binary_payload")
_put_selected_edit_domain_payload = _proxy("_put_selected_edit_domain_payload")
_put_selected_vertices_payload = _proxy("_put_selected_vertices_payload")
_put_source_vertex_map_payload = _proxy("_put_source_vertex_map_payload")
_put_source_vertex_offsets_payload = _proxy("_put_source_vertex_offsets_payload")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_write_bone_binary_payloads = _proxy("_write_bone_binary_payloads")
_write_f64_binary_payload = _proxy("_write_f64_binary_payload")
_write_face_binary_payload = _proxy("_write_face_binary_payload")
_write_vec2_binary_payload = _proxy("_write_vec2_binary_payload")
_write_vec3_binary_payload = _proxy("_write_vec3_binary_payload")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")
recompute_submesh_normals = _proxy("recompute_submesh_normals")
record_native_mesh_core_fallback = _proxy("record_native_mesh_core_fallback")


def _allow_python_normal_recompute_fallback(mesh: ParsedMesh, submesh_indices: set[int]) -> bool:
    if not submesh_indices:
        return False
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip() or find_native_mesh_core_binary() is None:
        return True
    vertex_count = _native_mesh_core_count_hint(mesh, "total_vertices")
    face_count = _native_mesh_core_count_hint(mesh, "total_faces")
    record_native_mesh_core_fallback(
        "normals.recalculate.blocked",
        "Python normal recompute fallback blocked while native mesh core is available",
        vertex_count=vertex_count,
        face_count=face_count,
        submesh_indices=tuple(sorted(submesh_indices)),
    )
    return False

def _recompute_normals_native_or_fallback(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    timeout_seconds: float,
) -> None:
    if not submesh_indices:
        return
    native_affected = apply_native_mesh_recalculate_normals(mesh, submesh_indices, timeout_seconds=timeout_seconds)
    if native_affected is not None:
        return
    if not _allow_python_normal_recompute_fallback(mesh, submesh_indices):
        return
    record_native_mesh_core_fallback(
        "normals.recalculate",
        "native normal recompute unavailable inside native wrapper",
        vertex_count=_native_mesh_core_count_hint(mesh, "total_vertices"),
        face_count=_native_mesh_core_count_hint(mesh, "total_faces"),
        submesh_indices=tuple(sorted(submesh_indices)),
    )
    for submesh_index in submesh_indices:
        if 0 <= submesh_index < len(mesh.submeshes):
            recompute_submesh_normals(mesh.submeshes[submesh_index])

def apply_native_mesh_copy_normals(
    mesh: ParsedMesh,
    source_mesh: ParsedMesh,
    vertices_by_submesh: Mapping[int, Sequence[int] | set[int]] | None = None,
    *,
    selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None,
    selected_faces_by_submesh: Mapping[int, set[int]] | None = None,
    source_indices: Sequence[int] = (),
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    vertices_by_submesh = vertices_by_submesh or {}
    selected_edges_by_submesh = selected_edges_by_submesh or {}
    selected_faces_by_submesh = selected_faces_by_submesh or {}
    requested_sources = {
        parsed
        for raw_index in source_indices or ()
        for parsed in (_index(raw_index),)
        if parsed is not None and 0 <= parsed < len(mesh.submeshes)
    }
    target_indices = set(requested_sources)
    for mapping in (vertices_by_submesh, selected_edges_by_submesh, selected_faces_by_submesh):
        for raw_index in mapping:
            parsed = _index(raw_index)
            if parsed is not None:
                target_indices.add(parsed)
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_copy_normals_"))
    try:
        submeshes = []
        for submesh_index in sorted(target_indices):
            if not (0 <= submesh_index < len(mesh.submeshes) and 0 <= submesh_index < len(source_mesh.submeshes)):
                continue
            target = mesh.submeshes[submesh_index]
            source = source_mesh.submeshes[submesh_index]
            vertex_count = len(target.vertices)
            face_count = len(target.faces or ())
            if vertex_count <= 0 or len(source.normals) != len(source.vertices):
                continue
            prefix = sidecar_root / f"copy_normals_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "normals_output_path": _native_preview_delta_output_path("_copy_normals.bin"),
                "changed_vertices_output_path": _native_preview_delta_output_path("_copy_normals_changed_vertices.bin"),
                "preview_vertex_output_path": _native_preview_delta_output_path("_copy_normals_vertices.bin"),
                "source_normals_binary": _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_source_normals.bin"),
                    source.normals,
                    fallback=0.0,
                ),
            }
            if not _put_selected_edit_domain_payload(
                item,
                prefix,
                selected_vertices=vertices_by_submesh.get(submesh_index, ()),
                selected_edges=selected_edges_by_submesh.get(submesh_index, ()),
                selected_faces=selected_faces_by_submesh.get(submesh_index, ()),
                selected_all_vertices=submesh_index in requested_sources,
                vertex_count=vertex_count,
                face_count=face_count,
            ):
                continue
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), target.vertices)
                faces = _face_json(target.faces, vertex_count)
                if faces:
                    item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                if len(target.normals) == vertex_count:
                    item["normals_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_normals.bin"),
                        target.normals,
                        fallback=0.0,
                    )
                if len(target.uvs) == vertex_count:
                    item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), target.uvs)
            submeshes.append(item)
        if not submeshes:
            return {}
        report = _run_native_mesh_core_job(
            binary,
            "recalculate-normals-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "copy_normals",
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
    changed = _apply_recalculate_normals_report(mesh, report, return_changed_vertices=True)
    if changed:
        _mark_native_mesh_session_submeshes_current(mesh, changed.keys())
    return changed

def apply_native_mesh_recalculate_normals(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    return_changed_vertices: bool = False,
    timeout_seconds: float = 5.0,
) -> set[int] | dict[int, Sequence[int] | set[int]] | None:
    return _apply_native_mesh_normal_edit(
        mesh,
        submesh_indices,
        operation="recalculate_normals",
        return_changed_vertices=return_changed_vertices,
        timeout_seconds=timeout_seconds,
    )

def apply_native_mesh_weighted_normals(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    return _apply_native_mesh_normal_edit(
        mesh,
        submesh_indices,
        operation="weighted_normals",
        include_existing_normals=True,
        return_changed_vertices=True,
        timeout_seconds=timeout_seconds,
    )

def apply_native_mesh_flip_normals(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    selected_faces_by_submesh: Mapping[int, set[int]] | None = None,
    timeout_seconds: float = 5.0,
) -> set[int] | None:
    return _apply_native_mesh_normal_edit(
        mesh,
        submesh_indices,
        operation="flip_normals",
        selected_faces_by_submesh=selected_faces_by_submesh,
        include_existing_normals=True,
        timeout_seconds=timeout_seconds,
    )

def apply_native_mesh_sharpen_normals(
    mesh: ParsedMesh,
    selected_faces_by_submesh: Mapping[int, set[int]],
    *,
    timeout_seconds: float = 5.0,
) -> dict[int, Sequence[int] | set[int]] | None:
    submesh_indices = set(selected_faces_by_submesh)
    if not submesh_indices:
        return {}
    return _apply_native_mesh_normal_edit(
        mesh,
        submesh_indices,
        operation="sharpen_normals",
        selected_faces_by_submesh=selected_faces_by_submesh,
        include_existing_normals=True,
        return_changed_vertices=True,
        timeout_seconds=timeout_seconds,
    )

def _apply_native_mesh_normal_edit(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    operation: str,
    selected_faces_by_submesh: Mapping[int, set[int]] | None = None,
    include_existing_normals: bool = False,
    return_changed_vertices: bool = False,
    timeout_seconds: float = 5.0,
) -> set[int] | dict[int, Sequence[int] | set[int]] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_normals_"))
    try:
        submeshes = []
        for submesh_index in sorted(submesh_indices):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(submesh.vertices)
            face_count = len(submesh.faces or ())
            if vertex_count <= 0 or face_count <= 0:
                continue
            prefix = sidecar_root / f"normals_{submesh_index}"
            item: dict[str, object] = {"index": submesh_index}
            item["normals_output_path"] = _native_preview_delta_output_path("_normals.bin")
            item["changed_vertices_output_path"] = _native_preview_delta_output_path("_changed_vertices.bin")
            if return_changed_vertices and operation != "flip_normals":
                item["preview_vertex_output_path"] = _native_preview_delta_output_path("_normal_vertices.bin")
            if operation == "flip_normals":
                item["faces_output_path"] = _native_preview_delta_output_path("_faces.bin")
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                faces = _face_json(submesh.faces, vertex_count)
                if not faces:
                    continue
                face_count = len(faces)
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            if include_existing_normals and not session_id and len(submesh.normals) == len(submesh.vertices):
                item["normals_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_normals.bin"),
                    submesh.normals,
                    fallback=0.0,
                )
            if operation in {"flip_normals", "sharpen_normals"}:
                selected_faces = set((selected_faces_by_submesh or {}).get(submesh_index, set()))
                kept_faces = sorted(index for index in selected_faces if 0 <= index < face_count)
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
                else:
                    item["selected_all_faces"] = True
            submeshes.append(item)
        if not submeshes:
            return set()

        report = _run_native_mesh_core_job(
            binary,
            "recalculate-normals-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": operation,
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
    applied = _apply_recalculate_normals_report(mesh, report, return_changed_vertices=return_changed_vertices)
    if applied is not None:
        _mark_native_mesh_session_submeshes_current(mesh, submesh_indices)
    return applied

def apply_native_mesh_generate_tangents(
    mesh: ParsedMesh,
    submesh_indices: set[int],
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_tangents_"))
    try:
        cancellation_kwargs = {"stop_event": stop_event} if stop_event is not None else {}
        submeshes = []
        for submesh_index in sorted(submesh_indices):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertex_count = len(submesh.vertices)
            face_count = len(submesh.faces or ())
            if vertex_count <= 0 or len(submesh.uvs) != vertex_count or face_count <= 0:
                continue
            prefix = sidecar_root / f"tangents_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertices_output_path": _native_preview_delta_output_path("_generated_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_generated_faces.bin"),
                "uvs_output_path": _native_preview_delta_output_path("_generated_uvs.bin"),
                "normals_output_path": _native_preview_delta_output_path("_generated_normals.bin"),
                "tangents_output_path": _native_preview_delta_output_path("_generated_tangents.bin"),
                "tangent_signs_output_path": _native_preview_delta_output_path("_generated_tangent_signs.bin"),
                "changed_vertices_output_path": _native_preview_delta_output_path("_generated_changed_vertices.bin"),
            }
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                **cancellation_kwargs,
                timeout_seconds=timeout_seconds,
            )
            if session_id:
                item["session_id"] = session_id
            else:
                faces = _face_json(submesh.faces, vertex_count)
                if not faces:
                    continue
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                if len(submesh.normals) == vertex_count:
                    item["normals_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_normals.bin"),
                        submesh.normals,
                        fallback=0.0,
                    )
                if len(getattr(submesh, "tangents", ()) or ()) == vertex_count:
                    item["tangents_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_tangents.bin"),
                        getattr(submesh, "tangents", ()) or (),
                        fallback=0.0,
                    )
            if (
                not session_id
                and len(getattr(submesh, "bone_indices", ()) or ()) == vertex_count
                and len(getattr(submesh, "bone_weights", ()) or ()) == vertex_count
            ):
                bone_payload = _write_bone_binary_payloads(
                    prefix,
                    getattr(submesh, "bone_indices", ()) or (),
                    getattr(submesh, "bone_weights", ()) or (),
                )
                if bone_payload is not None:
                    item.update(bone_payload)
            if len(getattr(submesh, "bone_indices", ()) or ()) == vertex_count and len(getattr(submesh, "bone_weights", ()) or ()) == vertex_count:
                item["bone_counts_output_path"] = _native_preview_delta_output_path("_generated_bone_counts.bin")
                item["bone_indices_output_path"] = _native_preview_delta_output_path("_generated_bone_indices.bin")
                item["bone_weights_output_path"] = _native_preview_delta_output_path("_generated_bone_weights.bin")
            if not session_id and len(getattr(submesh, "source_vertex_map", ()) or ()) == vertex_count:
                _put_source_vertex_map_payload(item, prefix, getattr(submesh, "source_vertex_map", ()) or ())
            if len(getattr(submesh, "source_vertex_map", ()) or ()) == vertex_count:
                item["source_vertex_map_output_path"] = _native_preview_delta_output_path("_generated_source_vertex_map.bin")
            if not session_id and len(getattr(submesh, "source_vertex_offsets", ()) or ()) == vertex_count:
                _put_source_vertex_offsets_payload(item, prefix, getattr(submesh, "source_vertex_offsets", ()) or ())
            if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == vertex_count:
                item["source_vertex_offsets_output_path"] = _native_preview_delta_output_path("_generated_source_vertex_offsets.bin")
            submeshes.append(item)
        if not submeshes:
            return set()

        report = _run_native_mesh_core_job(
            binary,
            "generate-tangents-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "generate_tangents",
                "submeshes": submeshes,
            },
            **cancellation_kwargs,
            timeout_seconds=timeout_seconds,
        )
    except RunCancelled:
        raise
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)
    if report is None:
        return None
    return _apply_generate_tangents_report(mesh, report)

def apply_native_mesh_remove_doubles(
    mesh: ParsedMesh,
    vertices_by_submesh: Mapping[int, set[int] | None],
    *,
    threshold: float,
    timeout_seconds: float = 5.0,
) -> set[int] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_cleanup_"))
    try:
        submeshes = []
        for submesh_index, selected in sorted(vertices_by_submesh.items()):
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            prefix = sidecar_root / f"cleanup_{submesh_index}"
            vertex_count = len(submesh.vertices)
            selected_all_vertices = selected is None
            if selected_all_vertices:
                if vertex_count < 2:
                    continue
                kept: list[int] = []
            else:
                kept = sorted(index for index in selected if 0 <= index < vertex_count)
                if len(kept) < 2:
                    continue
            session_id = _ensure_native_mesh_session_submesh(
                binary,
                mesh,
                submesh_index,
                timeout_seconds=timeout_seconds,
            )
            item: dict[str, object] = {
                "index": submesh_index,
                "vertices_output_path": _native_preview_delta_output_path("_cleanup_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_cleanup_faces.bin"),
                "normals_output_path": _native_preview_delta_output_path("_cleanup_normals.bin"),
                "suppress_index_map_report": True,
            }
            if selected_all_vertices:
                item["selected_all_vertices"] = True
            else:
                _put_selected_vertices_payload(item, prefix, kept, max_count=vertex_count)
            if session_id:
                item["session_id"] = session_id
            else:
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), submesh.vertices)
                item["faces_binary"] = _write_face_binary_payload(
                    prefix.with_name(prefix.name + "_faces.bin"),
                    _face_json(submesh.faces, vertex_count),
                )
            if len(submesh.uvs) == vertex_count:
                if not session_id:
                    item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), submesh.uvs)
                item["uvs_output_path"] = _native_preview_delta_output_path("_cleanup_uvs.bin")
            if len(getattr(submesh, "tangents", ()) or ()) == vertex_count:
                if not session_id:
                    item["tangents_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_tangents.bin"),
                        getattr(submesh, "tangents", ()) or (),
                    )
                item["tangents_output_path"] = _native_preview_delta_output_path("_cleanup_tangents.bin")
            if len(getattr(submesh, "tangent_signs", ()) or ()) == vertex_count:
                if not session_id:
                    item["tangent_signs_binary"] = _write_f64_binary_payload(
                        prefix.with_name(prefix.name + "_tangent_signs.bin"),
                        getattr(submesh, "tangent_signs", ()) or (),
                        fallback=1.0,
                    )
                item["tangent_signs_output_path"] = _native_preview_delta_output_path("_cleanup_tangent_signs.bin")
            has_bones = (
                len(getattr(submesh, "bone_indices", ()) or ()) == vertex_count
                and len(getattr(submesh, "bone_weights", ()) or ()) == vertex_count
            )
            if has_bones and not session_id:
                bone_payload = _write_bone_binary_payloads(
                    prefix,
                    getattr(submesh, "bone_indices", ()) or (),
                    getattr(submesh, "bone_weights", ()) or (),
                )
                if bone_payload is None:
                    has_bones = False
                else:
                    item.update(bone_payload)
            if has_bones:
                item["bone_counts_output_path"] = _native_preview_delta_output_path("_cleanup_bone_counts.bin")
                item["bone_indices_output_path"] = _native_preview_delta_output_path("_cleanup_bone_indices.bin")
                item["bone_weights_output_path"] = _native_preview_delta_output_path("_cleanup_bone_weights.bin")
            if len(getattr(submesh, "source_vertex_map", ()) or ()) == vertex_count:
                if not session_id:
                    _put_source_vertex_map_payload(item, prefix, getattr(submesh, "source_vertex_map", ()) or ())
                item["source_vertex_map_output_path"] = _native_preview_delta_output_path("_cleanup_source_vertex_map.bin")
            if len(getattr(submesh, "source_vertex_offsets", ()) or ()) == vertex_count:
                if not session_id:
                    _put_source_vertex_offsets_payload(item, prefix, getattr(submesh, "source_vertex_offsets", ()) or ())
                item["source_vertex_offsets_output_path"] = _native_preview_delta_output_path("_cleanup_source_vertex_offsets.bin")
            submeshes.append(item)
        if not submeshes:
            return set()

        report = _run_native_mesh_core_job(
            binary,
            "cleanup-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "cleanup",
                "cleanup": {"threshold": _finite_float(threshold, 1e-5)},
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
    return _apply_cleanup_report(mesh, report)

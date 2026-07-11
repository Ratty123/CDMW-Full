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
_native_fbx_bone_payloads = _proxy("_native_fbx_bone_payloads")
_put_source_face_indices_payload = _proxy("_put_source_face_indices_payload")
_put_source_vertex_indices_payload = _proxy("_put_source_vertex_indices_payload")
_put_source_vertex_map_payload = _proxy("_put_source_vertex_map_payload")
_run_native_mesh_core_job = _proxy("_run_native_mesh_core_job")
_write_face_binary_payload = _proxy("_write_face_binary_payload")
_write_int_binary_payload = _proxy("_write_int_binary_payload")
_write_vec2_binary_payload = _proxy("_write_vec2_binary_payload")
_write_vec3_binary_payload = _proxy("_write_vec3_binary_payload")
atomic_publish_files = _proxy("atomic_publish_files")
find_native_mesh_core_binary = _proxy("find_native_mesh_core_binary")


def write_native_preview_identity_blob(
    output_path: Path | str,
    *,
    source_submesh_index: int,
    vertex_count: int,
    source_vertex_indices: Sequence[int] = (),
    source_face_indices: Sequence[int] = (),
    source_vertex_indices_binary: Mapping[str, object] | None = None,
    source_face_indices_binary: Mapping[str, object] | None = None,
    source_vertex_start: int | None = None,
    source_vertex_count: int = 0,
    source_face_start: int | None = None,
    source_face_count: int = 0,
    role: str = "",
    part_name: str = "",
    editable: bool = True,
    append: bool = True,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    path = Path(output_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    payload: dict[str, object] = {
        "version": 1,
        "backend": NATIVE_MESH_CORE_BACKEND_ID,
        "operation": "preview_identity",
        "output_path": str(path),
        "append": bool(append),
        "source_submesh_index": int(source_submesh_index),
        "vertex_count": max(0, int(vertex_count)),
        "role": str(role or ""),
        "part_name": str(part_name or ""),
        "editable": bool(editable),
    }
    sidecar_root: Path | None = None
    try:
        source_vertex_descriptor = _native_i32_descriptor(source_vertex_indices_binary)
        if source_vertex_descriptor is not None:
            payload["source_vertex_indices_binary"] = source_vertex_descriptor
        elif source_vertex_start is not None and int(source_vertex_start) >= 0 and int(source_vertex_count) > 0:
            payload["source_vertex_start"] = int(source_vertex_start)
            payload["source_vertex_count"] = int(source_vertex_count)
        else:
            sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_preview_identity_"))
            payload["source_vertex_indices_binary"] = _write_int_binary_payload(
                sidecar_root / "source_vertices.bin",
                source_vertex_indices if source_vertex_indices is not None else (),
            )
        source_face_descriptor = _native_i32_descriptor(source_face_indices_binary)
        if source_face_descriptor is not None:
            payload["source_face_indices_binary"] = source_face_descriptor
        elif source_face_start is not None and int(source_face_start) >= 0 and int(source_face_count) > 0:
            payload["source_face_start"] = int(source_face_start)
            payload["source_face_count"] = int(source_face_count)
        else:
            if sidecar_root is None:
                sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_preview_identity_"))
            payload["source_face_indices_binary"] = _write_int_binary_payload(
                sidecar_root / "source_faces.bin",
                source_face_indices if source_face_indices is not None else (),
            )
        return _run_native_mesh_core_job(
            binary,
            "preview-identity-json",
            payload,
            timeout_seconds=timeout_seconds,
        )
    finally:
        if sidecar_root is not None:
            shutil.rmtree(sidecar_root, ignore_errors=True)

def _native_i32_descriptor(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    path = str(value.get("path") or "").strip()
    if not path:
        return None
    try:
        count = int(value.get("count", 0) or 0)
        components = int(value.get("components", 1) or 1)
    except (TypeError, ValueError, OverflowError):
        return None
    if count < 0 or components != 1:
        return None
    if str(value.get("type") or "i32").strip().lower() != "i32":
        return None
    descriptor: dict[str, object] = {
        "path": path,
        "count": count,
        "components": 1,
        "type": "i32",
    }
    if bool(value.get("delete_after")):
        descriptor["delete_after"] = True
    return descriptor

def _native_i32_range_descriptor(value: object, *, max_count: int | None = None) -> tuple[int, int] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        raw_start = value.get("start", value.get("selected_vertex_start", value.get("source_vertex_start", -1)))
        raw_count = value.get("count", value.get("selected_vertex_count", value.get("source_vertex_count", 0)))
        start = int(raw_start if raw_start is not None else -1)
        count = int(raw_count if raw_count is not None else 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if start < 0 or count <= 0:
        return None
    if max_count is not None and start + count > max(0, int(max_count)):
        return None
    return start, count

def write_native_preview_geometry_blob(
    output_path: Path | str,
    *,
    meshes: Sequence[Mapping[str, object]],
    identity_output_path: Path | str | None = None,
    append: bool = False,
    timeout_seconds: float = 20.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    path = Path(output_path)
    identity_path = Path(identity_output_path) if identity_output_path is not None else None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if identity_path is not None:
            identity_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_preview_geometry_"))
    try:
        native_meshes: list[dict[str, object]] = []
        for mesh_index, mesh in enumerate(meshes if meshes is not None else ()):
            item = dict(mesh)
            prefix = sidecar_root / f"preview_geometry_{mesh_index}"
            if "positions" in item:
                item["positions_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_positions.bin"), item.pop("positions"))
            if "normals" in item:
                item["normals_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_normals.bin"), item.pop("normals"))
            if "texture_coordinates" in item:
                item["texture_coordinates_binary"] = _write_vec2_binary_payload(
                    prefix.with_name(prefix.name + "_uvs.bin"),
                    item.pop("texture_coordinates"),
                )
            if "indices" in item:
                indices = item.pop("indices")
                item["indices_binary"] = _write_int_binary_payload(prefix.with_name(prefix.name + "_indices.bin"), indices if indices is not None else ())
            if "faces" in item:
                faces = item.pop("faces")
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces if faces is not None else ())
            if "source_vertex_indices" in item:
                source_vertices = item.pop("source_vertex_indices")
                _put_source_vertex_indices_payload(item, prefix, source_vertices if source_vertices is not None else ())
            if "source_face_indices" in item:
                source_faces = item.pop("source_face_indices")
                _put_source_face_indices_payload(item, prefix, source_faces if source_faces is not None else ())
            native_meshes.append(item)
        return _run_native_mesh_core_job(
            binary,
            "preview-geometry-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "preview_geometry",
                "output_path": str(path),
                "identity_output_path": str(identity_path) if identity_path is not None else "",
                "append": bool(append),
                "meshes": native_meshes,
            },
            timeout_seconds=timeout_seconds,
        )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def _native_obj_submesh_payloads(
    mesh: ParsedMesh,
    binary: Path,
    sidecar_root: Path,
    *,
    timeout_seconds: float,
) -> tuple[tuple[object, ...], list[dict[str, object]]]:
    raw_submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    submeshes: list[dict[str, object]] = []
    for submesh_index, submesh in enumerate(raw_submeshes):
        prefix = sidecar_root / f"obj_export_{submesh_index}"
        item: dict[str, object] = {
            "index": submesh_index,
            "name": str(getattr(submesh, "name", "") or ""),
            "material": str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or f"part_{submesh_index}"),
            "texture": str(getattr(submesh, "texture", "") or ""),
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
            vertices = tuple(getattr(submesh, "vertices", ()) or ())
            faces = _face_json(getattr(submesh, "faces", ()) or (), len(vertices))
            item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices)
            item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
            uvs = tuple(getattr(submesh, "uvs", ()) or ())
            if uvs:
                item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
            normals = tuple(getattr(submesh, "normals", ()) or ())
            if normals:
                item["normals_binary"] = _write_vec3_binary_payload(
                    prefix.with_name(prefix.name + "_normals.bin"),
                    normals,
                    fallback=0.0,
                )
            source_vertex_map = getattr(submesh, "source_vertex_map", ()) or ()
            if len(source_vertex_map) == len(vertices):
                _put_source_vertex_map_payload(item, prefix, source_vertex_map)
        submeshes.append(item)
    return raw_submeshes, submeshes

def export_native_obj(
    mesh: ParsedMesh,
    obj_path: str | Path,
    *,
    base_name: str,
    mtl_filename: str,
    scale: float = 1.0,
    manifest_path: str | Path = "",
    extra_payload: Mapping[str, object] | None = None,
    timeout_seconds: float = 20.0,
) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return False
    binary = find_native_mesh_core_binary()
    if binary is None:
        return False
    path = Path(obj_path)
    staged_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    final_manifest_path = Path(manifest_path) if manifest_path else None
    staged_manifest_path = (
        final_manifest_path.with_name(f".{final_manifest_path.name}.{uuid4().hex}.tmp")
        if final_manifest_path is not None
        else None
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_obj_export_"))
    try:
        raw_submeshes, submeshes = _native_obj_submesh_payloads(
            mesh,
            binary,
            sidecar_root,
            timeout_seconds=timeout_seconds,
        )
        job: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "obj_export",
            "output_path": str(staged_path),
            "export_path": str(path),
            "base_name": str(base_name or path.stem),
            "source_path": str(getattr(mesh, "path", "") or ""),
            "source_format": str(getattr(mesh, "format", "") or ""),
            "mtl_filename": str(mtl_filename or ""),
            "scale": _finite_float(scale, 1.0),
            "total_vertices": sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in raw_submeshes),
            "total_faces": sum(len(getattr(submesh, "faces", ()) or ()) for submesh in raw_submeshes),
            "submeshes": submeshes,
        }
        if staged_manifest_path is not None:
            job["manifest_output_path"] = str(staged_manifest_path)
        if extra_payload:
            job["extra_payload"] = dict(extra_payload)
        report = _run_native_mesh_core_job(
            binary,
            "obj-export-json",
            job,
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(report, Mapping) or str(report.get("operation") or "") != "obj_export":
            return False
        if _index(report.get("submesh_count")) != len(submeshes):
            return False
        if staged_manifest_path is not None and not staged_manifest_path.is_file():
            return False
        if not staged_path.is_file():
            return False
        staged_files: dict[Path, Path] = {staged_path: path}
        if staged_manifest_path is not None and final_manifest_path is not None:
            staged_files[staged_manifest_path] = final_manifest_path
        atomic_publish_files(staged_files)
        return path.is_file()
    except (OSError, OverflowError, RuntimeError, ValueError):
        return False
    finally:
        staged_path.unlink(missing_ok=True)
        if staged_manifest_path is not None:
            staged_manifest_path.unlink(missing_ok=True)
        shutil.rmtree(sidecar_root, ignore_errors=True)

def write_native_obj_roundtrip_manifest(
    mesh: ParsedMesh,
    export_path: str | Path,
    *,
    companion_path: str | Path = "",
    extra_payload: Mapping[str, object] | None = None,
    timeout_seconds: float = 20.0,
) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return False
    binary = find_native_mesh_core_binary()
    if binary is None:
        return False
    manifest_path = Path(f"{export_path}.meta.json")
    staged_manifest_path = manifest_path.with_name(f".{manifest_path.name}.{uuid4().hex}.tmp")
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_obj_manifest_"))
    try:
        _raw_submeshes, submeshes = _native_obj_submesh_payloads(
            mesh,
            binary,
            sidecar_root,
            timeout_seconds=timeout_seconds,
        )
        job: dict[str, object] = {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "operation": "obj_manifest",
            "manifest_output_path": str(staged_manifest_path),
            "export_path": str(export_path),
            "companion_path": str(companion_path or ""),
            "source_path": str(getattr(mesh, "path", "") or ""),
            "source_format": str(getattr(mesh, "format", "") or ""),
            "submeshes": submeshes,
        }
        if extra_payload:
            job["extra_payload"] = dict(extra_payload)
        report = _run_native_mesh_core_job(
            binary,
            "obj-manifest-json",
            job,
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(report, Mapping) or str(report.get("operation") or "") != "obj_manifest":
            return False
        if _index(report.get("submesh_count")) != len(submeshes):
            return False
        if not staged_manifest_path.is_file():
            return False
        atomic_publish_files({staged_manifest_path: manifest_path})
        return manifest_path.is_file()
    except (OSError, OverflowError, RuntimeError, ValueError):
        return False
    finally:
        staged_manifest_path.unlink(missing_ok=True)
        shutil.rmtree(sidecar_root, ignore_errors=True)

def build_native_fbx_geometry_arrays(
    mesh: ParsedMesh,
    output_dir: str | Path,
    *,
    scale: float = 1.0,
    require_vertex_aligned_uvs: bool = False,
    timeout_seconds: float = 20.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    output_root = Path(output_dir)
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_fbx_geometry_"))
    try:
        submeshes: list[dict[str, object]] = []
        raw_submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
        for submesh_index, submesh in enumerate(raw_submeshes):
            output_prefix = output_root / f"fbx_geometry_{submesh_index}"
            input_prefix = sidecar_root / f"fbx_geometry_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "vertices_output_path": str(output_prefix.with_name(output_prefix.name + "_vertices.bin")),
                "indices_output_path": str(output_prefix.with_name(output_prefix.name + "_indices.bin")),
                "normals_output_path": str(output_prefix.with_name(output_prefix.name + "_normals.bin")),
                "uvs_output_path": str(output_prefix.with_name(output_prefix.name + "_uvs.bin")),
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
                vertices = tuple(getattr(submesh, "vertices", ()) or ())
                faces = _face_json(getattr(submesh, "faces", ()) or (), len(vertices))
                item["vertices_binary"] = _write_vec3_binary_payload(
                    input_prefix.with_name(input_prefix.name + "_vertices.bin"),
                    vertices,
                )
                item["faces_binary"] = _write_face_binary_payload(
                    input_prefix.with_name(input_prefix.name + "_faces.bin"),
                    faces,
                )
                normals = tuple(getattr(submesh, "normals", ()) or ())
                if normals:
                    item["normals_binary"] = _write_vec3_binary_payload(
                        input_prefix.with_name(input_prefix.name + "_normals.bin"),
                        normals,
                        fallback=0.0,
                    )
                uvs = tuple(getattr(submesh, "uvs", ()) or ())
                if uvs:
                    item["uvs_binary"] = _write_vec2_binary_payload(input_prefix.with_name(input_prefix.name + "_uvs.bin"), uvs)
            submeshes.append(item)
        report = _run_native_mesh_core_job(
            binary,
            "fbx-geometry-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "fbx_geometry",
                "scale": _finite_float(scale, 1.0),
                "require_vertex_aligned_uvs": bool(require_vertex_aligned_uvs),
                "submeshes": submeshes,
            },
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(report, Mapping) or str(report.get("operation") or "") != "fbx_geometry":
            return None
        raw_results = report.get("submeshes")
        if not isinstance(raw_results, list) or len(raw_results) != len(submeshes):
            return None
        for raw_item in raw_results:
            if not isinstance(raw_item, Mapping):
                return None
            for key in ("vertices_binary", "indices_binary", "normals_binary", "uvs_binary"):
                descriptor = raw_item.get(key)
                if not isinstance(descriptor, Mapping):
                    return None
                raw_path = str(descriptor.get("path") or "").strip()
                if not raw_path or not Path(raw_path).is_file():
                    return None
        return dict(report)
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None
    finally:
        shutil.rmtree(sidecar_root, ignore_errors=True)

def export_native_fbx(
    mesh: ParsedMesh,
    fbx_path: str | Path,
    *,
    base_name: str,
    scale: float = 1.0,
    skeleton: object = None,
    timeout_seconds: float = 20.0,
) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return False
    binary = find_native_mesh_core_binary()
    if binary is None:
        return False
    path = Path(fbx_path)
    staged_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    sidecar_root = Path(tempfile.mkdtemp(prefix="cdmw_mesh_core_fbx_export_"))
    try:
        submeshes: list[dict[str, object]] = []
        raw_submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
        for submesh_index, submesh in enumerate(raw_submeshes):
            prefix = sidecar_root / f"fbx_export_{submesh_index}"
            item: dict[str, object] = {
                "index": submesh_index,
                "name": str(getattr(submesh, "name", "") or f"part_{submesh_index}"),
                "material": str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or f"part_{submesh_index}"),
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
                vertices = tuple(getattr(submesh, "vertices", ()) or ())
                faces = _face_json(getattr(submesh, "faces", ()) or (), len(vertices))
                item["vertices_binary"] = _write_vec3_binary_payload(prefix.with_name(prefix.name + "_vertices.bin"), vertices)
                item["faces_binary"] = _write_face_binary_payload(prefix.with_name(prefix.name + "_faces.bin"), faces)
                normals = tuple(getattr(submesh, "normals", ()) or ())
                if normals:
                    item["normals_binary"] = _write_vec3_binary_payload(
                        prefix.with_name(prefix.name + "_normals.bin"),
                        normals,
                        fallback=0.0,
                    )
                uvs = tuple(getattr(submesh, "uvs", ()) or ())
                if uvs:
                    item["uvs_binary"] = _write_vec2_binary_payload(prefix.with_name(prefix.name + "_uvs.bin"), uvs)
            submeshes.append(item)
        report = _run_native_mesh_core_job(
            binary,
            "fbx-export-json",
            {
                "version": 1,
                "backend": NATIVE_MESH_CORE_BACKEND_ID,
                "operation": "fbx_export",
                "output_path": str(staged_path),
                "base_name": str(base_name or path.stem),
                "scale": _finite_float(scale, 1.0),
                "submeshes": submeshes,
                "bones": _native_fbx_bone_payloads(skeleton),
            },
            timeout_seconds=timeout_seconds,
        )
        if not isinstance(report, Mapping) or str(report.get("operation") or "") != "fbx_export":
            return False
        if _index(report.get("submesh_count")) != len(submeshes):
            return False
        if not staged_path.is_file():
            return False
        atomic_publish_files({staged_path: path})
        return path.is_file()
    except (OSError, OverflowError, RuntimeError, ValueError):
        return False
    finally:
        staged_path.unlink(missing_ok=True)
        shutil.rmtree(sidecar_root, ignore_errors=True)

"""Native preview payload helpers for Mesh Editor sessions."""

from __future__ import annotations

import math
import os
import shutil
import struct
import tempfile
import threading
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from cdmw.domain.mesh import MeshEditSelection
from cdmw.models import PreparedModelPreviewBatch, PreparedModelPreviewData
from cdmw.modding.mesh_parser import ParsedMesh

_VERTEX_STRUCT = struct.Struct("<23f")
_NATIVE_MATERIAL_OVERRIDE_KEYS = (
    "texture_brightness",
    "roughness",
    "metalness",
    "specular",
    "height_scale",
    "emissive_intensity",
    "emissive_color",
    "contrast",
    "saturation",
    "gamma",
    "tint_color",
)
_NATIVE_MATERIAL_SCALAR_OVERRIDE_KEYS = (
    "texture_brightness",
    "roughness",
    "metalness",
    "specular",
    "height_scale",
    "emissive_intensity",
    "contrast",
    "saturation",
    "gamma",
)
_NATIVE_MATERIAL_COLOR_OVERRIDE_KEYS = ("emissive_color", "tint_color")
_DEFAULT_NATIVE_MATERIAL_OVERRIDES: Mapping[str, object] = {
    "texture_brightness": 1.0,
    "roughness": 0.0,
    "metalness": 0.0,
    "specular": 0.0,
    "height_scale": 0.0,
    "emissive_intensity": 0.0,
    "emissive_color": [0.35, 0.68, 1.0],
    "contrast": 1.0,
    "saturation": 1.0,
    "gamma": 1.0,
    "tint_color": [1.0, 1.0, 1.0],
}

def mesh_to_native_preview(mesh: ParsedMesh) -> PreparedModelPreviewData:
    native_preview = _mesh_to_native_preview_native(mesh)
    if native_preview is not None:
        return native_preview
    if not _allow_python_preview_fallback(mesh, "preview_geometry", submesh_index=-1):
        raise RuntimeError("native Mesh Editor preview geometry unavailable; Python preview fallback is disabled")
    _record_native_preview_fallback(mesh, "preview_geometry", "native preview geometry unavailable")
    raise RuntimeError("native Mesh Editor preview geometry unavailable; Python preview fallback is disabled")


def mesh_pose_to_native_preview(
    mesh: ParsedMesh,
    *,
    skeleton: object,
    pose_rotations: Mapping[int, Sequence[object]] | Mapping[object, object],
) -> PreparedModelPreviewData:
    native_preview = _mesh_to_native_preview_native(
        mesh,
        pose_skeleton=skeleton,
        pose_rotations=pose_rotations,
    )
    if native_preview is not None:
        return native_preview
    if not _allow_python_preview_fallback(mesh, "preview.pose_geometry", submesh_index=-1):
        raise RuntimeError("native Mesh Editor pose preview geometry unavailable; Python preview fallback is disabled")
    _record_native_preview_fallback(mesh, "preview.pose_geometry", "native pose preview geometry unavailable")
    raise RuntimeError("native Mesh Editor pose preview geometry unavailable; Python preview fallback is disabled")


def _mesh_to_native_preview_native(
    mesh: ParsedMesh,
    *,
    pose_skeleton: object | None = None,
    pose_rotations: Mapping[int, Sequence[object]] | Mapping[object, object] | None = None,
) -> PreparedModelPreviewData | None:
    try:
        from cdmw.modding.mesh_native_core import (
            _ensure_native_mesh_session_submesh,
            find_native_mesh_core_binary,
            write_native_pose_preview_geometry_blob,
            write_native_preview_geometry_blob,
        )
    except Exception:
        return None
    binary = find_native_mesh_core_binary()
    if binary is None:
        return None
    mesh_payloads: list[dict[str, object]] = []
    submeshes = getattr(mesh, "submeshes", ()) or ()
    pose_mode = pose_skeleton is not None and pose_rotations is not None
    if not pose_mode:
        for submesh_index, submesh in enumerate(submeshes):
            vertex_count = _sequence_len(getattr(submesh, "vertices", ()))
            face_count = _sequence_len(getattr(submesh, "faces", ()))
            if vertex_count == 0 or face_count == 0:
                continue
            session_id = _ensure_native_mesh_session_submesh(binary, mesh, submesh_index, timeout_seconds=20.0)
            if not session_id:
                return None
            mesh_payloads.append(
                {
                    "index": submesh_index,
                    "source_submesh_index": submesh_index,
                    "session_id": session_id,
                    "color": (0.25, 0.55, 0.85),
                }
            )
        if not mesh_payloads:
            return None
    elif not submeshes:
        return None
    with tempfile.TemporaryDirectory(prefix="cdmw_mesh_editor_preview_") as tmp:
        geometry_path = Path(tmp) / "geometry.bin"
        identity_path = Path(tmp) / "identity.bin"
        if pose_mode:
            report = write_native_pose_preview_geometry_blob(
                geometry_path,
                mesh=mesh,
                skeleton=pose_skeleton,
                pose_rotations=pose_rotations,
                identity_output_path=identity_path,
            )
        else:
            report = write_native_preview_geometry_blob(
                geometry_path,
                meshes=mesh_payloads,
                identity_output_path=identity_path,
            )
        if not isinstance(report, Mapping) or not geometry_path.is_file():
            return None
        vertex_blob = geometry_path.read_bytes()
        identity_blob = identity_path.read_bytes() if identity_path.is_file() else b""
        report = _persist_preview_geometry_source_descriptors(report)
        if report is None:
            return None
    try:
        vertex_count = int(report.get("vertex_count", 0) or 0)
        geometry_size = int(report.get("geometry_size", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if vertex_count <= 0 or geometry_size != len(vertex_blob) or len(vertex_blob) != vertex_count * _VERTEX_STRUCT.size:
        return None
    raw_batches = report.get("batches")
    if not isinstance(raw_batches, list):
        return None
    batches: list[PreparedModelPreviewBatch] = []
    valid_face_count = 0
    for raw_batch in raw_batches:
        if not isinstance(raw_batch, Mapping):
            continue
        try:
            submesh_index = int(raw_batch.get("mesh_index", -1))
            first_vertex = int(raw_batch.get("first_vertex", 0) or 0)
            batch_vertex_count = int(raw_batch.get("vertex_count", 0) or 0)
            identity_offset = int(raw_batch.get("identity_offset", 0) or 0)
            identity_size = int(raw_batch.get("identity_size", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return None
        if submesh_index < 0 or submesh_index >= len(submeshes) or batch_vertex_count <= 0:
            continue
        raw_source_vertices_binary = raw_batch.get("source_vertex_indices_binary")
        raw_source_faces_binary = raw_batch.get("source_face_indices_binary")
        source_vertices_binary = _native_binary_descriptor(
            raw_source_vertices_binary,
            expected_count=_descriptor_count(raw_source_vertices_binary),
            components=1,
            kind="i32",
        )
        source_faces_binary = _native_binary_descriptor(
            raw_source_faces_binary,
            expected_count=_descriptor_count(raw_source_faces_binary),
            components=1,
            kind="i32",
        )
        source_vertex_range_start = _coerce_index(raw_batch.get("source_vertex_start"))
        source_vertex_range_count = _coerce_index(raw_batch.get("source_vertex_count"))
        if source_vertex_range_start is None or source_vertex_range_start < 0:
            source_vertex_range_start = -1
            source_vertex_range_count = 0
        source_face_range_start = _coerce_index(raw_batch.get("source_face_start"))
        source_face_range_count = _coerce_index(raw_batch.get("source_face_count"))
        if source_face_range_start is None or source_face_range_start < 0:
            source_face_range_start = -1
            source_face_range_count = 0
        source_vertices: tuple[int, ...] = ()
        source_faces: tuple[int, ...] = ()
        if source_vertices_binary is not None:
            source_vertices = ()
        elif source_vertex_range_count and source_vertex_range_count > 0:
            source_vertices = ()
        else:
            source_vertices = _int_tuple(raw_batch.get("source_vertex_indices"))
            if not source_vertices and _descriptor_count(raw_source_vertices_binary) > 0:
                return None
        if source_faces_binary is not None:
            source_faces = ()
        elif source_face_range_count and source_face_range_count > 0:
            source_faces = ()
        else:
            source_faces = _int_tuple(raw_batch.get("source_face_indices"))
            if not source_faces and _descriptor_count(raw_source_faces_binary) > 0:
                return None
        valid_face_count += len(source_faces) or _descriptor_count(source_faces_binary) or int(source_face_range_count or 0)
        start = first_vertex * _VERTEX_STRUCT.size
        end = start + (batch_vertex_count * _VERTEX_STRUCT.size)
        if start < 0 or end > len(vertex_blob):
            return None
        batch_identity_blob = b""
        if identity_size == batch_vertex_count * 12 and 0 <= identity_offset <= len(identity_blob):
            identity_end = identity_offset + identity_size
            if identity_end <= len(identity_blob):
                batch_identity_blob = identity_blob[identity_offset:identity_end]
        submesh = submeshes[submesh_index]
        batches.append(
            PreparedModelPreviewBatch(
                material_name=str(submesh.material or submesh.name or f"part_{submesh_index}"),
                texture_name=str(submesh.texture or ""),
                preview_texture_path=_local_texture_preview_path(submesh.texture),
                preview_texture_dds_path=_local_texture_dds_path(submesh.texture),
                vertex_blob=vertex_blob[start:end],
                index_count=batch_vertex_count,
                has_texture_coordinates=bool(raw_batch.get("has_texture_coordinates", False)),
                preview_native_material_overrides=dict(getattr(submesh, "preview_native_material_overrides", {}) or {}),
                source_submesh_index=submesh_index,
                source_vertex_indices=source_vertices,
                source_face_indices=source_faces,
                source_vertex_indices_binary=source_vertices_binary or {},
                source_face_indices_binary=source_faces_binary or {},
                source_vertex_range_start=int(source_vertex_range_start),
                source_vertex_range_count=int(source_vertex_range_count or 0),
                source_face_range_start=int(source_face_range_start),
                source_face_range_count=int(source_face_range_count or 0),
                editor_identity_blob=batch_identity_blob,
                editor_role="replacement_preview",
                editor_part_name=str(submesh.name or ""),
                editor_editable=True,
            )
        )
    if not batches:
        return None
    return PreparedModelPreviewData(
        source_path=str(mesh.path or "mesh_editor.pac"),
        format=str(mesh.format or "pac"),
        mesh_count=len(submeshes),
        vertex_count=_nonnegative_int(mesh.total_vertices),
        face_count=valid_face_count,
        batches=tuple(batches),
    )


def _int_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    result: list[int] = []
    for item in value:
        index = _coerce_index(item)
        if index is not None:
            result.append(index)
    return tuple(result)


def _descriptor_count(value: object) -> int:
    if not isinstance(value, Mapping):
        return 0
    parsed = _coerce_index(value.get("count"))
    return parsed if parsed is not None and parsed > 0 else 0


def _persist_preview_geometry_source_descriptors(report: object) -> dict[str, object] | None:
    if not isinstance(report, Mapping):
        return None
    raw_batches = report.get("batches")
    if not isinstance(raw_batches, list):
        return dict(report)
    persisted = dict(report)
    batches: list[object] = []
    for raw_batch in raw_batches:
        if not isinstance(raw_batch, Mapping):
            batches.append(raw_batch)
            continue
        batch = dict(raw_batch)
        for key in ("source_vertex_indices_binary", "source_face_indices_binary"):
            descriptor = _persist_native_i32_descriptor(batch.get(key))
            if descriptor is not None:
                batch[key] = descriptor
            elif _descriptor_count(batch.get(key)) > 0:
                return None
        batches.append(batch)
    persisted["batches"] = batches
    return persisted


def _persist_native_i32_descriptor(value: object) -> dict[str, object] | None:
    descriptor = _native_binary_descriptor(
        value,
        expected_count=_descriptor_count(value),
        components=1,
        kind="i32",
    )
    if descriptor is None or int(descriptor.get("count", 0) or 0) <= 0:
        return descriptor
    try:
        from cdmw.modding.mesh_native_core import _native_preview_delta_output_path

        target = Path(_native_preview_delta_output_path(".bin"))
        shutil.copyfile(str(descriptor["path"]), target)
    except (OSError, RuntimeError, ValueError):
        return None
    persisted = dict(descriptor)
    persisted["path"] = str(target)
    persisted["delete_after"] = True
    return persisted


def _local_texture_preview_path(value: object) -> str:
    path = _local_texture_path(value)
    if path is None:
        return ""
    return str(path)


def _local_texture_dds_path(value: object) -> str:
    path = _local_texture_path(value)
    if path is None or path.suffix.lower() != ".dds":
        return ""
    return str(path)


def _local_texture_path(value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        path = Path(text).expanduser()
    except OSError:
        return None
    try:
        if path.is_file():
            return path.resolve()
    except OSError:
        return None
    return None


def mesh_edit_triangle_groups(
    mesh: ParsedMesh,
    source_submesh_indices: Sequence[int] | None = None,
    *,
    allow_python_fallback: bool = False,
) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    selected = None if source_submesh_indices is None else set(_source_submesh_indices(source_submesh_indices))
    requested = [
        submesh_index
        for submesh_index, _submesh in enumerate(mesh.submeshes)
        if selected is None or submesh_index in selected
    ]
    missing_native: list[int] = []
    consumed_native: dict[int, dict[str, object]] = {}
    for submesh_index in requested:
        native_group = _consume_native_triangle_group(mesh.submeshes[submesh_index], submesh_index)
        if native_group is None:
            missing_native.append(submesh_index)
        else:
            consumed_native[submesh_index] = native_group
    generated_native = _mesh_edit_triangle_groups_native(mesh, missing_native) if missing_native else {}
    for submesh_index, submesh in enumerate(mesh.submeshes):
        if submesh_index not in requested:
            continue
        native_group = consumed_native.get(submesh_index) or generated_native.get(submesh_index)
        if native_group is not None:
            groups.append(_with_triangle_material_fields(native_group, submesh, submesh_index))
            continue
        if not allow_python_fallback:
            _record_native_preview_fallback(
                mesh,
                "preview_triangle_group.blocked",
                "native triangle update group unavailable; Python fallback is disabled",
                submesh_index=submesh_index,
            )
            continue
        if not _allow_python_preview_fallback(
            mesh,
            "preview_triangle_group",
            submesh_index=submesh_index,
            vertex_count=len(getattr(submesh, "vertices", ()) or ()),
            face_count=len(getattr(submesh, "faces", ()) or ()),
        ):
            continue
        valid_faces = _valid_face_items(submesh)
        has_valid_faces = bool(valid_faces)
        if has_valid_faces:
            _record_native_preview_fallback(
                mesh,
                "preview_triangle_group",
                "native triangle update group unavailable",
                submesh_index=submesh_index,
            )
        source_face_indices = [face_index for face_index, _face in valid_faces]
        group: dict[str, object] = {
            "source_submesh_index": submesh_index,
            "positions": [component for vertex in submesh.vertices for component in _vec3(vertex)] if has_valid_faces else [],
            "normals": [
                component
                for index in range(len(submesh.vertices))
                for component in _vec3(submesh.normals[index] if index < len(submesh.normals) else (0.0, 0.0, 1.0), (0.0, 0.0, 1.0))
            ]
            if has_valid_faces
            else [],
            "uvs": [
                component
                for index in range(len(submesh.vertices))
                for component in _vec2(submesh.uvs[index] if index < len(submesh.uvs) else (0.0, 0.0))
            ]
            if has_valid_faces
            else [],
            "indices": [index for _face_index, face in valid_faces for index in face],
        }
        if has_valid_faces:
            group["source_vertex_start"] = 0
            group["source_vertex_count"] = len(submesh.vertices)
            source_face_range = _contiguous_index_range(source_face_indices)
            if source_face_range is None:
                group["source_face_indices"] = source_face_indices
            else:
                group["source_face_start"], group["source_face_count"] = source_face_range
        else:
            group["source_vertex_indices"] = []
            group["source_face_indices"] = []
        groups.append(
            _with_triangle_material_fields(
                group,
                submesh,
                submesh_index,
            )
        )
    return groups


def _mesh_edit_triangle_groups_native(mesh: ParsedMesh, source_submesh_indices: Sequence[int]) -> dict[int, dict[str, object]]:
    if not source_submesh_indices:
        return {}
    try:
        from cdmw.modding.mesh_native_core import build_native_mesh_preview_triangle_groups
    except Exception:
        return {}
    native_groups = build_native_mesh_preview_triangle_groups(mesh, source_indices=source_submesh_indices)
    if native_groups is None:
        return {}
    result: dict[int, dict[str, object]] = {}
    for group in native_groups:
        if not isinstance(group, Mapping):
            continue
        source_index = _coerce_index(group.get("source_submesh_index"))
        if source_index is not None:
            result[source_index] = dict(group)
    return result


def _with_triangle_material_fields(group: Mapping[str, object], submesh: object, submesh_index: int) -> dict[str, object]:
    result = dict(group)
    result.update(
        {
            "source_submesh_index": submesh_index,
            "material_source_submesh_index": _nonnegative_int(
                getattr(submesh, "cdmw_mesh_edit_material_source_submesh_index", submesh_index),
                submesh_index,
            ),
            "material_name": str(submesh.material or submesh.name or f"part_{submesh_index}"),
            "texture_name": str(submesh.texture or ""),
        }
    )
    return result


def _consume_native_triangle_group(submesh: object, submesh_index: int) -> dict[str, object] | None:
    raw_group = getattr(submesh, "cdmw_native_preview_triangle_group", None)
    if hasattr(submesh, "cdmw_native_preview_triangle_group"):
        delattr(submesh, "cdmw_native_preview_triangle_group")
    if not isinstance(raw_group, Mapping):
        return None
    if str(raw_group.get("preview_backend") or "") != "cdmw_mesh_core":
        return None
    if _coerce_index(raw_group.get("source_submesh_index")) != submesh_index:
        return None
    group = dict(raw_group)
    raw_source_vertices_binary = group.get("source_vertex_indices_binary")
    source_vertex_start = _coerce_index(group.get("source_vertex_start"))
    source_vertex_range_count = _coerce_index(group.get("source_vertex_count"))
    has_source_vertex_range = (
        source_vertex_start is not None
        and source_vertex_start >= 0
        and source_vertex_range_count is not None
        and source_vertex_range_count > 0
    )
    source_vertex_count = 0
    if isinstance(raw_source_vertices_binary, Mapping):
        source_vertex_count = _coerce_index(raw_source_vertices_binary.get("count")) or 0
    elif has_source_vertex_range:
        source_vertex_count = int(source_vertex_range_count or 0)
    else:
        source_vertices = _source_vertex_indices(group.get("source_vertex_indices"), 1 << 30)
        source_vertex_count = len(source_vertices)
        if source_vertices:
            group["source_vertex_indices"] = source_vertices
    source_vertices_binary = _native_binary_descriptor(raw_source_vertices_binary, expected_count=source_vertex_count, components=1, kind="i32")
    if source_vertices_binary is not None:
        group["source_vertex_indices_binary"] = source_vertices_binary
        group.pop("source_vertex_indices", None)
        group.pop("source_vertex_start", None)
        group.pop("source_vertex_count", None)
    elif has_source_vertex_range:
        group["source_vertex_start"] = int(source_vertex_start or 0)
        group["source_vertex_count"] = int(source_vertex_range_count or 0)
        group.pop("source_vertex_indices", None)
        group.pop("source_vertex_indices_binary", None)

    raw_source_faces_binary = group.get("source_face_indices_binary")
    source_face_start = _coerce_index(group.get("source_face_start"))
    source_face_range_count = _coerce_index(group.get("source_face_count"))
    has_source_face_range = (
        source_face_start is not None
        and source_face_start >= 0
        and source_face_range_count is not None
        and source_face_range_count > 0
    )
    source_face_count = 0
    if isinstance(raw_source_faces_binary, Mapping):
        source_face_count = _coerce_index(raw_source_faces_binary.get("count")) or 0
    elif has_source_face_range:
        source_face_count = int(source_face_range_count or 0)
    else:
        source_faces = _source_vertex_indices(group.get("source_face_indices"), 1 << 30)
        source_face_count = len(source_faces)
        if source_faces:
            group["source_face_indices"] = source_faces
    source_faces_binary = _native_binary_descriptor(raw_source_faces_binary, expected_count=source_face_count, components=1, kind="i32")
    if source_faces_binary is not None:
        group["source_face_indices_binary"] = source_faces_binary
        group.pop("source_face_indices", None)
        group.pop("source_face_start", None)
        group.pop("source_face_count", None)
    elif has_source_face_range:
        group["source_face_start"] = int(source_face_start or 0)
        group["source_face_count"] = int(source_face_range_count or 0)
        group.pop("source_face_indices", None)
        group.pop("source_face_indices_binary", None)

    positions = group.get("positions")
    positions_binary = _native_binary_descriptor(group.get("positions_binary"), expected_count=source_vertex_count, components=3, kind="f64")
    if positions_binary is not None:
        group["positions_binary"] = positions_binary
        group.pop("positions", None)
    elif not isinstance(positions, list) or len(positions) != source_vertex_count * 3:
        return None

    normals = group.get("normals")
    normals_binary = _native_binary_descriptor(group.get("normals_binary"), expected_count=source_vertex_count, components=3, kind="f64")
    if normals_binary is not None:
        group["normals_binary"] = normals_binary
        group.pop("normals", None)
    elif not isinstance(normals, list) or (normals and len(normals) != source_vertex_count * 3):
        return None

    uvs = group.get("uvs")
    uvs_binary = _native_binary_descriptor(group.get("uvs_binary"), expected_count=source_vertex_count, components=2, kind="f64")
    if uvs_binary is not None:
        group["uvs_binary"] = uvs_binary
        group.pop("uvs", None)
    elif not isinstance(uvs, list) or (uvs and len(uvs) != source_vertex_count * 2):
        return None

    raw_indices_binary = group.get("indices_binary")
    indices: list[int] = []
    index_count = 0
    if isinstance(raw_indices_binary, Mapping):
        index_count = _coerce_index(raw_indices_binary.get("count")) or 0
    else:
        try:
            raw_indices = iter(group.get("indices") or ())
        except (TypeError, ValueError, OverflowError):
            return None
        for raw_index in raw_indices:
            index = _coerce_index(raw_index)
            if index is not None and index >= 0:
                indices.append(index)
        index_count = len(indices)
        if indices:
            group["indices"] = indices
    indices_binary = _native_binary_descriptor(raw_indices_binary, expected_count=index_count, components=1, kind="i32")
    if indices_binary is not None:
        group["indices_binary"] = indices_binary
        group.pop("indices", None)
    elif index_count > 0 and not indices:
        return None
    if source_vertex_count == 0:
        for key in ("source_vertex_indices", "source_face_indices", "positions", "normals", "uvs", "indices"):
            group.setdefault(key, [])
    return group


def mesh_edit_material_override_groups(
    mesh: ParsedMesh,
    source_submesh_indices: Sequence[int],
    *,
    include_defaults: bool = False,
) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    for submesh_index in _source_submesh_indices(source_submesh_indices):
        if submesh_index >= len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        overrides = dict(getattr(submesh, "preview_native_material_overrides", {}) or {})
        group: dict[str, object] = {
            "source_submesh_indices": [submesh_index],
            "editor_role": "replacement_preview",
            "material_name": str(submesh.material or submesh.name or f"part_{submesh_index}"),
            "texture_name": str(submesh.texture or ""),
        }
        if include_defaults:
            group.update(_sanitized_material_override_values(_DEFAULT_NATIVE_MATERIAL_OVERRIDES, include_defaults=False))
        group.update(_sanitized_material_override_values(overrides, include_defaults=include_defaults))
        if include_defaults or len(group) > 4:
            groups.append(group)
    return groups


def mesh_edit_selection_groups(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    *,
    stop_event: threading.Event | None = None,
    allow_python_fallback: bool = False,
) -> list[dict[str, object]]:
    native_groups = _mesh_edit_selection_groups_native(mesh, selection, stop_event=stop_event)
    if native_groups is not None:
        return native_groups
    if not allow_python_fallback:
        _record_native_preview_fallback(mesh, "selection_overlay.blocked", "native selection overlay groups unavailable; Python fallback is disabled")
        return []
    if not _allow_python_preview_fallback(mesh, "selection_overlay", submesh_index=-1):
        return []
    vertex_work, face_work = _selection_preview_fallback_work(mesh, selection)
    if not _allow_python_preview_fallback(
        mesh,
        "selection_overlay",
        submesh_index=-1,
        vertex_count=vertex_work,
        face_count=face_work,
    ):
        return []
    _record_native_preview_fallback(mesh, "selection_overlay", "native selection overlay groups unavailable")
    return _mesh_edit_selection_groups_python_reference(mesh, selection)


def _mesh_edit_selection_groups_native(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    *,
    stop_event: threading.Event | None = None,
) -> list[dict[str, object]] | None:
    try:
        from cdmw.modding.mesh_native_core import build_native_mesh_selection_groups
    except Exception:
        return None
    return build_native_mesh_selection_groups(
        mesh,
        vertices_by_submesh=selection.vertex_map(),
        edges_by_submesh=selection.edge_map(),
        faces_by_submesh=selection.face_map(),
        source_indices=selection.source_indices,
        stop_event=stop_event,
    )


def _mesh_edit_selection_groups_python_reference(mesh: ParsedMesh, selection: MeshEditSelection) -> list[dict[str, object]]:
    vertices_by_submesh = selection.vertex_map()
    edges_by_submesh = selection.edge_map()
    faces_by_submesh = selection.face_map()
    selected_vertices: dict[int, set[int]] = {submesh: set(indices) for submesh, indices in vertices_by_submesh.items()}
    selected_edges_by_submesh: dict[int, set[tuple[int, int]]] = {}
    whole_vertex_submeshes: set[int] = set()
    for submesh_index, edges in edges_by_submesh.items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        edges = _valid_selected_edges_for_submesh(mesh.submeshes[submesh_index], edges)
        if not edges:
            continue
        selected_edges_by_submesh[submesh_index] = edges
        vertices = selected_vertices.setdefault(submesh_index, set())
        for a, b in edges:
            vertices.update((a, b))
    for submesh_index, faces in faces_by_submesh.items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        valid_faces = dict(_valid_face_items(submesh))
        vertices = selected_vertices.setdefault(submesh_index, set())
        for face_index in faces:
            face = valid_faces.get(face_index)
            if face is not None:
                vertices.update(face)
    for submesh_index in selection.source_indices:
        if 0 <= submesh_index < len(mesh.submeshes):
            whole_vertex_submeshes.add(submesh_index)

    groups: list[dict[str, object]] = []
    for submesh_index in sorted(set(selected_vertices) | whole_vertex_submeshes):
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        if submesh_index in whole_vertex_submeshes:
            vertices: Sequence[int] = range(len(submesh.vertices))
        else:
            raw_vertices = selected_vertices.get(submesh_index, set())
            vertices = sorted(index for index in raw_vertices if 0 <= index < len(submesh.vertices))
        if not vertices:
            continue
        group: dict[str, object] = {
            "source_submesh_index": submesh_index,
        }
        _put_index_range_or_values(group, vertices, "source_vertex_indices", "source_vertex_start", "source_vertex_count")
        selected_edges = sorted(selected_edges_by_submesh.get(submesh_index, ()))
        if selected_edges:
            group["source_edges"] = [[a, b] for a, b in selected_edges]
        valid_face_indices = {face_index for face_index, _face in _valid_face_items(submesh)}
        selected_faces = sorted(index for index in faces_by_submesh.get(submesh_index, ()) if index in valid_face_indices)
        if selected_faces:
            _put_index_range_or_values(group, selected_faces, "source_face_indices", "source_face_start", "source_face_count")
        groups.append(group)
    return groups


def mesh_edit_vertex_update_groups(
    mesh: ParsedMesh,
    changed_vertices_by_submesh: Mapping[int, object],
    *,
    allow_python_fallback: bool = False,
) -> list[dict[str, object]]:
    entries: list[tuple[int, Sequence[int], dict[str, object] | None, int]] = []
    missing_native: dict[int, object] = {}
    for raw_submesh_index, raw_indices in changed_vertices_by_submesh.items():
        try:
            submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if submesh_index < 0 or submesh_index >= len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        vertex_count = len(submesh.vertices)
        if vertex_count <= 0:
            continue
        changed_all_vertices = _is_full_vertex_range(raw_indices, vertex_count)
        native_count = _changed_vertex_input_count(raw_indices, vertex_count)
        if native_count is not None and native_count > 0:
            native_group = _consume_native_vertex_update_group(
                submesh,
                submesh_index,
                None,
                expected_count=native_count,
            )
            if native_group is not None:
                entries.append((submesh_index, (), native_group, native_count))
                continue
        if isinstance(raw_indices, Mapping):
            if native_count is None or native_count <= 0:
                continue
            missing_native[submesh_index] = raw_indices
            entries.append((submesh_index, (), None, native_count))
            continue
        if changed_all_vertices:
            indices: Sequence[int] = raw_indices
            native_group = _consume_native_vertex_update_group(submesh, submesh_index, indices)
            if native_group is not None:
                entries.append((submesh_index, indices, native_group, native_count or len(indices)))
                continue
        else:
            normalized_indices = _source_vertex_indices(raw_indices, vertex_count)
            if not normalized_indices:
                continue
            indices = normalized_indices
            native_group = _consume_native_vertex_update_group(submesh, submesh_index, indices)
            if native_group is not None:
                entries.append((submesh_index, indices, native_group, native_count or len(indices)))
                continue
        missing_native[submesh_index] = indices
        entries.append((submesh_index, indices, native_group, native_count or len(indices)))
    generated_native = _mesh_edit_vertex_update_groups_native(mesh, missing_native) if missing_native else {}
    groups: list[dict[str, object]] = []
    for submesh_index, indices, native_group, native_count in entries:
        if native_group is not None:
            groups.append(native_group)
            continue
        native_group = generated_native.get(submesh_index)
        if native_group is not None:
            groups.append(native_group)
            continue
        if not allow_python_fallback:
            _record_native_preview_fallback(
                mesh,
                "preview_vertex_update.blocked",
                "native vertex update group unavailable; Python fallback is disabled",
                submesh_index=submesh_index,
                changed_vertex_count=native_count,
            )
            continue
        if not indices and native_count > 0:
            _record_native_preview_fallback(
                mesh,
                "preview_vertex_update.blocked",
                "descriptor vertex update requires native mesh core preview generation",
                submesh_index=submesh_index,
                changed_vertex_count=native_count,
            )
            continue
        submesh = mesh.submeshes[submesh_index]
        if not _allow_python_preview_fallback(
            mesh,
            "preview_vertex_update",
            submesh_index=submesh_index,
            vertex_count=len(indices),
        ):
            continue
        _record_native_preview_fallback(
            mesh,
            "preview_vertex_update",
            "native vertex update group unavailable",
            submesh_index=submesh_index,
            changed_vertex_count=len(indices),
        )
        group = {
            "source_submesh_index": submesh_index,
            "positions": [component for index in indices for component in _vec3(submesh.vertices[index])],
            "normals": [
                component
                for index in indices
                for component in _vec3(submesh.normals[index] if index < len(submesh.normals) else (0.0, 0.0, 1.0), (0.0, 0.0, 1.0))
            ],
            "uvs": [
                component
                for index in indices
                for component in _vec2(submesh.uvs[index] if index < len(submesh.uvs) else (0.0, 0.0))
            ],
        }
        _put_index_range_or_values(group, indices, "source_vertex_indices", "source_vertex_start", "source_vertex_count")
        groups.append(group)
    return groups


def _changed_vertex_input_count(value: object, vertex_count: int) -> int | None:
    if _is_full_vertex_range(value, vertex_count):
        return vertex_count
    if isinstance(value, Mapping):
        for descriptor_key in ("changed_vertices_binary", "source_vertex_indices_binary"):
            count = _descriptor_count(value.get(descriptor_key))
            if 0 < count <= vertex_count:
                return count
        if "path" in value:
            count = _descriptor_count(value)
            if 0 < count <= vertex_count:
                return count
        for start_key, count_key in (
            ("changed_vertex_start", "changed_vertex_count"),
            ("source_vertex_start", "source_vertex_count"),
        ):
            start = _coerce_index(value.get(start_key))
            count = _coerce_index(value.get(count_key))
            if start is None and count is None:
                continue
            if start is None or count is None or start < 0 or count <= 0 or start + count > vertex_count:
                return None
            return count
        return None
    return _sequence_len(value)


def _sequence_len(value: object) -> int | None:
    try:
        length = len(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return length if length >= 0 else None


def _mesh_edit_vertex_update_groups_native(mesh: ParsedMesh, changed_vertices_by_submesh: Mapping[int, object]) -> dict[int, dict[str, object]]:
    if not changed_vertices_by_submesh:
        return {}
    try:
        from cdmw.modding.mesh_native_core import (
            build_native_mesh_preview_vertex_update_groups,
            invalidate_native_mesh_session_submeshes,
        )
    except Exception:
        return {}
    requested: dict[int, object] = {}
    for raw_submesh_index, raw_indices in changed_vertices_by_submesh.items():
        submesh_index = _coerce_index(raw_submesh_index)
        if submesh_index is not None and 0 <= submesh_index < len(mesh.submeshes):
            requested[submesh_index] = raw_indices
    native_groups = build_native_mesh_preview_vertex_update_groups(mesh, requested)
    result: dict[int, dict[str, object]] = {}

    def consume(groups: object) -> None:
        if groups is None:
            return
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            submesh_index = _coerce_index(group.get("source_submesh_index"))
            if submesh_index is not None:
                result[submesh_index] = dict(group)

    consume(native_groups)
    missing = {submesh_index: requested[submesh_index] for submesh_index in requested if submesh_index not in result}
    if missing:
        invalidate_native_mesh_session_submeshes(mesh, missing.keys())
        consume(build_native_mesh_preview_vertex_update_groups(mesh, missing))
    return result


def _native_binary_descriptor(value: object, *, expected_count: int, components: int, kind: str) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    raw_path = str(value.get("path") or "").strip()
    if not raw_path:
        return None
    try:
        count = int(value.get("count", expected_count))
        raw_components = int(value.get("components", components))
    except (TypeError, ValueError, OverflowError):
        return None
    if count != expected_count or raw_components != components:
        return None
    raw_kind = str(value.get("type") or kind).strip().lower()
    if raw_kind != kind:
        return None
    descriptor: dict[str, object] = {
        "path": raw_path,
        "count": expected_count,
        "components": components,
        "type": kind,
    }
    if bool(value.get("delete_after")):
        descriptor["delete_after"] = True
    return descriptor


def _consume_native_vertex_update_group(
    submesh: object,
    submesh_index: int,
    expected_indices: Sequence[int] | None,
    *,
    expected_count: int | None = None,
) -> dict[str, object] | None:
    raw_group = getattr(submesh, "cdmw_native_preview_vertex_update_group", None)
    if hasattr(submesh, "cdmw_native_preview_vertex_update_group"):
        delattr(submesh, "cdmw_native_preview_vertex_update_group")
    if not isinstance(raw_group, Mapping):
        return None
    if str(raw_group.get("preview_backend") or "") != "cdmw_mesh_core":
        return None
    if _coerce_index(raw_group.get("source_submesh_index")) != submesh_index:
        return None
    group = dict(raw_group)
    expected_count = _sequence_len(expected_indices) if expected_count is None else expected_count
    if expected_count is None or expected_count < 0:
        return None
    source_vertex_start = _coerce_index(group.get("source_vertex_start"))
    source_vertex_range_count = _coerce_index(group.get("source_vertex_count"))
    has_source_vertex_range = (
        source_vertex_start is not None
        and source_vertex_start >= 0
        and source_vertex_range_count == expected_count
        and expected_count > 0
    )
    source_indices_binary = _native_binary_descriptor(
        group.get("source_vertex_indices_binary"),
        expected_count=expected_count,
        components=1,
        kind="i32",
    )
    source_indices: Sequence[int] = ()
    if source_indices_binary is None and not has_source_vertex_range:
        source_indices = _source_vertex_indices(group.get("source_vertex_indices"), len(getattr(submesh, "vertices", ()) or ()))
        if expected_indices is not None and source_indices and not _same_index_sequence(source_indices, expected_indices):
            return None
        if expected_indices is None and source_indices and len(source_indices) != expected_count:
            return None
    if not source_indices and source_indices_binary is None and not has_source_vertex_range and expected_count > 0:
        return None
    positions = group.get("positions")
    positions_binary = _native_binary_descriptor(
        group.get("positions_binary"),
        expected_count=expected_count,
        components=3,
        kind="f64",
    )
    normals = group.get("normals")
    normals_binary = _native_binary_descriptor(
        group.get("normals_binary"),
        expected_count=expected_count,
        components=3,
        kind="f64",
    )
    uvs = group.get("uvs")
    uvs_binary = _native_binary_descriptor(
        group.get("uvs_binary"),
        expected_count=expected_count,
        components=2,
        kind="f64",
    )
    if positions_binary is None and (not isinstance(positions, list) or len(positions) != expected_count * 3):
        return None
    if normals_binary is None and (not isinstance(normals, list) or (normals and len(normals) != expected_count * 3)):
        return None
    if uvs_binary is None and (not isinstance(uvs, list) or (uvs and len(uvs) != expected_count * 2)):
        return None
    if source_indices_binary is not None:
        group["source_vertex_indices_binary"] = source_indices_binary
        group.pop("source_vertex_indices", None)
        group.pop("source_vertex_start", None)
        group.pop("source_vertex_count", None)
    elif has_source_vertex_range:
        group["source_vertex_start"] = int(source_vertex_start or 0)
        group["source_vertex_count"] = int(source_vertex_range_count or 0)
        group.pop("source_vertex_indices", None)
        group.pop("source_vertex_indices_binary", None)
    else:
        group["source_vertex_indices"] = source_indices
        group.pop("source_vertex_indices_binary", None)
        group.pop("source_vertex_start", None)
        group.pop("source_vertex_count", None)
    if positions_binary is not None:
        group["positions_binary"] = positions_binary
        group.pop("positions", None)
    if normals_binary is not None:
        group["normals_binary"] = normals_binary
        group.pop("normals", None)
    if uvs_binary is not None:
        group["uvs_binary"] = uvs_binary
        group.pop("uvs", None)
    return group


def _record_native_preview_fallback(mesh: ParsedMesh, operation: str, reason: str, **details: object) -> None:
    try:
        from cdmw.modding.mesh_native_core import record_native_mesh_core_fallback
    except Exception:
        return
    record_native_mesh_core_fallback(
        operation,
        reason,
        vertex_count=_nonnegative_int(getattr(mesh, "total_vertices", 0)),
        face_count=_nonnegative_int(getattr(mesh, "total_faces", 0)),
        **details,
    )


def _native_mesh_core_available_for_preview() -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE"):
        return False
    try:
        from cdmw.modding.mesh_native_core import native_mesh_core_available
    except Exception:
        return False
    try:
        return bool(native_mesh_core_available())
    except Exception:
        return False


def _allow_python_preview_fallback(
    mesh: ParsedMesh,
    operation: str,
    *,
    submesh_index: int,
    vertex_count: int = 0,
    face_count: int = 0,
) -> bool:
    if not _native_mesh_core_available_for_preview():
        return True
    _record_native_preview_fallback(
        mesh,
        f"{operation}.blocked",
        "Python preview fallback blocked while native mesh core is available",
        submesh_index=submesh_index,
        source_vertex_count=_nonnegative_int(vertex_count),
        source_face_count=_nonnegative_int(face_count),
    )
    return False


def _selection_preview_fallback_work(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[int, int]:
    submeshes = getattr(mesh, "submeshes", ()) or ()
    vertex_work = 0
    face_work = 0
    for raw_source_index in selection.source_indices:
        source_index = _coerce_index(raw_source_index)
        if source_index is not None and 0 <= source_index < len(submeshes):
            submesh = submeshes[source_index]
            vertex_work += len(getattr(submesh, "vertices", ()) or ())
            face_work += len(getattr(submesh, "faces", ()) or ())
    for raw_submesh_index, vertices in selection.vertex_map().items():
        submesh_index = _coerce_index(raw_submesh_index)
        if submesh_index is not None and 0 <= submesh_index < len(submeshes):
            vertex_work += _sequence_len(vertices) or 0
    for raw_submesh_index, edges in selection.edge_map().items():
        submesh_index = _coerce_index(raw_submesh_index)
        if submesh_index is not None and 0 <= submesh_index < len(submeshes):
            submesh = submeshes[submesh_index]
            vertex_work += 2 * (_sequence_len(edges) or 0)
            face_work += len(getattr(submesh, "faces", ()) or ())
    for raw_submesh_index, faces in selection.face_map().items():
        submesh_index = _coerce_index(raw_submesh_index)
        if submesh_index is not None and 0 <= submesh_index < len(submeshes):
            submesh = submeshes[submesh_index]
            face_work += len(getattr(submesh, "faces", ()) or ())
            vertex_work += 3 * (_sequence_len(faces) or 0)
    return vertex_work, face_work


def _finite_float(value: object, fallback: float = 0.0) -> float:
    parsed = _finite_float_or_none(value)
    return fallback if parsed is None else parsed


def _finite_float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _nonnegative_int(value: object, fallback: int = 0) -> int:
    parsed = _coerce_index(value)
    if parsed is None:
        return fallback
    return parsed if parsed >= 0 else fallback


def _vec3(value: object, fallback: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return fallback
    parsed = (_finite_float(value[0]), _finite_float(value[1]), _finite_float(value[2]))
    return parsed if all(math.isfinite(component) for component in parsed) else fallback


def _vec2(value: object, fallback: tuple[float, float] = (0.0, 0.0)) -> tuple[float, float]:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return fallback
    parsed = (_finite_float(value[0]), _finite_float(value[1]))
    return parsed if all(math.isfinite(component) for component in parsed) else fallback


def _source_submesh_indices(indices: Sequence[int] | None) -> tuple[int, ...]:
    result: list[int] = []
    seen: set[int] = set()
    if indices is None:
        return ()
    try:
        raw_indices = iter(indices)
    except TypeError:
        return ()
    for raw_index in raw_indices:
        index = _coerce_index(raw_index)
        if index is None:
            continue
        if index >= 0 and index not in seen:
            result.append(index)
            seen.add(index)
    return tuple(result)


def _source_vertex_indices(indices: Iterable[int] | None, vertex_count: int) -> Sequence[int]:
    if isinstance(indices, range):
        if indices.step == 1:
            start = max(0, indices.start)
            stop = min(max(0, vertex_count), indices.stop)
            return range(start, stop) if start < stop else ()
        raw_indices: Iterable[int] = indices
    else:
        if indices is None:
            return ()
        compact_range = _contiguous_valid_index_range(indices, vertex_count)
        if compact_range is not None:
            return compact_range
        raw_indices = indices
    result: list[int] = []
    seen: set[int] = set()
    try:
        iterator = iter(raw_indices)
    except TypeError:
        return ()
    for raw_index in iterator:
        index = _coerce_index(raw_index)
        if index is None:
            continue
        if 0 <= index < vertex_count and index not in seen:
            result.append(index)
            seen.add(index)
    return result


def _contiguous_valid_index_range(indices: Iterable[int], vertex_count: int) -> range | None:
    try:
        raw_length = len(indices)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    if raw_length <= 0:
        return None
    try:
        iterator = iter(indices)
        first = int(next(iterator))
    except (StopIteration, TypeError, ValueError, OverflowError):
        return None
    if first < 0 or first >= vertex_count:
        return None
    for offset, raw_index in enumerate(iterator, start=1):
        try:
            index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            return None
        if index != first + offset or index >= vertex_count:
            return None
    return range(first, first + raw_length)


def _is_full_vertex_range(indices: object, vertex_count: int) -> bool:
    return (
        vertex_count > 0
        and isinstance(indices, range)
        and indices.start == 0
        and indices.stop == vertex_count
        and indices.step == 1
    )


def _contiguous_index_range(indices: Sequence[int]) -> tuple[int, int] | None:
    if isinstance(indices, range):
        if indices.start >= 0 and indices.step == 1 and len(indices) > 0:
            return indices.start, len(indices)
        return None
    try:
        iterator = iter(indices)
        start = int(next(iterator))
    except (TypeError, ValueError, OverflowError):
        return None
    except StopIteration:
        return None
    if start < 0:
        return None
    count = 1
    for offset, raw_value in enumerate(iterator, start=1):
        try:
            value = int(raw_value)
        except (TypeError, ValueError, OverflowError):
            return None
        if value != start + offset:
            return None
        count += 1
    return start, count


def _same_index_sequence(left: Sequence[int], right: Sequence[int]) -> bool:
    if len(left) != len(right):
        return False
    return all(int(left_value) == int(right_value) for left_value, right_value in zip(left, right))


def _put_index_range_or_values(
    group: dict[str, object],
    indices: Sequence[int],
    indices_key: str,
    start_key: str,
    count_key: str,
) -> None:
    index_range = _contiguous_index_range(indices)
    if index_range is not None:
        group[start_key] = index_range[0]
        group[count_key] = index_range[1]
    else:
        group[indices_key] = list(indices)


def _valid_face_items(submesh: object) -> tuple[tuple[int, tuple[int, int, int]], ...]:
    vertex_count = _sequence_len(getattr(submesh, "vertices", ())) or 0
    items: list[tuple[int, tuple[int, int, int]]] = []
    for face_index, face in enumerate(getattr(submesh, "faces", ()) or ()):
        face_vertices = _valid_face_vertices(face, vertex_count)
        if len(face_vertices) == 3:
            items.append((face_index, (face_vertices[0], face_vertices[1], face_vertices[2])))
    return tuple(items)


def _valid_face_vertices(face: object, vertex_count: int) -> list[int]:
    if not isinstance(face, (tuple, list)):
        return []
    items = tuple(face or ())
    if len(items) < 3:
        return []
    indices: list[int] = []
    for raw_index in items[:3]:
        vertex_index = _coerce_index(raw_index)
        if vertex_index is None:
            return []
        if vertex_index < 0 or vertex_index >= vertex_count:
            return []
        indices.append(vertex_index)
    return indices


def _coerce_index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text or any(marker in text for marker in ".eE"):
            return None
        try:
            return int(text, 10)
        except ValueError:
            return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None


def _sanitized_material_override_values(overrides: Mapping[str, object], *, include_defaults: bool) -> dict[str, object]:
    values: dict[str, object] = {}
    defaults = _DEFAULT_NATIVE_MATERIAL_OVERRIDES if include_defaults else {}
    for key in _NATIVE_MATERIAL_SCALAR_OVERRIDE_KEYS:
        if key not in overrides:
            continue
        parsed = _finite_float_or_none(overrides[key])
        if parsed is not None:
            values[key] = parsed
        elif key in defaults:
            values[key] = defaults[key]
    for key in _NATIVE_MATERIAL_COLOR_OVERRIDE_KEYS:
        if key not in overrides:
            continue
        parsed_color = _finite_color(overrides[key])
        if parsed_color is not None:
            values[key] = parsed_color
        elif key in defaults:
            values[key] = list(defaults[key]) if isinstance(defaults[key], list) else defaults[key]
    return values


def _finite_color(value: object) -> list[float] | None:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return None
    parsed = [_finite_float_or_none(component) for component in value[:3]]
    if any(component is None for component in parsed):
        return None
    return [float(component) for component in parsed if component is not None]


def _valid_selected_edges_for_submesh(submesh: object, edges: set[tuple[int, int]]) -> set[tuple[int, int]]:
    vertex_count = _sequence_len(getattr(submesh, "vertices", ())) or 0
    selected = {
        _edge_key(a, b)
        for a, b in edges
        if 0 <= a < vertex_count and 0 <= b < vertex_count and a != b
    }
    if not selected:
        return set()
    if not (_sequence_len(getattr(submesh, "faces", ())) or 0):
        return selected
    return selected & _existing_face_edges(submesh)


def _existing_face_edges(submesh: object) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    for _face_index, (a, b, c) in _valid_face_items(submesh):
        edges.update((_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)))
    return edges


def _edge_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


__all__ = [
    "mesh_edit_material_override_groups",
    "mesh_edit_selection_groups",
    "mesh_edit_triangle_groups",
    "mesh_edit_vertex_update_groups",
    "mesh_pose_to_native_preview",
    "mesh_to_native_preview",
]

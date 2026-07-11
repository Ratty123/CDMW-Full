"""GLB editable-package interchange for Mesh Editor v2."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Mapping, Sequence

from cdmw.core.atomic_file import atomic_write_bytes

from .mesh_exporter import write_roundtrip_manifest
from .mesh_obj_importer import (
    _OBJ_ROUNDTRIP_SIDECAR_FORMATS,
    _OBJ_ROUNDTRIP_SUPPORTED_SCHEMA_VERSION,
    _attach_obj_sidecar_edit_operations,
    _attach_obj_sidecar_lod_identity,
    _attach_obj_sidecar_source_identity,
    _attach_obj_sidecar_unknown_fields,
    _attach_obj_sidecar_warnings,
    _match_obj_roundtrip_sidecar_submeshes,
    _normalize_obj_sidecar_source_vertex_map,
    _normalize_obj_sidecar_texture_name,
    _obj_sidecar_int,
    _obj_sidecar_original_index_count,
    _obj_sidecar_original_vertex_stride,
    _obj_sidecar_source_vertex_offsets,
    _validate_obj_sidecar_skinning_metadata,
    _validate_obj_sidecar_source_index_maps,
    _validate_obj_sidecar_stable_ids,
)
from .mesh_parser import ParsedMesh, SubMesh
from .scene_importer import import_scene_mesh


def export_glb(
    mesh: ParsedMesh,
    output_dir: str | Path,
    name: str = "mesh",
    *,
    extra_payload: Mapping[str, object] | None = None,
) -> list[str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    glb_path = root / f"{name or 'mesh'}.glb"
    atomic_write_bytes(glb_path, _build_glb(mesh))
    sidecar_path = write_roundtrip_manifest(mesh, glb_path, extra_payload=dict(extra_payload or {}))
    return [str(glb_path), str(sidecar_path)]


def import_glb_with_sidecar(path: str | Path) -> ParsedMesh:
    glb_path = _editable_glb_path(Path(path))
    sidecar = _load_glb_roundtrip_sidecar(glb_path)
    mesh = import_scene_mesh(glb_path)
    _attach_glb_sidecar(mesh, sidecar, glb_path.name)
    return mesh


def _editable_glb_path(path: Path) -> Path:
    if path.is_dir():
        for name in ("mesh.glb", "edited_mesh.glb", "edited.glb"):
            candidate = path / name
            if candidate.is_file():
                return candidate
    return path


def _load_glb_roundtrip_sidecar(glb_path: Path) -> dict[str, object]:
    for candidate in (Path(f"{glb_path}.meta.json"), glb_path.parent / "mesh.cdmeta.json"):
        if not candidate.is_file():
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"GLB sidecar is not a JSON object: {candidate}")
        payload_format = str(payload.get("format", "") or "").strip()
        if payload_format and payload_format not in _OBJ_ROUNDTRIP_SIDECAR_FORMATS:
            raise ValueError(f"Unsupported GLB sidecar format: {payload_format!r}.")
        schema_version = payload.get("schema_version")
        if schema_version is not None and int(schema_version) != _OBJ_ROUNDTRIP_SUPPORTED_SCHEMA_VERSION:
            raise ValueError(f"Unsupported GLB sidecar schema version: {schema_version!r}.")
        _validate_obj_sidecar_stable_ids(payload)
        _validate_obj_sidecar_skinning_metadata(payload)
        _validate_obj_sidecar_source_index_maps(payload)
        return payload
    raise ValueError("GLB sidecar is required for editable mesh package import.")


def _attach_glb_sidecar(mesh: ParsedMesh, sidecar: dict[str, object], source_name: str) -> None:
    mesh.path = str(sidecar.get("source_path", "") or mesh.path or "")
    mesh.format = str(sidecar.get("source_format", "") or mesh.format or "")
    submesh_list = [{"name": str(submesh.name or ""), "material": str(submesh.material or "")} for submesh in mesh.submeshes]
    matched_entries = _match_obj_roundtrip_sidecar_submeshes(
        sidecar,
        submesh_list,
        source_path=str(sidecar.get("source_path", "") or ""),
        source_format=str(sidecar.get("source_format", "") or ""),
    )
    _attach_obj_sidecar_source_identity(mesh, sidecar)
    _attach_obj_sidecar_lod_identity(mesh, sidecar)
    _attach_obj_sidecar_warnings(mesh, matched_entries, {})
    for submesh, entry in zip(mesh.submeshes, matched_entries):
        _attach_glb_submesh_sidecar(submesh, entry)
    _attach_obj_sidecar_edit_operations(mesh, matched_entries, sidecar, source_name)


def _attach_glb_submesh_sidecar(submesh: SubMesh, entry: object) -> None:
    if not isinstance(entry, dict):
        return
    source_vertex_map = _normalize_obj_sidecar_source_vertex_map(entry, expected_count=len(submesh.vertices))
    submesh.source_vertex_map = source_vertex_map
    submesh.source_vertex_map_authority = "target_donor_record" if source_vertex_map else ""
    submesh.source_vertex_offsets = _obj_sidecar_source_vertex_offsets(entry, source_vertex_map)
    submesh.source_index_offset = _obj_sidecar_int(entry, "original_index_offset")
    submesh.source_index_count = _obj_sidecar_original_index_count(entry)
    submesh.source_vertex_stride = _obj_sidecar_original_vertex_stride(entry)
    submesh.source_descriptor_offset = _obj_sidecar_int(entry, "original_descriptor_offset")
    submesh.texture = _normalize_obj_sidecar_texture_name(entry) or submesh.texture
    _attach_obj_sidecar_unknown_fields(submesh, entry)


def _build_glb(mesh: ParsedMesh) -> bytes:
    buffer = bytearray()
    buffer_views: list[dict[str, object]] = []
    accessors: list[dict[str, object]] = []
    gltf_meshes: list[dict[str, object]] = []
    nodes: list[dict[str, object]] = []
    materials: list[dict[str, object]] = []
    for index, submesh in enumerate(tuple(mesh.submeshes or ())):
        vertices = [tuple(float(value) for value in vertex[:3]) for vertex in tuple(submesh.vertices or ())]
        faces = [tuple(int(value) for value in face[:3]) for face in tuple(submesh.faces or ())]
        if not vertices or not faces:
            raise ValueError("GLB editable export requires triangle geometry.")
        normals = _rows_or_default(submesh.normals, len(vertices), (0.0, 1.0, 0.0))
        uvs = [(float(uv[0]), 1.0 - float(uv[1])) for uv in _rows_or_default(submesh.uvs, len(vertices), (0.0, 0.0))]
        position_accessor = _float_accessor(buffer, buffer_views, accessors, vertices, "VEC3", 34962, include_min_max=True)
        normal_accessor = _float_accessor(buffer, buffer_views, accessors, normals, "VEC3", 34962)
        uv_accessor = _float_accessor(buffer, buffer_views, accessors, uvs, "VEC2", 34962)
        index_accessor = _index_accessor(buffer, buffer_views, accessors, [value for face in faces for value in face])
        material_index = len(materials)
        materials.append({"name": str(submesh.material or submesh.name or f"material_{index}")})
        name = str(submesh.name or f"submesh_{index}")
        gltf_meshes.append(
            {
                "name": name,
                "primitives": [
                    {
                        "attributes": {"POSITION": position_accessor, "NORMAL": normal_accessor, "TEXCOORD_0": uv_accessor},
                        "indices": index_accessor,
                        "material": material_index,
                    }
                ],
            }
        )
        nodes.append({"name": name, "mesh": index})
    document = {
        "asset": {"version": "2.0", "generator": "Crimson Desert Mod Workbench"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": gltf_meshes,
        "materials": materials,
        "buffers": [{"byteLength": len(buffer)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
    }
    return _pack_glb(document, bytes(buffer))


def _rows_or_default(rows: Sequence[Sequence[float]], count: int, default: tuple[float, ...]) -> list[tuple[float, ...]]:
    values = [tuple(float(value) for value in tuple(row)[: len(default)]) for row in tuple(rows or ())]
    if len(values) != count:
        return [default] * count
    return values


def _float_accessor(
    buffer: bytearray,
    buffer_views: list[dict[str, object]],
    accessors: list[dict[str, object]],
    rows: Sequence[Sequence[float]],
    type_name: str,
    target: int,
    *,
    include_min_max: bool = False,
) -> int:
    component_count = 3 if type_name == "VEC3" else 2
    raw = b"".join(struct.pack("<" + ("f" * component_count), *tuple(row)[:component_count]) for row in rows)
    view = _append_buffer_view(buffer, buffer_views, raw, target)
    accessor: dict[str, object] = {"bufferView": view, "componentType": 5126, "count": len(rows), "type": type_name}
    if include_min_max and rows:
        accessor["min"] = [min(float(row[axis]) for row in rows) for axis in range(component_count)]
        accessor["max"] = [max(float(row[axis]) for row in rows) for axis in range(component_count)]
    accessors.append(accessor)
    return len(accessors) - 1


def _index_accessor(
    buffer: bytearray,
    buffer_views: list[dict[str, object]],
    accessors: list[dict[str, object]],
    indices: Sequence[int],
) -> int:
    max_index = max(indices, default=0)
    component_type = 5123 if max_index <= 65535 else 5125
    pack_code = "H" if component_type == 5123 else "I"
    raw = b"".join(struct.pack("<" + pack_code, int(index)) for index in indices)
    view = _append_buffer_view(buffer, buffer_views, raw, 34963)
    accessors.append(
        {
            "bufferView": view,
            "componentType": component_type,
            "count": len(indices),
            "type": "SCALAR",
            "min": [min(indices) if indices else 0],
            "max": [max_index],
        }
    )
    return len(accessors) - 1


def _append_buffer_view(buffer: bytearray, buffer_views: list[dict[str, object]], raw: bytes, target: int) -> int:
    offset = len(buffer)
    buffer.extend(raw)
    buffer.extend(b"\x00" * ((4 - (len(buffer) % 4)) % 4))
    buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw), "target": target})
    return len(buffer_views) - 1


def _pack_glb(document: dict[str, object], binary: bytes) -> bytes:
    json_chunk = _pad4(json.dumps(document, separators=(",", ":")).encode("utf-8"), b" ")
    bin_chunk = _pad4(binary, b"\x00")
    total_length = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    return b"glTF" + struct.pack("<II", 2, total_length) + struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk + struct.pack(
        "<I4s", len(bin_chunk), b"BIN\x00"
    ) + bin_chunk


def _pad4(data: bytes, pad_byte: bytes) -> bytes:
    return data + pad_byte * ((4 - (len(data) % 4)) % 4)

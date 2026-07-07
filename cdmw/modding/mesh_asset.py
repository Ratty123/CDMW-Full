"""Adapters from parsed Crimson meshes to the strict MeshAsset contract."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Callable

from cdmw.domain.mesh.skeleton import summarize_mesh_skinning

from cdmw.domain.mesh.asset import (
    BinaryLayout,
    LAYOUT_CONFIDENCE_EXACT,
    LAYOUT_CONFIDENCE_FALLBACK_SCAN,
    LAYOUT_CONFIDENCE_INFERRED,
    IndexBuffer,
    MaterialSlot,
    MeshAsset,
    MeshAssetSubmesh,
    MeshFileSection,
    MeshLod,
    MeshVertex,
    VertexBuffer,
)

from .mesh_parser import MeshBinaryLayout, ParsedMesh, SubMesh, inspect_mesh_binary_layout, parse_mesh


def mesh_asset_from_bytes(
    data: bytes,
    filename: str = "",
    *,
    parser: Callable[[bytes, str], ParsedMesh] = parse_mesh,
) -> MeshAsset:
    parsed = parser(data, filename)
    layout = inspect_mesh_binary_layout(data, filename)
    return mesh_asset_from_parsed_mesh(parsed, data, binary_layout=layout, source_path=filename)


def mesh_asset_from_parsed_mesh(
    mesh: ParsedMesh,
    original_data: bytes = b"",
    *,
    binary_layout: MeshBinaryLayout | None = None,
    source_path: str = "",
) -> MeshAsset:
    source = str(source_path or mesh.path or "").strip()
    fmt = str(mesh.format or "").strip().lower()
    binary_layout = _binary_layout_from_source(original_data, source, binary_layout)
    material_slots = _material_slots(mesh, binary_layout)
    layout = _binary_layout(binary_layout)
    lods = _lods(mesh, original_data, material_slots, binary_layout)
    return MeshAsset(
        source_path=source,
        source_format=fmt,
        original_file_hash=hashlib.sha256(original_data).hexdigest() if original_data else "",
        original_file_size=len(original_data),
        asset_id=_asset_id(source, original_data),
        lods=lods,
        material_slots=material_slots,
        skeleton_info=mesh_skinning_contract(mesh),
        binary_layout=layout,
        unknown_sections=tuple(section for section in layout.file_sections if section.name != "geometry"),
        metadata={
            "parsed_mesh_type": "ParsedMesh",
            "total_vertices": int(getattr(mesh, "total_vertices", 0) or 0),
            "total_faces": int(getattr(mesh, "total_faces", 0) or 0),
            "has_uvs": bool(getattr(mesh, "has_uvs", False)),
            "has_bones": bool(getattr(mesh, "has_bones", False)),
        },
        layout_confidence=_layout_confidence(mesh, binary_layout),
    )


def _binary_layout_from_source(
    original_data: bytes,
    source_path: str,
    binary_layout: MeshBinaryLayout | None,
) -> MeshBinaryLayout | None:
    if binary_layout is not None or not original_data:
        return binary_layout
    try:
        inspected = inspect_mesh_binary_layout(original_data, source_path)
    except Exception:
        return None
    if inspected.layout_confidence != LAYOUT_CONFIDENCE_FALLBACK_SCAN or inspected.section_ranges:
        return inspected
    return None


def mesh_asset_to_inspect_dict(asset: MeshAsset) -> dict[str, object]:
    """Return a JSON-safe inspection view without raw vertex byte payloads."""
    return {
        "source_path": asset.source_path,
        "source_format": asset.source_format,
        "original_file_hash": asset.original_file_hash,
        "original_file_size": asset.original_file_size,
        "asset_id": asset.asset_id,
        "parse_confidence": asset.parse_confidence,
        "layout_confidence": asset.layout_confidence,
        "skeleton_info": _json_safe(asset.skeleton_info),
        "material_slots": [asdict(slot) for slot in asset.material_slots],
        "binary_layout": {
            "endian": asset.binary_layout.endian,
            "alignment": asset.binary_layout.alignment,
            "file_sections": [asdict(section) for section in asset.binary_layout.file_sections],
            "preserved_ranges": [asdict(section) for section in asset.binary_layout.preserved_ranges],
            "offsets": dict(asset.binary_layout.offsets),
            "sizes": dict(asset.binary_layout.sizes),
            "rebuild_rules": list(asset.binary_layout.rebuild_rules),
        },
        "unknown_sections": [asdict(section) for section in asset.unknown_sections],
        "lods": [_lod_to_dict(lod) for lod in asset.lods],
        "metadata": _json_safe(asset.metadata),
    }


def mesh_skinning_contract(mesh: ParsedMesh) -> dict[str, object]:
    summary = summarize_mesh_skinning(mesh)
    return {
        "skinned": summary.skinned,
        "skeleton_linked": summary.skeleton_linked,
        "skeleton_bone_count": summary.skeleton_bone_count,
        "inferred_bone_count": summary.inferred_bone_count,
        "max_bone_index": summary.max_bone_index,
        "weighted_part_count": summary.weighted_part_count,
        "weighted_vertex_count": summary.weighted_vertex_count,
        "invalid_row_count": summary.invalid_row_count,
        "unnormalized_vertex_count": summary.unnormalized_vertex_count,
        "parts": [
            {
                "index": part.index,
                "name": part.name,
                "vertex_count": part.vertex_count,
                "skinned": part.skinned,
                "weighted_vertex_count": part.weighted_vertex_count,
                "max_influences": part.max_influences,
                "max_bone_index": part.max_bone_index,
                "unique_bone_indices": list(part.unique_bone_indices),
                "invalid_row_count": part.invalid_row_count,
                "unnormalized_vertex_count": part.unnormalized_vertex_count,
            }
            for part in summary.parts
        ],
    }


def _lod_to_dict(lod: MeshLod) -> dict[str, object]:
    return {
        "lod_index": lod.lod_index,
        "name": lod.name,
        "original_section_offset": lod.original_section_offset,
        "original_section_size": lod.original_section_size,
        "bounds": lod.bounds,
        "submeshes": [
            {
                "submesh_index": submesh.submesh_index,
                "stable_id": submesh.stable_id,
                "name": submesh.name,
                "material_slot_index": submesh.material_slot_index,
                "vertex_count": len(submesh.vertex_buffer.vertices),
                "index_count": len(submesh.index_buffer.indices),
                "original_descriptor_offset": submesh.original_descriptor_offset,
                "original_vertex_offset": submesh.original_vertex_offset,
                "original_index_offset": submesh.original_index_offset,
                "original_vertex_stride": submesh.original_vertex_stride,
                "source_vertex_map_count": len(submesh.source_vertex_map),
                "source_index_map_count": len(submesh.source_index_map),
                "raw_vertex_record_count": sum(1 for record in submesh.vertex_buffer.raw_vertex_records if record),
                "bounds": submesh.bounds,
                "metadata": _json_safe(submesh.metadata),
                "unknown_fields": _json_safe(submesh.unknown_fields),
            }
            for submesh in lod.submeshes
        ],
        "metadata": _json_safe(lod.metadata),
    }


def _binary_layout(layout: MeshBinaryLayout | None) -> BinaryLayout:
    if layout is None:
        return BinaryLayout(rebuild_rules=("preserve_original_bytes_unless_edited",))
    sections = tuple(
        MeshFileSection(section.name, int(section.offset), int(section.size), int(section.index))
        for section in getattr(layout, "section_ranges", ()) or ()
    )
    offsets = {
        "geometry": _int_attr(getattr(layout, "geometry_offset", -1)),
        "vertex_buffer": _int_attr(getattr(layout, "vertex_buffer_offset", -1)),
        "index_buffer": _int_attr(getattr(layout, "index_buffer_offset", -1)),
    }
    sizes = {"geometry": int(getattr(layout, "geometry_size", 0) or 0)}
    return BinaryLayout(
        file_sections=sections,
        offsets=offsets,
        sizes=sizes,
        preserved_ranges=sections,
        rebuild_rules=("preserve_unknown_sections", "patch_known_vertex_channels_only"),
    )


def _material_slots(mesh: ParsedMesh, layout: MeshBinaryLayout | None) -> tuple[MaterialSlot, ...]:
    raw_slots = tuple(getattr(layout, "material_slots", ()) or ()) if layout is not None else ()
    if raw_slots:
        return tuple(MaterialSlot(int(slot.index), str(slot.name or ""), str(slot.texture or "")) for slot in raw_slots)
    return tuple(
        MaterialSlot(index, str(submesh.material or submesh.name or ""), str(submesh.texture or ""))
        for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ()))
    )


def _lods(
    mesh: ParsedMesh,
    original_data: bytes,
    material_slots: tuple[MaterialSlot, ...],
    layout: MeshBinaryLayout | None,
) -> tuple[MeshLod, ...]:
    raw_lods = tuple(getattr(mesh, "lod_levels", ()) or ())
    source_lods = raw_lods if raw_lods else (tuple(getattr(mesh, "submeshes", ()) or ()),)
    sections = tuple(getattr(layout, "section_ranges", ()) or ()) if layout is not None else ()
    result: list[MeshLod] = []
    for lod_index, submeshes in enumerate(source_lods):
        section = sections[min(lod_index + 1, len(sections) - 1)] if sections else None
        asset_submeshes = tuple(
            _submesh_asset(lod_index, submesh_index, submesh, original_data, material_slots)
            for submesh_index, submesh in enumerate(tuple(submeshes or ()))
        )
        result.append(
            MeshLod(
                lod_index=lod_index,
                name=f"lod{lod_index}",
                submeshes=asset_submeshes,
                original_section_offset=int(getattr(section, "offset", -1) if section is not None else -1),
                original_section_size=int(getattr(section, "size", 0) if section is not None else 0),
                bounds=_bounds_for_submeshes(asset_submeshes),
                metadata={"source": "lod_levels" if raw_lods else "submeshes"},
            )
        )
    return tuple(result)


def _submesh_asset(
    lod_index: int,
    submesh_index: int,
    submesh: SubMesh,
    original_data: bytes,
    material_slots: tuple[MaterialSlot, ...],
) -> MeshAssetSubmesh:
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    faces = tuple(getattr(submesh, "faces", ()) or ())
    stride = int(getattr(submesh, "source_vertex_stride", 0) or _stride_from_offsets(submesh))
    source_offsets = tuple(int(value) for value in tuple(getattr(submesh, "source_vertex_offsets", ()) or ()))
    raw_records = tuple(_raw_record(original_data, source_offsets[index] if index < len(source_offsets) else -1, stride) for index in range(len(vertices)))
    vertex_rows = tuple(
        MeshVertex(
            position=_vec3(vertices[index]),
            normal=_vec3(_value_at(getattr(submesh, "normals", ()), index)) if _value_at(getattr(submesh, "normals", ()), index) is not None else None,
            tangent=_vec3(_value_at(getattr(submesh, "tangents", ()), index)) if _value_at(getattr(submesh, "tangents", ()), index) is not None else None,
            uv0=_vec2(_value_at(getattr(submesh, "uvs", ()), index)) if _value_at(getattr(submesh, "uvs", ()), index) is not None else None,
            bone_indices=tuple(int(value) for value in tuple(_value_at(getattr(submesh, "bone_indices", ()), index) or ())),
            bone_weights=tuple(float(value) for value in tuple(_value_at(getattr(submesh, "bone_weights", ()), index) or ())),
            source_offset=source_offsets[index] if index < len(source_offsets) else -1,
            raw_bytes_before_edit=raw_records[index],
        )
        for index in range(len(vertices))
    )
    indices = tuple(int(index) for face in faces for index in tuple(face or ()))
    source_vertex_map = _source_vertex_map(submesh, len(vertices))
    original_index_count = int(getattr(submesh, "source_index_count", 0) or len(indices))
    return MeshAssetSubmesh(
        submesh_index=submesh_index,
        stable_id=f"lod{lod_index}_submesh{submesh_index}",
        name=str(submesh.name or ""),
        material_slot_index=_material_slot_index(submesh, material_slots, submesh_index),
        vertex_buffer=VertexBuffer(vertex_rows, stride, _vertex_format(stride), raw_records),
        index_buffer=IndexBuffer(
            indices=indices,
            index_format="u16",
            original_offset=_int_attr(getattr(submesh, "source_index_offset", -1)),
            original_count=original_index_count,
        ),
        source_vertex_map=source_vertex_map,
        source_index_map=tuple(range(original_index_count)),
        original_descriptor_offset=_int_attr(getattr(submesh, "source_descriptor_offset", -1)),
        original_vertex_offset=min((offset for offset in source_offsets if offset >= 0), default=-1),
        original_index_offset=_int_attr(getattr(submesh, "source_index_offset", -1)),
        original_vertex_stride=stride,
        bounds=_bounds(vertices),
        metadata={
            "material": str(submesh.material or ""),
            "texture": str(submesh.texture or ""),
            "source_lod_count": int(getattr(submesh, "source_lod_count", 0) or 0),
        },
        unknown_fields={
            "source_bbox_min": tuple(getattr(submesh, "source_bbox_min", ()) or ()),
            "source_bbox_extent": tuple(getattr(submesh, "source_bbox_extent", ()) or ()),
        },
    )


def _layout_confidence(mesh: ParsedMesh, layout: MeshBinaryLayout | None) -> str:
    raw_confidence = str(getattr(layout, "layout_confidence", "") or "").strip()
    if raw_confidence in {LAYOUT_CONFIDENCE_EXACT, LAYOUT_CONFIDENCE_INFERRED, LAYOUT_CONFIDENCE_FALLBACK_SCAN}:
        return raw_confidence
    warnings = tuple(getattr(layout, "warnings", ()) or ()) if layout is not None else ()
    if any("fallback" in str(warning).lower() or "failed" in str(warning).lower() for warning in warnings):
        return LAYOUT_CONFIDENCE_FALLBACK_SCAN
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    if submeshes and all(_has_source_trace(submesh) for submesh in submeshes):
        return LAYOUT_CONFIDENCE_EXACT
    return LAYOUT_CONFIDENCE_INFERRED if submeshes else LAYOUT_CONFIDENCE_FALLBACK_SCAN


def _has_source_trace(submesh: SubMesh) -> bool:
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    offsets = tuple(getattr(submesh, "source_vertex_offsets", ()) or ())
    return bool(vertices) and len(offsets) == len(vertices) and int(getattr(submesh, "source_vertex_stride", 0) or 0) > 0


def _asset_id(source_path: str, original_data: bytes) -> str:
    if source_path:
        return Path(source_path).stem
    digest = hashlib.sha256(original_data).hexdigest() if original_data else ""
    return digest[:16]


def _source_vertex_map(submesh: SubMesh, vertex_count: int) -> tuple[int, ...]:
    raw = tuple(getattr(submesh, "source_vertex_map", ()) or ())
    if len(raw) == vertex_count:
        try:
            return tuple(int(value) for value in raw)
        except Exception:
            return tuple(-1 for _ in range(vertex_count))
    return tuple(range(vertex_count))


def _int_attr(value: object, default: int = -1) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _raw_record(data: bytes, offset: int, stride: int) -> bytes:
    if stride <= 0 or offset < 0 or offset + stride > len(data):
        return b""
    return bytes(data[offset : offset + stride])


def _stride_from_offsets(submesh: SubMesh) -> int:
    offsets = sorted(int(value) for value in tuple(getattr(submesh, "source_vertex_offsets", ()) or ()) if int(value) >= 0)
    if len(offsets) < 2:
        return 0
    deltas = [right - left for left, right in zip(offsets, offsets[1:]) if right > left]
    return min(deltas) if deltas else 0


def _vertex_format(stride: int) -> str:
    return f"stride_{stride}" if stride > 0 else "unknown"


def _material_slot_index(submesh: SubMesh, slots: tuple[MaterialSlot, ...], fallback: int) -> int:
    names = {str(submesh.material or "").strip(), str(submesh.name or "").strip()}
    for slot in slots:
        if str(slot.name or "").strip() in names or str(slot.texture or "").strip() in names:
            return slot.index
    return fallback if 0 <= fallback < len(slots) else -1


def _bounds_for_submeshes(submeshes: tuple[MeshAssetSubmesh, ...]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    points = [vertex.position for submesh in submeshes for vertex in submesh.vertex_buffer.vertices]
    return _bounds(tuple(points))


def _bounds(vertices: tuple[object, ...]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    points = [_vec3(vertex) for vertex in vertices if vertex is not None]
    if not points:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    return (
        tuple(min(point[axis] for point in points) for axis in range(3)),
        tuple(max(point[axis] for point in points) for axis in range(3)),
    )


def _value_at(values: object, index: int) -> object | None:
    sequence = tuple(values or ()) if not isinstance(values, tuple) else values
    return sequence[index] if 0 <= index < len(sequence) else None


def _vec3(value: object) -> tuple[float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return (0.0, 0.0, 0.0)
    return (float(value[0]), float(value[1]), float(value[2]))


def _vec2(value: object) -> tuple[float, float]:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return (0.0, 0.0)
    return (float(value[0]), float(value[1]))


def _json_safe(value: object) -> object:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, bytes):
        return {"byte_count": len(value)}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


__all__ = [
    "mesh_skinning_contract",
    "mesh_asset_from_bytes",
    "mesh_asset_from_parsed_mesh",
    "mesh_asset_to_inspect_dict",
]

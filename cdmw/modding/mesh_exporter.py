"""OBJ and binary FBX 7.4 exporter for parsed mesh data.

Exports ParsedMesh objects from mesh_parser to standard 3D formats:
  - OBJ + MTL (Wavefront, universally supported)
  - FBX binary 7.4 (Blender, Maya, 3ds Max, Unity, Unreal Engine)

No external libraries required — pure Python binary FBX writer.
"""

from __future__ import annotations

import io
import json
import os
import struct
import tempfile
import zlib
import math
import hashlib
from pathlib import Path, PurePath
from datetime import UTC, datetime
from typing import Optional

from cdmw.core.atomic_file import atomic_write_bytes, atomic_write_text

from .mesh_asset import mesh_skinning_contract
from .mesh_parser import ParsedMesh, SubMesh
from .logging import get_logger

logger = get_logger("core.mesh_exporter")

_OBJ_ROUNDTRIP_SIDECAR_FORMAT = "mesh_roundtrip_manifest_v2"
_OBJ_ROUNDTRIP_SCHEMA_VERSION = 1
_OBJ_ROUNDTRIP_TOOL_VERSION = "cdmw_mesh_roundtrip_manifest_v2"
_OBJ_ROUNDTRIP_ALLOWED_EDIT_OPERATIONS = (
    "replace_positions_same_count",
    "replace_normals_same_count",
    "replace_uv0_same_count",
    "scale_vertices",
    "translate_vertices",
    "rotate_vertices",
    "recompute_bounds",
)

def _obj_roundtrip_sidecar_path(obj_path: str | Path) -> Path:
    return Path(f"{obj_path}.meta.json")


def _coerce_submesh_source_vertex_map(submesh: SubMesh) -> list[int]:
    raw_map = list(getattr(submesh, "source_vertex_map", ()) or ())
    vertex_count = len(getattr(submesh, "vertices", ()) or ())
    if len(raw_map) == vertex_count:
        return [
            int(value) if isinstance(value, (int, float)) else -1
            for value in raw_map
        ]
    return list(range(vertex_count))


def _mesh_original_data(mesh: ParsedMesh) -> bytes:
    original_data = bytes(getattr(mesh, "_cdmw_original_data", b"") or b"")
    if not original_data:
        source = Path(str(getattr(mesh, "path", "") or ""))
        if source.is_file():
            try:
                original_data = source.read_bytes()
            except OSError:
                original_data = b""
    return original_data


def _source_identity_payload(mesh: ParsedMesh) -> dict[str, object]:
    original_data = _mesh_original_data(mesh)
    if not original_data:
        return {}
    return {
        "source_asset_hash": hashlib.sha256(original_data).hexdigest(),
        "source_asset_size": len(original_data),
    }


def _mesh_asset_id(mesh: ParsedMesh, source_identity: dict[str, object]) -> str:
    source_path = str(getattr(mesh, "path", "") or "").strip()
    if source_path:
        return Path(source_path).stem
    source_hash = str(source_identity.get("source_asset_hash", "") or "")
    return source_hash[:16]


def _mesh_parse_confidence(mesh: ParsedMesh) -> str:
    raw = str(getattr(mesh, "_cdmw_mesh_asset_parse_confidence", "") or "").strip()
    if raw:
        return raw
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    if not submeshes:
        return "failed"
    if all(
        len(getattr(submesh, "source_vertex_offsets", ()) or ()) == len(getattr(submesh, "vertices", ()) or ())
        and int(getattr(submesh, "source_vertex_stride", 0) or 0) > 0
        for submesh in submeshes
    ):
        return "exact"
    return "inferred"


def _submesh_bounds(submesh: SubMesh) -> list[list[float]]:
    vertices = list(getattr(submesh, "vertices", ()) or ())
    if not vertices:
        return [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    return [
        [float(min(vertex[axis] for vertex in vertices)) for axis in range(3)],
        [float(max(vertex[axis] for vertex in vertices)) for axis in range(3)],
    ]


def _lod_bounds(submeshes: object) -> list[list[float]]:
    vertices = [
        vertex
        for submesh in tuple(submeshes or ())
        for vertex in tuple(getattr(submesh, "vertices", ()) or ())
    ]
    if not vertices:
        return [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    return [
        [float(min(vertex[axis] for vertex in vertices)) for axis in range(3)],
        [float(max(vertex[axis] for vertex in vertices)) for axis in range(3)],
    ]


def _mesh_material_slots_payload(mesh: ParsedMesh) -> list[dict[str, object]]:
    raw_slots = tuple(getattr(mesh, "_cdmw_mesh_asset_material_slots", ()) or getattr(mesh, "material_slots", ()) or ())
    if raw_slots:
        return [
            {
                "index": _int_attr(getattr(slot, "index", None), index),
                "name": str(getattr(slot, "name", "") or "").strip(),
                "texture": str(getattr(slot, "texture", "") or "").strip(),
            }
            for index, slot in enumerate(raw_slots)
        ]
    return [
        {
            "index": index,
            "name": str(submesh.material or submesh.name or "").strip(),
            "texture": str(submesh.texture or "").strip(),
        }
        for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ()))
    ]


def _mesh_unknown_sections_payload(mesh: ParsedMesh) -> list[dict[str, object]]:
    raw_sections = tuple(getattr(mesh, "_cdmw_mesh_asset_unknown_sections", ()) or getattr(mesh, "unknown_sections", ()) or ())
    result: list[dict[str, object]] = []
    for index, section in enumerate(raw_sections):
        if isinstance(section, dict):
            name = str(section.get("name", "") or "").strip()
            offset = _int_attr(section.get("offset", -1))
            size = _int_attr(section.get("size", 0), 0)
            section_index = _int_attr(section.get("index", index), index)
        elif isinstance(section, (list, tuple)):
            name = str(section[0] if len(section) > 0 else "").strip()
            offset = _int_attr(section[1] if len(section) > 1 else -1)
            size = _int_attr(section[2] if len(section) > 2 else 0, 0)
            section_index = _int_attr(section[3] if len(section) > 3 else index, index)
        else:
            name = str(getattr(section, "name", "") or "").strip()
            offset = _int_attr(getattr(section, "offset", -1))
            size = _int_attr(getattr(section, "size", 0), 0)
            section_index = _int_attr(getattr(section, "index", index), index)
        if offset < 0 and size <= 0 and not name:
            continue
        result.append({"name": name, "offset": offset, "size": size, "index": section_index})
    return result


def _metadata_json_safe(value: object) -> object:
    if isinstance(value, bytes):
        return {"byte_count": len(value)}
    if isinstance(value, dict):
        return {str(key): _metadata_json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_metadata_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted((_metadata_json_safe(item) for item in value), key=repr)
    return value


def _submesh_unknown_fields_payload(submesh: SubMesh) -> dict[str, object]:
    raw_fields = getattr(submesh, "unknown_fields", None)
    if not isinstance(raw_fields, dict) or not raw_fields:
        return {}
    return {"unknown_fields": _metadata_json_safe(raw_fields)}


def _submesh_source_index_map(submesh: SubMesh) -> list[int]:
    source_count = int(getattr(submesh, "source_index_count", 0) or 0)
    index_count = source_count if source_count > 0 else len(getattr(submesh, "faces", ()) or ()) * 3
    return list(range(index_count))


def _metadata_value(source: object, key: str, default: object = None) -> object:
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _int_attr(value: object, default: int = -1) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _submesh_bone_layout(submesh: SubMesh) -> dict[str, object]:
    index_rows = tuple(getattr(submesh, "bone_indices", ()) or ())
    weight_rows = tuple(getattr(submesh, "bone_weights", ()) or ())
    row_count = max(len(index_rows), len(weight_rows))
    max_influences = 0
    for row_index in range(row_count):
        index_row = index_rows[row_index] if row_index < len(index_rows) else ()
        weight_row = weight_rows[row_index] if row_index < len(weight_rows) else ()
        max_influences = max(max_influences, _bone_row_width(index_row), _bone_row_width(weight_row))
    return {
        "has_bones": max_influences > 0,
        "vertex_count": row_count,
        "max_influences": max_influences,
    }


def _bone_row_width(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, (str, bytes)):
        return 1 if value else 0
    try:
        return len(tuple(value))  # type: ignore[arg-type]
    except TypeError:
        return 1


def _submesh_raw_vertex_records_payload(submesh: SubMesh, original_data: bytes) -> dict[str, object]:
    stride = int(getattr(submesh, "source_vertex_stride", 0) or 0)
    offsets = tuple(int(value) for value in tuple(getattr(submesh, "source_vertex_offsets", ()) or ()))
    if not original_data or stride <= 0 or not offsets:
        return {}
    records = [
        original_data[offset : offset + stride]
        for offset in offsets
        if offset >= 0 and offset + stride <= len(original_data)
    ]
    if len(records) != len(offsets):
        return {}
    return {
        "raw_vertex_record_count": len(records),
        "raw_vertex_record_stride": stride,
        "raw_vertex_records_sha256": hashlib.sha256(b"".join(records)).hexdigest(),
    }


def _sidecar_source_index_map(submesh: SubMesh, asset_submesh: object | None) -> list[int]:
    raw_map = _metadata_value(asset_submesh, "source_index_map", ()) if asset_submesh is not None else ()
    if raw_map:
        return [int(value) for value in tuple(raw_map or ())]
    return _submesh_source_index_map(submesh)


def _sidecar_submesh_contract(
    lod_index: int,
    submesh_index: int,
    submesh: SubMesh,
    original_data: bytes,
    *,
    asset_submesh: object | None = None,
) -> dict[str, object]:
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    faces = tuple(getattr(submesh, "faces", ()) or ())
    source_offsets = tuple(getattr(submesh, "source_vertex_offsets", ()) or ())
    asset_vertex_offset = _int_attr(_metadata_value(asset_submesh, "original_vertex_offset"), -1)
    payload = {
        "submesh_index": submesh_index,
        "stable_id": str(_metadata_value(asset_submesh, "stable_id", "") or f"lod{lod_index}_submesh{submesh_index}"),
        "name": str(submesh.name or "").strip(),
        "material_slot_index": _int_attr(_metadata_value(asset_submesh, "material_slot_index"), submesh_index),
        "material": str(submesh.material or "").strip(),
        "texture": str(submesh.texture or "").strip(),
        "original_vertex_count": len(vertices),
        "original_index_count": len(faces) * 3,
        "original_vertex_stride": _int_attr(
            _metadata_value(asset_submesh, "original_vertex_stride"),
            int(getattr(submesh, "source_vertex_stride", 0) or 0),
        ),
        "original_vertex_offset": asset_vertex_offset if asset_vertex_offset >= 0 else (int(source_offsets[0]) if source_offsets else -1),
        "original_index_offset": _int_attr(
            _metadata_value(asset_submesh, "original_index_offset"),
            _int_attr(getattr(submesh, "source_index_offset", -1)),
        ),
        "original_descriptor_offset": _int_attr(
            _metadata_value(asset_submesh, "original_descriptor_offset"),
            _int_attr(getattr(submesh, "source_descriptor_offset", -1)),
        ),
        "source_vertex_map": _coerce_submesh_source_vertex_map(submesh),
        "source_index_map": _sidecar_source_index_map(submesh, asset_submesh),
        "bounds": _metadata_json_safe(_metadata_value(asset_submesh, "bounds")) if asset_submesh is not None else _submesh_bounds(submesh),
        "bone_layout": _submesh_bone_layout(submesh),
    }
    payload.update(_submesh_raw_vertex_records_payload(submesh, original_data))
    payload.update(_submesh_unknown_fields_payload(submesh))
    return payload


def _sidecar_lods(mesh: ParsedMesh, original_data: bytes) -> list[dict[str, object]]:
    raw_lods = tuple(getattr(mesh, "lod_levels", ()) or ())
    source_lods = raw_lods if raw_lods else (tuple(getattr(mesh, "submeshes", ()) or ()),)
    asset_lods = tuple(getattr(mesh, "_cdmw_mesh_asset_lods", ()) or ())
    payload: list[dict[str, object]] = []
    for lod_index, submeshes in enumerate(source_lods):
        asset_lod = asset_lods[lod_index] if lod_index < len(asset_lods) else None
        asset_submeshes = tuple(_metadata_value(asset_lod, "submeshes", ()) or ()) if asset_lod is not None else ()
        lod_payload = {
            "lod_index": lod_index,
            "name": str(_metadata_value(asset_lod, "name", "") or f"lod{lod_index}"),
            "original_section_offset": _int_attr(_metadata_value(asset_lod, "original_section_offset"), -1),
            "original_section_size": _int_attr(_metadata_value(asset_lod, "original_section_size"), 0),
            "bounds": _metadata_json_safe(_metadata_value(asset_lod, "bounds", _lod_bounds(submeshes))),
            "metadata": _metadata_json_safe(_metadata_value(asset_lod, "metadata", {})),
            "submeshes": [
                _sidecar_submesh_contract(
                    lod_index,
                    submesh_index,
                    submesh,
                    original_data,
                    asset_submesh=asset_submeshes[submesh_index] if submesh_index < len(asset_submeshes) else None,
                )
                for submesh_index, submesh in enumerate(tuple(submeshes or ()))
            ],
        }
        payload.append(lod_payload)
    return payload


def _sidecar_import_rules(mesh: ParsedMesh, source_identity: dict[str, object]) -> dict[str, object]:
    return {
        "allow_position_edit": True,
        "allow_normal_edit": True,
        "allow_uv_edit": True,
        "allow_topology_change": False,
        "preserve_bone_weights": any(bool(_submesh_bone_layout(submesh).get("has_bones")) for submesh in tuple(getattr(mesh, "submeshes", ()) or ())),
        "require_source_asset_hash": bool(source_identity.get("source_asset_hash")),
    }


def _roundtrip_contract_payload(mesh: ParsedMesh) -> dict[str, object]:
    original_data = _mesh_original_data(mesh)
    source_identity = _source_identity_payload(mesh)
    rules = _sidecar_import_rules(mesh, source_identity)
    return {
        "schema_version": _OBJ_ROUNDTRIP_SCHEMA_VERSION,
        "tool_version": _OBJ_ROUNDTRIP_TOOL_VERSION,
        **source_identity,
        "asset_id": _mesh_asset_id(mesh, source_identity),
        "parse_confidence": _mesh_parse_confidence(mesh),
        "skeleton_info": mesh_skinning_contract(mesh),
        "material_slots": _mesh_material_slots_payload(mesh),
        "unknown_sections": _mesh_unknown_sections_payload(mesh),
        "lods": _sidecar_lods(mesh, original_data),
        "import_rules": rules,
        "rules": rules,
        "allowed_edit_operations": list(_OBJ_ROUNDTRIP_ALLOWED_EDIT_OPERATIONS),
    }


def _roundtrip_manifest_extra_payload(mesh: ParsedMesh, extra_payload: Optional[dict]) -> dict[str, object]:
    payload = _roundtrip_contract_payload(mesh)
    if extra_payload:
        payload.update(extra_payload)
    return payload


def _build_roundtrip_manifest_payload(
    mesh: ParsedMesh,
    export_path: str,
    *,
    companion_path: str = "",
    extra_payload: Optional[dict] = None,
) -> dict:
    original_data = _mesh_original_data(mesh)
    payload = {
        "format": _OBJ_ROUNDTRIP_SIDECAR_FORMAT,
        "schema_version": _OBJ_ROUNDTRIP_SCHEMA_VERSION,
        "source_path": str(mesh.path or "").strip(),
        "source_format": str(mesh.format or "").strip(),
        "export_path": Path(export_path).name,
        "companion_filename": Path(companion_path).name if companion_path else "",
        "exported_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "roundtrip_policy": {
            "primary_workflow": "obj_first",
            "default_import_policy": "auto-fix safe, warn risky",
        },
        "submeshes": [
            {
                "index": index,
                "name": str(submesh.name or "").strip(),
                "material": str(submesh.material or "").strip(),
                "texture": str(submesh.texture or "").strip(),
                "vertex_count": len(submesh.vertices),
                "face_count": len(submesh.faces),
                "original_vertex_stride": int(getattr(submesh, "source_vertex_stride", 0) or 0),
                "source_vertex_map": _coerce_submesh_source_vertex_map(submesh),
                **_submesh_raw_vertex_records_payload(submesh, original_data),
                **_submesh_unknown_fields_payload(submesh),
            }
            for index, submesh in enumerate(mesh.submeshes)
        ],
    }
    payload.update(_roundtrip_manifest_extra_payload(mesh, extra_payload))
    return payload


def write_roundtrip_manifest(
    mesh: ParsedMesh,
    export_path: str | Path,
    *,
    companion_path: str | Path = "",
    extra_payload: Optional[dict] = None,
) -> Path:
    sidecar_path = _obj_roundtrip_sidecar_path(export_path)
    try:
        from .mesh_native_core import write_native_obj_roundtrip_manifest
    except Exception:
        write_native_obj_roundtrip_manifest = None
    if write_native_obj_roundtrip_manifest is not None:
        try:
            if write_native_obj_roundtrip_manifest(
                mesh,
                export_path,
                companion_path=companion_path,
                extra_payload=_roundtrip_manifest_extra_payload(mesh, extra_payload),
            ):
                return sidecar_path
        except Exception:
            pass
    payload = _build_roundtrip_manifest_payload(
        mesh,
        str(export_path),
        companion_path=str(companion_path or ""),
        extra_payload=extra_payload,
    )
    atomic_write_text(sidecar_path, json.dumps(payload, indent=2))
    return sidecar_path


# ═══════════════════════════════════════════════════════════════════════
#  OBJ EXPORTER
# ═══════════════════════════════════════════════════════════════════════

def _export_obj_native(
    mesh: ParsedMesh,
    obj_path: str,
    mtl_path: str,
    base: str,
    scale: float,
    *,
    manifest_path: str | Path = "",
    extra_payload: Optional[dict] = None,
) -> bool:
    try:
        from .mesh_native_core import export_native_obj
    except Exception:
        return False
    return export_native_obj(
        mesh,
        obj_path,
        base_name=base,
        mtl_filename=os.path.basename(mtl_path),
        scale=scale,
        manifest_path=manifest_path,
        extra_payload=_roundtrip_manifest_extra_payload(mesh, extra_payload),
    )


def export_obj(mesh: ParsedMesh, output_dir: str, name: str = "",
               split_submeshes: bool = False, scale: float = 1.0,
               *, extra_payload: Optional[dict] = None) -> list[str]:
    """Export mesh to OBJ + MTL files.

    Args:
        mesh: Parsed mesh data.
        output_dir: Directory to write files.
        name: Base filename (without extension). Defaults to mesh path stem.
        split_submeshes: If True, write each submesh as a separate OBJ file.
        scale: Scale factor applied to all vertices.

    Returns:
        List of output file paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    base = name or Path(mesh.path).stem

    if split_submeshes:
        return _export_obj_split(mesh, output_dir, base, scale)

    obj_path = os.path.join(output_dir, f"{base}.obj")
    mtl_path = os.path.join(output_dir, f"{base}.mtl")

    # Write MTL
    _write_mtl(mtl_path, mesh.submeshes)

    sidecar_path = _obj_roundtrip_sidecar_path(obj_path)
    native_kwargs = {} if extra_payload is None else {"extra_payload": extra_payload}
    native_exported = _export_obj_native(mesh, obj_path, mtl_path, base, scale, manifest_path=sidecar_path, **native_kwargs)
    if native_exported:
        if not sidecar_path.is_file():
            sidecar_path = write_roundtrip_manifest(mesh, obj_path, companion_path=mtl_path, extra_payload=extra_payload)
        logger.info("Exported OBJ: %s (%d verts, %d faces)", obj_path,
                    mesh.total_vertices, mesh.total_faces)
        return [obj_path, mtl_path, str(sidecar_path)]
    if not _allow_python_export_fallback(mesh, "export.obj"):
        raise RuntimeError("native OBJ export failed and Python export fallback was blocked")

    # Write OBJ
    lines = [
        f"# Crimson Desert Mesh — {base}",
        f"# {len(mesh.submeshes)} submesh(es), {mesh.total_vertices} verts, {mesh.total_faces} faces",
        "# Exported by Crimson Desert Mod Workbench",
        f"# source_path: {mesh.path}",
        f"# source_format: {mesh.format}",
        f"mtllib {os.path.basename(mtl_path)}",
        "",
    ]

    vert_offset = 1  # OBJ is 1-based
    uv_offset = 1
    normal_offset = 1

    for sm in mesh.submeshes:
        mat = sm.material or sm.name
        lines.append(f"o {sm.name}")
        lines.append(f"usemtl {mat}")

        for x, y, z in sm.vertices:
            lines.append(
                f"v {float(x * scale):.17g} {float(y * scale):.17g} {float(z * scale):.17g}"
            )

        for u, v in sm.uvs:
            lines.append(f"vt {float(u):.17g} {float(1.0 - v):.17g}")

        for nx, ny, nz in sm.normals:
            lines.append(f"vn {float(nx):.17g} {float(ny):.17g} {float(nz):.17g}")

        lines.append("s 1")

        has_uv = bool(sm.uvs)
        has_normals = bool(sm.normals)

        for a, b, c in sm.faces:
            va, vb, vc = a + vert_offset, b + vert_offset, c + vert_offset
            if has_uv and has_normals:
                ta, tb, tc = a + uv_offset, b + uv_offset, c + uv_offset
                na, nb, nc = a + normal_offset, b + normal_offset, c + normal_offset
                lines.append(f"f {va}/{ta}/{na} {vb}/{tb}/{nb} {vc}/{tc}/{nc}")
            elif has_uv:
                ta, tb, tc = a + uv_offset, b + uv_offset, c + uv_offset
                lines.append(f"f {va}/{ta} {vb}/{tb} {vc}/{tc}")
            elif has_normals:
                na, nb, nc = a + normal_offset, b + normal_offset, c + normal_offset
                lines.append(f"f {va}//{na} {vb}//{nb} {vc}//{nc}")
            else:
                lines.append(f"f {va} {vb} {vc}")

        lines.append("")
        vert_offset += len(sm.vertices)
        uv_offset += len(sm.uvs)
        normal_offset += len(sm.normals)

    atomic_write_text(obj_path, "\n".join(lines))

    sidecar_path = write_roundtrip_manifest(mesh, obj_path, companion_path=mtl_path, extra_payload=extra_payload)

    logger.info("Exported OBJ: %s (%d verts, %d faces)", obj_path,
                mesh.total_vertices, mesh.total_faces)
    return [obj_path, mtl_path, str(sidecar_path)]


def _export_obj_split(mesh, output_dir, base, scale):
    """Export each submesh as a separate OBJ file."""
    results = []
    for i, sm in enumerate(mesh.submeshes):
        sub_name = f"{base}_mesh{i:02d}"
        sub_mesh = ParsedMesh(
            path=mesh.path, format=mesh.format,
            bbox_min=mesh.bbox_min, bbox_max=mesh.bbox_max,
            submeshes=[sm],
            total_vertices=len(sm.vertices), total_faces=len(sm.faces),
            has_uvs=bool(sm.uvs),
        )
        results.extend(export_obj(sub_mesh, output_dir, sub_name, scale=scale))
    return results


def _format_mtl_texture_reference(texture_name: str) -> str:
    """Make material-library texture references friendly to OBJ/MTL readers."""
    normalized = str(texture_name or "").strip().replace("\\", "/")
    if not normalized:
        return ""
    if PurePath(normalized).suffix:
        return normalized
    return f"{normalized}.dds"


def _write_mtl(path, submeshes):
    """Write a Wavefront MTL material file."""
    seen = set()
    lines = ["# Crimson Desert Materials", ""]
    for sm in submeshes:
        n = sm.material or sm.name
        if n in seen:
            continue
        seen.add(n)
        lines.extend([
            f"newmtl {n}",
            "Ka 1.000 1.000 1.000",
            "Kd 0.800 0.800 0.800",
            "Ks 0.100 0.100 0.100",
            "Ns 50.000",
            "d 1.000",
            "illum 2",
        ])
        if sm.texture:
            texture_reference = _format_mtl_texture_reference(sm.texture)
            if texture_reference:
                lines.append(f"map_Kd {texture_reference}")
        lines.append("")

    atomic_write_text(path, "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════
#  FBX BINARY 7.4 EXPORTER
# ═══════════════════════════════════════════════════════════════════════

class _FbxId:
    """Wrapper for FBX unique IDs (always int64)."""
    def __init__(self, val): self.val = val


class _FbxBinaryArray:
    def __init__(self, descriptor: dict, kind: str):
        self.path = Path(str(descriptor.get("path") or ""))
        self.count = int(descriptor.get("count", 0) or 0)
        self.kind = kind

    def __bool__(self) -> bool:
        return self.count > 0

    @property
    def item_size(self) -> int:
        return 8 if self.kind == "d" else 4


class _NativeFbxGeometry:
    def __init__(self, temp_dir: tempfile.TemporaryDirectory, report: dict):
        self._temp_dir = temp_dir
        self._by_index: dict[int, dict[str, _FbxBinaryArray]] = {}
        for raw_item in report.get("submeshes") or ():
            if not isinstance(raw_item, dict):
                continue
            try:
                index = int(raw_item.get("index", len(self._by_index)))
                item = {
                    "vertices": _FbxBinaryArray(raw_item["vertices_binary"], "d"),
                    "indices": _FbxBinaryArray(raw_item["indices_binary"], "i"),
                    "normals": _FbxBinaryArray(raw_item["normals_binary"], "d"),
                    "uvs": _FbxBinaryArray(raw_item["uvs_binary"], "d"),
                }
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            self._by_index[index] = item

    def __bool__(self) -> bool:
        return bool(self._by_index)

    def item(self, index: int) -> dict[str, _FbxBinaryArray] | None:
        return self._by_index.get(index)

    def close(self) -> None:
        self._temp_dir.cleanup()


def _fbx_geometry_native(
    mesh: ParsedMesh,
    *,
    scale: float,
    require_vertex_aligned_uvs: bool = False,
) -> _NativeFbxGeometry | None:
    try:
        from .mesh_native_core import build_native_fbx_geometry_arrays
    except Exception:
        return None
    temp_dir = tempfile.TemporaryDirectory(prefix="cdmw_fbx_geometry_")
    report = build_native_fbx_geometry_arrays(
        mesh,
        temp_dir.name,
        scale=scale,
        require_vertex_aligned_uvs=require_vertex_aligned_uvs,
    )
    if not isinstance(report, dict):
        temp_dir.cleanup()
        return None
    native_geometry = _NativeFbxGeometry(temp_dir, report)
    if not native_geometry:
        native_geometry.close()
        return None
    return native_geometry


def _fbx_prop(v):
    """Encode a single FBX property value."""
    if isinstance(v, bool):
        return b"C" + struct.pack("B", int(v))
    if isinstance(v, _FbxId):
        return b"L" + struct.pack("<q", v.val)
    if isinstance(v, int):
        if -2147483648 <= v <= 2147483647:
            return b"I" + struct.pack("<i", v)
        return b"L" + struct.pack("<q", v)
    if isinstance(v, float):
        return b"D" + struct.pack("<d", v)
    if isinstance(v, str):
        e = v.encode("utf-8")
        return b"S" + struct.pack("<I", len(e)) + e
    if isinstance(v, bytes):
        return b"R" + struct.pack("<I", len(v)) + v
    if isinstance(v, _FbxBinaryArray):
        raw = v.path.read_bytes()
        expected_size = v.count * v.item_size
        if len(raw) != expected_size:
            raise ValueError("invalid native FBX array payload size")
        cmp = zlib.compress(raw)
        enc = 1 if len(cmp) < len(raw) else 0
        payload = cmp if enc else raw
        return v.kind.encode("ascii") + struct.pack("<III", v.count, enc, len(payload)) + payload
    if isinstance(v, list):
        if not v:
            return b"i" + struct.pack("<III", 0, 0, 0)
        if isinstance(v[0], float):
            raw = struct.pack(f"<{len(v)}d", *v)
            cmp = zlib.compress(raw)
            enc = 1 if len(cmp) < len(raw) else 0
            cl = len(cmp) if enc else len(raw)
            return b"d" + struct.pack("<III", len(v), enc, cl) + (cmp if enc else raw)
        raw = struct.pack(f"<{len(v)}i", *v)
        cmp = zlib.compress(raw)
        enc = 1 if len(cmp) < len(raw) else 0
        cl = len(cmp) if enc else len(raw)
        return b"i" + struct.pack("<III", len(v), enc, cl) + (cmp if enc else raw)
    raise TypeError(f"Unsupported FBX property type: {type(v)}")


def _fbx_node(buf: io.BytesIO, name: str, props=None, children=None):
    """Write an FBX binary node with correct absolute end offsets.

    Uses placeholder + patch approach: writes a placeholder end_offset,
    then patches it after all children are written to the same buffer.
    """
    nb = name.encode("ascii")
    props = props or []
    children = children or []

    # Serialize properties
    pb = io.BytesIO()
    for p in props:
        pb.write(_fbx_prop(p))
    pb = pb.getvalue()

    # Write node header with placeholder end_offset
    end_pos_loc = buf.tell()  # remember where end_offset is stored
    buf.write(struct.pack("<I", 0))  # placeholder — patched below
    buf.write(struct.pack("<I", len(props)))
    buf.write(struct.pack("<I", len(pb)))
    buf.write(struct.pack("B", len(nb)))
    buf.write(nb)
    buf.write(pb)

    # Write children directly to the SAME buffer (so offsets are absolute)
    for child_fn in children:
        child_fn(buf)
    if children:
        buf.write(b"\x00" * 13)  # null terminator node

    # Patch the end_offset with the actual current position
    end_offset = buf.tell()
    buf.seek(end_pos_loc)
    buf.write(struct.pack("<I", end_offset))
    buf.seek(end_offset)  # restore position


def _fbx_bone_visual_sizes(skeleton, scale: float = 1.0) -> dict[int, float]:
    """Compute FBX LimbNode Size values from child distances."""
    bones = list(getattr(skeleton, "bones", None) or [])
    if not bones:
        return {}
    abs_scale = abs(float(scale)) if abs(float(scale)) > 1e-8 else 1.0
    children_by_parent: dict[int, list[object]] = {}
    bones_by_index: dict[int, object] = {}
    for bone in bones:
        index = int(getattr(bone, "index", len(bones_by_index)) or 0)
        bones_by_index[index] = bone
        parent_index = int(getattr(bone, "parent_index", -1) or -1)
        if parent_index >= 0:
            children_by_parent.setdefault(parent_index, []).append(bone)

    sizes: dict[int, float] = {}
    for bone in bones:
        index = int(getattr(bone, "index", 0) or 0)
        position = tuple(getattr(bone, "position", ()) or (0.0, 0.0, 0.0))
        if len(position) < 3:
            continue
        distances: list[float] = []
        for child in children_by_parent.get(index, ()):
            child_position = tuple(getattr(child, "position", ()) or (0.0, 0.0, 0.0))
            if len(child_position) < 3:
                continue
            dx = float(child_position[0]) - float(position[0])
            dy = float(child_position[1]) - float(position[1])
            dz = float(child_position[2]) - float(position[2])
            distance = math.sqrt(dx * dx + dy * dy + dz * dz)
            if distance > 1e-4:
                distances.append(distance)
        if distances:
            sizes[index] = max(distances) * abs_scale

    default_leaf_size = 0.02 * abs_scale
    for bone in bones:
        index = int(getattr(bone, "index", 0) or 0)
        if index in sizes:
            continue
        parent_index = int(getattr(bone, "parent_index", -1) or -1)
        if parent_index >= 0 and parent_index in sizes:
            sizes[index] = sizes[parent_index] * 0.5
        else:
            sizes[index] = default_leaf_size

    minimum = 0.005 * abs_scale
    maximum = 2.0 * abs_scale
    return {index: max(minimum, min(float(size), maximum)) for index, size in sizes.items()}


def _export_fbx_native(mesh: ParsedMesh, fbx_path: str, base: str, scale: float, *, skeleton: object = None) -> bool:
    try:
        from .mesh_native_core import export_native_fbx
    except Exception:
        return False
    return export_native_fbx(
        mesh,
        fbx_path,
        base_name=base,
        scale=scale,
        skeleton=skeleton,
    )


def _allow_python_export_fallback(mesh: ParsedMesh, operation: str) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    try:
        from .mesh_native_core import native_mesh_core_available, record_native_mesh_core_fallback
    except Exception:
        return True
    if not native_mesh_core_available():
        return True
    vertex_count = _mesh_count_hint(mesh, "total_vertices")
    face_count = _mesh_count_hint(mesh, "total_faces")
    record_native_mesh_core_fallback(
        f"{operation}.blocked",
        "Python export fallback blocked while native mesh core is available",
        vertex_count=vertex_count,
        face_count=face_count,
    )
    return False


def _mesh_count_hint(mesh: ParsedMesh, attr: str) -> int:
    try:
        value = int(getattr(mesh, attr, 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return value if value >= 0 else 0


def export_fbx(mesh: ParsedMesh, output_dir: str, name: str = "",
               scale: float = 1.0) -> str:
    """Export mesh to binary FBX 7.4 file.

    Compatible with Blender 2.8+, Maya, 3ds Max, Unity 5+, Unreal Engine 4+.
    """
    os.makedirs(output_dir, exist_ok=True)
    base = name or Path(mesh.path).stem
    fbx_path = os.path.join(output_dir, f"{base}.fbx")

    if _export_fbx_native(mesh, fbx_path, base, scale):
        logger.info("Exported FBX: %s (%d verts, %d faces)", fbx_path,
                    mesh.total_vertices, mesh.total_faces)
        return fbx_path
    native_geometry = _fbx_geometry_native(mesh, scale=scale)
    if native_geometry is None and not _allow_python_export_fallback(mesh, "export.fbx"):
        raise RuntimeError("native FBX export failed and Python export fallback was blocked")

    buf = io.BytesIO()
    W = _fbx_node

    # Header
    buf.write(b"Kaydara FBX Binary  \x00")
    buf.write(b"\x1a\x00")
    buf.write(struct.pack("<I", 7400))  # version

    id_ctr = [3_000_000_000]

    def uid():
        id_ctr[0] += 1
        return _FbxId(id_ctr[0])

    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")

    # FBXHeaderExtension
    def header_ext(b):
        W(b, "FBXHeaderVersion", [1003])
        W(b, "FBXVersion", [7400])
        W(b, "Creator", ["Crimson Desert Mod Workbench Mesh Exporter"])

    W(buf, "FBXHeaderExtension", children=[header_ext])

    # GlobalSettings
    def global_settings(b):
        def props70(b2):
            W(b2, "P", ["UpAxis", "int", "Integer", "", 1])
            W(b2, "P", ["UpAxisSign", "int", "Integer", "", 1])
            W(b2, "P", ["FrontAxis", "int", "Integer", "", 2])
            W(b2, "P", ["FrontAxisSign", "int", "Integer", "", 1])
            W(b2, "P", ["CoordAxis", "int", "Integer", "", 0])
            W(b2, "P", ["CoordAxisSign", "int", "Integer", "", 1])
            W(b2, "P", ["UnitScaleFactor", "double", "Number", "", 1.0])
        W(b, "Properties70", children=[props70])
    W(buf, "GlobalSettings", children=[global_settings])

    # Build mesh/model/material IDs
    mesh_ids = []
    model_ids = []
    mat_ids = []
    for sm in mesh.submeshes:
        mesh_ids.append(uid())
        model_ids.append(uid())
        mat_ids.append(uid())

    root_id = uid()
    # Objects
    def objects(b):
        for idx, sm in enumerate(mesh.submeshes):
            mid = mesh_ids[idx]
            mod_id = model_ids[idx]
            ma_id = mat_ids[idx]

            # Geometry node
            native_item = native_geometry.item(idx) if native_geometry is not None else None
            if native_item is not None:
                verts_flat = native_item["vertices"]
                indices_flat = native_item["indices"]
                normals_flat = native_item["normals"]
                uvs_flat = native_item["uvs"]
                uv_indices = []
            else:
                verts_flat = []
                for x, y, z in sm.vertices:
                    verts_flat.extend([x * scale, y * scale, z * scale])

                indices_flat = []
                for a, b_idx, c in sm.faces:
                    indices_flat.extend([a, b_idx, c ^ -1])  # FBX: last index XOR -1

                normals_flat = []
                for nx, ny, nz in sm.normals:
                    normals_flat.extend([nx, ny, nz])

                uvs_flat = []
                uv_indices = []
                for i_v, (u, v) in enumerate(sm.uvs):
                    uvs_flat.extend([u, 1.0 - v])
                    uv_indices.append(i_v)

            def geom_node(b2, vf=verts_flat, iff=indices_flat, nf=normals_flat,
                          uf=uvs_flat, ui=uv_indices, sm_ref=sm, m=mid):
                def layer_elem_normal(b3, nf_=nf):
                    W(b3, "Version", [101])
                    W(b3, "Name", [""])
                    W(b3, "MappingInformationType", ["ByVertice"])
                    W(b3, "ReferenceInformationType", ["Direct"])
                    W(b3, "Normals", [nf_])

                def layer_elem_uv(b3, uf_=uf, ui_=ui):
                    W(b3, "Version", [101])
                    W(b3, "Name", ["UVMap"])
                    W(b3, "MappingInformationType", ["ByVertice"])
                    W(b3, "ReferenceInformationType", ["Direct"])
                    W(b3, "UV", [uf_])

                def layer0(b3):
                    W(b3, "Version", [100])

                    def le_normal(b4):
                        W(b4, "Type", ["LayerElementNormal"])
                        W(b4, "TypedIndex", [0])
                    W(b3, "LayerElement", children=[le_normal])

                    if uf:
                        def le_uv(b4):
                            W(b4, "Type", ["LayerElementUV"])
                            W(b4, "TypedIndex", [0])
                        W(b3, "LayerElement", children=[le_uv])

                W(b2, "Vertices", [vf])
                W(b2, "PolygonVertexIndex", [iff])

                if nf:
                    W(b2, "LayerElementNormal", [0], children=[layer_elem_normal])
                if uf:
                    W(b2, "LayerElementUV", [0], children=[layer_elem_uv])
                W(b2, "Layer", [0], children=[layer0])

            W(b, "Geometry", [mid, f"{sm.name}\x00\x01Geometry", "Mesh"],
              children=[geom_node])

            # Model node
            def model_node(b2):
                W(b2, "Version", [232])

                def props(b3):
                    W(b3, "P", ["Lcl Translation", "Lcl Translation", "", "A", 0.0, 0.0, 0.0])
                    W(b3, "P", ["Lcl Rotation", "Lcl Rotation", "", "A", 0.0, 0.0, 0.0])
                    W(b3, "P", ["Lcl Scaling", "Lcl Scaling", "", "A", 1.0, 1.0, 1.0])
                W(b2, "Properties70", children=[props])

            W(b, "Model", [mod_id, f"{sm.name}\x00\x01Model", "Mesh"],
              children=[model_node])

            # Material node
            def mat_node(b2):
                W(b2, "Version", [102])
                W(b2, "ShadingModel", ["phong"])

                def mat_props(b3):
                    W(b3, "P", ["DiffuseColor", "Color", "", "A", 0.8, 0.8, 0.8])
                W(b2, "Properties70", children=[mat_props])

            W(b, "Material", [ma_id, f"{sm.material or sm.name}\x00\x01Material", ""],
              children=[mat_node])

    try:
        W(buf, "Objects", children=[objects])
    finally:
        if native_geometry is not None:
            native_geometry.close()

    # Connections
    def connections(b):
        for idx in range(len(mesh.submeshes)):
            # Model → Root
            W(b, "C", ["OO", model_ids[idx], _FbxId(0)])
            # Geometry → Model
            W(b, "C", ["OO", mesh_ids[idx], model_ids[idx]])
            # Material → Model
            W(b, "C", ["OO", mat_ids[idx], model_ids[idx]])

    W(buf, "Connections", children=[connections])

    # Footer
    buf.write(b"\x00" * 13)  # null terminator

    # FBX footer
    buf.write(b"\xfa\xbc\xab\x09\xd0\xc8\xd4\x66\xb1\x76\xfb\x83\x1c\xf7\x26\x7e")  # padding
    buf.write(b"\x00" * 4)
    buf.write(struct.pack("<I", 7400))
    buf.write(b"\x00" * 120)
    buf.write(bytes([
        0xf8, 0x5a, 0x8c, 0x6a, 0xde, 0xf5, 0xd9, 0x7e,
        0xec, 0xe9, 0x0c, 0xe3, 0x75, 0x8f, 0x29, 0x0b,
    ]))

    atomic_write_bytes(fbx_path, buf.getvalue())

    logger.info("Exported FBX: %s (%d verts, %d faces)", fbx_path,
                mesh.total_vertices, mesh.total_faces)
    return fbx_path


def export_fbx_with_skeleton(mesh: ParsedMesh, skeleton, output_dir: str,
                              name: str = "", scale: float = 1.0) -> str:
    """Export mesh + skeleton to FBX with armature hierarchy.

    The skeleton parameter is a Skeleton object from skeleton_parser.
    Bone hierarchy is written as FBX LimbNode models connected to the
    mesh via Skin deformers. Compatible with Blender, Maya, Unity, Unreal.
    """
    from .skeleton_parser import Skeleton

    os.makedirs(output_dir, exist_ok=True)
    base = name or Path(mesh.path).stem
    fbx_path = os.path.join(output_dir, f"{base}.fbx")

    if _export_fbx_native(mesh, fbx_path, base, scale, skeleton=skeleton):
        bone_count = len(skeleton.bones) if skeleton else 0
        logger.info("Exported FBX+Skeleton: %s (%d verts, %d faces, %d bones)",
                    fbx_path, mesh.total_vertices, mesh.total_faces, bone_count)
        return fbx_path
    native_geometry = _fbx_geometry_native(mesh, scale=scale, require_vertex_aligned_uvs=True)
    if native_geometry is None and not _allow_python_export_fallback(mesh, "export.fbx_skeleton"):
        raise RuntimeError("native FBX skeleton export failed and Python export fallback was blocked")

    buf = io.BytesIO()
    W = _fbx_node

    # Header
    buf.write(b"Kaydara FBX Binary  \x00")
    buf.write(b"\x1a\x00")
    buf.write(struct.pack("<I", 7400))

    id_ctr = [3_000_000_000]
    def uid():
        id_ctr[0] += 1
        return _FbxId(id_ctr[0])

    # FBXHeaderExtension
    def header_ext(b):
        W(b, "FBXHeaderVersion", [1003])
        W(b, "FBXVersion", [7400])
        W(b, "Creator", ["Crimson Desert Mod Workbench Mesh+Skeleton Exporter"])
    W(buf, "FBXHeaderExtension", children=[header_ext])

    # GlobalSettings
    def global_settings(b):
        def props70(b2):
            W(b2, "P", ["UpAxis", "int", "Integer", "", 1])
            W(b2, "P", ["UpAxisSign", "int", "Integer", "", 1])
            W(b2, "P", ["FrontAxis", "int", "Integer", "", 2])
            W(b2, "P", ["FrontAxisSign", "int", "Integer", "", 1])
            W(b2, "P", ["CoordAxis", "int", "Integer", "", 0])
            W(b2, "P", ["CoordAxisSign", "int", "Integer", "", 1])
            W(b2, "P", ["UnitScaleFactor", "double", "Number", "", 1.0])
        W(b, "Properties70", children=[props70])
    W(buf, "GlobalSettings", children=[global_settings])

    # Build IDs
    mesh_ids, model_ids, mat_ids = [], [], []
    for sm in mesh.submeshes:
        mesh_ids.append(uid())
        model_ids.append(uid())
        mat_ids.append(uid())

    bone_model_ids = {}
    bone_attr_ids = {}
    if skeleton and skeleton.bones:
        for bone in skeleton.bones:
            bone_model_ids[bone.index] = uid()
            bone_attr_ids[bone.index] = uid()
    bone_visual_sizes = _fbx_bone_visual_sizes(skeleton, scale) if skeleton and skeleton.bones else {}

    root_id = uid()
    skin_id = uid() if skeleton and skeleton.bones else None
    # Objects
    def objects(b):
        # Mesh geometry + model + material (same as before)
        for idx, sm in enumerate(mesh.submeshes):
            mid = mesh_ids[idx]
            mod_id = model_ids[idx]
            ma_id = mat_ids[idx]

            native_item = native_geometry.item(idx) if native_geometry is not None else None
            if native_item is not None:
                verts_flat = native_item["vertices"]
                indices_flat = native_item["indices"]
                normals_flat = native_item["normals"]
                uvs_flat = native_item["uvs"]
            else:
                verts_flat = []
                for x, y, z in sm.vertices:
                    verts_flat.extend([x * scale, y * scale, z * scale])

                indices_flat = []
                for a, b_idx, c in sm.faces:
                    indices_flat.extend([a, b_idx, c ^ -1])

                normals_flat = []
                for nx, ny, nz in sm.normals:
                    normals_flat.extend([nx, ny, nz])

                uvs_flat = []
                if len(sm.uvs) == len(sm.vertices):
                    for u, v in sm.uvs:
                        uvs_flat.extend([u, 1.0 - v])

            def geom_node(b2, vf=verts_flat, iff=indices_flat, nf=normals_flat, uf=uvs_flat):
                def layer_elem_normal(b3, nf_=nf):
                    W(b3, "Version", [101])
                    W(b3, "Name", [""])
                    W(b3, "MappingInformationType", ["ByVertice"])
                    W(b3, "ReferenceInformationType", ["Direct"])
                    W(b3, "Normals", [nf_])

                def layer_elem_uv(b3, uf_=uf):
                    W(b3, "Version", [101])
                    W(b3, "Name", ["UVMap"])
                    W(b3, "MappingInformationType", ["ByVertice"])
                    W(b3, "ReferenceInformationType", ["Direct"])
                    W(b3, "UV", [uf_])

                def layer0(b3):
                    W(b3, "Version", [100])
                    def le_normal(b4):
                        W(b4, "Type", ["LayerElementNormal"])
                        W(b4, "TypedIndex", [0])
                    W(b3, "LayerElement", children=[le_normal])
                    if uf:
                        def le_uv(b4):
                            W(b4, "Type", ["LayerElementUV"])
                            W(b4, "TypedIndex", [0])
                        W(b3, "LayerElement", children=[le_uv])

                W(b2, "Vertices", [vf])
                W(b2, "PolygonVertexIndex", [iff])
                if nf:
                    W(b2, "LayerElementNormal", [0], children=[layer_elem_normal])
                if uf:
                    W(b2, "LayerElementUV", [0], children=[layer_elem_uv])
                W(b2, "Layer", [0], children=[layer0])

            W(b, "Geometry", [mid, f"{sm.name}\x00\x01Geometry", "Mesh"],
              children=[geom_node])

            def model_node(b2):
                W(b2, "Version", [232])
            W(b, "Model", [mod_id, f"{sm.name}\x00\x01Model", "Mesh"],
              children=[model_node])

            def mat_node(b2):
                W(b2, "Version", [102])
                W(b2, "ShadingModel", ["phong"])
            W(b, "Material", [ma_id, f"{sm.material or sm.name}\x00\x01Material", ""],
              children=[mat_node])

        # Bone nodes
        if skeleton and skeleton.bones:
            for bone in skeleton.bones:
                # NodeAttribute (LimbNode)
                def bone_attr(b2, bn=bone):
                    W(b2, "TypeFlags", ["Skeleton"])
                    def props(b3, size=bone_visual_sizes.get(bn.index, 0.02 * abs(float(scale) or 1.0))):
                        W(b3, "P", ["Size", "double", "Number", "", float(size)])
                    W(b2, "Properties70", children=[props])
                W(b, "NodeAttribute", [bone_attr_ids[bone.index],
                    f"{bone.name}\x00\x01NodeAttribute", "LimbNode"],
                    children=[bone_attr])

                # Model for bone
                def bone_model(b2, bn=bone):
                    W(b2, "Version", [232])
                    def props(b3, _bn=bn):
                        W(b3, "P", ["Lcl Translation", "Lcl Translation", "", "A",
                                    float(_bn.position[0] * scale),
                                    float(_bn.position[1] * scale),
                                    float(_bn.position[2] * scale)])
                    W(b2, "Properties70", children=[props])

                W(b, "Model", [bone_model_ids[bone.index],
                    f"{bone.name}\x00\x01Model", "LimbNode"],
                    children=[bone_model])

    try:
        W(buf, "Objects", children=[objects])
    finally:
        if native_geometry is not None:
            native_geometry.close()

    # Connections
    def connections(b):
        for idx in range(len(mesh.submeshes)):
            W(b, "C", ["OO", model_ids[idx], _FbxId(0)])
            W(b, "C", ["OO", mesh_ids[idx], model_ids[idx]])
            W(b, "C", ["OO", mat_ids[idx], model_ids[idx]])

        # Bone connections
        if skeleton and skeleton.bones:
            for bone in skeleton.bones:
                # NodeAttribute → Bone Model
                W(b, "C", ["OO", bone_attr_ids[bone.index], bone_model_ids[bone.index]])
                # Bone → Parent (or root)
                if bone.parent_index >= 0 and bone.parent_index in bone_model_ids:
                    W(b, "C", ["OO", bone_model_ids[bone.index],
                               bone_model_ids[bone.parent_index]])
                else:
                    W(b, "C", ["OO", bone_model_ids[bone.index], _FbxId(0)])

    W(buf, "Connections", children=[connections])

    # Footer
    buf.write(b"\x00" * 13)
    buf.write(b"\xfa\xbc\xab\x09\xd0\xc8\xd4\x66\xb1\x76\xfb\x83\x1c\xf7\x26\x7e")
    buf.write(b"\x00" * 4)
    buf.write(struct.pack("<I", 7400))
    buf.write(b"\x00" * 120)
    buf.write(bytes([
        0xf8, 0x5a, 0x8c, 0x6a, 0xde, 0xf5, 0xd9, 0x7e,
        0xec, 0xe9, 0x0c, 0xe3, 0x75, 0x8f, 0x29, 0x0b,
    ]))

    atomic_write_bytes(fbx_path, buf.getvalue())

    bone_count = len(skeleton.bones) if skeleton else 0
    logger.info("Exported FBX+Skeleton: %s (%d verts, %d faces, %d bones)",
                fbx_path, mesh.total_vertices, mesh.total_faces, bone_count)
    return fbx_path

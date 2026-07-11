"""Wavefront OBJ round-trip importer for mesh replacement flows."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Optional

from cdmw.domain.mesh.operations import (
    MeshEditOperation,
    mesh_edit_operations_to_dicts,
    validate_mesh_edit_operations,
)

from .logging import get_logger
from .mesh_parser import ParsedMesh, SubMesh, _compute_smooth_normals

logger = get_logger("core.mesh_importer")

_OBJ_ROUNDTRIP_SIDECAR_FORMATS = {"obj_meta_v1", "mesh_roundtrip_manifest_v2"}
_OBJ_ROUNDTRIP_SUPPORTED_SCHEMA_VERSION = 1


def _resolve_obj_index(raw_index: str, item_count: int) -> int:
    """Resolve a Wavefront OBJ index token to a zero-based Python index."""
    value = int(raw_index)
    if value > 0:
        return value - 1
    if value < 0:
        return item_count + value
    raise ValueError("OBJ indices are 1-based and cannot be zero")


def _obj_roundtrip_sidecar_candidates(obj_path: Path) -> tuple[Path, ...]:
    return (Path(f"{obj_path}.meta.json"),)


def _load_obj_roundtrip_sidecar(obj_path: str) -> Optional[dict[str, object]]:
    for candidate in _obj_roundtrip_sidecar_candidates(Path(obj_path)):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read OBJ round-trip sidecar %s: %s", candidate, exc)
            continue
        if not isinstance(payload, dict):
            logger.warning("Ignoring OBJ round-trip sidecar %s because it is not a JSON object.", candidate)
            continue
        payload_format = str(payload.get("format", "") or "").strip()
        if payload_format and payload_format not in _OBJ_ROUNDTRIP_SIDECAR_FORMATS:
            logger.warning(
                "Ignoring OBJ round-trip sidecar %s because it uses unsupported format %r.",
                candidate,
                payload_format,
            )
            continue
        schema_version = payload.get("schema_version")
        if schema_version is not None:
            try:
                parsed_schema_version = int(schema_version)
            except (TypeError, ValueError):
                parsed_schema_version = -1
            if parsed_schema_version != _OBJ_ROUNDTRIP_SUPPORTED_SCHEMA_VERSION:
                raise ValueError(
                    f"Unsupported OBJ sidecar schema version: {schema_version!r}."
                )
        _validate_obj_sidecar_stable_ids(payload)
        _validate_obj_sidecar_skinning_metadata(payload)
        _validate_obj_sidecar_source_index_maps(payload)
        logger.info("Loaded OBJ round-trip sidecar: %s", candidate)
        return payload
    return None


def _validate_obj_sidecar_stable_ids(payload: dict[str, object]) -> None:
    raw_lods = payload.get("lods")
    if raw_lods is None:
        return
    if not isinstance(raw_lods, list):
        raise ValueError("OBJ sidecar lods must be a list.")
    for raw_lod in raw_lods:
        if not isinstance(raw_lod, dict):
            raise ValueError("OBJ sidecar LOD entry must be an object.")
        raw_submeshes = raw_lod.get("submeshes")
        if not isinstance(raw_submeshes, list):
            raise ValueError("OBJ sidecar LOD submeshes must be a list.")
        for raw_submesh in raw_submeshes:
            if not isinstance(raw_submesh, dict):
                raise ValueError("OBJ sidecar submesh entry must be an object.")
            if not str(raw_submesh.get("stable_id", "") or "").strip():
                raise ValueError("OBJ sidecar submesh is missing stable_id.")


def _validate_obj_sidecar_skinning_metadata(payload: dict[str, object]) -> None:
    if not _obj_sidecar_declares_skinning(payload):
        return
    entries = _obj_sidecar_lod_submesh_entries(payload)
    if not entries:
        raise ValueError("OBJ sidecar bone metadata is required for skinned meshes.")
    has_bone_rows = False
    weighted_entry_count = 0
    for submesh_index, entry in enumerate(entries):
        bone_layout = entry.get("bone_layout")
        if not isinstance(bone_layout, dict) or "has_bones" not in bone_layout:
            raise ValueError("OBJ sidecar bone metadata is required for skinned meshes.")
        if not bool(bone_layout.get("has_bones")):
            continue
        has_bone_rows = True
        expected_vertices = _entry_int(entry, "original_vertex_count", "vertex_count")
        layout_vertices = _entry_int(bone_layout, "vertex_count")
        if expected_vertices >= 0 and layout_vertices != expected_vertices:
            raise ValueError(
                "OBJ sidecar bone metadata vertex count mismatch for submesh "
                f"{submesh_index}: expected {expected_vertices}, got {layout_vertices}."
            )
        max_influences = _entry_int(bone_layout, "max_influences")
        if max_influences < 0:
            raise ValueError("OBJ sidecar bone metadata is missing influence counts for skinned meshes.")
        if max_influences == 0:
            continue
        weighted_entry_count += 1
        source_map = _normalize_obj_sidecar_source_vertex_map(entry, expected_count=layout_vertices)
        if not source_map or any(value < 0 for value in source_map):
            raise ValueError("OBJ sidecar source vertex map is required for skinned meshes.")
    if has_bone_rows and weighted_entry_count <= 0:
        raise ValueError("OBJ sidecar bone metadata declares a skinned mesh but has no weighted submeshes.")

def _validate_obj_sidecar_source_index_maps(payload: dict[str, object]) -> None:
    for submesh_index, entry in enumerate(_obj_sidecar_lod_submesh_entries(payload)):
        expected_indices = _entry_int(entry, "original_index_count")
        if expected_indices < 0:
            expected_faces = _entry_int(entry, "face_count")
            expected_indices = expected_faces * 3 if expected_faces >= 0 else -1
        if expected_indices <= 0:
            continue
        raw_map = entry.get("source_index_map")
        if not isinstance(raw_map, list):
            raise ValueError("OBJ sidecar source index map is required for indexed submeshes.")
        try:
            source_index_map = [int(value) for value in raw_map]
        except (TypeError, ValueError):
            raise ValueError("OBJ sidecar source index map must contain integer entries.") from None
        if len(source_index_map) != expected_indices:
            raise ValueError(
                "OBJ sidecar source index map length mismatch for submesh "
                f"{submesh_index}: expected {expected_indices}, got {len(source_index_map)}."
            )
        if any(value < 0 or value >= expected_indices for value in source_index_map):
            raise ValueError("OBJ sidecar source index map contains an out-of-range source index.")


def _obj_sidecar_declares_skinning(payload: dict[str, object]) -> bool:
    raw_rules = payload.get("import_rules") or payload.get("rules") or {}
    if isinstance(raw_rules, dict) and bool(raw_rules.get("preserve_bone_weights")):
        return True
    skeleton_info = payload.get("skeleton_info")
    if isinstance(skeleton_info, dict) and bool(skeleton_info.get("skinned")):
        return True
    for entry in _obj_sidecar_lod_submesh_entries(payload):
        bone_layout = entry.get("bone_layout")
        if isinstance(bone_layout, dict) and bool(bone_layout.get("has_bones")):
            return True
    return False


def _obj_sidecar_lod_submesh_entries(payload: dict[str, object]) -> tuple[dict[str, object], ...]:
    entries: list[dict[str, object]] = []
    raw_lods = payload.get("lods")
    if isinstance(raw_lods, list):
        for raw_lod in raw_lods:
            if not isinstance(raw_lod, dict):
                continue
            raw_submeshes = raw_lod.get("submeshes")
            if isinstance(raw_submeshes, list):
                entries.extend(entry for entry in raw_submeshes if isinstance(entry, dict))
    return tuple(entries)


def _normalize_obj_sidecar_texture_name(sidecar_submesh_entry: object) -> str:
    if not isinstance(sidecar_submesh_entry, dict):
        return ""
    return str(sidecar_submesh_entry.get("texture", "") or "").strip()


def _obj_sidecar_original_vertex_stride(sidecar_submesh_entry: object) -> int:
    if not isinstance(sidecar_submesh_entry, dict):
        return 0
    return max(0, _entry_int(sidecar_submesh_entry, "original_vertex_stride"))


def _obj_sidecar_int(sidecar_submesh_entry: object, *keys: str) -> int:
    if not isinstance(sidecar_submesh_entry, dict):
        return -1
    return _entry_int(sidecar_submesh_entry, *keys)


def _obj_sidecar_source_vertex_offsets(sidecar_submesh_entry: object, source_vertex_map: list[int]) -> list[int]:
    first_offset = _obj_sidecar_int(sidecar_submesh_entry, "original_vertex_offset")
    stride = _obj_sidecar_original_vertex_stride(sidecar_submesh_entry)
    if first_offset < 0 or stride <= 0 or not source_vertex_map:
        return []
    return [first_offset + source_index * stride if source_index >= 0 else -1 for source_index in source_vertex_map]


def _obj_sidecar_original_index_count(sidecar_submesh_entry: object) -> int:
    count = _obj_sidecar_int(sidecar_submesh_entry, "original_index_count")
    if count >= 0:
        return count
    face_count = _obj_sidecar_int(sidecar_submesh_entry, "face_count")
    return face_count * 3 if face_count >= 0 else 0


def _attach_obj_sidecar_unknown_fields(submesh: SubMesh, sidecar_submesh_entry: object) -> None:
    if not isinstance(sidecar_submesh_entry, dict):
        return
    raw_fields = sidecar_submesh_entry.get("unknown_fields")
    if isinstance(raw_fields, dict):
        setattr(submesh, "unknown_fields", dict(raw_fields))


def _attach_obj_sidecar_lod_identity(mesh: ParsedMesh, sidecar_payload: dict[str, object] | None) -> None:
    if not isinstance(sidecar_payload, dict):
        return
    raw_lods = sidecar_payload.get("lods")
    if isinstance(raw_lods, list):
        setattr(mesh, "_cdmw_mesh_asset_lods", tuple(dict(lod) for lod in raw_lods if isinstance(lod, dict)))


def _resolve_obj_material_library_paths(obj_path: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    seen: set[str] = set()
    try:
        with obj_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line.lower().startswith("mtllib "):
                    continue
                raw_value = line[7:].strip()
                if not raw_value:
                    continue
                candidate = (obj_path.parent / raw_value).expanduser().resolve()
                lowered = str(candidate).lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                candidates.append(candidate)
    except OSError:
        return ()
    fallback_candidate = obj_path.with_suffix(".mtl").expanduser().resolve()
    fallback_key = str(fallback_candidate).lower()
    if fallback_key not in seen:
        candidates.append(fallback_candidate)
    return tuple(candidates)


def _load_obj_material_texture_map(obj_path: str) -> dict[str, str]:
    texture_by_material: dict[str, str] = {}
    for candidate in _resolve_obj_material_library_paths(Path(obj_path)):
        if not candidate.is_file():
            continue
        current_material = ""
        try:
            with candidate.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    lowered = line.lower()
                    if lowered.startswith("newmtl "):
                        current_material = line[7:].strip()
                        continue
                    if not current_material or not lowered.startswith("map_kd "):
                        continue
                    texture_value = line[7:].strip()
                    if texture_value and current_material not in texture_by_material:
                        texture_by_material[current_material] = texture_value
        except OSError as exc:
            logger.warning("Failed to read OBJ material library %s: %s", candidate, exc)
            continue
    return texture_by_material


def _normalize_obj_sidecar_source_vertex_map(
    sidecar_submesh_entry: object,
    *,
    expected_count: Optional[int] = None,
) -> list[int]:
    if not isinstance(sidecar_submesh_entry, dict):
        return []
    raw_map = sidecar_submesh_entry.get("source_vertex_map")
    if not isinstance(raw_map, list):
        return []
    normalized: list[int] = []
    for value in raw_map:
        try:
            normalized.append(int(value))
        except Exception:
            return []
    if expected_count is not None and len(normalized) != expected_count:
        return []
    return normalized


def _obj_sidecar_source_asset_hash(sidecar_payload: Optional[dict[str, object]]) -> str:
    if not isinstance(sidecar_payload, dict):
        return ""
    return str(sidecar_payload.get("source_asset_hash", "") or "").strip().lower()


def _obj_sidecar_source_asset_size(sidecar_payload: Optional[dict[str, object]]) -> int:
    if not isinstance(sidecar_payload, dict):
        return -1
    try:
        return int(sidecar_payload.get("source_asset_size", -1))
    except (TypeError, ValueError):
        return -1


def _attach_obj_sidecar_source_identity(mesh: ParsedMesh, sidecar_payload: Optional[dict[str, object]]) -> None:
    setattr(mesh, "_cdmw_imported_from_obj", True)
    setattr(mesh, "_cdmw_obj_sidecar_present", isinstance(sidecar_payload, dict))
    if isinstance(sidecar_payload, dict):
        setattr(mesh, "_cdmw_obj_sidecar_payload", dict(sidecar_payload))
        setattr(mesh, "_cdmw_sidecar_import_rules", dict(sidecar_payload.get("import_rules") or {}))
        setattr(mesh, "_cdmw_sidecar_allowed_edit_operations", tuple(sidecar_payload.get("allowed_edit_operations") or ()))
    source_hash = _obj_sidecar_source_asset_hash(sidecar_payload)
    source_size = _obj_sidecar_source_asset_size(sidecar_payload)
    if source_hash:
        setattr(mesh, "_cdmw_sidecar_source_asset_hash", source_hash)
    if source_size >= 0:
        setattr(mesh, "_cdmw_sidecar_source_asset_size", source_size)


def _attach_obj_sidecar_warnings(
    mesh: ParsedMesh,
    matched_sidecar_entries: list[Optional[dict[str, object]]],
    material_texture_map: dict[str, str],
) -> None:
    warnings: list[dict[str, object]] = []
    for submesh_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        sidecar_entry = matched_sidecar_entries[submesh_index] if submesh_index < len(matched_sidecar_entries) else None
        if not isinstance(sidecar_entry, dict):
            continue
        expected_material = str(sidecar_entry.get("material", "") or "").strip()
        actual_material = str(getattr(submesh, "material", "") or "").strip()
        if expected_material and actual_material and actual_material != expected_material:
            warnings.append(
                {
                    "code": "sidecar_material_name_changed",
                    "message": (
                        f"OBJ sidecar material changed for submesh {submesh_index}: "
                        f"expected {expected_material}, got {actual_material}."
                    ),
                    "submesh_index": submesh_index,
                    "expected": expected_material,
                    "actual": actual_material,
                    "blocks_rebuild": True,
                }
            )
        expected_texture = _normalize_obj_sidecar_texture_name(sidecar_entry)
        actual_texture = str(material_texture_map.get(actual_material, "") or "").strip()
        if expected_texture and actual_texture and _obj_texture_key(actual_texture) != _obj_texture_key(expected_texture):
            warnings.append(
                {
                    "code": "sidecar_texture_path_changed",
                    "message": (
                        f"OBJ sidecar texture changed for submesh {submesh_index}: "
                        f"expected {expected_texture}, got {actual_texture}."
                    ),
                    "submesh_index": submesh_index,
                    "expected": expected_texture,
                    "actual": actual_texture,
                    "blocks_rebuild": True,
                }
            )
    if warnings:
        setattr(mesh, "_cdmw_sidecar_warnings", tuple(warnings))


def _attach_obj_sidecar_edit_operations(
    mesh: ParsedMesh,
    matched_sidecar_entries: list[Optional[dict[str, object]]],
    sidecar_payload: Optional[dict[str, object]],
    source_name: str,
) -> None:
    operations: list[MeshEditOperation] = []
    for submesh_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        sidecar_entry = matched_sidecar_entries[submesh_index] if submesh_index < len(matched_sidecar_entries) else None
        if not isinstance(sidecar_entry, dict):
            continue
        expected_vertices = _entry_int(sidecar_entry, "original_vertex_count", "vertex_count")
        actual_vertices = len(tuple(getattr(submesh, "vertices", ()) or ()))
        if expected_vertices < 0 or actual_vertices != expected_vertices:
            continue
        operations.append(
            MeshEditOperation(
                "replace_positions_same_count",
                lod_index=0,
                submesh_index=submesh_index,
                vertex_count=actual_vertices,
                source=source_name,
            )
        )
        if len(tuple(getattr(submesh, "normals", ()) or ())) == actual_vertices:
            operations.append(
                MeshEditOperation(
                    "replace_normals_same_count",
                    lod_index=0,
                    submesh_index=submesh_index,
                    vertex_count=actual_vertices,
                    source=source_name,
                )
            )
        if len(tuple(getattr(submesh, "uvs", ()) or ())) == actual_vertices:
            operations.append(
                MeshEditOperation(
                    "replace_uv0_same_count",
                    lod_index=0,
                    submesh_index=submesh_index,
                    vertex_count=actual_vertices,
                    source=source_name,
                )
            )
    if not operations:
        return
    allowed_operations: object | None = None
    if isinstance(sidecar_payload, dict) and "allowed_edit_operations" in sidecar_payload:
        allowed_operations = sidecar_payload.get("allowed_edit_operations") or ()
    blockers = tuple(
        issue
        for issue in validate_mesh_edit_operations(
            operations,
            mesh=mesh,
            allowed_operations=allowed_operations if isinstance(allowed_operations, list | tuple | set) else None,
        )
        if issue.severity == "blocker"
    )
    if blockers:
        raise ValueError(blockers[0].message)
    setattr(mesh, "_cdmw_edit_operations", mesh_edit_operations_to_dicts(operations))


def _obj_texture_key(value: object) -> str:
    texture = Path(str(value or "").replace("\\", "/").strip()).name.casefold()
    if texture.endswith(".dds"):
        texture = texture[:-4]
    return texture


def validate_obj_sidecar_source_identity(mesh: ParsedMesh, original_data: bytes) -> None:
    if getattr(mesh, "_cdmw_imported_from_obj", False) and not getattr(mesh, "_cdmw_obj_sidecar_present", False):
        submesh_count = len(getattr(mesh, "submeshes", ()) or ())
        if submesh_count > 1 or bool(getattr(mesh, "has_bones", False)):
            raise ValueError("OBJ sidecar is required for non-trivial mesh rebuilds.")
    sidecar_payload = getattr(mesh, "_cdmw_obj_sidecar_payload", None)
    if isinstance(sidecar_payload, dict):
        _validate_obj_sidecar_topology(mesh, sidecar_payload)

    expected_size = getattr(mesh, "_cdmw_sidecar_source_asset_size", -1)
    try:
        expected_size = int(expected_size)
    except (TypeError, ValueError):
        expected_size = -1
    if expected_size >= 0 and len(original_data) != expected_size:
        raise ValueError(
            f"OBJ sidecar source size mismatch: expected {expected_size} bytes, got {len(original_data)} bytes."
        )

    expected_hash = str(getattr(mesh, "_cdmw_sidecar_source_asset_hash", "") or "").strip().lower()
    if not expected_hash:
        return
    actual_hash = hashlib.sha256(bytes(original_data or b"")).hexdigest() if original_data else ""
    if actual_hash != expected_hash:
        raise ValueError("OBJ sidecar source hash mismatch; re-export from the current source asset before rebuild.")
    if isinstance(sidecar_payload, dict):
        _validate_obj_sidecar_raw_vertex_records(sidecar_payload, bytes(original_data or b""))


def _validate_obj_sidecar_topology(mesh: ParsedMesh, sidecar_payload: dict[str, object]) -> None:
    if _obj_sidecar_allows_topology_change(sidecar_payload):
        return
    expected_entries = _obj_sidecar_topology_entries(sidecar_payload)
    if not expected_entries:
        return
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    if len(submeshes) != len(expected_entries):
        raise ValueError(
            f"OBJ sidecar topology changed: expected {len(expected_entries)} submeshes, got {len(submeshes)}."
        )
    for submesh_index, (submesh, entry) in enumerate(zip(submeshes, expected_entries)):
        expected_vertices = _entry_int(entry, "original_vertex_count", "vertex_count")
        if expected_vertices >= 0:
            actual_vertices = _effective_source_vertex_count(submesh)
            if actual_vertices != expected_vertices:
                raise ValueError(
                    "OBJ sidecar topology changed for submesh "
                    f"{submesh_index}: expected {expected_vertices} source vertices, got {actual_vertices}."
                )
        expected_indices = _entry_int(entry, "original_index_count")
        if expected_indices < 0:
            expected_faces = _entry_int(entry, "face_count")
            expected_indices = expected_faces * 3 if expected_faces >= 0 else -1
        if expected_indices >= 0:
            actual_indices = len(tuple(getattr(submesh, "faces", ()) or ())) * 3
            if actual_indices != expected_indices:
                raise ValueError(
                    "OBJ sidecar topology changed for submesh "
                    f"{submesh_index}: expected {expected_indices} indices, got {actual_indices}."
                )


def _validate_obj_sidecar_raw_vertex_records(sidecar_payload: dict[str, object], original_data: bytes) -> None:
    if not original_data:
        return
    for submesh_index, entry in enumerate(_obj_sidecar_raw_record_entries(sidecar_payload)):
        expected_count = _entry_int(entry, "raw_vertex_record_count")
        expected_hash = str(entry.get("raw_vertex_records_sha256", "") or "").strip().lower()
        if expected_count < 0 and not expected_hash:
            continue
        records = _obj_sidecar_raw_vertex_records(entry, original_data)
        if expected_count >= 0 and len(records) != expected_count:
            raise ValueError(
                "OBJ sidecar raw vertex record count mismatch for submesh "
                f"{submesh_index}: expected {expected_count}, got {len(records)}."
            )
        if expected_hash and hashlib.sha256(b"".join(records)).hexdigest() != expected_hash:
            raise ValueError(f"OBJ sidecar raw vertex records changed for submesh {submesh_index}.")


def _obj_sidecar_raw_record_entries(sidecar_payload: dict[str, object]) -> tuple[dict[str, object], ...]:
    lod_entries = _obj_sidecar_lod_submesh_entries(sidecar_payload)
    if lod_entries:
        return lod_entries
    raw_submeshes = sidecar_payload.get("submeshes")
    if isinstance(raw_submeshes, list):
        return tuple(entry for entry in raw_submeshes if isinstance(entry, dict))
    return ()


def _obj_sidecar_raw_vertex_records(entry: dict[str, object], original_data: bytes) -> list[bytes]:
    stride = _obj_sidecar_original_vertex_stride(entry)
    offsets = _obj_sidecar_source_vertex_offsets(entry, _normalize_obj_sidecar_source_vertex_map(entry))
    if stride <= 0 or not offsets:
        return []
    records: list[bytes] = []
    for offset in offsets:
        if offset < 0 or offset + stride > len(original_data):
            return []
        records.append(original_data[offset : offset + stride])
    return records


def _obj_sidecar_allows_topology_change(sidecar_payload: dict[str, object]) -> bool:
    raw_rules = sidecar_payload.get("import_rules") or sidecar_payload.get("rules") or {}
    return isinstance(raw_rules, dict) and bool(raw_rules.get("allow_topology_change"))


def _obj_sidecar_topology_entries(sidecar_payload: dict[str, object]) -> tuple[dict[str, object], ...]:
    raw_submeshes = sidecar_payload.get("submeshes")
    if isinstance(raw_submeshes, list):
        entries = tuple(entry for entry in raw_submeshes if isinstance(entry, dict))
        if entries:
            return entries
    entries: list[dict[str, object]] = []
    raw_lods = sidecar_payload.get("lods")
    if isinstance(raw_lods, list):
        for raw_lod in raw_lods:
            if not isinstance(raw_lod, dict):
                continue
            raw_lod_submeshes = raw_lod.get("submeshes")
            if isinstance(raw_lod_submeshes, list):
                entries.extend(entry for entry in raw_lod_submeshes if isinstance(entry, dict))
    return tuple(entries)


def _entry_int(entry: dict[str, object], *keys: str) -> int:
    for key in keys:
        if key not in entry:
            continue
        try:
            return int(entry.get(key))
        except (TypeError, ValueError):
            continue
    return -1


def _effective_source_vertex_count(submesh: SubMesh) -> int:
    source_map = tuple(getattr(submesh, "source_vertex_map", ()) or ())
    if source_map:
        source_vertices: set[int] = set()
        for value in source_map:
            try:
                source_index = int(value)
            except (TypeError, ValueError):
                continue
            if source_index >= 0:
                source_vertices.add(source_index)
        if source_vertices:
            return len(source_vertices)
    return len(tuple(getattr(submesh, "vertices", ()) or ()))


def _match_obj_roundtrip_sidecar_submeshes(
    sidecar_payload: Optional[dict[str, object]],
    submesh_list: list[dict],
    *,
    source_path: str,
    source_format: str,
) -> list[Optional[dict[str, object]]]:
    matched_entries: list[Optional[dict[str, object]]] = [None] * len(submesh_list)
    if not sidecar_payload:
        return matched_entries

    sidecar_source_path = str(sidecar_payload.get("source_path", "") or "").strip()
    if source_path and sidecar_source_path and sidecar_source_path != source_path:
        logger.warning(
            "Ignoring OBJ round-trip sidecar because source path mismatch: %s != %s",
            sidecar_source_path,
            source_path,
        )
        return matched_entries

    sidecar_source_format = str(sidecar_payload.get("source_format", "") or "").strip().lower()
    if source_format and sidecar_source_format and sidecar_source_format != source_format.strip().lower():
        logger.warning(
            "Ignoring OBJ round-trip sidecar because source format mismatch: %s != %s",
            sidecar_source_format,
            source_format,
        )
        return matched_entries

    raw_submeshes = sidecar_payload.get("submeshes")
    if not isinstance(raw_submeshes, list) or not raw_submeshes:
        return matched_entries

    sidecar_submeshes = [entry for entry in raw_submeshes if isinstance(entry, dict)]
    if not sidecar_submeshes:
        return matched_entries
    lod_submeshes = list(_obj_sidecar_lod_submesh_entries(sidecar_payload))
    if len(lod_submeshes) == len(sidecar_submeshes):
        sidecar_submeshes = [
            {**sidecar_submesh, **lod_submesh}
            for sidecar_submesh, lod_submesh in zip(sidecar_submeshes, lod_submeshes)
        ]

    by_name: dict[str, dict[str, object]] = {}
    for sidecar_entry in sidecar_submeshes:
        sidecar_name = str(sidecar_entry.get("name", "") or "").strip()
        if not sidecar_name or sidecar_name in by_name:
            continue
        by_name[sidecar_name] = sidecar_entry

    if len(sidecar_submeshes) == len(submesh_list):
        by_name_matches: list[Optional[dict[str, object]]] = []
        for sm_data in submesh_list:
            submesh_name = str(sm_data.get("name", "") or "").strip()
            by_name_matches.append(by_name.get(submesh_name) if submesh_name else None)
        if all(entry is not None for entry in by_name_matches):
            return [entry for entry in by_name_matches if entry is not None]
        return [entry for entry in sidecar_submeshes]

    for index, sm_data in enumerate(submesh_list):
        submesh_name = str(sm_data.get("name", "") or "").strip()
        if submesh_name and submesh_name in by_name:
            matched_entries[index] = by_name[submesh_name]
    return matched_entries


# ═══════════════════════════════════════════════════════════════════════
#  OBJ IMPORTER
# ═══════════════════════════════════════════════════════════════════════

def import_obj(obj_path: str) -> ParsedMesh:
    """Import an OBJ file back into a ParsedMesh.

    Reads OBJ round-trip metadata comments (source_path, source_format)
    to identify the original game file.

    Returns:
        ParsedMesh with vertices, UVs, normals, faces per submesh.
    """
    sidecar_payload = _load_obj_roundtrip_sidecar(obj_path)
    material_texture_map = _load_obj_material_texture_map(obj_path)
    source_path = ""
    source_format = ""
    submeshes: list[SubMesh] = []

    current_name = ""

    # Global vertex/uv/normal arrays (OBJ uses global indices)
    all_verts: list[tuple[float, float, float]] = []
    all_uvs: list[tuple[float, float]] = []
    all_normals: list[tuple[float, float, float]] = []

    # Per-submesh: track which global indices belong to each submesh
    submesh_list: list[dict] = []
    current_faces_global: list[tuple] = []
    current_material = ""
    saw_object_markers = False

    with open(obj_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            # Parse metadata comments
            if line.startswith("# source_path:"):
                source_path = line.split(":", 1)[1].strip()
                continue
            if line.startswith("# source_format:"):
                source_format = line.split(":", 1)[1].strip()
                continue
            if line.startswith("#") or not line:
                continue

            parts = line.split()
            if not parts:
                continue

            if parts[0] == "v" and len(parts) >= 4:
                all_verts.append((float(parts[1]), float(parts[2]), float(parts[3])))

            elif parts[0] == "vt" and len(parts) >= 3:
                u = float(parts[1])
                v = 1.0 - float(parts[2])  # flip V back (OBJ export flipped it)
                all_uvs.append((u, v))

            elif parts[0] == "vn" and len(parts) >= 4:
                all_normals.append((float(parts[1]), float(parts[2]), float(parts[3])))

            elif parts[0] in {"o", "g"}:
                # New object/submesh — save previous
                saw_object_markers = True
                if current_name and current_faces_global:
                    submesh_list.append({
                        "name": current_name,
                        "material": current_material,
                        "faces_global": current_faces_global,
                    })
                current_name = parts[1] if len(parts) > 1 else f"submesh_{len(submesh_list)}"
                current_faces_global = []
                current_material = ""

            elif parts[0] == "usemtl":
                current_material = parts[1] if len(parts) > 1 else ""

            elif parts[0] == "f" and len(parts) >= 4:
                if not current_name:
                    current_name = "default"
                # Parse face indices (supports v, v/vt, v/vt/vn, v//vn) and
                # triangulate polygons by fan because Blender commonly exports quads.
                face_verts = []
                for fp in parts[1:]:
                    indices = fp.split("/")
                    vi = _resolve_obj_index(indices[0], len(all_verts))
                    ti = _resolve_obj_index(indices[1], len(all_uvs)) if len(indices) > 1 and indices[1] else -1
                    ni = _resolve_obj_index(indices[2], len(all_normals)) if len(indices) > 2 and indices[2] else -1
                    face_verts.append((vi, ti, ni))
                if len(face_verts) < 3:
                    continue
                for tri_idx in range(1, len(face_verts) - 1):
                    current_faces_global.append(
                        (face_verts[0], face_verts[tri_idx], face_verts[tri_idx + 1])
                    )

    # Save last submesh
    if current_name and current_faces_global:
        submesh_list.append({
            "name": current_name,
            "material": current_material,
            "faces_global": current_faces_global,
        })

    if not submesh_list:
        raise ValueError("OBJ import did not contain any face/object data.")

    matched_sidecar_entries = _match_obj_roundtrip_sidecar_submeshes(
        sidecar_payload,
        submesh_list,
        source_path=source_path,
        source_format=source_format,
    )

    # Convert global indices to per-submesh local indices.
    # Key: keep ALL vertices in each submesh's range (not just face-referenced ones).
    # Some meshes have unused vertices that must be preserved for correct rebuild.

    def _build_generic_submesh(
        sm_data: dict,
        *,
        sidecar_entry: Optional[dict[str, object]] = None,
    ) -> SubMesh:
        vertex_key_to_local: dict[tuple[int, int, int], int] = {}
        local_verts: list[tuple[float, float, float]] = []
        local_uvs: list[tuple[float, float]] = []
        local_normals: list[tuple[float, float, float]] = []
        local_faces: list[tuple[int, int, int]] = []
        local_source_vertex_map: list[int] = []
        sidecar_source_map = _normalize_obj_sidecar_source_vertex_map(sidecar_entry)

        for face in sm_data["faces_global"]:
            local_face = []
            for vi, ti, ni in face:
                key = (vi, ti, ni)
                local_index = vertex_key_to_local.get(key)
                if local_index is None:
                    local_index = len(local_verts)
                    vertex_key_to_local[key] = local_index
                    local_verts.append(
                        all_verts[vi] if 0 <= vi < len(all_verts) else (0.0, 0.0, 0.0)
                    )
                    local_uvs.append(
                        all_uvs[ti] if 0 <= ti < len(all_uvs) else (0.0, 0.0)
                    )
                    local_normals.append(
                        all_normals[ni] if 0 <= ni < len(all_normals) else (0.0, 1.0, 0.0)
                    )
                    if sidecar_source_map and 0 <= vi < len(sidecar_source_map):
                        local_source_vertex_map.append(sidecar_source_map[vi])
                local_face.append(local_index)
            if len(local_face) == 3:
                local_faces.append(tuple(local_face))
        source_vertex_map = local_source_vertex_map if len(local_source_vertex_map) == len(local_verts) else []
        submesh = SubMesh(
            name=sm_data["name"],
            material=sm_data["material"],
            texture=_normalize_obj_sidecar_texture_name(sidecar_entry) or material_texture_map.get(sm_data["material"], ""),
            vertices=local_verts,
            uvs=local_uvs if len(local_uvs) == len(local_verts) else [],
            normals=local_normals if len(local_normals) == len(local_verts) else [],
            faces=local_faces,
            source_vertex_map=source_vertex_map,
            source_vertex_map_authority="target_donor_record" if source_vertex_map else "",
            source_vertex_offsets=_obj_sidecar_source_vertex_offsets(sidecar_entry, source_vertex_map),
            source_index_offset=_obj_sidecar_int(sidecar_entry, "original_index_offset"),
            source_index_count=_obj_sidecar_original_index_count(sidecar_entry),
            source_vertex_stride=_obj_sidecar_original_vertex_stride(sidecar_entry),
            source_descriptor_offset=_obj_sidecar_int(sidecar_entry, "original_descriptor_offset"),
            vertex_count=len(local_verts),
            face_count=len(local_faces),
        )
        _attach_obj_sidecar_unknown_fields(submesh, sidecar_entry)
        return submesh

    # Build vertex ranges from the OBJ structure:
    # Vertices between successive 'o' markers belong to that submesh
    # Re-parse to find vertex counts per submesh
    sm_vert_counts = []
    sm_uv_counts = []
    sm_normal_counts = []
    current_v = current_vt = current_vn = 0

    if saw_object_markers:
        with open(obj_path, "r", encoding="utf-8") as f:
            in_submesh = False
            for line in f:
                line = line.strip()
                if line.startswith("o ") or line.startswith("g "):
                    if in_submesh:
                        sm_vert_counts.append(current_v)
                        sm_uv_counts.append(current_vt)
                        sm_normal_counts.append(current_vn)
                    current_v = current_vt = current_vn = 0
                    in_submesh = True
                elif line.startswith("v ") and not line.startswith("vt") and not line.startswith("vn"):
                    current_v += 1
                elif line.startswith("vt "):
                    current_vt += 1
                elif line.startswith("vn "):
                    current_vn += 1
            if in_submesh:
                sm_vert_counts.append(current_v)
                sm_uv_counts.append(current_vt)
                sm_normal_counts.append(current_vn)

    # Now build each submesh using the FULL vertex range (not just face-referenced).
    # Blender may remap/deduplicate vt/vn indices independently from position indices,
    # so we must honor the face-level vi/ti/ni tuples instead of assuming vi==ti==ni.
    v_offset = 0
    vt_offset = 0
    vn_offset = 0

    for si, sm_data in enumerate(submesh_list):
        matched_sidecar_entry = matched_sidecar_entries[si] if si < len(matched_sidecar_entries) else None
        if not saw_object_markers or si >= len(sm_vert_counts):
            submeshes.append(_build_generic_submesh(sm_data, sidecar_entry=matched_sidecar_entry))
            continue

        nv = sm_vert_counts[si] if si < len(sm_vert_counts) else 0
        nvt = sm_uv_counts[si] if si < len(sm_uv_counts) else 0
        nvn = sm_normal_counts[si] if si < len(sm_normal_counts) else 0

        if nv <= 0:
            submeshes.append(_build_generic_submesh(sm_data, sidecar_entry=matched_sidecar_entry))
            continue

        # Preserve the original exported vertex slots, including any unused vertices,
        # then split only when the same position is referenced with multiple UV/normal
        # pairs after Blender re-export.
        base_verts = [
            all_verts[v_offset + i] if (v_offset + i) < len(all_verts) else (0.0, 0.0, 0.0)
            for i in range(nv)
        ]
        base_uvs = [
            all_uvs[vt_offset + i] if i < nvt and (vt_offset + i) < len(all_uvs) else (0.0, 0.0)
            for i in range(nv)
        ]
        base_normals = [
            all_normals[vn_offset + i] if i < nvn and (vn_offset + i) < len(all_normals) else (0.0, 1.0, 0.0)
            for i in range(nv)
        ]

        local_verts = list(base_verts)
        local_uvs = list(base_uvs)
        local_normals = list(base_normals)
        local_source_vertex_map = _normalize_obj_sidecar_source_vertex_map(
            matched_sidecar_entry,
            expected_count=nv,
        )

        assigned_uvs: list[tuple[float, float] | None] = [None] * nv
        assigned_normals: list[tuple[float, float, float] | None] = [None] * nv
        split_vertex_map: dict[tuple[int, int, int], int] = {}

        def _resolve_corner_index(vi: int, ti: int, ni: int) -> int:
            local_vi = vi - v_offset
            if not (0 <= local_vi < nv):
                return 0

            local_ti = ti - vt_offset if ti >= 0 else -1
            local_ni = ni - vn_offset if ni >= 0 else -1
            key = (local_vi, local_ti, local_ni)
            existing_idx = split_vertex_map.get(key)
            if existing_idx is not None:
                return existing_idx

            uv_value = (
                all_uvs[ti]
                if 0 <= ti < len(all_uvs)
                else (base_uvs[local_vi] if local_vi < len(base_uvs) else (0.0, 0.0))
            )
            normal_value = (
                all_normals[ni]
                if 0 <= ni < len(all_normals)
                else (base_normals[local_vi] if local_vi < len(base_normals) else (0.0, 1.0, 0.0))
            )

            current_uv = assigned_uvs[local_vi]
            current_normal = assigned_normals[local_vi]
            if current_uv is None and current_normal is None:
                assigned_uvs[local_vi] = uv_value
                assigned_normals[local_vi] = normal_value
                local_uvs[local_vi] = uv_value
                local_normals[local_vi] = normal_value
                split_vertex_map[key] = local_vi
                return local_vi

            if current_uv == uv_value and current_normal == normal_value:
                split_vertex_map[key] = local_vi
                return local_vi

            clone_idx = len(local_verts)
            local_verts.append(base_verts[local_vi])
            local_uvs.append(uv_value)
            local_normals.append(normal_value)
            if local_source_vertex_map and local_vi < len(local_source_vertex_map):
                local_source_vertex_map.append(local_source_vertex_map[local_vi])
            split_vertex_map[key] = clone_idx
            return clone_idx

        local_faces = []
        for face in sm_data["faces_global"]:
            local_face = []
            for vi, ti, ni in face:
                local_face.append(_resolve_corner_index(vi, ti, ni))
            if len(local_face) == 3:
                local_faces.append(tuple(local_face))

        source_vertex_map = local_source_vertex_map if len(local_source_vertex_map) == len(local_verts) else []
        sm = SubMesh(
            name=sm_data["name"],
            material=sm_data["material"],
            texture=_normalize_obj_sidecar_texture_name(matched_sidecar_entry) or material_texture_map.get(sm_data["material"], ""),
            vertices=local_verts,
            uvs=local_uvs if len(local_uvs) == len(local_verts) else [],
            normals=local_normals if len(local_normals) == len(local_verts) else [],
            faces=local_faces,
            source_vertex_map=source_vertex_map,
            source_vertex_map_authority="target_donor_record" if source_vertex_map else "",
            source_vertex_offsets=_obj_sidecar_source_vertex_offsets(matched_sidecar_entry, source_vertex_map),
            source_index_offset=_obj_sidecar_int(matched_sidecar_entry, "original_index_offset"),
            source_index_count=_obj_sidecar_original_index_count(matched_sidecar_entry),
            source_vertex_stride=_obj_sidecar_original_vertex_stride(matched_sidecar_entry),
            source_descriptor_offset=_obj_sidecar_int(matched_sidecar_entry, "original_descriptor_offset"),
            vertex_count=len(local_verts),
            face_count=len(local_faces),
        )
        _attach_obj_sidecar_unknown_fields(sm, matched_sidecar_entry)
        submeshes.append(sm)

        v_offset += nv
        vt_offset += nvt
        vn_offset += nvn

    for sm_data, submesh in zip(submesh_list, submeshes, strict=True):
        corners = [corner for face in sm_data["faces_global"] for corner in face]
        if any(not 0 <= corner[1] < len(all_uvs) for corner in corners):
            submesh.uvs = []
        if any(not 0 <= corner[2] < len(all_normals) for corner in corners):
            submesh.normals = _compute_smooth_normals(submesh.vertices, submesh.faces)

    result = ParsedMesh(
        path=source_path,
        format=source_format,
        submeshes=submeshes,
        total_vertices=sum(len(s.vertices) for s in submeshes),
        total_faces=sum(len(s.faces) for s in submeshes),
        has_uvs=any(s.uvs for s in submeshes),
    )
    _attach_obj_sidecar_source_identity(result, sidecar_payload)
    _attach_obj_sidecar_lod_identity(result, sidecar_payload)
    _attach_obj_sidecar_warnings(result, matched_sidecar_entries, material_texture_map)
    _attach_obj_sidecar_edit_operations(result, matched_sidecar_entries, sidecar_payload, Path(obj_path).name)

    if result.submeshes:
        all_v = [v for s in submeshes for v in s.vertices]
        if all_v:
            xs, ys, zs = zip(*all_v)
            result.bbox_min = (min(xs), min(ys), min(zs))
            result.bbox_max = (max(xs), max(ys), max(zs))

    logger.info("Imported OBJ %s: %d submeshes, %d verts, %d faces, source=%s (%s)",
                obj_path, len(submeshes), result.total_vertices,
                result.total_faces, source_path, source_format)
    return result

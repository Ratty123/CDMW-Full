"""Compatibility facade for mesh round-trip import and rebuild helpers."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass

from cdmw.domain.mesh.operations import (
    mesh_edit_operation_changed_channel,
    mesh_edit_operations_from_dicts,
    mesh_edit_operations_to_dicts,
    validate_mesh_edit_operation_coverage,
    validate_mesh_edit_operations,
)

from .mesh_parser import ParsedMesh, parse_pac, parse_pam, parse_pamlod
from .mesh_builder_common import (
    _align_static_vertex_sequences,
    _align_submesh_order_like_original,
    _apply_quantized_vertex_patches,
    _build_spatial_hash,
    _choose_static_donor_indices,
    _combine_static_submeshes,
    _collect_vertex_offset_refs,
    _compute_bbox,
    _expand_bbox_to_vertices,
    _make_temp_mesh,
    _make_vertex_template_record,
    _merge_partial_static_import,
    _nearby_point_indices,
    _nearest_point_index,
    _pack_static_vertex_record,
    _percentile,
    _quantize_u16,
    _replace_all_in_region,
    _reorder_submeshes_to_match_original,
    _resolve_pam_alias_vertex,
    _spatial_cell_key,
    _static_alignment_match_cost,
    _static_submesh_match_score,
    _submesh_uvs_match,
)
from .mesh_obj_importer import (
    _load_obj_material_texture_map,
    _load_obj_roundtrip_sidecar,
    _match_obj_roundtrip_sidecar_submeshes,
    _normalize_obj_sidecar_source_vertex_map,
    _normalize_obj_sidecar_texture_name,
    _obj_roundtrip_sidecar_candidates,
    _resolve_obj_index,
    _resolve_obj_material_library_paths,
    import_obj,
    validate_obj_sidecar_source_identity,
)
from .mesh_pac_builder import (
    _append_pac_cloned_descriptors,
    _build_pac_full_rebuild,
    _build_pac_in_place,
    _build_pac_output_descriptors,
    _choose_pac_donor_indices,
    _format_roundtrip_topology_error,
    _length_prefixed_ascii,
    _merge_partial_pac_import,
    _pac_descriptor_record_length,
    _pac_lod_submesh_variant,
    _pac_lod_variants_for_submesh,
    _pac_needs_full_rebuild,
    _pac_submesh_match_score,
    _pack_pac_normal,
    _patch_pac_descriptor_bounds,
    _quantize_pac_u16,
    build_pac,
)
from .mesh_pac_legacy_builder import _rebuild_pac_section0, build_pac as _legacy_build_pac
from .mesh_pam_builder import (
    _inspect_pam_layout,
    _pam_needs_full_rebuild,
    _serialize_pam_backward_scan_combined_layout,
    _serialize_pam_combined_layout,
    _serialize_pam_local_layout,
    _serialize_pam_scan_combined_layout,
    _sync_pam_geom_size_header,
    _sync_pam_header_mirrors,
    build_pam,
)
from .mesh_pamlod_builder import (
    _inspect_pamlod_lod0_layout,
    _pamlod_lod0_original_parts,
    _pamlod_needs_full_rebuild,
    _serialize_pamlod_lod0_full_rebuild,
    _split_pamlod_lod0_edit_by_entries,
    build_pamlod,
    transfer_pam_edit_to_pamlod_mesh,
)


@dataclass(frozen=True, slots=True)
class MeshRebuildReport:
    mesh_format: str
    source_asset_hash: str
    rebuilt_asset_hash: str
    source_size: int
    rebuilt_size: int
    parse_confidence: str
    validation_status: str
    byte_identical: bool
    changed_byte_ranges: tuple[tuple[int, int], ...]
    edited_lods: tuple[int, ...] = ()
    edited_submeshes: tuple[str, ...] = ()
    changed_channels: tuple[str, ...] = ()
    recomputed_fields: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    developer_overrides: tuple[str, ...] = ()
    edit_operations: tuple[dict[str, object], ...] = ()
    output_path: str = ""

    @property
    def changed_range_count(self) -> int:
        return len(self.changed_byte_ranges)


@dataclass(frozen=True, slots=True)
class MeshRebuildResult:
    data: bytes
    report: MeshRebuildReport


def build_mesh(mesh: ParsedMesh, original_data: bytes) -> bytes:
    """Auto-detect format and rebuild binary from modified mesh."""
    return _build_mesh_bytes(mesh, original_data)


def rebuild_mesh_with_report(
    mesh: ParsedMesh,
    original_data: bytes,
    *,
    validation_status: str = "not_run",
    output_path: str = "",
) -> MeshRebuildResult:
    """Rebuild mesh bytes and return the structured binary-diff report."""
    fmt, rebuild_mesh, original_mesh = _prepare_mesh_for_rebuild(mesh, original_data)
    rebuilt = original_data if original_mesh is not None and _mesh_matches_no_edit(original_mesh, rebuild_mesh) else _build_prepared_mesh_bytes(fmt, rebuild_mesh, original_data)
    return MeshRebuildResult(
        data=rebuilt,
        report=_build_rebuild_report(
            rebuild_mesh,
            original_data,
            rebuilt,
            validation_status=validation_status,
            output_path=output_path,
        ),
    )


def _build_mesh_bytes(mesh: ParsedMesh, original_data: bytes) -> bytes:
    fmt, rebuild_mesh, original_mesh = _prepare_mesh_for_rebuild(mesh, original_data)
    if original_mesh is not None and _mesh_matches_no_edit(original_mesh, rebuild_mesh):
        return original_data
    return _build_prepared_mesh_bytes(fmt, rebuild_mesh, original_data)


def _prepare_mesh_for_rebuild(mesh: ParsedMesh, original_data: bytes) -> tuple[str, ParsedMesh, ParsedMesh | None]:
    fmt = mesh.format.lower()
    validate_obj_sidecar_source_identity(mesh, original_data)
    _validate_mesh_rebuild_sidecar_warnings(mesh)
    try:
        original_mesh = _parse_original_mesh_for_no_edit(fmt, original_data, mesh.path)
    except Exception:
        original_mesh = None
    if original_mesh is not None:
        _validate_mesh_rebuild_operations(mesh, original_mesh=original_mesh)
        return fmt, _apply_operation_channels_to_original(original_mesh, mesh), original_mesh
    else:
        _validate_mesh_rebuild_operations(mesh, original_mesh=None)
        return fmt, mesh, None


def _build_prepared_mesh_bytes(fmt: str, mesh: ParsedMesh, original_data: bytes) -> bytes:
    try:
        from cdmw.core.mesh_native import build_mesh_native

        native_data = build_mesh_native(mesh, original_data)
        if native_data is not None:
            if fmt == "pac":
                parsed_native = parse_pac(native_data, mesh.path)
            elif fmt == "pam":
                parsed_native = parse_pam(native_data, mesh.path)
            elif fmt == "pamlod":
                parsed_native = parse_pamlod(native_data, mesh.path)
            else:
                parsed_native = None
            if parsed_native is None or len(parsed_native.submeshes) != len(mesh.submeshes):
                native_data = None
        if native_data is not None:
            return native_data
    except Exception:
        pass
    if fmt == "pac":
        return build_pac(mesh, original_data)
    if fmt == "pam":
        return build_pam(mesh, original_data)
    if fmt == "pamlod":
        return build_pamlod(mesh, original_data)
    raise ValueError(f"Unsupported mesh format for rebuild: {fmt}")


def _build_rebuild_report(
    mesh: ParsedMesh,
    original_data: bytes,
    rebuilt_data: bytes,
    *,
    validation_status: str,
    output_path: str,
) -> MeshRebuildReport:
    fmt = str(mesh.format or "").lower()
    changed_ranges = _diff_byte_ranges(original_data, rebuilt_data)
    original_mesh = _parse_original_mesh_for_report(fmt, original_data, mesh.path)
    edited_lods, edited_submeshes, changed_channels = _merge_mesh_scopes(
        _changed_mesh_scope(original_mesh, mesh),
        _operation_mesh_scope(mesh),
    )
    return MeshRebuildReport(
        mesh_format=fmt,
        source_asset_hash=_sha256(original_data),
        rebuilt_asset_hash=_sha256(rebuilt_data),
        source_size=len(original_data),
        rebuilt_size=len(rebuilt_data),
        parse_confidence=_parse_confidence(mesh, original_data),
        validation_status=str(validation_status or "not_run"),
        byte_identical=not changed_ranges,
        changed_byte_ranges=changed_ranges,
        edited_lods=edited_lods,
        edited_submeshes=edited_submeshes,
        changed_channels=changed_channels,
        edit_operations=_mesh_edit_operation_payloads(mesh),
        output_path=str(output_path or ""),
    )


def _validate_mesh_rebuild_operations(mesh: ParsedMesh, *, original_mesh: ParsedMesh | None) -> None:
    operations = mesh_edit_operations_from_dicts(getattr(mesh, "_cdmw_edit_operations", ()) or ())
    if not operations:
        if bool(getattr(mesh, "_cdmw_imported_from_obj", False)) and bool(getattr(mesh, "_cdmw_obj_sidecar_present", False)):
            raise ValueError("Imported OBJ sidecar rebuild requires explicit Mesh Editor v2 edit operations.")
        return
    allowed_operations = getattr(mesh, "_cdmw_sidecar_allowed_edit_operations", None)
    issues = validate_mesh_edit_operations(
        operations,
        mesh=mesh,
        allowed_operations=allowed_operations if allowed_operations is not None else None,
    )
    if original_mesh is not None:
        issues += validate_mesh_edit_operation_coverage(operations, mesh=mesh, original_mesh=original_mesh)
    blockers = tuple(issue for issue in issues if issue.severity == "blocker")
    if blockers:
        raise ValueError(f"Mesh edit operation blocked rebuild: {blockers[0].message}")


def _apply_operation_channels_to_original(original_mesh: ParsedMesh, edited_mesh: ParsedMesh) -> ParsedMesh:
    operations = mesh_edit_operations_from_dicts(getattr(edited_mesh, "_cdmw_edit_operations", ()) or ())
    if not operations:
        return edited_mesh
    rebuilt = copy.deepcopy(original_mesh)
    _copy_cdmw_attrs(edited_mesh, rebuilt)
    rebuilt.path = str(edited_mesh.path or rebuilt.path or "")
    rebuilt.format = str(edited_mesh.format or rebuilt.format or "")
    for operation in operations:
        channel = mesh_edit_operation_changed_channel(operation.operation)
        if not channel or channel == "visibility":
            continue
        source = _operation_target_submesh(edited_mesh, operation.lod_index, operation.submesh_index)
        target = _operation_target_submesh(rebuilt, operation.lod_index, operation.submesh_index)
        if source is None or target is None:
            continue
        _copy_operation_channel(source, target, channel)
    _refresh_mesh_counts(rebuilt)
    return rebuilt


def apply_operation_channels_to_original(original_mesh: ParsedMesh, edited_mesh: ParsedMesh) -> ParsedMesh:
    return _apply_operation_channels_to_original(original_mesh, edited_mesh)


def _copy_cdmw_attrs(source: ParsedMesh, target: ParsedMesh) -> None:
    for name, value in vars(source).items():
        if name.startswith("_cdmw_"):
            setattr(target, name, copy.deepcopy(value))


def _operation_target_submesh(mesh: ParsedMesh, lod_index: int, submesh_index: int) -> object | None:
    if submesh_index < 0:
        return None
    lod_levels = getattr(mesh, "lod_levels", None) or []
    if lod_levels:
        if not 0 <= lod_index < len(lod_levels):
            return None
        lod_submeshes = lod_levels[lod_index] or []
        return lod_submeshes[submesh_index] if 0 <= submesh_index < len(lod_submeshes) else None
    submeshes = getattr(mesh, "submeshes", None) or []
    return submeshes[submesh_index] if 0 <= submesh_index < len(submeshes) else None


def _copy_operation_channel(source: object, target: object, channel: str) -> None:
    if channel == "positions":
        target.vertices = copy.deepcopy(getattr(source, "vertices", []) or [])
    elif channel == "normals":
        target.normals = copy.deepcopy(getattr(source, "normals", []) or [])
    elif channel == "tangents":
        target.tangents = copy.deepcopy(getattr(source, "tangents", []) or [])
    elif channel == "uv0":
        target.uvs = copy.deepcopy(getattr(source, "uvs", []) or [])
    elif channel == "bounds":
        target.source_bbox_min = tuple(getattr(source, "source_bbox_min", ()) or getattr(target, "source_bbox_min", ()))
        target.source_bbox_extent = tuple(getattr(source, "source_bbox_extent", ()) or getattr(target, "source_bbox_extent", ()))


def _refresh_mesh_counts(mesh: ParsedMesh) -> None:
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        submesh.vertex_count = len(getattr(submesh, "vertices", ()) or ())
        submesh.face_count = len(getattr(submesh, "faces", ()) or ())
    mesh.total_vertices = sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in tuple(getattr(mesh, "submeshes", ()) or ()))
    mesh.total_faces = sum(len(getattr(submesh, "faces", ()) or ()) for submesh in tuple(getattr(mesh, "submeshes", ()) or ()))
    mesh.has_uvs = any(bool(getattr(submesh, "uvs", ()) or ()) for submesh in tuple(getattr(mesh, "submeshes", ()) or ()))
    mesh.has_bones = any(
        bool(getattr(submesh, "bone_indices", ()) or ()) or bool(getattr(submesh, "bone_weights", ()) or ())
        for submesh in tuple(getattr(mesh, "submeshes", ()) or ())
    )


def _validate_mesh_rebuild_sidecar_warnings(mesh: ParsedMesh) -> None:
    for warning in tuple(getattr(mesh, "_cdmw_sidecar_warnings", ()) or ()):
        if not isinstance(warning, dict) or not bool(warning.get("blocks_rebuild")):
            continue
        message = str(warning.get("message") or "Sidecar metadata changed.").strip()
        raise ValueError(f"Mesh sidecar metadata drift blocked rebuild: {message}")


def _mesh_edit_operation_payloads(mesh: ParsedMesh) -> tuple[dict[str, object], ...]:
    operations = mesh_edit_operations_from_dicts(getattr(mesh, "_cdmw_edit_operations", ()) or ())
    return mesh_edit_operations_to_dicts(operations)


def _parse_original_mesh_for_no_edit(fmt: str, original_data: bytes, path: str) -> ParsedMesh | None:
    if fmt == "pac":
        return parse_pac(original_data, path)
    if fmt == "pam":
        return parse_pam(original_data, path)
    if fmt == "pamlod":
        return parse_pamlod(original_data, path)
    return None


def _parse_original_mesh_for_report(fmt: str, original_data: bytes, path: str) -> ParsedMesh | None:
    try:
        return _parse_original_mesh_for_no_edit(fmt, original_data, path)
    except Exception:
        return None


def _mesh_matches_no_edit(original: ParsedMesh, edited: ParsedMesh) -> bool:
    return (
        str(original.format or "").lower() == str(edited.format or "").lower()
        and list(original.submeshes or []) == list(edited.submeshes or [])
        and list(original.lod_levels or []) == list(edited.lod_levels or [])
        and int(original.total_vertices or 0) == int(edited.total_vertices or 0)
        and int(original.total_faces or 0) == int(edited.total_faces or 0)
        and bool(original.has_uvs) == bool(edited.has_uvs)
        and bool(original.has_bones) == bool(edited.has_bones)
    )


def _diff_byte_ranges(original_data: bytes, rebuilt_data: bytes) -> tuple[tuple[int, int], ...]:
    from .mesh_roundtrip import diff_byte_ranges

    return tuple((int(start), int(end)) for start, end in diff_byte_ranges(original_data, rebuilt_data))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_confidence(mesh: ParsedMesh, original_data: bytes) -> str:
    raw = str(getattr(mesh, "_cdmw_mesh_asset_parse_confidence", "") or "").strip()
    if raw:
        return raw
    try:
        from .mesh_asset import mesh_asset_from_parsed_mesh

        return mesh_asset_from_parsed_mesh(mesh, original_data).parse_confidence
    except Exception:
        return ""


def _changed_mesh_scope(
    original: ParsedMesh | None,
    edited: ParsedMesh,
) -> tuple[tuple[int, ...], tuple[str, ...], tuple[str, ...]]:
    if original is None:
        return (), (), ()
    edited_lods: set[int] = set()
    edited_submeshes: set[str] = set()
    changed_channels: set[str] = set()
    original_lods = _submeshes_by_lod(original)
    updated_lods = _submeshes_by_lod(edited)
    for lod_index in range(max(len(original_lods), len(updated_lods))):
        original_submeshes = original_lods[lod_index] if lod_index < len(original_lods) else ()
        updated_submeshes = updated_lods[lod_index] if lod_index < len(updated_lods) else ()
        if len(original_submeshes) != len(updated_submeshes):
            edited_lods.add(lod_index)
            changed_channels.add("submesh_count")
        for submesh_index in range(max(len(original_submeshes), len(updated_submeshes))):
            before = original_submeshes[submesh_index] if submesh_index < len(original_submeshes) else None
            after = updated_submeshes[submesh_index] if submesh_index < len(updated_submeshes) else None
            changes = _changed_submesh_channels(before, after)
            if not changes:
                continue
            edited_lods.add(lod_index)
            edited_submeshes.add(_submesh_stable_id(lod_index, submesh_index, after or before))
            changed_channels.update(changes)
    return tuple(sorted(edited_lods)), tuple(sorted(edited_submeshes)), tuple(sorted(changed_channels))


def _operation_mesh_scope(mesh: ParsedMesh) -> tuple[tuple[int, ...], tuple[str, ...], tuple[str, ...]]:
    operations = mesh_edit_operations_from_dicts(getattr(mesh, "_cdmw_edit_operations", ()) or ())
    if not operations:
        return (), (), ()
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    edited_lods: set[int] = set()
    edited_submeshes: set[str] = set()
    changed_channels: set[str] = set()
    for operation in operations:
        channel = _operation_changed_channel(operation.operation)
        if not channel:
            continue
        lod_index = max(0, int(operation.lod_index or 0))
        edited_lods.add(lod_index)
        changed_channels.add(channel)
        submesh_index = int(operation.submesh_index)
        if 0 <= submesh_index < len(submeshes):
            edited_submeshes.add(_submesh_stable_id(lod_index, submesh_index, submeshes[submesh_index]))
    return tuple(sorted(edited_lods)), tuple(sorted(edited_submeshes)), tuple(sorted(changed_channels))


def _merge_mesh_scopes(
    *scopes: tuple[tuple[int, ...], tuple[str, ...], tuple[str, ...]]
) -> tuple[tuple[int, ...], tuple[str, ...], tuple[str, ...]]:
    edited_lods: set[int] = set()
    edited_submeshes: set[str] = set()
    changed_channels: set[str] = set()
    for lods, submeshes, channels in scopes:
        edited_lods.update(int(value) for value in lods)
        edited_submeshes.update(str(value) for value in submeshes if str(value))
        changed_channels.update(str(value) for value in channels if str(value))
    return tuple(sorted(edited_lods)), tuple(sorted(edited_submeshes)), tuple(sorted(changed_channels))


def _operation_changed_channel(operation: str) -> str:
    return mesh_edit_operation_changed_channel(operation)


def _submeshes_by_lod(mesh: ParsedMesh) -> tuple[tuple[object, ...], ...]:
    lod_levels = tuple(getattr(mesh, "lod_levels", ()) or ())
    if lod_levels:
        return tuple(tuple(level or ()) for level in lod_levels)
    return (tuple(getattr(mesh, "submeshes", ()) or ()),)


def _changed_submesh_channels(before: object | None, after: object | None) -> tuple[str, ...]:
    if before is None or after is None:
        return ("topology",)
    fields = (
        ("vertices", "positions"),
        ("normals", "normals"),
        ("tangents", "tangents"),
        ("uvs", "uv0"),
        ("faces", "indices"),
        ("bone_indices", "bone_indices"),
        ("bone_weights", "bone_weights"),
    )
    changed = [
        channel
        for attr, channel in fields
        if tuple(getattr(before, attr, ()) or ()) != tuple(getattr(after, attr, ()) or ())
    ]
    if str(getattr(before, "material", "") or "") != str(getattr(after, "material", "") or ""):
        changed.append("material")
    if str(getattr(before, "texture", "") or "") != str(getattr(after, "texture", "") or ""):
        changed.append("texture")
    if int(getattr(before, "vertex_count", 0) or 0) != int(getattr(after, "vertex_count", 0) or 0):
        changed.append("vertex_count")
    if int(getattr(before, "face_count", 0) or 0) != int(getattr(after, "face_count", 0) or 0):
        changed.append("index_count")
    return tuple(changed)


def _submesh_stable_id(lod_index: int, submesh_index: int, submesh: object | None) -> str:
    raw = str(getattr(submesh, "stable_id", "") or "").strip() if submesh is not None else ""
    return raw or f"lod{lod_index}_submesh{submesh_index}"

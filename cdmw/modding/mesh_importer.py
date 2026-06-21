"""Compatibility facade for mesh round-trip import and rebuild helpers."""

from __future__ import annotations

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


def build_mesh(mesh: ParsedMesh, original_data: bytes) -> bytes:
    """Auto-detect format and rebuild binary from modified mesh."""
    fmt = mesh.format.lower()
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

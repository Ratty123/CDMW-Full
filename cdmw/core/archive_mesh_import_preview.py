"""Compatibility surface for mesh-import preview preparation."""

from __future__ import annotations

from cdmw.core.archive_mesh_import_build import build_mesh_import_preview
from cdmw.core.archive_mesh_import_generated_textures import (
    _apply_generated_static_texture_previews,
    _generated_texture_preview_file,
    _texture_replacement_payloads_to_specs,
)
from cdmw.core.archive_mesh_import_local_textures import (
    _apply_mesh_import_local_sidecar_texture_overrides,
    _apply_mesh_import_local_support_texture_overrides,
    _apply_mesh_import_local_texture_overrides,
    _build_mesh_import_local_dds_lookup,
    _merge_sidecar_text_maps,
    _mesh_import_candidate_virtual_paths,
    _mesh_import_loose_texture_preferred_paths,
    _mesh_import_modelproperty_variant,
    _mesh_import_sidecar_preferred_paths,
    _mesh_import_target_sidecar_candidates_for_base,
    _resolve_supplemental_target_entry,
)
from cdmw.core.archive_mesh_import_scene_preview import (
    _preview_meshes_from_submeshes,
    _restore_rebuilt_mesh_texture_identity,
    attach_scene_preview_textures,
    build_mesh_preview_from_bytes,
    parsed_mesh_to_preview_model,
)
from cdmw.core.archive_mesh_import_supplemental import (
    _align_source_owned_target_names_to_mesh,
    _build_mesh_import_supplemental_file_specs,
    _build_selected_sidecar_texture_bindings,
    _collect_original_mesh_sidecar_texts,
    _decode_text_payload,
    _find_first_archive_entry_by_virtual_path,
    _mesh_import_normalize_runtime_stem_candidate,
    _mesh_import_runtime_mesh_paths_from_sidecars,
    _mesh_import_runtime_sibling_mesh_candidates,
    _mesh_import_runtime_sibling_warning_lines,
    _mesh_import_runtime_stem_candidates_from_mesh,
    _mesh_import_runtime_stem_candidates_from_sidecars,
    _mesh_texture_original_bytes,
    _mesh_texture_original_source_path,
    _source_owned_sidecar_name_is_helper_row,
    _source_owned_sidecar_name_key,
    _source_owned_target_names_from_sidecars,
    _summarize_crimson_companion_supplemental_files,
    mesh_import_runtime_sibling_mesh_candidates,
)
from cdmw.core.archive_mesh_import_validation import (
    _build_mesh_import_validation,
    _build_selected_sidecar_target_overrides,
    _build_sidecar_binding_validation,
    _describe_sidecar_binding_locator,
    _iter_normalized_sidecar_binding_records,
    _normalize_import_binding_token,
    _normalize_import_lookup_path,
    _summarize_import_values,
)
from cdmw.core.archive_mesh_types import MeshImportPreviewResult, MeshImportSupplementalFileSpec
from cdmw.core.archive_patching import _normalize_virtual_path
from cdmw.core.mesh_baseline import read_archive_entry_baseline_data
from cdmw.modding.material_replacer import TextureReplacementPayload, build_texture_replacement_payloads
from cdmw.modding.mesh_importer import (
    _load_obj_roundtrip_sidecar,
    build_mesh,
    transfer_pam_edit_to_pamlod_mesh,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_mesh
from cdmw.modding.scene_importer import (
    SCENE_TEXTURE_SOURCE_EXTENSIONS,
    SceneImportResult,
    discover_scene_texture_files,
    import_scene_mesh_with_report,
)
from cdmw.modding.static_mesh_replacer import (
    StaticMeshReplacementOptions,
    build_static_mesh_replacement,
    effective_static_replacement_source_mesh,
    suggest_static_submesh_mappings,
)

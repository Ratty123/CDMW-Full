"""Explicit UI-facing mesh workflow service surface."""

from __future__ import annotations


MESH_WORKFLOW_EXPORTS: dict[str, tuple[str, str]] = {
    # Native session, sparse edit, and preview operations.
    name: ("cdmw.modding.mesh_native_core", name)
    for name in (
        "_ensure_native_mesh_session_submesh",
        "_native_preview_delta_output_path",
        "apply_native_mesh_affine_transform_submeshes",
        "apply_native_mesh_recalculate_normals",
        "apply_native_mesh_selection",
        "apply_native_mesh_sparse_vertex_restore",
        "build_native_mesh_preview_triangle_groups",
        "build_native_mesh_preview_vertex_update_groups",
        "build_native_mesh_selection_groups",
        "build_native_morph_post_edit_deltas",
        "build_native_preview_model_in_original_frame",
        "clone_native_mesh_affine_transformed_submesh",
        "dispose_native_mesh_sparse_vertex_snapshot",
        "dispose_native_mesh_submesh_snapshot",
        "invalidate_native_mesh_session_submeshes",
        "prune_native_mesh_selection",
        "record_native_mesh_core_fallback",
        "restore_native_mesh_submesh_snapshot",
        "restore_native_mesh_submeshes_from_mesh",
        "snapshot_native_mesh_sparse_vertex_positions",
        "snapshot_native_mesh_submeshes",
        "summarize_native_mesh_selection_bounds",
        "summarize_native_mesh_submesh_metadata",
        "write_native_pose_preview_geometry_blob",
        "write_native_preview_geometry_blob",
    )
}
MESH_WORKFLOW_EXPORTS.update(
    {
        name: ("cdmw.modding.mesh_native_availability", name)
        for name in ("find_native_mesh_core_binary", "native_mesh_core_available")
    }
)
MESH_WORKFLOW_EXPORTS.update(
    {
        name: ("cdmw.modding.static_mesh_replacer", name)
        for name in (
            "StaticDonorMaterialPlan",
            "StaticDonorMaterialTextureBinding",
            "StaticIndependentPart",
            "StaticMeshReplacementOptions",
            "StaticOriginalPartCopy",
            "StaticReplacementTransform",
            "StaticSourceMaterialTextureOverride",
            "StaticSourcePartAdjustment",
            "StaticSubmeshMapping",
            "StaticTextureSlotOverride",
            "StaticTextureUvTransform",
            "_compute_anchor_alignment",
            "_normalize",
            "_rotate_xyz",
            "_semantic_tokens",
            "_transformed_replacement_sources",
            "build_static_replacement_preview_mesh",
            "describe_static_placement_context",
            "infer_static_replacement_part_role",
            "source_affine_for_transformed_preview",
            "source_normal_transform_for_transformed_preview",
            "suggest_static_submesh_mappings",
        )
    }
)
MESH_WORKFLOW_EXPORTS.update(
    {
        "ParsedMesh": ("cdmw.modding.mesh_parser", "ParsedMesh"),
        "parse_mesh": ("cdmw.modding.mesh_parser", "parse_mesh"),
        "SCENE_IMPORT_EXTENSIONS": ("cdmw.modding.scene_importer", "SCENE_IMPORT_EXTENSIONS"),
        "SCENE_TEXTURE_SOURCE_EXTENSIONS": ("cdmw.modding.scene_importer", "SCENE_TEXTURE_SOURCE_EXTENSIONS"),
        "SceneImportResult": ("cdmw.modding.scene_importer", "SceneImportResult"),
        "append_scene_import_to_mesh": ("cdmw.modding.scene_importer", "append_scene_import_to_mesh"),
        "discover_scene_texture_files": ("cdmw.modding.scene_importer", "discover_scene_texture_files"),
        "flatten_scene_import_result_parts": ("cdmw.modding.scene_importer", "flatten_scene_import_result_parts"),
        "group_scene_import_result_parts_by_material": ("cdmw.modding.scene_importer", "group_scene_import_result_parts_by_material"),
        "import_scene_mesh": ("cdmw.modding.scene_importer", "import_scene_mesh"),
        "import_scene_mesh_with_report": ("cdmw.modding.scene_importer", "import_scene_mesh_with_report"),
        "reduce_scene_import_result_quality": ("cdmw.modding.scene_importer", "reduce_scene_import_result_quality"),
        "refresh_parsed_mesh_totals": ("cdmw.modding.scene_import_result_ops", "refresh_parsed_mesh_totals"),
        "ReplacementAssetProfile": ("cdmw.modding.asset_replacement", "ReplacementAssetProfile"),
        "analyze_replacement_asset": ("cdmw.modding.asset_replacement", "analyze_replacement_asset"),
        "classify_texture_binding": ("cdmw.modding.asset_replacement", "classify_texture_binding"),
        "ReplacementTextureSet": ("cdmw.modding.material_replacer", "ReplacementTextureSet"),
        "ReplacementTextureSlot": ("cdmw.modding.material_replacer", "ReplacementTextureSlot"),
        "SidecarPatchPlan": ("cdmw.modding.material_replacer", "SidecarPatchPlan"),
        "_apply_source_part_role_overrides": ("cdmw.modding.material_replacer", "_apply_source_part_role_overrides"),
        "apply_true_source_basic_controls_to_profile": ("cdmw.modding.material_replacer", "apply_true_source_basic_controls_to_profile"),
        "build_source_material_routing_plan": ("cdmw.modding.material_replacer", "build_source_material_routing_plan"),
        "classify_texture_assignment_guidance": ("cdmw.modding.material_replacer", "classify_texture_assignment_guidance"),
        "complete_swap_material_profile_to_dict": ("cdmw.modding.material_replacer", "complete_swap_material_profile_to_dict"),
        "complete_swap_material_runtime_profiles": ("cdmw.modding.material_replacer", "complete_swap_material_runtime_profiles"),
        "get_complete_swap_material_profile": ("cdmw.modding.material_replacer", "get_complete_swap_material_profile"),
        "group_replacement_texture_sets": ("cdmw.modding.material_replacer", "group_replacement_texture_sets"),
        "is_shared_material_layer_texture": ("cdmw.modding.material_replacer", "is_shared_material_layer_texture"),
        "material_authority_preview_texture_slots": ("cdmw.modding.material_replacer", "material_authority_preview_texture_slots"),
        "patch_material_sidecar_text": ("cdmw.modding.material_replacer", "patch_material_sidecar_text"),
        "read_complete_swap_calibrated_material_profile": ("cdmw.modding.material_replacer", "read_complete_swap_calibrated_material_profile"),
        "replacement_texture_slot_preview_semantics": ("cdmw.modding.material_replacer", "replacement_texture_slot_preview_semantics"),
        "serialize_complete_swap_manual_material_profile": ("cdmw.modding.material_replacer", "serialize_complete_swap_manual_material_profile"),
        "write_complete_swap_calibrated_material_profile": ("cdmw.modding.material_replacer", "write_complete_swap_calibrated_material_profile"),
        "assert_mesh_topology_unchanged": ("cdmw.modding.mesh_deformer", "assert_mesh_topology_unchanged"),
        "clone_mesh_for_editing": ("cdmw.modding.mesh_deformer", "clone_mesh_for_editing"),
        "grow_vertex_selection": ("cdmw.modding.mesh_deformer", "grow_vertex_selection"),
        "invert_vertex_selection": ("cdmw.modding.mesh_deformer", "invert_vertex_selection"),
        "mesh_topology_signature": ("cdmw.modding.mesh_deformer", "mesh_topology_signature"),
        "select_all_vertex_selection": ("cdmw.modding.mesh_deformer", "select_all_vertex_selection"),
        "shrink_vertex_selection": ("cdmw.modding.mesh_deformer", "shrink_vertex_selection"),
        "smooth_vertex_selection": ("cdmw.modding.mesh_deformer", "smooth_vertex_selection"),
        "release_native_preview_delta_path": ("cdmw.modding.mesh_native_core_temp_paths", "release_native_preview_delta_path"),
        "parse_pab": ("cdmw.modding.skeleton_parser", "parse_pab"),
        "clear_pac_xml_profile_index_cache": ("cdmw.modding.pac_xml_profiles", "clear_pac_xml_profile_index_cache"),
        "default_pac_xml_profile_cache_path": ("cdmw.modding.pac_xml_profiles", "default_pac_xml_profile_cache_path"),
        "apply_full_import_model_replacement_preset": ("cdmw.modding.full_import_model_replacement", "apply_full_import_model_replacement_preset"),
        "MeshMorphSliderDelta": ("cdmw.modding.mesh_morph_sliders", "MeshMorphSliderDelta"),
        "MeshMorphSliderProfile": ("cdmw.modding.mesh_morph_sliders", "MeshMorphSliderProfile"),
        "apply_morph_slider_values": ("cdmw.modding.mesh_morph_sliders", "apply_morph_slider_values"),
        "create_region_volume_slider_profile": ("cdmw.modding.mesh_morph_sliders", "create_region_volume_slider_profile"),
        "load_morph_slider_delta": ("cdmw.modding.mesh_morph_sliders", "load_morph_slider_delta"),
        "load_morph_slider_profiles": ("cdmw.modding.mesh_morph_sliders", "load_morph_slider_profiles"),
        "validate_morph_target": ("cdmw.modding.mesh_morph_sliders", "validate_morph_target"),
        "MeshRebuildReport": ("cdmw.modding.mesh_importer", "MeshRebuildReport"),
        "MeshImportPreflight": ("cdmw.core.mesh_preflight", "MeshImportPreflight"),
        "build_mesh_import_preflight": ("cdmw.core.mesh_preflight", "build_mesh_import_preflight"),
        "check_material_authority_report": (
            "cdmw.core.material_authority_report_check",
            "check_material_authority_report",
        ),
        "export_model_preview_to_obj": ("cdmw.core.model_export", "export_model_preview_to_obj"),
        "read_archive_entry_baseline_data": (
            "cdmw.core.mesh_baseline",
            "read_archive_entry_baseline_data",
        ),
    }
)


__all__ = ["MESH_WORKFLOW_EXPORTS"]

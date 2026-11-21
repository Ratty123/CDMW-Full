"""Explicit archive ownership for the workbench."""

from __future__ import annotations

import importlib

from PySide6.QtWidgets import QWidget

from cdmw.ui.archive_browser.preview_details import ArchivePreviewDetailsMixin
from cdmw.ui.archive_browser.preview_layout import ArchivePreviewLayoutMixin
from cdmw.ui.archive_browser.preview_loading import ArchivePreviewLoadingMixin
from cdmw.ui.archive_browser.preview_native_core import ArchivePreviewNativeCoreLifecycleMixin
from cdmw.ui.archive_browser.preview_renderer_controls import ArchivePreviewRendererControlsMixin
from cdmw.ui.archive_browser.preview_d3d11_parts import ArchivePreviewD3D11PartsMixin
from cdmw.ui.archive_browser.preview_dotnet_lifecycle import ArchivePreviewDotNetLifecycleMixin
from cdmw.ui.archive_browser.preview_zoom import ArchivePreviewZoomMixin
from cdmw.ui.archive_browser.progress import ArchiveProgressMixin
from cdmw.ui.archive_browser.scan_lifecycle import ArchiveScanLifecycleMixin
from cdmw.ui.archive_browser.render_lifecycle import ArchiveRenderLifecycleMixin
from cdmw.ui.archive_browser.filter_workers import ArchiveFilterWorkerMixin
from cdmw.ui.archive_browser.filters import ArchiveFilterStateMixin
from cdmw.ui.archive_browser.filter_controls import ArchiveFilterControlsMixin
from cdmw.ui.archive_browser.files_panel import ArchiveFilesPanelMixin
from cdmw.ui.archive_browser.asset_catalog_dialog import ArchiveAssetCatalogDialogMixin
from cdmw.ui.archive_browser.controls_panel import ArchiveControlsPanelMixin
from cdmw.ui.archive_browser.edited_results import ArchiveEditedResultsMixin
from cdmw.ui.archive_browser.edit_in_place import BrowseEditInPlaceMixin
from cdmw.ui.archive_browser.extraction import ArchiveExtractionMixin
from cdmw.ui.archive_browser.icon_pipeline import ArchiveIconPipelineMixin
from cdmw.ui.archive_browser.header import ArchiveBrowserHeaderMixin
from cdmw.ui.archive_browser.controller import ArchiveBrowserRowPayloadMixin
from cdmw.ui.archive_browser.controller import ArchiveBrowserTreeControllerMixin
from cdmw.ui.archive_browser.actions import ArchiveBrowserActionMixin
from cdmw.ui.archive_browser.action_chart_actions import ArchiveActionChartActionsMixin
from cdmw.ui.archive_browser.pab_json_actions import ArchivePabJsonActionsMixin
from cdmw.ui.archive_browser.asset_family_references import ArchiveAssetFamilyReferenceMixin
from cdmw.ui.archive_browser.asset_family_panel import ArchiveAssetFamilyPanelMixin
from cdmw.ui.archive_browser.asset_family_layout import ArchiveAssetFamilyLayoutMixin
from cdmw.ui.archive_browser.preview_panel import ArchivePreviewTextToolsMixin
from cdmw.ui.archive_browser.runtime_state import ArchiveRuntimeStateMixin
from cdmw.ui.archive_browser.workspace_layout import ArchiveWorkspaceLayoutMixin

# Mixins unused during startup construction are loaded on first attribute access
# and attached directly onto ArchiveBrowserWorkspace so subsequent lookups pay
# zero __getattr__ overhead while preserving normal bound-method semantics.
_LAZY_MIXIN_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("cdmw.ui.archive_browser.sidecar_index", "ArchiveSidecarIndexMixin", ("_start_archive_sidecar_index_worker", "_compact_archive_sidecar_status_text", "_set_archive_sidecar_status", "_refresh_archive_sidecar_status_elapsed", "_finish_archive_sidecar_status", "_handle_archive_sidecar_progress", "_handle_archive_sidecar_complete", "_handle_archive_sidecar_error", "_cleanup_archive_sidecar_refs")),
    ("cdmw.ui.archive_browser.preview_settings", "ArchivePreviewSettingsMixin", ("_current_model_preview_render_settings", "_model_preview_settings_status", "_refresh_archive_preview_settings_status", "_read_model_preview_render_settings", "_sync_model_preview_settings_dialog", "_sync_model_preview_settings_controls", "_sync_archive_performance_settings_controls", "_open_model_preview_settings_dialog", "_open_modal_model_preview_settings_dialog", "_handle_clear_archive_preview_cache_requested", "_archive_preview_cache_maintenance_completed", "_handle_reset_tool_pbd_cloth_preview_requested", "_handle_archive_renderer_backend_changed", "_configure_model_preview_widget", "_schedule_current_model_preview_asset_refresh", "_refresh_current_model_preview_assets", "_force_refresh_current_model_preview_assets", "_handle_model_preview_settings_changed", "_handle_archive_performance_settings_changed")),
    ("cdmw.ui.archive_browser.reference_preview", "ArchiveReferencePreviewMixin", ("_current_archive_preview_result_for_reference_entry", "_show_archive_reference_preview_dialog", "_update_archive_texture_reference_action_controls", "_show_archive_texture_reference_context_menu", "_open_selected_archive_texture_reference", "_open_archive_reference_preview_entry", "_export_selected_archive_texture_reference", "_export_all_archive_texture_references")),
    ("cdmw.ui.archive_browser.preview_result", "ArchivePreviewResultMixin", ("_show_archive_preview_result", "_show_preview_held_for_edit", "_apply_archive_preview_health", "_toggle_archive_loose_preview", "_apply_archive_preview_result", "_set_archive_preview_image_controls_enabled", "_handle_archive_current_item_change", "_schedule_archive_selection_state_update", "_set_archive_isolated_renderer_debug", "_update_archive_selection_state")),
    ("cdmw.ui.archive_browser.workers", "ArchiveWorkerLifecycleMixin", ("_stop_archive_sidecar_worker",)),
    ("cdmw.ui.archive_browser.workers", "ArchivePreviewWorkerMixin", ("_render_archive_preview", "_coalesce_into_scheduled_archive_preview_request", "_handle_archive_preview_track_selected", "_resolve_scheduled_remote_preview_dependencies", "_schedule_archive_preview_selection_retry", "_retry_scheduled_archive_preview_selection", "_flush_scheduled_archive_preview_request", "_handle_archive_remote_preview_dependencies_ready", "_schedule_archive_preview_secondary_index_retry", "_retry_archive_preview_for_secondary_index", "_handle_archive_remote_preview_dependencies_failed", "_start_archive_preview_worker", "_handle_archive_preview_ready", "_handle_archive_preview_error", "_cleanup_archive_preview_refs", "_start_pending_archive_preview_request")),
    ("cdmw.ui.archive_browser.source_mix_overlay", "ArchiveSourceMixOverlayMixin", ("_resolve_loose_mod_targets_from_live_catalogue", "_open_archive_loose_mod_overlay_dialog")),
    ("cdmw.ui.archive_browser.appearance_composite", "ArchiveAppearanceCompositeMixin", ("_appearance_composite_override_score", "_prompt_appearance_composite_override_component", "_appearance_composite_component_notes", "_prompt_appearance_composite_component_selection", "_open_current_archive_appearance_composite_preview", "_open_archive_appearance_composite_preview_for_entry", "_begin_archive_appearance_composite_selection", "_start_archive_appearance_composite_build", "_handle_archive_appearance_composite_build_result")),
    ("cdmw.ui.archive_browser.binary_sidecar_actions", "ArchiveBinarySidecarActionsMixin", ("_default_archive_hkx_json_path", "_default_archive_hkx_xml_path", "_default_archive_hkx_havok_xml_view_path", "_default_hkx_corpus_report_path", "_default_hkx_corpus_report_path_for_sources", "_default_archive_binary_sidecar_json_path", "_default_binary_sidecar_corpus_report_path_for_sources", "_build_archive_binary_sidecar_json_document", "_export_current_archive_binary_sidecar_json", "_edit_selected_archive_hkx_reference", "_open_archive_binary_sidecar_inspector_dialog", "_inspect_current_archive_binary_sidecar", "_edit_archive_structured_binary_sidecar", "_prompt_structured_sidecar_edit", "_handle_structured_sidecar_edit_complete", "_export_hkx_converter_corpus_report", "_export_binary_sidecar_corpus_report", "_edit_archive_skinned_decal", "_show_skinned_decal_editor", "_skinned_decal_saved")),
    ("cdmw.ui.archive_browser.hkx_document_actions", "ArchiveHkxDocumentActionsMixin", ("_archive_hkx_workflow_dependencies", "_archive_hkx_companion_descriptor_entries", "_build_archive_hkx_companion_descriptor_hints", "_choose_archive_hkx_placement_candidate", "_open_archive_hkx_placement_for_entry", "_open_current_archive_hkx_placement", "_export_current_archive_hkx_document", "_export_current_archive_hkx_json", "_export_current_archive_hkx_xml", "_export_current_archive_hkx_havok_xml_view", "_start_current_archive_hkx_document_import_content", "_start_current_archive_hkx_document_import", "_handle_hkx_import_document_loaded", "_edit_current_archive_hkx", "_edit_archive_hkx_entry", "_edit_archive_hkx_entry_when_idle")),
    ("cdmw.ui.archive_browser.hkx_physics_editor_actions", "ArchiveHkxPhysicsEditorMixin", ("_open_current_hkx_physics_editor", "_read_hkx_entry_bytes", "_open_hkx_physics_editor_for_entry", "_pick_hkx_collision_replacement", "_check_hkx_collision_replacement", "_choose_hkx_replacement_entry", "_report_hkx_physics_refusal", "_save_hkx_physics_file", "_save_hkx_physics_mod")),
    ("cdmw.ui.archive_browser.patch_actions", "ArchivePatchActionsMixin", ("_start_archive_audio_export", "_start_archive_audio_patch", "_start_archive_bank_media_replace", "_select_replacement_audio", "_export_audio_replacement", "_start_archive_sound_bank_edit", "_edit_sound_bank_model", "_write_audio_loose_mod", "_restore_archive_patch_backup_from_ui")),
    ("cdmw.ui.archive_browser.mesh_import_export", "ArchiveMeshImportExportMixin", ("_prepare_archive_mesh_import_setup_async", "_prompt_archive_mesh_import_setup", "_export_selected_archive_models", "_open_batch_mesh_export", "_start_archive_mesh_export", "_export_current_archive_model")),
    ("cdmw.ui.archive_browser.import_actions", "ArchiveImportActionsMixin", ("_import_current_archive_hkx_json", "_import_current_archive_hkx_xml", "_preview_current_archive_mesh_import", "_preview_current_archive_mesh_dds_import", "_patch_current_archive_mesh_from_obj", "_full_import_current_archive_model_replacement", "_swap_current_archive_mesh_with_in_game")),
    ("cdmw.ui.archive_browser.asset_family_dialog", "ArchiveAssetFamilyDialogMixin", ("_archive_has_asset_family_workspace", "_clear_archive_asset_family_cache", "_archive_asset_family_cache_key", "_remember_archive_asset_family_graph", "_archive_asset_family_graph_for_entry", "_archive_asset_family_graph_or_prepare", "_archive_entries_from_asset_family_graph", "_populate_asset_family_dialog_tree", "_attachment_family_skeleton_paths", "_open_archive_asset_family_workspace_dialog", "_populate_attachment_placement_dialog_tree", "_attachment_socket_entry_from_selection", "_parse_attachment_transform_values", "_format_attachment_transform_values")),
    ("cdmw.ui.archive_browser.preview_memory", "ArchivePreviewMemoryAuditMixin", ("_memory_mib", "_archive_memory_audit_payload", "_record_archive_memory_audit")),
    ("cdmw.ui.archive_browser.preview_state", "ArchivePreviewStateMixin", ("_clear_archive_preview", "_show_archive_folder_preview", "_update_archive_preview_warning_controls", "_archive_model_preview_supports_textures")),
    ("cdmw.ui.archive_browser.preview_timing", "ArchivePreviewTimingMixin", ("_archive_preview_timing_summary", "_archive_preview_timing_warning", "_log_archive_preview_timing_if_needed")),
    ("cdmw.ui.archive_browser.ui_formatting", "ArchiveUiFormattingMixin", ("_ui_compact_status_line", "_ui_evidence_label", "_ui_risk_color", "_ui_style_status_columns", "_archive_role_color", "_style_archive_role_columns", "_archive_override_state_color", "_style_archive_override_state_column")),
    ("cdmw.ui.archive_browser.virtual_path_lookup", "ArchiveVirtualPathLookupMixin", ("_find_archive_entry_by_virtual_path", "_archive_lookup_indexes_snapshot", "_reveal_archive_path_in_live_catalogue", "_reveal_archive_paths_in_live_catalogue")),
    ("cdmw.ui.archive_browser.asset_catalog", "ArchiveAssetCatalogMixin", ("_archive_entry_model_base_key_matches", "_archive_entry_item_name_match", "_archive_asset_catalog_table_evidence_labels", "_archive_asset_catalog_text", "_archive_asset_catalog_categories", "_archive_asset_catalog_group_sort_key", "_archive_asset_catalog_group_choices")),
    ("cdmw.ui.archive_browser.asset_catalog_scope", "ArchiveAssetCatalogScopeMixin", ("_archive_asset_catalog_row_values", "_resolve_archive_asset_catalog_path_candidates", "_resolve_archive_asset_catalog_scope_entries", "_archive_asset_catalog_preview_pixmap", "_archive_asset_catalog_inventory_icon_pixmap", "_apply_archive_direct_scope", "_apply_archive_direct_scope_live", "_apply_archive_asset_catalog_scope")),
    ("cdmw.ui.archive_browser.character_dependency_export", "ArchiveCharacterDependencyExportMixin", ("_export_character_dependency_package_live", "_start_character_dependency_live_lookup", "_run_character_dependency_live_round", "_finish_character_dependency_live_plan", "_export_character_dependency_package_for_entry", "_handle_character_dependency_package_plan", "_run_character_dependency_package_export")),
    ("cdmw.ui.archive_browser.material_sidecar_actions", "ArchiveMaterialSidecarActionsMixin", ("_current_or_related_material_sidecar_entry", "_related_material_sidecar_entry_for_archive_entry", "_material_sidecar_selection_candidates", "_choose_material_sidecar_entry", "_edit_current_archive_material_sidecar", "_edit_selected_archive_material_sidecar_reference", "_decode_material_sidecar_bytes", "_qcolor_from_material_value", "_prompt_material_sidecar_related_files", "_material_sidecar_preview_model_candidate", "_material_sidecar_texture_resolution_warnings", "_normalized_material_preview_label", "_apply_material_sidecar_preview_overrides_to_model")),
    ("cdmw.ui.archive_browser.material_sidecar_editor_dialog", "ArchiveMaterialSidecarEditorMixin", ("_show_material_sidecar_editor", "_open_material_sidecar_editor", "_handle_material_sidecar_document_loaded")),
    ("cdmw.ui.archive_browser.mod_ready_export", "ArchiveModReadyExportMixin", ("_prompt_archive_mod_ready_export_target", "_collect_archive_mod_ready_export_target")),
    ("cdmw.ui.tools.mod_package_retrofit", "ArchiveModPackageRetrofitDialogMixin", ("_show_mod_package_retrofit_dialog", "_build_mod_package_retrofit_tool")),
    ("cdmw.ui.archive_browser.action_controls", "ArchiveBrowserActionControlsMixin", ("_update_archive_extract_action_controls", "_update_archive_model_action_controls")),
    ("cdmw.ui.archive_browser.appearance_common", "ArchiveAppearanceCommonMixin", ("_appearance_composite_entry_summary", "_appearance_composite_entry_key", "_appearance_composite_selected_context", "_select_archive_appearance_candidate", "_appearance_swap_selected_context", "_appearance_swap_exact_app_match", "_find_exact_appearance_contexts_for_model")),
    ("cdmw.ui.archive_browser.appearance_swap", "ArchiveAppearanceSwapMixin", ("_open_current_archive_appearance_swap", "_open_archive_appearance_swap_for_entry", "_begin_archive_appearance_swap_review", "_prompt_appearance_swap_target_model", "_appearance_swap_plan_review_text", "_open_archive_appearance_swap_review_dialog", "_start_archive_appearance_swap_package_build", "_handle_archive_appearance_swap_package_result")),
    ("cdmw.ui.archive_browser.prefab_inspector_actions", "ArchivePrefabInspectorActionsMixin", ("_open_current_archive_prefab_inspector", "_show_prefab_inspector", "_offer_prefab_export", "_export_inspected_prefab_package", "_export_inspected_prefab")),
    ("cdmw.ui.archive_browser.speed_tuning_actions", "ArchiveSpeedTuningActionsMixin", ("_open_speed_tuning", "_open_current_archive_speed_tuning", "_show_speed_tuning", "_export_speed_tuning", "_search_speed_prefabs", "_open_speed_game_table", "_open_speed_prefab")),
    ("cdmw.ui.archive_browser.game_table_actions", "ArchiveGameTableActionsMixin", ("_game_table_root", "_open_game_table_editor", "_game_table_task_refused", "_load_game_table", "_write_game_table_mod")),
    ("cdmw.ui.archive_browser.prefab_json_actions", "ArchivePrefabJsonActionsMixin", ("_current_archive_prefab_entry", "_default_archive_prefab_edit_json_path", "_export_current_archive_prefab_edit_json", "_import_current_archive_prefab_edit_json")),
    ("cdmw.ui.archive_browser.hkx_editor_dialog", "ArchiveHkxEditorDialogMixin", ("_open_archive_hkx_editor_dialog",)),
    ("cdmw.ui.archive_browser.static_replacement_dialog", "ArchiveStaticReplacementDialogMixin", ("_prompt_archive_static_replacement_options",)),
    ("cdmw.ui.archive_browser.mesh_modify_original", "ArchiveMeshModifyOriginalMixin", ("_prompt_archive_modify_original_workspace_options", "_archive_modify_original_workspace_name", "_modify_original_workspace_supplemental_files", "_cleanup_stale_modify_original_sessions", "_modify_original_runtime_candidate_note", "_retarget_static_options_for_runtime_entry", "_start_archive_modify_original_workspace", "_prompt_modify_original_draft_choice", "_launch_archive_modify_original_workspace", "_open_modify_original_mesh_setup")),
    ("cdmw.ui.archive_browser.mesh_setup_helpers", "ArchiveMeshSetupHelperMixin", ("_show_modify_original_workspace_ready_dialog", "_format_static_alignment_number", "_format_static_alignment_vec", "_build_archive_static_placement_context_html", "_add_replacement_asset_profile_summary")),
    ("cdmw.ui.archive_browser.mesh_builder_lifecycle", "ArchiveMeshBuilderLifecycleMixin", ("_modeless_alignment_dialog_key", "_mesh_replacement_builder_active", "_defer_archive_preview_refresh_for_builder", "_resume_archive_preview_after_builder", "_activate_modeless_alignment_dialog", "_register_modeless_alignment_dialog", "_dispose_partial_alignment_builder", "_unregister_modeless_alignment_dialog")),
    ("cdmw.ui.archive_browser.mesh_dds_preview", "ArchiveMeshDdsPreviewMixin", ("_preview_slot_label", "_build_local_dds_preview_override_path", "_apply_archive_entry_dds_preview_to_model", "_build_archive_mesh_dds_import_preview_result", "_show_archive_dds_import_preview_result", "_start_archive_mesh_dds_import_preview", "_archive_related_references_for_entry", "_current_archive_related_references_for_entry")),
    ("cdmw.ui.archive_browser.mesh_direct_patch", "ArchiveMeshDirectPatchMixin", ("_show_archive_import_preview", "_confirm_archive_mesh_import_commit", "_attach_archive_model_preview_images", "_prompt_archive_mesh_related_file_selection", "_archive_mesh_import_file_filter", "_has_valid_obj_roundtrip_sidecar", "_obj_roundtrip_source_matches_entry")),
    ("cdmw.ui.archive_browser.mesh_swap_support", "ArchiveMeshSwapSupportMixin", ("_archive_entry_identity_key", "_same_archive_entry", "_archive_swap_dependencies", "_archive_mesh_source_label", "_archive_mesh_source_scene_path", "_load_archive_mesh_scene_import_result", "_archive_entry_is_material_sidecar", "_archive_entry_is_appearance_descriptor", "_archive_entry_is_prefab_descriptor", "_archive_entry_is_equipment_model_for_swap", "_archive_entry_is_character_appearance_swap_candidate", "_archive_entries_allow_character_swap_scope", "_archive_entry_swap_companion_group", "_archive_model_related_entries_for_swap", "_archive_model_sidecar_entries_for_swap", "_archive_character_appearance_entries_for_swap", "_archive_character_app_graph_entries_for_swap", "_archive_character_app_graph_texture_entries_for_swap", "_archive_model_source_texture_entries_for_swap", "_build_archive_swap_source_texture_evidence", "_target_sidecar_path_for_source_sidecar", "_target_appearance_path_for_source_appearance", "_target_family_path_for_source_companion")),
    ("cdmw.ui.archive_browser.mesh_swap_scope_dialog", "ArchiveMeshSwapScopeDialogMixin", ("_prompt_archive_in_game_mesh_swap_scope",)),
    ("cdmw.ui.archive_browser.mesh_launch_flow", "ArchiveMeshLaunchFlowMixin", ("_build_in_game_mesh_swap_extra_specs", "_start_archive_direct_source_model_swap", "_pin_in_game_mesh_swap_target_dependencies", "_refresh_archive_in_game_swap_banner", "_set_pending_in_game_mesh_swap_target", "_cancel_archive_in_game_mesh_swap_target", "_report_in_game_mesh_swap_blocked", "_handle_archive_in_game_mesh_swap_entry", "_start_archive_mesh_import_preview", "_start_archive_in_game_mesh_swap", "_continue_archive_in_game_mesh_swap")),
    ("cdmw.ui.archive_browser.mesh_patch_flow", "ArchiveMeshPatchFlowMixin", ("_start_archive_full_import_model_replacement", "_start_archive_materials_and_textures_replacement", "_preview_invalid", "_start_archive_mesh_patch")),
    ("cdmw.ui.archive_browser.attachment_batch", "ArchiveAttachmentBatchMixin", ("_open_archive_bulk_attachment_placement_from_selection", "_open_archive_bulk_attachment_placement_dialog")),
    ("cdmw.ui.archive_browser.attachment_donor_picker_dialog", "ArchiveAttachmentDonorPickerDialogMixin", ("_open_archive_attachment_donor_picker_dialog",)),
    ("cdmw.ui.archive_browser.attachment_icons", "ArchiveAttachmentIconMixin", ("_attachment_package_item_icon_entries", "_archive_item_icon_related_stems", "_build_custom_item_icon_supplemental_spec", "_attachment_package_source_icon_override_rows")),
    ("cdmw.ui.archive_browser.attachment_loose_files", "ArchiveAttachmentLooseFileMixin", ("_attachment_package_material_sidecar_for_model",)),
    ("cdmw.ui.archive_browser.attachment_package", "ArchiveAttachmentPackageMixin", ("_attachment_package_entry_key", "_attachment_package_path_stem", "_attachment_package_side_suffix", "_attachment_package_strip_side_suffix", "_attachment_package_graph_entries", "_attachment_package_entries_with_extension", "_score_attachment_package_target_entry", "_choose_attachment_package_target_entry", "_choose_attachment_package_donor_prefab", "_attachment_package_target_prefab_entries_for_donor", "_attachment_package_socket_entries_for_prefab", "_attachment_package_weapon_class_tokens", "_attachment_package_weapon_subclass_tokens", "_attachment_package_weapon_class_label", "_attachment_package_placement_compatibility", "_attachment_package_target_support_entries")),
    ("cdmw.ui.archive_browser.attachment_plan", "ArchiveAttachmentPlanMixin", ("_open_archive_attachment_placement_workspace_dialog", "_build_archive_asset_family_graph_from_snapshots", "_run_archive_attachment_placement_prepare", "_cancel_archive_attachment_placement_prepare", "_placement_swap_package_info_with_diagnostics", "_build_attachment_donor_package_plan")),
    ("cdmw.ui.archive_browser.attachment_placement_diff_dialog", "ArchiveAttachmentPlacementDiffDialogMixin", ("_open_archive_attachment_placement_diff_dialog",)),
    ("cdmw.ui.archive_browser.attachment_safe_placement_dialog", "ArchiveAttachmentSafePlacementDialogMixin", ("_open_archive_attachment_safe_placement_dialog",)),
    ("cdmw.ui.archive_browser.attachment_socket_editor", "ArchiveAttachmentSocketEditorMixin", ("_attachment_socket_xml_text", "_attachment_socket_xml_numbered_text", "_open_archive_socket_xml_editor_dialog")),
    ("cdmw.ui.archive_browser.attachment_visual_dialog", "ArchiveAttachmentVisualDialogMixin", ("_open_archive_attachment_visual_placement_dialog",)),
    ("cdmw.ui.archive_browser.attachment_visual_payload", "ArchiveAttachmentVisualPayloadMixin", ("_attachment_visual_edited_socket_payload", "_build_attachment_placement_schematic_preview_model", "_attachment_visual_socket_anchor_position", "_build_attachment_socket_only_preview_model", "_build_attachment_visual_preview_model", "_attachment_visual_chain_transform", "_attachment_visual_transform_point", "_attachment_visual_transform_local_point", "_attachment_visual_denormalized_model_point", "_attachment_visual_model_vertex_count", "_attachment_visual_clone_model_meshes", "_attachment_visual_box_mesh", "_attachment_visual_oriented_box_mesh", "_attachment_visual_segment_mesh", "_attachment_visual_body_proxy_meshes", "_attachment_visual_weapon_proxy_meshes", "_attachment_visual_lookup_named_vector", "_attachment_visual_lookup_named_matrix", "_attachment_visual_transform_bone_vector", "_attachment_visual_socket_world_position", "_attachment_visual_socket_evidence_roots", "_attachment_visual_find_loose_evidence_path", "_attachment_visual_find_archive_entry_by_path_or_basename", "_attachment_visual_socket_document_from_path", "_attachment_visual_model_skeleton_path_candidates", "_attachment_visual_candidate_skeleton_paths", "_attachment_visual_bone_position_from_matrix_or_local", "_attachment_visual_build_skeleton_context", "_attachment_visual_skeleton_context", "_attachment_visual_character_socket_document", "_attachment_visual_resolve_context", "_attachment_visual_character_socket_choices", "_attachment_visual_context_for_character_socket", "_attachment_visual_pivot_socket_for_character_socket", "_attachment_visual_evidence_for_character_socket", "_attachment_visual_model_entry", "_attachment_visual_body_context_model_entry", "_attachment_visual_best_evidence", "_attachment_visual_evidence_for_prefab", "_attachment_visual_finite_vector3", "_attachment_visual_finite_quat", "_attachment_visual_quat_inverse", "_attachment_visual_quat_multiply", "_attachment_visual_quat_rotate", "_attachment_visual_euler_quat", "_attachment_visual_socket_proxy_position", "_attachment_visual_find_socket_info", "_attachment_visual_context_has_real_anchor", "_attachment_visual_context_transform_scale")),
    ("cdmw.ui.archive_browser.reference_export", "ArchiveReferenceExportMixin", ("_archive_reference_export_filter", "_export_archive_reference_entry", "_export_archive_reference_entries_to_folder", "_prompt_archive_reference_selection")),
    ("cdmw.ui.archive_browser.source_picker_dialog", "ArchiveSourcePickerDialogMixin", ("_choose_archive_mesh_source_dialog",)),
    ("cdmw.ui.archive_browser.source_mix_actions", "ArchiveSourceMixActionsMixin", ("_source_mix_target_entries_by_virtual_path", "_source_mix_candidate_target_from_indexes", "_resolve_source_mix_candidate_targets", "_source_mix_counterpart_entry", "_source_mix_default_target_entries", "_source_mix_lookup_keys_for_texture_path", "_source_mix_sidecar_referenced_payload_specs", "_open_archive_source_mix_package_dialog")),
    ("cdmw.ui.archive_browser.preview_cache", "ArchivePreviewCacheMixin", ("_clear_archive_preview_cache", "_request_archive_preview_cache_maintenance", "_archive_preview_support_texture_slots", "_archive_preview_cache_key", "_native_preview_package_cache_root", "_native_preview_core_cache_root", "_native_preview_package_cache_mode", "_native_preview_package_cache_budget", "_collect_archive_preview_loose_roots", "_archive_entry_native_cache_signature", "_archive_preview_item_context", "_archive_native_preview_package_cache_key", "_archive_file_stamp_for_cache", "_validate_d3d11_preview_package_paths", "_d3d11_preview_package_model_key", "_sanitize_d3d11_view_state_for_restore", "_clone_archive_preview_model", "_archive_preview_result_cacheable", "_clone_archive_preview_result_for_cache", "_load_preview_image_if_available", "_attach_archive_preview_result_images", "_archive_preview_result_prepared_bytes", "_get_cached_archive_preview_result", "_store_cached_archive_preview_result", "_strip_archive_preview_heavy_payloads_for_mesh_editor", "_trim_archive_preview_cache")),
    ("cdmw.ui.archive_browser.preview_core_prewarm", "ArchivePreviewCorePrewarmMixin", ("_archive_preview_core_prewarm_entry", "_archive_preview_core_prewarm_allowed", "_start_archive_preview_core_prewarm", "_cancel_archive_preview_core_prewarm", "_finish_archive_preview_core_prewarm")),
)

_LAZY_ATTR_TO_MIXIN: dict[str, tuple[str, str]] = {
    attr: (module_name, class_name)
    for module_name, class_name, attrs in _LAZY_MIXIN_SPECS
    for attr in attrs
}


_ATTACHED_LAZY_MIXINS: set[tuple[str, str]] = set()


def _attach_lazy_mixin(
    target_cls: type,
    module_name: str,
    class_name: str,
    *,
    overwrite: bool = False,
) -> None:
    key = (module_name, class_name)
    if key in _ATTACHED_LAZY_MIXINS:
        return
    mixin_cls = getattr(importlib.import_module(module_name), class_name)
    for base in mixin_cls.__mro__:
        if not base.__module__.startswith("cdmw."):
            continue
        for attr_name, raw_value in base.__dict__.items():
            if attr_name.startswith("__") and attr_name.endswith("__"):
                continue
            if overwrite or attr_name not in target_cls.__dict__:
                setattr(target_cls, attr_name, raw_value)
    _ATTACHED_LAZY_MIXINS.add(key)


class ArchiveBrowserWorkspace(
    BrowseEditInPlaceMixin,
    ArchiveEditedResultsMixin,
    ArchivePreviewDetailsMixin,
    ArchivePreviewLayoutMixin,
    ArchivePreviewLoadingMixin,
    ArchivePreviewNativeCoreLifecycleMixin,
    ArchivePreviewRendererControlsMixin,
    ArchivePreviewD3D11PartsMixin,
    ArchivePreviewDotNetLifecycleMixin,
    ArchivePreviewZoomMixin,
    ArchiveProgressMixin,
    ArchiveScanLifecycleMixin,
    ArchiveRenderLifecycleMixin,
    ArchiveFilterWorkerMixin,
    ArchiveFilterStateMixin,
    ArchiveFilterControlsMixin,
    ArchiveFilesPanelMixin,
    ArchiveAssetCatalogDialogMixin,
    ArchiveControlsPanelMixin,
    ArchiveExtractionMixin,
    ArchiveIconPipelineMixin,
    ArchiveBrowserHeaderMixin,
    ArchiveBrowserRowPayloadMixin,
    ArchiveBrowserTreeControllerMixin,
    ArchiveBrowserActionMixin,
    ArchiveActionChartActionsMixin,
    ArchivePabJsonActionsMixin,
    ArchiveAssetFamilyReferenceMixin,
    ArchiveAssetFamilyPanelMixin,
    ArchiveAssetFamilyLayoutMixin,
    ArchivePreviewTextToolsMixin,
    ArchiveRuntimeStateMixin,
    ArchiveWorkspaceLayoutMixin,
    QWidget,
):
    def __init__(self, shell) -> None:
        super().__init__(shell)
        self.shell = shell

    def _ensure_preview_settings_mixin(self) -> None:
        _attach_lazy_mixin(
            ArchiveBrowserWorkspace,
            "cdmw.ui.archive_browser.preview_settings",
            "ArchivePreviewSettingsMixin",
            overwrite=True,
        )

    def _refresh_current_model_preview_assets(self, *, force: bool = False) -> None:
        self._ensure_preview_settings_mixin()
        return ArchiveBrowserWorkspace._refresh_current_model_preview_assets(self, force=force)

    def _force_refresh_current_model_preview_assets(self) -> None:
        self._ensure_preview_settings_mixin()
        return ArchiveBrowserWorkspace._force_refresh_current_model_preview_assets(self)

    def _ensure_preview_result_mixin(self) -> None:
        _attach_lazy_mixin(
            ArchiveBrowserWorkspace,
            "cdmw.ui.archive_browser.preview_result",
            "ArchivePreviewResultMixin",
            overwrite=True,
        )

    def _handle_archive_current_item_change(self, current, previous) -> None:
        self._ensure_preview_result_mixin()
        return ArchiveBrowserWorkspace._handle_archive_current_item_change(self, current, previous)

    def _schedule_archive_selection_state_update(self) -> None:
        self._ensure_preview_result_mixin()
        return ArchiveBrowserWorkspace._schedule_archive_selection_state_update(self)

    def _update_archive_selection_state(self) -> None:
        self._ensure_preview_result_mixin()
        return ArchiveBrowserWorkspace._update_archive_selection_state(self)

    def _ensure_preview_worker_mixins(self) -> None:
        _attach_lazy_mixin(
            ArchiveBrowserWorkspace,
            "cdmw.ui.archive_browser.workers",
            "ArchiveWorkerLifecycleMixin",
            overwrite=True,
        )
        _attach_lazy_mixin(
            ArchiveBrowserWorkspace,
            "cdmw.ui.archive_browser.workers",
            "ArchivePreviewWorkerMixin",
            overwrite=True,
        )

    def _flush_scheduled_archive_preview_request(self) -> None:
        self._ensure_preview_worker_mixins()
        return ArchiveBrowserWorkspace._flush_scheduled_archive_preview_request(self)

    def _handle_archive_preview_track_selected(self, track_index: int) -> None:
        self._ensure_preview_worker_mixins()
        return ArchiveBrowserWorkspace._handle_archive_preview_track_selected(self, track_index)

    def _handle_archive_remote_preview_dependencies_failed(self, request_id: int, message: str) -> None:
        self._ensure_preview_worker_mixins()
        return ArchiveBrowserWorkspace._handle_archive_remote_preview_dependencies_failed(self, request_id, message)

    def _handle_archive_remote_preview_dependencies_ready(self, request_id: int, payload: object) -> None:
        self._ensure_preview_worker_mixins()
        return ArchiveBrowserWorkspace._handle_archive_remote_preview_dependencies_ready(self, request_id, payload)

    def __getattr__(self, name: str):
        target = _LAZY_ATTR_TO_MIXIN.get(name)
        if target is None:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        module_name, class_name = target
        _attach_lazy_mixin(
            ArchiveBrowserWorkspace,
            module_name,
            class_name,
            overwrite=(
                module_name
                in {
                    "cdmw.ui.archive_browser.workers",
                    "cdmw.ui.archive_browser.preview_result",
                    "cdmw.ui.archive_browser.preview_settings",
                }
            ),
        )
        return getattr(self, name)

    @property
    def archive(self):
        return self

    @property
    def textures(self):
        return self.shell.textures

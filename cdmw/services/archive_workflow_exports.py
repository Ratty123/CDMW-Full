"""Explicit UI-facing archive workflow service surface."""

from __future__ import annotations


ARCHIVE_WORKFLOW_EXPORTS: dict[str, tuple[str, str]] = {}


def _add(module: str, *names: str) -> None:
    ARCHIVE_WORKFLOW_EXPORTS.update({name: (module, name) for name in names})


_add(
    "cdmw.core.archive_loose_export",
    "export_archive_mesh_payloads_to_mod_ready_loose",
    "export_archive_payloads_to_mod_ready_loose",
)
_add("cdmw.core.archive_mesh_export", "export_archive_mesh")
_add(
    "cdmw.core.archive_attachment_patches",
    "build_attachment_body_location_choices",
    "build_pac_xml_stack_equip_type_patch",
    "build_part_in_out_socket_attach_point_patch",
    "build_part_in_out_socket_class_copy_patch",
    "build_part_in_out_socket_profile_patch",
    "build_prefab_attachment_profile_patch",
    "build_prefab_socket_name_patch",
    "build_socket_bone_data_profile_patch",
    "infer_attachment_child_socket_name",
    "infer_part_in_out_weapon_class",
    "infer_stack_equip_type_for_socket",
    "inspect_prefab_attachment_profile_fields",
    "parse_part_in_out_socket_info_xml",
    "parse_socket_bone_data_xml",
    "part_in_out_rows_for_weapon_class",
)
_add(
    "cdmw.core.archive_attachment_iteminfo",
    "build_iteminfo_behavior_equip_type_patch",
    "build_universal_twohand_sword_animation_alias_plan",
    "build_universal_twohand_sword_true_onehand_iteminfo_patch",
)
_add(
    "cdmw.core.archive_model_references",
    "_collect_same_stem_related_target_basenames",
    "_extract_archive_model_sidecar_texture_references",
    "_normalize_model_visible_texture_mode",
    "_strip_archive_model_family_variant_suffix",
    "iter_archive_character_equipment_root_alias_stems",
    "iter_archive_equipment_model_alias_stems",
)
_add(
    "cdmw.core.archive_model_textures",
    "_attach_model_sidecar_texture_preview_paths",
    "_attach_model_support_texture_preview_paths",
    "_attach_model_texture_preview_paths",
    "_infer_model_preview_normal_strength",
    "_resolve_model_texture_semantic_details",
    "set_model_texture_display_preview_max_dimension",
)
_add(
    "cdmw.core.archive_relationships",
    "build_archive_relationship_plan",
    "build_character_dependency_plan",
    "build_character_swap_plan",
    "resolve_material_texture_graph",
)
_add("cdmw.core.archive_sidecar_cache", "_extract_archive_sidecar_texture_lookup_paths")
_add("cdmw.core.archive_audio", "build_archive_audio_patch_payload", "export_archive_audio_as_wav")
_add("cdmw.core.prefab_json", "apply_prefab_edit_json", "dumps_prefab_edit_json")
_add("cdmw.core.weapon_swap_templates", "weapon_swap_template_socket_rows")
_add("cdmw.core.archive_name_search", "ArchiveNameSearchIndex")
_add("cdmw.core.archive_compact_index", "ArchiveRowIndex")
_add(
    "cdmw.core.archive_filtering",
    "archive_entry_item_name_match",
    "archive_entry_model_base_key_matches",
)


__all__ = ["ARCHIVE_WORKFLOW_EXPORTS"]

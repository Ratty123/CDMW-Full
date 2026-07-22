"""Explicit lazy exports used by texture/recolor UI workflows."""

from __future__ import annotations


TEXTURE_WORKFLOW_EXPORTS: dict[str, tuple[str, str]] = {}


def _exports(module: str, *names: str) -> None:
    TEXTURE_WORKFLOW_EXPORTS.update({name: (module, name) for name in names})


_exports(
    "cdmw.core.recolor_variants",
    "RecolorVariantAnalysis",
    "RecolorVariantBuildResult",
    "RecolorVariantOutputProfile",
    "RecolorVariantPreviewImage",
    "RecolorVariantRule",
    "RecolorVariantTemplate",
    "analyze_recolor_variant_package",
    "export_recolor_variant_templates",
    "import_recolor_variant_templates",
    "load_recolor_variant_templates",
    "matching_recolor_variant_rule",
    "preview_recolor_variant_target_image",
    "preview_recolor_variant_template",
    "recolor_export_options_for_manager",
    "save_recolor_variant_templates",
    "texture_editor_settings_for_recolor_variant_rule",
)
_exports("cdmw.core.realesrgan_ncnn", "discover_realesrgan_ncnn_models", "resolve_ncnn_model_dir")
_exports(
    "cdmw.core.upscale_profiles",
    "classify_texture_type",
    "derive_texture_group_key",
    "get_texture_preset_definition",
    "normalize_texture_reference_for_sidecar_lookup",
    "parse_material_sidecar_profile",
    "parse_texture_sidecar_bindings",
)
_exports(
    "cdmw.core.appearance_composite",
    "AppearanceCompositeBuildResult",
    "AppearanceCompositeModelOverride",
    "AppearanceCompositePreviewPlan",
    "AppearanceSinglePacSwapPlan",
    "build_appearance_composite_model",
    "build_appearance_composite_preview_plan",
    "build_appearance_single_pac_swap_package_plan",
    "find_appearance_composite_candidates",
)
_exports("cdmw.core.texture_pipeline.inspection", "parse_dds")
_exports("cdmw.core.texture_pipeline.package_export", "resolve_default_mod_ready_export_root")
_exports(
    "cdmw.core.source_mix",
    "SourceMixCandidate",
    "SourceMixSelection",
    "group_source_mix_candidates_by_family",
    "normalize_source_mix_virtual_path",
    "paired_counterpart_virtual_path",
    "scan_loose_folder_source",
    "scan_mod_archive_source",
    "source_mix_role_for_virtual_path",
    "validate_source_mix_selections",
)
_exports(
    "cdmw.core.classification_registry",
    "get_registered_texture_classification",
    "remove_registered_texture_classifications",
    "set_registered_texture_classifications",
    "texture_classification_registry_path",
)
_exports(
    "cdmw.core.texture_pipeline.workspace",
    "common_workspace_root_from_config",
    "create_missing_directories_for_config",
    "create_workspace_structure",
    "suggested_workspace_paths",
)
_exports("cdmw.core.chainner", "import_model_assets_to_directory", "validate_ncnn_model_import_sources")
_exports(
    "cdmw.core.texture_pipeline.planning",
    "build_single_texture_processing_plan",
    "build_texture_processing_plan",
)
_exports(
    "cdmw.core.texture_pipeline.runtime_config",
    "normalize_config",
    "normalize_config_for_planning",
    "validate_backend_runtime_requirements",
)
_exports(
    "cdmw.core.ncnn_model_catalog",
    "NCNN_CATALOG_SOURCE_LINKS",
    "NCNN_MODEL_CATALOG",
    "get_ncnn_catalog_entry",
)
_exports("cdmw.core.texture_pipeline.discovery", "collect_dds_files")
_exports("cdmw.core.texture_pipeline.preflight", "build_texture_policy_preview_payload")
_exports("cdmw.core.texture_native", "native_texture_backend_identity")
_exports(
    "cdmw.core.texture_legacy_compat",
    "OBSOLETE_SETTINGS_KEY",
    "sanitized_profile_mapping",
)


__all__ = ["TEXTURE_WORKFLOW_EXPORTS"]

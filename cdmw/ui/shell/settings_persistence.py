"""Main shell settings persistence."""

from __future__ import annotations

import dataclasses
import json
from typing import List, Sequence

from cdmw.constants import (
    ARCHIVE_BROWSER_VIEW_MODE,
    DDS_SIZE_MODE_ORIGINAL,
    DEFAULT_UI_THEME,
    DEFAULT_UPSCALE_BACKEND,
    DEFAULT_UPSCALE_POST_CORRECTION,
    DEFAULT_UPSCALE_TEXTURE_PRESET,
    ENABLE_AUTOMATIC_TEXTURE_RULES,
    ENABLE_MOD_READY_LOOSE_EXPORT,
    ENABLE_UNSAFE_TECHNICAL_OVERRIDE,
    MOD_READY_CREATE_NO_ENCRYPT,
    MOD_READY_EXPORT_ROOT,
    MOD_READY_PACKAGE_AUTHOR,
    MOD_READY_PACKAGE_DESCRIPTION,
    MOD_READY_PACKAGE_NEXUS_URL,
    MOD_READY_PACKAGE_TITLE,
    MOD_READY_PACKAGE_VERSION,
    REALESRGAN_NCNN_EXE_PATH,
    REALESRGAN_NCNN_EXTRA_ARGS,
    REALESRGAN_NCNN_MODEL_DIR,
    REALESRGAN_NCNN_MODEL_NAME,
    REALESRGAN_NCNN_SCALE,
    REALESRGAN_NCNN_TILE_SIZE,
    RETRY_SMALLER_TILE_ON_FAILURE,
    UPSCALE_BACKEND_CHAINNER,
    UPSCALE_BACKEND_NONE,
    UPSCALE_BACKEND_REALESRGAN_NCNN,
)
from cdmw.core.archive import normalize_archive_browser_sort_column, normalize_archive_browser_sort_order
from cdmw.core.mod_package import MOD_PACKAGE_MANAGER_PROFILES, mod_package_export_options_for_manager
from cdmw.domain.textures.profiles import (
    build_default_texture_workflow_profiles,
    build_default_texture_workflow_rules,
    should_seed_default_texture_workflow_state,
    upgrade_default_texture_workflow_state,
)
from cdmw.domain.textures.rules import (
    coerce_texture_workflow_profiles,
    coerce_texture_workflow_rules,
    migrate_legacy_texture_rules_to_structured,
)
from cdmw.models import default_config
from cdmw.ui.themes import UI_THEME_SCHEMES


class SettingsPersistenceMixin:
    """Save and restore main-window settings state."""
    def _save_settings(self) -> None:
        if not self._settings_ready:
            return
        self.settings.setValue("appearance/theme", self.current_theme_key)
        self.settings.setValue("appearance/language", self.ui_localizer.language_code)
        self.settings.setValue("paths/original_dds_root", self.original_dds_edit.text())
        self.settings.setValue("paths/png_root", self.png_root_edit.text())
        self.settings.setValue("paths/texture_editor_png_root", self.texture_editor_png_root_edit.text())
        self.settings.setValue("paths/dds_staging_root", self.dds_staging_root_edit.text())
        self.settings.setValue("paths/output_root", self.output_root_edit.text())
        self.settings.setValue("paths/texconv_path", self.texconv_path_edit.text())
        self.settings.setValue("asset_authoring/material_maker_project_path", self.material_maker_project_edit.text())
        self.settings.setValue("asset_authoring/material_maker_export_dir", self.material_maker_export_dir_edit.text())
        self.settings.setValue("asset_authoring/oiio_source_path", self.openimageio_source_path_edit.text())
        self.settings.setValue("asset_authoring/oiio_output_path", self.openimageio_output_path_edit.text())
        self.settings.setValue("asset_authoring/oiio_compare_path", self.openimageio_compare_path_edit.text())
        self.settings.setValue("archive/package_root", self.archive_package_root_edit.text())
        self.settings.setValue("archive/extract_root", self.archive_extract_root_edit.text())
        self.settings.setValue("archive/filter_text", self.archive_filter_edit.text())
        self.settings.setValue("archive/exclude_filter_text", self.archive_exclude_filter_edit.text())
        self.settings.setValue("archive/extension_filter", self._combo_value(self.archive_extension_filter_combo))
        self.settings.setValue("archive/package_filter_text", self.archive_package_filter_edit.text())
        self.settings.setValue("archive/structure_filter", self._current_archive_structure_filter_value())
        self.settings.setValue("archive/role_filter", self._combo_value(self.archive_role_filter_combo))
        self.settings.setValue(
            "archive/exclude_common_technical_suffixes",
            self.archive_exclude_common_technical_checkbox.isChecked(),
        )
        self.settings.setValue("archive/min_size_kb", self.archive_min_size_spin.value())
        self.settings.setValue("archive/previewable_only", self.archive_previewable_only_checkbox.isChecked())
        self.settings.setValue("archive/browser_view_mode", self._archive_browser_view_mode())
        self.settings.setValue("ui/archive_tree_v4_sort_column", int(self.archive_tree_sort_column))
        self.settings.setValue("ui/archive_tree_v4_sort_order", self.archive_tree_sort_order)
        self._save_archive_tree_header_settings()
        preview_settings = self._current_model_preview_render_settings()
        self.settings.setValue("archive/model_use_textures", preview_settings.use_textures_by_default)
        self.settings.setValue("archive/model_high_quality", preview_settings.high_quality_by_default)
        self.settings.setValue(
            "archive/model_preview_dark_background",
            bool(getattr(self, "archive_model_preview_dark_background_enabled", True)),
        )
        self.settings.setValue("preview/archive_renderer_backend", self._archive_model_renderer_backend())
        archive_performance_settings = self._current_archive_performance_settings()
        self.settings.setValue("performance/resource_profile", archive_performance_settings.resource_profile)
        self.settings.setValue("performance/archive_fetch_batch_size", archive_performance_settings.archive_fetch_batch_size)
        self.settings.setValue("performance/native_archive_acceleration", archive_performance_settings.native_archive_acceleration)
        self.settings.setValue("archive/enable_sidecar_indexing", archive_performance_settings.enable_sidecar_indexing)
        self.settings.setValue("archive/sidecar_worker_count", archive_performance_settings.sidecar_worker_count)
        self.settings.setValue("archive/preview_cache_limit", archive_performance_settings.preview_cache_limit)
        self.settings.setValue("archive/native_preview_cache_mode", archive_performance_settings.native_preview_cache_mode)
        self.settings.setValue("archive/quick_then_full_preview", archive_performance_settings.quick_then_full_preview)
        self.settings.setValue("archive/maximum_indexing_priority", archive_performance_settings.maximum_indexing_priority)
        self.settings.setValue("preview/visible_texture_mode", preview_settings.visible_texture_mode)
        self.settings.setValue("preview/render_diagnostic_mode", preview_settings.render_diagnostic_mode)
        self.settings.setValue("preview/d3d11_view_mode", preview_settings.d3d11_view_mode)
        self.settings.setValue("preview/d3d11_normal_y_mode", preview_settings.d3d11_normal_y_mode)
        self.settings.setValue("preview/d3d11_texture_address_mode", preview_settings.d3d11_texture_address_mode)
        self.settings.setValue("preview/alpha_handling_mode", preview_settings.alpha_handling_mode)
        self.settings.setValue("preview/texture_probe_source", preview_settings.texture_probe_source)
        self.settings.setValue("preview/sampler_probe_mode", preview_settings.sampler_probe_mode)
        self.settings.setValue("preview/diffuse_swizzle_mode", preview_settings.diffuse_swizzle_mode)
        self.settings.setValue("preview/disable_tint", preview_settings.disable_tint)
        self.settings.setValue("preview/disable_brightness", preview_settings.disable_brightness)
        self.settings.setValue("preview/disable_uv_scale", preview_settings.disable_uv_scale)
        self.settings.setValue("preview/force_nearest_no_mipmaps", preview_settings.force_nearest_no_mipmaps)
        self.settings.setValue("preview/disable_normal_map", preview_settings.disable_normal_map)
        self.settings.setValue("preview/disable_material_map", preview_settings.disable_material_map)
        self.settings.setValue("preview/disable_height_map", preview_settings.disable_height_map)
        self.settings.setValue("preview/flip_texture_v", preview_settings.flip_texture_v)
        self.settings.setValue("preview/disable_all_support_maps", preview_settings.disable_all_support_maps)
        self.settings.setValue("preview/disable_lighting", preview_settings.disable_lighting)
        self.settings.setValue("preview/disable_depth_test", preview_settings.disable_depth_test)
        self.settings.setValue("preview/show_texture_debug_strip", preview_settings.show_texture_debug_strip)
        self.settings.setValue("preview/d3d11_cull_back_faces", preview_settings.d3d11_cull_back_faces)
        self.settings.setValue("preview/show_physics_overlay", preview_settings.show_physics_overlay)
        self.settings.setValue(
            "preview/show_physics_simulation_preview",
            preview_settings.show_physics_simulation_preview,
        )
        self.settings.setValue("preview/enable_tool_pbd_cloth_preview", preview_settings.enable_tool_pbd_cloth_preview)
        self.settings.setValue("preview/pause_tool_pbd_cloth_preview", preview_settings.pause_tool_pbd_cloth_preview)
        self.settings.setValue("preview/tool_pbd_cloth_wind_strength", preview_settings.tool_pbd_cloth_wind_strength)
        self.settings.setValue(
            "preview/tool_pbd_cloth_wind_direction_degrees",
            preview_settings.tool_pbd_cloth_wind_direction_degrees,
        )
        self.settings.setValue("preview/show_tool_pbd_cloth_pins", preview_settings.show_tool_pbd_cloth_pins)
        self.settings.setValue("preview/show_tool_pbd_cloth_colliders", preview_settings.show_tool_pbd_cloth_colliders)
        self.settings.setValue("preview/solo_batch_index", preview_settings.solo_batch_index)
        self.settings.setValue("preview/texture_max_dimension", preview_settings.preview_texture_max_dimension)
        self.settings.setValue("preview/low_quality_texture_max_dimension", preview_settings.low_quality_texture_max_dimension)
        self.settings.setValue("preview/max_anisotropy", preview_settings.max_anisotropy)
        self.settings.setValue("preview/d3d11_mip_lod_bias", preview_settings.d3d11_mip_lod_bias)
        self.settings.setValue("preview/ambient_strength", preview_settings.ambient_strength)
        self.settings.setValue("preview/diffuse_wrap_bias", preview_settings.diffuse_wrap_bias)
        self.settings.setValue("preview/diffuse_light_scale", preview_settings.diffuse_light_scale)
        self.settings.setValue("preview/d3d11_light_azimuth_degrees", preview_settings.d3d11_light_azimuth_degrees)
        self.settings.setValue("preview/d3d11_light_elevation_degrees", preview_settings.d3d11_light_elevation_degrees)
        self.settings.setValue("preview/orbit_sensitivity", preview_settings.orbit_sensitivity)
        self.settings.setValue("preview/pan_sensitivity", preview_settings.pan_sensitivity)
        self.settings.setValue("preview/invert_orbit_x", preview_settings.invert_orbit_x)
        self.settings.setValue("preview/invert_orbit_y", preview_settings.invert_orbit_y)
        self.settings.setValue("preview/invert_pan_x", preview_settings.invert_pan_x)
        self.settings.setValue("preview/invert_pan_y", preview_settings.invert_pan_y)
        self.settings.setValue("preview/normal_strength_cap", preview_settings.normal_strength_cap)
        self.settings.setValue("preview/normal_strength_floor", preview_settings.normal_strength_floor)
        self.settings.setValue("preview/height_effect_max", preview_settings.height_effect_max)
        self.settings.setValue("preview/cavity_clamp_min", preview_settings.cavity_clamp_min)
        self.settings.setValue("preview/cavity_clamp_max", preview_settings.cavity_clamp_max)
        self.settings.setValue("preview/specular_base", preview_settings.specular_base)
        self.settings.setValue("preview/specular_min", preview_settings.specular_min)
        self.settings.setValue("preview/specular_max", preview_settings.specular_max)
        self.settings.setValue("preview/shininess_base", preview_settings.shininess_base)
        self.settings.setValue("preview/shininess_min", preview_settings.shininess_min)
        self.settings.setValue("preview/shininess_max", preview_settings.shininess_max)
        self.settings.setValue("preview/height_shininess_boost", preview_settings.height_shininess_boost)
        self.settings.setValue("preview/d3d11_ao_strength", preview_settings.d3d11_ao_strength)
        self.settings.setValue("preview/d3d11_roughness_bias", preview_settings.d3d11_roughness_bias)
        self.settings.setValue("preview/d3d11_metalness_scale", preview_settings.d3d11_metalness_scale)
        self.settings.setValue("preview/d3d11_environment_strength", preview_settings.d3d11_environment_strength)
        self.settings.setValue("preview/d3d11_emissive_gain", preview_settings.d3d11_emissive_gain)
        self.settings.setValue("preview/d3d11_tone_exposure", preview_settings.d3d11_tone_exposure)
        self.settings.setValue("preview/d3d11_tone_contrast", preview_settings.d3d11_tone_contrast)
        self.settings.setValue("preview/d3d11_tone_gamma", preview_settings.d3d11_tone_gamma)
        self.settings.setValue("dds_output/format_mode", self._combo_value(self.dds_format_mode_combo))
        self.settings.setValue("dds_output/custom_format", self._combo_value(self.dds_custom_format_combo))
        self.settings.setValue("dds_output/size_mode", self._combo_value(self.dds_size_mode_combo))
        self.settings.setValue("dds_output/custom_width", self.dds_custom_width_spin.value())
        self.settings.setValue("dds_output/custom_height", self.dds_custom_height_spin.value())
        self.settings.setValue("dds_output/mip_mode", self._combo_value(self.dds_mip_mode_combo))
        self.settings.setValue("dds_output/custom_mip_count", self.dds_custom_mip_spin.value())
        self.settings.setValue("settings/dry_run", self.dry_run_checkbox.isChecked())
        self.settings.setValue("settings/enable_dds_staging", self.enable_dds_staging_checkbox.isChecked())
        self.settings.setValue("settings/enable_incremental_resume", self.enable_incremental_resume_checkbox.isChecked())
        self.settings.setValue("settings/csv_log_enabled", self.csv_log_enabled_checkbox.isChecked())
        self.settings.setValue("settings/csv_log_path", self.csv_log_path_edit.text())
        self.settings.setValue(
            "settings/allow_unique_basename_fallback",
            self.unique_basename_checkbox.isChecked(),
        )
        self.settings.setValue(
            "settings/overwrite_existing_dds",
            self.overwrite_existing_checkbox.isChecked(),
        )
        self.settings.setValue("settings/include_filters", self.filters_edit.toPlainText())
        self.settings.setValue("settings/texture_rules_text", self.texture_rules_legacy_text)
        self.settings.setValue(
            "settings/workflow_profiles_json",
            json.dumps([dataclasses.asdict(profile) for profile in self.workflow_profiles_state], indent=2),
        )
        self.settings.setValue(
            "settings/workflow_rules_json",
            json.dumps([dataclasses.asdict(rule) for rule in self.texture_rules_state], indent=2),
        )
        current_upscale_backend = self._current_upscale_backend()
        self.settings.setValue("upscale/backend", current_upscale_backend)
        self.settings.setValue("chainner/enabled", current_upscale_backend == UPSCALE_BACKEND_CHAINNER)
        self.settings.setValue("chainner/exe_path", self.chainner_exe_path_edit.text())
        self.settings.setValue("chainner/chain_path", self.chainner_chain_path_edit.text())
        self.settings.setValue("chainner/override_json", self.chainner_override_edit.toPlainText())
        self.settings.setValue("ncnn/exe_path", self.ncnn_exe_path_edit.text())
        self.settings.setValue("ncnn/model_dir", self.ncnn_model_dir_edit.text())
        self.settings.setValue("ncnn/model_name", self._combo_value(self.ncnn_model_combo))
        self.settings.setValue("ncnn/scale", self.ncnn_scale_spin.value())
        self.settings.setValue("ncnn/tile_size", self.ncnn_tile_size_spin.value())
        self.settings.setValue("ncnn/extra_args", self.ncnn_extra_args_edit.text())
        self.settings.setValue("upscale/post_correction_mode", self._combo_value(self.upscale_post_correction_combo))
        self.settings.setValue("ncnn/texture_preset", self._combo_value(self.upscale_texture_preset_combo))
        self.settings.setValue("upscale/automatic_texture_rules", self.enable_automatic_texture_rules_checkbox.isChecked())
        self.settings.setValue("upscale/unsafe_technical_override", self.enable_unsafe_technical_override_checkbox.isChecked())
        self.settings.setValue("upscale/retry_smaller_tile", self.retry_smaller_tile_checkbox.isChecked())
        self.settings.setValue("upscale/mod_ready_loose_export", self.enable_mod_ready_loose_export_checkbox.isChecked())
        self.settings.setValue("upscale/mod_ready_export_root", self.mod_ready_export_root_edit.text())
        self.settings.setValue("upscale/mod_ready_create_no_encrypt", self.mod_ready_create_no_encrypt_checkbox.isChecked())
        self.settings.setValue("upscale/mod_ready_package_title", self.mod_ready_package_title_edit.text())
        self.settings.setValue("upscale/mod_ready_package_version", self.mod_ready_package_version_edit.text())
        self.settings.setValue("upscale/mod_ready_package_author", self.mod_ready_package_author_edit.text())
        self.settings.setValue("upscale/mod_ready_package_description", self.mod_ready_package_description_edit.text())
        self.settings.setValue("upscale/mod_ready_package_nexus_url", self.mod_ready_package_nexus_url_edit.text())
        self.settings.setValue("upscale/mod_ready_manager_profile", self._combo_value(self.mod_ready_manager_combo))
        self.settings.setValue(
            "upscale/mod_ready_manager_profiles",
            json.dumps(
                [
                    profile
                    for profile, checkbox in self.mod_ready_profile_checkboxes.items()
                    if checkbox.isChecked()
                ],
                separators=(",", ":"),
            ),
        )
        self.settings.setValue("upscale/mod_ready_package_structure", self._combo_value(self.mod_ready_structure_combo))
        self.settings.setValue("upscale/mod_ready_manifest_json", self.mod_ready_manifest_checkbox.isChecked())
        self.settings.setValue("upscale/mod_ready_mod_json", self.mod_ready_mod_json_checkbox.isChecked())
        self.settings.setValue("upscale/mod_ready_modinfo_json", self.mod_ready_modinfo_checkbox.isChecked())
        self.settings.setValue("upscale/mod_ready_info_json", self.mod_ready_info_json_checkbox.isChecked())
        self.settings.setValue("upscale/mod_ready_zip", self.mod_ready_zip_checkbox.isChecked())
        self.settings.setValue("upscale/mod_ready_conflict_mode", self._combo_value(self.mod_ready_conflict_mode_combo))
        self.settings.setValue("upscale/mod_ready_target_language", self.mod_ready_target_language_edit.text())
        current_key = self._tool_key_for_widget(self._current_navigation_widget())
        self.settings.setValue("ui/active_tool_key", current_key or "archive_browser")
        self.settings.setValue("ui/main_tab_index", self.main_tabs.currentIndex())
        self.settings.setValue("ui/compare_sync_pan", self.compare_sync_pan_checkbox.isChecked())
        self.settings.setValue("ui/compare_preview_size_mode", self._combo_value(self.compare_preview_size_combo))
        if self._preference_bool("remember_splitter_sizes", True):
            self.settings.setValue("ui/workflow_splitter_sizes", ",".join(str(value) for value in self.workflow_splitter.sizes()))
            workflow_right_sizes = (
                self.workflow_right_splitter_normal_sizes
                if self.progress_group.isHidden() and self.workflow_right_splitter_normal_sizes
                else self.workflow_right_splitter.sizes()
            )
            self.settings.setValue(
                "ui/workflow_right_splitter_sizes_v2",
                ",".join(str(value) for value in workflow_right_sizes),
            )
            self.settings.setValue(
                "ui/compare_splitter_sizes_v2",
                ",".join(str(value) for value in self.compare_splitter.sizes()),
            )
            self.settings.setValue("ui/archive_splitter_sizes", ",".join(str(value) for value in self.archive_splitter.sizes()))
            self.settings.setValue("ui/text_search_splitter_sizes", ",".join(str(value) for value in self.text_search_tab.splitter_sizes()))
            self.settings.setValue(
                "ui/replace_assistant_splitter_sizes",
                ",".join(str(value) for value in self.replace_assistant_tab.splitter_sizes()),
            )
            self.settings.setValue(
                "ui/research_main_splitter_sizes",
                ",".join(str(value) for value in self.research_tab.main_splitter_sizes()),
            )
            self.settings.setValue(
                "ui/research_groups_splitter_sizes",
                ",".join(str(value) for value in self.research_tab.groups_splitter_sizes()),
            )
            self.settings.setValue(
                "ui/research_unknown_splitter_sizes",
                ",".join(str(value) for value in self.research_tab.unknown_splitter_sizes()),
            )
            self.settings.setValue(
                "ui/research_reference_splitter_sizes",
                ",".join(str(value) for value in self.research_tab.reference_splitter_sizes()),
            )
            self.settings.setValue(
                "ui/research_analysis_splitter_sizes",
                ",".join(str(value) for value in self.research_tab.analysis_splitter_sizes()),
            )
            self.settings.setValue(
                "ui/research_notes_splitter_sizes",
                ",".join(str(value) for value in self.research_tab.notes_splitter_sizes()),
            )
        self.settings.setValue("sections/setup_expanded", self.setup_section.toggle_button.isChecked())
        self.settings.setValue("sections/paths_expanded", self.paths_section.toggle_button.isChecked())
        self.settings.setValue("sections/archive_locations_expanded", self.archive_locations_section.toggle_button.isChecked())
        self.settings.setValue("sections/settings_expanded", self.settings_section.toggle_button.isChecked())
        self.settings.setValue("sections/asset_authoring_expanded", self.asset_authoring_section.toggle_button.isChecked())
        self.settings.setValue("sections/dds_output_expanded", self.dds_output_section.toggle_button.isChecked())
        self.settings.setValue("sections/filters_expanded", self.filters_section.toggle_button.isChecked())
        self.settings.setValue("sections/chainner_expanded", self.chainner_section.toggle_button.isChecked())
        self._save_detached_tool_geometries()
        self.settings.sync()

    def schedule_settings_save(self, *_args) -> None:
        if (
            not self._settings_ready
            or self._shutting_down
            or getattr(self, "_applying_responsive_layout", False)
        ):
            return
        self._settings_save_timer.start()

    def flush_settings_save(self) -> None:
        if self._settings_save_timer.isActive():
            self._settings_save_timer.stop()
        self._save_settings()

    def _load_settings(self) -> None:
        defaults = default_config()
        self.current_theme_key = str(self.settings.value("appearance/theme", self.current_theme_key or DEFAULT_UI_THEME))
        if self.current_theme_key not in UI_THEME_SCHEMES:
            self.current_theme_key = DEFAULT_UI_THEME
        self.original_dds_edit.setText(
            self.settings.value("paths/original_dds_root", defaults.original_dds_root)
        )
        self.png_root_edit.setText(self.settings.value("paths/png_root", defaults.png_root))
        self.texture_editor_png_root_edit.setText(
            self.settings.value("paths/texture_editor_png_root", getattr(defaults, "texture_editor_png_root", ""))
        )
        self.dds_staging_root_edit.setText(self.settings.value("paths/dds_staging_root", defaults.dds_staging_root))
        self.output_root_edit.setText(self.settings.value("paths/output_root", defaults.output_root))
        self.texconv_path_edit.setText(self.settings.value("paths/texconv_path", defaults.texconv_path))
        self.material_maker_project_edit.setText(
            str(self.settings.value("asset_authoring/material_maker_project_path", "") or "")
        )
        self.material_maker_export_dir_edit.setText(
            str(self.settings.value("asset_authoring/material_maker_export_dir", "") or "")
        )
        self.openimageio_source_path_edit.setText(
            str(self.settings.value("asset_authoring/oiio_source_path", "") or "")
        )
        self.openimageio_output_path_edit.setText(
            str(self.settings.value("asset_authoring/oiio_output_path", "") or "")
        )
        self.openimageio_compare_path_edit.setText(
            str(self.settings.value("asset_authoring/oiio_compare_path", "") or "")
        )
        self.archive_package_root_edit.setText(self.settings.value("archive/package_root", defaults.archive_package_root))
        self.archive_extract_root_edit.setText(self.settings.value("archive/extract_root", defaults.archive_extract_root))
        archive_filter_text = defaults.archive_filter_text
        archive_exclude_filter_text = defaults.archive_exclude_filter_text
        archive_extension_filter = "*"
        archive_package_filter_text = defaults.archive_package_filter_text
        archive_structure_filter = defaults.archive_structure_filter
        archive_role_filter = defaults.archive_role_filter
        self.archive_filter_edit.setText(archive_filter_text)
        self.archive_exclude_filter_edit.setText(archive_exclude_filter_text)
        self._rebuild_archive_extension_filter_choices(
            archive_extension_filter
        )
        self._set_combo_by_value(
            self.archive_extension_filter_combo,
            archive_extension_filter,
        )
        self.archive_package_filter_edit.setText(archive_package_filter_text)
        self.archive_structure_filter_pending_value = str(archive_structure_filter)
        self._set_combo_by_value(
            self.archive_role_filter_combo,
            archive_role_filter,
        )
        self.archive_exclude_common_technical_checkbox.setChecked(defaults.archive_exclude_common_technical_suffixes)
        self.archive_min_size_spin.setValue(int(defaults.archive_min_size_kb))
        self.archive_previewable_only_checkbox.setChecked(bool(defaults.archive_previewable_only))
        self._set_combo_by_value(self.archive_browser_view_mode_combo, ARCHIVE_BROWSER_VIEW_MODE)
        self.archive_tree_sort_column = normalize_archive_browser_sort_column(
            self.settings.value("ui/archive_tree_v4_sort_column", -1)
        )
        self.archive_tree_sort_order = normalize_archive_browser_sort_order(
            self.settings.value("ui/archive_tree_v4_sort_order", "asc")
        )
        self._update_archive_tree_sort_indicator()
        self._model_preview_render_settings = self._read_model_preview_render_settings()
        self.archive_model_renderer_backend = self._read_archive_model_renderer_backend()
        dark_background = self._read_bool("archive/model_preview_dark_background", True)
        self.archive_model_preview_dark_background_enabled = bool(dark_background)
        self.archive_model_preview.set_dark_background_enabled(dark_background)
        self._archive_performance_settings = self._read_archive_performance_settings()
        self.archive_preview_cache_limit = self._archive_performance_settings.preview_cache_limit
        size_mode_value = self.settings.value("dds_output/size_mode")
        if size_mode_value is None:
            old_keep_original_size = self._read_bool("settings/keep_original_size", False)
            size_mode_value = DDS_SIZE_MODE_ORIGINAL if old_keep_original_size else defaults.dds_size_mode
        self._set_combo_by_value(
            self.dds_format_mode_combo,
            str(self.settings.value("dds_output/format_mode", defaults.dds_format_mode)),
        )
        self._set_combo_by_value(
            self.dds_custom_format_combo,
            str(self.settings.value("dds_output/custom_format", defaults.dds_custom_format)),
        )
        self._set_combo_by_value(self.dds_size_mode_combo, str(size_mode_value))
        self.dds_custom_width_spin.setValue(
            int(self.settings.value("dds_output/custom_width", defaults.dds_custom_width))
        )
        self.dds_custom_height_spin.setValue(
            int(self.settings.value("dds_output/custom_height", defaults.dds_custom_height))
        )
        self._set_combo_by_value(
            self.dds_mip_mode_combo,
            str(self.settings.value("dds_output/mip_mode", defaults.dds_mip_mode)),
        )
        self.dds_custom_mip_spin.setValue(
            int(self.settings.value("dds_output/custom_mip_count", defaults.dds_custom_mip_count))
        )
        self.dry_run_checkbox.setChecked(self._read_bool("settings/dry_run", defaults.dry_run))
        self.enable_dds_staging_checkbox.setChecked(
            self._read_bool("settings/enable_dds_staging", defaults.enable_dds_staging)
        )
        self.enable_incremental_resume_checkbox.setChecked(
            self._read_bool("settings/enable_incremental_resume", defaults.enable_incremental_resume)
        )
        self.csv_log_enabled_checkbox.setChecked(
            self._read_bool("settings/csv_log_enabled", defaults.csv_log_enabled)
        )
        self.csv_log_path_edit.setText(
            self.settings.value("settings/csv_log_path", defaults.csv_log_path)
        )
        self.unique_basename_checkbox.setChecked(
            self._read_bool(
                "settings/allow_unique_basename_fallback",
                defaults.allow_unique_basename_fallback,
            )
        )
        self.overwrite_existing_checkbox.setChecked(
            self._read_bool("settings/overwrite_existing_dds", defaults.overwrite_existing_dds)
        )
        self.filters_edit.setPlainText(
            self.settings.value("settings/include_filters", defaults.include_filters)
        )
        legacy_texture_rules_text = str(
            self.settings.value("settings/texture_rules_text", getattr(defaults, "texture_rules_text", ""))
            or ""
        )
        workflow_profiles_json = str(self.settings.value("settings/workflow_profiles_json", "") or "")
        workflow_rules_json = str(self.settings.value("settings/workflow_rules_json", "") or "")
        loaded_workflow_profiles: Sequence[object] = ()
        loaded_workflow_rules: Sequence[object] = ()
        if workflow_profiles_json.strip():
            try:
                parsed_profiles = json.loads(workflow_profiles_json)
                if isinstance(parsed_profiles, list):
                    loaded_workflow_profiles = parsed_profiles
            except Exception:
                loaded_workflow_profiles = ()
        if workflow_rules_json.strip():
            try:
                parsed_rules = json.loads(workflow_rules_json)
                if isinstance(parsed_rules, list):
                    loaded_workflow_rules = parsed_rules
            except Exception:
                loaded_workflow_rules = ()
        self.texture_rules_legacy_text = legacy_texture_rules_text
        self.workflow_profiles_state = list(coerce_texture_workflow_profiles(loaded_workflow_profiles))
        self.texture_rules_state = list(coerce_texture_workflow_rules(loaded_workflow_rules))
        if not self.workflow_profiles_state and not self.texture_rules_state and legacy_texture_rules_text.strip():
            migrated_profiles, migrated_rules = migrate_legacy_texture_rules_to_structured(legacy_texture_rules_text)
            self.workflow_profiles_state = list(migrated_profiles)
            self.texture_rules_state = list(migrated_rules)
        elif should_seed_default_texture_workflow_state(self.workflow_profiles_state, self.texture_rules_state):
            self.workflow_profiles_state = list(build_default_texture_workflow_profiles())
            self.texture_rules_state = list(build_default_texture_workflow_rules())
        upgraded_profiles, upgraded_rules = upgrade_default_texture_workflow_state(
            self.workflow_profiles_state,
            self.texture_rules_state,
        )
        self.workflow_profiles_state = list(upgraded_profiles)
        self.texture_rules_state = list(upgraded_rules)
        saved_backend = str(self.settings.value("upscale/backend", "") or "").strip()
        if saved_backend not in {
            UPSCALE_BACKEND_NONE,
            UPSCALE_BACKEND_CHAINNER,
            UPSCALE_BACKEND_REALESRGAN_NCNN,
        }:
            saved_backend = UPSCALE_BACKEND_CHAINNER if self._read_bool("chainner/enabled", defaults.enable_chainner) else DEFAULT_UPSCALE_BACKEND
        self._set_combo_by_value(self.upscale_backend_combo, saved_backend)
        self.chainner_exe_path_edit.setText(
            self.settings.value("chainner/exe_path", defaults.chainner_exe_path)
        )
        self.chainner_chain_path_edit.setText(
            self.settings.value("chainner/chain_path", defaults.chainner_chain_path)
        )
        self.chainner_override_edit.setPlainText(
            self.settings.value("chainner/override_json", defaults.chainner_override_json)
        )
        self.ncnn_exe_path_edit.setText(
            self.settings.value("ncnn/exe_path", getattr(defaults, "ncnn_exe_path", REALESRGAN_NCNN_EXE_PATH))
        )
        self.ncnn_model_dir_edit.setText(
            self.settings.value("ncnn/model_dir", getattr(defaults, "ncnn_model_dir", REALESRGAN_NCNN_MODEL_DIR))
        )
        self.ncnn_extra_args_edit.setText(
            str(self.settings.value("ncnn/extra_args", getattr(defaults, "ncnn_extra_args", REALESRGAN_NCNN_EXTRA_ARGS)))
        )
        self.ncnn_scale_spin.setValue(
            int(self.settings.value("ncnn/scale", getattr(defaults, "ncnn_scale", REALESRGAN_NCNN_SCALE)))
        )
        self.ncnn_tile_size_spin.setValue(
            int(self.settings.value("ncnn/tile_size", getattr(defaults, "ncnn_tile_size", REALESRGAN_NCNN_TILE_SIZE)))
        )
        self._set_combo_by_value(
            self.upscale_post_correction_combo,
            str(
                self.settings.value(
                    "upscale/post_correction_mode",
                    getattr(defaults, "upscale_post_correction_mode", DEFAULT_UPSCALE_POST_CORRECTION),
                )
            ),
        )
        self._set_combo_by_value(
            self.upscale_texture_preset_combo,
            str(
                self.settings.value(
                    "ncnn/texture_preset",
                    getattr(defaults, "upscale_texture_preset", DEFAULT_UPSCALE_TEXTURE_PRESET),
                )
            ),
        )
        self._refresh_ncnn_model_picker(
            preferred_name=str(
                self.settings.value(
                    "ncnn/model_name",
                    getattr(defaults, "ncnn_model_name", REALESRGAN_NCNN_MODEL_NAME),
                )
            )
        )
        self.enable_automatic_texture_rules_checkbox.setChecked(
            self._read_bool(
                "upscale/automatic_texture_rules",
                getattr(defaults, "enable_automatic_texture_rules", ENABLE_AUTOMATIC_TEXTURE_RULES),
            )
        )
        self.enable_unsafe_technical_override_checkbox.setChecked(
            self._read_bool(
                "upscale/unsafe_technical_override",
                getattr(defaults, "enable_unsafe_technical_override", ENABLE_UNSAFE_TECHNICAL_OVERRIDE),
            )
        )
        self.retry_smaller_tile_checkbox.setChecked(
            self._read_bool(
                "upscale/retry_smaller_tile",
                getattr(defaults, "retry_smaller_tile_on_failure", RETRY_SMALLER_TILE_ON_FAILURE),
            )
        )
        self.enable_mod_ready_loose_export_checkbox.setChecked(
            self._read_bool(
                "upscale/mod_ready_loose_export",
                getattr(defaults, "enable_mod_ready_loose_export", ENABLE_MOD_READY_LOOSE_EXPORT),
            )
        )
        self.mod_ready_export_root_edit.setText(
            self.settings.value(
                "upscale/mod_ready_export_root",
                getattr(defaults, "mod_ready_export_root", MOD_READY_EXPORT_ROOT),
            )
        )
        self.mod_ready_create_no_encrypt_checkbox.setChecked(
            self._read_bool(
                "upscale/mod_ready_create_no_encrypt",
                getattr(defaults, "mod_ready_create_no_encrypt_file", MOD_READY_CREATE_NO_ENCRYPT),
            )
        )
        self.mod_ready_package_title_edit.setText(
            str(
                self.settings.value(
                    "upscale/mod_ready_package_title",
                    getattr(defaults, "mod_ready_package_title", MOD_READY_PACKAGE_TITLE),
                )
            )
        )
        self.mod_ready_package_version_edit.setText(
            str(
                self.settings.value(
                    "upscale/mod_ready_package_version",
                    getattr(defaults, "mod_ready_package_version", MOD_READY_PACKAGE_VERSION),
                )
            )
        )
        self.mod_ready_package_author_edit.setText(
            str(
                self.settings.value(
                    "upscale/mod_ready_package_author",
                    getattr(defaults, "mod_ready_package_author", MOD_READY_PACKAGE_AUTHOR),
                )
            )
        )
        self.mod_ready_package_description_edit.setText(
            str(
                self.settings.value(
                    "upscale/mod_ready_package_description",
                    getattr(defaults, "mod_ready_package_description", MOD_READY_PACKAGE_DESCRIPTION),
                )
            )
        )
        self.mod_ready_package_nexus_url_edit.setText(
            str(
                self.settings.value(
                    "upscale/mod_ready_package_nexus_url",
                    getattr(defaults, "mod_ready_package_nexus_url", MOD_READY_PACKAGE_NEXUS_URL),
                )
            )
        )
        mod_ready_profile_value = str(
            self.settings.value("upscale/mod_ready_manager_profile", getattr(defaults, "mod_ready_manager_profile", "dmm"))
        )
        mod_ready_profile_defaults = mod_package_export_options_for_manager(mod_ready_profile_value)
        self._set_combo_by_value(
            self.mod_ready_manager_combo,
            mod_ready_profile_value,
        )
        saved_profile_values: List[str] = []
        try:
            loaded_profiles = json.loads(str(self.settings.value("upscale/mod_ready_manager_profiles", "[]") or "[]"))
            if isinstance(loaded_profiles, list):
                saved_profile_values = [
                    str(value or "").strip()
                    for value in loaded_profiles
                    if str(value or "").strip() in MOD_PACKAGE_MANAGER_PROFILES
                ]
        except Exception:
            saved_profile_values = []
        if not saved_profile_values:
            saved_profile_values = [mod_ready_profile_value if mod_ready_profile_value in MOD_PACKAGE_MANAGER_PROFILES else "dmm"]
        for profile, checkbox in self.mod_ready_profile_checkboxes.items():
            checkbox.setChecked(profile in set(saved_profile_values))
        self._set_combo_by_value(
            self.mod_ready_structure_combo,
            str(
                self.settings.value(
                    "upscale/mod_ready_package_structure",
                    getattr(defaults, "mod_ready_package_structure", self._combo_value(self.mod_ready_structure_combo)),
                )
            ),
        )
        self.mod_ready_manifest_checkbox.setChecked(
            self._read_bool(
                "upscale/mod_ready_manifest_json",
                getattr(defaults, "mod_ready_create_manifest_json", mod_ready_profile_defaults.create_manifest_json),
            )
        )
        self.mod_ready_mod_json_checkbox.setChecked(
            self._read_bool(
                "upscale/mod_ready_mod_json",
                getattr(defaults, "mod_ready_create_mod_json", mod_ready_profile_defaults.create_mod_json),
            )
        )
        self.mod_ready_modinfo_checkbox.setChecked(
            self._read_bool(
                "upscale/mod_ready_modinfo_json",
                getattr(defaults, "mod_ready_create_modinfo_json", mod_ready_profile_defaults.create_modinfo_json),
            )
        )
        self.mod_ready_info_json_checkbox.setChecked(
            self._read_bool(
                "upscale/mod_ready_info_json",
                getattr(defaults, "mod_ready_create_info_json", mod_ready_profile_defaults.create_info_json),
            )
        )
        if (
            mod_ready_profile_value.strip().lower() == "universal"
            and not self.settings.contains("upscale/mod_ready_metadata_defaults_minimized")
            and self.settings.contains("upscale/mod_ready_mod_json")
            and self.mod_ready_mod_json_checkbox.isChecked()
            and self.mod_ready_modinfo_checkbox.isChecked()
            and self.mod_ready_info_json_checkbox.isChecked()
        ):
            self.mod_ready_mod_json_checkbox.setChecked(False)
            self.mod_ready_modinfo_checkbox.setChecked(False)
            self.mod_ready_info_json_checkbox.setChecked(False)
            self.settings.setValue("upscale/mod_ready_mod_json", False)
            self.settings.setValue("upscale/mod_ready_modinfo_json", False)
            self.settings.setValue("upscale/mod_ready_info_json", False)
        self.settings.setValue("upscale/mod_ready_metadata_defaults_minimized", True)
        self.mod_ready_zip_checkbox.setChecked(
            self._read_bool("upscale/mod_ready_zip", getattr(defaults, "mod_ready_create_zip", False))
        )
        self._set_combo_by_value(
            self.mod_ready_conflict_mode_combo,
            str(self.settings.value("upscale/mod_ready_conflict_mode", getattr(defaults, "mod_ready_conflict_mode", ""))),
        )
        self.mod_ready_target_language_edit.setText(
            str(self.settings.value("upscale/mod_ready_target_language", getattr(defaults, "mod_ready_target_language", "")))
        )
        self._restore_saved_navigation()
        self.compare_sync_pan_checkbox.setChecked(self._read_bool("ui/compare_sync_pan", False))
        self._set_combo_by_value(
            self.compare_preview_size_combo,
            str(self.settings.value("ui/compare_preview_size_mode", "fit:1.25")),
        )
        self.setup_section.set_expanded(True)
        self.paths_section.set_expanded(self._read_bool("sections/paths_expanded", False))
        self.archive_locations_section.set_expanded(self._read_bool("sections/archive_locations_expanded", False))
        self.settings_section.set_expanded(self._read_bool("sections/settings_expanded", False))
        self.asset_authoring_section.set_expanded(self._read_bool("sections/asset_authoring_expanded", False))
        self.dds_output_section.set_expanded(self._read_bool("sections/dds_output_expanded", False))
        self.filters_section.set_expanded(self._read_bool("sections/filters_expanded", False))
        self.chainner_section.set_expanded(self._read_bool("sections/chainner_expanded", False))
        self._apply_mod_ready_export_state()
        self._refresh_workflow_profile_ncnn_model_combo()
        self._refresh_workflow_profiles_tree()
        self._refresh_workflow_rules_tree()
        self._schedule_workflow_match_refresh()

    def _read_bool(self, key: str, default: bool) -> bool:
        value = self.settings.value(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _read_int(self, key: str, default: int) -> int:
        value = self.settings.value(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def _read_float(self, key: str, default: float) -> float:
        value = self.settings.value(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _apply_csv_log_enabled_state(self) -> None:
        enabled = self.csv_log_enabled_checkbox.isChecked()
        self.csv_log_path_edit.setEnabled(enabled)
        self.csv_log_browse_button.setEnabled(enabled)
        if enabled and not self.csv_log_path_edit.text().strip():
            self.csv_log_path_edit.setText(default_config().csv_log_path)

__all__ = ["SettingsPersistenceMixin"]

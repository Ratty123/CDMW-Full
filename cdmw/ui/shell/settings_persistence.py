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
from cdmw.domain.archives.filters import (
    normalize_archive_browser_sort_column,
    normalize_archive_browser_sort_order,
)
from cdmw.domain.packages.export_policy import MOD_PACKAGE_MANAGER_PROFILES, mod_package_export_options_for_manager
from cdmw.domain.textures.profiles import (
    build_default_texture_workflow_profiles,
    build_default_texture_workflow_rules,
    should_seed_default_texture_workflow_state,
    upgrade_default_texture_workflow_state,
)
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.ui.shell.texture_panel_persistence import (
    load_asset_authoring_panel_settings,
    load_dds_output_panel_settings,
    load_upscale_panel_settings,
    load_workflow_profiles_panel_settings,
    load_workflow_profiles_state,
    load_workflow_settings_panel_settings,
    save_upscale_panel_settings,
)
from cdmw.domain.textures.rules import (
    coerce_texture_workflow_profiles,
    coerce_texture_workflow_rules,
    migrate_legacy_texture_rules_to_structured,
)
from cdmw.models import (
    ArchivePerformanceSettings,
    clamp_archive_performance_settings,
    default_config,
)
from cdmw.ui.archive_performance_settings_io import read_archive_performance_settings
from cdmw.ui.themes import UI_THEME_SCHEMES


_MODEL_PREVIEW_SETTING_KEY_OVERRIDES = {
    "use_textures_by_default": "archive/model_use_textures",
    "high_quality_by_default": "archive/model_high_quality",
    "preview_texture_max_dimension": "preview/texture_max_dimension",
    "low_quality_texture_max_dimension": "preview/low_quality_texture_max_dimension",
}
_MODEL_PREVIEW_SETTINGS_NOT_PERSISTED = {"alignment_use_final_output_preview"}


class SettingsPersistenceMixin:
    """Save and restore main-window settings state."""

    def _save_model_preview_settings_if_loaded(self) -> bool:
        if getattr(self, "_model_preview_settings_read_pending", False):
            return False
        values = dataclasses.asdict(self._current_model_preview_render_settings())
        for attribute in _MODEL_PREVIEW_SETTINGS_NOT_PERSISTED:
            values.pop(attribute, None)
        for attribute, value in values.items():
            key = _MODEL_PREVIEW_SETTING_KEY_OVERRIDES.get(attribute, f"preview/{attribute}")
            self.settings.setValue(key, value)
        return True

    def _current_archive_performance_settings(self) -> ArchivePerformanceSettings:
        return clamp_archive_performance_settings(self._archive_performance_settings)

    def _read_archive_performance_settings(self) -> ArchivePerformanceSettings:
        return read_archive_performance_settings(self.settings)

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
        if self.asset_authoring_section.is_body_built():
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
        self.settings.setValue("ui/archive_tree_v5_sort_column", int(self.archive_tree_sort_column))
        self.settings.setValue("ui/archive_tree_v5_sort_order", self.archive_tree_sort_order)
        self._save_archive_tree_header_settings()
        self._save_model_preview_settings_if_loaded()
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
        if self.dds_output_section.is_body_built():
            self.settings.setValue("dds_output/format_mode", self._combo_value(self.dds_format_mode_combo))
            self.settings.setValue("dds_output/custom_format", self._combo_value(self.dds_custom_format_combo))
            self.settings.setValue("dds_output/size_mode", self._combo_value(self.dds_size_mode_combo))
            self.settings.setValue("dds_output/custom_width", self.dds_custom_width_spin.value())
            self.settings.setValue("dds_output/custom_height", self.dds_custom_height_spin.value())
            self.settings.setValue("dds_output/mip_mode", self._combo_value(self.dds_mip_mode_combo))
            self.settings.setValue("dds_output/custom_mip_count", self.dds_custom_mip_spin.value())
            self.settings.setValue("settings/enable_dds_staging", self.enable_dds_staging_checkbox.isChecked())
        if self.settings_section.is_body_built():
            self.settings.setValue("settings/dry_run", self.dry_run_checkbox.isChecked())
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
        if self.filters_section.is_body_built():
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
        if self.chainner_section.is_body_built():
            save_upscale_panel_settings(self)
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
            text_search_tab = created_tool_widget(getattr(self, "text_search_tab", None))
            if text_search_tab is not None:
                self.settings.setValue(
                    "ui/text_search_splitter_sizes",
                    ",".join(str(value) for value in text_search_tab.splitter_sizes()),
                )
            replace_assistant_tab = created_tool_widget(getattr(self, "replace_assistant_tab", None))
            if replace_assistant_tab is not None:
                self.settings.setValue(
                    "ui/replace_assistant_splitter_sizes",
                    ",".join(str(value) for value in replace_assistant_tab.splitter_sizes()),
                )
            research_tab = created_tool_widget(getattr(self, "research_tab", None))
            if research_tab is not None:
                for key, getter_name in (
                    ("ui/research_main_splitter_sizes", "main_splitter_sizes"),
                    ("ui/research_groups_splitter_sizes", "groups_splitter_sizes"),
                    ("ui/research_unknown_splitter_sizes", "unknown_splitter_sizes"),
                    ("ui/research_reference_splitter_sizes", "reference_splitter_sizes"),
                    ("ui/research_analysis_splitter_sizes", "analysis_splitter_sizes"),
                    ("ui/research_notes_splitter_sizes", "notes_splitter_sizes"),
                ):
                    values = getattr(research_tab, getter_name)()
                    self.settings.setValue(key, ",".join(str(value) for value in values))
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
        if self.asset_authoring_section.is_body_built():
            load_asset_authoring_panel_settings(self, defaults)
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
            self.settings.value("ui/archive_tree_v5_sort_column", -1)
        )
        self.archive_tree_sort_order = normalize_archive_browser_sort_order(
            self.settings.value("ui/archive_tree_v5_sort_order", "asc")
        )
        self._update_archive_tree_sort_indicator()
        self._model_preview_settings_read_pending = True
        self._archive_preview_startup_state_pending = True
        self.archive_model_renderer_backend = self._read_archive_model_renderer_backend()
        dark_background = self._read_bool("archive/model_preview_dark_background", True)
        self.archive_model_preview_dark_background_enabled = bool(dark_background)
        self.archive_model_preview.set_dark_background_enabled(dark_background)
        self._archive_performance_settings = self._read_archive_performance_settings()
        self.archive_preview_cache_limit = self._archive_performance_settings.preview_cache_limit
        if self.dds_output_section.is_body_built():
            load_dds_output_panel_settings(self, defaults)
        if self.settings_section.is_body_built():
            load_workflow_settings_panel_settings(self, defaults)
        load_workflow_profiles_state(self, defaults)
        if self.filters_section.is_body_built():
            load_workflow_profiles_panel_settings(self, defaults)
        if self.chainner_section.is_body_built():
            load_upscale_panel_settings(self, defaults)
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
        if self.chainner_section.is_body_built():
            self._apply_mod_ready_export_state()
        if self.filters_section.is_body_built():
            if self.chainner_section.is_body_built():
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
        if not self.settings_section.is_body_built():
            return
        enabled = self.csv_log_enabled_checkbox.isChecked()
        self.csv_log_path_edit.setEnabled(enabled)
        self.csv_log_browse_button.setEnabled(enabled)
        if enabled and not self.csv_log_path_edit.text().strip():
            self.csv_log_path_edit.setText(default_config().csv_log_path)

__all__ = ["SettingsPersistenceMixin"]

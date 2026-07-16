"""Texture workflow AppConfig collection helpers."""

from __future__ import annotations

from cdmw.constants import UPSCALE_BACKEND_CHAINNER
from cdmw.domain.packages.export_policy import (
    mod_package_export_options_for_profiles,
    mod_package_profile_uses_manager_metadata,
)
from cdmw.models import AppConfig


class TextureWorkflowConfigCollectionMixin:
    """Collect the current texture workflow and archive filter UI state."""
    def collect_config(self) -> AppConfig:
        for section in (
            self.settings_section,
            self.dds_output_section,
            self.filters_section,
            self.chainner_section,
        ):
            section.ensure_body_built()
        mod_ready_manager_profiles = tuple(
            profile
            for profile, checkbox in self.mod_ready_profile_checkboxes.items()
            if checkbox.isChecked()
        )
        mod_ready_manager_profile = (
            mod_ready_manager_profiles[0]
            if mod_ready_manager_profiles
            else self._combo_value(self.mod_ready_manager_combo)
        )
        if not mod_ready_manager_profiles:
            mod_ready_manager_profiles = (mod_ready_manager_profile,)
        mod_ready_uses_manager_metadata = any(
            mod_package_profile_uses_manager_metadata(profile)
            for profile in mod_ready_manager_profiles
        )
        mod_ready_auto_options = mod_package_export_options_for_profiles(
            mod_ready_manager_profiles,
            create_zip=self.mod_ready_zip_checkbox.isChecked(),
            conflict_mode=self._combo_value(self.mod_ready_conflict_mode_combo) if mod_ready_uses_manager_metadata else "",
            target_language=self.mod_ready_target_language_edit.text().strip() if mod_ready_uses_manager_metadata else "",
        )
        return AppConfig(
            original_dds_root=self.original_dds_edit.text().strip(),
            png_root=self.png_root_edit.text().strip(),
            texture_editor_png_root=self.texture_editor_png_root_edit.text().strip(),
            dds_staging_root=self.dds_staging_root_edit.text().strip(),
            output_root=self.output_root_edit.text().strip(),
            dds_format_mode=self._combo_value(self.dds_format_mode_combo),
            dds_custom_format=self._combo_value(self.dds_custom_format_combo),
            dds_size_mode=self._combo_value(self.dds_size_mode_combo),
            dds_custom_width=self.dds_custom_width_spin.value(),
            dds_custom_height=self.dds_custom_height_spin.value(),
            dds_mip_mode=self._combo_value(self.dds_mip_mode_combo),
            dds_custom_mip_count=self.dds_custom_mip_spin.value(),
            enable_dds_staging=self.enable_dds_staging_checkbox.isChecked(),
            enable_incremental_resume=self.enable_incremental_resume_checkbox.isChecked(),
            texture_rules_text=self.texture_rules_legacy_text,
            texture_rules=tuple(self.texture_rules_state),
            workflow_profiles=tuple(self.workflow_profiles_state),
            dry_run=self.dry_run_checkbox.isChecked(),
            csv_log_enabled=self.csv_log_enabled_checkbox.isChecked(),
            csv_log_path=self.csv_log_path_edit.text().strip(),
            allow_unique_basename_fallback=self.unique_basename_checkbox.isChecked(),
            overwrite_existing_dds=self.overwrite_existing_checkbox.isChecked(),
            include_filters=self.filters_edit.toPlainText(),
            upscale_backend=self._current_upscale_backend(),
            enable_chainner=self._current_upscale_backend() == UPSCALE_BACKEND_CHAINNER,
            chainner_exe_path=self.chainner_exe_path_edit.text().strip(),
            chainner_chain_path=self.chainner_chain_path_edit.text().strip(),
            chainner_override_json=self.chainner_override_edit.toPlainText(),
            ncnn_exe_path=self.ncnn_exe_path_edit.text().strip(),
            ncnn_model_dir=self.ncnn_model_dir_edit.text().strip(),
            ncnn_model_name=self._combo_value(self.ncnn_model_combo),
            ncnn_scale=self.ncnn_scale_spin.value(),
            ncnn_tile_size=self.ncnn_tile_size_spin.value(),
            ncnn_extra_args=self.ncnn_extra_args_edit.text().strip(),
            upscale_post_correction_mode=self._combo_value(self.upscale_post_correction_combo),
            upscale_texture_preset=self._combo_value(self.upscale_texture_preset_combo),
            enable_automatic_texture_rules=self.enable_automatic_texture_rules_checkbox.isChecked(),
            enable_unsafe_technical_override=self.enable_unsafe_technical_override_checkbox.isChecked(),
            retry_smaller_tile_on_failure=self.retry_smaller_tile_checkbox.isChecked(),
            enable_mod_ready_loose_export=self.enable_mod_ready_loose_export_checkbox.isChecked(),
            mod_ready_export_root=self.mod_ready_export_root_edit.text().strip(),
            mod_ready_create_no_encrypt_file=self.mod_ready_create_no_encrypt_checkbox.isChecked(),
            mod_ready_package_title=self.mod_ready_package_title_edit.text().strip(),
            mod_ready_package_version=self.mod_ready_package_version_edit.text().strip(),
            mod_ready_package_author=self.mod_ready_package_author_edit.text().strip(),
            mod_ready_package_description=self.mod_ready_package_description_edit.text().strip(),
            mod_ready_package_nexus_url=self.mod_ready_package_nexus_url_edit.text().strip(),
            mod_ready_manager_profile=mod_ready_manager_profile,
            mod_ready_manager_profiles=mod_ready_manager_profiles,
            mod_ready_package_structure=mod_ready_auto_options.structure,
            mod_ready_create_manifest_json=mod_ready_auto_options.create_manifest_json,
            mod_ready_create_mod_json=mod_ready_auto_options.create_mod_json,
            mod_ready_create_modinfo_json=mod_ready_auto_options.create_modinfo_json,
            mod_ready_create_info_json=mod_ready_auto_options.create_info_json,
            mod_ready_create_zip=mod_ready_auto_options.create_zip,
            mod_ready_conflict_mode=self._combo_value(self.mod_ready_conflict_mode_combo) if mod_ready_uses_manager_metadata else "",
            mod_ready_target_language=self.mod_ready_target_language_edit.text().strip() if mod_ready_uses_manager_metadata else "",
            archive_package_root=self.archive_package_root_edit.text().strip(),
            archive_extract_root=self.archive_extract_root_edit.text().strip(),
            archive_filter_text=self.archive_filter_edit.text().strip(),
            archive_exclude_filter_text=self.archive_exclude_filter_edit.text().strip(),
            archive_extension_filter=self._combo_value(self.archive_extension_filter_combo),
            archive_package_filter_text=self.archive_package_filter_edit.text().strip(),
            archive_structure_filter=self._current_archive_structure_filter_value(),
            archive_role_filter=self._combo_value(self.archive_role_filter_combo),
            archive_exclude_common_technical_suffixes=self.archive_exclude_common_technical_checkbox.isChecked(),
            archive_min_size_kb=self.archive_min_size_spin.value(),
            archive_previewable_only=self.archive_previewable_only_checkbox.isChecked(),
            archive_browser_view_mode=self._archive_browser_view_mode(),
        )

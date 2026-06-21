from __future__ import annotations

import json
from typing import List

from cdmw.constants import (
    DEFAULT_UPSCALE_POST_CORRECTION,
    DEFAULT_UPSCALE_TEXTURE_PRESET,
    REALESRGAN_NCNN_EXTRA_ARGS,
    REALESRGAN_NCNN_MODEL_DIR,
    REALESRGAN_NCNN_MODEL_NAME,
    REALESRGAN_NCNN_SCALE,
    REALESRGAN_NCNN_TILE_SIZE,
)
from cdmw.core.mod_package import MOD_PACKAGE_MANAGER_PROFILES, mod_package_export_options_for_manager
from cdmw.services.workspace_layout import workspace_paths


class ReplaceAssistantSettingsMixin:
    def schedule_settings_save(self) -> None:
        if not self._settings_ready:
            return
        self._settings_save_timer.start()

    def flush_settings_save(self) -> None:
        if self._settings_ready:
            self._save_settings()

    def _save_settings(self) -> None:
        if not self._settings_ready:
            return
        self.settings.setValue("replace_assistant/build_mode", self._combo_value(self.build_mode_combo))
        self.settings.setValue("replace_assistant/size_mode", self._combo_value(self.size_mode_combo))
        self.settings.setValue("replace_assistant/package_output_root", self.package_output_root_edit.text())
        self.settings.setValue("replace_assistant/overwrite_existing", self.overwrite_package_checkbox.isChecked())
        self.settings.setValue("replace_assistant/create_no_encrypt", self.create_no_encrypt_checkbox.isChecked())
        self.settings.setValue("replace_assistant/package_title", self.package_title_edit.text())
        self.settings.setValue("replace_assistant/package_version", self.package_version_edit.text())
        self.settings.setValue("replace_assistant/package_author", self.package_author_edit.text())
        self.settings.setValue("replace_assistant/package_description", self.package_description_edit.text())
        self.settings.setValue("replace_assistant/package_nexus", self.package_nexus_edit.text())
        self.settings.setValue("replace_assistant/package_manager_profile", self._combo_value(self.package_manager_combo))
        self.settings.setValue(
            "replace_assistant/package_manager_profiles",
            json.dumps(
                [
                    profile
                    for profile, checkbox in self.package_profile_checkboxes.items()
                    if checkbox.isChecked()
                ],
                separators=(",", ":"),
            ),
        )
        self.settings.setValue("replace_assistant/package_structure", self._combo_value(self.package_structure_combo))
        self.settings.setValue("replace_assistant/package_manifest_json", self.package_manifest_checkbox.isChecked())
        self.settings.setValue("replace_assistant/package_mod_json", self.package_mod_json_checkbox.isChecked())
        self.settings.setValue("replace_assistant/package_modinfo_json", self.package_modinfo_checkbox.isChecked())
        self.settings.setValue("replace_assistant/package_info_json", self.package_info_json_checkbox.isChecked())
        self.settings.setValue("replace_assistant/package_zip", self.package_zip_checkbox.isChecked())
        self.settings.setValue("replace_assistant/package_conflict_mode", self._combo_value(self.package_conflict_mode_combo))
        self.settings.setValue("replace_assistant/package_target_language", self.package_target_language_edit.text())
        self.settings.setValue("replace_assistant/ncnn_exe_path", self.ncnn_exe_path_edit.text())
        self.settings.setValue("replace_assistant/ncnn_model_dir", self.ncnn_model_dir_edit.text())
        self.settings.setValue("replace_assistant/ncnn_model_name", self._combo_value(self.ncnn_model_combo))
        self.settings.setValue("replace_assistant/ncnn_scale", self.ncnn_scale_spin.value())
        self.settings.setValue("replace_assistant/ncnn_tile_size", self.ncnn_tile_size_spin.value())
        self.settings.setValue("replace_assistant/ncnn_extra_args", self.ncnn_extra_args_edit.text())
        self.settings.setValue("replace_assistant/post_correction", self._combo_value(self.upscale_post_correction_combo))
        self.settings.setValue("replace_assistant/texture_preset", self._combo_value(self.upscale_texture_preset_combo))
        self.settings.setValue("replace_assistant/automatic_rules", self.enable_automatic_texture_rules_checkbox.isChecked())
        self.settings.setValue("replace_assistant/unsafe_override", self.enable_unsafe_technical_override_checkbox.isChecked())
        self.settings.setValue("replace_assistant/retry_smaller_tile", self.retry_smaller_tile_checkbox.isChecked())

    def _load_settings(self) -> None:
        self._set_combo_by_value(self.build_mode_combo, str(self.settings.value("replace_assistant/build_mode", "rebuild_only")))
        self._set_combo_by_value(self.size_mode_combo, str(self.settings.value("replace_assistant/size_mode", "use_edited_size")))
        default_output_root = workspace_paths(self.base_dir)["workspace_root"] / "outputs" / "texture_replacer"
        self.package_output_root_edit.setText(
            str(self.settings.value("replace_assistant/package_output_root", str(default_output_root.resolve())))
        )
        self.overwrite_package_checkbox.setChecked(bool(self.settings.value("replace_assistant/overwrite_existing", True)))
        package_profile_value = str(self.settings.value("replace_assistant/package_manager_profile", "dmm"))
        package_profile_defaults = mod_package_export_options_for_manager(package_profile_value)
        self.create_no_encrypt_checkbox.setChecked(
            bool(self.settings.value("replace_assistant/create_no_encrypt", package_profile_defaults.create_no_encrypt_file))
        )
        self.package_title_edit.setText(str(self.settings.value("replace_assistant/package_title", "Crimson Desert Mod Workbench Mod")))
        self.package_version_edit.setText(str(self.settings.value("replace_assistant/package_version", "1.0")))
        self.package_author_edit.setText(str(self.settings.value("replace_assistant/package_author", "")))
        self.package_description_edit.setText(str(self.settings.value("replace_assistant/package_description", "")))
        self.package_nexus_edit.setText(str(self.settings.value("replace_assistant/package_nexus", "")))
        self._set_combo_by_value(
            self.package_manager_combo,
            package_profile_value,
        )
        saved_profile_values: List[str] = []
        try:
            loaded_profiles = json.loads(str(self.settings.value("replace_assistant/package_manager_profiles", "[]") or "[]"))
            if isinstance(loaded_profiles, list):
                saved_profile_values = [
                    str(value or "").strip()
                    for value in loaded_profiles
                    if str(value or "").strip() in MOD_PACKAGE_MANAGER_PROFILES
                ]
        except Exception:
            saved_profile_values = []
        if not saved_profile_values:
            saved_profile_values = [package_profile_value if package_profile_value in MOD_PACKAGE_MANAGER_PROFILES else "dmm"]
        for profile, checkbox in self.package_profile_checkboxes.items():
            checkbox.setChecked(profile in set(saved_profile_values))
        self._set_combo_by_value(
            self.package_structure_combo,
            str(self.settings.value("replace_assistant/package_structure", self._combo_value(self.package_structure_combo))),
        )
        self.package_manifest_checkbox.setChecked(
            bool(self.settings.value("replace_assistant/package_manifest_json", package_profile_defaults.create_manifest_json))
        )
        self.package_mod_json_checkbox.setChecked(
            bool(self.settings.value("replace_assistant/package_mod_json", package_profile_defaults.create_mod_json))
        )
        self.package_modinfo_checkbox.setChecked(
            bool(self.settings.value("replace_assistant/package_modinfo_json", package_profile_defaults.create_modinfo_json))
        )
        self.package_info_json_checkbox.setChecked(
            bool(self.settings.value("replace_assistant/package_info_json", package_profile_defaults.create_info_json))
        )
        if (
            package_profile_value.strip().lower() == "universal"
            and not self.settings.contains("replace_assistant/package_metadata_defaults_minimized")
            and self.settings.contains("replace_assistant/package_mod_json")
            and self.package_mod_json_checkbox.isChecked()
            and self.package_modinfo_checkbox.isChecked()
            and self.package_info_json_checkbox.isChecked()
        ):
            self.package_mod_json_checkbox.setChecked(False)
            self.package_modinfo_checkbox.setChecked(False)
            self.package_info_json_checkbox.setChecked(False)
            self.settings.setValue("replace_assistant/package_mod_json", False)
            self.settings.setValue("replace_assistant/package_modinfo_json", False)
            self.settings.setValue("replace_assistant/package_info_json", False)
        self.settings.setValue("replace_assistant/package_metadata_defaults_minimized", True)
        self.package_zip_checkbox.setChecked(
            bool(self.settings.value("replace_assistant/package_zip", package_profile_defaults.create_zip))
        )
        self._set_combo_by_value(
            self.package_conflict_mode_combo,
            str(self.settings.value("replace_assistant/package_conflict_mode", "")),
        )
        self.package_target_language_edit.setText(str(self.settings.value("replace_assistant/package_target_language", "")))
        self.ncnn_exe_path_edit.setText(str(self.settings.value("replace_assistant/ncnn_exe_path", "")))
        self.ncnn_model_dir_edit.setText(str(self.settings.value("replace_assistant/ncnn_model_dir", REALESRGAN_NCNN_MODEL_DIR)))
        self._set_combo_by_value(
            self.ncnn_model_combo,
            str(self.settings.value("replace_assistant/ncnn_model_name", REALESRGAN_NCNN_MODEL_NAME)),
        )
        self.ncnn_scale_spin.setValue(int(self.settings.value("replace_assistant/ncnn_scale", REALESRGAN_NCNN_SCALE)))
        self.ncnn_tile_size_spin.setValue(int(self.settings.value("replace_assistant/ncnn_tile_size", REALESRGAN_NCNN_TILE_SIZE)))
        self.ncnn_extra_args_edit.setText(str(self.settings.value("replace_assistant/ncnn_extra_args", REALESRGAN_NCNN_EXTRA_ARGS)))
        self._set_combo_by_value(
            self.upscale_post_correction_combo,
            str(self.settings.value("replace_assistant/post_correction", DEFAULT_UPSCALE_POST_CORRECTION)),
        )
        self._set_combo_by_value(
            self.upscale_texture_preset_combo,
            str(self.settings.value("replace_assistant/texture_preset", DEFAULT_UPSCALE_TEXTURE_PRESET)),
        )
        self.enable_automatic_texture_rules_checkbox.setChecked(
            bool(self.settings.value("replace_assistant/automatic_rules", False))
        )
        self.enable_unsafe_technical_override_checkbox.setChecked(bool(self.settings.value("replace_assistant/unsafe_override", False)))
        self.retry_smaller_tile_checkbox.setChecked(bool(self.settings.value("replace_assistant/retry_smaller_tile", True)))

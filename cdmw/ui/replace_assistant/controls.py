from __future__ import annotations

from pathlib import Path
from typing import Dict

from cdmw.constants import REALESRGAN_NCNN_MODEL_DIR
from cdmw.domain.packages.export_policy import (
    MOD_PACKAGE_MANAGER_PROFILES,
    mod_package_export_options_for_manager,
    mod_package_export_options_for_profiles,
    mod_package_profile_uses_manager_metadata,
)
from cdmw.services.texture_workflow_service import discover_realesrgan_ncnn_models


class ReplaceAssistantControlMixin:
    def _refresh_ncnn_models(self) -> None:
        current_name = self._combo_value(self.ncnn_model_combo) or self.ncnn_model_combo.currentText()
        exe_path_text = self.ncnn_exe_path_edit.text().strip()
        exe_path = Path(exe_path_text).expanduser() if exe_path_text else None
        model_dir = Path(self.ncnn_model_dir_edit.text().strip() or REALESRGAN_NCNN_MODEL_DIR)
        try:
            discovered = discover_realesrgan_ncnn_models(exe_path, model_dir)
        except Exception as exc:
            self.ncnn_model_combo.blockSignals(True)
            self.ncnn_model_combo.clear()
            self.ncnn_model_combo.addItem(f"No models found: {exc}", "")
            self.ncnn_model_combo.blockSignals(False)
            self.append_log(f"ERROR: {exc}")
            self.status_label.setText("NCNN model scan failed.")
            self._update_controls()
            return

        self.ncnn_model_combo.blockSignals(True)
        self.ncnn_model_combo.clear()
        for model_name, _model_dir in discovered:
            self.ncnn_model_combo.addItem(model_name, model_name)
        self.ncnn_model_combo.blockSignals(False)
        if discovered:
            self._set_combo_by_value(self.ncnn_model_combo, current_name)
            if self.ncnn_model_combo.currentIndex() < 0:
                self.ncnn_model_combo.setCurrentIndex(0)
            self.status_label.setText(f"Loaded {len(discovered):,} NCNN model(s).")
        else:
            self.ncnn_model_combo.addItem("No models found", "")
            self.status_label.setText("No NCNN models found.")
        self._update_summary()
        self._update_controls()

    def _set_summary_text(self, text: str) -> None:
        self.summary_label.setText(text)

    def _update_summary(self) -> None:
        total = len(self.items)
        matched = sum(1 for item in self.items if item.status == "matched")
        unresolved = sum(1 for item in self.items if item.status == "unresolved")
        failed = sum(1 for item in self.items if item.status == "failed")
        kind_counts: Dict[str, int] = {}
        for item in self.items:
            kind_counts[item.source_kind] = kind_counts.get(item.source_kind, 0) + 1
        kinds_text = ", ".join(f"{kind}:{count}" for kind, count in sorted(kind_counts.items())) if kind_counts else "none"
        self._set_summary_text(
            f"{total:,} edited file(s) loaded. Matched: {matched:,}. Unresolved: {unresolved:,}. Failed: {failed:,}. "
            f"Kinds: {kinds_text}."
        )
        if unresolved:
            self.status_label.setText(f"{unresolved:,} item(s) still need an original DDS.")
        elif total:
            self.status_label.setText("All imported files are matched.")
        else:
            self.status_label.setText("Ready.")

    def _sync_build_mode_visibility(self) -> None:
        show_ncnn = self._combo_value(self.build_mode_combo) == "upscale_then_rebuild"
        self.ncnn_group.setVisible(show_ncnn)

    def _sync_package_manager_field_visibility(self) -> None:
        checked_profiles = tuple(
            profile
            for profile, checkbox in self.package_profile_checkboxes.items()
            if checkbox.isChecked()
        ) or (self._combo_value(self.package_manager_combo),)
        uses_manager_metadata = any(mod_package_profile_uses_manager_metadata(profile) for profile in checked_profiles)
        auto_options = mod_package_export_options_for_profiles(
            checked_profiles,
            create_zip=self.package_zip_checkbox.isChecked(),
            conflict_mode=self._combo_value(self.package_conflict_mode_combo) if uses_manager_metadata else "",
            target_language=self.package_target_language_edit.text().strip() if uses_manager_metadata else "",
        )
        self.create_no_encrypt_checkbox.setChecked(auto_options.create_no_encrypt_file)
        self.package_manifest_checkbox.setChecked(auto_options.create_manifest_json)
        self.package_mod_json_checkbox.setChecked(auto_options.create_mod_json)
        self.package_modinfo_checkbox.setChecked(auto_options.create_modinfo_json)
        self.package_info_json_checkbox.setChecked(auto_options.create_info_json)
        structure_index = self.package_structure_combo.findData(auto_options.structure)
        if structure_index >= 0 and self.package_structure_combo.currentIndex() != structure_index:
            self.package_structure_combo.blockSignals(True)
            self.package_structure_combo.setCurrentIndex(structure_index)
            self.package_structure_combo.blockSignals(False)
        first_profile = checked_profiles[0] if checked_profiles else "dmm"
        manager_index = self.package_manager_combo.findData(first_profile)
        if manager_index >= 0 and self.package_manager_combo.currentIndex() != manager_index:
            self.package_manager_combo.blockSignals(True)
            self.package_manager_combo.setCurrentIndex(manager_index)
            self.package_manager_combo.blockSignals(False)
        for widget in (
            self.package_conflict_mode_label,
            self.package_conflict_mode_combo,
            self.package_conflict_mode_help,
            self.package_target_language_label,
            self.package_target_language_edit,
            self.package_target_language_help,
        ):
            widget.setVisible(uses_manager_metadata)

    def _update_controls(self) -> None:
        busy = self.external_busy or self.is_busy()
        has_items = bool(self.items)
        selected_count = len(self.queue_tree.selectedItems())
        show_ncnn = self._combo_value(self.build_mode_combo) == "upscale_then_rebuild"
        checked_profiles = tuple(
            profile
            for profile, checkbox in self.package_profile_checkboxes.items()
            if checkbox.isChecked()
        ) or (self._combo_value(self.package_manager_combo),)
        uses_manager_metadata = any(mod_package_profile_uses_manager_metadata(profile) for profile in checked_profiles)
        self.add_files_button.setEnabled(not busy)
        self.add_folder_button.setEnabled(not busy)
        self.auto_match_button.setEnabled(not busy and has_items)
        self.choose_local_original_button.setEnabled(not busy and selected_count == 1)
        self.choose_archive_original_button.setEnabled(
            not busy and selected_count == 1 and self._archive_original_source_ready()
        )
        self.remove_selected_button.setEnabled(not busy and selected_count > 0)
        self.clear_all_button.setEnabled(not busy and has_items)
        self.build_package_button.setEnabled(not busy and has_items)
        self.open_output_folder_button.setEnabled(not busy and bool(self.package_output_root_edit.text().strip()))
        self.mirror_workflow_button.setEnabled(not busy)
        self.ncnn_refresh_models_button.setEnabled(not busy)
        self.preview_zoom_out_button.setEnabled(has_items and not self.preview_label.text().startswith("Preparing"))
        self.preview_zoom_fit_button.setEnabled(has_items)
        self.preview_zoom_100_button.setEnabled(has_items)
        self.preview_zoom_in_button.setEnabled(has_items)
        self.build_mode_combo.setEnabled(not busy)
        self.size_mode_combo.setEnabled(not busy)
        self.package_output_root_edit.setEnabled(not busy)
        self.package_output_browse_button.setEnabled(not busy)
        self.overwrite_package_checkbox.setEnabled(not busy)
        self.create_no_encrypt_checkbox.setEnabled(not busy)
        self.package_title_edit.setEnabled(not busy)
        self.package_version_edit.setEnabled(not busy)
        self.package_author_edit.setEnabled(not busy)
        self.package_description_edit.setEnabled(not busy)
        self.package_profiles_widget.setEnabled(not busy)
        for checkbox in self.package_profile_checkboxes.values():
            checkbox.setEnabled(not busy)
        self.package_zip_checkbox.setEnabled(not busy)
        self.package_conflict_mode_combo.setEnabled(not busy and uses_manager_metadata)
        self.package_target_language_edit.setEnabled(not busy and uses_manager_metadata)
        self.open_in_editor_button.setEnabled(not busy and selected_count == 1)
        self.ncnn_group.setVisible(show_ncnn)
        self.ncnn_exe_path_edit.setEnabled(not busy and show_ncnn)
        self.ncnn_model_dir_edit.setEnabled(not busy and show_ncnn)
        self.ncnn_model_combo.setEnabled(not busy and show_ncnn)
        self.ncnn_scale_spin.setEnabled(not busy and show_ncnn)
        self.ncnn_tile_size_spin.setEnabled(not busy and show_ncnn)
        self.ncnn_extra_args_edit.setEnabled(not busy and show_ncnn)
        self.upscale_post_correction_combo.setEnabled(not busy and show_ncnn)
        self.upscale_texture_preset_combo.setEnabled(not busy and show_ncnn)
        self.enable_automatic_texture_rules_checkbox.setEnabled(not busy and show_ncnn)
        self.enable_unsafe_technical_override_checkbox.setEnabled(not busy and show_ncnn)
        self.retry_smaller_tile_checkbox.setEnabled(not busy and show_ncnn)
        if hasattr(self, "queue_stack"):
            self.queue_stack.setCurrentWidget(self.queue_tree if has_items or busy else self.queue_empty_state)

    def append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)
        self.status_message_requested.emit(message, message.startswith("ERROR:"))

    def mirror_texture_workflow_settings(self) -> None:
        config = self.get_current_config()
        self.ncnn_exe_path_edit.setText(str(getattr(config, "ncnn_exe_path", "")))
        self.ncnn_model_dir_edit.setText(str(getattr(config, "ncnn_model_dir", self.ncnn_model_dir_edit.text())))
        self._refresh_ncnn_models()
        self._set_combo_by_value(self.ncnn_model_combo, str(getattr(config, "ncnn_model_name", "")))
        self.ncnn_scale_spin.setValue(int(getattr(config, "ncnn_scale", self.ncnn_scale_spin.value())))
        self.ncnn_tile_size_spin.setValue(int(getattr(config, "ncnn_tile_size", self.ncnn_tile_size_spin.value())))
        self.ncnn_extra_args_edit.setText(str(getattr(config, "ncnn_extra_args", "")))
        self._set_combo_by_value(self.upscale_post_correction_combo, str(getattr(config, "upscale_post_correction_mode", "")))
        self._set_combo_by_value(self.upscale_texture_preset_combo, str(getattr(config, "upscale_texture_preset", "")))
        self.enable_automatic_texture_rules_checkbox.setChecked(bool(getattr(config, "enable_automatic_texture_rules", False)))
        self.enable_unsafe_technical_override_checkbox.setChecked(bool(getattr(config, "enable_unsafe_technical_override", False)))
        self.retry_smaller_tile_checkbox.setChecked(bool(getattr(config, "retry_smaller_tile_on_failure", True)))
        self.package_output_root_edit.setText(
            str(getattr(config, "mod_ready_export_root", self.package_output_root_edit.text()))
        )
        self._set_combo_by_value(
            self.package_manager_combo,
            str(getattr(config, "mod_ready_manager_profile", self._combo_value(self.package_manager_combo))),
        )
        mirrored_profiles = tuple(
            str(value or "").strip()
            for value in tuple(getattr(config, "mod_ready_manager_profiles", ()) or ())
            if str(value or "").strip() in MOD_PACKAGE_MANAGER_PROFILES
        ) or (str(getattr(config, "mod_ready_manager_profile", "dmm") or "dmm"),)
        for profile, checkbox in self.package_profile_checkboxes.items():
            checkbox.setChecked(profile in set(mirrored_profiles))
        profile_defaults = mod_package_export_options_for_manager(str(getattr(config, "mod_ready_manager_profile", "dmm")))
        self._set_combo_by_value(
            self.package_structure_combo,
            str(getattr(config, "mod_ready_package_structure", self._combo_value(self.package_structure_combo))),
        )
        self.package_manifest_checkbox.setChecked(bool(getattr(config, "mod_ready_create_manifest_json", profile_defaults.create_manifest_json)))
        self.package_mod_json_checkbox.setChecked(bool(getattr(config, "mod_ready_create_mod_json", profile_defaults.create_mod_json)))
        self.package_modinfo_checkbox.setChecked(bool(getattr(config, "mod_ready_create_modinfo_json", profile_defaults.create_modinfo_json)))
        self.package_info_json_checkbox.setChecked(bool(getattr(config, "mod_ready_create_info_json", profile_defaults.create_info_json)))
        self.package_zip_checkbox.setChecked(bool(getattr(config, "mod_ready_create_zip", profile_defaults.create_zip)))
        self._set_combo_by_value(
            self.package_conflict_mode_combo,
            str(getattr(config, "mod_ready_conflict_mode", "")),
        )
        self.package_target_language_edit.setText(str(getattr(config, "mod_ready_target_language", "")))
        self.append_log("Mirrored Texture Workflow NCNN and policy settings into Texture Replacer.")
        self._update_controls()

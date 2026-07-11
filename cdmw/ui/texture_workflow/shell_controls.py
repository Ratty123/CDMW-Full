"""Texture workflow shell-level layout and option state controls."""

from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton

from cdmw.constants import MOD_READY_PACKAGE_TITLE, MOD_READY_PACKAGE_VERSION
from cdmw.domain.packages.export_policy import (
    mod_package_export_options_for_manager,
    mod_package_export_options_for_profiles,
    mod_package_profile_uses_manager_metadata,
)
from cdmw.services.texture_workflow_service import resolve_default_mod_ready_export_root


class TextureWorkflowShellControlsMixin:
    """Coordinate shell-owned texture workflow controls and saved state."""
    def _build_texture_workflow_action_button_row(self, workflow_layout) -> None:
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.scan_button = QPushButton("Scan")
        self.preview_policy_button = QPushButton("Preview Policy")
        self.preview_policy_button.setToolTip(
            "Show the current per-texture processing plan before running Start."
        )
        self.clear_workflow_roots_button = QPushButton("Clear Workflow Roots...")
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.open_output_button = QPushButton("Open Output")
        self.stop_button.setEnabled(False)
        button_row.addWidget(self.scan_button)
        button_row.addWidget(self.preview_policy_button)
        button_row.addWidget(self.clear_workflow_roots_button)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)
        button_row.addStretch(1)
        button_row.addWidget(self.open_output_button)
        workflow_layout.addLayout(button_row)

    def _default_workflow_right_splitter_sizes(self) -> List[int]:
        available_right_height = max(420, self.height() - 260)
        progress_min_height = getattr(self, "progress_group_min_height", 190)
        progress_height = min(
            max(progress_min_height, int(available_right_height * 0.18)),
            max(progress_min_height, 210),
        )
        return [progress_height, max(320, available_right_height - progress_height)]

    def _apply_workflow_content_tab_layout(self, *_args) -> None:
        compare_active = (
            self._is_tool_visible_or_current(self.workflow_tab)
            and self.content_tabs.currentWidget() is self.compare_tab
        )
        if compare_active:
            current_sizes = self.workflow_right_splitter.sizes()
            if len(current_sizes) >= 2 and current_sizes[0] > 0:
                self.workflow_right_splitter_normal_sizes = current_sizes
            self.progress_group.setVisible(False)
            self.workflow_right_splitter.setHandleWidth(0)
            self.workflow_right_splitter.setSizes([0, max(1, self.workflow_right_splitter.height())])
            return

        self.progress_group.setVisible(True)
        self.workflow_right_splitter.setHandleWidth(4)
        restore_sizes = self.workflow_right_splitter_normal_sizes or self._default_workflow_right_splitter_sizes()
        self.workflow_right_splitter.setSizes(restore_sizes)

    def _compare_preview_can_autostart(self) -> bool:
        if self._shutting_down:
            return False
        if self._startup_benchmark_enabled():
            return False
        if not bool(getattr(self, "_settings_ready", False)):
            return False
        if getattr(self, "_startup_splash_window", None) is not None:
            return False
        return (
            self._is_tool_visible_or_current(self.workflow_tab)
            and self.content_tabs.currentWidget() is self.compare_tab
        )

    def _queue_current_compare_preview_if_visible(self) -> None:
        if not self._compare_preview_can_autostart():
            return
        current = self.compare_list.currentItem()
        if current is None:
            return
        raw_path = current.data(Qt.UserRole)
        if not raw_path:
            return
        self.pending_compare_preview_selection = Path(raw_path)
        self._compare_preview_timer.start()

    def _handle_workflow_content_tab_changed(self, index: int) -> None:
        del index
        self._apply_workflow_content_tab_layout()
        self._queue_current_compare_preview_if_visible()
        if not self._startup_benchmark_enabled():
            self._save_settings()

    def _refresh_chainner_chain_info(self) -> None:
        if self._shutting_down or not self.chainner_section.is_body_built():
            return
        _analysis, text = self._resolve_chainner_analysis()
        self.chainner_chain_info_view.setPlainText(text)

    def _schedule_chainner_chain_info_refresh(self, *_args) -> None:
        if self._shutting_down or not self._settings_ready:
            return
        self._chainner_analysis_timer.start()

    def _apply_mod_ready_export_state(self) -> None:
        if not self.chainner_section.is_body_built():
            return
        enabled = self.enable_mod_ready_loose_export_checkbox.isChecked()
        checked_profiles = tuple(
            profile
            for profile, checkbox in self.mod_ready_profile_checkboxes.items()
            if checkbox.isChecked()
        ) or (self._combo_value(self.mod_ready_manager_combo),)
        uses_manager_metadata = any(mod_package_profile_uses_manager_metadata(profile) for profile in checked_profiles)
        auto_options = mod_package_export_options_for_profiles(
            checked_profiles,
            create_zip=self.mod_ready_zip_checkbox.isChecked(),
            conflict_mode=self._combo_value(self.mod_ready_conflict_mode_combo) if uses_manager_metadata else "",
            target_language=self.mod_ready_target_language_edit.text().strip() if uses_manager_metadata else "",
        )
        first_profile = checked_profiles[0] if checked_profiles else "dmm"
        manager_index = self.mod_ready_manager_combo.findData(first_profile)
        if manager_index >= 0 and self.mod_ready_manager_combo.currentIndex() != manager_index:
            self.mod_ready_manager_combo.blockSignals(True)
            self.mod_ready_manager_combo.setCurrentIndex(manager_index)
            self.mod_ready_manager_combo.blockSignals(False)
        structure_index = self.mod_ready_structure_combo.findData(auto_options.structure)
        if structure_index >= 0 and self.mod_ready_structure_combo.currentIndex() != structure_index:
            self.mod_ready_structure_combo.blockSignals(True)
            self.mod_ready_structure_combo.setCurrentIndex(structure_index)
            self.mod_ready_structure_combo.blockSignals(False)
        self.mod_ready_manifest_checkbox.setChecked(auto_options.create_manifest_json)
        self.mod_ready_mod_json_checkbox.setChecked(auto_options.create_mod_json)
        self.mod_ready_modinfo_checkbox.setChecked(auto_options.create_modinfo_json)
        self.mod_ready_info_json_checkbox.setChecked(auto_options.create_info_json)
        self.mod_ready_create_no_encrypt_checkbox.setChecked(auto_options.create_no_encrypt_file)
        self.mod_ready_export_root_edit.setEnabled(enabled)
        self.mod_ready_export_browse_button.setEnabled(enabled)
        self.mod_ready_package_group.setVisible(enabled)
        self.mod_ready_package_title_edit.setEnabled(enabled)
        self.mod_ready_package_version_edit.setEnabled(enabled)
        self.mod_ready_package_author_edit.setEnabled(enabled)
        self.mod_ready_package_description_edit.setEnabled(enabled)
        self.mod_ready_profiles_widget.setEnabled(enabled)
        for checkbox in self.mod_ready_profile_checkboxes.values():
            checkbox.setEnabled(enabled)
        self.mod_ready_zip_checkbox.setEnabled(enabled)
        for widget in (
            self.mod_ready_conflict_mode_label,
            self.mod_ready_conflict_mode_combo,
            self.mod_ready_conflict_mode_help,
            self.mod_ready_target_language_label,
            self.mod_ready_target_language_edit,
            self.mod_ready_target_language_help,
        ):
            widget.setVisible(uses_manager_metadata)
        self.mod_ready_conflict_mode_combo.setEnabled(enabled and uses_manager_metadata)
        self.mod_ready_target_language_edit.setEnabled(enabled and uses_manager_metadata)
        if enabled and not self.mod_ready_export_root_edit.text().strip():
            output_text = self.output_root_edit.text().strip()
            if output_text:
                default_root = resolve_default_mod_ready_export_root(Path(output_text).expanduser())
                self.mod_ready_export_root_edit.setText(str(default_root))
        if enabled and not self.mod_ready_package_title_edit.text().strip():
            self.mod_ready_package_title_edit.setText(MOD_READY_PACKAGE_TITLE)
        if enabled and not self.mod_ready_package_version_edit.text().strip():
            self.mod_ready_package_version_edit.setText(MOD_READY_PACKAGE_VERSION)
        self._save_settings()

    def _apply_mod_ready_manager_profile_state(self) -> None:
        current_profile = str(self.mod_ready_manager_combo.currentData() or "dmm")
        profile_options = mod_package_export_options_for_manager(current_profile)
        index = self.mod_ready_structure_combo.findData(profile_options.structure)
        if index >= 0:
            self.mod_ready_structure_combo.setCurrentIndex(index)
        for profile, checkbox in self.mod_ready_profile_checkboxes.items():
            checkbox.setChecked(profile == current_profile)
        self.mod_ready_manifest_checkbox.setChecked(profile_options.create_manifest_json)
        self.mod_ready_mod_json_checkbox.setChecked(profile_options.create_mod_json)
        self.mod_ready_modinfo_checkbox.setChecked(profile_options.create_modinfo_json)
        self.mod_ready_info_json_checkbox.setChecked(profile_options.create_info_json)
        self.mod_ready_create_no_encrypt_checkbox.setChecked(profile_options.create_no_encrypt_file)
        self.mod_ready_zip_checkbox.setChecked(profile_options.create_zip)
        self._apply_mod_ready_export_state()
        self.schedule_settings_save()

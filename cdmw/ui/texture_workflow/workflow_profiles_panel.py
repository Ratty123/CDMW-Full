"""Texture workflow profile and rule editor helpers."""

from __future__ import annotations

import dataclasses
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QInputDialog, QLabel, QTreeWidgetItem, QVBoxLayout

from cdmw.constants import REALESRGAN_NCNN_TILE_SIZE, UPSCALE_BACKEND_REALESRGAN_NCNN
from cdmw.services.texture_workflow_service import collect_dds_files
from cdmw.services.texture_workflow_service import build_texture_processing_plan
from cdmw.services.texture_workflow_service import normalize_config_for_planning
from cdmw.domain.textures.output import (
    summarize_effective_dds_override,
    summarize_effective_ncnn_settings,
    summarize_texture_workflow_rule,
)
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
from cdmw.models import AppConfig, TextureRule, TextureWorkflowProfile


class TextureWorkflowProfilesPanelMixin:
    """Texture workflow profile/rule editor state and actions."""
    def _add_combo_choice(self, combo: QComboBox, label: str, value: str) -> None:
        combo.addItem(label, value)

    def _combo_value(self, combo: QComboBox) -> str:
        if combo.isEditable():
            text = combo.currentText().strip()
            index = combo.currentIndex()
            item_text = combo.itemText(index).strip() if index >= 0 else ""
            if text and text != item_text:
                return text
        data = combo.currentData()
        return str(data) if data is not None else combo.currentText().strip()

    def _set_combo_by_value(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
        elif combo.isEditable():
            combo.setEditText(str(value or "").strip())

    def _next_workflow_profile_id(self) -> str:
        existing_ids = {profile.profile_id for profile in self.workflow_profiles_state}
        index = 1
        while True:
            candidate = f"profile_{index}"
            if candidate not in existing_ids:
                return candidate
            index += 1

    def _selected_workflow_profile_index(self) -> int:
        item = self.workflow_profiles_tree.currentItem()
        if item is None:
            return -1
        try:
            return int(item.data(0, Qt.UserRole))
        except (TypeError, ValueError):
            return -1

    def _selected_workflow_rule_index(self) -> int:
        item = self.workflow_rules_tree.currentItem()
        if item is None:
            return -1
        try:
            return int(item.data(0, Qt.UserRole))
        except (TypeError, ValueError):
            return -1

    def _workflow_profile_by_id(self, profile_id: str) -> Optional[TextureWorkflowProfile]:
        target = str(profile_id or "").strip()
        for profile in self.workflow_profiles_state:
            if profile.profile_id == target:
                return profile
        return None

    def _workflow_profile_label(self, profile_id: str) -> str:
        profile = self._workflow_profile_by_id(profile_id)
        return profile.label if profile is not None else ""

    def _workflow_profile_dds_summary(self, profile: TextureWorkflowProfile) -> str:
        parts: List[str] = []
        if profile.format_value:
            parts.append(f"fmt={profile.format_value}")
        if profile.size_value:
            parts.append(f"size={profile.size_value}")
        if profile.mip_value:
            parts.append(f"mips={profile.mip_value}")
        return ", ".join(parts) if parts else "Inherit"

    def _workflow_profile_ncnn_summary(self, profile: TextureWorkflowProfile) -> str:
        parts: List[str] = []
        if profile.ncnn_model_name:
            parts.append(profile.ncnn_model_name)
        if profile.ncnn_scale is not None:
            parts.append(f"{profile.ncnn_scale}x")
        if profile.ncnn_tile_size is not None:
            parts.append(f"tile {profile.ncnn_tile_size}")
        if profile.post_correction_mode:
            parts.append(profile.post_correction_mode)
        if profile.ncnn_extra_args:
            parts.append("extra args")
        return " | ".join(parts) if parts else "Inherit"

    def _workflow_rule_summary(self, rule: TextureRule) -> Tuple[str, str, str, str, str, str, str, str, str]:
        return (
            "Yes" if rule.enabled else "No",
            "Exact" if str(rule.match_mode or "glob").strip().lower() == "exact" else "Glob",
            rule.pattern,
            self._workflow_profile_label(rule.workflow_profile_id) or "(none)",
            rule.semantic_value or "",
            rule.profile_value or "",
            rule.colorspace_value or "",
            rule.alpha_policy_value or "",
            rule.intermediate_value or "",
        )

    def _refresh_workflow_profile_ncnn_model_combo(self) -> None:
        current_value = self._combo_value(self.workflow_profile_ncnn_model_combo)
        models = (
            [self.ncnn_model_combo.itemData(index) for index in range(self.ncnn_model_combo.count())]
            if self.chainner_section.is_body_built()
            else []
        )
        self.workflow_profile_ncnn_model_combo.blockSignals(True)
        self.workflow_profile_ncnn_model_combo.clear()
        self._add_combo_choice(self.workflow_profile_ncnn_model_combo, "Inherit Direct NCNN Model", "")
        seen: set[str] = set()
        for model_name in models:
            normalized = str(model_name or "").strip()
            if not normalized or normalized in seen:
                continue
            self._add_combo_choice(self.workflow_profile_ncnn_model_combo, normalized, normalized)
            seen.add(normalized)
        if current_value and current_value not in seen:
            self._add_combo_choice(
                self.workflow_profile_ncnn_model_combo,
                f"{current_value} (missing)",
                current_value,
            )
        self._set_combo_by_value(self.workflow_profile_ncnn_model_combo, current_value)
        self.workflow_profile_ncnn_model_combo.blockSignals(False)

    def _refresh_workflow_rule_profile_combo(self, preferred_profile_id: str = "") -> None:
        current_value = preferred_profile_id or self._combo_value(self.workflow_rule_profile_combo)
        self.workflow_rule_profile_combo.blockSignals(True)
        self.workflow_rule_profile_combo.clear()
        self._add_combo_choice(self.workflow_rule_profile_combo, "No Workflow Profile", "")
        for profile in self.workflow_profiles_state:
            self._add_combo_choice(self.workflow_rule_profile_combo, profile.label, profile.profile_id)
        self._set_combo_by_value(self.workflow_rule_profile_combo, current_value)
        self.workflow_rule_profile_combo.blockSignals(False)

    def _set_workflow_profile_custom_controls_state(self, *_args) -> None:
        size_value = self._combo_value(self.workflow_profile_size_combo)
        size_custom = size_value == "__custom__"
        self.workflow_profile_custom_size_label.setVisible(size_custom)
        self.workflow_profile_custom_size_widget.setVisible(size_custom)
        self.workflow_profile_custom_width_spin.setEnabled(size_custom)
        self.workflow_profile_custom_height_spin.setEnabled(size_custom)
        mip_value = self._combo_value(self.workflow_profile_mip_combo)
        mip_custom = mip_value == "__custom__"
        self.workflow_profile_custom_mip_label.setVisible(mip_custom)
        self.workflow_profile_custom_mip_spin.setVisible(mip_custom)
        self.workflow_profile_custom_mip_spin.setEnabled(mip_custom)
        tile_enabled = self.workflow_profile_ncnn_tile_override_checkbox.isChecked()
        self.workflow_profile_ncnn_tile_spin.setEnabled(tile_enabled and self._current_upscale_backend() == UPSCALE_BACKEND_REALESRGAN_NCNN)

    def _sync_workflow_editor_state(self, *_args) -> None:
        profile_index = self._selected_workflow_profile_index()
        rule_index = self._selected_workflow_rule_index()
        has_profile = 0 <= profile_index < len(self.workflow_profiles_state)
        has_rule = 0 <= rule_index < len(self.texture_rules_state)
        self.workflow_profile_duplicate_button.setEnabled(has_profile)
        self.workflow_profile_delete_button.setEnabled(has_profile)
        self.workflow_rule_duplicate_button.setEnabled(has_rule)
        self.workflow_rule_delete_button.setEnabled(has_rule)
        self.workflow_rule_move_up_button.setEnabled(has_rule and rule_index > 0)
        self.workflow_rule_move_down_button.setEnabled(has_rule and rule_index < len(self.texture_rules_state) - 1)
        self.workflow_assign_profile_button.setEnabled(
            bool(self.workflow_profiles_state) and bool(self.workflow_matched_files_tree.selectedItems())
        )
        direct_backend_enabled = self._current_upscale_backend() == UPSCALE_BACKEND_REALESRGAN_NCNN
        for widget in (
            self.workflow_profile_ncnn_model_combo,
            self.workflow_profile_ncnn_scale_combo,
            self.workflow_profile_ncnn_tile_override_checkbox,
            self.workflow_profile_ncnn_extra_args_edit,
            self.workflow_profile_post_correction_combo,
        ):
            widget.setEnabled(has_profile and direct_backend_enabled)
        self.workflow_profile_ncnn_tile_spin.setEnabled(
            has_profile and direct_backend_enabled and self.workflow_profile_ncnn_tile_override_checkbox.isChecked()
        )
        self._set_workflow_profile_custom_controls_state()

    def _refresh_workflow_profiles_tree(self, *, select_profile_id: str = "") -> None:
        if not select_profile_id:
            current_index = self._selected_workflow_profile_index()
            if 0 <= current_index < len(self.workflow_profiles_state):
                select_profile_id = self.workflow_profiles_state[current_index].profile_id
        self._workflow_editor_syncing = True
        try:
            self.workflow_profiles_tree.clear()
            selected_item = None
            for index, profile in enumerate(self.workflow_profiles_state):
                item = QTreeWidgetItem(
                    [
                        profile.label,
                        profile.action_mode or "inherit",
                        self._workflow_profile_dds_summary(profile),
                        self._workflow_profile_ncnn_summary(profile),
                    ]
                )
                item.setData(0, Qt.UserRole, index)
                item.setData(0, Qt.UserRole + 1, profile.profile_id)
                self.workflow_profiles_tree.addTopLevelItem(item)
                if profile.profile_id == select_profile_id:
                    selected_item = item
            if selected_item is None and self.workflow_profiles_tree.topLevelItemCount() > 0:
                selected_item = self.workflow_profiles_tree.topLevelItem(0)
            if selected_item is not None:
                self.workflow_profiles_tree.setCurrentItem(selected_item)
        finally:
            self._workflow_editor_syncing = False
        self._refresh_workflow_rule_profile_combo()
        self._update_workflow_profile_detail_widgets()
        self._refresh_workflow_rules_tree()

    def _refresh_workflow_rules_tree(self, *, select_index: Optional[int] = None) -> None:
        if select_index is None:
            current_index = self._selected_workflow_rule_index()
            select_index = current_index if current_index >= 0 else None
        self._workflow_editor_syncing = True
        try:
            self.workflow_rules_tree.clear()
            selected_item = None
            for index, rule in enumerate(self.texture_rules_state):
                item = QTreeWidgetItem(list(self._workflow_rule_summary(rule)))
                item.setData(0, Qt.UserRole, index)
                self.workflow_rules_tree.addTopLevelItem(item)
                if select_index is not None and index == select_index:
                    selected_item = item
            if selected_item is None and self.workflow_rules_tree.topLevelItemCount() > 0:
                selected_item = self.workflow_rules_tree.topLevelItem(0)
            if selected_item is not None:
                self.workflow_rules_tree.setCurrentItem(selected_item)
        finally:
            self._workflow_editor_syncing = False
        self._update_workflow_rule_detail_widgets()

    def _update_workflow_profile_detail_widgets(self, *_args) -> None:
        index = self._selected_workflow_profile_index()
        has_profile = 0 <= index < len(self.workflow_profiles_state)
        profile = self.workflow_profiles_state[index] if has_profile else None
        direct_tile_size = (
            self.ncnn_tile_size_spin.value()
            if self.chainner_section.is_body_built()
            else int(self.settings.value("ncnn/tile_size", REALESRGAN_NCNN_TILE_SIZE))
        )
        self._workflow_editor_syncing = True
        try:
            for widget in (
                self.workflow_profile_name_edit,
                self.workflow_profile_action_combo,
                self.workflow_profile_format_combo,
                self.workflow_profile_size_combo,
                self.workflow_profile_mip_combo,
                self.workflow_profile_ncnn_model_combo,
                self.workflow_profile_ncnn_scale_combo,
                self.workflow_profile_ncnn_tile_override_checkbox,
                self.workflow_profile_ncnn_extra_args_edit,
                self.workflow_profile_post_correction_combo,
            ):
                widget.setEnabled(has_profile)
            self.workflow_profile_custom_width_spin.setEnabled(has_profile)
            self.workflow_profile_custom_height_spin.setEnabled(has_profile)
            self.workflow_profile_custom_mip_spin.setEnabled(has_profile)
            if profile is None:
                self.workflow_profile_name_edit.clear()
                self._set_combo_by_value(self.workflow_profile_action_combo, "")
                self._set_combo_by_value(self.workflow_profile_format_combo, "")
                self._set_combo_by_value(self.workflow_profile_size_combo, "")
                self.workflow_profile_custom_width_spin.setValue(2048)
                self.workflow_profile_custom_height_spin.setValue(2048)
                self._set_combo_by_value(self.workflow_profile_mip_combo, "")
                self.workflow_profile_custom_mip_spin.setValue(1)
                self._refresh_workflow_profile_ncnn_model_combo()
                self._set_combo_by_value(self.workflow_profile_ncnn_scale_combo, "")
                self.workflow_profile_ncnn_tile_override_checkbox.setChecked(False)
                self.workflow_profile_ncnn_tile_spin.setValue(max(0, direct_tile_size))
                self.workflow_profile_ncnn_extra_args_edit.clear()
                self._set_combo_by_value(self.workflow_profile_post_correction_combo, "")
            else:
                self.workflow_profile_name_edit.setText(profile.label)
                self._set_combo_by_value(self.workflow_profile_action_combo, profile.action_mode)
                self._set_combo_by_value(self.workflow_profile_format_combo, profile.format_value or "")
                size_value = profile.size_value or ""
                if "x" in size_value:
                    self._set_combo_by_value(self.workflow_profile_size_combo, "__custom__")
                    width_text, height_text = size_value.split("x", 1)
                    self.workflow_profile_custom_width_spin.setValue(int(width_text))
                    self.workflow_profile_custom_height_spin.setValue(int(height_text))
                else:
                    self._set_combo_by_value(self.workflow_profile_size_combo, size_value)
                mip_value = profile.mip_value or ""
                if mip_value.isdigit():
                    self._set_combo_by_value(self.workflow_profile_mip_combo, "__custom__")
                    self.workflow_profile_custom_mip_spin.setValue(int(mip_value))
                else:
                    self._set_combo_by_value(self.workflow_profile_mip_combo, mip_value)
                self._refresh_workflow_profile_ncnn_model_combo()
                self._set_combo_by_value(self.workflow_profile_ncnn_model_combo, profile.ncnn_model_name)
                self._set_combo_by_value(
                    self.workflow_profile_ncnn_scale_combo,
                    str(profile.ncnn_scale) if profile.ncnn_scale is not None else "",
                )
                self.workflow_profile_ncnn_tile_override_checkbox.setChecked(profile.ncnn_tile_size is not None)
                self.workflow_profile_ncnn_tile_spin.setValue(
                    int(profile.ncnn_tile_size) if profile.ncnn_tile_size is not None else max(0, direct_tile_size)
                )
                self.workflow_profile_ncnn_extra_args_edit.setText(profile.ncnn_extra_args)
                self._set_combo_by_value(self.workflow_profile_post_correction_combo, profile.post_correction_mode or "")
        finally:
            self._workflow_editor_syncing = False
        self._sync_workflow_editor_state()

    def _update_workflow_rule_detail_widgets(self, *_args) -> None:
        index = self._selected_workflow_rule_index()
        has_rule = 0 <= index < len(self.texture_rules_state)
        rule = self.texture_rules_state[index] if has_rule else None
        self._workflow_editor_syncing = True
        try:
            for widget in (
                self.workflow_rule_enabled_checkbox,
                self.workflow_rule_match_mode_combo,
                self.workflow_rule_pattern_edit,
                self.workflow_rule_profile_combo,
                self.workflow_rule_semantic_combo,
                self.workflow_rule_planner_profile_combo,
                self.workflow_rule_colorspace_combo,
                self.workflow_rule_alpha_combo,
                self.workflow_rule_intermediate_combo,
            ):
                widget.setEnabled(has_rule)
            if rule is None:
                self.workflow_rule_enabled_checkbox.setChecked(False)
                self._set_combo_by_value(self.workflow_rule_match_mode_combo, "glob")
                self.workflow_rule_pattern_edit.clear()
                self._refresh_workflow_rule_profile_combo("")
                self.workflow_rule_semantic_combo.setCurrentText("")
                self._set_combo_by_value(self.workflow_rule_planner_profile_combo, "")
                self._set_combo_by_value(self.workflow_rule_colorspace_combo, "")
                self._set_combo_by_value(self.workflow_rule_alpha_combo, "")
                self._set_combo_by_value(self.workflow_rule_intermediate_combo, "")
            else:
                self.workflow_rule_enabled_checkbox.setChecked(rule.enabled)
                self._set_combo_by_value(self.workflow_rule_match_mode_combo, rule.match_mode)
                self.workflow_rule_pattern_edit.setText(rule.pattern)
                self._refresh_workflow_rule_profile_combo(rule.workflow_profile_id)
                self.workflow_rule_semantic_combo.setCurrentText(rule.semantic_value or "")
                self._set_combo_by_value(self.workflow_rule_planner_profile_combo, rule.profile_value or "")
                self._set_combo_by_value(self.workflow_rule_colorspace_combo, rule.colorspace_value or "")
                self._set_combo_by_value(self.workflow_rule_alpha_combo, rule.alpha_policy_value or "")
                self._set_combo_by_value(self.workflow_rule_intermediate_combo, rule.intermediate_value or "")
        finally:
            self._workflow_editor_syncing = False
        self._sync_workflow_editor_state()

    def _schedule_workflow_match_refresh(self, *_args) -> None:
        if (
            not self.filters_section.is_body_built()
            or not self._settings_ready
            or self._shutting_down
            or self._workflow_editor_syncing
        ):
            return
        self._workflow_match_refresh_timer.start()

    def _refresh_workflow_matched_files_view(self, *_args) -> None:
        self.workflow_matched_files_tree.clear()
        self.workflow_matched_processing_plan = []
        try:
            config = self.collect_config()
            normalized = normalize_config_for_planning(config)
            dds_files = collect_dds_files(
                normalized.original_dds_root,
                normalized.include_filter_patterns,
            )
            if not dds_files:
                self.workflow_matched_summary_label.setText(
                    "No DDS files matched the current Original DDS root and filter."
                )
                self._sync_workflow_editor_state()
                return
            processing_plan = build_texture_processing_plan(normalized, dds_files)
            self.workflow_matched_processing_plan = list(processing_plan)
            self.workflow_matched_summary_label.setText(
                f"{len(processing_plan):,} matched DDS file(s). Last matching rule wins. "
                "Use Assign Profile to append exact-path rules for the selected rows."
            )
            for entry in processing_plan:
                item = QTreeWidgetItem(
                    [
                        entry.relative_path.as_posix(),
                        f"{entry.decision.texture_type}/{entry.decision.semantic_subtype}",
                        summarize_texture_workflow_rule(entry.matched_rule),
                        entry.workflow_profile.label if entry.workflow_profile is not None else "(none)",
                        summarize_effective_dds_override(entry),
                        summarize_effective_ncnn_settings(normalized, entry),
                        f"{entry.action} | {entry.action_reason}",
                    ]
                )
                item.setData(0, Qt.UserRole, entry.relative_path.as_posix())
                self.workflow_matched_files_tree.addTopLevelItem(item)
        except Exception as exc:
            self.workflow_matched_summary_label.setText(f"Matched files preview unavailable: {exc}")
        self._sync_workflow_editor_state()

    def _apply_selected_workflow_profile_edits(self, *_args) -> None:
        if self._workflow_editor_syncing:
            return
        index = self._selected_workflow_profile_index()
        if not (0 <= index < len(self.workflow_profiles_state)):
            return
        current = self.workflow_profiles_state[index]
        size_value = self._combo_value(self.workflow_profile_size_combo)
        if size_value == "__custom__":
            size_value = f"{self.workflow_profile_custom_width_spin.value()}x{self.workflow_profile_custom_height_spin.value()}"
        mip_value = self._combo_value(self.workflow_profile_mip_combo)
        if mip_value == "__custom__":
            mip_value = str(self.workflow_profile_custom_mip_spin.value())
        updated = TextureWorkflowProfile(
            profile_id=current.profile_id,
            label=self.workflow_profile_name_edit.text().strip() or current.label,
            action_mode=self._combo_value(self.workflow_profile_action_combo),
            format_value=self._combo_value(self.workflow_profile_format_combo) or None,
            size_value=size_value or None,
            mip_value=mip_value or None,
            ncnn_model_name=self._combo_value(self.workflow_profile_ncnn_model_combo),
            ncnn_scale=int(self._combo_value(self.workflow_profile_ncnn_scale_combo)) if self._combo_value(self.workflow_profile_ncnn_scale_combo) else None,
            ncnn_tile_size=self.workflow_profile_ncnn_tile_spin.value() if self.workflow_profile_ncnn_tile_override_checkbox.isChecked() else None,
            ncnn_extra_args=self.workflow_profile_ncnn_extra_args_edit.text().strip(),
            post_correction_mode=self._combo_value(self.workflow_profile_post_correction_combo),
        )
        self.workflow_profiles_state[index] = updated
        self._refresh_workflow_profiles_tree(select_profile_id=updated.profile_id)
        self.schedule_settings_save()
        self._schedule_workflow_match_refresh()

    def _apply_selected_workflow_rule_edits(self, *_args) -> None:
        if self._workflow_editor_syncing:
            return
        index = self._selected_workflow_rule_index()
        if not (0 <= index < len(self.texture_rules_state)):
            return
        current = self.texture_rules_state[index]
        pattern_text = self.workflow_rule_pattern_edit.text().strip() or current.pattern
        updated = TextureRule(
            pattern=pattern_text,
            action=current.action,
            format_value=current.format_value,
            size_value=current.size_value,
            mip_value=current.mip_value,
            semantic_value=self.workflow_rule_semantic_combo.currentText().strip().lower() or None,
            profile_value=self._combo_value(self.workflow_rule_planner_profile_combo) or None,
            colorspace_value=self._combo_value(self.workflow_rule_colorspace_combo) or None,
            alpha_policy_value=self._combo_value(self.workflow_rule_alpha_combo) or None,
            intermediate_value=self._combo_value(self.workflow_rule_intermediate_combo) or None,
            enabled=self.workflow_rule_enabled_checkbox.isChecked(),
            match_mode=self._combo_value(self.workflow_rule_match_mode_combo) or "glob",
            workflow_profile_id=self._combo_value(self.workflow_rule_profile_combo),
            source_line=current.source_line or pattern_text,
        )
        self.texture_rules_state[index] = updated
        self._refresh_workflow_rules_tree(select_index=index)
        self.schedule_settings_save()
        self._schedule_workflow_match_refresh()

    def _add_workflow_profile(self, *_args) -> None:
        new_profile = TextureWorkflowProfile(
            profile_id=self._next_workflow_profile_id(),
            label=f"Profile {len(self.workflow_profiles_state) + 1}",
        )
        self.workflow_profiles_state.append(new_profile)
        self._refresh_workflow_profiles_tree(select_profile_id=new_profile.profile_id)
        self.schedule_settings_save()
        self._schedule_workflow_match_refresh()

    def _duplicate_workflow_profile(self, *_args) -> None:
        index = self._selected_workflow_profile_index()
        if not (0 <= index < len(self.workflow_profiles_state)):
            return
        current = self.workflow_profiles_state[index]
        duplicated = dataclasses.replace(
            current,
            profile_id=self._next_workflow_profile_id(),
            label=f"{current.label} Copy",
        )
        self.workflow_profiles_state.insert(index + 1, duplicated)
        self._refresh_workflow_profiles_tree(select_profile_id=duplicated.profile_id)
        self.schedule_settings_save()
        self._schedule_workflow_match_refresh()

    def _delete_workflow_profile(self, *_args) -> None:
        index = self._selected_workflow_profile_index()
        if not (0 <= index < len(self.workflow_profiles_state)):
            return
        profile_id = self.workflow_profiles_state[index].profile_id
        del self.workflow_profiles_state[index]
        for rule_index, rule in enumerate(self.texture_rules_state):
            if rule.workflow_profile_id == profile_id:
                self.texture_rules_state[rule_index] = dataclasses.replace(rule, workflow_profile_id="")
        self._refresh_workflow_profiles_tree()
        self._refresh_workflow_rules_tree()
        self.schedule_settings_save()
        self._schedule_workflow_match_refresh()

    def _add_workflow_rule(self, *_args) -> None:
        rule = TextureRule(pattern="*.dds", enabled=True, match_mode="glob")
        self.texture_rules_state.append(rule)
        self._refresh_workflow_rules_tree(select_index=len(self.texture_rules_state) - 1)
        self.schedule_settings_save()
        self._schedule_workflow_match_refresh()

    def _duplicate_workflow_rule(self, *_args) -> None:
        index = self._selected_workflow_rule_index()
        if not (0 <= index < len(self.texture_rules_state)):
            return
        duplicated = dataclasses.replace(self.texture_rules_state[index])
        self.texture_rules_state.insert(index + 1, duplicated)
        self._refresh_workflow_rules_tree(select_index=index + 1)
        self.schedule_settings_save()
        self._schedule_workflow_match_refresh()

    def _delete_workflow_rule(self, *_args) -> None:
        index = self._selected_workflow_rule_index()
        if not (0 <= index < len(self.texture_rules_state)):
            return
        del self.texture_rules_state[index]
        next_index = min(index, len(self.texture_rules_state) - 1)
        self._refresh_workflow_rules_tree(select_index=next_index if next_index >= 0 else None)
        self.schedule_settings_save()
        self._schedule_workflow_match_refresh()

    def _move_workflow_rule(self, offset: int, *_args) -> None:
        index = self._selected_workflow_rule_index()
        target_index = index + offset
        if not (0 <= index < len(self.texture_rules_state)):
            return
        if not (0 <= target_index < len(self.texture_rules_state)):
            return
        self.texture_rules_state[index], self.texture_rules_state[target_index] = (
            self.texture_rules_state[target_index],
            self.texture_rules_state[index],
        )
        self._refresh_workflow_rules_tree(select_index=target_index)
        self.schedule_settings_save()
        self._schedule_workflow_match_refresh()

    def _assign_profile_to_selected_workflow_matches(self, *_args) -> None:
        selected_items = self.workflow_matched_files_tree.selectedItems()
        if not selected_items or not self.workflow_profiles_state:
            return
        profile_labels = [profile.label for profile in self.workflow_profiles_state]
        selected_label, accepted = QInputDialog.getItem(
            self,
            "Assign Workflow Profile",
            "Choose a workflow profile for the selected files:",
            profile_labels,
            0,
            False,
        )
        if not accepted or not selected_label:
            return
        selected_profile = next((profile for profile in self.workflow_profiles_state if profile.label == selected_label), None)
        if selected_profile is None:
            return
        for item in selected_items:
            relative_path = str(item.data(0, Qt.UserRole) or "").strip()
            if not relative_path:
                continue
            self.texture_rules_state.append(
                TextureRule(
                    pattern=relative_path,
                    enabled=True,
                    match_mode="exact",
                    workflow_profile_id=selected_profile.profile_id,
                    source_line=relative_path,
                )
            )
        self._refresh_workflow_rules_tree(select_index=len(self.texture_rules_state) - 1)
        self.schedule_settings_save()
        self._schedule_workflow_match_refresh()

    def _apply_workflow_state_from_config(self, config: AppConfig) -> None:
        legacy_text = str(getattr(config, "texture_rules_text", "") or "")
        workflow_profiles = list(coerce_texture_workflow_profiles(getattr(config, "workflow_profiles", ())))
        texture_rules = list(coerce_texture_workflow_rules(getattr(config, "texture_rules", ())))
        if not workflow_profiles and not texture_rules and legacy_text.strip():
            migrated_profiles, migrated_rules = migrate_legacy_texture_rules_to_structured(legacy_text)
            workflow_profiles = list(migrated_profiles)
            texture_rules = list(migrated_rules)
        elif should_seed_default_texture_workflow_state(workflow_profiles, texture_rules):
            workflow_profiles = list(build_default_texture_workflow_profiles())
            texture_rules = list(build_default_texture_workflow_rules())
        workflow_profiles_tuple, texture_rules_tuple = upgrade_default_texture_workflow_state(workflow_profiles, texture_rules)
        self.texture_rules_legacy_text = legacy_text
        self.workflow_profiles_state = list(workflow_profiles_tuple)
        self.texture_rules_state = list(texture_rules_tuple)
        self._refresh_workflow_profile_ncnn_model_combo()
        self._refresh_workflow_profiles_tree()
        self._refresh_workflow_rules_tree()
        self._schedule_workflow_match_refresh()

    def _workflow_profile_field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("WorkflowProfileFieldLabel")
        return label

    def _create_workflow_profile_panel(self, title: str, role: str):
        panel = QFrame()
        panel.setObjectName("WorkflowProfilePanel")
        panel.setProperty("profileRole", role)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 6, 8, 8)
        panel_layout.setSpacing(5)

        title_label = QLabel(title)
        title_label.setObjectName("WorkflowProfilePanelTitle")
        title_label.setProperty("profileRole", role)

        fields_layout = QGridLayout()
        fields_layout.setHorizontalSpacing(8)
        fields_layout.setVerticalSpacing(5)
        fields_layout.setColumnMinimumWidth(0, 96)
        fields_layout.setColumnMinimumWidth(2, 108)
        fields_layout.setColumnStretch(1, 1)
        fields_layout.setColumnStretch(3, 1)

        panel_layout.addWidget(title_label)
        panel_layout.addLayout(fields_layout)
        return panel, fields_layout

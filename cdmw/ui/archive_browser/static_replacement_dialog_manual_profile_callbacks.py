"""Manual material profile callback factory for the static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace


def create_manual_material_profile_runtime_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Dict = context.get('Dict')
    Mapping = context.get('Mapping')
    Optional = context.get('Optional')
    QCheckBox = context.get('QCheckBox')
    QComboBox = context.get('QComboBox')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    QMessageBox = context.get('QMessageBox')
    QSpinBox = context.get('QSpinBox')
    Sequence = context.get('Sequence')
    _coerce_manual_profile_values = context.get('_coerce_manual_profile_values')
    _complete_external_swap_enabled = context.get('_complete_external_swap_enabled')
    _delete_manual_material_profile_preset_helper = context.get('_delete_manual_material_profile_preset_helper')
    _manual_material_profile_control_effect_states_helper = context.get('_manual_material_profile_control_effect_states_helper')
    _manual_material_profile_delete_question_helper = context.get('_manual_material_profile_delete_question_helper')
    _manual_material_profile_dirty_state_helper = context.get('_manual_material_profile_dirty_state_helper')
    _manual_material_profile_panel_state_helper = context.get('_manual_material_profile_panel_state_helper')
    _manual_material_profile_preset_from_fields_helper = context.get('_manual_material_profile_preset_from_fields_helper')
    _manual_material_profile_preset_metadata_helper = context.get('_manual_material_profile_preset_metadata_helper')
    _manual_material_profile_preset_names_helper = context.get('_manual_material_profile_preset_names_helper')
    _manual_material_profile_saved_message_helper = context.get('_manual_material_profile_saved_message_helper')
    _manual_material_profile_token_helper = context.get('_manual_material_profile_token_helper')
    _modify_original_manual_texture_tuning_values_helper = context.get('_modify_original_manual_texture_tuning_values_helper')
    _modify_original_texture_tuning_enabled = context.get('_modify_original_texture_tuning_enabled')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _refresh_output_impact_review = context.get('_refresh_output_impact_review')
    _save_manual_profile_presets = context.get('_save_manual_profile_presets')
    _selected_manual_material_profile_preset_helper = context.get('_selected_manual_material_profile_preset_helper')
    _upsert_manual_material_profile_preset_helper = context.get('_upsert_manual_material_profile_preset_helper')
    complete_swap_material_profile_combo = context.get('complete_swap_material_profile_combo')
    complete_swap_profile_store_path = context.get('complete_swap_profile_store_path')
    dialog = context.get('dialog')
    json = context.get('json')
    manual_profile_apply_button = context.get('manual_profile_apply_button')
    manual_profile_change_status = context.get('manual_profile_change_status')
    manual_profile_control_text = context.get('manual_profile_control_text')
    manual_profile_control_tooltips = context.get('manual_profile_control_tooltips')
    manual_profile_controls = context.get('manual_profile_controls')
    manual_profile_default_values = context.get('manual_profile_default_values')
    manual_profile_dirty = context.get('manual_profile_dirty')
    manual_profile_effect_widgets = context.get('manual_profile_effect_widgets')
    manual_profile_group = context.get('manual_profile_group')
    manual_profile_preset_combo = context.get('manual_profile_preset_combo')
    manual_profile_preset_details_edit = context.get('manual_profile_preset_details_edit')
    manual_profile_preset_name_edit = context.get('manual_profile_preset_name_edit')
    manual_profile_preset_recommended_edit = context.get('manual_profile_preset_recommended_edit')
    manual_profile_presets = context.get('manual_profile_presets')
    manual_profile_ready = context.get('manual_profile_ready')
    manual_profile_saved_values = context.get('manual_profile_saved_values')
    manual_profile_settings_key = context.get('manual_profile_settings_key')
    modify_original_clone_mode = bool(context.get('modify_original_clone_mode'))
    self = context.get('self')
    serialize_complete_swap_manual_material_profile = context.get('serialize_complete_swap_manual_material_profile')
    write_complete_swap_calibrated_material_profile = context.get('write_complete_swap_calibrated_material_profile')

    def _modify_original_tuning_enabled_value() -> bool:
        if not callable(_modify_original_texture_tuning_enabled):
            return False
        return bool(_modify_original_texture_tuning_enabled())

    def _sanitize_modify_original_manual_values(values: Mapping[str, object]) -> Dict[str, object]:
        return dict(
            _modify_original_manual_texture_tuning_values_helper(
                values,
                defaults=manual_profile_default_values,
            )
        )

    def _current_manual_material_profile_values() -> Dict[str, object]:
        values: Dict[str, object] = dict(manual_profile_default_values) if modify_original_clone_mode else {}
        for key, control in manual_profile_controls.items():
            if isinstance(control, QComboBox):
                values[key] = str(control.currentData() or "")
            elif isinstance(control, QSpinBox):
                values[key] = int(control.value())
            elif isinstance(control, QDoubleSpinBox):
                values[key] = float(control.value())
            elif isinstance(control, QCheckBox):
                values[key] = bool(control.isChecked())
            elif isinstance(control, tuple):
                rgb_values: list[int] = []
                for channel_control in control:
                    if isinstance(channel_control, QSpinBox):
                        rgb_values.append(int(channel_control.value()))
                if len(rgb_values) >= 3:
                    values[key] = tuple(rgb_values[:3])
        if modify_original_clone_mode:
            return _sanitize_modify_original_manual_values(values)
        return values

    def _refresh_manual_profile_control_effects(values: Optional[Mapping[str, object]] = None) -> None:
        current_values = dict(values or _current_manual_material_profile_values())
        control_states = _manual_material_profile_control_effect_states_helper(
            current_values,
            control_keys=tuple(manual_profile_effect_widgets),
            control_tooltips=manual_profile_control_tooltips,
        )
        for key, widgets in manual_profile_effect_widgets.items():
            state = control_states.get(key, {})
            for widget in widgets:
                if hasattr(widget, "setEnabled"):
                    widget.setEnabled(bool(state.get("enabled", True)))
                if hasattr(widget, "setToolTip"):
                    widget.setToolTip(str(state.get("tooltip", "")))

    def _set_manual_profile_dirty(dirty: bool) -> None:
        state = _manual_material_profile_dirty_state_helper(dirty)
        manual_profile_dirty["dirty"] = bool(state["dirty"])
        manual_profile_apply_button.setEnabled(bool(state["apply_enabled"]))
        manual_profile_change_status.setText(str(state["status_text"]))

    def _apply_manual_material_profile_values(values: Mapping[str, object], *, persist: bool, refresh_preview: bool = False) -> None:
        was_ready = bool(manual_profile_ready.get("ready"))
        manual_profile_ready["ready"] = False
        try:
            for key, control in manual_profile_controls.items():
                value = values.get(key, manual_profile_default_values.get(key))
                if isinstance(control, QComboBox):
                    index = control.findData(str(value or ""))
                    control.setCurrentIndex(max(0, index))
                elif isinstance(control, QSpinBox):
                    try:
                        control.setValue(int(value))
                    except (TypeError, ValueError, OverflowError):
                        pass
                elif isinstance(control, QDoubleSpinBox):
                    try:
                        control.setValue(float(value))
                    except (TypeError, ValueError, OverflowError):
                        pass
                elif isinstance(control, QCheckBox):
                    control.setChecked(bool(value))
                elif isinstance(control, tuple):
                    rgb = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()
                    for channel_index, channel_control in enumerate(control):
                        if not isinstance(channel_control, QSpinBox):
                            continue
                        try:
                            channel_control.setValue(int(rgb[channel_index]))
                        except (TypeError, ValueError, OverflowError, IndexError):
                            pass
        finally:
            manual_profile_ready["ready"] = was_ready
        if persist:
            saved = _current_manual_material_profile_values()
            manual_profile_saved_values.clear()
            manual_profile_saved_values.update(saved)
            self.settings.setValue(manual_profile_settings_key, json.dumps(saved, sort_keys=True, separators=(",", ":")))
            _save_complete_swap_material_profile()
            _refresh_manual_profile_control_effects(saved)
            if refresh_preview:
                _set_manual_profile_dirty(False)
                _refresh_output_impact_review()
                _queue_texture_preview_refresh()
            else:
                _set_manual_profile_dirty(True)

    def _reset_manual_material_profile_to_material_authority() -> None:
        _apply_manual_material_profile_values(manual_profile_default_values, persist=True, refresh_preview=True)

    def _apply_current_manual_material_profile_to_preview() -> None:
        if modify_original_clone_mode:
            if not _modify_original_tuning_enabled_value():
                return
        elif str(complete_swap_material_profile_combo.currentData() or "") != "material_authority_manual":
            return
        values = _current_manual_material_profile_values()
        self.settings.setValue(manual_profile_settings_key, json.dumps(values, sort_keys=True, separators=(",", ":")))
        manual_profile_saved_values.clear()
        manual_profile_saved_values.update(values)
        _save_complete_swap_material_profile()
        _set_manual_profile_dirty(False)
        _refresh_output_impact_review()
        _queue_texture_preview_refresh()

    _selected_manual_profile_preset = lambda: _selected_manual_material_profile_preset_helper(
            manual_profile_presets,
            manual_profile_preset_combo.currentData(),
        )

    def _refresh_manual_profile_preset_combo(select_name: str = "") -> None:
        current_name = str(select_name or manual_profile_preset_combo.currentData() or "").strip()
        manual_profile_preset_combo.blockSignals(True)
        try:
            manual_profile_preset_combo.clear()
            manual_profile_preset_combo.addItem(manual_profile_control_text["no_saved_profile"], "")
            for name in _manual_material_profile_preset_names_helper(manual_profile_presets):
                manual_profile_preset_combo.addItem(name, name)
            index = manual_profile_preset_combo.findData(current_name)
            manual_profile_preset_combo.setCurrentIndex(max(0, index))
        finally:
            manual_profile_preset_combo.blockSignals(False)
        _show_selected_manual_profile_preset_metadata()

    def _show_selected_manual_profile_preset_metadata() -> None:
        preset = _selected_manual_profile_preset()
        if preset is None:
            return
        metadata = _manual_material_profile_preset_metadata_helper(preset)
        manual_profile_preset_name_edit.setText(metadata["name"])
        manual_profile_preset_details_edit.setPlainText(metadata["details"])
        manual_profile_preset_recommended_edit.setText(metadata["recommended_models"])

    def _save_current_manual_profile_preset() -> None:
        name = manual_profile_preset_name_edit.text().strip()
        if not name:
            QMessageBox.information(
                dialog,
                manual_profile_control_text["save_title"],
                manual_profile_control_text["save_missing_name"],
            )
            return
        preset = _manual_material_profile_preset_from_fields_helper(
            name=name,
            details=manual_profile_preset_details_edit.toPlainText(),
            recommended_models=manual_profile_preset_recommended_edit.text(),
            values=_current_manual_material_profile_values(),
        )
        manual_profile_presets[:] = _upsert_manual_material_profile_preset_helper(manual_profile_presets, preset)
        _save_manual_profile_presets(manual_profile_presets)
        _refresh_manual_profile_preset_combo(name)
        QMessageBox.information(
            dialog,
            manual_profile_control_text["save_title"],
            _manual_material_profile_saved_message_helper(name),
        )

    def _load_selected_manual_profile_preset() -> None:
        preset = _selected_manual_profile_preset()
        if preset is None:
            QMessageBox.information(
                dialog,
                manual_profile_control_text["load_title"],
                manual_profile_control_text["load_missing_selection"],
            )
            return
        _show_selected_manual_profile_preset_metadata()
        _apply_manual_material_profile_values(_coerce_manual_profile_values(preset.get("values")), persist=True, refresh_preview=True)

    def _delete_selected_manual_profile_preset() -> None:
        preset = _selected_manual_profile_preset()
        if preset is None:
            QMessageBox.information(
                dialog,
                manual_profile_control_text["delete_title"],
                manual_profile_control_text["delete_missing_selection"],
            )
            return
        name = str(preset.get("name") or "").strip()
        answer = QMessageBox.question(
            dialog,
            manual_profile_control_text["delete_title"],
            _manual_material_profile_delete_question_helper(name),
        )
        if answer != QMessageBox.Yes:
            return
        manual_profile_presets[:] = _delete_manual_material_profile_preset_helper(manual_profile_presets, name)
        _save_manual_profile_presets(manual_profile_presets)
        _refresh_manual_profile_preset_combo("")

    def _current_complete_swap_material_profile_token() -> str:
        if modify_original_clone_mode:
            if not _modify_original_tuning_enabled_value():
                return "material_authority_detail_mask"
            return str(
                serialize_complete_swap_manual_material_profile(
                    _current_manual_material_profile_values()
                )
            )
        profile_name = str(complete_swap_material_profile_combo.currentData() or "material_authority_detail_mask")
        return _manual_material_profile_token_helper(
            profile_name,
            manual_token=serialize_complete_swap_manual_material_profile(
                _current_manual_material_profile_values()
            ),
        )

    def _refresh_manual_material_profile_panel() -> None:
        if modify_original_clone_mode:
            manual_profile_group.setVisible(_modify_original_tuning_enabled_value())
            manual_profile_group.setEnabled(_modify_original_tuning_enabled_value())
            _refresh_manual_profile_control_effects()
            return
        state = _manual_material_profile_panel_state_helper(
            complete_swap_material_profile_combo.currentData(),
            complete_enabled=_complete_external_swap_enabled(),
        )
        manual_profile_group.setVisible(bool(state["visible"]))
        manual_profile_group.setEnabled(bool(state["enabled"]))
        _refresh_manual_profile_control_effects()

    def _save_complete_swap_material_profile() -> None:
        if modify_original_clone_mode:
            self.settings.setValue(
                manual_profile_settings_key,
                json.dumps(_current_manual_material_profile_values(), sort_keys=True, separators=(",", ":")),
            )
            return
        profile_name = str(complete_swap_material_profile_combo.currentData() or "material_authority_detail_mask")
        self.settings.setValue("settings/complete_swap_material_profile", profile_name)
        if profile_name == "material_authority_manual":
            self.settings.setValue(
                manual_profile_settings_key,
                json.dumps(_current_manual_material_profile_values(), sort_keys=True, separators=(",", ":")),
            )
        try:
            write_complete_swap_calibrated_material_profile(
                complete_swap_profile_store_path,
                _current_complete_swap_material_profile_token(),
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            # Best effort: settings above remain authoritative if calibrated profile persistence fails.
            pass

    return SimpleNamespace(
        _current_manual_material_profile_values=_current_manual_material_profile_values,
        _refresh_manual_profile_control_effects=_refresh_manual_profile_control_effects,
        _set_manual_profile_dirty=_set_manual_profile_dirty,
        _apply_manual_material_profile_values=_apply_manual_material_profile_values,
        _reset_manual_material_profile_to_material_authority=_reset_manual_material_profile_to_material_authority,
        _apply_current_manual_material_profile_to_preview=_apply_current_manual_material_profile_to_preview,
        _selected_manual_profile_preset=_selected_manual_profile_preset,
        _refresh_manual_profile_preset_combo=_refresh_manual_profile_preset_combo,
        _show_selected_manual_profile_preset_metadata=_show_selected_manual_profile_preset_metadata,
        _save_current_manual_profile_preset=_save_current_manual_profile_preset,
        _load_selected_manual_profile_preset=_load_selected_manual_profile_preset,
        _delete_selected_manual_profile_preset=_delete_selected_manual_profile_preset,
        _current_complete_swap_material_profile_token=_current_complete_swap_material_profile_token,
        _refresh_manual_material_profile_panel=_refresh_manual_material_profile_panel,
        _save_complete_swap_material_profile=_save_complete_swap_material_profile,
    )

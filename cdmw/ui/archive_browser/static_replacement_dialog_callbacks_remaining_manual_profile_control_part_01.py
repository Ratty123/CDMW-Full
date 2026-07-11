from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
    resident_material_parameters_available,
    resident_material_resources_available,
)

def _remaining_manual_profile_control_step_001(_state):
    _state.state = _state._StaticReplacementDialogState(_state.context)
    _state.QCheckBox = _state.context.get('QCheckBox')
    _state.QComboBox = _state.context.get('QComboBox')
    _state.QDoubleSpinBox = _state.context.get('QDoubleSpinBox')
    _state.QHBoxLayout = _state.context.get('QHBoxLayout')
    _state.QLabel = _state.context.get('QLabel')
    _state.QSlider = _state.context.get('QSlider')
    _state.QSpinBox = _state.context.get('QSpinBox')
    _state.Qt = _state.context.get('Qt')
    _state.Sequence = _state.context.get('Sequence')
    _state._current_manual_material_profile_values = _state.context.get('_current_manual_material_profile_values')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._make_int_spin_helper = _state.context.get('_make_int_spin_helper')
    _state._modify_original_texture_tuning_enabled = _state.context.get('_modify_original_texture_tuning_enabled')
    _state._queue_material_authority_adjustment_preview_refresh = _state.context.get('_queue_material_authority_adjustment_preview_refresh')
    _state._queue_texture_preview_refresh = _state.context.get('_queue_texture_preview_refresh')
    _state._refresh_manual_profile_control_effects = _state.context.get('_refresh_manual_profile_control_effects')
    _state._refresh_output_impact_review = _state.context.get('_refresh_output_impact_review')
    _state._save_complete_swap_material_profile = _state.context.get('_save_complete_swap_material_profile')
    _state._set_manual_profile_dirty = _state.context.get('_set_manual_profile_dirty')
    _state.channel_index = _state.context.get('channel_index')
    _state.channel_name = _state.context.get('channel_name')
    _state.channel_spin = _state.context.get('channel_spin')
    _state.channel_value = _state.context.get('channel_value')
    _state.checkbox = _state.context.get('checkbox')
    _state.choices = _state.context.get('choices')
    _state.combo = _state.context.get('combo')
    _state.complete_swap_material_profile_combo = _state.context.get('complete_swap_material_profile_combo')
    _state.dialog = _state.context.get('dialog')
    _state.index = _state.context.get('index')
    _state.json = _state.context.get('json')
    _state.key = _state.context.get('key')
    _state.label = _state.context.get('label')
    _state.label_widget = _state.context.get('label_widget')
    _state.manual_profile_control_tooltips = _state.context.get('manual_profile_control_tooltips')
    _state.manual_profile_controls = _state.context.get('manual_profile_controls')
    _state.manual_profile_default_values = _state.context.get('manual_profile_default_values')
    _state.manual_profile_effect_widgets = _state.context.get('manual_profile_effect_widgets')
    _state.manual_profile_layout = _state.context.get('manual_profile_layout')
    _state.manual_profile_ready = _state.context.get('manual_profile_ready')
    _state.manual_profile_saved_values = _state.context.get('manual_profile_saved_values')
    _state.manual_profile_settings_key = _state.context.get('manual_profile_settings_key')
    _state.modify_original_clone_mode = bool(_state.context.get('modify_original_clone_mode'))
    _state.maximum = _state.context.get('maximum')
    _state.minimum = _state.context.get('minimum')
    _state.raw = _state.context.get('raw')
    _state.raw_rgb = _state.context.get('raw_rgb')
    _state.rgb = _state.context.get('rgb')
    _state.row = _state.context.get('row')
    _state.row_layout = _state.context.get('row_layout')
    _state.self = _state.context.get('self')
    _state.slider = _state.context.get('slider')
    _state.slider_scale = _state.context.get('slider_scale')
    _state.spin = _state.context.get('spin')
    _state.spins = _state.context.get('spins')
    _state.step = _state.context.get('step')
    _state.target = _state.context.get('target')
    _state.text = _state.context.get('text')
    _state.tooltip = _state.context.get('tooltip')
    _state.value = _state.context.get('value')
    _state.values = _state.context.get('values')

def _remaining_manual_profile_control_step_002(_state):

    def _modify_original_tuning_enabled_value() -> bool:
        if not callable(_state._modify_original_texture_tuning_enabled):
            return False
        return bool(_state._modify_original_texture_tuning_enabled())
    _state._modify_original_tuning_enabled_value = _modify_original_tuning_enabled_value

def _remaining_manual_profile_control_step_003(_state):

    def _manual_profile_refresh_preview(resource_keys=()) -> None:
        try:
            editor_active = bool(_state._alignment_mesh_edit_tab_active()) if callable(_state._alignment_mesh_edit_tab_active) else False
        except (AttributeError, RuntimeError, TypeError, ValueError):
            editor_active = False
        if editor_active:
            if resident_material_parameters_available(_state.dialog) or resident_material_resources_available(_state.dialog):
                _state._queue_material_authority_adjustment_preview_refresh(resource_keys=tuple(resource_keys or ()))
            return
        _state._queue_texture_preview_refresh()
    _state._manual_profile_refresh_preview = _manual_profile_refresh_preview

    def _manual_profile_mark_changed(resource_key: str = "") -> None:
        if not _state.manual_profile_ready.get('ready'):
            return
        values = _state._current_manual_material_profile_values()
        _state.self.settings.setValue(_state.manual_profile_settings_key, _state.json.dumps(values, sort_keys=True, separators=(',', ':')))
        _state._save_complete_swap_material_profile()
        _state._refresh_manual_profile_control_effects(values)
        _state._set_manual_profile_dirty(True)
        if _state.modify_original_clone_mode and _state._modify_original_tuning_enabled_value():
            _state._refresh_output_impact_review()
            _state._manual_profile_refresh_preview((resource_key,) if resource_key else ())
        elif str(_state.complete_swap_material_profile_combo.currentData() or '') == 'material_authority_manual':
            try:
                _state._refresh_output_impact_review()
                _state._manual_profile_refresh_preview((resource_key,) if resource_key else ())
            except NameError:
                pass
    _state._manual_profile_mark_changed = _manual_profile_mark_changed

def _remaining_manual_profile_control_step_004(_state):

    def _manual_combo(row: int, key: str, label: str, choices: Sequence[tuple[str, str]], tooltip: str) -> None:
        label_widget = _state.QLabel(label)
        label_widget.setToolTip(tooltip)
        combo = _state.QComboBox()
        combo.setObjectName(f'MeshAlignmentManualMaterialProfile_{key}')
        combo.setToolTip(tooltip)
        for text, value in choices:
            combo.addItem(text, value)
        index = combo.findData(str(_state.manual_profile_saved_values.get(key, '')))
        combo.setCurrentIndex(max(0, index))
        combo.currentIndexChanged.connect(lambda _index, control_key=key: _state._manual_profile_mark_changed(control_key))
        _state.manual_profile_controls[key] = combo
        _state.manual_profile_effect_widgets[key] = [label_widget, combo]
        _state.manual_profile_control_tooltips[key] = tooltip
        _state.manual_profile_layout.addWidget(label_widget, row, 0)
        _state.manual_profile_layout.addWidget(combo, row, 1, 1, 3)
    _state._manual_combo = _manual_combo

def _remaining_manual_profile_control_step_005(_state):

    def _manual_int(row: int, key: str, label: str, minimum: int, maximum: int, tooltip: str) -> None:
        label_widget = _state.QLabel(label)
        label_widget.setToolTip(tooltip)
        slider = _state.QSlider(_state.Qt.Horizontal)
        slider.setObjectName(f'MeshAlignmentManualMaterialProfile_{key}_Slider')
        slider.setRange(minimum, maximum)
        spin = _state.QSpinBox()
        spin.setObjectName(f'MeshAlignmentManualMaterialProfile_{key}_Spin')
        spin.setRange(minimum, maximum)
        value = max(minimum, min(maximum, int(_state.manual_profile_saved_values.get(key, _state.manual_profile_default_values.get(key, minimum)) or minimum)))
        slider.setValue(value)
        spin.setValue(value)
        slider.setToolTip(tooltip)
        spin.setToolTip(tooltip)
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        spin.valueChanged.connect(lambda _value, control_key=key: _state._manual_profile_mark_changed(control_key))
        _state.manual_profile_controls[key] = spin
        _state.manual_profile_effect_widgets[key] = [label_widget, slider, spin]
        _state.manual_profile_control_tooltips[key] = tooltip
        _state.manual_profile_layout.addWidget(label_widget, row, 0)
        _state.manual_profile_layout.addWidget(slider, row, 1)
        _state.manual_profile_layout.addWidget(spin, row, 2)
    _state._manual_int = _manual_int

def _remaining_manual_profile_control_step_006(_state):

    def _manual_float(row: int, key: str, label: str, minimum: float, maximum: float, step: float, tooltip: str) -> None:
        label_widget = _state.QLabel(label)
        label_widget.setToolTip(tooltip)
        slider_scale = 100
        slider = _state.QSlider(_state.Qt.Horizontal)
        slider.setObjectName(f'MeshAlignmentManualMaterialProfile_{key}_Slider')
        slider.setRange(int(round(minimum * slider_scale)), int(round(maximum * slider_scale)))
        spin = _state.QDoubleSpinBox()
        spin.setObjectName(f'MeshAlignmentManualMaterialProfile_{key}_Spin')
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(2)
        value = float(_state.manual_profile_saved_values.get(key, _state.manual_profile_default_values.get(key, minimum)) or minimum)
        value = max(minimum, min(maximum, value))
        slider.setValue(int(round(value * slider_scale)))
        spin.setValue(value)
        slider.setToolTip(tooltip)
        spin.setToolTip(tooltip)
        slider.valueChanged.connect(lambda raw, target=spin: target.setValue(float(raw) / slider_scale))
        spin.valueChanged.connect(lambda value, target=slider: target.setValue(int(round(float(value) * slider_scale))))
        spin.valueChanged.connect(lambda _value, control_key=key: _state._manual_profile_mark_changed(control_key))
        _state.manual_profile_controls[key] = spin
        _state.manual_profile_effect_widgets[key] = [label_widget, slider, spin]
        _state.manual_profile_control_tooltips[key] = tooltip
        _state.manual_profile_layout.addWidget(label_widget, row, 0)
        _state.manual_profile_layout.addWidget(slider, row, 1)
        _state.manual_profile_layout.addWidget(spin, row, 2)
    _state._manual_float = _manual_float

def _remaining_manual_profile_control_step_007(_state):

    def _manual_check(row: int, key: str, text: str, tooltip: str) -> None:
        checkbox = _state.QCheckBox(text)
        checkbox.setObjectName(f'MeshAlignmentManualMaterialProfile_{key}')
        checkbox.setToolTip(tooltip)
        checkbox.setChecked(bool(_state.manual_profile_saved_values.get(key, _state.manual_profile_default_values.get(key, False))))
        checkbox.toggled.connect(lambda _checked, control_key=key: _state._manual_profile_mark_changed(control_key))
        _state.manual_profile_controls[key] = checkbox
        _state.manual_profile_effect_widgets[key] = [checkbox]
        _state.manual_profile_control_tooltips[key] = tooltip
        _state.manual_profile_layout.addWidget(checkbox, row, 0, 1, 4)
    _state._manual_check = _manual_check

def _remaining_manual_profile_control_step_008(_state):

    def _manual_rgb(row: int, key: str, label: str, tooltip: str) -> None:
        label_widget = _state.QLabel(label)
        label_widget.setToolTip(tooltip)
        row_layout = _state.QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        raw_rgb = _state.manual_profile_saved_values.get(key, _state.manual_profile_default_values.get(key, (216, 216, 216)))
        rgb = tuple(raw_rgb if isinstance(raw_rgb, _state.Sequence) and (not isinstance(raw_rgb, (str, bytes))) else (216, 216, 216))
        spins: list[_state.QSpinBox] = []
        for channel_index, channel_name in enumerate(('R', 'G', 'B')):
            try:
                channel_value = int(rgb[channel_index])
            except (TypeError, ValueError, IndexError):
                channel_value = 216
            channel_spin = _state._make_int_spin_helper(object_name=f'MeshAlignmentManualMaterialProfile_{key}_{channel_name}', minimum=0, maximum=255, value=channel_value, prefix=f'{channel_name} ', tooltip=tooltip)
            channel_spin.valueChanged.connect(lambda _value, control_key=key: _state._manual_profile_mark_changed(control_key))
            row_layout.addWidget(channel_spin)
            spins.append(channel_spin)
        _state.manual_profile_controls[key] = tuple(spins)
        _state.manual_profile_effect_widgets[key] = [label_widget, *spins]
        _state.manual_profile_control_tooltips[key] = tooltip
        _state.manual_profile_layout.addWidget(label_widget, row, 0)
        _state.manual_profile_layout.addLayout(row_layout, row, 1, 1, 2)
    _state._manual_rgb = _manual_rgb

def _remaining_manual_profile_control_step_009(_state):
    _state._factory_result_values.update({'_manual_profile_mark_changed': _state._manual_profile_mark_changed, '_manual_combo': _state._manual_combo, '_manual_int': _state._manual_int, '_manual_float': _state._manual_float, '_manual_check': _state._manual_check, '_manual_rgb': _state._manual_rgb})

STEPS = (
    _remaining_manual_profile_control_step_001,
    _remaining_manual_profile_control_step_002,
    _remaining_manual_profile_control_step_003,
    _remaining_manual_profile_control_step_004,
    _remaining_manual_profile_control_step_005,
    _remaining_manual_profile_control_step_006,
    _remaining_manual_profile_control_step_007,
    _remaining_manual_profile_control_step_008,
    _remaining_manual_profile_control_step_009,
)

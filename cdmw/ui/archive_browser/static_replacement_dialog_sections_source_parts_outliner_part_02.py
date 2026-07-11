from __future__ import annotations

def _source_parts_outliner_step_018(_state):
    _state.assign_source_button.clicked.connect(_state._assign_selected_source_to_target)
    _state.merge_source_button.clicked.connect(_state._merge_selected_source_into_target)
    _state.remove_source_button.clicked.connect(_state._remove_selected_source_from_target)
    _state.clear_target_button.clicked.connect(_state._clear_selected_target)
    _state.delete_source_parts_button.clicked.connect(lambda _checked=False: _state._delete_selected_source_parts())
    _state.apply_source_parts_button.clicked.connect(_state._apply_source_part_preview_changes)
    _state.group_materials_button.clicked.connect(_state._apply_source_material_grouped_routing)
    _state.preview_target_button.clicked.connect(_state._preview_selected_target_slot)
    _state.original_clear_selection_button.clicked.connect(_state._clear_original_selection)
    _state.clear_replacement_selection_button.clicked.connect(_state._clear_replacement_selection)
    _state.clear_all_selection_button.clicked.connect(_state._clear_all_part_selections)
    _state.clear_alignment_selection_button.clicked.connect(_state._clear_all_part_selections)
    _state.source_part_inspector_control_text = _state._source_part_inspector_control_text_helper()
    _state.part_inspector = _state.QGroupBox(_state.source_part_inspector_control_text['group_title'])
    _state.part_layout = _state.QGridLayout(_state.part_inspector)
    _state.part_layout.setContentsMargins(5, 3, 5, 3)
    _state.part_layout.setHorizontalSpacing(4)
    _state.part_layout.setVerticalSpacing(2)
    _state.part_workflow_hint = _state.QLabel(_state.source_part_inspector_control_text['workflow_hint'])
    _state.part_workflow_hint.setObjectName('HintLabel')
    _state.part_workflow_hint.setWordWrap(True)
    _state.part_workflow_hint.setToolTip(_state.source_part_inspector_control_text['workflow_hint_tooltip'])
    _state.part_workflow_hint.setVisible(False)
    _state.part_source_combo = _state.QComboBox()
    _state.part_source_combo.addItem(_state.source_part_inspector_control_text['source_select_label'], -1)
    if _state.replacement_mesh_for_mapping is not None:
        for _state.source_index, _state.source in enumerate(_state.replacement_mesh_for_mapping.submeshes):
            if _state._is_marker_source(_state.source):
                continue
            _state.part_source_combo.addItem(_state._source_display_name(_state.source_index), _state.source_index)
    _state.part_source_combo.setMinimumContentsLength(16)
    _state.part_source_combo.setSizeAdjustPolicy(_state.QComboBox.AdjustToMinimumContentsLengthWithIcon)
    _state.part_source_combo.setToolTip(_state.source_part_inspector_control_text['source_combo_tooltip'])
    _state.part_name_label = _state.QLabel(_state.source_part_inspector_control_text['name_placeholder'])
    _state.part_name_label.setTextInteractionFlags(_state.Qt.TextSelectableByMouse)
    _state.part_target_label = _state.QLabel(_state.source_part_inspector_control_text['target_placeholder'])
    _state.part_target_label.setObjectName('HintLabel')
    _state.part_enabled_checkbox = _state.QCheckBox(_state.source_part_inspector_control_text['include_in_output'])
    _state.part_enabled_checkbox.setChecked(True)
    _state.part_role_combo = _state.QComboBox()
    for _state.role_label, _state.role_value in _state.SOURCE_ROLE_OPTIONS:
        _state.part_role_combo.addItem(_state.role_label, _state.role_value)
    _state.part_role_combo.setToolTip(_state.source_part_inspector_control_text['role_tooltip'])
    _state.part_target_combo = _state.QComboBox()
    _state.part_target_combo.addItem(_state.source_part_inspector_control_text['no_target_selected'], -1)
    if _state.original_mesh_for_mapping is not None:
        for _state.target_index, _state._target in enumerate(_state.original_mesh_for_mapping.submeshes):
            _state.part_target_combo.addItem(_state._target_display_name(_state.target_index), _state.target_index)
    _state.part_target_combo.setToolTip(_state.source_part_inspector_control_text['target_tooltip'])
    _state.part_replace_target_button = _state.QPushButton(_state.source_part_inspector_control_text['replace_target'])
    _state.part_add_target_button = _state.QPushButton(_state.source_part_inspector_control_text['add_target'])
    _state.part_remove_target_button = _state.QPushButton(_state.source_part_inspector_control_text['unmap_part'])
    _state.part_replace_target_button.setToolTip(_state.source_part_inspector_control_text['replace_target_tooltip'])
    _state.part_add_target_button.setToolTip(_state.source_part_inspector_control_text['add_target_tooltip'])
    _state.part_remove_target_button.setToolTip(_state.source_part_inspector_control_text['unmap_part_tooltip'])
    _state.part_layout.addWidget(_state.part_name_label, 0, 0, 1, 4)
    _state.part_layout.addWidget(_state.part_target_label, 1, 0, 1, 4)
    _state.part_layout.addWidget(_state.part_workflow_hint, 2, 0, 1, 4)
    _state.part_source_row = _state.QHBoxLayout()
    _state.part_source_row.setContentsMargins(0, 0, 0, 0)
    _state.part_source_row.setSpacing(4)
    _state.part_source_row.addWidget(_state.QLabel(_state.source_part_inspector_control_text['part_label']))
    _state.part_source_row.addWidget(_state.part_source_combo, 1)
    _state.append_mesh_part_button = _state.QPushButton(_state.source_part_inspector_control_text['add_mesh_part'])
    _state.append_mesh_part_button.setMinimumWidth(0)
    _state.append_mesh_part_button.setToolTip(_state.source_part_inspector_control_text['add_mesh_part_tooltip'])
    _state.duplicate_part_button = _state.QPushButton(_state.source_part_inspector_control_text['duplicate_part'])
    _state.duplicate_part_button.setMinimumWidth(0)
    _state.duplicate_part_button.setToolTip(_state.source_part_inspector_control_text['duplicate_part_tooltip'])
    _state.mirror_duplicate_part_button = _state.QPushButton(_state.source_part_inspector_control_text['mirror_duplicate_part'])
    _state.mirror_duplicate_part_button.setMinimumWidth(0)
    _state.mirror_duplicate_part_button.setToolTip(_state.source_part_inspector_control_text['mirror_duplicate_part_tooltip'])
    _state.part_source_row.addWidget(_state.append_mesh_part_button)
    _state.part_source_row.addWidget(_state.duplicate_part_button)
    _state.part_source_row.addWidget(_state.mirror_duplicate_part_button)
    _state.part_layout.addLayout(_state.part_source_row, 3, 0, 1, 4)
    _state.part_top_row = _state.QHBoxLayout()
    _state.part_top_row.setContentsMargins(0, 0, 0, 0)
    _state.part_top_row.setSpacing(4)
    _state.part_top_row.addWidget(_state.part_enabled_checkbox)
    _state.part_top_row.addWidget(_state.QLabel(_state.source_part_inspector_control_text['role_label']))
    _state.part_top_row.addWidget(_state.part_role_combo, 1)
    _state.part_top_row.addWidget(_state.QLabel(_state.source_part_inspector_control_text['map_to_label']))
    _state.part_top_row.addWidget(_state.part_target_combo, 1)
    _state.part_layout.addLayout(_state.part_top_row, 4, 0, 1, 4)
    _state.part_map_button_row = _state.QHBoxLayout()
    _state.part_map_button_row.setContentsMargins(0, 0, 0, 0)
    _state.part_map_button_row.setSpacing(3)
    _state.part_map_button_row.addWidget(_state.part_replace_target_button)
    _state.part_map_button_row.addWidget(_state.part_add_target_button)
    _state.part_map_button_row.addWidget(_state.part_remove_target_button)
    _state.part_layout.addLayout(_state.part_map_button_row, 5, 0, 1, 4)
    _state.part_copied_texture_row = _state.QHBoxLayout()
    _state.part_copied_texture_row.setContentsMargins(0, 0, 0, 0)
    _state.part_copied_texture_row.setSpacing(3)
    _state.part_copied_texture_status_label = _state.QLabel(_state.source_part_inspector_control_text['texture_status_initial'])
    _state.part_copied_texture_status_label.setObjectName('HintLabel')
    _state.part_use_copied_texture_button = _state.QPushButton(_state.source_part_inspector_control_text['use_copied_texture'])
    _state.part_use_route_texture_button = _state.QPushButton(_state.source_part_inspector_control_text['use_route_texture'])
    _state.part_remove_copied_texture_button = _state.QPushButton(_state.source_part_inspector_control_text['remove_copied_texture'])

def _source_parts_outliner_step_019(_state):
    for _state.copied_texture_button in (_state.part_use_copied_texture_button, _state.part_use_route_texture_button, _state.part_remove_copied_texture_button):
        _state.copied_texture_button.setMinimumWidth(0)
    _state.part_use_copied_texture_button.setToolTip(_state.source_part_inspector_control_text['use_copied_texture_tooltip'])
    _state.part_use_route_texture_button.setToolTip(_state.source_part_inspector_control_text['use_route_texture_tooltip'])
    _state.part_remove_copied_texture_button.setToolTip(_state.source_part_inspector_control_text['remove_copied_texture_tooltip'])
    _state.part_copied_texture_row.addWidget(_state.part_copied_texture_status_label, 1)
    _state.part_copied_texture_row.addWidget(_state.part_use_copied_texture_button)
    _state.part_copied_texture_row.addWidget(_state.part_use_route_texture_button)
    _state.part_copied_texture_row.addWidget(_state.part_remove_copied_texture_button)
    _state.part_layout.addLayout(_state.part_copied_texture_row, 6, 0, 1, 4)
    _state.part_offset_x_spin = _state._make_double_spin_helper(0.0, -10.0, 10.0, 5, 0.0005)
    _state.part_offset_y_spin = _state._make_double_spin_helper(0.0, -10.0, 10.0, 5, 0.0005)
    _state.part_offset_z_spin = _state._make_double_spin_helper(0.0, -10.0, 10.0, 5, 0.0005)
    _state.part_rotate_x_spin = _state._make_double_spin_helper(0.0, -360.0, 360.0, 2, 0.1, ' deg')
    _state.part_rotate_y_spin = _state._make_double_spin_helper(0.0, -360.0, 360.0, 2, 0.1, ' deg')
    _state.part_rotate_z_spin = _state._make_double_spin_helper(0.0, -360.0, 360.0, 2, 0.1, ' deg')
    _state.part_scale_x_spin = _state._make_double_spin_helper(1.0, 0.001, 100.0, 4, 0.005)
    _state.part_scale_y_spin = _state._make_double_spin_helper(1.0, 0.001, 100.0, 4, 0.005)
    _state.part_scale_z_spin = _state._make_double_spin_helper(1.0, 0.001, 100.0, 4, 0.005)
    _state.part_uniform_spin = _state._make_double_spin_helper(1.0, 0.001, 100.0, 4, 0.005)
    _state.part_controls = (_state.part_offset_x_spin, _state.part_offset_y_spin, _state.part_offset_z_spin, _state.part_rotate_x_spin, _state.part_rotate_y_spin, _state.part_rotate_z_spin, _state.part_scale_x_spin, _state.part_scale_y_spin, _state.part_scale_z_spin, _state.part_uniform_spin)
    for _state.axis_label, _state.spin in (('X', _state.part_offset_x_spin), ('Y', _state.part_offset_y_spin), ('Z', _state.part_offset_z_spin), ('X', _state.part_rotate_x_spin), ('Y', _state.part_rotate_y_spin), ('Z', _state.part_rotate_z_spin), ('X', _state.part_scale_x_spin), ('Y', _state.part_scale_y_spin), ('Z', _state.part_scale_z_spin)):
        _state.spin.setPrefix(f'{_state.axis_label} ')
    _state.source_part_transform_control_text = _state._source_part_transform_control_text_helper()
    _state.part_uniform_spin.setPrefix(_state.source_part_transform_control_text['uniform_prefix'])
    for _state.spin in (_state.part_offset_x_spin, _state.part_offset_y_spin, _state.part_offset_z_spin):
        _state.spin.setToolTip(_state.source_part_transform_control_text['translate_spin_tooltip'])
    for _state.spin in (_state.part_rotate_x_spin, _state.part_rotate_y_spin, _state.part_rotate_z_spin):
        _state.spin.setToolTip(_state.source_part_transform_control_text['rotate_spin_tooltip'])
    for _state.spin in (_state.part_scale_x_spin, _state.part_scale_y_spin, _state.part_scale_z_spin):
        _state.spin.setToolTip(_state.source_part_transform_control_text['axis_spin_tooltip'])
    _state.part_uniform_spin.setToolTip(_state.source_part_transform_control_text['uniform_spin_tooltip'])
    for _state.part_spin in _state.part_controls:
        _state.part_spin.setMinimumWidth(0)
        _state.part_spin.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Fixed)
    _state.part_transform_sliders: _state.Dict[_state.QDoubleSpinBox, _state.QSlider] = {}
    _state.alignment_source_part_transform_control_callbacks = _state.create_alignment_source_part_transform_control_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._part_transform_slider = _state.alignment_source_part_transform_control_callbacks._part_transform_slider
    _state._sync_part_slider_from_spin = _state.alignment_source_part_transform_control_callbacks._sync_part_slider_from_spin
    _state._part_spin_with_slider = lambda spin, *, scale, tooltip, slider_minimum=None, slider_maximum=None: _state._wrap_spin_with_slider_helper(spin, _state._part_transform_slider(spin, scale=scale, tooltip=tooltip, slider_minimum=slider_minimum, slider_maximum=slider_maximum))
    _state.part_layout.addWidget(_state.QLabel(_state.source_part_transform_control_text['translate_label']), 7, 0)
    _state.part_layout.addWidget(_state._part_spin_with_slider(_state.part_offset_x_spin, scale=2000.0, tooltip=_state.source_part_transform_control_text['translate_x_tooltip']), 7, 1)
    _state.part_layout.addWidget(_state._part_spin_with_slider(_state.part_offset_y_spin, scale=2000.0, tooltip=_state.source_part_transform_control_text['translate_y_tooltip']), 7, 2)
    _state.part_layout.addWidget(_state._part_spin_with_slider(_state.part_offset_z_spin, scale=2000.0, tooltip=_state.source_part_transform_control_text['translate_z_tooltip']), 7, 3)
    _state.part_nudge_step_spin = _state._make_double_spin_helper(0.005, 1e-05, 1.0, 5, 0.0005)
    _state.part_nudge_step_spin.setPrefix(_state.source_part_transform_control_text['nudge_step_prefix'])
    _state.part_nudge_step_spin.setToolTip(_state.source_part_transform_control_text['nudge_step_tooltip'])
    _state.part_nudge_x_minus_button = _state.QPushButton(_state.source_part_transform_control_text['nudge_x_minus'])
    _state.part_nudge_x_plus_button = _state.QPushButton(_state.source_part_transform_control_text['nudge_x_plus'])
    _state.part_nudge_y_minus_button = _state.QPushButton(_state.source_part_transform_control_text['nudge_y_minus'])
    _state.part_nudge_y_plus_button = _state.QPushButton(_state.source_part_transform_control_text['nudge_y_plus'])
    _state.part_nudge_z_minus_button = _state.QPushButton(_state.source_part_transform_control_text['nudge_z_minus'])
    _state.part_nudge_z_plus_button = _state.QPushButton(_state.source_part_transform_control_text['nudge_z_plus'])
    _state.center_part_button = _state.QPushButton(_state.source_part_transform_control_text['center_part'])
    _state.center_part_button.setToolTip(_state.source_part_transform_control_text['center_part_tooltip'])
    _state.part_nudge_row = _state.QHBoxLayout()
    _state.part_nudge_row.setContentsMargins(0, 0, 0, 0)
    _state.part_nudge_row.setSpacing(3)
    _state.part_nudge_row.addWidget(_state.part_nudge_step_spin)
    for _state.nudge_button in (_state.part_nudge_x_minus_button, _state.part_nudge_x_plus_button, _state.part_nudge_y_minus_button, _state.part_nudge_y_plus_button, _state.part_nudge_z_minus_button, _state.part_nudge_z_plus_button):
        _state.nudge_button.setMinimumWidth(0)
        _state.nudge_button.setToolTip(_state.source_part_transform_control_text['nudge_tooltip'])
        _state.part_nudge_row.addWidget(_state.nudge_button)
    _state.part_nudge_row.addWidget(_state.center_part_button)
    _state.part_layout.addLayout(_state.part_nudge_row, 8, 0, 1, 4)
    _state.part_layout.addWidget(_state.QLabel(_state.source_part_transform_control_text['rotate_label']), 9, 0)
    _state.part_layout.addWidget(_state._part_spin_with_slider(_state.part_rotate_x_spin, scale=10.0, tooltip=_state.source_part_transform_control_text['rotate_x_tooltip']), 9, 1)
    _state.part_layout.addWidget(_state._part_spin_with_slider(_state.part_rotate_y_spin, scale=10.0, tooltip=_state.source_part_transform_control_text['rotate_y_tooltip']), 9, 2)
    _state.part_layout.addWidget(_state._part_spin_with_slider(_state.part_rotate_z_spin, scale=10.0, tooltip=_state.source_part_transform_control_text['rotate_z_tooltip']), 9, 3)
    _state.axis_scale_label = _state.QLabel(_state.source_part_transform_control_text['axis_scale_label'])
    _state.axis_scale_label.setToolTip(_state.source_part_transform_control_text['axis_scale_tooltip'])
    _state.part_layout.addWidget(_state.axis_scale_label, 10, 0)
    _state.part_layout.addWidget(_state._part_spin_with_slider(_state.part_scale_x_spin, scale=1000.0, slider_minimum=0.1, slider_maximum=3.0, tooltip=_state.source_part_transform_control_text['scale_x_tooltip']), 10, 1)
    _state.part_layout.addWidget(_state._part_spin_with_slider(_state.part_scale_y_spin, scale=1000.0, slider_minimum=0.1, slider_maximum=3.0, tooltip=_state.source_part_transform_control_text['scale_y_tooltip']), 10, 2)
    _state.part_layout.addWidget(_state._part_spin_with_slider(_state.part_scale_z_spin, scale=1000.0, slider_minimum=0.1, slider_maximum=3.0, tooltip=_state.source_part_transform_control_text['scale_z_tooltip']), 10, 3)
    _state.uniform_scale_label = _state.QLabel(_state.source_part_transform_control_text['uniform_scale_label'])
    _state.uniform_scale_label.setToolTip(_state.source_part_transform_control_text['uniform_scale_tooltip'])
    _state.part_layout.addWidget(_state.uniform_scale_label, 11, 0)
    _state.part_layout.addWidget(_state._part_spin_with_slider(_state.part_uniform_spin, scale=1000.0, slider_minimum=0.1, slider_maximum=3.0, tooltip=_state.source_part_transform_control_text['uniform_scale_slider_tooltip']), 11, 1)
    _state.reset_part_button = _state.QPushButton(_state.source_part_transform_control_text['reset_part'])
    _state.remove_part_button = _state.QPushButton(_state.source_part_transform_control_text['remove_part'])
    _state.fit_part_button = _state.QPushButton(_state.source_part_transform_control_text['fit_part'])
    _state.undo_geometry_button = _state.QPushButton(_state.source_part_transform_control_text['undo_geometry'])
    _state.reset_geometry_button = _state.QPushButton(_state.source_part_transform_control_text['reset_geometry'])
    _state.remove_part_button.setToolTip(_state.source_part_transform_control_text['remove_part_tooltip'])
    _state.reset_part_button.setToolTip(_state.source_part_transform_control_text['reset_part_tooltip'])
    _state.fit_part_button.setToolTip(_state.source_part_transform_control_text['fit_part_tooltip'])
    _state.undo_geometry_button.setToolTip(_state.source_part_transform_control_text['undo_geometry_tooltip'])
    _state.reset_geometry_button.setToolTip(_state.source_part_transform_control_text['reset_geometry_tooltip'])
    _state.undo_geometry_button.setEnabled(False)
    _state.reset_geometry_button.setEnabled(False)
    _state.part_button_row = _state.QHBoxLayout()
    _state.part_button_row.addWidget(_state.remove_part_button)
    _state.part_button_row.addWidget(_state.reset_part_button)
    _state.part_button_row.addWidget(_state.fit_part_button)
    _state.part_button_row.addWidget(_state.undo_geometry_button)
    _state.part_button_row.addWidget(_state.reset_geometry_button)
    _state.part_button_row.addStretch(1)
    _state.part_layout.addLayout(_state.part_button_row, 12, 0, 1, 4)
    _state.part_material_brightness_spin = _state._make_double_spin_helper(0.0, -100.0, 100.0, 0, 1.0, '%')

def _source_parts_outliner_step_020(_state):
    _state.part_material_contrast_spin = _state._make_double_spin_helper(0.0, -100.0, 100.0, 0, 1.0, '%')
    _state.part_material_saturation_spin = _state._make_double_spin_helper(0.0, -100.0, 100.0, 0, 1.0, '%')
    _state.part_material_gamma_spin = _state._make_double_spin_helper(1.0, 0.25, 4.0, 2, 0.01)
    _state.part_material_tint_r_spin = _state._make_double_spin_helper(255.0, 0.0, 255.0, 0, 1.0)
    _state.part_material_tint_g_spin = _state._make_double_spin_helper(255.0, 0.0, 255.0, 0, 1.0)
    _state.part_material_tint_b_spin = _state._make_double_spin_helper(255.0, 0.0, 255.0, 0, 1.0)
    _state.part_material_controls = (_state.part_material_brightness_spin, _state.part_material_contrast_spin, _state.part_material_saturation_spin, _state.part_material_gamma_spin, _state.part_material_tint_r_spin, _state.part_material_tint_g_spin, _state.part_material_tint_b_spin)
    for _state.prefix, _state.spin in (('R ', _state.part_material_tint_r_spin), ('G ', _state.part_material_tint_g_spin), ('B ', _state.part_material_tint_b_spin)):
        _state.spin.setPrefix(_state.prefix)
    for _state.spin in _state.part_material_controls:
        _state.spin.setMinimumWidth(0)
        _state.spin.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Fixed)
    _state.part_material_tooltip = _state.source_part_inspector_control_text['material_adjustment_tooltip']
    for _state.spin in _state.part_material_controls:
        _state.spin.setToolTip(_state.part_material_tooltip)
    _state.part_material_label = _state.QLabel(_state.source_part_inspector_control_text['material_label'])
    _state.part_material_brightness_widget = _state._part_spin_with_slider(_state.part_material_brightness_spin, scale=1.0, slider_minimum=-100.0, slider_maximum=100.0, tooltip=_state.part_material_tooltip)
    _state.part_material_contrast_widget = _state._part_spin_with_slider(_state.part_material_contrast_spin, scale=1.0, slider_minimum=-100.0, slider_maximum=100.0, tooltip=_state.part_material_tooltip)
    _state.part_material_saturation_widget = _state._part_spin_with_slider(_state.part_material_saturation_spin, scale=1.0, slider_minimum=-100.0, slider_maximum=100.0, tooltip=_state.part_material_tooltip)
    _state.part_material_gamma_label = _state.QLabel(_state.source_part_inspector_control_text['material_gamma_label'])
    _state.part_material_gamma_widget = _state._part_spin_with_slider(_state.part_material_gamma_spin, scale=100.0, slider_minimum=0.25, slider_maximum=4.0, tooltip=_state.part_material_tooltip)
    _state.part_material_tint_label = _state.QLabel(_state.source_part_inspector_control_text['material_tint_label'])
    _state.part_layout.addWidget(_state.part_material_label, 13, 0)
    _state.part_layout.addWidget(_state.part_material_brightness_widget, 13, 1)
    _state.part_layout.addWidget(_state.part_material_contrast_widget, 13, 2)
    _state.part_layout.addWidget(_state.part_material_saturation_widget, 13, 3)
    _state.part_layout.addWidget(_state.part_material_gamma_label, 14, 0)
    _state.part_layout.addWidget(_state.part_material_gamma_widget, 14, 1)
    _state.part_layout.addWidget(_state.part_material_tint_label, 15, 0)
    _state.part_layout.addWidget(_state.part_material_tint_r_spin, 15, 1)
    _state.part_layout.addWidget(_state.part_material_tint_g_spin, 15, 2)
    _state.part_layout.addWidget(_state.part_material_tint_b_spin, 15, 3)
    _state.part_material_tuning_widgets = (_state.part_material_label, _state.part_material_brightness_widget, _state.part_material_contrast_widget, _state.part_material_saturation_widget, _state.part_material_gamma_label, _state.part_material_gamma_widget, _state.part_material_tint_label, _state.part_material_tint_r_spin, _state.part_material_tint_g_spin, _state.part_material_tint_b_spin)

def _source_parts_outliner_step_021(_state):

    def _refresh_part_material_tuning_visibility() -> None:
        visible = not bool(_state.modify_original_clone_mode) or _state._modify_original_texture_tuning_enabled()
        for widget in _state.part_material_tuning_widgets:
            widget.setVisible(bool(visible))
    _state._refresh_part_material_tuning_visibility = _refresh_part_material_tuning_visibility

def _source_parts_outliner_step_022(_state):
    _state._refresh_part_material_tuning_visibility()
    _state.part_inspector_loading = _state._part_inspector_loading_initial_state_helper()
    _state.alignment_source_part_glow_callbacks = _state.create_alignment_source_part_glow_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._selected_part_glow_rgb_from_controls = _state.alignment_source_part_glow_callbacks._selected_part_glow_rgb_from_controls
    _state._sync_part_glow_color_button = _state.alignment_source_part_glow_callbacks._sync_part_glow_color_button
    _state._refresh_part_glow_color_controls_enabled = _state.alignment_source_part_glow_callbacks._refresh_part_glow_color_controls_enabled
    _state._load_part_glow_color_controls = _state.alignment_source_part_glow_callbacks._load_part_glow_color_controls
    _state.alignment_source_role_flush_callbacks = _state.create_alignment_source_role_flush_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._apply_current_glow_color_to_role_overrides = _state.alignment_source_role_flush_callbacks._apply_current_glow_color_to_role_overrides
    _state._flush_source_role_overrides_for_export = _state.alignment_source_role_flush_callbacks._flush_source_role_overrides_for_export
    _state._refresh_ui_texture_sets_after_source_part_material_override = _state.alignment_source_role_flush_callbacks._refresh_ui_texture_sets_after_source_part_material_override
    _state._part_mapped_target_indices = _state.alignment_source_role_flush_callbacks._part_mapped_target_indices
    _state.alignment_selected_part_adjustment_callbacks = _state.create_alignment_selected_part_adjustment_callbacks({**_state.context, **_state._factory_globals, **vars(_state), '_queue_part_transform_preview_update': lambda *args, **kwargs: _state._queue_part_transform_preview_update(*args, **kwargs)})
    _state._update_selected_part_adjustment = _state.alignment_selected_part_adjustment_callbacks._update_selected_part_adjustment
    _state.alignment_selected_part_control_callbacks = _state.create_alignment_selected_part_control_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._update_selected_part_material_adjustment = _state.alignment_selected_part_control_callbacks._update_selected_part_material_adjustment
    _state._refresh_selected_part_copied_texture_controls = _state.alignment_selected_part_control_callbacks._refresh_selected_part_copied_texture_controls
    _state._use_copied_original_texture_for_selected_source = _state.alignment_selected_part_control_callbacks._use_copied_original_texture_for_selected_source
    _state._use_route_texture_for_selected_copied_source = _state.alignment_selected_part_control_callbacks._use_route_texture_for_selected_copied_source
    _state._remove_copied_texture_from_selected_source = _state.alignment_selected_part_control_callbacks._remove_copied_texture_from_selected_source
    _state._load_selected_part_controls = _state.alignment_selected_part_control_callbacks._load_selected_part_controls
    _state._selected_part_source_changed = _state.alignment_selected_part_control_callbacks._selected_part_source_changed
    _state._set_selected_source_role = _state.alignment_selected_part_control_callbacks._set_selected_source_role
    _state._set_selected_source_glow_color = _state.alignment_selected_part_control_callbacks._set_selected_source_glow_color
    _state._selected_part_target_index = _state.alignment_selected_part_control_callbacks._selected_part_target_index
    _state._select_part_target_row = _state.alignment_selected_part_control_callbacks._select_part_target_row
    _state._map_selected_part_to_combo_target = _state.alignment_selected_part_control_callbacks._map_selected_part_to_combo_target
    _state._remove_selected_part_from_combo_target = _state.alignment_selected_part_control_callbacks._remove_selected_part_from_combo_target
    _state._reset_selected_part = _state.alignment_selected_part_control_callbacks._reset_selected_part
    _state._remove_selected_part_from_output = _state.alignment_selected_part_control_callbacks._remove_selected_part_from_output
    _state.alignment_selected_part_glow_picker_callbacks = _state.create_alignment_selected_part_glow_picker_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._pick_selected_source_glow_color = _state.alignment_selected_part_glow_picker_callbacks._pick_selected_source_glow_color
    _state._reference_vertices_for_appended_part = lambda: _state._reference_vertices_for_appended_part_helper(_state.original_mesh_for_mapping, target_index=_state._selected_target_index(), original_index=int(_state.selected_original_part.get('index', -1)))
    _state.alignment_source_part_geometry_action_callbacks = _state.create_alignment_source_part_geometry_action_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._normalize_appended_part_to_work_area = _state.alignment_source_part_geometry_action_callbacks._normalize_appended_part_to_work_area
    _state._fit_selected_part_size = _state.alignment_source_part_geometry_action_callbacks._fit_selected_part_size
    _state._nudge_selected_part = _state.alignment_source_part_geometry_action_callbacks._nudge_selected_part
    _state._nudge_selected_part_axis = _state.alignment_source_part_geometry_action_callbacks._nudge_selected_part_axis
    _state._center_selected_part_on_target = _state.alignment_source_part_geometry_action_callbacks._center_selected_part_on_target
    _state._add_dialog_supplemental_file = _state.alignment_source_part_geometry_action_callbacks._add_dialog_supplemental_file
    _state.alignment_source_part_assignment_callbacks = _state.create_alignment_source_part_assignment_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._prompt_assign_appended_mesh_parts = _state.alignment_source_part_assignment_callbacks._prompt_assign_appended_mesh_parts
    _state._maybe_flatten_scene_import_parts = _state.alignment_source_part_assignment_callbacks._maybe_flatten_scene_import_parts
    _state._maybe_reduce_high_density_scene_import = _state.alignment_source_part_assignment_callbacks._maybe_reduce_high_density_scene_import
    _state._rebuild_source_part_widgets = _state.alignment_source_part_assignment_callbacks._rebuild_source_part_widgets
    _state._source_mapping_target_indices = _state.alignment_source_part_assignment_callbacks._source_mapping_target_indices
    _state._source_mirror_plane_x = lambda source_vertices: _state._source_mirror_plane_x_helper(_state.original_mesh_for_mapping, source_vertices)
    _state._copy_source_part_with_adjustment = lambda source, adjustment, **kwargs: _state._copy_source_part_with_adjustment_helper(source, adjustment, rotate_vector=_state._rotate_xyz, normalize_vector=_state._normalize, **kwargs)
    _state._mirror_submesh_x = lambda source, plane_x: _state._mirror_submesh_x_helper(source, plane_x, normalize_vector=_state._normalize)
    _state.alignment_source_part_mutation_callbacks = _state.create_alignment_source_part_mutation_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    for _state.part_spin in _state.part_controls:
        _state.part_spin.valueChanged.connect(_state._update_selected_part_adjustment)
        _state.part_spin.editingFinished.connect(lambda spin=part_spin: (_state._commit_spinbox_text(spin), _state._update_selected_part_adjustment()))
    for _state.part_material_spin in _state.part_material_controls:
        _state.part_material_spin.valueChanged.connect(_state._update_selected_part_material_adjustment)
        _state.part_material_spin.editingFinished.connect(lambda spin=part_material_spin: (_state._commit_spinbox_text(spin), _state._update_selected_part_material_adjustment()))
    _state.part_source_combo.currentIndexChanged.connect(_state._selected_part_source_changed)
    _state.part_enabled_checkbox.toggled.connect(_state._update_selected_part_adjustment)
    _state.part_role_combo.currentIndexChanged.connect(_state._set_selected_source_role)
    _state.part_target_combo.currentIndexChanged.connect(_state._select_part_target_row)
    _state.part_replace_target_button.clicked.connect(lambda _checked=False: _state._map_selected_part_to_combo_target(replace=True))
    _state.part_add_target_button.clicked.connect(lambda _checked=False: _state._map_selected_part_to_combo_target(replace=False))
    _state.part_remove_target_button.clicked.connect(_state._remove_selected_part_from_combo_target)
    _state.part_use_copied_texture_button.clicked.connect(_state._use_copied_original_texture_for_selected_source)
    _state.part_use_route_texture_button.clicked.connect(_state._use_route_texture_for_selected_copied_source)
    _state.part_remove_copied_texture_button.clicked.connect(_state._remove_copied_texture_from_selected_source)
    _state.remove_part_button.clicked.connect(_state._remove_selected_part_from_output)
    _state.reset_part_button.clicked.connect(_state._reset_selected_part)
    _state.fit_part_button.clicked.connect(_state._fit_selected_part_size)
    _state.undo_geometry_button.clicked.connect(_state._undo_geometry_change)
    _state.reset_geometry_button.clicked.connect(_state._reset_geometry_changes)
    _state.part_nudge_x_minus_button.clicked.connect(lambda _checked=False: _state._nudge_selected_part_axis('x', -1.0))
    _state.part_nudge_x_plus_button.clicked.connect(lambda _checked=False: _state._nudge_selected_part_axis('x', 1.0))
    _state.part_nudge_y_minus_button.clicked.connect(lambda _checked=False: _state._nudge_selected_part_axis('y', -1.0))
    _state.part_nudge_y_plus_button.clicked.connect(lambda _checked=False: _state._nudge_selected_part_axis('y', 1.0))
    _state.part_nudge_z_minus_button.clicked.connect(lambda _checked=False: _state._nudge_selected_part_axis('z', -1.0))
    _state.part_nudge_z_plus_button.clicked.connect(lambda _checked=False: _state._nudge_selected_part_axis('z', 1.0))
    _state.center_part_button.clicked.connect(_state._center_selected_part_on_target)
    _state.QShortcut(_state.QKeySequence('Ctrl+Left'), _state.dialog).activated.connect(lambda: _state._nudge_selected_part_axis('x', -1.0))
    _state.QShortcut(_state.QKeySequence('Ctrl+Right'), _state.dialog).activated.connect(lambda: _state._nudge_selected_part_axis('x', 1.0))
    _state.QShortcut(_state.QKeySequence('Ctrl+Down'), _state.dialog).activated.connect(lambda: _state._nudge_selected_part_axis('y', -1.0))
    _state.QShortcut(_state.QKeySequence('Ctrl+Up'), _state.dialog).activated.connect(lambda: _state._nudge_selected_part_axis('y', 1.0))
    _state.QShortcut(_state.QKeySequence('Ctrl+PageDown'), _state.dialog).activated.connect(lambda: _state._nudge_selected_part_axis('z', -1.0))
    _state.QShortcut(_state.QKeySequence('Ctrl+PageUp'), _state.dialog).activated.connect(lambda: _state._nudge_selected_part_axis('z', 1.0))
    _state.append_mesh_part_button.clicked.connect(_state._append_mesh_part_to_geometry)
    _state.duplicate_part_button.clicked.connect(lambda _checked=False: _state._duplicate_selected_part(mirrored=False))
    _state.mirror_duplicate_part_button.clicked.connect(lambda _checked=False: _state._duplicate_selected_part(mirrored=True))
    _state.alignment_source_tree_selection_callbacks = _state.create_alignment_source_tree_selection_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._refresh_source_tree_selection_state = _state.alignment_source_tree_selection_callbacks._refresh_source_tree_selection_state
    _state._source_selection_changed = _state.alignment_source_tree_selection_callbacks._source_selection_changed
    _state._ensure_source_tree_item_available = _state.alignment_source_tree_selection_callbacks._ensure_source_tree_item_available
    _state._select_source_part_from_viewport = _state.alignment_source_tree_selection_callbacks._select_source_part_from_viewport
    _state._d3d11_source_part_context_requested = _state.alignment_source_tree_selection_callbacks._d3d11_source_part_context_requested
    _state._d3d11_source_part_hovered = _state.alignment_source_tree_selection_callbacks._d3d11_source_part_hovered
    _state._d3d11_source_part_selected = _state.alignment_source_tree_selection_callbacks._d3d11_source_part_selected
    _state._original_selection_changed = _state.alignment_source_tree_selection_callbacks._original_selection_changed
    _state._target_selection_changed = _state.alignment_source_tree_selection_callbacks._target_selection_changed
    _state._parts_outliner_selection_changed = _state.alignment_source_tree_selection_callbacks._parts_outliner_selection_changed
    _state._clear_part_selections_when_leaving_geometry = _state.alignment_source_tree_selection_callbacks._clear_part_selections_when_leaving_geometry

def _source_parts_outliner_step_023(_state):
    if _state.alignment_d3d11_preview_host is not None:
        _state.alignment_d3d11_preview_host.source_part_hovered.connect(_state._d3d11_source_part_hovered)
        _state.alignment_d3d11_preview_host.source_part_selected.connect(_state._d3d11_source_part_selected)
        if hasattr(_state.alignment_d3d11_preview_host, 'source_part_context_requested'):
            _state.alignment_d3d11_preview_host.source_part_context_requested.connect(_state._d3d11_source_part_context_requested)

def _source_parts_outliner_step_024(_state):
    _state._factory_result_values.update({'_add_dialog_supplemental_file': vars(_state).get('_add_dialog_supplemental_file'), '_add_source_tree_item': vars(_state).get('_add_source_tree_item'), '_alignment_part_clipboard_can_paste': vars(_state).get('_alignment_part_clipboard_can_paste'), '_append_original_part_payload_as_source': vars(_state).get('_append_original_part_payload_as_source'), '_apply_current_glow_color_to_role_overrides': vars(_state).get('_apply_current_glow_color_to_role_overrides'), '_apply_source_role_selection': vars(_state).get('_apply_source_role_selection'), '_clear_part_selections_when_leaving_geometry': vars(_state).get('_clear_part_selections_when_leaving_geometry'), '_clear_source_parts_preview_rebuild_pending': vars(_state).get('_clear_source_parts_preview_rebuild_pending'), '_clear_transform_source_indices': vars(_state).get('_clear_transform_source_indices'), '_clear_tree_current_item': vars(_state).get('_clear_tree_current_item'), '_copied_original_dds_badge': vars(_state).get('_copied_original_dds_badge'), '_copied_original_texture_tooltip': vars(_state).get('_copied_original_texture_tooltip'), '_copy_original_part_payload': vars(_state).get('_copy_original_part_payload'), '_copy_source_part_with_adjustment': vars(_state).get('_copy_source_part_with_adjustment'), '_d3d11_source_part_context_requested': vars(_state).get('_d3d11_source_part_context_requested'), '_d3d11_source_part_hovered': vars(_state).get('_d3d11_source_part_hovered'), '_d3d11_source_part_selected': vars(_state).get('_d3d11_source_part_selected'), '_finish_source_tree_population': vars(_state).get('_finish_source_tree_population'), '_flush_source_role_overrides_for_export': vars(_state).get('_flush_source_role_overrides_for_export'), '_load_part_glow_color_controls': vars(_state).get('_load_part_glow_color_controls'), '_load_selected_part_controls': vars(_state).get('_load_selected_part_controls'), '_mapping_vertex_limit_issues': vars(_state).get('_mapping_vertex_limit_issues'), '_maybe_flatten_scene_import_parts': vars(_state).get('_maybe_flatten_scene_import_parts'), '_maybe_reduce_high_density_scene_import': vars(_state).get('_maybe_reduce_high_density_scene_import'), '_mirror_submesh_x': vars(_state).get('_mirror_submesh_x'), '_normalize_appended_part_to_work_area': vars(_state).get('_normalize_appended_part_to_work_area'), '_original_index_from_tree_item': vars(_state).get('_original_index_from_tree_item'), '_original_part_texture_intent_rows': vars(_state).get('_original_part_texture_intent_rows'), '_original_selection_changed': vars(_state).get('_original_selection_changed'), '_original_target_label': vars(_state).get('_original_target_label'), '_parse_mapping_edit': vars(_state).get('_parse_mapping_edit'), '_part_mapped_target_indices': vars(_state).get('_part_mapped_target_indices'), '_parts_outliner_selection_changed': vars(_state).get('_parts_outliner_selection_changed'), '_parts_outliner_set_source_selection': vars(_state).get('_parts_outliner_set_source_selection'), '_paste_alignment_part_clipboard_as_replacement_source': vars(_state).get('_paste_alignment_part_clipboard_as_replacement_source'), '_physics_status_tooltip': vars(_state).get('_physics_status_tooltip'), '_pick_selected_source_glow_color': vars(_state).get('_pick_selected_source_glow_color'), '_prompt_assign_appended_mesh_parts': vars(_state).get('_prompt_assign_appended_mesh_parts'), '_rebuild_source_part_widgets': vars(_state).get('_rebuild_source_part_widgets'), '_reference_vertices_for_appended_part': vars(_state).get('_reference_vertices_for_appended_part'), '_refresh_copied_original_texture_ui': vars(_state).get('_refresh_copied_original_texture_ui'), '_refresh_original_reference_preview': vars(_state).get('_refresh_original_reference_preview'), '_refresh_part_glow_color_controls_enabled': vars(_state).get('_refresh_part_glow_color_controls_enabled'), '_refresh_parts_outliner': vars(_state).get('_refresh_parts_outliner'), '_refresh_source_tree_selection_state': vars(_state).get('_refresh_source_tree_selection_state')})

def _source_parts_outliner_step_025(_state):
    _state._factory_result_values.update({'_refresh_ui_texture_sets_after_source_part_material_override': vars(_state).get('_refresh_ui_texture_sets_after_source_part_material_override'), '_remap_selected_source_index': vars(_state).get('_remap_selected_source_index'), '_remap_source_index_collection': vars(_state).get('_remap_source_index_collection'), '_remap_source_index_dict': vars(_state).get('_remap_source_index_dict'), '_select_source_part_from_viewport': vars(_state).get('_select_source_part_from_viewport'), '_selected_original_index_from_tree': vars(_state).get('_selected_original_index_from_tree'), '_selected_part_glow_rgb_from_controls': vars(_state).get('_selected_part_glow_rgb_from_controls'), '_selected_source_index': vars(_state).get('_selected_source_index'), '_selected_source_indices_from_tree': vars(_state).get('_selected_source_indices_from_tree'), '_selected_target_index': vars(_state).get('_selected_target_index'), '_set_mapping_indices': vars(_state).get('_set_mapping_indices'), '_set_selected_source_glow_color': vars(_state).get('_set_selected_source_glow_color'), '_set_source_parts_apply_pending': vars(_state).get('_set_source_parts_apply_pending'), '_set_source_parts_preview_rebuild_pending': vars(_state).get('_set_source_parts_preview_rebuild_pending'), '_set_transform_source_indices': vars(_state).get('_set_transform_source_indices'), '_source_index_from_tree_item': vars(_state).get('_source_index_from_tree_item'), '_source_mapping_target_indices': vars(_state).get('_source_mapping_target_indices'), '_source_material_group_label': vars(_state).get('_source_material_group_label'), '_source_mirror_plane_x': vars(_state).get('_source_mirror_plane_x'), '_source_physics_status_text': vars(_state).get('_source_physics_status_text'), '_source_selection_changed': vars(_state).get('_source_selection_changed'), '_sync_part_slider_from_spin': vars(_state).get('_sync_part_slider_from_spin'), '_sync_target_mapping_tree_item': vars(_state).get('_sync_target_mapping_tree_item'), '_target_physics_status_text': vars(_state).get('_target_physics_status_text'), '_target_selection_changed': vars(_state).get('_target_selection_changed'), '_target_texture_status_details': vars(_state).get('_target_texture_status_details'), '_target_texture_status_text': vars(_state).get('_target_texture_status_text'), '_texture_set_for_source_index': vars(_state).get('_texture_set_for_source_index'), '_update_mapping_status': vars(_state).get('_update_mapping_status'), '_update_selected_part_adjustment': vars(_state).get('_update_selected_part_adjustment'), 'alignment_original_texture_intent_callbacks': vars(_state).get('alignment_original_texture_intent_callbacks'), 'apply_best_guesses_button': vars(_state).get('apply_best_guesses_button'), 'apply_source_parts_button': vars(_state).get('apply_source_parts_button'), 'assign_source_button': vars(_state).get('assign_source_button'), 'center_part_button': vars(_state).get('center_part_button'), 'clear_all_guesses_button': vars(_state).get('clear_all_guesses_button'), 'clear_state': vars(_state).get('clear_state'), 'clear_target_button': vars(_state).get('clear_target_button'), 'duplicate_part_button': vars(_state).get('duplicate_part_button'), 'empty_targets_filter_checkbox': vars(_state).get('empty_targets_filter_checkbox'), 'fit_part_button': vars(_state).get('fit_part_button'), 'group_materials_button': vars(_state).get('group_materials_button'), 'index': vars(_state).get('index'), 'index_map': vars(_state).get('index_map'), 'initial_mapping_text_by_target': vars(_state).get('initial_mapping_text_by_target')})

def _source_parts_outliner_step_026(_state):
    _state._factory_result_values.update({'label_text': vars(_state).get('label_text'), 'low_confidence_filter_checkbox': vars(_state).get('low_confidence_filter_checkbox'), 'mapping_progress_label': vars(_state).get('mapping_progress_label'), 'mapping_status_label': vars(_state).get('mapping_status_label'), 'mapping_table_action_control_text': vars(_state).get('mapping_table_action_control_text'), 'mapping_table_build_requested': vars(_state).get('mapping_table_build_requested'), 'mapping_table_build_state': vars(_state).get('mapping_table_build_state'), 'mapping_table_build_timer': vars(_state).get('mapping_table_build_timer'), 'mapping_targets': vars(_state).get('mapping_targets'), 'mapping_tree': vars(_state).get('mapping_tree'), 'mappings_by_target': vars(_state).get('mappings_by_target'), 'merge_source_button': vars(_state).get('merge_source_button'), 'mirror_duplicate_part_button': vars(_state).get('mirror_duplicate_part_button'), 'mirrored': vars(_state).get('mirrored'), 'original_button_panel': vars(_state).get('original_button_panel'), 'original_part_clipboard_action_text': vars(_state).get('original_part_clipboard_action_text'), 'original_parts_label': vars(_state).get('original_parts_label'), 'original_tree': vars(_state).get('original_tree'), 'part_add_target_button': vars(_state).get('part_add_target_button'), 'part_controls': vars(_state).get('part_controls'), 'part_copied_texture_status_label': vars(_state).get('part_copied_texture_status_label'), 'part_enabled_checkbox': vars(_state).get('part_enabled_checkbox'), 'part_inspector': vars(_state).get('part_inspector'), 'part_inspector_loading': vars(_state).get('part_inspector_loading'), 'part_name_label': vars(_state).get('part_name_label'), 'part_nudge_step_spin': vars(_state).get('part_nudge_step_spin'), 'part_material_brightness_spin': vars(_state).get('part_material_brightness_spin'), 'part_material_contrast_spin': vars(_state).get('part_material_contrast_spin'), 'part_material_controls': vars(_state).get('part_material_controls'), 'part_material_gamma_spin': vars(_state).get('part_material_gamma_spin'), 'part_material_saturation_spin': vars(_state).get('part_material_saturation_spin'), 'part_material_tint_b_spin': vars(_state).get('part_material_tint_b_spin'), 'part_material_tint_g_spin': vars(_state).get('part_material_tint_g_spin'), 'part_material_tint_r_spin': vars(_state).get('part_material_tint_r_spin'), 'part_nudge_x_minus_button': vars(_state).get('part_nudge_x_minus_button'), 'part_nudge_x_plus_button': vars(_state).get('part_nudge_x_plus_button'), 'part_nudge_y_minus_button': vars(_state).get('part_nudge_y_minus_button'), 'part_nudge_y_plus_button': vars(_state).get('part_nudge_y_plus_button'), 'part_nudge_z_minus_button': vars(_state).get('part_nudge_z_minus_button'), 'part_nudge_z_plus_button': vars(_state).get('part_nudge_z_plus_button'), 'part_offset_x_spin': vars(_state).get('part_offset_x_spin'), 'part_offset_y_spin': vars(_state).get('part_offset_y_spin'), 'part_offset_z_spin': vars(_state).get('part_offset_z_spin'), 'part_remove_copied_texture_button': vars(_state).get('part_remove_copied_texture_button'), 'part_remove_target_button': vars(_state).get('part_remove_target_button')})

def _source_parts_outliner_step_027(_state):
    _state._factory_result_values.update({'part_replace_target_button': vars(_state).get('part_replace_target_button'), 'part_role_combo': vars(_state).get('part_role_combo'), 'part_rotate_x_spin': vars(_state).get('part_rotate_x_spin'), 'part_rotate_y_spin': vars(_state).get('part_rotate_y_spin'), 'part_rotate_z_spin': vars(_state).get('part_rotate_z_spin'), 'part_scale_x_spin': vars(_state).get('part_scale_x_spin'), 'part_scale_y_spin': vars(_state).get('part_scale_y_spin'), 'part_scale_z_spin': vars(_state).get('part_scale_z_spin'), 'part_source_combo': vars(_state).get('part_source_combo'), 'part_target_combo': vars(_state).get('part_target_combo'), 'part_target_label': vars(_state).get('part_target_label'), 'part_transform_sliders': vars(_state).get('part_transform_sliders'), 'part_uniform_spin': vars(_state).get('part_uniform_spin'), 'part_use_copied_texture_button': vars(_state).get('part_use_copied_texture_button'), 'part_use_route_texture_button': vars(_state).get('part_use_route_texture_button'), 'parts_outliner_cache_state': vars(_state).get('parts_outliner_cache_state'), 'parts_outliner_item_update_guard': vars(_state).get('parts_outliner_item_update_guard'), 'parts_outliner_source_items': vars(_state).get('parts_outliner_source_items'), 'parts_outliner_target_items': vars(_state).get('parts_outliner_target_items'), 'parts_outliner_tree': vars(_state).get('parts_outliner_tree'), 'preview_target_button': vars(_state).get('preview_target_button'), 'previous_blocked': vars(_state).get('previous_blocked'), 'remove_part_button': vars(_state).get('remove_part_button'), 'remove_source_button': vars(_state).get('remove_source_button'), 'reset_geometry_button': vars(_state).get('reset_geometry_button'), 'reset_part_button': vars(_state).get('reset_part_button'), 'role_value': vars(_state).get('role_value'), 'scale': vars(_state).get('scale'), 'slider_maximum': vars(_state).get('slider_maximum'), 'slider_minimum': vars(_state).get('slider_minimum'), 'source_part_inspector_control_text': vars(_state).get('source_part_inspector_control_text'), 'source_parts_group': vars(_state).get('source_parts_group'), 'source_parts_pending_label': vars(_state).get('source_parts_pending_label'), 'source_tree': vars(_state).get('source_tree'), 'source_tree_context_selection_state': vars(_state).get('source_tree_context_selection_state'), 'source_tree_item_update_guard': vars(_state).get('source_tree_item_update_guard'), 'source_tree_layout_state': vars(_state).get('source_tree_layout_state'), 'source_tree_population_state': vars(_state).get('source_tree_population_state'), 'source_tree_population_timer': vars(_state).get('source_tree_population_timer'), 'source_tree_progress_label': vars(_state).get('source_tree_progress_label'), 'target': vars(_state).get('target'), 'target_slots_label': vars(_state).get('target_slots_label'), 'tooltip': vars(_state).get('tooltip'), 'tree': vars(_state).get('tree'), 'undo_geometry_button': vars(_state).get('undo_geometry_button')})

def _source_parts_outliner_step_028(_state):
    _state._factory_result_values.update({'value': vars(_state).get('value'), 'values': vars(_state).get('values')})

STEPS = (
    _source_parts_outliner_step_018,
    _source_parts_outliner_step_019,
    _source_parts_outliner_step_020,
    _source_parts_outliner_step_021,
    _source_parts_outliner_step_022,
    _source_parts_outliner_step_023,
    _source_parts_outliner_step_024,
    _source_parts_outliner_step_025,
    _source_parts_outliner_step_026,
    _source_parts_outliner_step_027,
    _source_parts_outliner_step_028,
)

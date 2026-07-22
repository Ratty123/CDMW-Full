from __future__ import annotations

def _setup_options_transform_step_013(_state):
    _state.part_glow_color_checkbox.setEnabled(_state.source_part_glow_controls_ready)
    for _state.part_glow_spin in _state.part_glow_color_spins:
        _state.part_glow_spin.setEnabled(_state.source_part_glow_controls_ready)
    _state.part_glow_color_pick_button.setEnabled(_state.source_part_glow_controls_ready)
    _state.part_glow_strength_checkbox.setEnabled(_state.source_part_glow_controls_ready)
    _state.part_glow_strength_spin.setEnabled(False)
    _state.part_glow_color_checkbox.toggled.connect(_state._set_selected_source_glow_color_if_ready)
    for _state.part_glow_spin in _state.part_glow_color_spins:
        _state.part_glow_spin.valueChanged.connect(_state._set_selected_source_glow_color_if_ready)
    _state.part_glow_strength_checkbox.toggled.connect(_state._set_selected_source_glow_color_if_ready)
    _state.part_glow_strength_spin.valueChanged.connect(_state._set_selected_source_glow_color_if_ready)
    _state.part_glow_color_pick_button.clicked.connect(_state._pick_selected_source_glow_color_if_ready)
    if callable(_state._refresh_part_glow_color_controls_enabled):
        _state._refresh_part_glow_color_controls_enabled()
    if callable(_state._apply_current_glow_color_to_role_overrides):
        _state._apply_current_glow_color_to_role_overrides()
    _state.true_source_basic_reset_button.clicked.connect(_state._reset_material_authority_adjustments)
    _state.complete_external_swap_checkbox.toggled.connect(_state._sync_complete_external_swap_mode)
    if _state.preferred_complete_source_swap:
        _state._select_complete_swap_material_profile('material_authority_detail_mask', persist=False)
        _state.rebuild_sidecar_checkbox.setChecked(True)
        _state.prune_unmapped_original_dds_checkbox.setChecked(True)
        _state.source_color_faithful_checkbox.setChecked(True)
        _state.external_material_reset_checkbox.setChecked(True)
        _state.inject_base_color_checkbox.setChecked(True)
        _state.complete_external_swap_checkbox.setChecked(True)

def _setup_options_transform_step_014(_state):

    def _refresh_part_material_tuning_visibility() -> None:
        return None
    _state._refresh_part_material_tuning_visibility = _refresh_part_material_tuning_visibility

def _setup_options_transform_step_015(_state):
    _state.complete_swap_material_profile_combo.currentIndexChanged.connect(lambda _index: (_state._ensure_material_authority_route_active('profile_selection'), _state._save_complete_swap_material_profile(), _state._refresh_manual_material_profile_panel(), _state._refresh_global_gloss_reduction_hint(), _state._refresh_true_source_basic_controls_state(), _state._refresh_output_impact_review(), _state.material_authority_history_callbacks.refresh_preview()))
    _state.modify_original_texture_tuning_checkbox.toggled.connect(lambda checked: (_state.self.settings.setValue(_state.modify_original_texture_tuning_enabled_key, bool(checked)), _state._refresh_manual_material_profile_panel(), _state._refresh_part_material_tuning_visibility(), _state._save_complete_swap_material_profile(), _state._refresh_output_impact_review(), _state.material_authority_history_callbacks.refresh_preview()))
    _state.texture_output_size_combo.currentIndexChanged.connect(_state.material_authority_history_callbacks.refresh_preview)
    _state._refresh_sidecar_option_state()
    _state._refresh_output_impact_review()
    if _state.full_import_model_replacement:
        _state.frozen_tooltip = 'Required by Full Import Model Replacement; Material Authority tuning and Parts & Routing remain editable.'
        _state.alignment_mode_combo.setCurrentIndex(max(0, _state.alignment_mode_combo.findData('grid_flat')))
        _state.scale_to_length_checkbox.setChecked(True)
        _state.flip_direction_checkbox.setChecked(False)
        for _state.widget in (_state.rebuild_sidecar_checkbox, _state.prune_unmapped_original_dds_checkbox, _state.inject_base_color_checkbox, _state.source_color_faithful_checkbox, _state.external_material_reset_checkbox, _state.complete_external_swap_checkbox):
            _state.widget.setEnabled(False)
            _state.widget.setToolTip(_state.frozen_tooltip)
    _state._wire_material_authority_history()
    _state.material_authority_undo_shortcut = _state.QShortcut(_state.QKeySequence('Ctrl+Z'), _state.material_authority_section)
    _state.material_authority_undo_shortcut.setContext(_state.Qt.ShortcutContext.WidgetWithChildrenShortcut)
    _state.material_authority_undo_shortcut.activated.connect(_state._undo_material_authority_change)
    _state.material_authority_redo_shortcut = _state.QShortcut(_state.QKeySequence('Ctrl+Y'), _state.material_authority_section)
    _state.material_authority_redo_shortcut.setContext(_state.Qt.ShortcutContext.WidgetWithChildrenShortcut)
    _state.material_authority_redo_shortcut.activated.connect(_state._redo_material_authority_change)
    _state.alignment_custom_icon_callbacks = _state.create_alignment_custom_icon_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._alignment_custom_icon_override_spec = _state.alignment_custom_icon_callbacks._alignment_custom_icon_override_spec
    _state._refresh_alignment_custom_icon_status = _state.alignment_custom_icon_callbacks._refresh_alignment_custom_icon_status
    _state._choose_alignment_custom_icon_file = _state.alignment_custom_icon_callbacks._choose_alignment_custom_icon_file
    _state._choose_alignment_custom_icon_folder = _state.alignment_custom_icon_callbacks._choose_alignment_custom_icon_folder
    _state._choose_alignment_custom_icon_library_source = _state.alignment_custom_icon_callbacks._choose_alignment_custom_icon_library_source
    _state._capture_alignment_replacement_icon_pixmap = _state.alignment_custom_icon_callbacks._capture_alignment_replacement_icon_pixmap
    _state._generate_alignment_icon_from_preview = _state.alignment_custom_icon_callbacks._generate_alignment_icon_from_preview
    _state.custom_icon_checkbox.toggled.connect(lambda _checked=False: _state._refresh_alignment_custom_icon_status())
    _state.custom_icon_source_edit.textChanged.connect(lambda _text='': _state._refresh_alignment_custom_icon_status())
    _state.custom_icon_target_combo.currentIndexChanged.connect(lambda _index=0: _state._refresh_alignment_custom_icon_status())
    _state.custom_icon_file_button.clicked.connect(lambda _checked=False: _state._choose_alignment_custom_icon_file())
    _state.custom_icon_folder_button.clicked.connect(lambda _checked=False: _state._choose_alignment_custom_icon_folder())
    _state.custom_icon_library_button.clicked.connect(lambda _checked=False: _state._choose_alignment_custom_icon_library_source())
    _state.generate_alignment_icon_button.clicked.connect(lambda _checked=False: _state._generate_alignment_icon_from_preview())
    _state._refresh_alignment_custom_icon_status()
    _state.original_center = _state._mesh_center_for_ui(_state.original_mesh_for_mapping)
    _state.alignment_transform_control_text = _state._alignment_transform_control_text_helper()
    _state.transform_layout_specs = _state._alignment_global_transform_layout_specs_helper()
    _state.transform_group = _state.QGroupBox(_state.alignment_transform_control_text['export_group_title'])
    _state.transform_layout = _state.QGridLayout(_state.transform_group)
    _state.transform_layout.setContentsMargins(*tuple(_state.transform_layout_specs['margins']))
    _state.transform_layout.setHorizontalSpacing(int(_state.transform_layout_specs['horizontal_spacing']))
    _state.transform_layout.setVerticalSpacing(int(_state.transform_layout_specs['vertical_spacing']))
    for _state.column, _state.stretch in tuple(_state.transform_layout_specs['column_stretches']):
        _state.transform_layout.setColumnStretch(int(_state.column), int(_state.stretch))
    for _state.column, _state.width in tuple(_state.transform_layout_specs['column_minimum_widths']):
        _state.transform_layout.setColumnMinimumWidth(int(_state.column), int(_state.width))
    _state.transform_layout.addWidget(_state.QLabel(_state.alignment_transform_control_text['export_property_header']), 0, 0)
    _state.transform_layout.addWidget(_state.QLabel(_state.alignment_transform_control_text['export_original_header']), 0, 1)
    _state.transform_layout.addWidget(_state.QLabel(_state.alignment_transform_control_text['export_values_header']), 0, 2)
    _state.transform_spin_specs = _state._alignment_global_transform_spin_specs_helper()
    _state.offset_x_spin = _state._make_double_spin_helper(**_state.transform_spin_specs['offset'])
    _state.offset_y_spin = _state._make_double_spin_helper(**_state.transform_spin_specs['offset'])
    _state.offset_z_spin = _state._make_double_spin_helper(**_state.transform_spin_specs['offset'])
    _state.rotate_x_spin = _state._make_double_spin_helper(**_state.transform_spin_specs['rotation'])
    _state.rotate_y_spin = _state._make_double_spin_helper(**_state.transform_spin_specs['rotation'])
    _state.rotate_z_spin = _state._make_double_spin_helper(**_state.transform_spin_specs['rotation'])
    _state.scale_x_spin = _state._make_double_spin_helper(**_state.transform_spin_specs['scale'])
    _state.scale_y_spin = _state._make_double_spin_helper(**_state.transform_spin_specs['scale'])
    _state.scale_z_spin = _state._make_double_spin_helper(**_state.transform_spin_specs['scale'])
    for _state.transform_spin in (_state.offset_x_spin, _state.offset_y_spin, _state.offset_z_spin, _state.rotate_x_spin, _state.rotate_y_spin, _state.rotate_z_spin, _state.scale_x_spin, _state.scale_y_spin, _state.scale_z_spin):
        _state.transform_spin.setMinimumWidth(int(_state.transform_layout_specs['spin_minimum_width']))
        _state.transform_spin.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Fixed)
    _state.alignment_transform_sliders: _state.Dict[_state.QDoubleSpinBox, _state.QSlider] = {}
    _state.transform_slider_specs = _state._alignment_global_transform_slider_specs_helper()
    _state.alignment_transform_slider_callbacks = _state.create_alignment_transform_slider_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._paired_transform_slider = _state.alignment_transform_slider_callbacks._paired_transform_slider
    _state._spin_with_slider = lambda spin, *, slider_scale, tooltip, slider_minimum=None, slider_maximum=None: _state._wrap_spin_with_slider_helper(spin, _state._paired_transform_slider(spin, scale=slider_scale, tooltip=tooltip, slider_minimum=slider_minimum, slider_maximum=slider_maximum))
    _state.alignment_transform_row_callbacks = _state.create_alignment_transform_row_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._sync_alignment_transform_slider_from_spin = _state.alignment_transform_row_callbacks._sync_alignment_transform_slider_from_spin
    _state._add_transform_row = _state.alignment_transform_row_callbacks._add_transform_row
    _state.transform_row_widgets = {'offset': (_state.offset_x_spin, _state.offset_y_spin, _state.offset_z_spin), 'rotation': (_state.rotate_x_spin, _state.rotate_y_spin, _state.rotate_z_spin), 'scale': (_state.scale_x_spin, _state.scale_y_spin, _state.scale_z_spin)}
    _state.transform_original_texts = {'original_center': _state._alignment_transform_location_original_text_helper(_state.original_center), 'rotation_original': _state.alignment_transform_control_text['rotation_original'], 'scale_original': _state.alignment_transform_control_text['scale_original']}
    for _state.row_spec in _state._alignment_global_transform_row_specs_helper():
        _state._add_transform_row(int(_state.row_spec['row_index']), _state.alignment_transform_control_text[str(_state.row_spec['label_key'])], _state.transform_original_texts[str(_state.row_spec.get('original_source') or _state.row_spec.get('original_key'))], _state.transform_row_widgets[str(_state.row_spec['widget_group'])], **_state.transform_slider_specs[str(_state.row_spec['slider_spec'])])
    _state.scale_link_checkbox = _state.QCheckBox(_state.alignment_transform_control_text['link_scale_axes'])
    _state.scale_link_checkbox.setChecked(True)
    _state.transform_layout.addWidget(_state.scale_link_checkbox, 4, 2)
    _state.reset_buttons_by_key = {str(spec['key']): _state.QPushButton(_state.alignment_transform_control_text[str(spec['text_key'])]) for spec in _state._alignment_global_transform_reset_button_specs_helper()}
    for _state.reset_button in _state.reset_buttons_by_key.values():
        _state.reset_button.setMinimumWidth(int(_state.transform_layout_specs['reset_button_minimum_width']))
    _state.reset_buttons = _state.QHBoxLayout()
    for _state.spec in _state._alignment_global_transform_reset_button_specs_helper():
        _state.reset_buttons.addWidget(_state.reset_buttons_by_key[str(_state.spec['key'])])
    _state.transform_layout.addLayout(_state.reset_buttons, 5, 0, 1, 3)
    _state.tilt_step_spin = _state._make_double_spin_helper(**_state.transform_spin_specs['tilt_step'])
    _state.tilt_step_spin.setMinimumWidth(int(_state.transform_layout_specs['tilt_step_minimum_width']))
    _state.tilt_step_spin.setToolTip(_state.alignment_transform_control_text['tilt_step_tooltip'])
    _state.tilt_button_row = _state.QHBoxLayout()
    _state.tilt_button_row.addWidget(_state.QLabel(_state.alignment_transform_control_text['tilt_step_label']))
    _state.tilt_button_row.addWidget(_state.tilt_step_spin)
    _state.tilt_buttons_by_key = {}
    for _state.spec in _state._alignment_global_transform_tilt_button_specs_helper():
        _state.tilt_button = _state.QPushButton(_state.alignment_transform_control_text[str(_state.spec['text_key'])])
        _state.tilt_button.setMinimumWidth(0)
        _state.tilt_button.setToolTip(_state.alignment_transform_control_text[str(_state.spec['tooltip_key'])])
        _state.tilt_buttons_by_key[str(_state.spec['key'])] = _state.tilt_button
        _state.tilt_button_row.addWidget(_state.tilt_button)
    _state.transform_layout.addLayout(_state.tilt_button_row, 6, 0, 1, 3)

def _setup_options_transform_step_016(_state):
    _state.transform_hint = _state.QLabel(_state.alignment_transform_control_text['hint_html'])
    _state.transform_hint.setWordWrap(True)
    _state.transform_hint.setTextFormat(_state.Qt.RichText)
    _state.transform_hint.setObjectName('HintLabel')
    _state.transform_layout.addWidget(_state.transform_hint, 7, 0, 1, 3)
    _state.transform_section = _state.CollapsibleSection(_state.alignment_transform_control_text['section_title'], expanded=True)
    _state.transform_section.body_layout.addWidget(_state.transform_group)
    _state.setup_layout.addWidget(_state.transform_section)
    _state.setup_layout.addWidget(_state.item_icon_section)
    if _state.advanced_setup_section is not None:
        _state.setup_layout.addWidget(_state.advanced_setup_section)
    if _state.modify_original_clone_mode:
        _state.setup_layout.addWidget(_state.modify_original_texture_tuning_section)
        _state.modify_original_texture_tuning_section.setVisible(True)
    if _state.placement_note is not None:
        _state.setup_layout.addWidget(_state.placement_note)
    _state.scale_syncing = _state._scale_syncing_initial_state_helper()
    _state.scale_spins = (_state.scale_x_spin, _state.scale_y_spin, _state.scale_z_spin)
    _state.alignment_transform_drag_callbacks = _state.create_alignment_transform_drag_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._sync_linked_scale = _state.alignment_transform_drag_callbacks._sync_linked_scale
    _state._commit_global_transform_spin = _state.alignment_transform_drag_callbacks._commit_global_transform_spin
    _state._global_transform_values = _state.alignment_transform_drag_callbacks._global_transform_values
    _state._part_transform_values = _state.alignment_transform_drag_callbacks._part_transform_values
    _state._capture_static_preview_baked_transform_state = _state.alignment_transform_drag_callbacks._capture_static_preview_baked_transform_state
    _state._active_alignment_transform_preview_widgets = _state.alignment_transform_drag_callbacks._active_alignment_transform_preview_widgets
    _state._set_global_fast_preview_edit_scope = _state.alignment_transform_drag_callbacks._set_global_fast_preview_edit_scope
    _state._set_part_fast_preview_edit_scope = _state.alignment_transform_drag_callbacks._set_part_fast_preview_edit_scope
    _state._queue_alignment_d3d11_fast_transform = _state.alignment_transform_drag_callbacks._queue_alignment_d3d11_fast_transform
    _state._send_alignment_d3d11_fast_transform_state = _state.alignment_transform_drag_callbacks._send_alignment_d3d11_fast_transform_state
    _state._replay_alignment_d3d11_fast_transform = _state.alignment_transform_drag_callbacks._replay_alignment_d3d11_fast_transform
    _state._apply_global_transform_fast_preview = _state.alignment_transform_drag_callbacks._apply_global_transform_fast_preview
    _state._apply_part_transform_fast_preview = _state.alignment_transform_drag_callbacks._apply_part_transform_fast_preview
    _state._queue_global_transform_preview_update = _state.alignment_transform_drag_callbacks._queue_global_transform_preview_update
    _state._queue_part_transform_preview_update = _state.alignment_transform_drag_callbacks._queue_part_transform_preview_update
    _state._apply_alignment_transform_reset_state = _state.alignment_transform_drag_callbacks._apply_alignment_transform_reset_state
    _state._reset_location_values = _state.alignment_transform_drag_callbacks._reset_location_values
    _state._reset_rotation_values = _state.alignment_transform_drag_callbacks._reset_rotation_values
    _state._reset_scale_values = _state.alignment_transform_drag_callbacks._reset_scale_values
    _state._reset_placement_values = _state.alignment_transform_drag_callbacks._reset_placement_values
    _state._nudge_rotation = _state.alignment_transform_drag_callbacks._nudge_rotation
    _state._current_global_rotation_origin_for_preview = _state.alignment_transform_drag_callbacks._current_global_rotation_origin_for_preview
    _state._alignment_part_source_indices_for_commit = _state.alignment_transform_drag_callbacks._alignment_part_source_indices_for_commit
    _state._apply_alignment_part_translation_delta = _state.alignment_transform_drag_callbacks._apply_alignment_part_translation_delta
    _state._apply_alignment_part_rotation_delta = _state.alignment_transform_drag_callbacks._apply_alignment_part_rotation_delta
    _state._sync_alignment_preview_rotation_context = _state.alignment_transform_drag_callbacks._sync_alignment_preview_rotation_context
    _state._prepare_alignment_preview_drag = _state.alignment_transform_drag_callbacks._prepare_alignment_preview_drag
    _state._prepare_alignment_d3d11_preview_drag = _state.alignment_transform_drag_callbacks._prepare_alignment_d3d11_preview_drag
    _state._commit_alignment_d3d11_drag_generation = _state.alignment_transform_drag_callbacks._commit_alignment_d3d11_drag_generation
    _state._set_global_transform_values_for_d3d11_drag = _state.alignment_transform_drag_callbacks._set_global_transform_values_for_d3d11_drag
    _state._queue_global_transform_values_for_d3d11_drag = _state.alignment_transform_drag_callbacks._queue_global_transform_values_for_d3d11_drag
    _state._set_selected_part_controls_for_d3d11_drag = _state.alignment_transform_drag_callbacks._set_selected_part_controls_for_d3d11_drag
    _state._queue_selected_part_controls_for_d3d11_drag = _state.alignment_transform_drag_callbacks._queue_selected_part_controls_for_d3d11_drag
    _state._flush_alignment_d3d11_drag_ui = _state.alignment_transform_drag_callbacks._flush_alignment_d3d11_drag_ui
    _state._alignment_d3d11_base_global_transform = _state.alignment_transform_drag_callbacks._alignment_d3d11_base_global_transform
    _state._alignment_d3d11_base_part_transform = _state.alignment_transform_drag_callbacks._alignment_d3d11_base_part_transform
    _state._alignment_d3d11_translation_to_transform_units = _state.alignment_transform_drag_callbacks._alignment_d3d11_translation_to_transform_units
    _state._apply_alignment_d3d11_translation_total = _state.alignment_transform_drag_callbacks._apply_alignment_d3d11_translation_total
    _state._apply_alignment_d3d11_rotation_total = _state.alignment_transform_drag_callbacks._apply_alignment_d3d11_rotation_total
    _state._finish_alignment_d3d11_translation = _state.alignment_transform_drag_callbacks._finish_alignment_d3d11_translation
    _state._finish_alignment_d3d11_rotation = _state.alignment_transform_drag_callbacks._finish_alignment_d3d11_rotation
    _state._commit_alignment_preview_translation = _state.alignment_transform_drag_callbacks._commit_alignment_preview_translation
    _state._commit_alignment_preview_rotation = _state.alignment_transform_drag_callbacks._commit_alignment_preview_rotation
    def _mesh_editor_apply_dotnet_placement_state(payload: object) -> bool:
        if not isinstance(payload, _state.Mapping):
            return False
        rows = (
            ('translation', (_state.offset_x_spin, _state.offset_y_spin, _state.offset_z_spin)),
            ('rotation_degrees', (_state.rotate_x_spin, _state.rotate_y_spin, _state.rotate_z_spin)),
            ('scale', _state.scale_spins),
        )
        changed = False
        for key, widgets in rows:
            values = payload.get(key)
            if not isinstance(values, _state.Sequence) or isinstance(values, (str, bytes, bytearray)):
                continue
            for widget, value in zip(widgets, tuple(values)[:3]):
                try:
                    parsed = float(value)
                except (TypeError, ValueError, OverflowError):
                    continue
                widget.blockSignals(True)
                try:
                    widget.setValue(parsed)
                finally:
                    widget.blockSignals(False)
                changed = True
        if changed:
            _state._queue_global_transform_preview_update()
        return changed
    if _state.dialog is not None:
        setattr(_state.dialog, '_mesh_editor_apply_dotnet_placement_state', _mesh_editor_apply_dotnet_placement_state)
    _state.reset_buttons_by_key['location'].clicked.connect(_state._reset_location_values)
    _state.reset_buttons_by_key['rotation'].clicked.connect(_state._reset_rotation_values)
    _state.reset_buttons_by_key['scale'].clicked.connect(_state._reset_scale_values)
    _state.reset_buttons_by_key['placement'].clicked.connect(_state._reset_placement_values)
    _state.tilt_spins_by_axis = {'x': _state.rotate_x_spin, 'y': _state.rotate_y_spin, 'z': _state.rotate_z_spin}
    for _state.spec in _state._alignment_global_transform_tilt_button_specs_helper():
        _state.tilt_buttons_by_key[str(_state.spec['key'])].clicked.connect(lambda _checked=False, spec=_state.spec: _state._nudge_rotation(_state.tilt_spins_by_axis[str(spec['axis'])], float(spec['direction'])))
    for _state.preview_widget in (_state.static_dialog_preview, _state.overlay_dialog_preview, _state.replacement_only_preview):
        _state.preview_widget.set_alignment_translation_sensitivity(0.85)
        _state.preview_widget.set_alignment_rotation_degrees_per_pixel(0.18)
        _state.preview_widget.alignment_drag_started.connect(lambda preview_widget=_state.preview_widget: _state._prepare_alignment_preview_drag(preview_widget))
        _state.preview_widget.alignment_drag_finished.connect(_state._commit_alignment_preview_translation)
        _state.preview_widget.alignment_rotation_finished.connect(_state._commit_alignment_preview_rotation)
        _state.preview_widget.mesh_edit_stroke_started.connect(lambda payload: _state._mesh_edit_begin_stroke(payload))
        _state.preview_widget.mesh_edit_stroke_previewed.connect(lambda payload: _state._mesh_edit_apply_preview_payload(payload))
        _state.preview_widget.mesh_edit_stroke_finished.connect(lambda payload: _state._mesh_edit_finish_stroke(payload))
        _state.preview_widget.mesh_edit_stroke_cancelled.connect(lambda payload: _state._mesh_edit_cancel_stroke(payload))
        _state.preview_widget.mesh_edit_selection_changed.connect(lambda payload: _state._mesh_edit_selection_changed(payload))
    _state.alignment_d3d11_preview_host.mesh_edit_stroke_started.connect(lambda payload: _state._mesh_edit_begin_stroke(payload))
    _state.alignment_d3d11_preview_host.mesh_edit_stroke_previewed.connect(lambda payload: _state._mesh_edit_apply_preview_payload(payload))
    _state.alignment_d3d11_preview_host.mesh_edit_stroke_finished.connect(lambda payload: _state._mesh_edit_finish_stroke(payload))
    _state.alignment_d3d11_preview_host.mesh_edit_stroke_cancelled.connect(lambda payload: _state._mesh_edit_cancel_stroke(payload))
    _state.alignment_d3d11_preview_host.mesh_edit_selection_changed.connect(lambda payload: _state._mesh_edit_selection_changed(payload))
    _state.alignment_d3d11_preview_host.alignment_drag_started.connect(_state._prepare_alignment_d3d11_preview_drag)
    _state.alignment_d3d11_preview_host.alignment_drag_changed.connect(_state._apply_alignment_d3d11_translation_total)
    _state.alignment_d3d11_preview_host.alignment_drag_finished.connect(_state._finish_alignment_d3d11_translation)
    _state.alignment_d3d11_preview_host.alignment_rotation_changed.connect(_state._apply_alignment_d3d11_rotation_total)
    _state.alignment_d3d11_preview_host.alignment_rotation_finished.connect(_state._finish_alignment_d3d11_rotation)
    _state.alignment_d3d11_preview_host.source_part_selected.connect(_state._d3d11_source_part_selected)
    _state.preview_controls_ready['ready'] = True

def _setup_options_transform_step_017(_state):
    _state._factory_result_values.update({'_alignment_custom_icon_override_spec': vars(_state).get('_alignment_custom_icon_override_spec'), '_basic_controls_profile_enabled': vars(_state).get('_basic_controls_profile_enabled'), '_capture_static_preview_baked_transform_state': vars(_state).get('_capture_static_preview_baked_transform_state'), '_coerce_manual_profile_values': vars(_state).get('_coerce_manual_profile_values'), '_complete_external_swap_enabled': vars(_state).get('_complete_external_swap_enabled'), '_complete_external_swap_mappings': vars(_state).get('_complete_external_swap_mappings'), '_current_complete_swap_material_profile_token': vars(_state).get('_current_complete_swap_material_profile_token'), '_current_manual_material_profile_values': vars(_state).get('_current_manual_material_profile_values'), '_current_material_authority_preview_profile': vars(_state).get('_current_material_authority_preview_profile'), '_ensure_material_authority_route_active': vars(_state).get('_ensure_material_authority_route_active'), '_material_authority_preview_inactive_reason': vars(_state).get('_material_authority_preview_inactive_reason'), '_material_authority_preview_signature': vars(_state).get('_material_authority_preview_signature'), '_modify_original_texture_tuning_enabled': vars(_state).get('_modify_original_texture_tuning_enabled'), '_queue_material_authority_adjustment_preview_refresh': vars(_state).get('_queue_material_authority_adjustment_preview_refresh'), '_queue_part_transform_preview_update': vars(_state).get('_queue_part_transform_preview_update'), '_refresh_manual_material_profile_panel': vars(_state).get('_refresh_manual_material_profile_panel'), '_refresh_manual_profile_control_effects': vars(_state).get('_refresh_manual_profile_control_effects'), '_refresh_sidecar_option_state': vars(_state).get('_refresh_sidecar_option_state'), '_replay_alignment_d3d11_fast_transform': vars(_state).get('_replay_alignment_d3d11_fast_transform'), '_save_complete_swap_material_profile': vars(_state).get('_save_complete_swap_material_profile'), '_save_manual_profile_presets': vars(_state).get('_save_manual_profile_presets'), '_select_complete_swap_material_profile': vars(_state).get('_select_complete_swap_material_profile'), '_set_manual_profile_dirty': vars(_state).get('_set_manual_profile_dirty'), '_spin_with_slider': vars(_state).get('_spin_with_slider'), '_sync_alignment_transform_slider_from_spin': vars(_state).get('_sync_alignment_transform_slider_from_spin'), 'accent_glow_slider': vars(_state).get('accent_glow_slider'), 'accent_glow_spin': vars(_state).get('accent_glow_spin'), 'alignment_mode_combo': vars(_state).get('alignment_mode_combo'), 'alignment_transform_control_text': vars(_state).get('alignment_transform_control_text'), 'alignment_transform_sliders': vars(_state).get('alignment_transform_sliders'), 'auto_brightness_slider': vars(_state).get('auto_brightness_slider'), 'auto_brightness_spin': vars(_state).get('auto_brightness_spin'), 'channel_value': vars(_state).get('channel_value'), 'column': vars(_state).get('column'), 'complete_external_swap_checkbox': vars(_state).get('complete_external_swap_checkbox'), 'complete_swap_material_profile_combo': vars(_state).get('complete_swap_material_profile_combo'), 'complete_swap_profile_store_path': vars(_state).get('complete_swap_profile_store_path'), 'custom_icon_checkbox': vars(_state).get('custom_icon_checkbox'), 'custom_icon_file_button': vars(_state).get('custom_icon_file_button'), 'custom_icon_folder_button': vars(_state).get('custom_icon_folder_button'), 'custom_icon_library_button': vars(_state).get('custom_icon_library_button'), 'custom_icon_source_edit': vars(_state).get('custom_icon_source_edit'), 'custom_icon_status': vars(_state).get('custom_icon_status'), 'custom_icon_target_combo': vars(_state).get('custom_icon_target_combo'), 'custom_icon_target_entries': vars(_state).get('custom_icon_target_entries'), 'custom_icon_target_graph': vars(_state).get('custom_icon_target_graph')})

def _setup_options_transform_step_018(_state):
    _state._factory_result_values.update({'edge_relief_slider': vars(_state).get('edge_relief_slider'), 'edge_relief_source_combo': vars(_state).get('edge_relief_source_combo'), 'edge_relief_spin': vars(_state).get('edge_relief_spin'), 'external_material_reset_checkbox': vars(_state).get('external_material_reset_checkbox'), 'flip_direction_checkbox': vars(_state).get('flip_direction_checkbox'), 'global_gloss_reduction_hint': vars(_state).get('global_gloss_reduction_hint'), 'global_gloss_reduction_slider': vars(_state).get('global_gloss_reduction_slider'), 'global_gloss_reduction_spin': vars(_state).get('global_gloss_reduction_spin'), 'inject_base_color_checkbox': vars(_state).get('inject_base_color_checkbox'), 'manual_profile_apply_button': vars(_state).get('manual_profile_apply_button'), 'manual_profile_change_status': vars(_state).get('manual_profile_change_status'), 'manual_profile_control_text': vars(_state).get('manual_profile_control_text'), 'manual_profile_control_tooltips': vars(_state).get('manual_profile_control_tooltips'), 'manual_profile_controls': vars(_state).get('manual_profile_controls'), 'manual_profile_default_values': vars(_state).get('manual_profile_default_values'), 'manual_profile_dirty': vars(_state).get('manual_profile_dirty'), 'manual_profile_effect_widgets': vars(_state).get('manual_profile_effect_widgets'), 'manual_profile_group': vars(_state).get('manual_profile_group'), 'manual_profile_layout': vars(_state).get('manual_profile_layout'), 'manual_profile_preset_combo': vars(_state).get('manual_profile_preset_combo'), 'manual_profile_preset_details_edit': vars(_state).get('manual_profile_preset_details_edit'), 'manual_profile_preset_name_edit': vars(_state).get('manual_profile_preset_name_edit'), 'manual_profile_preset_recommended_edit': vars(_state).get('manual_profile_preset_recommended_edit'), 'manual_profile_presets': vars(_state).get('manual_profile_presets'), 'manual_profile_presets_key': vars(_state).get('manual_profile_presets_key'), 'manual_profile_ready': vars(_state).get('manual_profile_ready'), 'manual_profile_saved_values': vars(_state).get('manual_profile_saved_values'), 'manual_profile_settings_key': vars(_state).get('manual_profile_settings_key'), 'material_authority_section': vars(_state).get('material_authority_section'), 'modify_original_texture_tuning_checkbox': vars(_state).get('modify_original_texture_tuning_checkbox'), 'modify_original_texture_tuning_enabled_key': vars(_state).get('modify_original_texture_tuning_enabled_key'), 'modify_original_texture_tuning_section': vars(_state).get('modify_original_texture_tuning_section'), 'object_name': vars(_state).get('object_name'), 'offset_x_spin': vars(_state).get('offset_x_spin'), 'offset_y_spin': vars(_state).get('offset_y_spin'), 'offset_z_spin': vars(_state).get('offset_z_spin'), 'part_glow_color_checkbox': vars(_state).get('part_glow_color_checkbox'), 'part_glow_color_pick_button': vars(_state).get('part_glow_color_pick_button'), 'part_glow_color_spins': vars(_state).get('part_glow_color_spins'), 'profile_name': vars(_state).get('profile_name'), 'prune_unmapped_original_dds_checkbox': vars(_state).get('prune_unmapped_original_dds_checkbox'), 'rebuild_sidecar_checkbox': vars(_state).get('rebuild_sidecar_checkbox'), 'rotate_x_spin': vars(_state).get('rotate_x_spin'), 'rotate_y_spin': vars(_state).get('rotate_y_spin'), 'rotate_z_spin': vars(_state).get('rotate_z_spin')})
    _state._factory_result_values.update({
        'part_glow_strength_checkbox': vars(_state).get('part_glow_strength_checkbox'),
        'part_glow_strength_spin': vars(_state).get('part_glow_strength_spin'),
        'manual_profile_expert_group': vars(_state).get('manual_profile_expert_group'),
        'manual_profile_expert_warning': vars(_state).get('manual_profile_expert_warning'),
    })

def _setup_options_transform_step_019(_state):
    _state._factory_result_values.update({'save_generated_icon_to_library_checkbox': vars(_state).get('save_generated_icon_to_library_checkbox'), 'scale_link_checkbox': vars(_state).get('scale_link_checkbox'), 'scale_spins': vars(_state).get('scale_spins'), 'scale_syncing': vars(_state).get('scale_syncing'), 'scale_to_length_checkbox': vars(_state).get('scale_to_length_checkbox'), 'scale_x_spin': vars(_state).get('scale_x_spin'), 'scale_y_spin': vars(_state).get('scale_y_spin'), 'scale_z_spin': vars(_state).get('scale_z_spin'), 'setup_texture_flip_u_checkbox': vars(_state).get('setup_texture_flip_u_checkbox'), 'setup_texture_flip_v_checkbox': vars(_state).get('setup_texture_flip_v_checkbox'), 'setup_texture_rotate_combo': vars(_state).get('setup_texture_rotate_combo'), 'slider_maximum': vars(_state).get('slider_maximum'), 'slider_minimum': vars(_state).get('slider_minimum'), 'slider_scale': vars(_state).get('slider_scale'), 'source_brightness_slider': vars(_state).get('source_brightness_slider'), 'source_brightness_spin': vars(_state).get('source_brightness_spin'), 'source_color_faithful_checkbox': vars(_state).get('source_color_faithful_checkbox'), 'texture_output_size_combo': vars(_state).get('texture_output_size_combo'), 'tilt_step_spin': vars(_state).get('tilt_step_spin'), 'tone_contrast_slider': vars(_state).get('tone_contrast_slider'), 'tone_contrast_spin': vars(_state).get('tone_contrast_spin'), 'tooltip': vars(_state).get('tooltip'), 'transform_layout': vars(_state).get('transform_layout'), 'transform_layout_specs': vars(_state).get('transform_layout_specs'), 'transform_slider_specs': vars(_state).get('transform_slider_specs'), 'true_source_basic_group': vars(_state).get('true_source_basic_group'), 'true_source_basic_hint': vars(_state).get('true_source_basic_hint'), 'true_source_basic_reset_button': vars(_state).get('true_source_basic_reset_button'), 'unsafe_material_preflight_checkbox': vars(_state).get('unsafe_material_preflight_checkbox'), 'width': vars(_state).get('width')})

STEPS = (
    _setup_options_transform_step_013,
    _setup_options_transform_step_014,
    _setup_options_transform_step_015,
    _setup_options_transform_step_016,
    _setup_options_transform_step_017,
    _setup_options_transform_step_018,
    _setup_options_transform_step_019,
)

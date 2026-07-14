from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dotnet_presentation import (
    builder_presentation_state,
    effective_builder_comparison_mode,
)

def _mesh_geometry_preview_step_001(_state):
    _state.CollapsibleSection = _state.context.get('CollapsibleSection')
    _state.Dict = _state.context.get('Dict')
    _state.original_mesh_for_mapping = _state.context.get('original_mesh_for_mapping')
    _state.preview_mode_combo = _state.context.get('preview_mode_combo')
    _state.MESH_EDIT_DELETE_MODE_OPTIONS = _state.context.get('MESH_EDIT_DELETE_MODE_OPTIONS')
    _state.MESH_EDIT_FALLOFF_OPTIONS = _state.context.get('MESH_EDIT_FALLOFF_OPTIONS')
    _state.MESH_EDIT_SCOPE_OPTIONS = _state.context.get('MESH_EDIT_SCOPE_OPTIONS')
    _state.MESH_EDIT_SELECTION_DEPTH_OPTIONS = _state.context.get('MESH_EDIT_SELECTION_DEPTH_OPTIONS')
    _state.MESH_EDIT_SELECTION_MODE_OPTIONS = _state.context.get('MESH_EDIT_SELECTION_MODE_OPTIONS')
    _state.MESH_EDIT_TOOL_BUTTON_OPTIONS = _state.context.get('MESH_EDIT_TOOL_BUTTON_OPTIONS')
    _state.MESH_EDIT_TOOL_OPTIONS = _state.context.get('MESH_EDIT_TOOL_OPTIONS')
    _state.NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS = _state.context.get('NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS')
    _state.QCheckBox = _state.context.get('QCheckBox')
    _state.QComboBox = _state.context.get('QComboBox')
    _state.QFrame = _state.context.get('QFrame')
    _state.QGroupBox = _state.context.get('QGroupBox')
    _state.QHBoxLayout = _state.context.get('QHBoxLayout')
    _state.QLabel = _state.context.get('QLabel')
    _state.QMenu = _state.context.get('QMenu')
    _state.QPushButton = _state.context.get('QPushButton')
    _state.QSizePolicy = _state.context.get('QSizePolicy')
    _state.QSpinBox = _state.context.get('QSpinBox')
    _state.QToolButton = _state.context.get('QToolButton')
    _state.QVBoxLayout = _state.context.get('QVBoxLayout')
    _state.QWidget = _state.context.get('QWidget')
    _state.Qt = _state.context.get('Qt')
    _state.Tuple = _state.context.get('Tuple')
    _state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')
    _state._alignment_startup_step = _state.context.get('_alignment_startup_step')
    _state._apply_native_preview_core_material_manifest_helper = _state.context.get('_apply_native_preview_core_material_manifest_helper')
    _state._basic_controls_profile_enabled = _state.context.get('_basic_controls_profile_enabled')
    _state._clear_part_selections_when_leaving_geometry = _state.context.get('_clear_part_selections_when_leaving_geometry')
    _state._current_complete_swap_material_profile_token = _state.context.get('_current_complete_swap_material_profile_token')
    _state._current_material_authority_preview_profile = _state.context.get('_current_material_authority_preview_profile')
    _state._delete_selected_source_parts = _state.context.get('_delete_selected_source_parts')
    _state._enabled_renderable_source_indices = _state.context.get('_enabled_renderable_source_indices')
    _state._geometry_mapping_summary_html_helper = _state.context.get('_geometry_mapping_summary_html_helper')
    _state._handle_original_reference_texture_preview_error = _state.context.get('_handle_original_reference_texture_preview_error')
    _state._is_marker_source = _state.context.get('_is_marker_source')
    _state._load_native_preview_core_material_manifest_for_alignment_helper = _state.context.get('_load_native_preview_core_material_manifest_for_alignment_helper')
    _state._load_selected_part_controls = _state.context.get('_load_selected_part_controls')
    _state._make_double_spin_helper = _state.context.get('_make_double_spin_helper')
    _state._material_authority_preview_inactive_reason = _state.context.get('_material_authority_preview_inactive_reason')
    _state._material_authority_preview_signature = _state.context.get('_material_authority_preview_signature')
    _state._mesh_edit_action_control_text_helper = _state.context.get('_mesh_edit_action_control_text_helper')
    _state._mesh_edit_dialog_title_helper = _state.context.get('_mesh_edit_dialog_title_helper')
    _state.preview_mesh_edit_checkbox = _state.context.get('preview_mesh_edit_checkbox')
    _state.preview_gizmo_checkbox = _state.context.get('preview_gizmo_checkbox')
    _state.preview_part_pick_checkbox = _state.context.get('preview_part_pick_checkbox')
    _state._current_alignment_preview_render_settings = _state.context.get('_current_alignment_preview_render_settings')
    _state._morph_slider_add_target_action_text_helper = _state.context.get('_morph_slider_add_target_action_text_helper')
    _state._morph_slider_bake_action_text_helper = _state.context.get('_morph_slider_bake_action_text_helper')
    _state._morph_slider_bake_action_tooltip_helper = _state.context.get('_morph_slider_bake_action_tooltip_helper')
    _state._morph_slider_create_action_text_helper = _state.context.get('_morph_slider_create_action_text_helper')
    _state._morph_slider_create_action_tooltip_helper = _state.context.get('_morph_slider_create_action_tooltip_helper')
    _state._morph_slider_import_action_text_helper = _state.context.get('_morph_slider_import_action_text_helper')
    _state._morph_slider_manage_action_text_helper = _state.context.get('_morph_slider_manage_action_text_helper')
    _state._morph_slider_manage_action_tooltip_helper = _state.context.get('_morph_slider_manage_action_tooltip_helper')
    _state._morph_slider_reload_action_text_helper = _state.context.get('_morph_slider_reload_action_text_helper')
    _state._morph_slider_reset_action_text_helper = _state.context.get('_morph_slider_reset_action_text_helper')
    _state._morph_slider_status_text_helper = _state.context.get('_morph_slider_status_text_helper')
    _state._morph_slider_title_text_helper = _state.context.get('_morph_slider_title_text_helper')
    _state._native_manifest_input_from_descriptor = _state.context.get('_native_manifest_input_from_descriptor')
    _state._original_reference_texture_preview_clear_native_package_path_helper = _state.context.get('_original_reference_texture_preview_clear_native_package_path_helper')
    _state._original_reference_texture_preview_set_native_package_path_helper = _state.context.get('_original_reference_texture_preview_set_native_package_path_helper')
    _state._original_selection_changed = _state.context.get('_original_selection_changed')
    _state._parse_mapping_edit = _state.context.get('_parse_mapping_edit')
    _state._populate_combo_options_helper = _state.context.get('_populate_combo_options_helper')
    _state._queue_static_preview_refresh = _state.context.get('_queue_static_preview_refresh')
    _state._record_runtime_event = _state.context.get('_record_runtime_event')
    _state._refresh_mesh_editor_diagnostics = _state.context.get('_refresh_mesh_editor_diagnostics')
    _state._refresh_source_assignment_columns = _state.context.get('_refresh_source_assignment_columns')
    _state._refresh_source_tree_selection_state = _state.context.get('_refresh_source_tree_selection_state')
    _state._source_part_properties_control_text_helper = _state.context.get('_source_part_properties_control_text_helper')
    _state._source_selection_changed = _state.context.get('_source_selection_changed')
    _state._target_selection_changed = _state.context.get('_target_selection_changed')
    _state._update_mapping_status = _state.context.get('_update_mapping_status')
    _state._update_selection_context = _state.context.get('_update_selection_context')
    _state.alignment_startup_text = _state.context.get('alignment_startup_text')
    _state.any = _state._context_builtin(_state.context, 'any')
    _state.args = _state.context.get('args')
    _state.bool = _state._context_builtin(_state.context, 'bool')
    _state.classic_mesh_edit_toolbar = _state.context.get('classic_mesh_edit_toolbar')
    _state.classic_mesh_edit_toolbar_layout = _state.context.get('classic_mesh_edit_toolbar_layout')
    _state.control_tabs = _state.context.get('control_tabs')
    _state.create_alignment_mesh_edit_callbacks = _state.context.get('create_alignment_mesh_edit_callbacks')
    _state.create_alignment_original_texture_worker_callbacks = _state.context.get('create_alignment_original_texture_worker_callbacks')
    _state.create_alignment_preview_model_callbacks = _state.context.get('create_alignment_preview_model_callbacks')
    _state.create_alignment_static_preview_refresh_callbacks = _state.context.get('create_alignment_static_preview_refresh_callbacks')
    _state.diagnostics_tab = _state.context.get('diagnostics_tab')
    _state.dialog = _state.context.get('dialog')
    _state.dialog_title = _state.context.get('dialog_title')
    _state.entry = _state.context.get('entry')
    _state.getattr = _state._context_builtin(_state.context, 'getattr')
    _state.globals = _state._context_builtin(_state.context, 'globals')
    _state.index = _state.context.get('index')
    _state.kwargs = _state.context.get('kwargs')
    _state.label_text = _state.context.get('label_text')
    _state.len = _state._context_builtin(_state.context, 'len')
    _state.locals = _state._context_builtin(_state.context, 'locals')
    _state.mapping_edits = _state.context.get('mapping_edits')
    _state.mapping_tree = _state.context.get('mapping_tree')
    _state.hovered_source_part = _state.context.get('hovered_source_part') or {}
    _state.selected_source_highlight_indices = _state.context.get('selected_source_highlight_indices') or set()
    _state.selected_target_source_highlight_indices = _state.context.get('selected_target_source_highlight_indices') or set()
    _state.selected_original_highlight_indices = _state.context.get('selected_original_highlight_indices') or set()
    _state.selected_target_original_highlight_indices = _state.context.get('selected_target_original_highlight_indices') or set()
    _state.source_part_adjustments = _state.context.get('source_part_adjustments') or {}
    _state.texture_uv_global_transform_state = _state.context.get('texture_uv_global_transform_state') or {}
    _state.max = _state._context_builtin(_state.context, 'max')
    _state.mesh_edit_layout_page = _state.context.get('mesh_edit_layout_page')
    _state.mesh_edit_page = _state.context.get('mesh_edit_page')
    _state.object_name = _state.context.get('object_name')

def _mesh_geometry_preview_step_002(_state):
    _state.original_reference_texture_preview_state = _state.context.get('original_reference_texture_preview_state')
    _state.original_tree = _state.context.get('original_tree')
    _state.package_path = _state.context.get('package_path')
    _state.package_root_text = _state.context.get('package_root_text')
    _state.preview_model = _state.context.get('preview_model')
    _state._get_preview_render_settings = _state.context.get('_get_preview_render_settings')
    _state.preview_render_settings = _state.context.get('preview_render_settings')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.row_key = _state.context.get('row_key')
    _state.run_native_preview_core_preview_job = _state.context.get('run_native_preview_core_preview_job')
    _state.selected_tool = _state.context.get('selected_tool')
    _state.self = _state.context.get('self')
    _state.source_tree = _state.context.get('source_tree')
    _state.static_preview_refresh_timer = _state.context.get('static_preview_refresh_timer')
    _state.static_preview_settle_timer = _state.context.get('static_preview_settle_timer')
    _state.str = _state._context_builtin(_state.context, 'str')
    _state.sum = _state._context_builtin(_state.context, 'sum')
    _state.target_preview_model = _state.context.get('target_preview_model')
    _state.widget = _state.context.get('widget')

def _mesh_geometry_preview_step_003(_state):

    def _current_preview_render_settings() -> object:
        if callable(_state._get_preview_render_settings):
            return _state._get_preview_render_settings()
        return _state.preview_render_settings
    _state._current_preview_render_settings = _current_preview_render_settings

def _mesh_geometry_preview_step_004(_state):
    _state.mesh_edit_supported = _state.bool(_state.replacement_mesh_for_mapping is not None and _state.any((_state.bool(_state.getattr(source, 'vertices', None)) and _state.bool(_state.getattr(source, 'faces', None)) and (not _state._is_marker_source(source)) for source in _state.getattr(_state.replacement_mesh_for_mapping, 'submeshes', ()) or ())))
    _state.mesh_edit_group = _state.QFrame(_state.mesh_edit_page)
    _state.mesh_edit_group.setObjectName('MeshEditVerticalToolbox')
    _state.mesh_edit_group.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Maximum)
    _state.mesh_edit_layout = _state.QVBoxLayout(_state.mesh_edit_group)
    _state.mesh_edit_layout.setContentsMargins(8, 4, 8, 4)
    _state.mesh_edit_layout.setSpacing(4)
    _state.mesh_edit_action_control_text = _state._mesh_edit_action_control_text_helper()
    _state.mesh_edit_title_label = _state.QLabel(_state._mesh_edit_dialog_title_helper())
    _state.mesh_edit_title_label.setObjectName('SectionLabel')
    _state.mesh_edit_enabled_checkbox = _state.preview_mesh_edit_checkbox if _state.preview_mesh_edit_checkbox is not None else _state.QCheckBox(_state.mesh_edit_action_control_text['edit_mode'])
    _state.mesh_edit_enabled_checkbox.setText(_state.mesh_edit_action_control_text['edit_mode'])
    _state.mesh_edit_enabled_checkbox.setObjectName('MeshEditModeCheckbox')
    _state.mesh_edit_enabled_checkbox.setToolTip(_state.mesh_edit_action_control_text['edit_mode_tooltip'])
    _state.mesh_edit_scope_combo = _state.QComboBox()
    _state._populate_combo_options_helper(_state.mesh_edit_scope_combo, _state.MESH_EDIT_SCOPE_OPTIONS)
    _state.mesh_edit_scope_combo.setToolTip(_state.mesh_edit_action_control_text['scope_combo_tooltip'])
    _state.mesh_edit_part_combo = _state.QComboBox()
    _state.mesh_edit_part_combo.setToolTip(_state.mesh_edit_action_control_text['part_combo_tooltip'])
    _state.mesh_edit_tool_combo = _state.QComboBox()
    _state._populate_combo_options_helper(_state.mesh_edit_tool_combo, _state.MESH_EDIT_TOOL_OPTIONS)
    _state.mesh_edit_tool_combo.setCurrentIndex(_state.max(0, _state.mesh_edit_tool_combo.findData('vertex')))
    _state.mesh_edit_tool_combo.setVisible(False)
    _state.mesh_edit_tool_palette = _state.QFrame(_state.mesh_edit_group)
    _state.mesh_edit_tool_palette.setObjectName('MeshEditVerticalToolPalette')
    _state.mesh_edit_tool_palette_layout = _state.QVBoxLayout(_state.mesh_edit_tool_palette)
    _state.mesh_edit_tool_palette_layout.setContentsMargins(0, 0, 0, 0)
    _state.mesh_edit_tool_palette_layout.setSpacing(3)
    _state.mesh_edit_tool_buttons: _state.Dict[_state.str, _state.QToolButton] = {}
    for _state.label, _state.tool, _state.tooltip in _state.MESH_EDIT_TOOL_BUTTON_OPTIONS:
        _state.button = _state.QToolButton(_state.mesh_edit_tool_palette)
        _state.button.setText(_state.label)
        _state.button.setToolButtonStyle(_state.Qt.ToolButtonTextOnly)
        _state.button.setCheckable(True)
        _state.button.setAutoExclusive(True)
        _state.button.setChecked(_state.tool == 'vertex')
        _state.button.setMinimumHeight(24)
        _state.button.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Fixed)
        _state.button.setToolTip(_state.tooltip)
        _state.button.clicked.connect(lambda _checked=False, selected_tool=_state.tool: _state.mesh_edit_tool_combo.setCurrentIndex(_state.max(0, _state.mesh_edit_tool_combo.findData(selected_tool))))
        _state.mesh_edit_tool_buttons[_state.tool] = _state.button
        _state.mesh_edit_tool_palette_layout.addWidget(_state.button)
    _state.mesh_edit_delete_mode_combo = _state.QComboBox()
    _state._populate_combo_options_helper(_state.mesh_edit_delete_mode_combo, _state.MESH_EDIT_DELETE_MODE_OPTIONS)
    _state.mesh_edit_delete_mode_combo.setToolTip(_state.mesh_edit_action_control_text['delete_mode_tooltip'])
    _state.mesh_edit_radius_spin = _state._make_double_spin_helper(24.0, 2.0, 256.0, 0, 2.0, ' px')
    _state.mesh_edit_strength_spin = _state._make_double_spin_helper(50.0, 0.0, 100.0, 0, 5.0, '%')
    _state.mesh_edit_falloff_combo = _state.QComboBox()
    _state._populate_combo_options_helper(_state.mesh_edit_falloff_combo, _state.MESH_EDIT_FALLOFF_OPTIONS)
    _state.mesh_edit_iterations_spin = _state.QSpinBox()
    _state.mesh_edit_iterations_spin.setRange(1, 12)
    _state.mesh_edit_iterations_spin.setValue(3)
    _state.mesh_edit_iterations_spin.setToolTip(_state.mesh_edit_action_control_text['iterations_tooltip'])
    _state.mesh_edit_selection_mode_combo = _state.QComboBox()
    _state._populate_combo_options_helper(_state.mesh_edit_selection_mode_combo, _state.MESH_EDIT_SELECTION_MODE_OPTIONS)
    _state.mesh_edit_selection_mode_combo.setToolTip(_state.mesh_edit_action_control_text['selection_mode_tooltip'])
    _state.mesh_edit_selection_depth_combo = _state.QComboBox()
    _state._populate_combo_options_helper(_state.mesh_edit_selection_depth_combo, _state.MESH_EDIT_SELECTION_DEPTH_OPTIONS)
    _state.mesh_edit_selection_depth_combo.setToolTip(_state.mesh_edit_action_control_text['selection_depth_tooltip'])
    _state.mesh_edit_mirror_checkbox = _state.QCheckBox(_state.mesh_edit_action_control_text['mirror_checkbox'])
    _state.mesh_edit_show_vertices_checkbox = _state.QCheckBox(_state.mesh_edit_action_control_text['show_vertices_checkbox'])
    _state.mesh_edit_show_vertices_checkbox.setChecked(False)
    _state.mesh_edit_clear_selection_button = _state.QPushButton(_state.mesh_edit_action_control_text['clear_selection'])
    _state.mesh_edit_select_part_button = _state.QPushButton(_state.mesh_edit_action_control_text['select_part'])
    _state.mesh_edit_invert_selection_button = _state.QPushButton(_state.mesh_edit_action_control_text['invert_selection'])
    _state.mesh_edit_grow_selection_button = _state.QPushButton(_state.mesh_edit_action_control_text['grow_selection'])
    _state.mesh_edit_shrink_selection_button = _state.QPushButton(_state.mesh_edit_action_control_text['shrink_selection'])
    _state.mesh_edit_smooth_selection_button = _state.QPushButton(_state.mesh_edit_action_control_text['smooth_selection'])
    _state.mesh_edit_subdivide_selection_button = _state.QPushButton(_state.mesh_edit_action_control_text['subdivide_selection'])
    _state.mesh_edit_refine_smooth_selection_button = _state.QPushButton(_state.mesh_edit_action_control_text['refine_smooth_selection'])
    _state.mesh_edit_split_selection_button = _state.QPushButton(_state.mesh_edit_action_control_text['split_selection'])
    _state.mesh_edit_select_part_button.setToolTip(_state.mesh_edit_action_control_text['select_part_tooltip'])
    _state.mesh_edit_invert_selection_button.setToolTip(_state.mesh_edit_action_control_text['invert_selection_tooltip'])
    _state.mesh_edit_subdivide_selection_button.setToolTip(_state.mesh_edit_action_control_text['subdivide_selection_tooltip'])
    _state.mesh_edit_refine_smooth_selection_button.setToolTip(_state.mesh_edit_action_control_text['refine_smooth_selection_tooltip'])
    _state.mesh_edit_split_selection_button.setToolTip(_state.mesh_edit_action_control_text['split_selection_tooltip'])
    _state.mesh_edit_delete_faces_button = _state.QPushButton(_state.mesh_edit_action_control_text['delete_faces'])
    _state.mesh_edit_delete_faces_button.setToolTip(_state.mesh_edit_action_control_text['delete_faces_tooltip'])
    _state.mesh_edit_undo_button = _state.QPushButton(_state.mesh_edit_action_control_text['undo'])
    _state.mesh_edit_redo_button = _state.QPushButton(_state.mesh_edit_action_control_text['redo'])
    _state.mesh_edit_reset_part_button = _state.QPushButton(_state.mesh_edit_action_control_text['reset_scope'])
    _state.mesh_edit_full_reset_button = _state.QPushButton(_state.mesh_edit_action_control_text['full_reset_mesh'])
    for _state.mesh_edit_button in (_state.mesh_edit_clear_selection_button, _state.mesh_edit_select_part_button, _state.mesh_edit_invert_selection_button, _state.mesh_edit_grow_selection_button, _state.mesh_edit_shrink_selection_button, _state.mesh_edit_smooth_selection_button, _state.mesh_edit_subdivide_selection_button, _state.mesh_edit_refine_smooth_selection_button, _state.mesh_edit_split_selection_button, _state.mesh_edit_delete_faces_button, _state.mesh_edit_undo_button, _state.mesh_edit_redo_button, _state.mesh_edit_reset_part_button, _state.mesh_edit_full_reset_button):
        _state.mesh_edit_button.setMinimumWidth(0)
    _state.mesh_edit_status_label = _state.QLabel(_state.mesh_edit_action_control_text['initial_status'])
    _state.mesh_edit_status_label.setObjectName('HintLabel')
    _state.mesh_edit_status_label.setWordWrap(True)
    _state.mesh_edit_status_label.setMaximumHeight(54)
    _state.morph_slider_group = _state.QFrame(_state.mesh_edit_page)
    _state.morph_slider_group.setObjectName('MorphSliderToolbox')
    _state.morph_slider_group.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Maximum)
    _state.morph_slider_layout = _state.QVBoxLayout(_state.morph_slider_group)
    _state.morph_slider_layout.setContentsMargins(8, 5, 8, 5)
    _state.morph_slider_layout.setSpacing(4)
    _state.morph_slider_title_label = _state.QLabel(_state._morph_slider_title_text_helper())
    _state.morph_slider_title_label.setObjectName('SectionLabel')
    _state.morph_slider_status_label = _state.QLabel(_state._morph_slider_status_text_helper(supported=True, blocked=False, block_reason='', loaded=False, profile_count=0, slider_count=0))
    _state.morph_slider_status_label.setObjectName('HintLabel')
    _state.morph_slider_status_label.setWordWrap(True)
    _state.morph_slider_rows_widget = _state.QWidget(_state.morph_slider_group)

def _mesh_geometry_preview_step_005(_state):
    _state.morph_slider_rows_layout = _state.QVBoxLayout(_state.morph_slider_rows_widget)
    _state.morph_slider_rows_layout.setContentsMargins(0, 0, 0, 0)
    _state.morph_slider_rows_layout.setSpacing(3)
    _state.morph_slider_create_button = _state.QPushButton(_state._morph_slider_create_action_text_helper())
    _state.morph_slider_create_button.setToolTip(_state._morph_slider_create_action_tooltip_helper())
    _state.morph_slider_manage_button = _state.QPushButton(_state._morph_slider_manage_action_text_helper())
    _state.morph_slider_manage_button.setToolTip(_state._morph_slider_manage_action_tooltip_helper())
    _state.morph_slider_manage_menu = _state.QMenu(_state.morph_slider_manage_button)
    _state.morph_slider_import_action = _state.morph_slider_manage_menu.addAction(_state._morph_slider_import_action_text_helper())
    _state.morph_slider_add_action = _state.morph_slider_manage_menu.addAction(_state._morph_slider_add_target_action_text_helper())
    _state.morph_slider_manage_menu.addSeparator()
    _state.morph_slider_reload_action = _state.morph_slider_manage_menu.addAction(_state._morph_slider_reload_action_text_helper())
    _state.morph_slider_manage_button.setMenu(_state.morph_slider_manage_menu)
    _state.morph_slider_reset_button = _state.QPushButton(_state._morph_slider_reset_action_text_helper())
    _state.morph_slider_bake_button = _state.QPushButton(_state._morph_slider_bake_action_text_helper())
    _state.morph_slider_bake_button.setToolTip(_state._morph_slider_bake_action_tooltip_helper())
    _state.morph_slider_button_row = _state.QHBoxLayout()
    _state.morph_slider_button_row.setContentsMargins(0, 0, 0, 0)
    _state.morph_slider_button_row.setSpacing(3)
    _state.morph_slider_button_row.addWidget(_state.morph_slider_create_button)
    _state.morph_slider_button_row.addWidget(_state.morph_slider_manage_button)
    _state.morph_slider_button_row.addStretch(1)
    _state.morph_slider_reset_bake_row = _state.QHBoxLayout()
    _state.morph_slider_reset_bake_row.setContentsMargins(0, 0, 0, 0)
    _state.morph_slider_reset_bake_row.setSpacing(3)
    _state.morph_slider_reset_bake_row.addWidget(_state.morph_slider_reset_button)
    _state.morph_slider_reset_bake_row.addWidget(_state.morph_slider_bake_button)
    _state.morph_slider_reset_bake_row.addStretch(1)
    _state.morph_slider_layout.addWidget(_state.morph_slider_title_label)
    _state.morph_slider_layout.addWidget(_state.morph_slider_status_label)
    _state.morph_slider_layout.addWidget(_state.morph_slider_rows_widget)
    _state.morph_slider_layout.addLayout(_state.morph_slider_button_row)
    _state.morph_slider_layout.addLayout(_state.morph_slider_reset_bake_row)
    _state.mesh_edit_field_rows: _state.Dict[_state.str, _state.Tuple[_state.QLabel, _state.QWidget]] = {}

def _mesh_geometry_preview_step_006(_state):

    def _mesh_edit_field(row_key: str, label_text: str, widget: QWidget) -> None:
        label = _state.QLabel(label_text)
        label.setObjectName('HintLabel')
        _state.mesh_edit_layout.addWidget(label)
        _state.mesh_edit_layout.addWidget(widget)
        _state.mesh_edit_field_rows[_state.str(row_key)] = (label, widget)
    _state._mesh_edit_field = _mesh_edit_field

def _mesh_geometry_preview_step_007(_state):
    _state.mesh_edit_layout.addWidget(_state.mesh_edit_title_label)
    _state.checkbox_parent = _state.getattr(_state.mesh_edit_enabled_checkbox, 'parent', lambda: None)
    if callable(_state.checkbox_parent) and _state.checkbox_parent() is _state.mesh_edit_group:
        _state.mesh_edit_layout.addWidget(_state.mesh_edit_enabled_checkbox)
    _state._mesh_edit_field('scope', _state.mesh_edit_action_control_text['scope_label'], _state.mesh_edit_scope_combo)
    _state._mesh_edit_field('part', _state.mesh_edit_action_control_text['part_label'], _state.mesh_edit_part_combo)
    _state.mesh_edit_layout.addWidget(_state.QLabel(_state.mesh_edit_action_control_text['tool_label']))
    _state.mesh_edit_layout.addWidget(_state.mesh_edit_tool_palette)
    _state.mesh_edit_remove_mode_label = _state.QLabel(_state.mesh_edit_action_control_text['remove_mode_label'])
    _state.mesh_edit_remove_mode_label.setObjectName('HintLabel')
    _state.mesh_edit_layout.addWidget(_state.mesh_edit_remove_mode_label)
    _state.mesh_edit_layout.addWidget(_state.mesh_edit_delete_mode_combo)
    _state._mesh_edit_field('radius', _state.mesh_edit_action_control_text['radius_label'], _state.mesh_edit_radius_spin)
    _state._mesh_edit_field('strength', _state.mesh_edit_action_control_text['strength_label'], _state.mesh_edit_strength_spin)
    _state._mesh_edit_field('falloff', _state.mesh_edit_action_control_text['falloff_label'], _state.mesh_edit_falloff_combo)
    _state._mesh_edit_field('iterations', _state.mesh_edit_action_control_text['iterations_label'], _state.mesh_edit_iterations_spin)
    _state._mesh_edit_field('selection', _state.mesh_edit_action_control_text['selection_label'], _state.mesh_edit_selection_mode_combo)
    _state._mesh_edit_field('depth', _state.mesh_edit_action_control_text['depth_label'], _state.mesh_edit_selection_depth_combo)
    _state.mesh_edit_option_widget = _state.QWidget(_state.mesh_edit_group)
    _state.mesh_edit_option_row = _state.QHBoxLayout(_state.mesh_edit_option_widget)
    _state.mesh_edit_option_row.setContentsMargins(0, 0, 0, 0)
    _state.mesh_edit_option_row.setSpacing(4)
    _state.mesh_edit_option_row.addWidget(_state.mesh_edit_mirror_checkbox)
    _state.mesh_edit_option_row.addWidget(_state.mesh_edit_show_vertices_checkbox)
    _state.mesh_edit_option_row.addStretch(1)
    _state.mesh_edit_layout.addWidget(_state.mesh_edit_option_widget)
    _state.mesh_edit_selection_actions_widget = _state.QWidget(_state.mesh_edit_group)
    _state.mesh_edit_selection_button_row = _state.QHBoxLayout(_state.mesh_edit_selection_actions_widget)
    _state.mesh_edit_selection_button_row.setContentsMargins(0, 0, 0, 0)
    _state.mesh_edit_selection_button_row.setSpacing(3)
    _state.mesh_edit_selection_button_row.addWidget(_state.mesh_edit_grow_selection_button)
    _state.mesh_edit_selection_button_row.addWidget(_state.mesh_edit_shrink_selection_button)
    _state.mesh_edit_selection_button_row.addWidget(_state.mesh_edit_smooth_selection_button)
    _state.mesh_edit_layout.addWidget(_state.mesh_edit_clear_selection_button)
    _state.mesh_edit_layout.addWidget(_state.mesh_edit_select_part_button)
    _state.mesh_edit_layout.addWidget(_state.mesh_edit_invert_selection_button)
    _state.mesh_edit_layout.addWidget(_state.mesh_edit_selection_actions_widget)
    _state.mesh_edit_layout.addWidget(_state.mesh_edit_subdivide_selection_button)
    _state.mesh_edit_layout.addWidget(_state.mesh_edit_refine_smooth_selection_button)
    _state.mesh_edit_layout.addWidget(_state.mesh_edit_split_selection_button)
    _state.mesh_edit_layout.addWidget(_state.mesh_edit_delete_faces_button)
    _state.mesh_edit_button_row = _state.QHBoxLayout()
    _state.mesh_edit_button_row.setContentsMargins(0, 0, 0, 0)
    _state.mesh_edit_button_row.setSpacing(3)
    _state.mesh_edit_button_row.addWidget(_state.mesh_edit_undo_button)
    _state.mesh_edit_button_row.addWidget(_state.mesh_edit_redo_button)
    _state.classic_mesh_edit_action_bar = None
    _state.compact_mesh_edit_options_widget = None
    _state.compact_mesh_edit_status_label = None
    _state.compact_mesh_edit_clear_button = None
    _state.compact_mesh_edit_grow_button = None
    _state.compact_mesh_edit_shrink_button = None
    _state.compact_mesh_edit_feather_button = None
    _state.compact_mesh_edit_reset_scope_button = None
    _state.compact_selection_mode_combo = None
    _state.compact_selection_depth_combo = None

def _bind_embedded_mesh_editor_preview(_state):
    if _state.dialog is None:
        return

    def _mesh_editor_embedded_presentation_state():
        camera_getter = getattr(_state, '_alignment_current_camera_state', None)
        camera = camera_getter() if callable(camera_getter) else {}
        # This section is created before the alignment-settings callbacks. Read
        # through the live preview-settings accessor instead of retaining the
        # initial settings object captured in this factory state.
        settings_getter = getattr(_state, '_current_preview_render_settings', None)
        settings = settings_getter() if callable(settings_getter) else _state.preview_render_settings
        try:
            hovered_source_index = int(_state.hovered_source_part.get('index', -1))
        except (AttributeError, TypeError, ValueError):
            hovered_source_index = -1
        split_ratio_getter = getattr(
            _state.alignment_d3d11_preview_host,
            'remember_side_by_side_split_ratio',
            None,
        )
        try:
            split_ratio = float(split_ratio_getter()) if callable(split_ratio_getter) else 0.5
        except (TypeError, ValueError, AttributeError):
            split_ratio = 0.5
        comparison_mode = effective_builder_comparison_mode(
            _state.preview_mode_combo.currentData(),
            bool(_state.mesh_edit_enabled_checkbox.isChecked()),
        )
        return builder_presentation_state(
            comparison_mode=comparison_mode,
            camera=camera,
            render_settings=settings,
            grid_visible=True,
            gizmo_visible=bool(_state.preview_gizmo_checkbox.isChecked()),
            part_pick_enabled=bool(_state.preview_part_pick_checkbox.isChecked()),
            mesh_edit_active=bool(_state.mesh_edit_enabled_checkbox.isChecked()),
            selected_source_indices=tuple(_state.selected_source_highlight_indices),
            selected_target_source_indices=tuple(_state.selected_target_source_highlight_indices),
            selected_original_indices=tuple(_state.selected_original_highlight_indices),
            selected_target_original_indices=tuple(_state.selected_target_original_highlight_indices),
            hovered_source_index=hovered_source_index,
            source_part_adjustments=_state.source_part_adjustments,
            uv_state=_state.texture_uv_global_transform_state,
            side_by_side_split_ratio=split_ratio,
        )

    def _mesh_editor_embedded_split_ratio_changed(ratio):
        try:
            remembered = _state.alignment_d3d11_preview_host.remember_side_by_side_split_ratio(
                float(ratio)
            )
            _state.self.settings.setValue(
                'ui/mesh_alignment/d3d11_side_by_side_split_ratio',
                remembered,
            )
            return True
        except (TypeError, ValueError, AttributeError, RuntimeError):
            return False

    def _mesh_editor_embedded_reference_native_package() -> str:
        prepared = str(_state.original_reference_texture_preview_state.get('native_package_path', '') or '').strip()
        if prepared:
            return prepared
        current_entry = _state.self._current_archive_entry() if callable(getattr(_state.self, '_current_archive_entry', None)) else None
        same_entry = callable(getattr(_state.self, '_same_archive_entry', None)) and _state.self._same_archive_entry(current_entry, _state.entry)
        if not same_entry:
            return ''
        current_result = getattr(_state.self, 'current_archive_preview_result', None)
        return str(getattr(current_result, 'native_preview_package_path', '') or '').strip()

    setattr(_state.dialog, '_mesh_editor_auto_dotnet_preview', True)
    setattr(_state.dialog, '_mesh_editor_action_bar_action_requested', _state.alignment_mesh_edit_callbacks._mesh_editor_action_bar_action_requested)
    setattr(_state.dialog, '_mesh_editor_embedded_controller', _state.alignment_mesh_edit_callbacks._mesh_editor_embedded_controller)
    setattr(_state.dialog, '_mesh_editor_embedded_placement_state', _state.alignment_mesh_edit_callbacks._mesh_editor_embedded_placement_state)
    setattr(
        _state.dialog,
        '_mesh_editor_embedded_scene_transform',
        lambda: _state._current_static_alignment_transform(),
    )
    setattr(_state.dialog, '_mesh_editor_embedded_reference_mesh', lambda: _state.original_mesh_for_mapping)
    setattr(
        _state.dialog,
        '_mesh_editor_embedded_reference_native_package',
        _mesh_editor_embedded_reference_native_package,
    )
    setattr(
        _state.dialog,
        '_mesh_editor_embedded_reference_material_model',
        lambda: _state._current_original_reference_preview_model(),
    )
    setattr(
        _state.dialog,
        '_mesh_editor_embedded_comparison_mode',
        lambda: effective_builder_comparison_mode(
            _state.preview_mode_combo.currentData(),
            bool(_state.mesh_edit_enabled_checkbox.isChecked()),
        ),
    )
    setattr(
        _state.dialog,
        '_mesh_editor_embedded_placement_comparison_mode',
        lambda: effective_builder_comparison_mode(
            _state.preview_mode_combo.currentData(),
            False,
        ),
    )
    setattr(_state.dialog, '_mesh_editor_embedded_interaction_mode', lambda: 'mesh_edit' if _state.mesh_edit_enabled_checkbox.isChecked() else 'placement')
    setattr(_state.dialog, '_mesh_editor_embedded_presentation_state', _mesh_editor_embedded_presentation_state)
    setattr(_state.dialog, '_mesh_editor_embedded_split_ratio_changed', _mesh_editor_embedded_split_ratio_changed)
    setattr(_state.dialog, '_mesh_editor_embedded_apply_native_update', _state.alignment_mesh_edit_callbacks._mesh_editor_embedded_apply_native_update)
    setattr(_state.dialog, '_mesh_editor_embedded_finalize_dotnet_import', _state.alignment_mesh_edit_callbacks._mesh_editor_embedded_finalize_dotnet_import)
    setattr(_state.dialog, '_mesh_editor_embedded_run_part_action', _state.alignment_mesh_edit_callbacks._mesh_editor_embedded_run_part_action)
    setattr(_state.dialog, '_mesh_editor_embedded_set_skeleton_bone', _state.alignment_mesh_edit_callbacks._mesh_editor_embedded_set_skeleton_bone)


def _mesh_geometry_preview_step_008(_state):
    if _state.classic_mesh_edit_toolbar is not None and _state.classic_mesh_edit_toolbar_layout is not None:
        _state.compact_actions_by_key = _state.mesh_editor_actions_by_key()
        _state.compact_action_keys = ('select_vertex', 'select_edge', 'select_face', 'transform_move', 'brush_grab', 'brush_smooth', 'brush_inflate', 'brush_pinch', 'delete', 'subdivide', 'refine_smooth', 'split', 'undo', 'redo')
        _state.classic_mesh_edit_action_bar = _state.MeshEditorActionBar(tuple((_state.compact_actions_by_key[key] for key in _state.compact_action_keys if key in _state.compact_actions_by_key)), parent=_state.classic_mesh_edit_toolbar)
        _state.classic_mesh_edit_action_bar.setObjectName('ClassicMeshEditPreviewActionBar')
        _state.classic_mesh_edit_toolbar_layout.addWidget(_state.classic_mesh_edit_action_bar)
        _state.compact_mesh_edit_options_widget = _state.QWidget(_state.classic_mesh_edit_toolbar)
        _state.compact_mesh_edit_options_widget.setObjectName('ClassicMeshEditPreviewOptions')
        _state.compact_options_row = _state.QHBoxLayout(_state.compact_mesh_edit_options_widget)
        _state.compact_options_row.setContentsMargins(0, 0, 0, 0)
        _state.compact_options_row.setSpacing(4)
        _state.compact_radius_spin = _state._make_double_spin_helper(24.0, 2.0, 256.0, 0, 2.0, ' px')
        _state.compact_strength_spin = _state._make_double_spin_helper(50.0, 0.0, 100.0, 0, 5.0, '%')
        _state.compact_falloff_combo = _state.QComboBox(_state.compact_mesh_edit_options_widget)
        _state._populate_combo_options_helper(_state.compact_falloff_combo, _state.MESH_EDIT_FALLOFF_OPTIONS)
        _state.compact_selection_mode_combo = _state.QComboBox(_state.compact_mesh_edit_options_widget)
        _state.compact_selection_mode_combo.setObjectName('ClassicMeshEditSelectionModeCombo')
        _state._populate_combo_options_helper(_state.compact_selection_mode_combo, _state.MESH_EDIT_SELECTION_MODE_OPTIONS)
        _state.compact_selection_mode_combo.setToolTip(_state.mesh_edit_action_control_text['selection_mode_tooltip'])
        _state.compact_selection_depth_combo = _state.QComboBox(_state.compact_mesh_edit_options_widget)
        _state.compact_selection_depth_combo.setObjectName('ClassicMeshEditSelectionDepthCombo')
        _state._populate_combo_options_helper(_state.compact_selection_depth_combo, _state.MESH_EDIT_SELECTION_DEPTH_OPTIONS)
        _state.compact_selection_depth_combo.setToolTip(_state.mesh_edit_action_control_text['selection_depth_tooltip'])
        _state.compact_mirror_checkbox = _state.QCheckBox('Mirror X', _state.compact_mesh_edit_options_widget)
        _state.compact_vertices_checkbox = _state.QCheckBox('Dots', _state.compact_mesh_edit_options_widget)
        for _state.compact_spin in (_state.compact_radius_spin, _state.compact_strength_spin):
            _state.compact_spin.setMaximumWidth(76)
        _state.compact_falloff_combo.setMaximumWidth(132)
        _state.compact_selection_mode_combo.setMaximumWidth(132)
        _state.compact_selection_depth_combo.setMaximumWidth(104)
        _state.compact_options_row.addWidget(_state.QLabel('Radius'))
        _state.compact_options_row.addWidget(_state.compact_radius_spin)
        _state.compact_options_row.addWidget(_state.QLabel('Strength'))
        _state.compact_options_row.addWidget(_state.compact_strength_spin)
        _state.compact_options_row.addWidget(_state.QLabel('Falloff'))
        _state.compact_options_row.addWidget(_state.compact_falloff_combo)
        _state.compact_options_row.addWidget(_state.compact_selection_mode_combo)
        _state.compact_options_row.addWidget(_state.compact_selection_depth_combo)
        _state.compact_options_row.addWidget(_state.compact_mirror_checkbox)
        _state.compact_options_row.addWidget(_state.compact_vertices_checkbox)
        _state.compact_mesh_edit_clear_button = _state.QPushButton('Clear', _state.compact_mesh_edit_options_widget)
        _state.compact_mesh_edit_grow_button = _state.QPushButton('Grow', _state.compact_mesh_edit_options_widget)
        _state.compact_mesh_edit_shrink_button = _state.QPushButton('Shrink', _state.compact_mesh_edit_options_widget)
        _state.compact_mesh_edit_feather_button = _state.QPushButton('Feather', _state.compact_mesh_edit_options_widget)
        _state.compact_mesh_edit_reset_scope_button = _state.QPushButton('Reset Scope', _state.compact_mesh_edit_options_widget)
        for _state.compact_button in (_state.compact_mesh_edit_clear_button, _state.compact_mesh_edit_grow_button, _state.compact_mesh_edit_shrink_button, _state.compact_mesh_edit_feather_button, _state.compact_mesh_edit_reset_scope_button):
            _state.compact_button.setMinimumWidth(0)
            _state.compact_button.setMaximumWidth(92)
            _state.compact_options_row.addWidget(_state.compact_button)
        _state.compact_mesh_edit_status_label = _state.QLabel('', _state.compact_mesh_edit_options_widget)
        _state.compact_mesh_edit_status_label.setObjectName('ClassicMeshEditPreviewStatus')
        _state.compact_mesh_edit_status_label.setWordWrap(False)
        _state.compact_options_row.addWidget(_state.compact_mesh_edit_status_label, 1)
        _state.compact_options_row.addStretch(1)
        _state.compact_radius_spin.valueChanged.connect(lambda value: _state.mesh_edit_radius_spin.setValue(float(value)))
        _state.mesh_edit_radius_spin.valueChanged.connect(lambda value: _state.compact_radius_spin.setValue(float(value)))
        _state.compact_strength_spin.valueChanged.connect(lambda value: _state.mesh_edit_strength_spin.setValue(float(value)))
        _state.mesh_edit_strength_spin.valueChanged.connect(lambda value: _state.compact_strength_spin.setValue(float(value)))
        _state.compact_falloff_combo.currentIndexChanged.connect(lambda _index: _state.mesh_edit_falloff_combo.setCurrentIndex(_state.max(0, _state.mesh_edit_falloff_combo.findData(_state.compact_falloff_combo.currentData()))))
        _state.mesh_edit_falloff_combo.currentIndexChanged.connect(lambda _index: _state.compact_falloff_combo.setCurrentIndex(_state.max(0, _state.compact_falloff_combo.findData(_state.mesh_edit_falloff_combo.currentData()))))
        _state.compact_selection_mode_combo.currentIndexChanged.connect(lambda _index: _state.mesh_edit_selection_mode_combo.setCurrentIndex(_state.max(0, _state.mesh_edit_selection_mode_combo.findData(_state.compact_selection_mode_combo.currentData()))))
        _state.mesh_edit_selection_mode_combo.currentIndexChanged.connect(lambda _index: _state.compact_selection_mode_combo.setCurrentIndex(_state.max(0, _state.compact_selection_mode_combo.findData(_state.mesh_edit_selection_mode_combo.currentData()))))
        _state.compact_selection_depth_combo.currentIndexChanged.connect(lambda _index: _state.mesh_edit_selection_depth_combo.setCurrentIndex(_state.max(0, _state.mesh_edit_selection_depth_combo.findData(_state.compact_selection_depth_combo.currentData()))))
        _state.mesh_edit_selection_depth_combo.currentIndexChanged.connect(lambda _index: _state.compact_selection_depth_combo.setCurrentIndex(_state.max(0, _state.compact_selection_depth_combo.findData(_state.mesh_edit_selection_depth_combo.currentData()))))
        _state.compact_mirror_checkbox.toggled.connect(lambda checked: _state.mesh_edit_mirror_checkbox.setChecked(_state.bool(checked)))
        _state.mesh_edit_mirror_checkbox.toggled.connect(lambda checked: _state.compact_mirror_checkbox.setChecked(_state.bool(checked)))
        _state.compact_vertices_checkbox.toggled.connect(lambda checked: _state.mesh_edit_show_vertices_checkbox.setChecked(_state.bool(checked)))
        _state.mesh_edit_show_vertices_checkbox.toggled.connect(lambda checked: _state.compact_vertices_checkbox.setChecked(_state.bool(checked)))
        _state.compact_vertices_checkbox.setChecked(_state.mesh_edit_show_vertices_checkbox.isChecked())
        _state.compact_mesh_edit_clear_button.clicked.connect(lambda _checked=False: _state.mesh_edit_clear_selection_button.click())
        _state.compact_mesh_edit_grow_button.clicked.connect(lambda _checked=False: _state.mesh_edit_grow_selection_button.click())
        _state.compact_mesh_edit_shrink_button.clicked.connect(lambda _checked=False: _state.mesh_edit_shrink_selection_button.click())
        _state.compact_mesh_edit_feather_button.clicked.connect(lambda _checked=False: _state.mesh_edit_smooth_selection_button.click())
        _state.compact_mesh_edit_reset_scope_button.clicked.connect(lambda _checked=False: _state.mesh_edit_reset_part_button.click())
        _state.classic_mesh_edit_toolbar_layout.addWidget(_state.compact_mesh_edit_options_widget)
        _state.classic_mesh_edit_toolbar.setVisible(False)
    _state.alignment_mesh_edit_callbacks = _state.create_alignment_mesh_edit_callbacks({**_state.context, **_state._factory_globals, **vars(_state), '_delete_selected_source_parts': lambda *args, **kwargs: _state._delete_selected_source_parts(*args, **kwargs)})
    if _state.classic_mesh_edit_action_bar is not None:
        _state.classic_mesh_edit_action_bar.action_requested.connect(_state.alignment_mesh_edit_callbacks._mesh_editor_action_bar_action_requested)
    _bind_embedded_mesh_editor_preview(_state)
    _state._mesh_edit_adjusted_sources_for_live_preview = _state.alignment_mesh_edit_callbacks._mesh_edit_adjusted_sources_for_live_preview
    _state._mesh_edit_all_live_vertices_for_sources = _state.alignment_mesh_edit_callbacks._mesh_edit_all_live_vertices_for_sources
    _state._mesh_edit_allowed_source_indices = _state.alignment_mesh_edit_callbacks._mesh_edit_allowed_source_indices
    _state._mesh_edit_apply_preview_payload = _state.alignment_mesh_edit_callbacks._mesh_edit_apply_preview_payload
    _state._mesh_edit_base_source_index_is_editable = _state.alignment_mesh_edit_callbacks._mesh_edit_base_source_index_is_editable
    _state._mesh_edit_begin_stroke = _state.alignment_mesh_edit_callbacks._mesh_edit_begin_stroke
    _state._mesh_edit_can_edit_scope = _state.alignment_mesh_edit_callbacks._mesh_edit_can_edit_scope
    _state._mesh_edit_cancel_stroke = _state.alignment_mesh_edit_callbacks._mesh_edit_cancel_stroke
    _state._mesh_edit_clear_topology_selection = _state.alignment_mesh_edit_callbacks._mesh_edit_clear_topology_selection
    _state._mesh_edit_clear_vertex_selection = _state.alignment_mesh_edit_callbacks._mesh_edit_clear_vertex_selection
    _state._mesh_edit_commit_working_mesh = _state.alignment_mesh_edit_callbacks._mesh_edit_commit_working_mesh
    _state._mesh_edit_control_tab_changed = _state.alignment_mesh_edit_callbacks._mesh_edit_control_tab_changed
    _state._mesh_edit_current_tool = _state.alignment_mesh_edit_callbacks._mesh_edit_current_tool
    _state._mesh_edit_delete_selected_faces = _state.alignment_mesh_edit_callbacks._mesh_edit_delete_selected_faces

def _mesh_geometry_preview_step_009(_state):
    _state._mesh_edit_disable_emptied_parts = _state.alignment_mesh_edit_callbacks._mesh_edit_disable_emptied_parts
    _state._mesh_edit_enabled_toggled = _state.alignment_mesh_edit_callbacks._mesh_edit_enabled_toggled
    _state._mesh_edit_faces_from_payload = _state.alignment_mesh_edit_callbacks._mesh_edit_faces_from_payload
    _state._mesh_edit_finish_stroke = _state.alignment_mesh_edit_callbacks._mesh_edit_finish_stroke
    _state._mesh_edit_full_reset_mesh = _state.alignment_mesh_edit_callbacks._mesh_edit_full_reset_mesh
    _state._mesh_edit_grow_selection = _state.alignment_mesh_edit_callbacks._mesh_edit_grow_selection
    _state._mesh_edit_invert_selection = _state.alignment_mesh_edit_callbacks._mesh_edit_invert_selection
    _state._mesh_edit_live_vertex_update_groups = _state.alignment_mesh_edit_callbacks._mesh_edit_live_vertex_update_groups
    _state._mesh_edit_merge_face_groups = _state.alignment_mesh_edit_callbacks._mesh_edit_merge_face_groups
    _state._mesh_edit_merge_vertex_groups = _state.alignment_mesh_edit_callbacks._mesh_edit_merge_vertex_groups
    _state._mesh_edit_part_enabled_snapshot = _state.alignment_mesh_edit_callbacks._mesh_edit_part_enabled_snapshot
    _state._mesh_edit_payload_has_drag_motion = _state.alignment_mesh_edit_callbacks._mesh_edit_payload_has_drag_motion
    _state._mesh_edit_pop_undo_snapshot = _state.alignment_mesh_edit_callbacks._mesh_edit_pop_undo_snapshot
    _state._mesh_edit_preview_delta_to_source_delta = _state.alignment_mesh_edit_callbacks._mesh_edit_preview_delta_to_source_delta
    _state._mesh_edit_preview_distance_to_source_distance = _state.alignment_mesh_edit_callbacks._mesh_edit_preview_distance_to_source_distance
    _state._mesh_edit_preview_point_to_source_point = _state.alignment_mesh_edit_callbacks._mesh_edit_preview_point_to_source_point
    _state._mesh_edit_preview_source_indices = _state.alignment_mesh_edit_callbacks._mesh_edit_preview_source_indices
    _state._mesh_edit_push_undo_snapshot = _state.alignment_mesh_edit_callbacks._mesh_edit_push_undo_snapshot
    _state._mesh_edit_record_snapshot = _state.alignment_mesh_edit_callbacks._mesh_edit_record_snapshot
    _state._mesh_edit_redo = _state.alignment_mesh_edit_callbacks._mesh_edit_redo
    _state._mesh_edit_replace_live_triangles = _state.alignment_mesh_edit_callbacks._mesh_edit_replace_live_triangles
    _state._mesh_edit_replace_live_triangles_or_queue_rebuild = _state.alignment_mesh_edit_callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild
    _state._mesh_edit_replace_working_mesh = _state.alignment_mesh_edit_callbacks._mesh_edit_replace_working_mesh
    _state._mesh_edit_reset_scope = _state.alignment_mesh_edit_callbacks._mesh_edit_reset_scope
    _state._mesh_edit_restore_enabled_snapshot = _state.alignment_mesh_edit_callbacks._mesh_edit_restore_enabled_snapshot
    _state._mesh_edit_restore_snapshot = _state.alignment_mesh_edit_callbacks._mesh_edit_restore_snapshot
    _state._mesh_edit_scope_mode = _state.alignment_mesh_edit_callbacks._mesh_edit_scope_mode
    _state._mesh_edit_select_whole_part = _state.alignment_mesh_edit_callbacks._mesh_edit_select_whole_part
    _state._mesh_edit_selected_scope_source_index = _state.alignment_mesh_edit_callbacks._mesh_edit_selected_scope_source_index
    _state._mesh_edit_selected_source_index = _state.alignment_mesh_edit_callbacks._mesh_edit_selected_source_index
    _state._mesh_edit_selection_changed = _state.alignment_mesh_edit_callbacks._mesh_edit_selection_changed
    _state._mesh_edit_selection_depth_mode = _state.alignment_mesh_edit_callbacks._mesh_edit_selection_depth_mode
    _state._mesh_edit_selection_mode = _state.alignment_mesh_edit_callbacks._mesh_edit_selection_mode
    _state._mesh_edit_set_vertex_selection = _state.alignment_mesh_edit_callbacks._mesh_edit_set_vertex_selection
    _state._mesh_edit_shrink_selection = _state.alignment_mesh_edit_callbacks._mesh_edit_shrink_selection
    _state._mesh_edit_smooth_selection = _state.alignment_mesh_edit_callbacks._mesh_edit_smooth_selection
    _state._mesh_edit_source_index_is_editable = _state.alignment_mesh_edit_callbacks._mesh_edit_source_index_is_editable
    _state._mesh_edit_source_to_preview_point = _state.alignment_mesh_edit_callbacks._mesh_edit_source_to_preview_point
    _state._mesh_edit_stroke_id = _state.alignment_mesh_edit_callbacks._mesh_edit_stroke_id
    _state._mesh_edit_subdivide_selection = _state.alignment_mesh_edit_callbacks._mesh_edit_subdivide_selection
    _state._mesh_edit_submesh_for_live_preview = _state.alignment_mesh_edit_callbacks._mesh_edit_submesh_for_live_preview
    _state._mesh_edit_target_mode_for_tool = _state.alignment_mesh_edit_callbacks._mesh_edit_target_mode_for_tool
    _state._mesh_edit_transformed_sources_for_live_preview = _state.alignment_mesh_edit_callbacks._mesh_edit_transformed_sources_for_live_preview
    _state._mesh_edit_triangle_replace_groups = _state.alignment_mesh_edit_callbacks._mesh_edit_triangle_replace_groups
    _state._mesh_edit_undo = _state.alignment_mesh_edit_callbacks._mesh_edit_undo
    _state._mesh_edit_update_live_preview = _state.alignment_mesh_edit_callbacks._mesh_edit_update_live_preview
    _state._mesh_edit_update_mesh_totals = _state.alignment_mesh_edit_callbacks._mesh_edit_update_mesh_totals
    _state._mesh_edit_vertices_from_payload = _state.alignment_mesh_edit_callbacks._mesh_edit_vertices_from_payload
    _state._morph_slider_active_deltas = _state.alignment_mesh_edit_callbacks._morph_slider_active_deltas
    _state._morph_slider_add_row = _state.alignment_mesh_edit_callbacks._morph_slider_add_row
    _state._morph_slider_add_target = _state.alignment_mesh_edit_callbacks._morph_slider_add_target
    _state._morph_slider_apply_to_working_mesh = _state.alignment_mesh_edit_callbacks._morph_slider_apply_to_working_mesh
    _state._morph_slider_bake = _state.alignment_mesh_edit_callbacks._morph_slider_bake
    _state._morph_slider_begin_change = _state.alignment_mesh_edit_callbacks._morph_slider_begin_change
    _state._morph_slider_capture_post_edit_deltas = _state.alignment_mesh_edit_callbacks._morph_slider_capture_post_edit_deltas
    _state._morph_slider_clear_rows = _state.alignment_mesh_edit_callbacks._morph_slider_clear_rows
    _state._morph_slider_create_from_selection = _state.alignment_mesh_edit_callbacks._morph_slider_create_from_selection
    _state._morph_slider_default_region_amount = _state.alignment_mesh_edit_callbacks._morph_slider_default_region_amount
    _state._morph_slider_end_change = _state.alignment_mesh_edit_callbacks._morph_slider_end_change
    _state._morph_slider_ensure_post_edit_deltas = _state.alignment_mesh_edit_callbacks._morph_slider_ensure_post_edit_deltas
    _state._morph_slider_has_loaded_deltas = _state.alignment_mesh_edit_callbacks._morph_slider_has_loaded_deltas
    _state._morph_slider_has_nonzero_values = _state.alignment_mesh_edit_callbacks._morph_slider_has_nonzero_values
    _state._morph_slider_import_pack = _state.alignment_mesh_edit_callbacks._morph_slider_import_pack
    _state._morph_slider_mark_topology_changed = _state.alignment_mesh_edit_callbacks._morph_slider_mark_topology_changed
    _state._morph_slider_rebuild_rows = _state.alignment_mesh_edit_callbacks._morph_slider_rebuild_rows
    _state._morph_slider_refresh_controls = _state.alignment_mesh_edit_callbacks._morph_slider_refresh_controls
    _state._morph_slider_refresh_topology_block_state = _state.alignment_mesh_edit_callbacks._morph_slider_refresh_topology_block_state
    _state._morph_slider_reload_profiles = _state.alignment_mesh_edit_callbacks._morph_slider_reload_profiles
    _state._morph_slider_reset_all = _state.alignment_mesh_edit_callbacks._morph_slider_reset_all
    _state._morph_slider_set_value = _state.alignment_mesh_edit_callbacks._morph_slider_set_value
    _state._morph_slider_slider_only_mesh = _state.alignment_mesh_edit_callbacks._morph_slider_slider_only_mesh
    _state._morph_slider_supported = _state.alignment_mesh_edit_callbacks._morph_slider_supported
    _state._morph_slider_sync_row_widgets = _state.alignment_mesh_edit_callbacks._morph_slider_sync_row_widgets
    _state._morph_slider_zero_post_edit_deltas = _state.alignment_mesh_edit_callbacks._morph_slider_zero_post_edit_deltas
    _state._morph_slider_zero_post_edit_deltas_for_sources = _state.alignment_mesh_edit_callbacks._morph_slider_zero_post_edit_deltas_for_sources
    _state._refresh_mesh_edit_controls = _state.alignment_mesh_edit_callbacks._refresh_mesh_edit_controls
    _state._refresh_mesh_edit_part_combo = _state.alignment_mesh_edit_callbacks._refresh_mesh_edit_part_combo
    _state._sync_mesh_edit_preview_settings = _state.alignment_mesh_edit_callbacks._sync_mesh_edit_preview_settings
    if _state.CollapsibleSection is not None:
        _state.legacy_mesh_edit_section = _state.CollapsibleSection('Legacy Mesh Controls', expanded=False)
        _state.legacy_mesh_edit_section.setObjectName('LegacyMeshEditControlsDrawer')
        _state.legacy_mesh_edit_section.body_layout.addWidget(_state.mesh_edit_group, 0)
        _state.mesh_edit_layout_page.addWidget(_state.legacy_mesh_edit_section, 0)
    else:
        _state.mesh_edit_layout_page.addWidget(_state.mesh_edit_group, 0)
    _state.mesh_edit_layout_page.addWidget(_state.morph_slider_group, 0)
    _state.mesh_edit_layout_page.addStretch(1)
    _state.source_tree.currentItemChanged.connect(_state._source_selection_changed)
    _state.source_tree.itemSelectionChanged.connect(_state._refresh_source_tree_selection_state)
    _state.original_tree.currentItemChanged.connect(_state._original_selection_changed)
    _state.mapping_tree.currentItemChanged.connect(_state._target_selection_changed)
    _state.control_tabs.currentChanged.connect(_state._clear_part_selections_when_leaving_geometry)
    _state.control_tabs.currentChanged.connect(_state._mesh_edit_control_tab_changed)
    _state.control_tabs.currentChanged.connect(lambda _index: _state._update_selection_context())
    _state.control_tabs.currentChanged.connect(lambda index: _state._refresh_mesh_editor_diagnostics() if _state.control_tabs.widget(index) is _state.diagnostics_tab else None)
    _state._refresh_source_assignment_columns()
    _state._load_selected_part_controls()
    _state._refresh_mesh_edit_controls()
    _state._update_mapping_status()
    _state._update_selection_context()

def _mesh_geometry_preview_step_010(_state):
    _state._alignment_startup_step(_state.alignment_startup_text['geometry_controls'])
    _state.geometry_overview_group = _state.QWidget()
    _state.geometry_overview_layout = _state.QVBoxLayout(_state.geometry_overview_group)
    _state.geometry_overview_layout.setAlignment(_state.Qt.AlignTop)
    _state.geometry_overview_layout.setContentsMargins(5, 3, 5, 3)
    _state.geometry_overview_layout.setSpacing(3)
    _state.source_count = _state.sum((1 for source in _state.getattr(_state.replacement_mesh_for_mapping, 'submeshes', ()) or () if not _state._is_marker_source(source)))
    _state.active_target_count = _state.sum((1 for _target_index, edit in _state.mapping_edits if _state._enabled_renderable_source_indices(_state._parse_mapping_edit(edit))))
    _state.empty_target_count = _state.max(0, _state.len(_state.mapping_edits) - _state.active_target_count)
    _state.geometry_summary = _state.QLabel(_state._geometry_mapping_summary_html_helper(_state.source_count, _state.active_target_count, _state.empty_target_count))
    _state.geometry_summary.setWordWrap(True)
    _state.geometry_summary.setTextFormat(_state.Qt.RichText)
    _state.geometry_summary.setTextInteractionFlags(_state.Qt.TextSelectableByMouse)
    _state.geometry_overview_layout.addWidget(_state.geometry_summary)
    _state.output_impact_review_label = _state.QLabel()
    _state.output_impact_review_label.setObjectName('HintLabel')
    _state.output_impact_review_label.setWordWrap(True)
    _state.output_impact_review_label.setTextFormat(_state.Qt.RichText)
    _state.output_impact_review_label.setTextInteractionFlags(_state.Qt.TextSelectableByMouse)
    _state.geometry_overview_layout.addWidget(_state.output_impact_review_label)
    _state.properties_control_text = _state._source_part_properties_control_text_helper()
    _state.properties_sections = _state.properties_control_text['sections']
    _state.properties_group = _state.QGroupBox(_state.str(_state.properties_control_text['title']))
    _state.properties_group.setObjectName(_state.str(_state.properties_control_text['group_object']))
    _state.properties_layout = _state.QVBoxLayout(_state.properties_group)
    _state.properties_layout.setAlignment(_state.Qt.AlignTop)
    _state.properties_layout.setContentsMargins(5, 3, 5, 3)
    _state.properties_layout.setSpacing(3)

def _mesh_geometry_preview_step_011(_state):

    def _new_properties_section_label(object_name: str) -> QLabel:
        label = _state.QLabel(_state.str(_state.properties_control_text['placeholder']))
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setTextFormat(_state.Qt.RichText)
        label.setTextInteractionFlags(_state.Qt.TextSelectableByMouse)
        label.setMinimumWidth(0)
        label.setSizePolicy(_state.QSizePolicy.Ignored, _state.QSizePolicy.Maximum)
        return label
    _state._new_properties_section_label = _new_properties_section_label

def _mesh_geometry_preview_step_012(_state):
    _state.properties_identity_label = _state._new_properties_section_label(_state.properties_sections['identity'][1])
    _state.properties_assignment_label = _state._new_properties_section_label(_state.properties_sections['assignment'][1])
    _state.properties_dds_label = _state._new_properties_section_label(_state.properties_sections['dds'][1])
    _state.properties_output_label = _state._new_properties_section_label(_state.properties_sections['output'][1])
    _state.properties_warnings_label = _state._new_properties_section_label(_state.properties_sections['warnings'][1])
    for _state.properties_label in (_state.properties_identity_label, _state.properties_assignment_label, _state.properties_dds_label, _state.properties_output_label, _state.properties_warnings_label):
        _state.properties_layout.addWidget(_state.properties_label)
    _state.geometry_overview_layout.addWidget(_state.properties_group)
    _state.alignment_preview_model_callbacks = _state.create_alignment_preview_model_callbacks({**_state.context, **_state._factory_globals, **vars(_state)})
    _state._refresh_output_impact_review = _state.alignment_preview_model_callbacks._refresh_output_impact_review
    _state._refresh_geometry_summary = _state.alignment_preview_model_callbacks._refresh_geometry_summary
    _state._current_dialog_mappings_for_preview = _state.alignment_preview_model_callbacks._current_dialog_mappings_for_preview
    _state._preview_target_mesh_indices = _state.alignment_preview_model_callbacks._preview_target_mesh_indices
    _state._preview_model_in_original_frame = _state.alignment_preview_model_callbacks._preview_model_in_original_frame
    _state._source_preview_geometry_key = _state.alignment_preview_model_callbacks._source_preview_geometry_key
    _state._mapped_source_indices = _state.alignment_preview_model_callbacks._mapped_source_indices
    _state._current_independent_parts = _state.alignment_preview_model_callbacks._current_independent_parts
    _state._current_static_alignment_transform = _state.alignment_preview_model_callbacks._current_static_alignment_transform
    _state._current_static_placement_snapshot = _state.alignment_preview_model_callbacks._current_static_placement_snapshot
    _state._static_options_from_placement_snapshot = _state.alignment_preview_model_callbacks._static_options_from_placement_snapshot
    _state._build_unmapped_appended_source_overlay_model = _state.alignment_preview_model_callbacks._build_unmapped_appended_source_overlay_model
    _state._append_unmapped_appended_source_overlays = _state.alignment_preview_model_callbacks._append_unmapped_appended_source_overlays
    _state._source_selection_overlay_adjustments = _state.alignment_preview_model_callbacks._source_selection_overlay_adjustments
    _state._build_selected_source_highlight_overlay_model = _state.alignment_preview_model_callbacks._build_selected_source_highlight_overlay_model
    _state._append_selected_source_highlight_overlay = _state.alignment_preview_model_callbacks._append_selected_source_highlight_overlay
    _state._build_direct_source_preview_model = _state.alignment_preview_model_callbacks._build_direct_source_preview_model
    _state._selected_part_preview_indices = _state.alignment_preview_model_callbacks._selected_part_preview_indices
    _state._remember_alignment_d3d11_source_editor_ids = _state.alignment_preview_model_callbacks._remember_alignment_d3d11_source_editor_ids
    _state._copy_original_preview_material = _state.alignment_preview_model_callbacks._copy_original_preview_material
    _state._apply_original_material_preview = _state.alignment_preview_model_callbacks._apply_original_material_preview
    _state._ensure_original_reference_texture_preview_ready = _state.alignment_preview_model_callbacks._ensure_original_reference_texture_preview_ready
    _state._refresh_alignment_virtual_sidecar_contract = _state.alignment_preview_model_callbacks._refresh_alignment_virtual_sidecar_contract
    _state.alignment_static_preview_refresh_callbacks = _state.create_alignment_static_preview_refresh_callbacks({**_state.context, **_state._factory_globals, **vars(_state), '_basic_controls_profile_enabled': lambda *args, **kwargs: _state._basic_controls_profile_enabled(*args, **kwargs), '_current_complete_swap_material_profile_token': lambda *args, **kwargs: _state._current_complete_swap_material_profile_token(*args, **kwargs), '_current_material_authority_preview_profile': lambda *args, **kwargs: _state._current_material_authority_preview_profile(*args, **kwargs), '_material_authority_preview_inactive_reason': lambda *args, **kwargs: _state._material_authority_preview_inactive_reason(*args, **kwargs), '_material_authority_preview_signature': lambda *args, **kwargs: _state._material_authority_preview_signature(*args, **kwargs)})
    _state._refresh_static_dialog_preview = _state.alignment_static_preview_refresh_callbacks._refresh_static_dialog_preview
    _state._safe_refresh_static_dialog_preview = _state.alignment_static_preview_refresh_callbacks._safe_refresh_static_dialog_preview
    _state.static_preview_refresh_timer.timeout.connect(_state._safe_refresh_static_dialog_preview)
    _state.static_preview_settle_timer.timeout.connect(_state._queue_static_preview_refresh)
    _state._load_native_preview_core_material_manifest_for_alignment = lambda target_preview_model, package_root_text='': _state._load_native_preview_core_material_manifest_for_alignment_helper(target_preview_model, entry=_state.entry, package_root_text=package_root_text, active=_state._alignment_d3d11_preview_active(), model_extensions=_state.NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS, cache_root=_state.self.archive_cache_root / 'native_preview_core', render_settings=_state._current_preview_render_settings(), companion_entry=_state.self._find_archive_preview_companion_entry(_state.entry), run_preview_job=_state.run_native_preview_core_preview_job, clear_native_package_path=lambda: _state._original_reference_texture_preview_clear_native_package_path_helper(_state.original_reference_texture_preview_state), set_native_package_path=lambda package_path: _state._original_reference_texture_preview_set_native_package_path_helper(_state.original_reference_texture_preview_state, package_path), apply_manifest=lambda preview_model, package_path: _state._apply_native_preview_core_material_manifest_helper(preview_model, package_path, native_manifest_input_from_descriptor=_state._native_manifest_input_from_descriptor), record_runtime_event=_state._record_runtime_event, dialog_title=_state.dialog_title)
    _state.alignment_original_texture_worker_callbacks = _state.create_alignment_original_texture_worker_callbacks({**_state.context, **_state._factory_globals, **vars(_state), '_handle_original_reference_texture_preview_error': lambda *args, **kwargs: _state._handle_original_reference_texture_preview_error(*args, **kwargs)})
    _state._handle_original_reference_texture_preview_ready = _state.alignment_original_texture_worker_callbacks._handle_original_reference_texture_preview_ready
    _state._OriginalTexturePreviewWorkerReceiver = _state.alignment_original_texture_worker_callbacks._OriginalTexturePreviewWorkerReceiver
    _state.original_texture_worker_receiver = _state._OriginalTexturePreviewWorkerReceiver(_state.dialog)

def _mesh_geometry_preview_step_013(_state):
    _state._factory_result_values.update({'_append_selected_source_highlight_overlay': vars(_state).get('_append_selected_source_highlight_overlay'), '_apply_original_material_preview': vars(_state).get('_apply_original_material_preview'), '_build_direct_source_preview_model': vars(_state).get('_build_direct_source_preview_model'), '_current_dialog_mappings_for_preview': vars(_state).get('_current_dialog_mappings_for_preview'), '_current_static_alignment_transform': vars(_state).get('_current_static_alignment_transform'), '_current_static_placement_snapshot': vars(_state).get('_current_static_placement_snapshot'), '_ensure_original_reference_texture_preview_ready': vars(_state).get('_ensure_original_reference_texture_preview_ready'), '_load_native_preview_core_material_manifest_for_alignment': vars(_state).get('_load_native_preview_core_material_manifest_for_alignment'), '_mesh_edit_apply_preview_payload': vars(_state).get('_mesh_edit_apply_preview_payload'), '_mesh_edit_begin_stroke': vars(_state).get('_mesh_edit_begin_stroke'), '_mesh_edit_cancel_stroke': vars(_state).get('_mesh_edit_cancel_stroke'), '_mesh_edit_finish_stroke': vars(_state).get('_mesh_edit_finish_stroke'), '_mesh_edit_preview_source_indices': vars(_state).get('_mesh_edit_preview_source_indices'), '_mesh_edit_replace_live_triangles_or_queue_rebuild': vars(_state).get('_mesh_edit_replace_live_triangles_or_queue_rebuild'), '_mesh_edit_selection_changed': vars(_state).get('_mesh_edit_selection_changed'), '_mesh_edit_update_live_preview': vars(_state).get('_mesh_edit_update_live_preview'), '_morph_slider_refresh_controls': vars(_state).get('_morph_slider_refresh_controls'), '_morph_slider_reload_profiles': vars(_state).get('_morph_slider_reload_profiles'), '_preview_target_mesh_indices': vars(_state).get('_preview_target_mesh_indices'), '_refresh_alignment_virtual_sidecar_contract': vars(_state).get('_refresh_alignment_virtual_sidecar_contract'), '_refresh_mesh_edit_controls': vars(_state).get('_refresh_mesh_edit_controls'), '_refresh_output_impact_review': vars(_state).get('_refresh_output_impact_review'), '_remember_alignment_d3d11_source_editor_ids': vars(_state).get('_remember_alignment_d3d11_source_editor_ids'), '_safe_refresh_static_dialog_preview': vars(_state).get('_safe_refresh_static_dialog_preview'), '_selected_part_preview_indices': vars(_state).get('_selected_part_preview_indices'), '_static_options_from_placement_snapshot': vars(_state).get('_static_options_from_placement_snapshot'), '_sync_mesh_edit_preview_settings': vars(_state).get('_sync_mesh_edit_preview_settings'), 'button': vars(_state).get('button'), 'edit': vars(_state).get('edit'), 'geometry_overview_group': vars(_state).get('geometry_overview_group'), 'geometry_overview_layout': vars(_state).get('geometry_overview_layout'), 'geometry_summary': vars(_state).get('geometry_summary'), 'label': vars(_state).get('label'), 'mesh_edit_action_control_text': vars(_state).get('mesh_edit_action_control_text'), 'mesh_edit_button_row': vars(_state).get('mesh_edit_button_row'), 'mesh_edit_clear_selection_button': vars(_state).get('mesh_edit_clear_selection_button'), 'mesh_edit_delete_faces_button': vars(_state).get('mesh_edit_delete_faces_button'), 'mesh_edit_delete_mode_combo': vars(_state).get('mesh_edit_delete_mode_combo'), 'mesh_edit_enabled_checkbox': vars(_state).get('mesh_edit_enabled_checkbox'), 'mesh_edit_falloff_combo': vars(_state).get('mesh_edit_falloff_combo'), 'mesh_edit_field_rows': vars(_state).get('mesh_edit_field_rows'), 'mesh_edit_full_reset_button': vars(_state).get('mesh_edit_full_reset_button'), 'mesh_edit_group': vars(_state).get('mesh_edit_group'), 'mesh_edit_grow_selection_button': vars(_state).get('mesh_edit_grow_selection_button'), 'mesh_edit_invert_selection_button': vars(_state).get('mesh_edit_invert_selection_button')})

def _mesh_geometry_preview_step_014(_state):
    _state._factory_result_values.update({'mesh_edit_iterations_spin': vars(_state).get('mesh_edit_iterations_spin'), 'mesh_edit_layout': vars(_state).get('mesh_edit_layout'), 'mesh_edit_mirror_checkbox': vars(_state).get('mesh_edit_mirror_checkbox'), 'mesh_edit_option_widget': vars(_state).get('mesh_edit_option_widget'), 'mesh_edit_part_combo': vars(_state).get('mesh_edit_part_combo'), 'mesh_edit_radius_spin': vars(_state).get('mesh_edit_radius_spin'), 'mesh_edit_redo_button': vars(_state).get('mesh_edit_redo_button'), 'mesh_edit_remove_mode_label': vars(_state).get('mesh_edit_remove_mode_label'), 'mesh_edit_reset_part_button': vars(_state).get('mesh_edit_reset_part_button'), 'mesh_edit_scope_combo': vars(_state).get('mesh_edit_scope_combo'), 'mesh_edit_select_part_button': vars(_state).get('mesh_edit_select_part_button'), 'mesh_edit_selection_actions_widget': vars(_state).get('mesh_edit_selection_actions_widget'), 'mesh_edit_selection_depth_combo': vars(_state).get('mesh_edit_selection_depth_combo'), 'mesh_edit_selection_mode_combo': vars(_state).get('mesh_edit_selection_mode_combo'), 'mesh_edit_show_vertices_checkbox': vars(_state).get('mesh_edit_show_vertices_checkbox'), 'mesh_edit_shrink_selection_button': vars(_state).get('mesh_edit_shrink_selection_button'), 'mesh_edit_smooth_selection_button': vars(_state).get('mesh_edit_smooth_selection_button'), 'mesh_edit_refine_smooth_selection_button': vars(_state).get('mesh_edit_refine_smooth_selection_button'), 'mesh_edit_status_label': vars(_state).get('mesh_edit_status_label'), 'mesh_edit_strength_spin': vars(_state).get('mesh_edit_strength_spin'), 'mesh_edit_split_selection_button': vars(_state).get('mesh_edit_split_selection_button'), 'mesh_edit_subdivide_selection_button': vars(_state).get('mesh_edit_subdivide_selection_button'), 'mesh_edit_supported': vars(_state).get('mesh_edit_supported'), 'mesh_edit_tool_buttons': vars(_state).get('mesh_edit_tool_buttons'), 'mesh_edit_tool_combo': vars(_state).get('mesh_edit_tool_combo'), 'mesh_edit_tool_palette': vars(_state).get('mesh_edit_tool_palette'), 'mesh_edit_undo_button': vars(_state).get('mesh_edit_undo_button'), 'morph_slider_add_action': vars(_state).get('morph_slider_add_action'), 'morph_slider_bake_button': vars(_state).get('morph_slider_bake_button'), 'morph_slider_create_button': vars(_state).get('morph_slider_create_button'), 'morph_slider_group': vars(_state).get('morph_slider_group'), 'morph_slider_import_action': vars(_state).get('morph_slider_import_action'), 'morph_slider_manage_button': vars(_state).get('morph_slider_manage_button'), 'morph_slider_reload_action': vars(_state).get('morph_slider_reload_action'), 'morph_slider_reset_button': vars(_state).get('morph_slider_reset_button'), 'morph_slider_rows_layout': vars(_state).get('morph_slider_rows_layout'), 'morph_slider_rows_widget': vars(_state).get('morph_slider_rows_widget'), 'morph_slider_status_label': vars(_state).get('morph_slider_status_label'), 'original_texture_worker_receiver': vars(_state).get('original_texture_worker_receiver'), 'output_impact_review_label': vars(_state).get('output_impact_review_label'), 'source': vars(_state).get('source'), 'source_count': vars(_state).get('source_count'), 'tooltip': vars(_state).get('tooltip')})

STEPS = (
    _mesh_geometry_preview_step_001,
    _mesh_geometry_preview_step_002,
    _mesh_geometry_preview_step_003,
    _mesh_geometry_preview_step_004,
    _mesh_geometry_preview_step_005,
    _mesh_geometry_preview_step_006,
    _mesh_geometry_preview_step_007,
    _mesh_geometry_preview_step_008,
    _mesh_geometry_preview_step_009,
    _mesh_geometry_preview_step_010,
    _mesh_geometry_preview_step_011,
    _mesh_geometry_preview_step_012,
    _mesh_geometry_preview_step_013,
    _mesh_geometry_preview_step_014,
)

"""Preview shell UI builder for static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.shell.settings_bridge import read_bool_setting


def _control_group_separator(QFrame, parent):
    """A thin rule that keeps the preview control clusters visually apart."""
    separator = QFrame(parent)
    separator.setObjectName("MeshAlignmentPreviewControlSeparator")
    separator.setFrameShape(QFrame.VLine)
    separator.setFrameShadow(QFrame.Plain)
    separator.setFixedWidth(1)
    return separator


def _legacy_preview_rows(QWidget, QHBoxLayout, parent):
    legacy_preview_controls_widget = QWidget(parent)
    legacy_preview_controls_widget.setObjectName("MeshAlignmentLegacyPreviewControls")
    preview_controls_row = QHBoxLayout(legacy_preview_controls_widget)
    preview_controls_row.setContentsMargins(0, 0, 0, 0)
    preview_controls_row.setSpacing(6)
    legacy_preview_camera_widget = QWidget(parent)
    legacy_preview_camera_widget.setObjectName("MeshAlignmentLegacyPreviewCameraControls")
    preview_camera_row = QHBoxLayout(legacy_preview_camera_widget)
    preview_camera_row.setContentsMargins(0, 0, 0, 0)
    preview_camera_row.setSpacing(4)
    return legacy_preview_controls_widget, preview_controls_row, legacy_preview_camera_widget, preview_camera_row


def create_alignment_preview_shell_section(context: dict[str, object]) -> SimpleNamespace:
    DOTNET_PREVIEW_VIEW_MODE_OPTIONS = context.get('DOTNET_PREVIEW_VIEW_MODE_OPTIONS')
    Dict = context.get('Dict')
    MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODES = context.get('MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODES')
    MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS = context.get('MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS')
    MODEL_PREVIEW_VISIBLE_TEXTURE_MODES = context.get('MODEL_PREVIEW_VISIBLE_TEXTURE_MODES')
    MODEL_PREVIEW_VISIBLE_TEXTURE_MODE_LABELS = context.get('MODEL_PREVIEW_VISIBLE_TEXTURE_MODE_LABELS')
    MESH_PREVIEW_DEFAULT_DISPLAY_MODE = context.get('MESH_PREVIEW_DEFAULT_DISPLAY_MODE')
    MESH_PREVIEW_DISPLAY_MODE_OPTIONS = context.get('MESH_PREVIEW_DISPLAY_MODE_OPTIONS')
    DotNetPreviewHostFrame = context.get('DotNetPreviewHostFrame')
    DotNetPreviewProfile = context.get('DotNetPreviewProfile')
    NativePreviewPanel = context.get('NativePreviewPanel')
    OrderedDict = context.get('OrderedDict')
    PREVIEW_MODE_OPTIONS = context.get('PREVIEW_MODE_OPTIONS')
    PREVIEW_RENDERER_OPTIONS = context.get('PREVIEW_RENDERER_OPTIONS')
    QCheckBox = context.get('QCheckBox')
    QComboBox = context.get('QComboBox')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    QFrame = context.get('QFrame')
    QHBoxLayout = context.get('QHBoxLayout')
    QLabel = context.get('QLabel')
    QPushButton = context.get('QPushButton')
    QSizePolicy = context.get('QSizePolicy')
    QSplitter = context.get('QSplitter')
    QStackedWidget = context.get('QStackedWidget')
    QTimer = context.get('QTimer')
    QVBoxLayout = context.get('QVBoxLayout')
    QWidget = context.get('QWidget')
    Qt = context.get('Qt')
    _alignment_camera_button_helper = context.get('_alignment_camera_button_helper')
    _alignment_d3d11_loading_initial_state_helper = context.get('_alignment_d3d11_loading_initial_state_helper')
    _alignment_dialog_layout_initial_state_helper = context.get('_alignment_dialog_layout_initial_state_helper')
    _alignment_lit_render_settings_helper = context.get('_alignment_lit_render_settings_helper')
    _alignment_preview_camera_button_specs_helper = context.get('_alignment_preview_camera_button_specs_helper')
    _alignment_preview_control_text_helper = context.get('_alignment_preview_control_text_helper')
    _alignment_preview_help_presentation_helper = context.get('_alignment_preview_help_presentation_helper')
    _alignment_preview_initial_performance_status_helper = context.get('_alignment_preview_initial_performance_status_helper')
    _alignment_preview_mode_initial_state_helper = context.get('_alignment_preview_mode_initial_state_helper')
    _alignment_preview_render_control_text_helper = context.get('_alignment_preview_render_control_text_helper')
    _alignment_preview_view_sync_initial_state_helper = context.get('_alignment_preview_view_sync_initial_state_helper')
    _clear_all_part_selections = context.get('_clear_all_part_selections')
    _custom_item_icon_control_text_helper = context.get('_custom_item_icon_control_text_helper')
    _mesh_editor_diagnostics_initial_state_helper = context.get('_mesh_editor_diagnostics_initial_state_helper')
    _original_texture_preview_material_preview_enabled_helper = context.get('_original_texture_preview_material_preview_enabled_helper')
    _populate_combo_options_helper = context.get('_populate_combo_options_helper')
    _rough_control_value_from_settings = context.get('_rough_control_value_from_settings')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _texture_uv_control_text_helper = context.get('_texture_uv_control_text_helper')
    alignment_d3d11_view_state_reset_generation = context.get('alignment_d3d11_view_state_reset_generation')
    alignment_dialog_key = context.get('alignment_dialog_key')
    bool = context.get('bool')
    create_alignment_d3d11_loading_callbacks = context.get('create_alignment_d3d11_loading_callbacks')
    create_alignment_dialog_layout_callbacks = context.get('create_alignment_dialog_layout_callbacks')
    create_alignment_mesh_diagnostics_callbacks = context.get('create_alignment_mesh_diagnostics_callbacks')
    defer_original_texture_preview = context.get('defer_original_texture_preview')
    dialog = context.get('dialog')
    embedded_alignment_builder = bool(context.get('embedded_alignment_builder'))
    float = context.get('float')
    globals = context.get('globals')
    locals = context.get('locals')
    max = context.get('max')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    object = context.get('object')
    original_texture_preview_state = context.get('original_texture_preview_state')
    self = context.get('self')
    str = context.get('str')
    texture_uv_global_transform_state = context.get('texture_uv_global_transform_state') or {}
    tuple = context.get('tuple')
    value = context.get('value')

    alignment_grid_visible_settings_key = "ui/mesh_alignment/grid_visible"
    root_layout = QVBoxLayout(dialog)
    alignment_control_min_width = 420 if embedded_alignment_builder else 640
    alignment_control_content_min_width = 0 if embedded_alignment_builder else 700
    mesh_edit_control_min_width = 300 if embedded_alignment_builder else 300
    mesh_edit_control_content_min_width = 0 if embedded_alignment_builder else 300
    mesh_edit_control_max_width = 340 if embedded_alignment_builder else 340
    alignment_preview_min_width = 420
    main_splitter = QSplitter(Qt.Horizontal, dialog)
    main_splitter.setChildrenCollapsible(False)
    controls_panel = QWidget(dialog)
    controls_panel.setObjectName("MeshAlignmentStickyControlPanel")
    controls_panel.setMinimumWidth(alignment_control_min_width)
    controls_panel.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Expanding)
    content_container = controls_panel
    content_container.setMinimumWidth(alignment_control_content_min_width)
    content_container.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Expanding)
    layout = QVBoxLayout(content_container)
    layout.setContentsMargins(4, 3, 4, 3)
    layout.setSpacing(3)
    preview_panel = QWidget(dialog)
    preview_panel.setMinimumWidth(alignment_preview_min_width)
    preview_panel_layout = QVBoxLayout(preview_panel)
    # The splitter already separates this column, so the default frame margins
    # and row spacing are height the editor could be using instead.
    preview_panel_layout.setContentsMargins(0, 0, 0, 0)
    preview_panel_layout.setSpacing(3)
    preview_header = QVBoxLayout()
    preview_header.setContentsMargins(0, 0, 0, 0)
    preview_header.setSpacing(3)
    preview_action_row = QHBoxLayout()
    preview_action_row.setContentsMargins(0, 0, 0, 0)
    preview_action_row.setSpacing(5)
    legacy_preview_controls_widget, preview_controls_row, legacy_preview_camera_widget, preview_camera_row = _legacy_preview_rows(QWidget, QHBoxLayout, preview_panel)
    alignment_preview_control_text = _alignment_preview_control_text_helper()
    alignment_preview_render_control_text = _alignment_preview_render_control_text_helper()
    alignment_preview_default_help = _alignment_preview_help_presentation_helper(d3d11_active=False)
    preview_title_label = QLabel(alignment_preview_control_text["title"])
    preview_title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    preview_action_row.addWidget(preview_title_label, 1)
    clear_alignment_selection_button = QPushButton(alignment_preview_control_text["clear_selection"])
    clear_alignment_selection_button.setObjectName("MeshAlignmentGlobalClearSelectionButton")
    clear_alignment_selection_button.setToolTip(alignment_preview_control_text["clear_selection_tooltip"])
    clear_alignment_selection_button.setMinimumWidth(0)
    clear_alignment_selection_button.setMaximumWidth(128)
    preview_action_row.addWidget(clear_alignment_selection_button)
    custom_icon_control_text = _custom_item_icon_control_text_helper()
    generate_alignment_icon_button = QPushButton(custom_icon_control_text["generate_preview_button"])
    generate_alignment_icon_button.setObjectName("MeshAlignmentGenerateIconFromPreviewButton")
    generate_alignment_icon_button.setToolTip(custom_icon_control_text["generate_preview_tooltip"])
    generate_alignment_icon_button.setMinimumWidth(0)
    generate_alignment_icon_button.setMaximumWidth(128)
    preview_action_row.addWidget(generate_alignment_icon_button)
    preview_header.addLayout(preview_action_row)
    alignment_d3d11_available = True
    preview_renderer_combo = QComboBox()
    _populate_combo_options_helper(preview_renderer_combo, PREVIEW_RENDERER_OPTIONS)
    preview_renderer_combo.setToolTip(alignment_preview_control_text["renderer_tooltip"])
    preview_renderer_combo.setMinimumWidth(0)
    preview_renderer_combo.setMinimumContentsLength(16)
    preview_renderer_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    preview_renderer_label = QLabel(alignment_preview_control_text["renderer_label"])
    preview_renderer_label.setVisible(False)
    preview_renderer_combo.setVisible(False)
    preview_mode_combo = QComboBox()
    _populate_combo_options_helper(preview_mode_combo, PREVIEW_MODE_OPTIONS)
    preview_mode_combo.setToolTip(alignment_preview_control_text["preview_mode_tooltip"])
    preview_controls_row.addStretch(1)
    preview_controls_row.addWidget(QLabel(alignment_preview_control_text["preview_mode_label"]))
    preview_mode_combo.setMinimumWidth(0)
    preview_mode_combo.setMinimumContentsLength(12)
    preview_mode_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    preview_mode_combo.setMaximumWidth(220)
    preview_controls_row.addWidget(preview_mode_combo)
    # The original reference is always locked, so this only ever read back a
    # permanently checked, permanently disabled box. Keep the widget for the
    # callbacks that still read it, but take it out of the row.
    overlay_original_locked_checkbox = QCheckBox(
        alignment_preview_control_text["overlay_original_locked"], preview_panel
    )
    overlay_original_locked_checkbox.setObjectName("MeshAlignmentOverlayOriginalLockedCheckbox")
    overlay_original_locked_checkbox.setChecked(True)
    overlay_original_locked_checkbox.setEnabled(False)
    overlay_original_locked_checkbox.setToolTip(alignment_preview_control_text["overlay_original_locked_tooltip"])
    overlay_original_locked_checkbox.setVisible(False)
    preview_controls_row.addWidget(_control_group_separator(QFrame, preview_panel))
    preview_grid_checkbox = QCheckBox(alignment_preview_control_text["grid"])
    preview_grid_checkbox.setObjectName("MeshAlignmentGridVisibleCheckbox")
    preview_grid_checkbox.setChecked(
        read_bool_setting(self.settings, alignment_grid_visible_settings_key, True)
    )
    preview_grid_checkbox.setToolTip(alignment_preview_control_text["grid_tooltip"])
    preview_controls_row.addWidget(preview_grid_checkbox)
    preview_gizmo_checkbox = QCheckBox(alignment_preview_control_text["gizmo"])
    preview_gizmo_checkbox.setObjectName("MeshAlignmentGizmoVisibleCheckbox")
    preview_gizmo_checkbox.setChecked(True)
    preview_gizmo_checkbox.setToolTip(alignment_preview_control_text["gizmo_tooltip"])
    preview_controls_row.addWidget(preview_gizmo_checkbox)
    preview_part_pick_checkbox = QCheckBox(alignment_preview_control_text["part_pick"])
    preview_part_pick_checkbox.setObjectName("MeshAlignmentPartPickCheckbox")
    preview_part_pick_checkbox.setChecked(False)
    preview_part_pick_checkbox.setToolTip(alignment_preview_control_text["part_pick_tooltip"])
    preview_controls_row.addWidget(preview_part_pick_checkbox)
    preview_mesh_edit_checkbox = QCheckBox("Edit Mesh")
    preview_mesh_edit_checkbox.setObjectName("MeshEditModeCheckbox")
    preview_mesh_edit_checkbox.setChecked(False)
    preview_mesh_edit_checkbox.setToolTip("Enable viewport mesh editing tools for the current replacement preview.")
    preview_controls_row.addWidget(preview_mesh_edit_checkbox)
    mesh_edit_enabled_checkbox = preview_mesh_edit_checkbox
    preview_controls_row.addWidget(_control_group_separator(QFrame, preview_panel))
    preview_mesh_view_combo = QComboBox()
    preview_mesh_view_combo.setObjectName("MeshAlignmentViewportDisplayModeCombo")
    _populate_combo_options_helper(
        preview_mesh_view_combo,
        MESH_PREVIEW_DISPLAY_MODE_OPTIONS,
    )
    mesh_view_index = preview_mesh_view_combo.findData(
        MESH_PREVIEW_DEFAULT_DISPLAY_MODE
    )
    preview_mesh_view_combo.setCurrentIndex(max(0, mesh_view_index))
    preview_mesh_view_combo.setToolTip(
        alignment_preview_control_text["mesh_view_tooltip"]
    )
    preview_mesh_view_combo.setMinimumWidth(0)
    preview_mesh_view_combo.setMinimumContentsLength(12)
    preview_mesh_view_combo.setSizeAdjustPolicy(
        QComboBox.AdjustToMinimumContentsLengthWithIcon
    )
    preview_mesh_view_combo.setMaximumWidth(190)
    preview_controls_row.addWidget(
        QLabel(alignment_preview_control_text["mesh_view_label"])
    )
    preview_controls_row.addWidget(preview_mesh_view_combo)
    mesh_dotnet_experiment_button = QPushButton(".NET", preview_panel)
    mesh_dotnet_experiment_button.setObjectName("MeshAlignmentDotNetExperimentButton")
    mesh_dotnet_experiment_button.setToolTip("Diagnostics-only .NET editor launch; Edit Mesh opens .NET automatically when available.")
    mesh_dotnet_experiment_button.setMinimumWidth(0)
    mesh_dotnet_experiment_button.setMaximumWidth(64)
    mesh_dotnet_experiment_button.setEnabled(False)
    mesh_dotnet_experiment_button.setVisible(False)
    preview_controls_row.addWidget(mesh_dotnet_experiment_button)
    hovered_source_part = {"index": -1}
    alignment_d3d11_view_mode_combo = QComboBox()
    _populate_combo_options_helper(
        alignment_d3d11_view_mode_combo,
        DOTNET_PREVIEW_VIEW_MODE_OPTIONS,
    )
    d3d11_view_index = alignment_d3d11_view_mode_combo.findData(
        self._current_model_preview_render_settings().d3d11_view_mode
    )
    alignment_d3d11_view_mode_combo.setCurrentIndex(max(0, d3d11_view_index))
    alignment_d3d11_view_mode_combo.setToolTip(alignment_preview_control_text["dotnet_view_tooltip"])
    alignment_d3d11_view_mode_combo.setMinimumWidth(0)
    alignment_d3d11_view_mode_combo.setMinimumContentsLength(14)
    alignment_d3d11_view_mode_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    alignment_d3d11_view_mode_combo.setMaximumWidth(190)
    preview_controls_row.addWidget(QLabel(alignment_preview_control_text["dotnet_view_label"]))
    preview_controls_row.addWidget(alignment_d3d11_view_mode_combo)
    preview_controls_row.addWidget(_control_group_separator(QFrame, preview_panel))
    alignment_preview_settings_button = QPushButton(alignment_preview_control_text["settings_button"])
    alignment_preview_settings_button.setToolTip(alignment_preview_default_help.settings_tooltip)
    alignment_use_global_preview_button = QPushButton(alignment_preview_control_text["use_global"], preview_panel)
    alignment_use_global_preview_button.setVisible(False)
    alignment_use_global_preview_button.setToolTip(alignment_preview_control_text["use_global_tooltip"])
    for preview_button in (alignment_preview_settings_button, alignment_use_global_preview_button):
        preview_button.setMinimumWidth(0)
    alignment_preview_settings_button.setMaximumWidth(190)
    preview_controls_row.addWidget(alignment_preview_settings_button)
    preview_controls_row.addWidget(alignment_use_global_preview_button)
    preview_header.addWidget(legacy_preview_controls_widget)
    texture_uv_control_text = _texture_uv_control_text_helper()
    setup_texture_flip_u_checkbox = QCheckBox(texture_uv_control_text["flip_u_label"])
    setup_texture_flip_u_checkbox.setObjectName("MeshAlignmentSetupTextureFlipUCheckbox")
    setup_texture_flip_u_checkbox.setToolTip(texture_uv_control_text["setup_flip_u_tooltip"])
    setup_texture_flip_u_checkbox.setChecked(bool(texture_uv_global_transform_state.get("flip_u")))
    setup_texture_flip_v_checkbox = QCheckBox(texture_uv_control_text["flip_v_label"])
    setup_texture_flip_v_checkbox.setObjectName("MeshAlignmentSetupTextureFlipVCheckbox")
    setup_texture_flip_v_checkbox.setToolTip(texture_uv_control_text["setup_flip_v_tooltip"])
    setup_texture_flip_v_checkbox.setChecked(bool(texture_uv_global_transform_state.get("flip_v")))
    preview_camera_row.addWidget(setup_texture_flip_u_checkbox)
    preview_camera_row.addWidget(setup_texture_flip_v_checkbox)
    preview_camera_row.addStretch(1)
    preview_camera_row.addWidget(QLabel(alignment_preview_control_text["camera_label"]))

    (
        camera_front_button,
        camera_left_button,
        camera_right_button,
        camera_back_button,
        camera_top_button,
        camera_bottom_button,
        camera_yaw_left_button,
        camera_yaw_right_button,
        camera_reset_button,
    ) = tuple(
        _alignment_camera_button_helper(label, object_name, tooltip)
        for label, object_name, tooltip in _alignment_preview_camera_button_specs_helper()
    )
    for camera_button in (
        camera_front_button,
        camera_left_button,
        camera_right_button,
        camera_back_button,
        camera_top_button,
        camera_bottom_button,
        camera_yaw_left_button,
        camera_yaw_right_button,
        camera_reset_button,
    ):
        preview_camera_row.addWidget(camera_button)
    preview_header.addWidget(legacy_preview_camera_widget)
    setattr(
        dialog,
        "_mesh_editor_legacy_preview_rows",
        (legacy_preview_controls_widget, legacy_preview_camera_widget),
    )
    preview_panel_layout.addLayout(preview_header)

    alignment_renderer_scope_label = QLabel(alignment_preview_control_text["renderer_scope"])
    alignment_renderer_scope_label.setObjectName("HintLabel")
    alignment_renderer_scope_label.setWordWrap(True)
    alignment_renderer_scope_label.setVisible(False)
    preview_panel_layout.addWidget(alignment_renderer_scope_label)

    preview_render_settings = _alignment_lit_render_settings_helper(
        self._current_model_preview_render_settings(),
        self._current_model_preview_render_settings(),
    )
    if (
        modify_original_clone_mode
        and defer_original_texture_preview
        and not _original_texture_preview_material_preview_enabled_helper(modify_original_clone_mode, original_texture_preview_state)
    ):
        preview_render_settings.disable_all_support_maps = True
        preview_render_settings.disable_normal_map = True
        preview_render_settings.disable_material_map = True
        preview_render_settings.disable_height_map = True
    preview_render_controls_widget = QWidget(preview_panel)
    preview_render_controls_widget.setVisible(False)
    preview_render_controls = QHBoxLayout(preview_render_controls_widget)
    preview_render_controls.setContentsMargins(0, 0, 0, 0)
    preview_render_controls.setSpacing(4)
    preview_visible_mode_combo = QComboBox()
    for mode in MODEL_PREVIEW_VISIBLE_TEXTURE_MODES:
        preview_visible_mode_combo.addItem(MODEL_PREVIEW_VISIBLE_TEXTURE_MODE_LABELS.get(mode, mode), mode)
    visible_index = preview_visible_mode_combo.findData(preview_render_settings.visible_texture_mode)
    preview_visible_mode_combo.setCurrentIndex(max(0, visible_index))
    preview_visible_mode_combo.setToolTip(alignment_preview_render_control_text["visible_tooltip"])
    preview_visible_mode_combo.setMinimumWidth(0)
    preview_visible_mode_combo.setMinimumContentsLength(10)
    preview_visible_mode_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    preview_render_mode_combo = QComboBox()
    for mode in MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODES:
        preview_render_mode_combo.addItem(MODEL_PREVIEW_RENDER_DIAGNOSTIC_MODE_LABELS.get(mode, mode), mode)
    render_index = preview_render_mode_combo.findData(preview_render_settings.render_diagnostic_mode)
    preview_render_mode_combo.setCurrentIndex(max(0, render_index))
    preview_render_mode_combo.setToolTip(alignment_preview_render_control_text["render_tooltip"])
    preview_render_mode_combo.setMinimumWidth(0)
    preview_render_mode_combo.setMinimumContentsLength(8)
    preview_render_mode_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    preview_disable_tint_checkbox = QCheckBox(alignment_preview_render_control_text["disable_tint"])
    preview_disable_tint_checkbox.setChecked(bool(preview_render_settings.disable_tint))
    preview_disable_tint_checkbox.setToolTip(alignment_preview_render_control_text["disable_tint_tooltip"])
    preview_disable_brightness_checkbox = QCheckBox(alignment_preview_render_control_text["disable_brightness"])
    preview_disable_brightness_checkbox.setChecked(bool(preview_render_settings.disable_brightness))
    preview_disable_brightness_checkbox.setToolTip(alignment_preview_render_control_text["disable_brightness_tooltip"])
    preview_disable_uv_scale_checkbox = QCheckBox(alignment_preview_render_control_text["disable_uv_scale"])
    preview_disable_uv_scale_checkbox.setChecked(bool(preview_render_settings.disable_uv_scale))
    preview_disable_uv_scale_checkbox.setToolTip(alignment_preview_render_control_text["disable_uv_scale_tooltip"])
    preview_support_maps_checkbox = QCheckBox(alignment_preview_render_control_text["support_maps"])
    preview_support_maps_checkbox.setChecked(not bool(preview_render_settings.disable_all_support_maps))
    preview_support_maps_checkbox.setToolTip(alignment_preview_render_control_text["support_maps_tooltip"])

    preview_depth_spin = QDoubleSpinBox()
    preview_depth_spin.setRange(0.0, 1.0)
    preview_depth_spin.setDecimals(2)
    preview_depth_spin.setSingleStep(0.05)
    preview_depth_spin.setValue(float(preview_render_settings.height_effect_max))
    preview_depth_spin.setToolTip(alignment_preview_render_control_text["depth_tooltip"])
    preview_depth_spin.setMaximumWidth(74)
    preview_shine_spin = QDoubleSpinBox()
    preview_shine_spin.setRange(0.0, 1.0)
    preview_shine_spin.setDecimals(2)
    preview_shine_spin.setSingleStep(0.02)
    preview_shine_spin.setValue(float(preview_render_settings.specular_max))
    preview_shine_spin.setToolTip(alignment_preview_render_control_text["shine_tooltip"])
    preview_shine_spin.setMaximumWidth(74)
    preview_rough_spin = QDoubleSpinBox()
    preview_rough_spin.setRange(0.0, 1.0)
    preview_rough_spin.setDecimals(2)
    preview_rough_spin.setSingleStep(0.05)
    preview_rough_spin.setValue(_rough_control_value_from_settings(preview_render_settings))
    preview_rough_spin.setToolTip(alignment_preview_render_control_text["rough_tooltip"])
    preview_rough_spin.setMaximumWidth(74)
    preview_render_controls.addWidget(preview_disable_tint_checkbox)
    preview_render_controls.addWidget(preview_disable_brightness_checkbox)
    preview_render_controls.addWidget(preview_disable_uv_scale_checkbox)
    preview_render_controls.addWidget(preview_support_maps_checkbox)
    preview_render_controls.addWidget(QLabel(alignment_preview_render_control_text["depth_label"]))
    preview_render_controls.addWidget(preview_depth_spin)
    preview_render_controls.addWidget(QLabel(alignment_preview_render_control_text["shine_label"]))
    preview_render_controls.addWidget(preview_shine_spin)
    preview_render_controls.addWidget(QLabel(alignment_preview_render_control_text["rough_label"]))
    preview_render_controls.addWidget(preview_rough_spin)
    preview_panel_layout.addWidget(preview_render_controls_widget)
    classic_mesh_edit_toolbar = QFrame(preview_panel)
    classic_mesh_edit_toolbar.setObjectName("ClassicMeshEditPreviewToolbar")
    classic_mesh_edit_toolbar.setVisible(False)
    classic_mesh_edit_toolbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    classic_mesh_edit_toolbar_layout = QVBoxLayout(classic_mesh_edit_toolbar)
    classic_mesh_edit_toolbar_layout.setContentsMargins(4, 3, 4, 3)
    classic_mesh_edit_toolbar_layout.setSpacing(3)
    preview_panel_layout.addWidget(classic_mesh_edit_toolbar)
    preview_splitter = QSplitter(Qt.Horizontal, preview_panel)
    original_preview_container = QWidget(preview_splitter)
    original_preview_layout = QVBoxLayout(original_preview_container)
    original_preview_layout.setContentsMargins(0, 0, 0, 0)
    original_preview_layout.addWidget(QLabel(alignment_preview_render_control_text["original_reference_label"]))
    original_dialog_preview = NativePreviewPanel(
        alignment_preview_render_control_text["original_reference_description"],
        theme_key=self.current_theme_key,
    )
    original_dialog_preview.setMinimumSize(220, 260)
    original_dialog_preview.set_render_settings(preview_render_settings)
    original_dialog_preview.set_use_textures(True)
    original_dialog_preview.set_high_quality_textures(True)
    original_dialog_preview.set_alignment_guides_visible(True)
    original_preview_layout.addWidget(original_dialog_preview, 1)
    replacement_preview_container = QWidget(preview_splitter)
    replacement_preview_layout = QVBoxLayout(replacement_preview_container)
    replacement_preview_layout.setContentsMargins(0, 0, 0, 0)
    replacement_preview_layout.addWidget(QLabel(alignment_preview_render_control_text["replacement_preview_label"]))
    static_dialog_preview = NativePreviewPanel(
        alignment_preview_render_control_text["replacement_preview_description"],
        theme_key=self.current_theme_key,
    )
    static_dialog_preview.setMinimumSize(240, 260)
    static_dialog_preview.set_render_settings(preview_render_settings)
    static_dialog_preview.set_use_textures(True)
    static_dialog_preview.set_high_quality_textures(True)
    static_dialog_preview.set_alignment_guides_visible(True)
    static_dialog_preview.set_alignment_editing_enabled(True)
    replacement_preview_layout.addWidget(static_dialog_preview, 1)
    preview_splitter.addWidget(original_preview_container)
    preview_splitter.addWidget(replacement_preview_container)
    preview_splitter.setChildrenCollapsible(False)
    preview_splitter.setCollapsible(0, False)
    preview_splitter.setCollapsible(1, False)
    preview_splitter.setStretchFactor(0, 1)
    preview_splitter.setStretchFactor(1, 1)
    preview_splitter.setSizes([520, 520])
    overlay_dialog_preview = NativePreviewPanel("Overlay preview.", theme_key=self.current_theme_key)
    overlay_dialog_preview.setMinimumSize(300, 280)
    overlay_dialog_preview.set_render_settings(preview_render_settings)
    overlay_dialog_preview.set_use_textures(True)
    overlay_dialog_preview.set_high_quality_textures(True)
    overlay_dialog_preview.set_alignment_guides_visible(True)
    overlay_dialog_preview.set_alignment_editing_enabled(True)
    replacement_only_preview = NativePreviewPanel("Replacement preview.", theme_key=self.current_theme_key)
    replacement_only_preview.setMinimumSize(300, 280)
    replacement_only_preview.set_render_settings(preview_render_settings)
    replacement_only_preview.set_use_textures(True)
    replacement_only_preview.set_high_quality_textures(True)
    replacement_only_preview.set_alignment_guides_visible(True)
    replacement_only_preview.set_alignment_editing_enabled(True)
    # These panels remain as non-visible state/compatibility adapters for old
    # callbacks.  The authoring Vortice host below is the sole visual surface.
    preview_splitter.setVisible(False)
    overlay_dialog_preview.setVisible(False)
    replacement_only_preview.setVisible(False)

    def _get_preview_render_settings():
        return preview_render_settings

    def _set_preview_render_settings(value) -> None:
        nonlocal preview_render_settings
        preview_render_settings = value

    alignment_d3d11_preview_page = QWidget(preview_panel)
    alignment_d3d11_preview_layout = QVBoxLayout(alignment_d3d11_preview_page)
    alignment_d3d11_preview_layout.setContentsMargins(0, 0, 0, 0)
    alignment_d3d11_preview_layout.setSpacing(3)
    alignment_d3d11_preview_host = DotNetPreviewHostFrame(
        alignment_d3d11_preview_page,
        profile=DotNetPreviewProfile.AUTHORING,
        terminate_on_close=True,
    )
    alignment_d3d11_preview_host.setObjectName("AlignmentDotNetVorticePreviewHost")
    # Let winId() create the native handle after the builder is visible; eager
    # native child creation can hard-crash when the alignment dialog is shown.
    alignment_d3d11_preview_host.setMinimumSize(300, 280)
    alignment_d3d11_preview_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    alignment_d3d11_preview_host.set_viewport_display_mode(
        str(
            preview_mesh_view_combo.currentData()
            or MESH_PREVIEW_DEFAULT_DISPLAY_MODE
        )
    )
    # The Mesh Editor starts this prewarm after its authoritative edit-session
    # id is known.  Starting it here would bind the resident authoring helper
    # to a throwaway session before the real package can supersede it.
    alignment_d3d11_preview_host.setProperty(
        "cdmwPreviewPrewarmCacheRoot",
        str(self._native_preview_package_cache_root()),
    )
    alignment_d3d11_split_ratio_settings_key = "ui/mesh_alignment/d3d11_side_by_side_split_ratio"
    try:
        alignment_d3d11_preview_host.set_side_by_side_split_ratio(
            float(self.settings.value(alignment_d3d11_split_ratio_settings_key, 0.5) or 0.5)
        )
    except (TypeError, ValueError, AttributeError):
        alignment_d3d11_preview_host.set_side_by_side_split_ratio(0.5)

    def _remember_alignment_d3d11_split_ratio(payload: object) -> None:
        if not isinstance(payload, dict) or str(payload.get("event", "") or "") != "side_by_side_split":
            return
        try:
            ratio = alignment_d3d11_preview_host.remember_side_by_side_split_ratio(float(payload.get("ratio", 0.5) or 0.5))
            self.settings.setValue(alignment_d3d11_split_ratio_settings_key, ratio)
        except (TypeError, ValueError, AttributeError):
            pass

    alignment_d3d11_preview_host.native_event_received.connect(_remember_alignment_d3d11_split_ratio)
    alignment_d3d11_preview_legend_label = QLabel(alignment_preview_control_text["d3d11_legend"])
    alignment_d3d11_preview_legend_label.setObjectName("HintLabel")
    alignment_d3d11_preview_legend_label.setWordWrap(False)
    alignment_d3d11_preview_legend_label.setToolTip(alignment_preview_control_text["d3d11_legend_tooltip"])
    alignment_d3d11_preview_status_label = QLabel(alignment_preview_control_text["d3d11_waiting_status"])
    alignment_d3d11_preview_status_label.setObjectName("HintLabel")
    alignment_d3d11_preview_status_label.setAlignment(Qt.AlignCenter)
    alignment_d3d11_preview_status_label.setWordWrap(False)
    # One line of progress text: the spare height above it belongs to the editor.
    alignment_d3d11_preview_status_label.setMinimumHeight(18)
    alignment_d3d11_preview_status_label.setMaximumHeight(24)
    alignment_d3d11_preview_status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    alignment_d3d11_loading_spinner_label = QLabel("")
    alignment_d3d11_loading_spinner_label.setObjectName("AlignmentD3D11LoadingSpinner")
    alignment_d3d11_loading_spinner_label.setAlignment(Qt.AlignCenter)
    alignment_d3d11_loading_spinner_label.setTextFormat(Qt.RichText)
    alignment_d3d11_loading_spinner_label.setFixedSize(30, 22)
    alignment_d3d11_loading_spinner_label.setVisible(False)
    alignment_d3d11_status_row = QHBoxLayout()
    alignment_d3d11_status_row.setContentsMargins(0, 0, 0, 0)
    alignment_d3d11_status_row.setSpacing(4)
    alignment_d3d11_status_row.addStretch(1)
    alignment_d3d11_status_row.addWidget(alignment_d3d11_loading_spinner_label)
    alignment_d3d11_status_row.addWidget(alignment_d3d11_preview_status_label)
    alignment_d3d11_status_row.addStretch(1)
    alignment_d3d11_preview_layout.addWidget(alignment_d3d11_preview_legend_label)
    alignment_d3d11_preview_layout.addWidget(alignment_d3d11_preview_host, 1)
    alignment_d3d11_preview_layout.addLayout(alignment_d3d11_status_row)
    alignment_d3d11_status_timer = QTimer(dialog)
    alignment_d3d11_status_timer.setInterval(250)
    alignment_d3d11_loading_timer = QTimer(dialog)
    alignment_d3d11_loading_timer.setInterval(120)
    alignment_d3d11_loading_state = _alignment_d3d11_loading_initial_state_helper()
    alignment_d3d11_fast_reload_interval_ms = 180
    alignment_d3d11_package_reload_interval_ms = 560
    alignment_d3d11_reload_stuck_timeout_s = 6.0
    alignment_d3d11_reload_timer = QTimer(dialog)
    alignment_d3d11_reload_timer.setSingleShot(True)
    alignment_d3d11_reload_timer.setInterval(alignment_d3d11_fast_reload_interval_ms)

    alignment_d3d11_state: Dict[str, object] = {
        "request_id": 0,
        "thread": None,
        "worker": None,
        "process": None,
        "active_package": None,
        "status_file": None,
        "status_signature": (0, 0),
        "status_payload_text": "",
        "pending_model": None,
        "pending_label": "",
        "pending_display_mode": "",
        "pending_reason": "",
        "pending_package_quality": "",
        "queued_model": None,
        "queued_label": "",
        "queued_display_mode": "",
        "queued_reason": "",
        "queued_transform_generation": 0,
        "queued_package_quality": "",
        "request_drag_generation": 0,
        "request_drag_generations": {},
        "request_transform_generation": 0,
        "request_transform_generations": {},
        "active_package_request_id": 0,
        "active_package_display_mode": "",
        "active_package_quality": "",
        "active_package_cache_key": "",
        "request_display_modes": {},
        "request_package_qualities": {},
        "request_reasons": {},
        "request_cache_keys": {},
        "prepare_ms": 0.0,
        "package_ms": 0.0,
        "package_quality": "normal",
        "package_cache": OrderedDict(),
        "package_cache_limit": 12,
        "last_cache_event": "miss",
        "last_cache_reason": "geometry",
        "last_rebuild_reason": "geometry",
        "next_rebuild_reason": "",
        "pending_fast_transform": None,
        "pending_part_fast_transforms": {},
        "preview_loaded": False,
        "preview_pipeline_stage": "idle",
        "fast_geometry_loaded": False,
        "archive_parity_ready": False, "material_complete_preview_seen": False,
        "archive_parity_upgrade_queued": False,
        "resources_loaded": False,
        "stale_reload_restart_count": 0,
        "original_texture_worker_request_id": 0,
        "original_texture_thread": None,
        "original_texture_worker": None,
        "pending_process_package": None,
        "pending_process_retry_count": 0,
        "loading_started_at": 0.0,
        "loading_percent": 0,
        "loading_stage": "",
        "loading_message": "",
        "session_key": alignment_dialog_key,
        "mesh_editor_view_state_reset_generation": alignment_d3d11_view_state_reset_generation,
        "source_to_d3d11_ids": {},
        "d3d11_id_to_source_indices": {},
    }
    alignment_d3d11_view_state: Dict[str, object] = {}
    alignment_preview_mode_view_states: Dict[str, object] = {}
    alignment_preview_mode_state = _alignment_preview_mode_initial_state_helper(preview_mode_combo.currentData())
    alignment_preview_view_sync = _alignment_preview_view_sync_initial_state_helper()
    mesh_editor_diagnostics_state = _mesh_editor_diagnostics_initial_state_helper()

    alignment_mesh_diagnostics_callbacks = create_alignment_mesh_diagnostics_callbacks({**context, **globals(), **locals()})
    _refresh_mesh_editor_diagnostics = alignment_mesh_diagnostics_callbacks._refresh_mesh_editor_diagnostics
    _copy_mesh_editor_diagnostics = alignment_mesh_diagnostics_callbacks._copy_mesh_editor_diagnostics

    alignment_d3d11_loading_callbacks = create_alignment_d3d11_loading_callbacks({**context, **globals(), **locals()})
    _tick_alignment_d3d11_loading_spinner = alignment_d3d11_loading_callbacks._tick_alignment_d3d11_loading_spinner
    _set_alignment_d3d11_loading = alignment_d3d11_loading_callbacks._set_alignment_d3d11_loading
    _set_alignment_d3d11_progress = alignment_d3d11_loading_callbacks._set_alignment_d3d11_progress
    _set_alignment_d3d11_pipeline_stage = alignment_d3d11_loading_callbacks._set_alignment_d3d11_pipeline_stage
    _reset_alignment_d3d11_request_state = alignment_d3d11_loading_callbacks._reset_alignment_d3d11_request_state
    _alignment_d3d11_request_active = alignment_d3d11_loading_callbacks._alignment_d3d11_request_active
    _alignment_d3d11_live_frame_available = alignment_d3d11_loading_callbacks._alignment_d3d11_live_frame_available
    _alignment_d3d11_host_ready = alignment_d3d11_loading_callbacks._alignment_d3d11_host_ready
    _alignment_d3d11_loading_stuck = alignment_d3d11_loading_callbacks._alignment_d3d11_loading_stuck
    _clear_stuck_alignment_d3d11_loading = alignment_d3d11_loading_callbacks._clear_stuck_alignment_d3d11_loading
    _handle_alignment_d3d11_view_state_payload = alignment_d3d11_loading_callbacks._handle_alignment_d3d11_view_state_payload
    _alignment_d3d11_saved_view_state = alignment_d3d11_loading_callbacks._alignment_d3d11_saved_view_state
    _sync_alignment_preview_view_state = alignment_d3d11_loading_callbacks._sync_alignment_preview_view_state
    _alignment_d3d11_camera_active = alignment_d3d11_loading_callbacks._alignment_d3d11_camera_active
    _alignment_active_qt_camera_widgets = alignment_d3d11_loading_callbacks._alignment_active_qt_camera_widgets
    _alignment_current_camera_state = alignment_d3d11_loading_callbacks._alignment_current_camera_state
    _apply_alignment_camera_state = alignment_d3d11_loading_callbacks._apply_alignment_camera_state
    _save_alignment_preview_mode_view_state = alignment_d3d11_loading_callbacks._save_alignment_preview_mode_view_state
    _restore_alignment_preview_mode_view_state = alignment_d3d11_loading_callbacks._restore_alignment_preview_mode_view_state
    _set_alignment_camera = alignment_d3d11_loading_callbacks._set_alignment_camera
    _nudge_alignment_camera = alignment_d3d11_loading_callbacks._nudge_alignment_camera

    def _handle_alignment_dotnet_state(state: str, message: str) -> None:
        alignment_d3d11_state["process"] = alignment_d3d11_preview_host.controller.process
        alignment_d3d11_preview_status_label.setText(str(message or ".NET/Vortice Preview"))
        if str(state) == "ready":
            alignment_d3d11_state["preview_loaded"] = True
            alignment_d3d11_state["resources_loaded"] = True
            _set_alignment_d3d11_progress(100, ".NET/Vortice Preview ready.", active=False)
        elif str(state) == "error":
            alignment_d3d11_state["preview_loaded"] = False
            _set_alignment_d3d11_loading(False, str(message or ".NET/Vortice Preview failed."))

    alignment_d3d11_preview_host.controller.state_changed.connect(_handle_alignment_dotnet_state)

    camera_front_button.clicked.connect(lambda _checked=False: _set_alignment_camera(0.0, 0.0))
    camera_left_button.clicked.connect(lambda _checked=False: _set_alignment_camera(-90.0, 0.0))
    camera_right_button.clicked.connect(lambda _checked=False: _set_alignment_camera(90.0, 0.0))
    camera_back_button.clicked.connect(lambda _checked=False: _set_alignment_camera(180.0, 0.0))
    camera_top_button.clicked.connect(lambda _checked=False: _set_alignment_camera(0.0, -89.0))
    camera_bottom_button.clicked.connect(lambda _checked=False: _set_alignment_camera(0.0, 89.0))
    camera_yaw_left_button.clicked.connect(lambda _checked=False: _nudge_alignment_camera(-15.0, 0.0))
    camera_yaw_right_button.clicked.connect(lambda _checked=False: _nudge_alignment_camera(15.0, 0.0))
    camera_reset_button.clicked.connect(lambda _checked=False: _set_alignment_camera(-35.0, 20.0))

    def _preview_part_pick_toggled(checked: bool = False) -> None:
        if bool(checked):
            _sync_highlight_sets()
            return
        _clear_all_part_selections()

    def _preview_grid_toggled(checked: bool = False) -> None:
        try:
            self.settings.setValue(alignment_grid_visible_settings_key, bool(checked))
        except (AttributeError, RuntimeError):
            pass
        # The resident overlay flags ride along with the highlight state, so
        # this reaches both panes through the same update.
        _sync_highlight_sets()

    preview_grid_checkbox.toggled.connect(_preview_grid_toggled)
    preview_gizmo_checkbox.toggled.connect(lambda *_args: _sync_highlight_sets())
    preview_part_pick_checkbox.toggled.connect(_preview_part_pick_toggled)
    preview_stack = QStackedWidget(preview_panel)
    preview_stack.addWidget(alignment_d3d11_preview_page)
    preview_stack.setCurrentWidget(alignment_d3d11_preview_page)
    preview_panel_layout.addWidget(preview_stack, 1)
    preview_help = QLabel(alignment_preview_default_help.text)
    preview_help.setWordWrap(False)
    preview_help.setMaximumHeight(24)
    preview_help.setObjectName("HintLabel")
    preview_help.setToolTip(alignment_preview_default_help.tooltip)
    preview_performance_initial_status = _alignment_preview_initial_performance_status_helper()
    preview_performance_label = QLabel(preview_performance_initial_status.text)
    preview_performance_label.setObjectName("HintLabel")
    preview_performance_label.setWordWrap(False)
    preview_performance_label.setMaximumHeight(24)
    preview_performance_label.setToolTip(preview_performance_initial_status.tooltip)
    # Both hints are one line each. Stacking them cost the editor a whole row of
    # height for text that fits side by side. Neither label wraps, so their size
    # hint is the full string: an ignored horizontal policy keeps that hint from
    # raising the dialog's minimum width, and the tooltips carry the full text
    # when a narrow panel clips them.
    preview_help.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    preview_performance_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    preview_performance_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    preview_status_row = QHBoxLayout()
    preview_status_row.setContentsMargins(0, 0, 0, 0)
    preview_status_row.setSpacing(12)
    preview_status_row.addWidget(preview_help, 3)
    preview_status_row.addWidget(preview_performance_label, 2)
    preview_panel_layout.addLayout(preview_status_row)

    alignment_dialog_layout_state = _alignment_dialog_layout_initial_state_helper()
    previous_dialog_resize_event = dialog.resizeEvent
    alignment_dialog_layout_callbacks = create_alignment_dialog_layout_callbacks({**context, **globals(), **locals()})
    _set_preview_performance_status = alignment_dialog_layout_callbacks._set_preview_performance_status
    _apply_alignment_dialog_responsive_layout = alignment_dialog_layout_callbacks._apply_alignment_dialog_responsive_layout
    _responsive_dialog_resize_event = alignment_dialog_layout_callbacks._responsive_dialog_resize_event
    _save_alignment_dialog_splitter_sizes = alignment_dialog_layout_callbacks._save_alignment_dialog_splitter_sizes
    _run_static_preview_batch = alignment_dialog_layout_callbacks._run_static_preview_batch
    main_splitter.splitterMoved.connect(_save_alignment_dialog_splitter_sizes)
    preview_splitter.splitterMoved.connect(_save_alignment_dialog_splitter_sizes)
    preview_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    main_splitter.addWidget(preview_panel)
    main_splitter.addWidget(controls_panel)
    main_splitter.setCollapsible(0, False)
    main_splitter.setCollapsible(1, False)
    main_splitter.setStretchFactor(0, 3)
    main_splitter.setStretchFactor(1, 1)
    root_layout.addWidget(main_splitter, 1)

    dialog.resizeEvent = _responsive_dialog_resize_event  # type: ignore[method-assign]


    return SimpleNamespace(
        _alignment_current_camera_state=locals().get('_alignment_current_camera_state'),
        _alignment_d3d11_host_ready=locals().get('_alignment_d3d11_host_ready'),
        _alignment_d3d11_live_frame_available=locals().get('_alignment_d3d11_live_frame_available'),
        _alignment_d3d11_loading_stuck=locals().get('_alignment_d3d11_loading_stuck'),
        _alignment_d3d11_saved_view_state=locals().get('_alignment_d3d11_saved_view_state'),
        _apply_alignment_dialog_responsive_layout=locals().get('_apply_alignment_dialog_responsive_layout'),
        _clear_stuck_alignment_d3d11_loading=locals().get('_clear_stuck_alignment_d3d11_loading'),
        _copy_mesh_editor_diagnostics=locals().get('_copy_mesh_editor_diagnostics'),
        _get_preview_render_settings=locals().get('_get_preview_render_settings'),
        _refresh_mesh_editor_diagnostics=locals().get('_refresh_mesh_editor_diagnostics'),
        _restore_alignment_preview_mode_view_state=locals().get('_restore_alignment_preview_mode_view_state'),
        _run_static_preview_batch=locals().get('_run_static_preview_batch'),
        _save_alignment_preview_mode_view_state=locals().get('_save_alignment_preview_mode_view_state'),
        _set_alignment_d3d11_loading=locals().get('_set_alignment_d3d11_loading'),
        _set_alignment_d3d11_pipeline_stage=locals().get('_set_alignment_d3d11_pipeline_stage'),
        _set_alignment_d3d11_progress=locals().get('_set_alignment_d3d11_progress'),
        _set_preview_performance_status=locals().get('_set_preview_performance_status'),
        _set_preview_render_settings=locals().get('_set_preview_render_settings'),
        alignment_control_content_min_width=locals().get('alignment_control_content_min_width'),
        alignment_control_min_width=locals().get('alignment_control_min_width'),
        alignment_d3d11_available=locals().get('alignment_d3d11_available'),
        alignment_d3d11_fast_reload_interval_ms=locals().get('alignment_d3d11_fast_reload_interval_ms'),
        alignment_d3d11_loading_spinner_label=locals().get('alignment_d3d11_loading_spinner_label'),
        alignment_d3d11_loading_state=locals().get('alignment_d3d11_loading_state'),
        alignment_d3d11_loading_timer=locals().get('alignment_d3d11_loading_timer'),
        alignment_d3d11_package_reload_interval_ms=locals().get('alignment_d3d11_package_reload_interval_ms'),
        alignment_d3d11_preview_host=locals().get('alignment_d3d11_preview_host'),
        alignment_d3d11_preview_page=locals().get('alignment_d3d11_preview_page'),
        alignment_d3d11_preview_status_label=locals().get('alignment_d3d11_preview_status_label'),
        alignment_d3d11_reload_stuck_timeout_s=locals().get('alignment_d3d11_reload_stuck_timeout_s'),
        alignment_d3d11_reload_timer=locals().get('alignment_d3d11_reload_timer'),
        alignment_d3d11_state=locals().get('alignment_d3d11_state'),
        alignment_d3d11_status_timer=locals().get('alignment_d3d11_status_timer'),
        alignment_d3d11_view_mode_combo=locals().get('alignment_d3d11_view_mode_combo'),
        alignment_d3d11_view_state=locals().get('alignment_d3d11_view_state'),
        alignment_dialog_layout_callbacks=locals().get('alignment_dialog_layout_callbacks'),
        alignment_dialog_layout_state=locals().get('alignment_dialog_layout_state'),
        alignment_preview_control_text=locals().get('alignment_preview_control_text'),
        alignment_preview_min_width=locals().get('alignment_preview_min_width'),
        alignment_preview_mode_state=locals().get('alignment_preview_mode_state'),
        alignment_preview_mode_view_states=locals().get('alignment_preview_mode_view_states'),
        alignment_preview_render_control_text=locals().get('alignment_preview_render_control_text'),
        alignment_preview_settings_button=locals().get('alignment_preview_settings_button'),
        alignment_preview_view_sync=locals().get('alignment_preview_view_sync'),
        alignment_use_global_preview_button=locals().get('alignment_use_global_preview_button'),
        clear_alignment_selection_button=locals().get('clear_alignment_selection_button'),
        classic_mesh_edit_toolbar=locals().get('classic_mesh_edit_toolbar'),
        classic_mesh_edit_toolbar_layout=locals().get('classic_mesh_edit_toolbar_layout'),
        content_container=locals().get('content_container'),
        controls_panel=locals().get('controls_panel'),
        custom_icon_control_text=locals().get('custom_icon_control_text'),
        generate_alignment_icon_button=locals().get('generate_alignment_icon_button'),
        label=locals().get('label'),
        layout=locals().get('layout'),
        main_splitter=locals().get('main_splitter'),
        mesh_edit_control_content_min_width=locals().get('mesh_edit_control_content_min_width'),
        mesh_edit_control_max_width=locals().get('mesh_edit_control_max_width'),
        mesh_edit_control_min_width=locals().get('mesh_edit_control_min_width'),
        mesh_editor_diagnostics_state=locals().get('mesh_editor_diagnostics_state'),
        mesh_dotnet_experiment_button=locals().get('mesh_dotnet_experiment_button'),
        object_name=locals().get('object_name'),
        original_dialog_preview=locals().get('original_dialog_preview'),
        overlay_dialog_preview=locals().get('overlay_dialog_preview'),
        overlay_original_locked_checkbox=locals().get('overlay_original_locked_checkbox'),
        preview_depth_spin=locals().get('preview_depth_spin'),
        preview_disable_brightness_checkbox=locals().get('preview_disable_brightness_checkbox'),
        preview_disable_tint_checkbox=locals().get('preview_disable_tint_checkbox'),
        preview_disable_uv_scale_checkbox=locals().get('preview_disable_uv_scale_checkbox'),
        preview_grid_checkbox=locals().get('preview_grid_checkbox'),
        preview_gizmo_checkbox=locals().get('preview_gizmo_checkbox'),
        preview_mesh_edit_checkbox=locals().get('preview_mesh_edit_checkbox'),
        preview_mesh_view_combo=locals().get('preview_mesh_view_combo'),
        mesh_edit_enabled_checkbox=locals().get('mesh_edit_enabled_checkbox'),
        preview_part_pick_checkbox=locals().get('preview_part_pick_checkbox'),
        preview_help=locals().get('preview_help'),
        hovered_source_part=locals().get('hovered_source_part'),
        preview_mode_combo=locals().get('preview_mode_combo'),
        preview_panel=locals().get('preview_panel'),
        preview_performance_label=locals().get('preview_performance_label'),
        preview_render_mode_combo=locals().get('preview_render_mode_combo'),
        preview_render_settings=locals().get('preview_render_settings'),
        preview_renderer_combo=locals().get('preview_renderer_combo'),
        preview_rough_spin=locals().get('preview_rough_spin'),
        preview_shine_spin=locals().get('preview_shine_spin'),
        preview_splitter=locals().get('preview_splitter'),
        preview_stack=locals().get('preview_stack'),
        preview_support_maps_checkbox=locals().get('preview_support_maps_checkbox'),
        preview_visible_mode_combo=locals().get('preview_visible_mode_combo'),
        previous_dialog_resize_event=locals().get('previous_dialog_resize_event'),
        replacement_only_preview=locals().get('replacement_only_preview'),
        root_layout=locals().get('root_layout'),
        setup_texture_flip_u_checkbox=locals().get('setup_texture_flip_u_checkbox'),
        setup_texture_flip_v_checkbox=locals().get('setup_texture_flip_v_checkbox'),
        static_dialog_preview=locals().get('static_dialog_preview'),
        tooltip=locals().get('tooltip'),
    )

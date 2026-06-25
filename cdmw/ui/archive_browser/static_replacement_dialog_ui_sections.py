"""UI section builders for static replacement dialog."""

from __future__ import annotations

import builtins as _builtins
from types import SimpleNamespace


class _LateLocalProxy:
    def __init__(self, getter: object, name: str) -> None:
        self._getter = getter
        self._name = name

    def _target(self) -> object:
        if not callable(self._getter):
            return self._getter
        return self._getter()

    def __getattr__(self, name: str) -> object:
        target = self._target()
        if target is None:
            raise NameError(f"late-bound UI object {self._name!r} is not available")
        return getattr(target, name)


def _context_builtin(context: dict[str, object], name: str) -> object:
    value = context.get(name)
    return value if callable(value) else getattr(_builtins, name)


def create_alignment_setup_options_transform_section(context: dict[str, object]) -> SimpleNamespace:
    ALIGNMENT_MODE_OPTIONS = context.get('ALIGNMENT_MODE_OPTIONS')
    CUSTOM_ITEM_ICON_DISABLED_STATUS = context.get('CUSTOM_ITEM_ICON_DISABLED_STATUS')
    CollapsibleSection = context.get('CollapsibleSection')
    Dict = context.get('Dict')
    EDGE_RELIEF_SOURCE_OPTIONS = context.get('EDGE_RELIEF_SOURCE_OPTIONS')
    MATERIAL_AUTHORITY_VISIBLE_COMPLETE_SWAP_PROFILE_NAMES = context.get('MATERIAL_AUTHORITY_VISIBLE_COMPLETE_SWAP_PROFILE_NAMES')
    QCheckBox = context.get('QCheckBox')
    QComboBox = context.get('QComboBox')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    QGridLayout = context.get('QGridLayout')
    QGroupBox = context.get('QGroupBox')
    QHBoxLayout = context.get('QHBoxLayout')
    QLabel = context.get('QLabel')
    QLineEdit = context.get('QLineEdit')
    QPlainTextEdit = context.get('QPlainTextEdit')
    QPushButton = context.get('QPushButton')
    QSizePolicy = context.get('QSizePolicy')
    QSlider = context.get('QSlider')
    QSpinBox = context.get('QSpinBox')
    QWidget = context.get('QWidget')
    Qt = context.get('Qt')
    TEXTURE_OUTPUT_SIZE_OPTIONS = context.get('TEXTURE_OUTPUT_SIZE_OPTIONS')
    TEXTURE_UV_ROTATION_OPTIONS = context.get('TEXTURE_UV_ROTATION_OPTIONS')
    _alignment_global_transform_layout_specs_helper = context.get('_alignment_global_transform_layout_specs_helper')
    _alignment_global_transform_reset_button_specs_helper = context.get('_alignment_global_transform_reset_button_specs_helper')
    _alignment_global_transform_row_specs_helper = context.get('_alignment_global_transform_row_specs_helper')
    _alignment_global_transform_slider_specs_helper = context.get('_alignment_global_transform_slider_specs_helper')
    _alignment_global_transform_spin_specs_helper = context.get('_alignment_global_transform_spin_specs_helper')
    _alignment_global_transform_tilt_button_specs_helper = context.get('_alignment_global_transform_tilt_button_specs_helper')
    _alignment_setup_options_control_text_helper = context.get('_alignment_setup_options_control_text_helper')
    _alignment_transform_control_text_helper = context.get('_alignment_transform_control_text_helper')
    _alignment_transform_location_original_text_helper = context.get('_alignment_transform_location_original_text_helper')
    _apply_current_glow_color_to_role_overrides = context.get('_apply_current_glow_color_to_role_overrides')
    _coerce_manual_material_profile_values_helper = context.get('_coerce_manual_material_profile_values_helper')
    _custom_item_icon_apply_setup_state_helper = context.get('_custom_item_icon_apply_setup_state_helper')
    _custom_item_icon_setup_state_helper = context.get('_custom_item_icon_setup_state_helper')
    _d3d11_source_part_selected = context.get('_d3d11_source_part_selected')
    _load_manual_material_profile_presets_helper = context.get('_load_manual_material_profile_presets_helper')
    _load_manual_material_profile_values_helper = context.get('_load_manual_material_profile_values_helper')
    _make_double_spin_helper = context.get('_make_double_spin_helper')
    _make_int_slider_spin_row_helper = context.get('_make_int_slider_spin_row_helper')
    _make_int_spin_helper = context.get('_make_int_spin_helper')
    _manual_material_profile_control_text_helper = context.get('_manual_material_profile_control_text_helper')
    _manual_material_profile_default_values_helper = context.get('_manual_material_profile_default_values_helper')
    _manual_material_profile_initial_status_html_helper = context.get('_manual_material_profile_initial_status_html_helper')
    _manual_material_profile_preview_warning_html_helper = context.get('_manual_material_profile_preview_warning_html_helper')
    _manual_material_profile_texture_impact_html_helper = context.get('_manual_material_profile_texture_impact_html_helper')
    _manual_material_profile_tooltips_helper = context.get('_manual_material_profile_tooltips_helper')
    _manual_profile_dirty_initial_state_helper = context.get('_manual_profile_dirty_initial_state_helper')
    _manual_profile_ready_initial_state_helper = context.get('_manual_profile_ready_initial_state_helper')
    _material_authority_adjustment_labels_helper = context.get('_material_authority_adjustment_labels_helper')
    _material_authority_adjustment_tooltips_helper = context.get('_material_authority_adjustment_tooltips_helper')
    _material_authority_clamped_int_helper = context.get('_material_authority_clamped_int_helper')
    _material_authority_complete_swap_tooltip_helper = context.get('_material_authority_complete_swap_tooltip_helper')
    _material_authority_control_tooltips_helper = context.get('_material_authority_control_tooltips_helper')
    _material_authority_edge_relief_source_helper = context.get('_material_authority_edge_relief_source_helper')
    _material_authority_global_gloss_tooltip_helper = context.get('_material_authority_global_gloss_tooltip_helper')
    _material_authority_route_summary_text_helper = context.get('_material_authority_route_summary_text_helper')
    _material_authority_setup_labels_helper = context.get('_material_authority_setup_labels_helper')
    _material_authority_setup_tooltips_helper = context.get('_material_authority_setup_tooltips_helper')
    _material_authority_sidecar_warning_html_helper = context.get('_material_authority_sidecar_warning_html_helper')
    _material_authority_sidecar_warning_tooltip_helper = context.get('_material_authority_sidecar_warning_tooltip_helper')
    _material_authority_stale_glow_settings_keys_helper = context.get('_material_authority_stale_glow_settings_keys_helper')
    _mesh_center_for_ui = context.get('_mesh_center_for_ui')
    _mesh_edit_apply_preview_payload = context.get('_mesh_edit_apply_preview_payload')
    _mesh_edit_begin_stroke = context.get('_mesh_edit_begin_stroke')
    _mesh_edit_cancel_stroke = context.get('_mesh_edit_cancel_stroke')
    _mesh_edit_finish_stroke = context.get('_mesh_edit_finish_stroke')
    _mesh_edit_selection_changed = context.get('_mesh_edit_selection_changed')
    _pick_selected_source_glow_color = context.get('_pick_selected_source_glow_color')
    _populate_combo_options_helper = context.get('_populate_combo_options_helper')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _refresh_output_impact_review = context.get('_refresh_output_impact_review')
    _refresh_part_glow_color_controls_enabled = context.get('_refresh_part_glow_color_controls_enabled')
    _scale_syncing_initial_state_helper = context.get('_scale_syncing_initial_state_helper')
    _set_selected_source_glow_color = context.get('_set_selected_source_glow_color')
    _stored_manual_material_profile_values_helper = context.get('_stored_manual_material_profile_values_helper')
    _texture_uv_control_text_helper = context.get('_texture_uv_control_text_helper')
    _wrap_spin_with_slider_helper = context.get('_wrap_spin_with_slider_helper')
    alignment_d3d11_preview_host = context.get('alignment_d3d11_preview_host')
    complete_swap_material_runtime_profiles = context.get('complete_swap_material_runtime_profiles')
    create_alignment_complete_swap_callbacks = context.get('create_alignment_complete_swap_callbacks')
    create_alignment_complete_swap_profile_select_callbacks = context.get('create_alignment_complete_swap_profile_select_callbacks')
    create_alignment_custom_icon_callbacks = context.get('create_alignment_custom_icon_callbacks')
    create_alignment_manual_profile_control_callbacks = context.get('create_alignment_manual_profile_control_callbacks')
    create_alignment_manual_profile_preset_callbacks = context.get('create_alignment_manual_profile_preset_callbacks')
    create_alignment_source_part_mutation_callbacks = context.get('create_alignment_source_part_mutation_callbacks')
    create_alignment_texture_orientation_callbacks = context.get('create_alignment_texture_orientation_callbacks')
    create_alignment_transform_drag_callbacks = context.get('create_alignment_transform_drag_callbacks')
    create_alignment_transform_row_callbacks = context.get('create_alignment_transform_row_callbacks')
    create_alignment_transform_slider_callbacks = context.get('create_alignment_transform_slider_callbacks')
    create_manual_material_profile_runtime_callbacks = context.get('create_manual_material_profile_runtime_callbacks')
    create_material_authority_adjustment_callbacks = context.get('create_material_authority_adjustment_callbacks')
    custom_icon_control_text = context.get('custom_icon_control_text')
    entry = context.get('entry')
    generate_alignment_icon_button = context.get('generate_alignment_icon_button')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    overlay_dialog_preview = context.get('overlay_dialog_preview')
    preferred_complete_source_swap = context.get('preferred_complete_source_swap')
    preview_controls_ready = context.get('preview_controls_ready')
    read_complete_swap_calibrated_material_profile = context.get('read_complete_swap_calibrated_material_profile')
    replacement_only_preview = context.get('replacement_only_preview')
    self = context.get('self')
    setup_layout = context.get('setup_layout')
    static_dialog_preview = context.get('static_dialog_preview')
    full_import_model_replacement = bool(context.get("full_import_model_replacement"))

    alignment_setup_options_control_text = _alignment_setup_options_control_text_helper()
    options_group = QGroupBox(alignment_setup_options_control_text["group_title"])
    form = QGridLayout(options_group)
    form.setContentsMargins(5, 3, 5, 3)
    form.setHorizontalSpacing(6)
    form.setVerticalSpacing(2)
    setup_layout.addWidget(options_group)

    alignment_mode_combo = QComboBox()
    _populate_combo_options_helper(alignment_mode_combo, ALIGNMENT_MODE_OPTIONS)
    alignment_mode_combo.setToolTip(alignment_setup_options_control_text["alignment_mode_tooltip"])
    form.addWidget(QLabel(alignment_setup_options_control_text["alignment_mode_label"]), 0, 0)
    form.addWidget(alignment_mode_combo, 0, 1)
    form.setColumnStretch(1, 1)

    scale_to_length_checkbox = QCheckBox(alignment_setup_options_control_text["scale_to_length"])
    scale_to_length_checkbox.setChecked(True)
    scale_to_length_checkbox.setToolTip(alignment_setup_options_control_text["scale_to_length_tooltip"])
    flip_direction_checkbox = QCheckBox(alignment_setup_options_control_text["flip_direction"])
    flip_direction_checkbox.setToolTip(alignment_setup_options_control_text["flip_direction_tooltip"])
    material_authority_setup_labels = _material_authority_setup_labels_helper()
    material_authority_setup_tooltips = _material_authority_setup_tooltips_helper()
    rebuild_sidecar_checkbox = QCheckBox(material_authority_setup_labels["rebuild_sidecar"])
    rebuild_sidecar_checkbox.setChecked(False)
    rebuild_sidecar_checkbox.setToolTip(material_authority_setup_tooltips["rebuild_sidecar"])
    prune_unmapped_original_dds_checkbox = QCheckBox(material_authority_setup_labels["prune_unmapped_original_dds"])
    prune_unmapped_original_dds_checkbox.setChecked(False)
    prune_unmapped_original_dds_checkbox.setToolTip(material_authority_setup_tooltips["prune_unmapped_original_dds"])
    inject_base_color_checkbox = QCheckBox(material_authority_setup_labels["inject_base_color"])
    inject_base_color_checkbox.setChecked(False)
    inject_base_color_checkbox.setToolTip(material_authority_setup_tooltips["inject_base_color"])
    source_color_faithful_checkbox = QCheckBox(material_authority_setup_labels["source_color_faithful"])
    source_color_faithful_checkbox.setChecked(False)
    source_color_faithful_checkbox.setToolTip(material_authority_setup_tooltips["source_color_faithful"])
    external_material_reset_checkbox = QCheckBox(material_authority_setup_labels["external_material_reset"])
    external_material_reset_checkbox.setChecked(False)
    external_material_reset_checkbox.setToolTip(material_authority_setup_tooltips["external_material_reset"])
    complete_external_swap_checkbox = QCheckBox(material_authority_setup_labels["complete_external_swap"])
    complete_external_swap_checkbox.setObjectName("MeshAlignmentCompleteExternalSwapCheckbox")
    complete_external_swap_checkbox.setChecked(False)
    complete_external_swap_checkbox.setToolTip(material_authority_setup_tooltips["complete_external_swap"])

    def _complete_external_swap_enabled() -> bool:
        return bool(complete_external_swap_checkbox.isChecked())

    complete_swap_material_profile_combo = QComboBox()
    complete_swap_material_profile_combo.setObjectName("MeshAlignmentCompleteSwapMaterialProfileCombo")
    visible_complete_swap_material_profile_names = MATERIAL_AUTHORITY_VISIBLE_COMPLETE_SWAP_PROFILE_NAMES
    complete_swap_material_profiles_by_name = {
        str(getattr(profile, "name", "") or ""): profile for profile in complete_swap_material_runtime_profiles()
    }
    for profile_name in visible_complete_swap_material_profile_names:
        profile = complete_swap_material_profiles_by_name.get(profile_name)
        if profile is not None:
            complete_swap_material_profile_combo.addItem(profile.label, profile.name)

    alignment_complete_swap_profile_select_callbacks = create_alignment_complete_swap_profile_select_callbacks({**context, **globals(), **locals()})
    _select_complete_swap_material_profile = alignment_complete_swap_profile_select_callbacks._select_complete_swap_material_profile
    alignment_complete_swap_callbacks = create_alignment_complete_swap_callbacks({**context, **globals(), **locals()})
    _complete_external_swap_mappings = alignment_complete_swap_callbacks._complete_external_swap_mappings
    _apply_complete_external_swap_routing_to_ui = alignment_complete_swap_callbacks._apply_complete_external_swap_routing_to_ui
    _select_complete_swap_material_profile_silently = alignment_complete_swap_callbacks._select_complete_swap_material_profile_silently
    _sync_complete_external_swap_mode = alignment_complete_swap_callbacks._sync_complete_external_swap_mode


    complete_swap_profile_store_path = self.settings_file_path.parent / "complete_swap_material_profile.json"
    stored_complete_swap_material_profile_obj = read_complete_swap_calibrated_material_profile(
        complete_swap_profile_store_path,
        "material_authority_detail_mask",
    )
    stored_complete_swap_material_profile = str(getattr(stored_complete_swap_material_profile_obj, "name", "") or "")
    saved_complete_swap_material_profile = str(
        self.settings.value(
            "settings/complete_swap_material_profile",
            stored_complete_swap_material_profile or "material_authority_detail_mask",
        )
        or stored_complete_swap_material_profile
        or "material_authority_detail_mask"
    )
    _select_complete_swap_material_profile(saved_complete_swap_material_profile)
    complete_swap_material_profile_combo.setToolTip(_material_authority_complete_swap_tooltip_helper())
    material_route_summary_label = QLabel(_material_authority_route_summary_text_helper())
    material_route_summary_label.setObjectName("MeshAlignmentMaterialRouteSummary")
    material_route_summary_label.setWordWrap(True)
    material_route_summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    global_gloss_reduction_tooltip = _material_authority_global_gloss_tooltip_helper()
    try:
        saved_global_gloss_reduction = int(round(float(self.settings.value("settings/complete_swap_global_gloss_reduction", 0) or 0)))
    except (TypeError, ValueError, OverflowError):
        saved_global_gloss_reduction = 0
    saved_global_gloss_reduction = max(-100, min(100, saved_global_gloss_reduction))
    global_gloss_reduction_pair = _make_int_slider_spin_row_helper(
        slider_object_name="MeshAlignmentGlobalGlossReductionSlider",
        spin_object_name="MeshAlignmentGlobalGlossReductionSpinBox",
        minimum=-100,
        maximum=100,
        value=saved_global_gloss_reduction,
        tooltip=global_gloss_reduction_tooltip,
    )
    global_gloss_reduction_slider = global_gloss_reduction_pair.slider
    global_gloss_reduction_spin = global_gloss_reduction_pair.spin
    material_authority_adjustment_labels = _material_authority_adjustment_labels_helper()
    global_gloss_reduction_hint = QLabel(material_authority_adjustment_labels["global_gloss_hint"])
    global_gloss_reduction_hint.setObjectName("HintLabel")
    global_gloss_reduction_hint.setWordWrap(True)
    global_gloss_reduction_row = global_gloss_reduction_pair.row
    true_source_basic_group = QGroupBox(material_authority_adjustment_labels["group_title"])
    true_source_basic_group.setObjectName("MeshAlignmentTrueSourceBasicControlsGroup")
    true_source_basic_form = QGridLayout(true_source_basic_group)
    true_source_basic_form.setContentsMargins(5, 3, 5, 3)
    true_source_basic_form.setHorizontalSpacing(6)
    true_source_basic_form.setVerticalSpacing(2)
    true_source_basic_form.addWidget(QLabel(material_authority_adjustment_labels["global_gloss_bias"]), 0, 0)
    true_source_basic_form.addLayout(global_gloss_reduction_row, 0, 1)
    true_source_basic_form.addWidget(global_gloss_reduction_hint, 1, 0, 1, 2)

    material_authority_adjustment_tooltips = _material_authority_adjustment_tooltips_helper()
    saved_source_brightness = _material_authority_clamped_int_helper(
        self.settings.value("settings/complete_swap_source_brightness", 0),
        default=0,
        minimum=-100,
        maximum=100,
    )
    source_brightness_pair = _make_int_slider_spin_row_helper(
        slider_object_name="MeshAlignmentSourceBrightnessSlider",
        spin_object_name="MeshAlignmentSourceBrightnessSpinBox",
        minimum=-100,
        maximum=100,
        value=saved_source_brightness,
        tooltip=material_authority_adjustment_tooltips["source_brightness"],
    )
    source_brightness_slider = source_brightness_pair.slider
    source_brightness_spin = source_brightness_pair.spin
    source_brightness_row = source_brightness_pair.row

    saved_tone_contrast = _material_authority_clamped_int_helper(
        self.settings.value("settings/complete_swap_tone_contrast", 0),
        default=0,
        minimum=-100,
        maximum=100,
    )
    tone_contrast_pair = _make_int_slider_spin_row_helper(
        slider_object_name="MeshAlignmentToneContrastSlider",
        spin_object_name="MeshAlignmentToneContrastSpinBox",
        minimum=-100,
        maximum=100,
        value=saved_tone_contrast,
        tooltip=material_authority_adjustment_tooltips["tone_contrast"],
    )
    tone_contrast_slider = tone_contrast_pair.slider
    tone_contrast_spin = tone_contrast_pair.spin
    tone_contrast_row = tone_contrast_pair.row

    saved_auto_brightness = _material_authority_clamped_int_helper(
        self.settings.value("settings/complete_swap_auto_brightness", 50),
        default=50,
        minimum=0,
        maximum=100,
    )
    auto_brightness_pair = _make_int_slider_spin_row_helper(
        slider_object_name="MeshAlignmentAutoBrightnessSlider",
        spin_object_name="MeshAlignmentAutoBrightnessSpinBox",
        minimum=0,
        maximum=100,
        value=saved_auto_brightness,
        tooltip=material_authority_adjustment_tooltips["auto_brightness"],
    )
    auto_brightness_slider = auto_brightness_pair.slider
    auto_brightness_spin = auto_brightness_pair.spin
    auto_brightness_row = auto_brightness_pair.row

    saved_edge_relief = _material_authority_clamped_int_helper(
        self.settings.value("settings/complete_swap_edge_relief_strength", 0),
        default=0,
        minimum=0,
        maximum=100,
    )
    edge_relief_pair = _make_int_slider_spin_row_helper(
        slider_object_name="MeshAlignmentEdgeReliefSlider",
        spin_object_name="MeshAlignmentEdgeReliefSpinBox",
        minimum=0,
        maximum=100,
        value=saved_edge_relief,
        tooltip=material_authority_adjustment_tooltips["edge_relief"],
    )
    edge_relief_slider = edge_relief_pair.slider
    edge_relief_spin = edge_relief_pair.spin
    edge_relief_row = edge_relief_pair.row
    edge_relief_source_combo = QComboBox()
    edge_relief_source_combo.setObjectName("MeshAlignmentEdgeReliefSourceCombo")
    _populate_combo_options_helper(edge_relief_source_combo, EDGE_RELIEF_SOURCE_OPTIONS)
    saved_edge_source = _material_authority_edge_relief_source_helper(
        self.settings.value("settings/complete_swap_edge_relief_source", "hybrid")
    )
    edge_source_index = edge_relief_source_combo.findData(saved_edge_source)
    if edge_source_index < 0:
        edge_source_index = 0
    edge_relief_source_combo.setCurrentIndex(edge_source_index)
    edge_relief_source_combo.setToolTip(material_authority_adjustment_tooltips["edge_relief_source"])

    for stale_glow_settings_key in _material_authority_stale_glow_settings_keys_helper():
        self.settings.remove(stale_glow_settings_key)
    saved_accent_glow = 0
    accent_glow_pair = _make_int_slider_spin_row_helper(
        slider_object_name="MeshAlignmentAccentGlowSlider",
        spin_object_name="MeshAlignmentAccentGlowSpinBox",
        minimum=0,
        maximum=100,
        value=saved_accent_glow,
        tooltip=material_authority_adjustment_tooltips["accent_glow"],
    )
    accent_glow_slider = accent_glow_pair.slider
    accent_glow_spin = accent_glow_pair.spin
    accent_glow_row = accent_glow_pair.row
    material_authority_control_tooltips = _material_authority_control_tooltips_helper()
    part_glow_color_checkbox = QCheckBox(material_authority_adjustment_labels["custom_glow_color"])
    part_glow_color_checkbox.setObjectName("MeshAlignmentSourceGlowColorOverrideCheckBox")
    part_glow_color_checkbox.setToolTip(material_authority_control_tooltips["custom_glow_checkbox"])
    saved_glow_color_enabled = False
    saved_glow_rgb: list[int] = [255, 255, 255]
    part_glow_color_checkbox.setChecked(saved_glow_color_enabled)
    part_glow_color_spins: list[QSpinBox] = []
    for channel_label, object_name, channel_value in (
        ("R", "MeshAlignmentSourceGlowColorRSpinBox", saved_glow_rgb[0]),
        ("G", "MeshAlignmentSourceGlowColorGSpinBox", saved_glow_rgb[1]),
        ("B", "MeshAlignmentSourceGlowColorBSpinBox", saved_glow_rgb[2]),
    ):
        channel_spin = _make_int_spin_helper(
            object_name=object_name,
            minimum=0,
            maximum=255,
            value=int(channel_value),
            prefix=f"{channel_label} ",
            tooltip=material_authority_control_tooltips["custom_glow_channel"],
            minimum_width=64,
            keyboard_tracking=False,
        )
        part_glow_color_spins.append(channel_spin)
    part_glow_color_pick_button = QPushButton(material_authority_adjustment_labels["custom_glow_pick"])
    part_glow_color_pick_button.setObjectName("MeshAlignmentSourceGlowColorPickButton")
    part_glow_color_pick_button.setMinimumWidth(0)
    part_glow_color_pick_button.setToolTip(material_authority_control_tooltips["custom_glow_pick"])
    part_glow_color_row = QHBoxLayout()
    part_glow_color_row.setContentsMargins(0, 0, 0, 0)
    part_glow_color_row.setSpacing(3)
    part_glow_color_row.addWidget(part_glow_color_checkbox)
    for channel_spin in part_glow_color_spins:
        part_glow_color_row.addWidget(channel_spin)
    part_glow_color_row.addWidget(part_glow_color_pick_button)
    part_glow_color_row.addStretch(1)

    true_source_basic_reset_button = QPushButton(material_authority_adjustment_labels["reset_adjustments"])
    true_source_basic_reset_button.setObjectName("MeshAlignmentMaterialAuthorityResetAdjustmentsButton")
    true_source_basic_reset_button.setToolTip(material_authority_control_tooltips["reset_adjustments"])
    true_source_basic_hint = QLabel(material_authority_adjustment_labels["hint"])
    true_source_basic_hint.setObjectName("HintLabel")
    true_source_basic_hint.setWordWrap(True)
    true_source_basic_form.addWidget(QLabel(material_authority_adjustment_labels["auto_brightness"]), 2, 0)
    true_source_basic_form.addLayout(auto_brightness_row, 2, 1)
    true_source_basic_form.addWidget(QLabel(material_authority_adjustment_labels["source_brightness"]), 3, 0)
    true_source_basic_form.addLayout(source_brightness_row, 3, 1)
    true_source_basic_form.addWidget(QLabel(material_authority_adjustment_labels["tone_contrast"]), 4, 0)
    true_source_basic_form.addLayout(tone_contrast_row, 4, 1)
    true_source_basic_form.addWidget(QLabel(material_authority_adjustment_labels["edge_relief"]), 5, 0)
    true_source_basic_form.addLayout(edge_relief_row, 5, 1)
    true_source_basic_form.addWidget(QLabel(material_authority_adjustment_labels["edge_relief_source"]), 6, 0)
    true_source_basic_form.addWidget(edge_relief_source_combo, 6, 1)
    true_source_basic_form.addWidget(QLabel(material_authority_adjustment_labels["accent_glow"]), 7, 0)
    true_source_basic_form.addLayout(accent_glow_row, 7, 1)
    true_source_basic_form.addWidget(QLabel(material_authority_adjustment_labels["glow_color"]), 8, 0)
    true_source_basic_form.addLayout(part_glow_color_row, 8, 1)
    true_source_basic_form.addWidget(true_source_basic_reset_button, 9, 0, 1, 2, Qt.AlignmentFlag.AlignRight)
    true_source_basic_form.addWidget(true_source_basic_hint, 10, 0, 1, 2)
    unsafe_material_preflight_checkbox = QCheckBox(material_authority_setup_labels["unsafe_preflight"])
    unsafe_material_preflight_checkbox.setObjectName("MeshAlignmentUnsafeMaterialPreflightExportCheckbox")
    unsafe_material_preflight_checkbox.setChecked(False)
    unsafe_material_preflight_checkbox.setToolTip(material_authority_control_tooltips["unsafe_preflight"])
    unsafe_material_preflight_checkbox.setEnabled(False)
    manual_profile_settings_key = "settings/complete_swap_manual_material_profile"
    manual_profile_presets_key = "settings/complete_swap_manual_material_profile_presets"
    manual_profile_defaults = next(
        (
            profile
            for profile in complete_swap_material_runtime_profiles()
            if str(getattr(profile, "name", "") or "") == "material_authority_manual"
        ),
        None,
    )
    manual_profile_default_values = _manual_material_profile_default_values_helper(manual_profile_defaults)
    stored_manual_profile_values = _stored_manual_material_profile_values_helper(
        stored_complete_swap_material_profile,
        stored_complete_swap_material_profile_obj,
        manual_profile_default_values,
    )

    _load_manual_profile_values = lambda: _load_manual_material_profile_values_helper(
            defaults=manual_profile_default_values,
            stored_values=stored_manual_profile_values,
            raw_settings=self.settings.value(manual_profile_settings_key, ""),
        )

    manual_profile_saved_values = _load_manual_profile_values()

    _coerce_manual_profile_values = lambda raw_values: _coerce_manual_material_profile_values_helper(
        raw_values,
        manual_profile_default_values,
    )

    _load_manual_profile_presets = lambda: _load_manual_material_profile_presets_helper(
            self.settings.value(manual_profile_presets_key, ""),
            defaults=manual_profile_default_values,
        )

    alignment_manual_profile_preset_callbacks = create_alignment_manual_profile_preset_callbacks({**context, **globals(), **locals()})
    _save_manual_profile_presets = alignment_manual_profile_preset_callbacks._save_manual_profile_presets

    manual_profile_presets = _load_manual_profile_presets()
    manual_profile_ready = _manual_profile_ready_initial_state_helper()
    manual_profile_dirty = _manual_profile_dirty_initial_state_helper()
    manual_profile_controls: Dict[str, object] = {}
    manual_profile_effect_widgets: Dict[str, list[object]] = {}
    manual_profile_control_tooltips: Dict[str, str] = {}
    manual_profile_control_text = _manual_material_profile_control_text_helper()
    manual_profile_group = QGroupBox(manual_profile_control_text["group_title"])
    manual_profile_group.setObjectName(manual_profile_control_text["group_object"])
    manual_profile_layout = QGridLayout(manual_profile_group)
    manual_profile_layout.setContentsMargins(6, 4, 6, 4)
    manual_profile_layout.setHorizontalSpacing(6)
    manual_profile_layout.setVerticalSpacing(3)

    alignment_manual_profile_control_callbacks = create_alignment_manual_profile_control_callbacks({**context, **globals(), **locals(), '_current_manual_material_profile_values': (lambda *args, **kwargs: _current_manual_material_profile_values(*args, **kwargs)), '_queue_material_authority_adjustment_preview_refresh': (lambda *args, **kwargs: _queue_material_authority_adjustment_preview_refresh(*args, **kwargs)), '_refresh_manual_profile_control_effects': (lambda *args, **kwargs: _refresh_manual_profile_control_effects(*args, **kwargs)), '_save_complete_swap_material_profile': (lambda *args, **kwargs: _save_complete_swap_material_profile(*args, **kwargs)), '_set_manual_profile_dirty': (lambda *args, **kwargs: _set_manual_profile_dirty(*args, **kwargs))})
    _manual_profile_mark_changed = alignment_manual_profile_control_callbacks._manual_profile_mark_changed
    _manual_combo = alignment_manual_profile_control_callbacks._manual_combo
    _manual_int = alignment_manual_profile_control_callbacks._manual_int
    _manual_float = alignment_manual_profile_control_callbacks._manual_float
    _manual_check = alignment_manual_profile_control_callbacks._manual_check
    _manual_rgb = alignment_manual_profile_control_callbacks._manual_rgb

    _manual_combo(
        0,
        "base_binding_mode",
        "Color slot",
        (("Overlay color texture", "overlay_texture"), ("Color-blend slot", "overlay_from_colorblend_slot"), ("Disabled", "disabled")),
        "Where source base color is written. Overlay is safest. Color-blend is experimental. Disabled removes source base-color binding.",
    )
    _manual_combo(
        1,
        "mask_binding_mode",
        "PBR/mask slot",
        (
            ("Detail mask material", "detail_mask_material"),
            ("Legacy color-blend mask", "color_blending_mask"),
            ("Scratch scalars only", "scratch_scalars"),
            ("Disabled", "disabled"),
        ),
        "Where generated AO/roughness/metal mask is written. Detail mask material is the proven non-gloss route. Legacy color-blend can restore the old glossy response.",
    )
    _manual_combo(
        2,
        "support_policy",
        "Support maps",
        (("Source only", "source_only"), ("Source plus neutral gaps", "generated_or_neutral"), ("Keep original support", "keep_original_support")),
        "Controls normal/height/detail support routing. Source only avoids stock contamination; source plus neutral gaps fills missing support; keep original may restore target detail but can reintroduce old grime/dark response.",
    )
    _manual_combo(
        3,
        "emissive_mode",
        "Emissive",
        (("Disabled", "disabled"), ("Intensity texture", "intensity")),
        "Disabled removes glow. Intensity binds source emissive textures or emissive material colors for any glowing part.",
    )
    _manual_combo(
        39,
        "authority_contract",
        "Authority path",
        (
            ("Material Authority", "true_source_authority_detail_mask"),
            ("Legacy True Source", "true_source_authority"),
            ("Legacy Runtime XML", "runtime_xml_preserve"),
        ),
        "Final-package contract. Material Authority is the proven detail-mask route. Legacy modes are kept only for repair/debug compatibility.",
    )
    _manual_int(6, "base_color_lift", "Dark lift", 0, 128, "Affects generated base DDS (*_base*.dds / _overlayColorTexture). Right brightens black/dark pixels so detail survives. Left keeps source darker.")
    _manual_float(7, "base_color_gamma", "Gamma lift", 0.25, 2.50, 0.05, "Affects generated base DDS (*_base*.dds / _overlayColorTexture). Left brightens midtones. Right darkens midtones.")
    _manual_float(8, "base_color_saturation", "Color saturation", 0.00, 2.00, 0.05, "Affects generated base DDS (*_base*.dds / _overlayColorTexture). Left makes colors more muted. Right makes colors stronger.")
    _manual_int(9, "base_color_value_max", "White cap", 128, 255, "Affects generated base DDS (*_base*.dds / _overlayColorTexture). Left makes white blade/edge less pure white. Right allows full white.")
    _manual_float(10, "base_color_scale", "Color scale", 0.10, 2.00, 0.05, "Affects generated base DDS (*_base*.dds / _overlayColorTexture). Left dims all source color before lift/gamma. Right brightens all source color.")
    _manual_float(11, "emissive_color_scale", "Emissive scale", 0.00, 2.00, 0.05, "Affects generated emissive DDS (*_emi.dds) only when source emissive exists. Left dims glow. Right makes glow stronger or blown out.")
    _manual_float(12, "emissive_color_saturation", "Emissive saturation", 0.00, 2.00, 0.05, "Affects generated emissive DDS (*_emi.dds) only when source emissive exists. Left makes emissive color less pure. Right makes it stronger.")
    _manual_int(13, "emissive_color_value_max", "Emissive cap", 0, 255, "Affects generated emissive DDS (*_emi.dds) only when source emissive exists. Left caps brightness. Right allows pure bright emissive.")
    _manual_int(14, "roughness_default", "Roughness default", 0, 255, "Affects generated material mask DDS (*_ma.dds / _detailMaskTexture in Material Authority). Right is dull/matte. Left is shiny if source has no roughness.")
    _manual_int(15, "roughness_min", "Roughness floor", 0, 255, "Affects generated material mask DDS (*_ma.dds / _detailMaskTexture in Material Authority). Right prevents glossy highlights. Left allows shiny source roughness.")
    _manual_float(16, "roughness_scale", "Roughness scale", 0.00, 2.00, 0.05, "Affects generated material mask DDS (*_ma.dds / _detailMaskTexture in Material Authority). Right increases roughness from source map. Left lowers roughness/glossier.")
    _manual_int(17, "roughness_max", "Roughness cap", 0, 255, "Affects generated material mask DDS (*_ma.dds / _detailMaskTexture in Material Authority). Left limits maximum matte response. Right allows fully matte roughness.")
    _manual_int(18, "metallic_default", "Metal default", 0, 255, "Affects generated material mask DDS (*_ma.dds / _detailMaskTexture in Material Authority). Right makes factor-only parts more metal. Left makes them nonmetal.")
    _manual_int(19, "metallic_min", "Metal floor", 0, 255, "Affects generated material mask DDS (*_ma.dds / _detailMaskTexture in Material Authority). Right forces minimum metal response. Left allows nonmetal.")
    _manual_float(20, "metallic_scale", "Metal scale", 0.00, 2.00, 0.05, "Affects generated material mask DDS (*_ma.dds / _detailMaskTexture in Material Authority). Right keeps/boosts source metallic. Left makes parts less mirror-like.")
    _manual_int(21, "metallic_max", "Metal cap", 0, 255, "Affects generated material mask DDS (*_ma.dds / _detailMaskTexture in Material Authority). Left limits metal response/bright reflections. Right allows full metal.")
    _manual_float(22, "scratch_roughness", "Shader roughness", 0.00, 1.00, 0.05, "Sidecar XML scalar, not a DDS. Right tells runtime wrapper to be rougher. Left permits glossy shader response.")
    _manual_float(23, "scratch_metallic", "Shader metal", 0.00, 1.00, 0.05, "Sidecar XML scalar, not a DDS. Right adds wrapper metallic scalar. Left removes inherited metal scalar.")
    _manual_float(24, "shine_scalar", "Shader shine", 0.00, 1.00, 0.05, "Sidecar XML scalar, not a DDS. Left removes inherited shine. Right restores shine/gloss scalar.")
    _manual_float(25, "displacement_scale_multiplier", "Height scale", 0.00, 1.00, 0.05, "Affects height/detail support (*_disp.dds / *_mg.dds) only when support maps write or preserve them. Left disables raised/blobby height. Right restores height relief.")
    _manual_float(26, "displacement_scale_max", "Height cap", 0.00, 1.00, 0.05, "Affects height/detail support (*_disp.dds / *_mg.dds) only when support maps write or preserve them. Left clamps height. Right allows stronger raised relief.")
    _manual_int(27, "ao_default", "AO default", 0, 255, "Affects generated material mask DDS (*_ma.dds / _detailMaskTexture in Material Authority). Right is brighter/no ambient darkening. Left darkens missing-AO areas.")
    _manual_int(28, "alpha_default", "Mask alpha", 0, 255, "Affects generated material mask DDS (*_ma.dds / _detailMaskTexture in Material Authority). Usually 0. Right may preserve stronger mask alpha response.")
    _manual_rgb(29, "neutral_color_rgb", "Neutral tint RGB", "Sidecar XML color reset value. Affects tint/scratch/color scalar params only when the target wrapper has those params.")
    _manual_check(30, "force_nonmetal", "Force nonmetal", "Material mask generation: forces metal channel to the Metal default value. No visible effect if PBR/mask output is disabled or unused by the shader.")
    _manual_check(31, "roughness_inverted", "Invert roughness", "Material mask generation: flips roughness channel. Try when matte becomes shiny or shiny becomes matte.")
    _manual_check(32, "metallic_inverted", "Invert metallic", "Material mask generation: flips metal channel. Try when nonmetal/metal response looks reversed.")
    _manual_check(33, "preserve_scratch_alpha", "Preserve scratch alpha", "Sidecar XML color reset: keeps existing alpha only on scratch-tint color params. No effect if no scratch-tint params exist.")
    _manual_check(34, "allow_factor_only_authority", "Use factor-only colors", "Allows untextured materials with glTF/source color factors to generate their own base-color DDS. No effect when every material already has base textures.")
    _manual_check(35, "factor_only_material_mask", "Generate factor-only mask", "Generates neutral roughness/metal mask for untextured/factor-only materials. No effect for fully textured materials.")
    _manual_check(36, "force_neutral_layer_support", "Fill missing support with neutral maps", "Source-only support routing: writes neutral normal/height/detail/mask when source support is missing. No effect when source support is complete or support mode is not Source only.")
    _manual_check(37, "preserve_target_layer_response", "Preserve target layer response", "Sidecar XML reset: keeps more old CD layer/detail/shader response. Useful for lost detail, but can restore grime/dark tint/gloss.")
    _manual_check(38, "source_color_layer_authority", "Route source color to layer slots", "Sidecar XML texture routing: pushes source base color into compatible visible color/detail/grime slots if those slots exist. Can improve authority or overbind.")
    manual_profile_texture_impact = QLabel(_manual_material_profile_texture_impact_html_helper())
    manual_profile_texture_impact.setObjectName("HintLabel")
    manual_profile_texture_impact.setTextFormat(Qt.RichText)
    manual_profile_texture_impact.setWordWrap(True)
    manual_profile_layout.addWidget(manual_profile_texture_impact, 40, 0, 1, 4)
    manual_profile_preset_group = QGroupBox(manual_profile_control_text["preset_group"])
    manual_profile_preset_group.setObjectName("MeshAlignmentManualMaterialProfilePresetGroup")
    manual_profile_preset_layout = QGridLayout(manual_profile_preset_group)
    manual_profile_preset_layout.setContentsMargins(6, 4, 6, 4)
    manual_profile_preset_layout.setHorizontalSpacing(6)
    manual_profile_preset_layout.setVerticalSpacing(3)
    manual_profile_tooltips = _manual_material_profile_tooltips_helper()
    manual_profile_preset_combo = QComboBox()
    manual_profile_preset_combo.setObjectName("MeshAlignmentManualMaterialProfilePresetCombo")
    manual_profile_preset_combo.setToolTip(manual_profile_tooltips["preset_combo"])
    manual_profile_preset_name_edit = QLineEdit()
    manual_profile_preset_name_edit.setObjectName("MeshAlignmentManualMaterialProfilePresetName")
    manual_profile_preset_name_edit.setPlaceholderText(manual_profile_control_text["preset_name_placeholder"])
    manual_profile_preset_name_edit.setToolTip(manual_profile_tooltips["preset_name"])
    manual_profile_preset_details_edit = QPlainTextEdit()
    manual_profile_preset_details_edit.setObjectName("MeshAlignmentManualMaterialProfilePresetDetails")
    manual_profile_preset_details_edit.setPlaceholderText(manual_profile_control_text["preset_details_placeholder"])
    manual_profile_preset_details_edit.setMaximumHeight(58)
    manual_profile_preset_details_edit.setToolTip(manual_profile_tooltips["preset_details"])
    manual_profile_preset_recommended_edit = QLineEdit()
    manual_profile_preset_recommended_edit.setObjectName("MeshAlignmentManualMaterialProfilePresetRecommended")
    manual_profile_preset_recommended_edit.setPlaceholderText(manual_profile_control_text["preset_recommended_placeholder"])
    manual_profile_preset_recommended_edit.setToolTip(manual_profile_tooltips["preset_recommended"])
    manual_profile_preset_save_button = QPushButton(manual_profile_control_text["preset_save_button"])
    manual_profile_preset_save_button.setObjectName("MeshAlignmentManualMaterialProfilePresetSaveButton")
    manual_profile_preset_save_button.setToolTip(manual_profile_tooltips["preset_save"])
    manual_profile_preset_load_button = QPushButton(manual_profile_control_text["preset_load_button"])
    manual_profile_preset_load_button.setObjectName("MeshAlignmentManualMaterialProfilePresetLoadButton")
    manual_profile_preset_load_button.setToolTip(manual_profile_tooltips["preset_load"])
    manual_profile_preset_delete_button = QPushButton(manual_profile_control_text["preset_delete_button"])
    manual_profile_preset_delete_button.setObjectName("MeshAlignmentManualMaterialProfilePresetDeleteButton")
    manual_profile_preset_delete_button.setToolTip(manual_profile_tooltips["preset_delete"])
    manual_profile_preset_buttons = QHBoxLayout()
    manual_profile_preset_buttons.setContentsMargins(0, 0, 0, 0)
    manual_profile_preset_buttons.setSpacing(4)
    manual_profile_preset_buttons.addWidget(manual_profile_preset_save_button)
    manual_profile_preset_buttons.addWidget(manual_profile_preset_load_button)
    manual_profile_preset_buttons.addWidget(manual_profile_preset_delete_button)
    manual_profile_preset_layout.addWidget(QLabel(manual_profile_control_text["saved_label"]), 0, 0)
    manual_profile_preset_layout.addWidget(manual_profile_preset_combo, 0, 1)
    manual_profile_preset_layout.addWidget(QLabel(manual_profile_control_text["name_label"]), 1, 0)
    manual_profile_preset_layout.addWidget(manual_profile_preset_name_edit, 1, 1)
    manual_profile_preset_layout.addWidget(QLabel(manual_profile_control_text["details_label"]), 2, 0)
    manual_profile_preset_layout.addWidget(manual_profile_preset_details_edit, 2, 1)
    manual_profile_preset_layout.addWidget(QLabel(manual_profile_control_text["recommended_label"]), 3, 0)
    manual_profile_preset_layout.addWidget(manual_profile_preset_recommended_edit, 3, 1)
    manual_profile_preset_layout.addLayout(manual_profile_preset_buttons, 4, 1)
    manual_profile_layout.addWidget(manual_profile_preset_group, 41, 0, 1, 4)
    manual_profile_apply_button = QPushButton(manual_profile_control_text["apply_button"])
    manual_profile_apply_button.setObjectName("MeshAlignmentManualMaterialProfileApplyButton")
    manual_profile_apply_button.setToolTip(manual_profile_tooltips["apply"])
    manual_profile_apply_button.setEnabled(False)
    manual_profile_reset_button = QPushButton(manual_profile_control_text["reset_button"])
    manual_profile_reset_button.setObjectName("MeshAlignmentManualMaterialProfileResetButton")
    manual_profile_reset_button.setToolTip(manual_profile_tooltips["reset"])
    manual_profile_apply_row = QHBoxLayout()
    manual_profile_apply_row.setContentsMargins(0, 0, 0, 0)
    manual_profile_apply_row.setSpacing(4)
    manual_profile_apply_row.addWidget(manual_profile_apply_button)
    manual_profile_apply_row.addWidget(manual_profile_reset_button)
    manual_profile_layout.addLayout(manual_profile_apply_row, 4, 0, 1, 4)
    manual_profile_change_status = QLabel(_manual_material_profile_initial_status_html_helper())
    manual_profile_change_status.setObjectName("HintLabel")
    manual_profile_change_status.setTextFormat(Qt.RichText)
    manual_profile_change_status.setWordWrap(True)
    manual_profile_layout.addWidget(manual_profile_change_status, 5, 0, 1, 4)
    manual_profile_preview_warning = QLabel(_manual_material_profile_preview_warning_html_helper())
    manual_profile_preview_warning.setWordWrap(True)
    manual_profile_preview_warning.setTextFormat(Qt.RichText)
    manual_profile_preview_warning.setObjectName("WarningLabel")
    manual_profile_layout.addWidget(manual_profile_preview_warning, 42, 0, 1, 4)
    manual_profile_group.setVisible(False)
    manual_profile_ready["ready"] = True

    manual_profile_runtime_callbacks = create_manual_material_profile_runtime_callbacks({**context, **globals(), **locals()})
    _current_manual_material_profile_values = manual_profile_runtime_callbacks._current_manual_material_profile_values
    _refresh_manual_profile_control_effects = manual_profile_runtime_callbacks._refresh_manual_profile_control_effects
    _set_manual_profile_dirty = manual_profile_runtime_callbacks._set_manual_profile_dirty
    _apply_manual_material_profile_values = manual_profile_runtime_callbacks._apply_manual_material_profile_values
    _reset_manual_material_profile_to_material_authority = manual_profile_runtime_callbacks._reset_manual_material_profile_to_material_authority
    _apply_current_manual_material_profile_to_preview = manual_profile_runtime_callbacks._apply_current_manual_material_profile_to_preview
    _selected_manual_profile_preset = manual_profile_runtime_callbacks._selected_manual_profile_preset
    _refresh_manual_profile_preset_combo = manual_profile_runtime_callbacks._refresh_manual_profile_preset_combo
    _show_selected_manual_profile_preset_metadata = manual_profile_runtime_callbacks._show_selected_manual_profile_preset_metadata
    _save_current_manual_profile_preset = manual_profile_runtime_callbacks._save_current_manual_profile_preset
    _load_selected_manual_profile_preset = manual_profile_runtime_callbacks._load_selected_manual_profile_preset
    _delete_selected_manual_profile_preset = manual_profile_runtime_callbacks._delete_selected_manual_profile_preset
    _current_complete_swap_material_profile_token = manual_profile_runtime_callbacks._current_complete_swap_material_profile_token
    _refresh_manual_material_profile_panel = manual_profile_runtime_callbacks._refresh_manual_material_profile_panel
    _save_complete_swap_material_profile = manual_profile_runtime_callbacks._save_complete_swap_material_profile
    _refresh_manual_profile_preset_combo("")
    manual_profile_preset_combo.currentIndexChanged.connect(lambda _index: _show_selected_manual_profile_preset_metadata())
    manual_profile_preset_save_button.clicked.connect(_save_current_manual_profile_preset)
    manual_profile_preset_load_button.clicked.connect(_load_selected_manual_profile_preset)
    manual_profile_preset_delete_button.clicked.connect(_delete_selected_manual_profile_preset)
    manual_profile_apply_button.clicked.connect(_apply_current_manual_material_profile_to_preview)
    manual_profile_reset_button.clicked.connect(_reset_manual_material_profile_to_material_authority)
    sidecar_warning_label = QLabel(_material_authority_sidecar_warning_html_helper())
    sidecar_warning_label.setWordWrap(True)
    sidecar_warning_label.setTextFormat(Qt.RichText)
    sidecar_warning_label.setObjectName("HintLabel")
    sidecar_warning_label.setToolTip(_material_authority_sidecar_warning_tooltip_helper())
    sidecar_warning_label.setVisible(False)
    texture_output_size_combo = QComboBox()
    _populate_combo_options_helper(texture_output_size_combo, TEXTURE_OUTPUT_SIZE_OPTIONS)
    texture_uv_control_text = _texture_uv_control_text_helper()
    texture_output_size_combo.setToolTip(texture_uv_control_text["setup_output_size_tooltip"])
    setup_texture_rotate_combo = QComboBox()
    setup_texture_rotate_combo.setObjectName("MeshAlignmentSetupTextureRotateCombo")
    _populate_combo_options_helper(setup_texture_rotate_combo, TEXTURE_UV_ROTATION_OPTIONS)
    setup_texture_rotate_combo.setToolTip(texture_uv_control_text["setup_rotate_tooltip"])
    setup_texture_flip_u_checkbox = QCheckBox(texture_uv_control_text["flip_u_label"])
    setup_texture_flip_u_checkbox.setObjectName("MeshAlignmentSetupTextureFlipUCheckbox")
    setup_texture_flip_u_checkbox.setToolTip(texture_uv_control_text["setup_flip_u_tooltip"])
    setup_texture_flip_v_checkbox = QCheckBox(texture_uv_control_text["flip_v_label"])
    setup_texture_flip_v_checkbox.setObjectName("MeshAlignmentSetupTextureFlipVCheckbox")
    setup_texture_flip_v_checkbox.setToolTip(texture_uv_control_text["setup_flip_v_tooltip"])
    setup_texture_reset_button = QPushButton(texture_uv_control_text["setup_reset_button"])
    setup_texture_reset_button.setObjectName("MeshAlignmentSetupTextureResetButton")
    setup_texture_reset_button.setMinimumWidth(0)
    setup_texture_reset_button.setToolTip(texture_uv_control_text["setup_reset_tooltip"])

    alignment_texture_orientation_callbacks = create_alignment_texture_orientation_callbacks({**context, **globals(), **locals()})
    _save_setup_texture_orientation = alignment_texture_orientation_callbacks._save_setup_texture_orientation
    _reset_setup_texture_orientation = alignment_texture_orientation_callbacks._reset_setup_texture_orientation

    custom_icon_checkbox = QCheckBox(custom_icon_control_text["use_custom_icon"])
    custom_icon_checkbox.setToolTip(custom_icon_control_text["use_custom_icon_tooltip"])
    custom_icon_source_edit = QLineEdit()
    custom_icon_source_edit.setPlaceholderText(custom_icon_control_text["source_placeholder"])
    custom_icon_file_button = QPushButton(custom_icon_control_text["file_button"])
    custom_icon_folder_button = QPushButton(custom_icon_control_text["folder_button"])
    custom_icon_library_button = QPushButton(custom_icon_control_text["library_button"])
    custom_icon_target_combo = QComboBox()
    custom_icon_status = QLabel(CUSTOM_ITEM_ICON_DISABLED_STATUS)
    custom_icon_status.setObjectName("HintLabel")
    custom_icon_status.setWordWrap(True)
    custom_icon_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    save_generated_icon_to_library_checkbox = QCheckBox(custom_icon_control_text["save_generated_to_library"])
    save_generated_icon_to_library_checkbox.setObjectName("MeshAlignmentSaveGeneratedIconToLibraryCheckbox")
    save_generated_icon_to_library_checkbox.setChecked(False)
    save_generated_icon_to_library_checkbox.setToolTip(
        custom_icon_control_text["save_generated_to_library_tooltip"]
    )
    custom_icon_target_graph, _custom_icon_refs = self._archive_asset_family_graph_for_entry(entry)
    custom_icon_target_entries = self._attachment_package_item_icon_entries(entry, custom_icon_target_graph)
    custom_icon_setup_state = _custom_item_icon_setup_state_helper(
        has_target_entries=bool(custom_icon_target_entries),
        has_item_icons_tab=hasattr(self, "item_icons_tab"),
    )
    _custom_item_icon_apply_setup_state_helper(
        custom_icon_setup_state,
        save_generated_to_library_widget=save_generated_icon_to_library_checkbox,
        custom_icon_widget=custom_icon_checkbox,
        target_combo_widget=custom_icon_target_combo,
        status_widget=custom_icon_status,
    )
    for icon_entry in custom_icon_target_entries:
        custom_icon_target_combo.addItem(icon_entry.path, icon_entry)
    form.addWidget(scale_to_length_checkbox, 1, 0, 1, 2)
    form.addWidget(flip_direction_checkbox, 2, 0, 1, 2)
    form.addWidget(material_route_summary_label, 3, 0, 1, 2)
    form.addWidget(rebuild_sidecar_checkbox, 4, 0, 1, 2)
    form.addWidget(prune_unmapped_original_dds_checkbox, 5, 0, 1, 2)
    form.addWidget(inject_base_color_checkbox, 6, 0, 1, 2)
    form.addWidget(source_color_faithful_checkbox, 7, 0, 1, 2)
    form.addWidget(external_material_reset_checkbox, 8, 0, 1, 2)
    form.addWidget(complete_external_swap_checkbox, 9, 0, 1, 2)
    runtime_material_profile_label = QLabel(material_authority_setup_labels["runtime_material_profile"])
    form.addWidget(runtime_material_profile_label, 10, 0)
    form.addWidget(complete_swap_material_profile_combo, 10, 1)
    form.addWidget(true_source_basic_group, 11, 0, 1, 2)
    form.addWidget(unsafe_material_preflight_checkbox, 12, 0, 1, 2)
    form.addWidget(manual_profile_group, 13, 0, 1, 2)
    form.addWidget(sidecar_warning_label, 14, 0, 1, 2)
    texture_size_label = QLabel(material_authority_setup_labels["texture_size"])
    form.addWidget(texture_size_label, 15, 0)
    form.addWidget(texture_output_size_combo, 15, 1)
    setup_texture_orientation_widget = QWidget()
    setup_texture_orientation_row = QHBoxLayout(setup_texture_orientation_widget)
    setup_texture_orientation_row.setContentsMargins(0, 0, 0, 0)
    setup_texture_orientation_row.setSpacing(5)
    setup_texture_orientation_row.addWidget(setup_texture_rotate_combo, 1)
    setup_texture_orientation_row.addWidget(setup_texture_flip_u_checkbox)
    setup_texture_orientation_row.addWidget(setup_texture_flip_v_checkbox)
    setup_texture_orientation_row.addWidget(setup_texture_reset_button)
    texture_orientation_label = QLabel(material_authority_setup_labels["texture_orientation"])
    form.addWidget(texture_orientation_label, 16, 0)
    form.addWidget(setup_texture_orientation_widget, 16, 1)
    form.addWidget(custom_icon_checkbox, 17, 0, 1, 2)
    custom_icon_source_row = QHBoxLayout()
    custom_icon_source_row.setContentsMargins(0, 0, 0, 0)
    custom_icon_source_row.setSpacing(5)
    custom_icon_source_row.addWidget(custom_icon_source_edit, 1)
    custom_icon_source_row.addWidget(custom_icon_file_button)
    custom_icon_source_row.addWidget(custom_icon_folder_button)
    custom_icon_source_row.addWidget(custom_icon_library_button)
    form.addWidget(QLabel(custom_icon_control_text["source_label"]), 18, 0)
    form.addLayout(custom_icon_source_row, 18, 1)
    form.addWidget(QLabel(custom_icon_control_text["target_label"]), 19, 0)
    form.addWidget(custom_icon_target_combo, 19, 1)
    form.addWidget(custom_icon_status, 20, 0, 1, 2)
    form.addWidget(save_generated_icon_to_library_checkbox, 21, 0, 1, 2)
    setup_texture_rotate_combo.currentIndexChanged.connect(_save_setup_texture_orientation)
    setup_texture_flip_u_checkbox.toggled.connect(_save_setup_texture_orientation)
    setup_texture_flip_v_checkbox.toggled.connect(_save_setup_texture_orientation)
    setup_texture_reset_button.clicked.connect(_reset_setup_texture_orientation)

    material_authority_adjustment_callbacks = create_material_authority_adjustment_callbacks({**context, **globals(), **locals()})
    _set_global_gloss_reduction = material_authority_adjustment_callbacks._set_global_gloss_reduction
    _refresh_global_gloss_reduction_hint = material_authority_adjustment_callbacks._refresh_global_gloss_reduction_hint
    _basic_controls_profile_enabled = material_authority_adjustment_callbacks._basic_controls_profile_enabled
    _current_material_authority_preview_profile = material_authority_adjustment_callbacks._current_material_authority_preview_profile
    _material_authority_preview_signature = material_authority_adjustment_callbacks._material_authority_preview_signature
    _material_authority_preview_inactive_reason = material_authority_adjustment_callbacks._material_authority_preview_inactive_reason
    _material_authority_controls_affect_visible_preview = material_authority_adjustment_callbacks._material_authority_controls_affect_visible_preview
    _queue_material_authority_adjustment_preview_refresh = material_authority_adjustment_callbacks._queue_material_authority_adjustment_preview_refresh
    _set_spin_slider_pair = material_authority_adjustment_callbacks._set_spin_slider_pair
    _set_edge_relief = material_authority_adjustment_callbacks._set_edge_relief
    _set_source_brightness = material_authority_adjustment_callbacks._set_source_brightness
    _set_tone_contrast = material_authority_adjustment_callbacks._set_tone_contrast
    _set_auto_brightness = material_authority_adjustment_callbacks._set_auto_brightness
    _set_edge_relief_source = material_authority_adjustment_callbacks._set_edge_relief_source
    _set_accent_glow = material_authority_adjustment_callbacks._set_accent_glow
    _set_edge_relief_source_value = material_authority_adjustment_callbacks._set_edge_relief_source_value
    _reset_material_authority_adjustments = material_authority_adjustment_callbacks._reset_material_authority_adjustments
    _refresh_true_source_basic_controls_state = material_authority_adjustment_callbacks._refresh_true_source_basic_controls_state
    _refresh_sidecar_option_state = material_authority_adjustment_callbacks._refresh_sidecar_option_state
    _apply_sidecar_dependent_toggle = material_authority_adjustment_callbacks._apply_sidecar_dependent_toggle

    rebuild_sidecar_checkbox.toggled.connect(
        lambda _checked: (
            _refresh_sidecar_option_state(),
            _refresh_output_impact_review(),
            _queue_texture_preview_refresh(),
        )
    )
    inject_base_color_checkbox.toggled.connect(
        lambda checked: _apply_sidecar_dependent_toggle(bool(checked))
    )
    prune_unmapped_original_dds_checkbox.toggled.connect(
        lambda checked: _apply_sidecar_dependent_toggle(bool(checked), refresh_output=True)
    )
    source_color_faithful_checkbox.toggled.connect(
        lambda checked: _apply_sidecar_dependent_toggle(bool(checked))
    )
    external_material_reset_checkbox.toggled.connect(
        lambda checked: _apply_sidecar_dependent_toggle(bool(checked))
    )
    unsafe_material_preflight_checkbox.toggled.connect(lambda _checked: _refresh_output_impact_review())
    global_gloss_reduction_slider.valueChanged.connect(lambda value: _set_global_gloss_reduction(int(value)))
    global_gloss_reduction_spin.valueChanged.connect(lambda value: _set_global_gloss_reduction(int(value)))
    auto_brightness_slider.valueChanged.connect(lambda value: _set_auto_brightness(int(value)))
    auto_brightness_spin.valueChanged.connect(lambda value: _set_auto_brightness(int(value)))
    source_brightness_slider.valueChanged.connect(lambda value: _set_source_brightness(int(value)))
    source_brightness_spin.valueChanged.connect(lambda value: _set_source_brightness(int(value)))
    tone_contrast_slider.valueChanged.connect(lambda value: _set_tone_contrast(int(value)))
    tone_contrast_spin.valueChanged.connect(lambda value: _set_tone_contrast(int(value)))
    edge_relief_slider.valueChanged.connect(lambda value: _set_edge_relief(int(value)))
    edge_relief_spin.valueChanged.connect(lambda value: _set_edge_relief(int(value)))
    edge_relief_source_combo.currentIndexChanged.connect(lambda _index: _set_edge_relief_source())
    accent_glow_slider.valueChanged.connect(lambda value: _set_accent_glow(int(value)))
    accent_glow_spin.valueChanged.connect(lambda value: _set_accent_glow(int(value)))
    context.update(
        {
            "complete_external_swap_checkbox": complete_external_swap_checkbox,
            "part_glow_color_checkbox": part_glow_color_checkbox,
            "part_glow_color_pick_button": part_glow_color_pick_button,
            "part_glow_color_spins": part_glow_color_spins,
        }
    )
    source_part_glow_controls_ready = (
        callable(_set_selected_source_glow_color)
        and callable(_refresh_part_glow_color_controls_enabled)
        and callable(_apply_current_glow_color_to_role_overrides)
    )

    def _set_selected_source_glow_color_if_ready(*_args: object) -> None:
        if callable(_set_selected_source_glow_color):
            _set_selected_source_glow_color()

    def _pick_selected_source_glow_color_if_ready(*_args: object) -> None:
        if callable(_pick_selected_source_glow_color):
            _pick_selected_source_glow_color()

    part_glow_color_checkbox.setEnabled(source_part_glow_controls_ready)
    for part_glow_spin in part_glow_color_spins:
        part_glow_spin.setEnabled(source_part_glow_controls_ready)
    part_glow_color_pick_button.setEnabled(source_part_glow_controls_ready)
    part_glow_color_checkbox.toggled.connect(_set_selected_source_glow_color_if_ready)
    for part_glow_spin in part_glow_color_spins:
        part_glow_spin.valueChanged.connect(_set_selected_source_glow_color_if_ready)
    part_glow_color_pick_button.clicked.connect(_pick_selected_source_glow_color_if_ready)
    if callable(_refresh_part_glow_color_controls_enabled):
        _refresh_part_glow_color_controls_enabled()
    if callable(_apply_current_glow_color_to_role_overrides):
        _apply_current_glow_color_to_role_overrides()
    true_source_basic_reset_button.clicked.connect(_reset_material_authority_adjustments)
    complete_external_swap_checkbox.toggled.connect(_sync_complete_external_swap_mode)
    if preferred_complete_source_swap:
        _select_complete_swap_material_profile("material_authority_detail_mask", persist=False)
        rebuild_sidecar_checkbox.setChecked(True)
        prune_unmapped_original_dds_checkbox.setChecked(True)
        source_color_faithful_checkbox.setChecked(True)
        external_material_reset_checkbox.setChecked(True)
        inject_base_color_checkbox.setChecked(True)
        complete_external_swap_checkbox.setChecked(True)


    complete_swap_material_profile_combo.currentIndexChanged.connect(
        lambda _index: (
            _save_complete_swap_material_profile(),
            _refresh_manual_material_profile_panel(),
            _refresh_global_gloss_reduction_hint(),
            _refresh_true_source_basic_controls_state(),
            _refresh_output_impact_review(),
            _queue_texture_preview_refresh(),
        )
    )
    texture_output_size_combo.currentIndexChanged.connect(_queue_texture_preview_refresh)
    _refresh_sidecar_option_state()
    _refresh_output_impact_review()

    if full_import_model_replacement:
        frozen_tooltip = (
            "Locked by Full Import Model Replacement. Use regular Import Mesh for manual material, "
            "texture, UV, or part mapping."
        )
        material_route_summary_label.setText(
            "Full Import Model Replacement preset locked: imported source owns mesh, material, "
            "and textures. Only placement transform is editable."
        )
        alignment_mode_combo.setCurrentIndex(max(0, alignment_mode_combo.findData("manual")))
        scale_to_length_checkbox.setChecked(True)
        flip_direction_checkbox.setChecked(False)
        for widget in (
            alignment_mode_combo,
            scale_to_length_checkbox,
            flip_direction_checkbox,
            rebuild_sidecar_checkbox,
            prune_unmapped_original_dds_checkbox,
            inject_base_color_checkbox,
            source_color_faithful_checkbox,
            external_material_reset_checkbox,
            complete_external_swap_checkbox,
            complete_swap_material_profile_combo,
            unsafe_material_preflight_checkbox,
            texture_output_size_combo,
            setup_texture_rotate_combo,
            setup_texture_flip_u_checkbox,
            setup_texture_flip_v_checkbox,
            setup_texture_reset_button,
            true_source_basic_group,
            manual_profile_group,
        ):
            widget.setEnabled(False)
            widget.setToolTip(frozen_tooltip)
        true_source_basic_group.setVisible(False)
        manual_profile_group.setVisible(False)
        setup_texture_orientation_widget.setVisible(False)
        texture_orientation_label.setVisible(False)

    alignment_custom_icon_callbacks = create_alignment_custom_icon_callbacks({**context, **globals(), **locals()})
    _alignment_custom_icon_override_spec = alignment_custom_icon_callbacks._alignment_custom_icon_override_spec
    _refresh_alignment_custom_icon_status = alignment_custom_icon_callbacks._refresh_alignment_custom_icon_status
    _choose_alignment_custom_icon_file = alignment_custom_icon_callbacks._choose_alignment_custom_icon_file
    _choose_alignment_custom_icon_folder = alignment_custom_icon_callbacks._choose_alignment_custom_icon_folder
    _choose_alignment_custom_icon_library_source = alignment_custom_icon_callbacks._choose_alignment_custom_icon_library_source
    _capture_alignment_replacement_icon_pixmap = alignment_custom_icon_callbacks._capture_alignment_replacement_icon_pixmap
    _generate_alignment_icon_from_preview = alignment_custom_icon_callbacks._generate_alignment_icon_from_preview

    custom_icon_checkbox.toggled.connect(lambda _checked=False: _refresh_alignment_custom_icon_status())
    custom_icon_source_edit.textChanged.connect(lambda _text="": _refresh_alignment_custom_icon_status())
    custom_icon_target_combo.currentIndexChanged.connect(lambda _index=0: _refresh_alignment_custom_icon_status())
    custom_icon_file_button.clicked.connect(lambda _checked=False: _choose_alignment_custom_icon_file())
    custom_icon_folder_button.clicked.connect(lambda _checked=False: _choose_alignment_custom_icon_folder())
    custom_icon_library_button.clicked.connect(lambda _checked=False: _choose_alignment_custom_icon_library_source())
    generate_alignment_icon_button.clicked.connect(lambda _checked=False: _generate_alignment_icon_from_preview())
    _refresh_alignment_custom_icon_status()

    original_center = _mesh_center_for_ui(original_mesh_for_mapping)
    alignment_transform_control_text = _alignment_transform_control_text_helper()
    transform_layout_specs = _alignment_global_transform_layout_specs_helper()
    transform_group = QGroupBox(alignment_transform_control_text["export_group_title"])
    transform_layout = QGridLayout(transform_group)
    transform_layout.setContentsMargins(*tuple(transform_layout_specs["margins"]))
    transform_layout.setHorizontalSpacing(int(transform_layout_specs["horizontal_spacing"]))
    transform_layout.setVerticalSpacing(int(transform_layout_specs["vertical_spacing"]))
    for column, stretch in tuple(transform_layout_specs["column_stretches"]):
        transform_layout.setColumnStretch(int(column), int(stretch))
    for column, width in tuple(transform_layout_specs["column_minimum_widths"]):
        transform_layout.setColumnMinimumWidth(int(column), int(width))
    transform_layout.addWidget(QLabel(alignment_transform_control_text["export_property_header"]), 0, 0)
    transform_layout.addWidget(QLabel(alignment_transform_control_text["export_original_header"]), 0, 1)
    transform_layout.addWidget(QLabel(alignment_transform_control_text["export_values_header"]), 0, 2)
    transform_spin_specs = _alignment_global_transform_spin_specs_helper()
    offset_x_spin = _make_double_spin_helper(**transform_spin_specs["offset"])
    offset_y_spin = _make_double_spin_helper(**transform_spin_specs["offset"])
    offset_z_spin = _make_double_spin_helper(**transform_spin_specs["offset"])
    rotate_x_spin = _make_double_spin_helper(**transform_spin_specs["rotation"])
    rotate_y_spin = _make_double_spin_helper(**transform_spin_specs["rotation"])
    rotate_z_spin = _make_double_spin_helper(**transform_spin_specs["rotation"])
    scale_x_spin = _make_double_spin_helper(**transform_spin_specs["scale"])
    scale_y_spin = _make_double_spin_helper(**transform_spin_specs["scale"])
    scale_z_spin = _make_double_spin_helper(**transform_spin_specs["scale"])
    for transform_spin in (
        offset_x_spin,
        offset_y_spin,
        offset_z_spin,
        rotate_x_spin,
        rotate_y_spin,
        rotate_z_spin,
        scale_x_spin,
        scale_y_spin,
        scale_z_spin,
    ):
        transform_spin.setMinimumWidth(int(transform_layout_specs["spin_minimum_width"]))
        transform_spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    alignment_transform_sliders: Dict[QDoubleSpinBox, QSlider] = {}
    transform_slider_specs = _alignment_global_transform_slider_specs_helper()

    alignment_transform_slider_callbacks = create_alignment_transform_slider_callbacks({**context, **globals(), **locals()})
    _paired_transform_slider = alignment_transform_slider_callbacks._paired_transform_slider

    _spin_with_slider = lambda spin, *, slider_scale, tooltip, slider_minimum=None, slider_maximum=None: _wrap_spin_with_slider_helper(
        spin,
        _paired_transform_slider(
            spin,
            scale=slider_scale,
            tooltip=tooltip,
            slider_minimum=slider_minimum,
            slider_maximum=slider_maximum,
        ),
    )

    alignment_transform_row_callbacks = create_alignment_transform_row_callbacks({**context, **globals(), **locals()})
    _sync_alignment_transform_slider_from_spin = alignment_transform_row_callbacks._sync_alignment_transform_slider_from_spin
    _add_transform_row = alignment_transform_row_callbacks._add_transform_row

    transform_row_widgets = {
        "offset": (offset_x_spin, offset_y_spin, offset_z_spin),
        "rotation": (rotate_x_spin, rotate_y_spin, rotate_z_spin),
        "scale": (scale_x_spin, scale_y_spin, scale_z_spin),
    }
    transform_original_texts = {
        "original_center": _alignment_transform_location_original_text_helper(original_center),
        "rotation_original": alignment_transform_control_text["rotation_original"],
        "scale_original": alignment_transform_control_text["scale_original"],
    }
    for row_spec in _alignment_global_transform_row_specs_helper():
        _add_transform_row(
            int(row_spec["row_index"]),
            alignment_transform_control_text[str(row_spec["label_key"])],
            transform_original_texts[str(row_spec.get("original_source") or row_spec.get("original_key"))],
            transform_row_widgets[str(row_spec["widget_group"])],
            **transform_slider_specs[str(row_spec["slider_spec"])],
    )
    scale_link_checkbox = QCheckBox(alignment_transform_control_text["link_scale_axes"])
    scale_link_checkbox.setChecked(True)
    transform_layout.addWidget(scale_link_checkbox, 4, 2)
    reset_buttons_by_key = {
        str(spec["key"]): QPushButton(alignment_transform_control_text[str(spec["text_key"])])
        for spec in _alignment_global_transform_reset_button_specs_helper()
    }
    for reset_button in reset_buttons_by_key.values():
        reset_button.setMinimumWidth(int(transform_layout_specs["reset_button_minimum_width"]))
    reset_buttons = QHBoxLayout()
    for spec in _alignment_global_transform_reset_button_specs_helper():
        reset_buttons.addWidget(reset_buttons_by_key[str(spec["key"])])
    transform_layout.addLayout(reset_buttons, 5, 0, 1, 3)
    tilt_step_spin = _make_double_spin_helper(**transform_spin_specs["tilt_step"])
    tilt_step_spin.setMinimumWidth(int(transform_layout_specs["tilt_step_minimum_width"]))
    tilt_step_spin.setToolTip(alignment_transform_control_text["tilt_step_tooltip"])
    tilt_button_row = QHBoxLayout()
    tilt_button_row.addWidget(QLabel(alignment_transform_control_text["tilt_step_label"]))
    tilt_button_row.addWidget(tilt_step_spin)
    tilt_buttons_by_key = {}
    for spec in _alignment_global_transform_tilt_button_specs_helper():
        tilt_button = QPushButton(alignment_transform_control_text[str(spec["text_key"])])
        tilt_button.setMinimumWidth(0)
        tilt_button.setToolTip(alignment_transform_control_text[str(spec["tooltip_key"])])
        tilt_buttons_by_key[str(spec["key"])] = tilt_button
        tilt_button_row.addWidget(tilt_button)
    transform_layout.addLayout(tilt_button_row, 6, 0, 1, 3)
    transform_hint = QLabel(alignment_transform_control_text["hint_html"])
    transform_hint.setWordWrap(True)
    transform_hint.setTextFormat(Qt.RichText)
    transform_hint.setObjectName("HintLabel")
    transform_layout.addWidget(transform_hint, 7, 0, 1, 3)
    transform_section = CollapsibleSection(alignment_transform_control_text["section_title"], expanded=True)
    transform_section.body_layout.addWidget(transform_group)
    setup_layout.addWidget(transform_section)

    scale_syncing = _scale_syncing_initial_state_helper()
    scale_spins = (scale_x_spin, scale_y_spin, scale_z_spin)

    alignment_transform_drag_callbacks = create_alignment_transform_drag_callbacks({**context, **globals(), **locals()})
    _sync_linked_scale = alignment_transform_drag_callbacks._sync_linked_scale
    _commit_global_transform_spin = alignment_transform_drag_callbacks._commit_global_transform_spin
    _global_transform_values = alignment_transform_drag_callbacks._global_transform_values
    _part_transform_values = alignment_transform_drag_callbacks._part_transform_values
    _capture_static_preview_baked_transform_state = alignment_transform_drag_callbacks._capture_static_preview_baked_transform_state
    _active_alignment_transform_preview_widgets = alignment_transform_drag_callbacks._active_alignment_transform_preview_widgets
    _set_global_fast_preview_edit_scope = alignment_transform_drag_callbacks._set_global_fast_preview_edit_scope
    _set_part_fast_preview_edit_scope = alignment_transform_drag_callbacks._set_part_fast_preview_edit_scope
    _queue_alignment_d3d11_fast_transform = alignment_transform_drag_callbacks._queue_alignment_d3d11_fast_transform
    _send_alignment_d3d11_fast_transform_state = alignment_transform_drag_callbacks._send_alignment_d3d11_fast_transform_state
    _replay_alignment_d3d11_fast_transform = alignment_transform_drag_callbacks._replay_alignment_d3d11_fast_transform
    _apply_global_transform_fast_preview = alignment_transform_drag_callbacks._apply_global_transform_fast_preview
    _apply_part_transform_fast_preview = alignment_transform_drag_callbacks._apply_part_transform_fast_preview
    _queue_global_transform_preview_update = alignment_transform_drag_callbacks._queue_global_transform_preview_update
    _queue_part_transform_preview_update = alignment_transform_drag_callbacks._queue_part_transform_preview_update
    _apply_alignment_transform_reset_state = alignment_transform_drag_callbacks._apply_alignment_transform_reset_state
    _reset_location_values = alignment_transform_drag_callbacks._reset_location_values
    _reset_rotation_values = alignment_transform_drag_callbacks._reset_rotation_values
    _reset_scale_values = alignment_transform_drag_callbacks._reset_scale_values
    _reset_placement_values = alignment_transform_drag_callbacks._reset_placement_values
    _nudge_rotation = alignment_transform_drag_callbacks._nudge_rotation
    _current_global_rotation_origin_for_preview = alignment_transform_drag_callbacks._current_global_rotation_origin_for_preview
    _alignment_part_source_indices_for_commit = alignment_transform_drag_callbacks._alignment_part_source_indices_for_commit
    _apply_alignment_part_translation_delta = alignment_transform_drag_callbacks._apply_alignment_part_translation_delta
    _apply_alignment_part_rotation_delta = alignment_transform_drag_callbacks._apply_alignment_part_rotation_delta
    _sync_alignment_preview_rotation_context = alignment_transform_drag_callbacks._sync_alignment_preview_rotation_context
    _prepare_alignment_preview_drag = alignment_transform_drag_callbacks._prepare_alignment_preview_drag
    _prepare_alignment_d3d11_preview_drag = alignment_transform_drag_callbacks._prepare_alignment_d3d11_preview_drag
    _commit_alignment_d3d11_drag_generation = alignment_transform_drag_callbacks._commit_alignment_d3d11_drag_generation
    _set_global_transform_values_for_d3d11_drag = alignment_transform_drag_callbacks._set_global_transform_values_for_d3d11_drag
    _queue_global_transform_values_for_d3d11_drag = alignment_transform_drag_callbacks._queue_global_transform_values_for_d3d11_drag
    _set_selected_part_controls_for_d3d11_drag = alignment_transform_drag_callbacks._set_selected_part_controls_for_d3d11_drag
    _queue_selected_part_controls_for_d3d11_drag = alignment_transform_drag_callbacks._queue_selected_part_controls_for_d3d11_drag
    _flush_alignment_d3d11_drag_ui = alignment_transform_drag_callbacks._flush_alignment_d3d11_drag_ui
    _alignment_d3d11_base_global_transform = alignment_transform_drag_callbacks._alignment_d3d11_base_global_transform
    _alignment_d3d11_base_part_transform = alignment_transform_drag_callbacks._alignment_d3d11_base_part_transform
    _alignment_d3d11_translation_to_transform_units = alignment_transform_drag_callbacks._alignment_d3d11_translation_to_transform_units
    _apply_alignment_d3d11_translation_total = alignment_transform_drag_callbacks._apply_alignment_d3d11_translation_total
    _apply_alignment_d3d11_rotation_total = alignment_transform_drag_callbacks._apply_alignment_d3d11_rotation_total
    _finish_alignment_d3d11_translation = alignment_transform_drag_callbacks._finish_alignment_d3d11_translation
    _finish_alignment_d3d11_rotation = alignment_transform_drag_callbacks._finish_alignment_d3d11_rotation
    _commit_alignment_preview_translation = alignment_transform_drag_callbacks._commit_alignment_preview_translation
    _commit_alignment_preview_rotation = alignment_transform_drag_callbacks._commit_alignment_preview_rotation

    alignment_source_part_mutation_callbacks = create_alignment_source_part_mutation_callbacks({**context, **globals(), **locals()})

    reset_buttons_by_key["location"].clicked.connect(_reset_location_values)
    reset_buttons_by_key["rotation"].clicked.connect(_reset_rotation_values)
    reset_buttons_by_key["scale"].clicked.connect(_reset_scale_values)
    reset_buttons_by_key["placement"].clicked.connect(_reset_placement_values)
    tilt_spins_by_axis = {"x": rotate_x_spin, "y": rotate_y_spin, "z": rotate_z_spin}
    for spec in _alignment_global_transform_tilt_button_specs_helper():
        tilt_buttons_by_key[str(spec["key"])].clicked.connect(
            lambda _checked=False, spec=spec: _nudge_rotation(
                tilt_spins_by_axis[str(spec["axis"])],
                float(spec["direction"]),
            )
        )
    for preview_widget in (static_dialog_preview, overlay_dialog_preview, replacement_only_preview):
        preview_widget.set_alignment_translation_sensitivity(0.85)
        preview_widget.set_alignment_rotation_degrees_per_pixel(0.18)
        preview_widget.alignment_drag_started.connect(
            lambda preview_widget=preview_widget: _prepare_alignment_preview_drag(preview_widget)
        )
        preview_widget.alignment_drag_finished.connect(_commit_alignment_preview_translation)
        preview_widget.alignment_rotation_finished.connect(_commit_alignment_preview_rotation)
        preview_widget.mesh_edit_stroke_started.connect(_mesh_edit_begin_stroke)
        preview_widget.mesh_edit_stroke_previewed.connect(_mesh_edit_apply_preview_payload)
        preview_widget.mesh_edit_stroke_finished.connect(_mesh_edit_finish_stroke)
        preview_widget.mesh_edit_stroke_cancelled.connect(_mesh_edit_cancel_stroke)
        preview_widget.mesh_edit_selection_changed.connect(_mesh_edit_selection_changed)
    alignment_d3d11_preview_host.mesh_edit_stroke_started.connect(_mesh_edit_begin_stroke)
    alignment_d3d11_preview_host.mesh_edit_stroke_previewed.connect(_mesh_edit_apply_preview_payload)
    alignment_d3d11_preview_host.mesh_edit_stroke_finished.connect(_mesh_edit_finish_stroke)
    alignment_d3d11_preview_host.mesh_edit_stroke_cancelled.connect(_mesh_edit_cancel_stroke)
    alignment_d3d11_preview_host.mesh_edit_selection_changed.connect(_mesh_edit_selection_changed)
    alignment_d3d11_preview_host.alignment_drag_started.connect(_prepare_alignment_d3d11_preview_drag)
    alignment_d3d11_preview_host.alignment_drag_changed.connect(_apply_alignment_d3d11_translation_total)
    alignment_d3d11_preview_host.alignment_drag_finished.connect(_finish_alignment_d3d11_translation)
    alignment_d3d11_preview_host.alignment_rotation_changed.connect(_apply_alignment_d3d11_rotation_total)
    alignment_d3d11_preview_host.alignment_rotation_finished.connect(_finish_alignment_d3d11_rotation)
    alignment_d3d11_preview_host.source_part_selected.connect(_d3d11_source_part_selected)
    preview_controls_ready["ready"] = True

    return SimpleNamespace(
        _alignment_custom_icon_override_spec=locals().get('_alignment_custom_icon_override_spec'),
        _basic_controls_profile_enabled=locals().get('_basic_controls_profile_enabled'),
        _capture_static_preview_baked_transform_state=locals().get('_capture_static_preview_baked_transform_state'),
        _coerce_manual_profile_values=locals().get('_coerce_manual_profile_values'),
        _complete_external_swap_enabled=locals().get('_complete_external_swap_enabled'),
        _complete_external_swap_mappings=locals().get('_complete_external_swap_mappings'),
        _current_complete_swap_material_profile_token=locals().get('_current_complete_swap_material_profile_token'),
        _current_manual_material_profile_values=locals().get('_current_manual_material_profile_values'),
        _current_material_authority_preview_profile=locals().get('_current_material_authority_preview_profile'),
        _material_authority_preview_inactive_reason=locals().get('_material_authority_preview_inactive_reason'),
        _material_authority_preview_signature=locals().get('_material_authority_preview_signature'),
        _queue_material_authority_adjustment_preview_refresh=locals().get('_queue_material_authority_adjustment_preview_refresh'),
        _queue_part_transform_preview_update=locals().get('_queue_part_transform_preview_update'),
        _refresh_manual_material_profile_panel=locals().get('_refresh_manual_material_profile_panel'),
        _refresh_manual_profile_control_effects=locals().get('_refresh_manual_profile_control_effects'),
        _refresh_sidecar_option_state=locals().get('_refresh_sidecar_option_state'),
        _replay_alignment_d3d11_fast_transform=locals().get('_replay_alignment_d3d11_fast_transform'),
        _save_complete_swap_material_profile=locals().get('_save_complete_swap_material_profile'),
        _save_manual_profile_presets=locals().get('_save_manual_profile_presets'),
        _select_complete_swap_material_profile=locals().get('_select_complete_swap_material_profile'),
        _set_manual_profile_dirty=locals().get('_set_manual_profile_dirty'),
        _spin_with_slider=locals().get('_spin_with_slider'),
        _sync_alignment_transform_slider_from_spin=locals().get('_sync_alignment_transform_slider_from_spin'),
        accent_glow_slider=locals().get('accent_glow_slider'),
        accent_glow_spin=locals().get('accent_glow_spin'),
        alignment_mode_combo=locals().get('alignment_mode_combo'),
        alignment_transform_control_text=locals().get('alignment_transform_control_text'),
        alignment_transform_sliders=locals().get('alignment_transform_sliders'),
        auto_brightness_slider=locals().get('auto_brightness_slider'),
        auto_brightness_spin=locals().get('auto_brightness_spin'),
        channel_value=locals().get('channel_value'),
        column=locals().get('column'),
        complete_external_swap_checkbox=locals().get('complete_external_swap_checkbox'),
        complete_swap_material_profile_combo=locals().get('complete_swap_material_profile_combo'),
        complete_swap_profile_store_path=locals().get('complete_swap_profile_store_path'),
        custom_icon_checkbox=locals().get('custom_icon_checkbox'),
        custom_icon_file_button=locals().get('custom_icon_file_button'),
        custom_icon_folder_button=locals().get('custom_icon_folder_button'),
        custom_icon_library_button=locals().get('custom_icon_library_button'),
        custom_icon_source_edit=locals().get('custom_icon_source_edit'),
        custom_icon_status=locals().get('custom_icon_status'),
        custom_icon_target_combo=locals().get('custom_icon_target_combo'),
        custom_icon_target_entries=locals().get('custom_icon_target_entries'),
        custom_icon_target_graph=locals().get('custom_icon_target_graph'),
        edge_relief_slider=locals().get('edge_relief_slider'),
        edge_relief_source_combo=locals().get('edge_relief_source_combo'),
        edge_relief_spin=locals().get('edge_relief_spin'),
        external_material_reset_checkbox=locals().get('external_material_reset_checkbox'),
        flip_direction_checkbox=locals().get('flip_direction_checkbox'),
        global_gloss_reduction_hint=locals().get('global_gloss_reduction_hint'),
        global_gloss_reduction_slider=locals().get('global_gloss_reduction_slider'),
        global_gloss_reduction_spin=locals().get('global_gloss_reduction_spin'),
        inject_base_color_checkbox=locals().get('inject_base_color_checkbox'),
        manual_profile_apply_button=locals().get('manual_profile_apply_button'),
        manual_profile_change_status=locals().get('manual_profile_change_status'),
        manual_profile_control_text=locals().get('manual_profile_control_text'),
        manual_profile_control_tooltips=locals().get('manual_profile_control_tooltips'),
        manual_profile_controls=locals().get('manual_profile_controls'),
        manual_profile_default_values=locals().get('manual_profile_default_values'),
        manual_profile_dirty=locals().get('manual_profile_dirty'),
        manual_profile_effect_widgets=locals().get('manual_profile_effect_widgets'),
        manual_profile_group=locals().get('manual_profile_group'),
        manual_profile_layout=locals().get('manual_profile_layout'),
        manual_profile_preset_combo=locals().get('manual_profile_preset_combo'),
        manual_profile_preset_details_edit=locals().get('manual_profile_preset_details_edit'),
        manual_profile_preset_name_edit=locals().get('manual_profile_preset_name_edit'),
        manual_profile_preset_recommended_edit=locals().get('manual_profile_preset_recommended_edit'),
        manual_profile_presets=locals().get('manual_profile_presets'),
        manual_profile_presets_key=locals().get('manual_profile_presets_key'),
        manual_profile_ready=locals().get('manual_profile_ready'),
        manual_profile_saved_values=locals().get('manual_profile_saved_values'),
        manual_profile_settings_key=locals().get('manual_profile_settings_key'),
        object_name=locals().get('object_name'),
        offset_x_spin=locals().get('offset_x_spin'),
        offset_y_spin=locals().get('offset_y_spin'),
        offset_z_spin=locals().get('offset_z_spin'),
        part_glow_color_checkbox=locals().get('part_glow_color_checkbox'),
        part_glow_color_pick_button=locals().get('part_glow_color_pick_button'),
        part_glow_color_spins=locals().get('part_glow_color_spins'),
        profile_name=locals().get('profile_name'),
        prune_unmapped_original_dds_checkbox=locals().get('prune_unmapped_original_dds_checkbox'),
        rebuild_sidecar_checkbox=locals().get('rebuild_sidecar_checkbox'),
        rotate_x_spin=locals().get('rotate_x_spin'),
        rotate_y_spin=locals().get('rotate_y_spin'),
        rotate_z_spin=locals().get('rotate_z_spin'),
        save_generated_icon_to_library_checkbox=locals().get('save_generated_icon_to_library_checkbox'),
        scale_link_checkbox=locals().get('scale_link_checkbox'),
        scale_spins=locals().get('scale_spins'),
        scale_syncing=locals().get('scale_syncing'),
        scale_to_length_checkbox=locals().get('scale_to_length_checkbox'),
        scale_x_spin=locals().get('scale_x_spin'),
        scale_y_spin=locals().get('scale_y_spin'),
        scale_z_spin=locals().get('scale_z_spin'),
        setup_texture_flip_u_checkbox=locals().get('setup_texture_flip_u_checkbox'),
        setup_texture_flip_v_checkbox=locals().get('setup_texture_flip_v_checkbox'),
        setup_texture_rotate_combo=locals().get('setup_texture_rotate_combo'),
        slider_maximum=locals().get('slider_maximum'),
        slider_minimum=locals().get('slider_minimum'),
        slider_scale=locals().get('slider_scale'),
        source_brightness_slider=locals().get('source_brightness_slider'),
        source_brightness_spin=locals().get('source_brightness_spin'),
        source_color_faithful_checkbox=locals().get('source_color_faithful_checkbox'),
        texture_output_size_combo=locals().get('texture_output_size_combo'),
        tilt_step_spin=locals().get('tilt_step_spin'),
        tone_contrast_slider=locals().get('tone_contrast_slider'),
        tone_contrast_spin=locals().get('tone_contrast_spin'),
        tooltip=locals().get('tooltip'),
        transform_layout=locals().get('transform_layout'),
        transform_layout_specs=locals().get('transform_layout_specs'),
        transform_slider_specs=locals().get('transform_slider_specs'),
        true_source_basic_group=locals().get('true_source_basic_group'),
        true_source_basic_hint=locals().get('true_source_basic_hint'),
        true_source_basic_reset_button=locals().get('true_source_basic_reset_button'),
        unsafe_material_preflight_checkbox=locals().get('unsafe_material_preflight_checkbox'),
        width=locals().get('width'),
    )

def create_alignment_mesh_geometry_preview_section(context: dict[str, object]) -> SimpleNamespace:
    Dict = context.get('Dict')
    MESH_EDIT_DELETE_MODE_OPTIONS = context.get('MESH_EDIT_DELETE_MODE_OPTIONS')
    MESH_EDIT_FALLOFF_OPTIONS = context.get('MESH_EDIT_FALLOFF_OPTIONS')
    MESH_EDIT_SCOPE_OPTIONS = context.get('MESH_EDIT_SCOPE_OPTIONS')
    MESH_EDIT_SELECTION_DEPTH_OPTIONS = context.get('MESH_EDIT_SELECTION_DEPTH_OPTIONS')
    MESH_EDIT_SELECTION_MODE_OPTIONS = context.get('MESH_EDIT_SELECTION_MODE_OPTIONS')
    MESH_EDIT_TOOL_BUTTON_OPTIONS = context.get('MESH_EDIT_TOOL_BUTTON_OPTIONS')
    MESH_EDIT_TOOL_OPTIONS = context.get('MESH_EDIT_TOOL_OPTIONS')
    NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS = context.get('NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS')
    QCheckBox = context.get('QCheckBox')
    QComboBox = context.get('QComboBox')
    QFrame = context.get('QFrame')
    QGroupBox = context.get('QGroupBox')
    QHBoxLayout = context.get('QHBoxLayout')
    QLabel = context.get('QLabel')
    QMenu = context.get('QMenu')
    QPushButton = context.get('QPushButton')
    QSizePolicy = context.get('QSizePolicy')
    QSpinBox = context.get('QSpinBox')
    QToolButton = context.get('QToolButton')
    QVBoxLayout = context.get('QVBoxLayout')
    QWidget = context.get('QWidget')
    Qt = context.get('Qt')
    Tuple = context.get('Tuple')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _alignment_startup_step = context.get('_alignment_startup_step')
    _apply_native_preview_core_material_manifest_helper = context.get('_apply_native_preview_core_material_manifest_helper')
    _basic_controls_profile_enabled = context.get('_basic_controls_profile_enabled')
    _clear_part_selections_when_leaving_geometry = context.get('_clear_part_selections_when_leaving_geometry')
    _current_complete_swap_material_profile_token = context.get('_current_complete_swap_material_profile_token')
    _current_material_authority_preview_profile = context.get('_current_material_authority_preview_profile')
    _enabled_renderable_source_indices = context.get('_enabled_renderable_source_indices')
    _geometry_mapping_summary_html_helper = context.get('_geometry_mapping_summary_html_helper')
    _handle_original_reference_texture_preview_error = context.get('_handle_original_reference_texture_preview_error')
    _is_marker_source = context.get('_is_marker_source')
    _load_native_preview_core_material_manifest_for_alignment_helper = context.get('_load_native_preview_core_material_manifest_for_alignment_helper')
    _load_selected_part_controls = context.get('_load_selected_part_controls')
    _make_double_spin_helper = context.get('_make_double_spin_helper')
    _material_authority_preview_inactive_reason = context.get('_material_authority_preview_inactive_reason')
    _material_authority_preview_signature = context.get('_material_authority_preview_signature')
    _mesh_edit_action_control_text_helper = context.get('_mesh_edit_action_control_text_helper')
    _mesh_edit_dialog_title_helper = context.get('_mesh_edit_dialog_title_helper')
    _morph_slider_add_target_action_text_helper = context.get('_morph_slider_add_target_action_text_helper')
    _morph_slider_bake_action_text_helper = context.get('_morph_slider_bake_action_text_helper')
    _morph_slider_bake_action_tooltip_helper = context.get('_morph_slider_bake_action_tooltip_helper')
    _morph_slider_create_action_text_helper = context.get('_morph_slider_create_action_text_helper')
    _morph_slider_create_action_tooltip_helper = context.get('_morph_slider_create_action_tooltip_helper')
    _morph_slider_import_action_text_helper = context.get('_morph_slider_import_action_text_helper')
    _morph_slider_manage_action_text_helper = context.get('_morph_slider_manage_action_text_helper')
    _morph_slider_manage_action_tooltip_helper = context.get('_morph_slider_manage_action_tooltip_helper')
    _morph_slider_reload_action_text_helper = context.get('_morph_slider_reload_action_text_helper')
    _morph_slider_reset_action_text_helper = context.get('_morph_slider_reset_action_text_helper')
    _morph_slider_status_text_helper = context.get('_morph_slider_status_text_helper')
    _morph_slider_title_text_helper = context.get('_morph_slider_title_text_helper')
    _native_manifest_input_from_descriptor = context.get('_native_manifest_input_from_descriptor')
    _original_reference_texture_preview_clear_native_package_path_helper = context.get('_original_reference_texture_preview_clear_native_package_path_helper')
    _original_reference_texture_preview_set_native_package_path_helper = context.get('_original_reference_texture_preview_set_native_package_path_helper')
    _original_selection_changed = context.get('_original_selection_changed')
    _parse_mapping_edit = context.get('_parse_mapping_edit')
    _populate_combo_options_helper = context.get('_populate_combo_options_helper')
    _queue_static_preview_refresh = context.get('_queue_static_preview_refresh')
    _record_runtime_event = context.get('_record_runtime_event')
    _refresh_mesh_editor_diagnostics = context.get('_refresh_mesh_editor_diagnostics')
    _refresh_source_assignment_columns = context.get('_refresh_source_assignment_columns')
    _refresh_source_tree_selection_state = context.get('_refresh_source_tree_selection_state')
    _source_part_properties_control_text_helper = context.get('_source_part_properties_control_text_helper')
    _source_selection_changed = context.get('_source_selection_changed')
    _target_selection_changed = context.get('_target_selection_changed')
    _update_mapping_status = context.get('_update_mapping_status')
    _update_selection_context = context.get('_update_selection_context')
    alignment_startup_text = context.get('alignment_startup_text')
    any = _context_builtin(context, 'any')
    args = context.get('args')
    bool = _context_builtin(context, 'bool')
    control_tabs = context.get('control_tabs')
    create_alignment_mesh_edit_callbacks = context.get('create_alignment_mesh_edit_callbacks')
    create_alignment_original_texture_worker_callbacks = context.get('create_alignment_original_texture_worker_callbacks')
    create_alignment_preview_model_callbacks = context.get('create_alignment_preview_model_callbacks')
    create_alignment_static_preview_refresh_callbacks = context.get('create_alignment_static_preview_refresh_callbacks')
    diagnostics_tab = context.get('diagnostics_tab')
    dialog = context.get('dialog')
    dialog_title = context.get('dialog_title')
    entry = context.get('entry')
    getattr = _context_builtin(context, 'getattr')
    globals = _context_builtin(context, 'globals')
    index = context.get('index')
    kwargs = context.get('kwargs')
    label_text = context.get('label_text')
    len = _context_builtin(context, 'len')
    locals = _context_builtin(context, 'locals')
    mapping_edits = context.get('mapping_edits')
    mapping_tree = context.get('mapping_tree')
    max = _context_builtin(context, 'max')
    mesh_edit_layout_page = context.get('mesh_edit_layout_page')
    mesh_edit_page = context.get('mesh_edit_page')
    object_name = context.get('object_name')
    original_reference_texture_preview_state = context.get('original_reference_texture_preview_state')
    original_tree = context.get('original_tree')
    package_path = context.get('package_path')
    package_root_text = context.get('package_root_text')
    preview_model = context.get('preview_model')
    _get_preview_render_settings = context.get('_get_preview_render_settings')
    preview_render_settings = context.get('preview_render_settings')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    row_key = context.get('row_key')
    run_native_preview_core_preview_job = context.get('run_native_preview_core_preview_job')
    selected_tool = context.get('selected_tool')
    self = context.get('self')
    source_tree = context.get('source_tree')
    static_preview_refresh_timer = context.get('static_preview_refresh_timer')
    static_preview_settle_timer = context.get('static_preview_settle_timer')
    str = _context_builtin(context, 'str')
    sum = _context_builtin(context, 'sum')
    target_preview_model = context.get('target_preview_model')
    widget = context.get('widget')

    def _current_preview_render_settings() -> object:
        if callable(_get_preview_render_settings):
            return _get_preview_render_settings()
        return preview_render_settings

    mesh_edit_supported = bool(
        replacement_mesh_for_mapping is not None
        and any(
            bool(getattr(source, "vertices", None))
            and bool(getattr(source, "faces", None))
            and not _is_marker_source(source)
            for source in getattr(replacement_mesh_for_mapping, "submeshes", ()) or ()
        )
    )
    mesh_edit_group = QFrame(mesh_edit_page)
    mesh_edit_group.setObjectName("MeshEditVerticalToolbox")
    mesh_edit_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    mesh_edit_layout = QVBoxLayout(mesh_edit_group)
    mesh_edit_layout.setContentsMargins(8, 4, 8, 4)
    mesh_edit_layout.setSpacing(4)
    mesh_edit_action_control_text = _mesh_edit_action_control_text_helper()
    mesh_edit_title_label = QLabel(_mesh_edit_dialog_title_helper())
    mesh_edit_title_label.setObjectName("SectionLabel")
    mesh_edit_enabled_checkbox = QCheckBox(mesh_edit_action_control_text["edit_mode"])
    mesh_edit_enabled_checkbox.setObjectName("MeshEditModeCheckbox")
    mesh_edit_enabled_checkbox.setToolTip(mesh_edit_action_control_text["edit_mode_tooltip"])
    mesh_edit_scope_combo = QComboBox()
    _populate_combo_options_helper(mesh_edit_scope_combo, MESH_EDIT_SCOPE_OPTIONS)
    mesh_edit_scope_combo.setToolTip(mesh_edit_action_control_text["scope_combo_tooltip"])
    mesh_edit_part_combo = QComboBox()
    mesh_edit_part_combo.setToolTip(mesh_edit_action_control_text["part_combo_tooltip"])
    mesh_edit_tool_combo = QComboBox()
    _populate_combo_options_helper(mesh_edit_tool_combo, MESH_EDIT_TOOL_OPTIONS)
    mesh_edit_tool_combo.setVisible(False)
    mesh_edit_tool_palette = QFrame(mesh_edit_group)
    mesh_edit_tool_palette.setObjectName("MeshEditVerticalToolPalette")
    mesh_edit_tool_palette_layout = QVBoxLayout(mesh_edit_tool_palette)
    mesh_edit_tool_palette_layout.setContentsMargins(0, 0, 0, 0)
    mesh_edit_tool_palette_layout.setSpacing(3)
    mesh_edit_tool_buttons: Dict[str, QToolButton] = {}
    for label, tool, tooltip in MESH_EDIT_TOOL_BUTTON_OPTIONS:
        button = QToolButton(mesh_edit_tool_palette)
        button.setText(label)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setChecked(tool == "grab")
        button.setMinimumHeight(24)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setToolTip(tooltip)
        button.clicked.connect(
            lambda _checked=False, selected_tool=tool: mesh_edit_tool_combo.setCurrentIndex(
                max(0, mesh_edit_tool_combo.findData(selected_tool))
            )
        )
        mesh_edit_tool_buttons[tool] = button
        mesh_edit_tool_palette_layout.addWidget(button)
    mesh_edit_delete_mode_combo = QComboBox()
    _populate_combo_options_helper(mesh_edit_delete_mode_combo, MESH_EDIT_DELETE_MODE_OPTIONS)
    mesh_edit_delete_mode_combo.setToolTip(mesh_edit_action_control_text["delete_mode_tooltip"])
    mesh_edit_radius_spin = _make_double_spin_helper(24.0, 2.0, 256.0, 0, 2.0, " px")
    mesh_edit_strength_spin = _make_double_spin_helper(50.0, 0.0, 100.0, 0, 5.0, "%")
    mesh_edit_falloff_combo = QComboBox()
    _populate_combo_options_helper(mesh_edit_falloff_combo, MESH_EDIT_FALLOFF_OPTIONS)
    mesh_edit_iterations_spin = QSpinBox()
    mesh_edit_iterations_spin.setRange(1, 12)
    mesh_edit_iterations_spin.setValue(3)
    mesh_edit_iterations_spin.setToolTip(mesh_edit_action_control_text["iterations_tooltip"])
    mesh_edit_selection_mode_combo = QComboBox()
    _populate_combo_options_helper(mesh_edit_selection_mode_combo, MESH_EDIT_SELECTION_MODE_OPTIONS)
    mesh_edit_selection_mode_combo.setToolTip(mesh_edit_action_control_text["selection_mode_tooltip"])
    mesh_edit_selection_depth_combo = QComboBox()
    _populate_combo_options_helper(mesh_edit_selection_depth_combo, MESH_EDIT_SELECTION_DEPTH_OPTIONS)
    mesh_edit_selection_depth_combo.setToolTip(mesh_edit_action_control_text["selection_depth_tooltip"])
    mesh_edit_mirror_checkbox = QCheckBox(mesh_edit_action_control_text["mirror_checkbox"])
    mesh_edit_show_vertices_checkbox = QCheckBox(mesh_edit_action_control_text["show_vertices_checkbox"])
    mesh_edit_show_vertices_checkbox.setChecked(True)
    mesh_edit_clear_selection_button = QPushButton(mesh_edit_action_control_text["clear_selection"])
    mesh_edit_select_part_button = QPushButton(mesh_edit_action_control_text["select_part"])
    mesh_edit_invert_selection_button = QPushButton(mesh_edit_action_control_text["invert_selection"])
    mesh_edit_grow_selection_button = QPushButton(mesh_edit_action_control_text["grow_selection"])
    mesh_edit_shrink_selection_button = QPushButton(mesh_edit_action_control_text["shrink_selection"])
    mesh_edit_smooth_selection_button = QPushButton(mesh_edit_action_control_text["smooth_selection"])
    mesh_edit_subdivide_selection_button = QPushButton(mesh_edit_action_control_text["subdivide_selection"])
    mesh_edit_select_part_button.setToolTip(mesh_edit_action_control_text["select_part_tooltip"])
    mesh_edit_invert_selection_button.setToolTip(mesh_edit_action_control_text["invert_selection_tooltip"])
    mesh_edit_subdivide_selection_button.setToolTip(mesh_edit_action_control_text["subdivide_selection_tooltip"])
    mesh_edit_delete_faces_button = QPushButton(mesh_edit_action_control_text["delete_faces"])
    mesh_edit_delete_faces_button.setToolTip(mesh_edit_action_control_text["delete_faces_tooltip"])
    mesh_edit_undo_button = QPushButton(mesh_edit_action_control_text["undo"])
    mesh_edit_redo_button = QPushButton(mesh_edit_action_control_text["redo"])
    mesh_edit_reset_part_button = QPushButton(mesh_edit_action_control_text["reset_scope"])
    mesh_edit_full_reset_button = QPushButton(mesh_edit_action_control_text["full_reset_mesh"])
    for mesh_edit_button in (
        mesh_edit_clear_selection_button,
        mesh_edit_select_part_button,
        mesh_edit_invert_selection_button,
        mesh_edit_grow_selection_button,
        mesh_edit_shrink_selection_button,
        mesh_edit_smooth_selection_button,
        mesh_edit_subdivide_selection_button,
        mesh_edit_delete_faces_button,
        mesh_edit_undo_button,
        mesh_edit_redo_button,
        mesh_edit_reset_part_button,
        mesh_edit_full_reset_button,
    ):
        mesh_edit_button.setMinimumWidth(0)
    mesh_edit_status_label = QLabel(mesh_edit_action_control_text["initial_status"])
    mesh_edit_status_label.setObjectName("HintLabel")
    mesh_edit_status_label.setWordWrap(True)
    mesh_edit_status_label.setMaximumHeight(54)

    morph_slider_group = QFrame(mesh_edit_page)
    morph_slider_group.setObjectName("MorphSliderToolbox")
    morph_slider_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    morph_slider_layout = QVBoxLayout(morph_slider_group)
    morph_slider_layout.setContentsMargins(8, 5, 8, 5)
    morph_slider_layout.setSpacing(4)
    morph_slider_title_label = QLabel(_morph_slider_title_text_helper())
    morph_slider_title_label.setObjectName("SectionLabel")
    morph_slider_status_label = QLabel(
        _morph_slider_status_text_helper(
            supported=True,
            blocked=False,
            block_reason="",
            loaded=False,
            profile_count=0,
            slider_count=0,
        )
    )
    morph_slider_status_label.setObjectName("HintLabel")
    morph_slider_status_label.setWordWrap(True)
    morph_slider_rows_widget = QWidget(morph_slider_group)
    morph_slider_rows_layout = QVBoxLayout(morph_slider_rows_widget)
    morph_slider_rows_layout.setContentsMargins(0, 0, 0, 0)
    morph_slider_rows_layout.setSpacing(3)
    morph_slider_create_button = QPushButton(_morph_slider_create_action_text_helper())
    morph_slider_create_button.setToolTip(_morph_slider_create_action_tooltip_helper())
    morph_slider_manage_button = QPushButton(_morph_slider_manage_action_text_helper())
    morph_slider_manage_button.setToolTip(_morph_slider_manage_action_tooltip_helper())
    morph_slider_manage_menu = QMenu(morph_slider_manage_button)
    morph_slider_import_action = morph_slider_manage_menu.addAction(_morph_slider_import_action_text_helper())
    morph_slider_add_action = morph_slider_manage_menu.addAction(_morph_slider_add_target_action_text_helper())
    morph_slider_manage_menu.addSeparator()
    morph_slider_reload_action = morph_slider_manage_menu.addAction(_morph_slider_reload_action_text_helper())
    morph_slider_manage_button.setMenu(morph_slider_manage_menu)
    morph_slider_reset_button = QPushButton(_morph_slider_reset_action_text_helper())
    morph_slider_bake_button = QPushButton(_morph_slider_bake_action_text_helper())
    morph_slider_bake_button.setToolTip(_morph_slider_bake_action_tooltip_helper())
    morph_slider_button_row = QHBoxLayout()
    morph_slider_button_row.setContentsMargins(0, 0, 0, 0)
    morph_slider_button_row.setSpacing(3)
    morph_slider_button_row.addWidget(morph_slider_create_button)
    morph_slider_button_row.addWidget(morph_slider_manage_button)
    morph_slider_button_row.addStretch(1)
    morph_slider_reset_bake_row = QHBoxLayout()
    morph_slider_reset_bake_row.setContentsMargins(0, 0, 0, 0)
    morph_slider_reset_bake_row.setSpacing(3)
    morph_slider_reset_bake_row.addWidget(morph_slider_reset_button)
    morph_slider_reset_bake_row.addWidget(morph_slider_bake_button)
    morph_slider_reset_bake_row.addStretch(1)
    morph_slider_layout.addWidget(morph_slider_title_label)
    morph_slider_layout.addWidget(morph_slider_status_label)
    morph_slider_layout.addWidget(morph_slider_rows_widget)
    morph_slider_layout.addLayout(morph_slider_button_row)
    morph_slider_layout.addLayout(morph_slider_reset_bake_row)

    mesh_edit_field_rows: Dict[str, Tuple[QLabel, QWidget]] = {}

    def _mesh_edit_field(row_key: str, label_text: str, widget: QWidget) -> None:
        label = QLabel(label_text)
        label.setObjectName("HintLabel")
        mesh_edit_layout.addWidget(label)
        mesh_edit_layout.addWidget(widget)
        mesh_edit_field_rows[str(row_key)] = (label, widget)

    mesh_edit_layout.addWidget(mesh_edit_title_label)
    mesh_edit_layout.addWidget(mesh_edit_enabled_checkbox)
    _mesh_edit_field("scope", mesh_edit_action_control_text["scope_label"], mesh_edit_scope_combo)
    _mesh_edit_field("part", mesh_edit_action_control_text["part_label"], mesh_edit_part_combo)
    mesh_edit_layout.addWidget(QLabel(mesh_edit_action_control_text["tool_label"]))
    mesh_edit_layout.addWidget(mesh_edit_tool_palette)
    mesh_edit_remove_mode_label = QLabel(mesh_edit_action_control_text["remove_mode_label"])
    mesh_edit_remove_mode_label.setObjectName("HintLabel")
    mesh_edit_layout.addWidget(mesh_edit_remove_mode_label)
    mesh_edit_layout.addWidget(mesh_edit_delete_mode_combo)
    _mesh_edit_field("radius", mesh_edit_action_control_text["radius_label"], mesh_edit_radius_spin)
    _mesh_edit_field("strength", mesh_edit_action_control_text["strength_label"], mesh_edit_strength_spin)
    _mesh_edit_field("falloff", mesh_edit_action_control_text["falloff_label"], mesh_edit_falloff_combo)
    _mesh_edit_field("iterations", mesh_edit_action_control_text["iterations_label"], mesh_edit_iterations_spin)
    _mesh_edit_field("selection", mesh_edit_action_control_text["selection_label"], mesh_edit_selection_mode_combo)
    _mesh_edit_field("depth", mesh_edit_action_control_text["depth_label"], mesh_edit_selection_depth_combo)
    mesh_edit_option_widget = QWidget(mesh_edit_group)
    mesh_edit_option_row = QHBoxLayout(mesh_edit_option_widget)
    mesh_edit_option_row.setContentsMargins(0, 0, 0, 0)
    mesh_edit_option_row.setSpacing(4)
    mesh_edit_option_row.addWidget(mesh_edit_mirror_checkbox)
    mesh_edit_option_row.addWidget(mesh_edit_show_vertices_checkbox)
    mesh_edit_option_row.addStretch(1)
    mesh_edit_layout.addWidget(mesh_edit_option_widget)
    mesh_edit_selection_actions_widget = QWidget(mesh_edit_group)
    mesh_edit_selection_button_row = QHBoxLayout(mesh_edit_selection_actions_widget)
    mesh_edit_selection_button_row.setContentsMargins(0, 0, 0, 0)
    mesh_edit_selection_button_row.setSpacing(3)
    mesh_edit_selection_button_row.addWidget(mesh_edit_grow_selection_button)
    mesh_edit_selection_button_row.addWidget(mesh_edit_shrink_selection_button)
    mesh_edit_selection_button_row.addWidget(mesh_edit_smooth_selection_button)
    mesh_edit_layout.addWidget(mesh_edit_clear_selection_button)
    mesh_edit_layout.addWidget(mesh_edit_select_part_button)
    mesh_edit_layout.addWidget(mesh_edit_invert_selection_button)
    mesh_edit_layout.addWidget(mesh_edit_selection_actions_widget)
    mesh_edit_layout.addWidget(mesh_edit_subdivide_selection_button)
    mesh_edit_layout.addWidget(mesh_edit_delete_faces_button)
    mesh_edit_button_row = QHBoxLayout()
    mesh_edit_button_row.setContentsMargins(0, 0, 0, 0)
    mesh_edit_button_row.setSpacing(3)
    mesh_edit_button_row.addWidget(mesh_edit_undo_button)
    mesh_edit_button_row.addWidget(mesh_edit_redo_button)
    alignment_mesh_edit_callbacks = create_alignment_mesh_edit_callbacks({**context, **globals(), **locals()})
    _mesh_edit_adjusted_sources_for_live_preview = alignment_mesh_edit_callbacks._mesh_edit_adjusted_sources_for_live_preview
    _mesh_edit_all_live_vertices_for_sources = alignment_mesh_edit_callbacks._mesh_edit_all_live_vertices_for_sources
    _mesh_edit_all_vertices_in_scope = alignment_mesh_edit_callbacks._mesh_edit_all_vertices_in_scope
    _mesh_edit_allowed_source_indices = alignment_mesh_edit_callbacks._mesh_edit_allowed_source_indices
    _mesh_edit_apply_preview_payload = alignment_mesh_edit_callbacks._mesh_edit_apply_preview_payload
    _mesh_edit_base_source_index_is_editable = alignment_mesh_edit_callbacks._mesh_edit_base_source_index_is_editable
    _mesh_edit_begin_stroke = alignment_mesh_edit_callbacks._mesh_edit_begin_stroke
    _mesh_edit_can_edit_scope = alignment_mesh_edit_callbacks._mesh_edit_can_edit_scope
    _mesh_edit_cancel_stroke = alignment_mesh_edit_callbacks._mesh_edit_cancel_stroke
    _mesh_edit_clear_topology_selection = alignment_mesh_edit_callbacks._mesh_edit_clear_topology_selection
    _mesh_edit_clear_vertex_selection = alignment_mesh_edit_callbacks._mesh_edit_clear_vertex_selection
    _mesh_edit_commit_working_mesh = alignment_mesh_edit_callbacks._mesh_edit_commit_working_mesh
    _mesh_edit_control_tab_changed = alignment_mesh_edit_callbacks._mesh_edit_control_tab_changed
    _mesh_edit_current_tool = alignment_mesh_edit_callbacks._mesh_edit_current_tool
    _mesh_edit_delete_selected_faces = alignment_mesh_edit_callbacks._mesh_edit_delete_selected_faces
    _mesh_edit_disable_emptied_parts = alignment_mesh_edit_callbacks._mesh_edit_disable_emptied_parts
    _mesh_edit_enabled_toggled = alignment_mesh_edit_callbacks._mesh_edit_enabled_toggled
    _mesh_edit_faces_from_payload = alignment_mesh_edit_callbacks._mesh_edit_faces_from_payload
    _mesh_edit_finish_stroke = alignment_mesh_edit_callbacks._mesh_edit_finish_stroke
    _mesh_edit_full_reset_mesh = alignment_mesh_edit_callbacks._mesh_edit_full_reset_mesh
    _mesh_edit_grow_selection = alignment_mesh_edit_callbacks._mesh_edit_grow_selection
    _mesh_edit_invert_selection = alignment_mesh_edit_callbacks._mesh_edit_invert_selection
    _mesh_edit_live_vertex_update_groups = alignment_mesh_edit_callbacks._mesh_edit_live_vertex_update_groups
    _mesh_edit_merge_face_groups = alignment_mesh_edit_callbacks._mesh_edit_merge_face_groups
    _mesh_edit_merge_vertex_groups = alignment_mesh_edit_callbacks._mesh_edit_merge_vertex_groups
    _mesh_edit_part_enabled_snapshot = alignment_mesh_edit_callbacks._mesh_edit_part_enabled_snapshot
    _mesh_edit_payload_has_drag_motion = alignment_mesh_edit_callbacks._mesh_edit_payload_has_drag_motion
    _mesh_edit_pop_undo_snapshot = alignment_mesh_edit_callbacks._mesh_edit_pop_undo_snapshot
    _mesh_edit_preview_delta_to_source_delta = alignment_mesh_edit_callbacks._mesh_edit_preview_delta_to_source_delta
    _mesh_edit_preview_distance_to_source_distance = alignment_mesh_edit_callbacks._mesh_edit_preview_distance_to_source_distance
    _mesh_edit_preview_point_to_source_point = alignment_mesh_edit_callbacks._mesh_edit_preview_point_to_source_point
    _mesh_edit_preview_source_indices = alignment_mesh_edit_callbacks._mesh_edit_preview_source_indices
    _mesh_edit_preview_to_source_point = alignment_mesh_edit_callbacks._mesh_edit_preview_to_source_point
    _mesh_edit_preview_to_source_vector = alignment_mesh_edit_callbacks._mesh_edit_preview_to_source_vector
    _mesh_edit_push_undo_snapshot = alignment_mesh_edit_callbacks._mesh_edit_push_undo_snapshot
    _mesh_edit_record_snapshot = alignment_mesh_edit_callbacks._mesh_edit_record_snapshot
    _mesh_edit_redo = alignment_mesh_edit_callbacks._mesh_edit_redo
    _mesh_edit_replace_live_triangles = alignment_mesh_edit_callbacks._mesh_edit_replace_live_triangles
    _mesh_edit_replace_working_mesh = alignment_mesh_edit_callbacks._mesh_edit_replace_working_mesh
    _mesh_edit_reset_scope = alignment_mesh_edit_callbacks._mesh_edit_reset_scope
    _mesh_edit_restore_enabled_snapshot = alignment_mesh_edit_callbacks._mesh_edit_restore_enabled_snapshot
    _mesh_edit_restore_snapshot = alignment_mesh_edit_callbacks._mesh_edit_restore_snapshot
    _mesh_edit_scope_mode = alignment_mesh_edit_callbacks._mesh_edit_scope_mode
    _mesh_edit_select_whole_part = alignment_mesh_edit_callbacks._mesh_edit_select_whole_part
    _mesh_edit_selected_scope_source_index = alignment_mesh_edit_callbacks._mesh_edit_selected_scope_source_index
    _mesh_edit_selected_source_index = alignment_mesh_edit_callbacks._mesh_edit_selected_source_index
    _mesh_edit_selection_changed = alignment_mesh_edit_callbacks._mesh_edit_selection_changed
    _mesh_edit_selection_depth_mode = alignment_mesh_edit_callbacks._mesh_edit_selection_depth_mode
    _mesh_edit_selection_mode = alignment_mesh_edit_callbacks._mesh_edit_selection_mode
    _mesh_edit_set_vertex_selection = alignment_mesh_edit_callbacks._mesh_edit_set_vertex_selection
    _mesh_edit_shrink_selection = alignment_mesh_edit_callbacks._mesh_edit_shrink_selection
    _mesh_edit_smooth_selection = alignment_mesh_edit_callbacks._mesh_edit_smooth_selection
    _mesh_edit_source_index_is_editable = alignment_mesh_edit_callbacks._mesh_edit_source_index_is_editable
    _mesh_edit_source_to_preview_point = alignment_mesh_edit_callbacks._mesh_edit_source_to_preview_point
    _mesh_edit_stroke_id = alignment_mesh_edit_callbacks._mesh_edit_stroke_id
    _mesh_edit_subdivide_selection = alignment_mesh_edit_callbacks._mesh_edit_subdivide_selection
    _mesh_edit_submesh_for_live_preview = alignment_mesh_edit_callbacks._mesh_edit_submesh_for_live_preview
    _mesh_edit_target_mode_for_tool = alignment_mesh_edit_callbacks._mesh_edit_target_mode_for_tool
    _mesh_edit_transformed_sources_for_live_preview = alignment_mesh_edit_callbacks._mesh_edit_transformed_sources_for_live_preview
    _mesh_edit_triangle_replace_groups = alignment_mesh_edit_callbacks._mesh_edit_triangle_replace_groups
    _mesh_edit_undo = alignment_mesh_edit_callbacks._mesh_edit_undo
    _mesh_edit_update_live_preview = alignment_mesh_edit_callbacks._mesh_edit_update_live_preview
    _mesh_edit_update_mesh_totals = alignment_mesh_edit_callbacks._mesh_edit_update_mesh_totals
    _mesh_edit_vertices_from_payload = alignment_mesh_edit_callbacks._mesh_edit_vertices_from_payload
    _morph_slider_active_deltas = alignment_mesh_edit_callbacks._morph_slider_active_deltas
    _morph_slider_add_row = alignment_mesh_edit_callbacks._morph_slider_add_row
    _morph_slider_add_target = alignment_mesh_edit_callbacks._morph_slider_add_target
    _morph_slider_apply_to_working_mesh = alignment_mesh_edit_callbacks._morph_slider_apply_to_working_mesh
    _morph_slider_bake = alignment_mesh_edit_callbacks._morph_slider_bake
    _morph_slider_begin_change = alignment_mesh_edit_callbacks._morph_slider_begin_change
    _morph_slider_capture_post_edit_deltas = alignment_mesh_edit_callbacks._morph_slider_capture_post_edit_deltas
    _morph_slider_clear_rows = alignment_mesh_edit_callbacks._morph_slider_clear_rows
    _morph_slider_create_from_selection = alignment_mesh_edit_callbacks._morph_slider_create_from_selection
    _morph_slider_default_region_amount = alignment_mesh_edit_callbacks._morph_slider_default_region_amount
    _morph_slider_end_change = alignment_mesh_edit_callbacks._morph_slider_end_change
    _morph_slider_ensure_post_edit_deltas = alignment_mesh_edit_callbacks._morph_slider_ensure_post_edit_deltas
    _morph_slider_has_loaded_deltas = alignment_mesh_edit_callbacks._morph_slider_has_loaded_deltas
    _morph_slider_has_nonzero_values = alignment_mesh_edit_callbacks._morph_slider_has_nonzero_values
    _morph_slider_import_pack = alignment_mesh_edit_callbacks._morph_slider_import_pack
    _morph_slider_mark_topology_changed = alignment_mesh_edit_callbacks._morph_slider_mark_topology_changed
    _morph_slider_rebuild_rows = alignment_mesh_edit_callbacks._morph_slider_rebuild_rows
    _morph_slider_refresh_controls = alignment_mesh_edit_callbacks._morph_slider_refresh_controls
    _morph_slider_refresh_topology_block_state = alignment_mesh_edit_callbacks._morph_slider_refresh_topology_block_state
    _morph_slider_reload_profiles = alignment_mesh_edit_callbacks._morph_slider_reload_profiles
    _morph_slider_reset_all = alignment_mesh_edit_callbacks._morph_slider_reset_all
    _morph_slider_set_value = alignment_mesh_edit_callbacks._morph_slider_set_value
    _morph_slider_slider_only_mesh = alignment_mesh_edit_callbacks._morph_slider_slider_only_mesh
    _morph_slider_supported = alignment_mesh_edit_callbacks._morph_slider_supported
    _morph_slider_sync_row_widgets = alignment_mesh_edit_callbacks._morph_slider_sync_row_widgets
    _morph_slider_zero_post_edit_deltas = alignment_mesh_edit_callbacks._morph_slider_zero_post_edit_deltas
    _morph_slider_zero_post_edit_deltas_for_sources = alignment_mesh_edit_callbacks._morph_slider_zero_post_edit_deltas_for_sources
    _refresh_mesh_edit_controls = alignment_mesh_edit_callbacks._refresh_mesh_edit_controls
    _refresh_mesh_edit_part_combo = alignment_mesh_edit_callbacks._refresh_mesh_edit_part_combo
    _sync_mesh_edit_preview_settings = alignment_mesh_edit_callbacks._sync_mesh_edit_preview_settings

    mesh_edit_layout_page.addWidget(mesh_edit_group, 0)
    mesh_edit_layout_page.addWidget(morph_slider_group, 0)
    mesh_edit_layout_page.addStretch(1)

    source_tree.currentItemChanged.connect(_source_selection_changed)
    source_tree.itemSelectionChanged.connect(_refresh_source_tree_selection_state)
    original_tree.currentItemChanged.connect(_original_selection_changed)
    mapping_tree.currentItemChanged.connect(_target_selection_changed)
    control_tabs.currentChanged.connect(_clear_part_selections_when_leaving_geometry)
    control_tabs.currentChanged.connect(_mesh_edit_control_tab_changed)
    control_tabs.currentChanged.connect(lambda _index: _update_selection_context())
    control_tabs.currentChanged.connect(
        lambda index: _refresh_mesh_editor_diagnostics()
        if control_tabs.widget(index) is diagnostics_tab
        else None
    )
    _refresh_source_assignment_columns()
    _load_selected_part_controls()
    _refresh_mesh_edit_controls()
    _update_mapping_status()
    _update_selection_context()
    _alignment_startup_step(alignment_startup_text["geometry_controls"])
    geometry_overview_group = QWidget()
    geometry_overview_layout = QVBoxLayout(geometry_overview_group)
    geometry_overview_layout.setAlignment(Qt.AlignTop)
    geometry_overview_layout.setContentsMargins(5, 3, 5, 3)
    geometry_overview_layout.setSpacing(3)
    source_count = sum(
        1
        for source in getattr(replacement_mesh_for_mapping, "submeshes", ()) or ()
        if not _is_marker_source(source)
    )
    active_target_count = sum(
        1
        for _target_index, edit in mapping_edits
        if _enabled_renderable_source_indices(_parse_mapping_edit(edit))
    )
    empty_target_count = max(0, len(mapping_edits) - active_target_count)
    geometry_summary = QLabel(
        _geometry_mapping_summary_html_helper(source_count, active_target_count, empty_target_count)
    )
    geometry_summary.setWordWrap(True)
    geometry_summary.setTextFormat(Qt.RichText)
    geometry_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
    geometry_overview_layout.addWidget(geometry_summary)
    output_impact_review_label = QLabel()
    output_impact_review_label.setObjectName("HintLabel")
    output_impact_review_label.setWordWrap(True)
    output_impact_review_label.setTextFormat(Qt.RichText)
    output_impact_review_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    geometry_overview_layout.addWidget(output_impact_review_label)
    properties_control_text = _source_part_properties_control_text_helper()
    properties_sections = properties_control_text["sections"]
    properties_group = QGroupBox(str(properties_control_text["title"]))
    properties_group.setObjectName(str(properties_control_text["group_object"]))
    properties_layout = QVBoxLayout(properties_group)
    properties_layout.setAlignment(Qt.AlignTop)
    properties_layout.setContentsMargins(5, 3, 5, 3)
    properties_layout.setSpacing(3)

    def _new_properties_section_label(object_name: str) -> QLabel:
        label = QLabel(str(properties_control_text["placeholder"]))
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        return label

    properties_identity_label = _new_properties_section_label(properties_sections["identity"][1])
    properties_assignment_label = _new_properties_section_label(properties_sections["assignment"][1])
    properties_dds_label = _new_properties_section_label(properties_sections["dds"][1])
    properties_output_label = _new_properties_section_label(properties_sections["output"][1])
    properties_warnings_label = _new_properties_section_label(properties_sections["warnings"][1])
    for properties_label in (
        properties_identity_label,
        properties_assignment_label,
        properties_dds_label,
        properties_output_label,
        properties_warnings_label,
    ):
        properties_layout.addWidget(properties_label)
    geometry_overview_layout.addWidget(properties_group)

    alignment_preview_model_callbacks = create_alignment_preview_model_callbacks({**context, **globals(), **locals()})
    _refresh_output_impact_review = alignment_preview_model_callbacks._refresh_output_impact_review
    _refresh_geometry_summary = alignment_preview_model_callbacks._refresh_geometry_summary
    _current_dialog_mappings_for_preview = alignment_preview_model_callbacks._current_dialog_mappings_for_preview
    _preview_target_mesh_indices = alignment_preview_model_callbacks._preview_target_mesh_indices
    _current_independent_parts = alignment_preview_model_callbacks._current_independent_parts
    _current_static_alignment_transform = alignment_preview_model_callbacks._current_static_alignment_transform
    _current_static_placement_snapshot = alignment_preview_model_callbacks._current_static_placement_snapshot
    _static_options_from_placement_snapshot = alignment_preview_model_callbacks._static_options_from_placement_snapshot
    _build_unmapped_appended_source_overlay_model = alignment_preview_model_callbacks._build_unmapped_appended_source_overlay_model
    _append_unmapped_appended_source_overlays = alignment_preview_model_callbacks._append_unmapped_appended_source_overlays
    _source_selection_overlay_adjustments = alignment_preview_model_callbacks._source_selection_overlay_adjustments
    _build_selected_source_highlight_overlay_model = alignment_preview_model_callbacks._build_selected_source_highlight_overlay_model
    _append_selected_source_highlight_overlay = alignment_preview_model_callbacks._append_selected_source_highlight_overlay
    _build_direct_source_preview_model = alignment_preview_model_callbacks._build_direct_source_preview_model
    _selected_part_preview_indices = alignment_preview_model_callbacks._selected_part_preview_indices
    _remember_alignment_d3d11_source_editor_ids = alignment_preview_model_callbacks._remember_alignment_d3d11_source_editor_ids
    _copy_original_preview_material = alignment_preview_model_callbacks._copy_original_preview_material
    _apply_original_material_preview = alignment_preview_model_callbacks._apply_original_material_preview
    _ensure_original_reference_texture_preview_ready = alignment_preview_model_callbacks._ensure_original_reference_texture_preview_ready
    _refresh_alignment_virtual_sidecar_contract = alignment_preview_model_callbacks._refresh_alignment_virtual_sidecar_contract

    alignment_static_preview_refresh_callbacks = create_alignment_static_preview_refresh_callbacks({**context, **globals(), **locals(), '_basic_controls_profile_enabled': (lambda *args, **kwargs: _basic_controls_profile_enabled(*args, **kwargs)), '_current_complete_swap_material_profile_token': (lambda *args, **kwargs: _current_complete_swap_material_profile_token(*args, **kwargs)), '_current_material_authority_preview_profile': (lambda *args, **kwargs: _current_material_authority_preview_profile(*args, **kwargs)), '_material_authority_preview_inactive_reason': (lambda *args, **kwargs: _material_authority_preview_inactive_reason(*args, **kwargs)), '_material_authority_preview_signature': (lambda *args, **kwargs: _material_authority_preview_signature(*args, **kwargs))})
    _refresh_static_dialog_preview = alignment_static_preview_refresh_callbacks._refresh_static_dialog_preview
    _safe_refresh_static_dialog_preview = alignment_static_preview_refresh_callbacks._safe_refresh_static_dialog_preview

    static_preview_refresh_timer.timeout.connect(_safe_refresh_static_dialog_preview)
    static_preview_settle_timer.timeout.connect(_queue_static_preview_refresh)

    _load_native_preview_core_material_manifest_for_alignment = lambda target_preview_model, package_root_text="": _load_native_preview_core_material_manifest_for_alignment_helper(
        target_preview_model,
        entry=entry,
        package_root_text=package_root_text,
        active=_alignment_d3d11_preview_active(),
        model_extensions=NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS,
        cache_root=self.archive_cache_root / "native_preview_core",
        render_settings=_current_preview_render_settings(),
        companion_entry=self._find_archive_preview_companion_entry(entry),
        run_preview_job=run_native_preview_core_preview_job,
        clear_native_package_path=lambda: _original_reference_texture_preview_clear_native_package_path_helper(
            original_reference_texture_preview_state
        ),
        set_native_package_path=lambda package_path: _original_reference_texture_preview_set_native_package_path_helper(
            original_reference_texture_preview_state,
            package_path,
        ),
        apply_manifest=lambda preview_model, package_path: _apply_native_preview_core_material_manifest_helper(
            preview_model,
            package_path,
            native_manifest_input_from_descriptor=_native_manifest_input_from_descriptor,
        ),
        record_runtime_event=_record_runtime_event,
        dialog_title=dialog_title,
    )



    alignment_original_texture_worker_callbacks = create_alignment_original_texture_worker_callbacks({**context, **globals(), **locals(), '_handle_original_reference_texture_preview_error': (lambda *args, **kwargs: _handle_original_reference_texture_preview_error(*args, **kwargs))})
    _handle_original_reference_texture_preview_ready = alignment_original_texture_worker_callbacks._handle_original_reference_texture_preview_ready
    _OriginalTexturePreviewWorkerReceiver = alignment_original_texture_worker_callbacks._OriginalTexturePreviewWorkerReceiver

    original_texture_worker_receiver = _OriginalTexturePreviewWorkerReceiver(dialog)



    return SimpleNamespace(
        _append_selected_source_highlight_overlay=locals().get('_append_selected_source_highlight_overlay'),
        _apply_original_material_preview=locals().get('_apply_original_material_preview'),
        _build_direct_source_preview_model=locals().get('_build_direct_source_preview_model'),
        _current_dialog_mappings_for_preview=locals().get('_current_dialog_mappings_for_preview'),
        _current_static_alignment_transform=locals().get('_current_static_alignment_transform'),
        _current_static_placement_snapshot=locals().get('_current_static_placement_snapshot'),
        _ensure_original_reference_texture_preview_ready=locals().get('_ensure_original_reference_texture_preview_ready'),
        _load_native_preview_core_material_manifest_for_alignment=locals().get('_load_native_preview_core_material_manifest_for_alignment'),
        _mesh_edit_apply_preview_payload=locals().get('_mesh_edit_apply_preview_payload'),
        _mesh_edit_begin_stroke=locals().get('_mesh_edit_begin_stroke'),
        _mesh_edit_cancel_stroke=locals().get('_mesh_edit_cancel_stroke'),
        _mesh_edit_finish_stroke=locals().get('_mesh_edit_finish_stroke'),
        _mesh_edit_preview_source_indices=locals().get('_mesh_edit_preview_source_indices'),
        _mesh_edit_selection_changed=locals().get('_mesh_edit_selection_changed'),
        _morph_slider_refresh_controls=locals().get('_morph_slider_refresh_controls'),
        _morph_slider_reload_profiles=locals().get('_morph_slider_reload_profiles'),
        _preview_target_mesh_indices=locals().get('_preview_target_mesh_indices'),
        _refresh_alignment_virtual_sidecar_contract=locals().get('_refresh_alignment_virtual_sidecar_contract'),
        _refresh_mesh_edit_controls=locals().get('_refresh_mesh_edit_controls'),
        _refresh_output_impact_review=locals().get('_refresh_output_impact_review'),
        _remember_alignment_d3d11_source_editor_ids=locals().get('_remember_alignment_d3d11_source_editor_ids'),
        _safe_refresh_static_dialog_preview=locals().get('_safe_refresh_static_dialog_preview'),
        _selected_part_preview_indices=locals().get('_selected_part_preview_indices'),
        _static_options_from_placement_snapshot=locals().get('_static_options_from_placement_snapshot'),
        _sync_mesh_edit_preview_settings=locals().get('_sync_mesh_edit_preview_settings'),
        button=locals().get('button'),
        edit=locals().get('edit'),
        geometry_overview_group=locals().get('geometry_overview_group'),
        geometry_overview_layout=locals().get('geometry_overview_layout'),
        geometry_summary=locals().get('geometry_summary'),
        label=locals().get('label'),
        mesh_edit_action_control_text=locals().get('mesh_edit_action_control_text'),
        mesh_edit_button_row=locals().get('mesh_edit_button_row'),
        mesh_edit_clear_selection_button=locals().get('mesh_edit_clear_selection_button'),
        mesh_edit_delete_faces_button=locals().get('mesh_edit_delete_faces_button'),
        mesh_edit_delete_mode_combo=locals().get('mesh_edit_delete_mode_combo'),
        mesh_edit_enabled_checkbox=locals().get('mesh_edit_enabled_checkbox'),
        mesh_edit_falloff_combo=locals().get('mesh_edit_falloff_combo'),
        mesh_edit_field_rows=locals().get('mesh_edit_field_rows'),
        mesh_edit_full_reset_button=locals().get('mesh_edit_full_reset_button'),
        mesh_edit_group=locals().get('mesh_edit_group'),
        mesh_edit_grow_selection_button=locals().get('mesh_edit_grow_selection_button'),
        mesh_edit_invert_selection_button=locals().get('mesh_edit_invert_selection_button'),
        mesh_edit_iterations_spin=locals().get('mesh_edit_iterations_spin'),
        mesh_edit_layout=locals().get('mesh_edit_layout'),
        mesh_edit_mirror_checkbox=locals().get('mesh_edit_mirror_checkbox'),
        mesh_edit_option_widget=locals().get('mesh_edit_option_widget'),
        mesh_edit_part_combo=locals().get('mesh_edit_part_combo'),
        mesh_edit_radius_spin=locals().get('mesh_edit_radius_spin'),
        mesh_edit_redo_button=locals().get('mesh_edit_redo_button'),
        mesh_edit_remove_mode_label=locals().get('mesh_edit_remove_mode_label'),
        mesh_edit_reset_part_button=locals().get('mesh_edit_reset_part_button'),
        mesh_edit_scope_combo=locals().get('mesh_edit_scope_combo'),
        mesh_edit_select_part_button=locals().get('mesh_edit_select_part_button'),
        mesh_edit_selection_actions_widget=locals().get('mesh_edit_selection_actions_widget'),
        mesh_edit_selection_depth_combo=locals().get('mesh_edit_selection_depth_combo'),
        mesh_edit_selection_mode_combo=locals().get('mesh_edit_selection_mode_combo'),
        mesh_edit_show_vertices_checkbox=locals().get('mesh_edit_show_vertices_checkbox'),
        mesh_edit_shrink_selection_button=locals().get('mesh_edit_shrink_selection_button'),
        mesh_edit_smooth_selection_button=locals().get('mesh_edit_smooth_selection_button'),
        mesh_edit_status_label=locals().get('mesh_edit_status_label'),
        mesh_edit_strength_spin=locals().get('mesh_edit_strength_spin'),
        mesh_edit_subdivide_selection_button=locals().get('mesh_edit_subdivide_selection_button'),
        mesh_edit_supported=locals().get('mesh_edit_supported'),
        mesh_edit_tool_buttons=locals().get('mesh_edit_tool_buttons'),
        mesh_edit_tool_combo=locals().get('mesh_edit_tool_combo'),
        mesh_edit_tool_palette=locals().get('mesh_edit_tool_palette'),
        mesh_edit_undo_button=locals().get('mesh_edit_undo_button'),
        morph_slider_add_action=locals().get('morph_slider_add_action'),
        morph_slider_bake_button=locals().get('morph_slider_bake_button'),
        morph_slider_create_button=locals().get('morph_slider_create_button'),
        morph_slider_group=locals().get('morph_slider_group'),
        morph_slider_import_action=locals().get('morph_slider_import_action'),
        morph_slider_manage_button=locals().get('morph_slider_manage_button'),
        morph_slider_reload_action=locals().get('morph_slider_reload_action'),
        morph_slider_reset_button=locals().get('morph_slider_reset_button'),
        morph_slider_rows_layout=locals().get('morph_slider_rows_layout'),
        morph_slider_rows_widget=locals().get('morph_slider_rows_widget'),
        morph_slider_status_label=locals().get('morph_slider_status_label'),
        original_texture_worker_receiver=locals().get('original_texture_worker_receiver'),
        output_impact_review_label=locals().get('output_impact_review_label'),
        source=locals().get('source'),
        source_count=locals().get('source_count'),
        tooltip=locals().get('tooltip'),
    )

def create_alignment_texture_material_section(context: dict[str, object]) -> SimpleNamespace:
    Any = context.get('Any')
    Callable = context.get('Callable')
    CollapsibleSection = context.get('CollapsibleSection')
    Dict = context.get('Dict')
    List = context.get('List')
    Mapping = context.get('Mapping')
    NameError = _context_builtin(context, 'NameError')
    Optional = context.get('Optional')
    QApplication = context.get('QApplication')
    QBrush = context.get('QBrush')
    QCheckBox = context.get('QCheckBox')
    QColor = context.get('QColor')
    QComboBox = context.get('QComboBox')
    QFileDialog = context.get('QFileDialog')
    QFrame = context.get('QFrame')
    QGridLayout = context.get('QGridLayout')
    QGroupBox = context.get('QGroupBox')
    QHBoxLayout = context.get('QHBoxLayout')
    QLabel = context.get('QLabel')
    QMessageBox = context.get('QMessageBox')
    QProgressBar = context.get('QProgressBar')
    QPushButton = context.get('QPushButton')
    QSizePolicy = context.get('QSizePolicy')
    QSplitter = context.get('QSplitter')
    QTextBrowser = context.get('QTextBrowser')
    QTimer = context.get('QTimer')
    QTreeWidget = context.get('QTreeWidget')
    QTreeWidgetItem = context.get('QTreeWidgetItem')
    QVBoxLayout = context.get('QVBoxLayout')
    QWidget = context.get('QWidget')
    Qt = context.get('Qt')
    SCENE_TEXTURE_SOURCE_EXTENSIONS = context.get('SCENE_TEXTURE_SOURCE_EXTENSIONS')
    Sequence = context.get('Sequence')
    StaticSubmeshMapping = context.get('StaticSubmeshMapping')
    StaticTextureSlotOverride = context.get('StaticTextureSlotOverride')
    TEXTURE_UV_ROTATION_OPTIONS = context.get('TEXTURE_UV_ROTATION_OPTIONS')
    Tuple = context.get('Tuple')
    _added_part_texture_control_text_helper = context.get('_added_part_texture_control_text_helper')
    _added_texture_editor_loading_initial_state_helper = context.get('_added_texture_editor_loading_initial_state_helper')
    _advanced_dds_apply_guidance_state_helper = context.get('_advanced_dds_apply_guidance_state_helper')
    _advanced_dds_control_text_helper = context.get('_advanced_dds_control_text_helper')
    _advanced_dds_loading_busy_text_helper = context.get('_advanced_dds_loading_busy_text_helper')
    _advanced_dds_loading_start_text_helper = context.get('_advanced_dds_loading_start_text_helper')
    _advanced_dds_override_row_scan_state_helper = context.get('_advanced_dds_override_row_scan_state_helper')
    _advanced_dds_overrides_clear_loading_helper = context.get('_advanced_dds_overrides_clear_loading_helper')
    _advanced_dds_overrides_initial_state_helper = context.get('_advanced_dds_overrides_initial_state_helper')
    _advanced_dds_overrides_loaded_helper = context.get('_advanced_dds_overrides_loaded_helper')
    _advanced_dds_overrides_loading_helper = context.get('_advanced_dds_overrides_loading_helper')
    _advanced_dds_overrides_mark_loaded_helper = context.get('_advanced_dds_overrides_mark_loaded_helper')
    _advanced_dds_overrides_mark_loading_helper = context.get('_advanced_dds_overrides_mark_loading_helper')
    _advanced_dds_preparing_rows_text_helper = context.get('_advanced_dds_preparing_rows_text_helper')
    _advanced_dds_scanning_candidates_text_helper = context.get('_advanced_dds_scanning_candidates_text_helper')
    _advanced_dds_suggested_source_counts_helper = context.get('_advanced_dds_suggested_source_counts_helper')
    _alignment_contract_preview_path = context.get('_alignment_contract_preview_path')
    _alignment_startup_advanced_dds_classification_progress_text_helper = context.get('_alignment_startup_advanced_dds_classification_progress_text_helper')
    _alignment_startup_advanced_dds_guidance_progress_text_helper = context.get('_alignment_startup_advanced_dds_guidance_progress_text_helper')
    _alignment_startup_step = context.get('_alignment_startup_step')
    _alignment_virtual_contract_preview_specs_helper = context.get('_alignment_virtual_contract_preview_specs_helper')
    _alignment_virtual_contract_rows_helper = context.get('_alignment_virtual_contract_rows_helper')
    _alignment_virtual_sidecar_contract_state_helper = context.get('_alignment_virtual_sidecar_contract_state_helper')
    _apply_source_material_texture_overrides_to_ui_texture_sets = context.get('_apply_source_material_texture_overrides_to_ui_texture_sets')
    _best_source_for_slot = context.get('_best_source_for_slot')
    _binding_matches_target_callback = context.get('_binding_matches_target')
    _binding_matches_target_helper = context.get('_binding_matches_target_helper')
    _commit_spinbox_text = context.get('_commit_spinbox_text')
    _configure_alignment_tree = context.get('_configure_alignment_tree')
    _configure_texture_mapping_tree = context.get('_configure_texture_mapping_tree')
    _confirm_texture_assignment_action_helper = context.get('_confirm_texture_assignment_action_helper')
    _copied_source_texture_preview_specs_helper = context.get('_copied_source_texture_preview_specs_helper')
    _copied_source_texture_slot_overrides_helper = context.get('_copied_source_texture_slot_overrides_helper')
    _current_dialog_mappings_for_preview = context.get('_current_dialog_mappings_for_preview')
    _fit_alignment_tree_height_to_rows = context.get('_fit_alignment_tree_height_to_rows')
    _inline_help_button_helper = context.get('_inline_help_button_helper')
    _is_marker_source = context.get('_is_marker_source')
    _make_double_spin_helper = context.get('_make_double_spin_helper')
    _material_authority_donor_control_text_helper = context.get('_material_authority_donor_control_text_helper')
    _material_plan_control_text_helper = context.get('_material_plan_control_text_helper')
    _original_part_texture_intent_rows = context.get('_original_part_texture_intent_rows')
    _original_texture_preview_checkbox_tooltip_helper = context.get('_original_texture_preview_checkbox_tooltip_helper')
    _original_texture_preview_control_text_helper = context.get('_original_texture_preview_control_text_helper')
    _original_texture_preview_help_text_helper = context.get('_original_texture_preview_help_text_helper')
    _original_texture_preview_material_preview_enabled_helper = context.get('_original_texture_preview_material_preview_enabled_helper')
    _original_texture_preview_note_text_helper = context.get('_original_texture_preview_note_text_helper')
    _original_texture_preview_note_tooltip_helper = context.get('_original_texture_preview_note_tooltip_helper')
    _populate_combo_options_helper = context.get('_populate_combo_options_helper')
    _queue_alignment_post_open_task = context.get('_queue_alignment_post_open_task')
    _queue_static_preview_refresh = context.get('_queue_static_preview_refresh')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _register_texture_source_files_helper = context.get('_register_texture_source_files_helper')
    _registered_texture_sources_action_state_helper = context.get('_registered_texture_sources_action_state_helper')
    _selected_added_part_texture_row_initial_state_helper = context.get('_selected_added_part_texture_row_initial_state_helper')
    _selected_source_material_texture_action_state_helper = context.get('_selected_source_material_texture_action_state_helper')
    _selected_texture_editor_loading_initial_state_helper = context.get('_selected_texture_editor_loading_initial_state_helper')
    _selected_texture_plan_source_initial_state_helper = context.get('_selected_texture_plan_source_initial_state_helper')
    _selected_texture_row_initial_state_helper = context.get('_selected_texture_row_initial_state_helper')
    _selected_texture_source_committing_initial_state_helper = context.get('_selected_texture_source_committing_initial_state_helper')
    _source_display_name = context.get('_source_display_name')
    _source_indices_for_material_name_helper = context.get('_source_indices_for_material_name_helper')
    _source_indices_for_target_contract_helper = context.get('_source_indices_for_target_contract_helper')
    _source_indices_for_target_name = context.get('_source_indices_for_target_name')
    _source_preview_path = context.get('_source_preview_path')
    _source_slot_for_texture_row_helper = context.get('_source_slot_for_texture_row_helper')
    _sync_texture_row_assignment_state_helper = context.get('_sync_texture_row_assignment_state_helper')
    _target_index_for_name = context.get('_target_index_for_name')
    _texture_assignment_slot_item_helper = context.get('_texture_assignment_slot_item_helper')
    _texture_assignment_summary_html = context.get('_texture_assignment_summary_html')
    _texture_editor_control_text_helper = context.get('_texture_editor_control_text_helper')
    _texture_override_row_sort_key = context.get('_texture_override_row_sort_key')
    _texture_role_label_for_slot = context.get('_texture_role_label_for_slot')
    _texture_row_current_source_indices_helper = context.get('_texture_row_current_source_indices_helper')
    _texture_row_effective_source_helper = context.get('_texture_row_effective_source_helper')
    _texture_row_is_assigned_helper = context.get('_texture_row_is_assigned_helper')
    _texture_row_is_shared = context.get('_texture_row_is_shared')
    _texture_row_override_key = context.get('_texture_row_override_key')
    _texture_row_source_summary_helper = context.get('_texture_row_source_summary_helper')
    _texture_set_for_source_index = context.get('_texture_set_for_source_index')
    _texture_slot_contract_key = context.get('_texture_slot_contract_key')
    _texture_source_choices_for_row_helper = context.get('_texture_source_choices_for_row_helper')
    _texture_source_files_in_folder_helper = context.get('_texture_source_files_in_folder_helper')
    _texture_source_key = context.get('_texture_source_key')
    _texture_transform_controls_loading_initial_state_helper = context.get('_texture_transform_controls_loading_initial_state_helper')
    _texture_uv_control_text_helper = context.get('_texture_uv_control_text_helper')
    _virtual_contract_sidecar_text_for_path_helper = context.get('_virtual_contract_sidecar_text_for_path_helper')
    alignment_startup_text = context.get('alignment_startup_text')
    alignment_virtual_texture_contract = context.get('alignment_virtual_texture_contract')
    args = context.get('args')
    bool = _context_builtin(context, 'bool')
    checked = context.get('checked')
    classify_texture_binding = context.get('classify_texture_binding')
    control_tabs = context.get('control_tabs')
    copied_original_texture_disabled_sources = context.get('copied_original_texture_disabled_sources')
    copied_original_texture_intents_by_source = context.get('copied_original_texture_intents_by_source')
    create_alignment_added_part_texture_callbacks = context.get('create_alignment_added_part_texture_callbacks')
    create_alignment_added_part_texture_choice_callbacks = context.get('create_alignment_added_part_texture_choice_callbacks')
    create_alignment_added_part_texture_override_callbacks = context.get('create_alignment_added_part_texture_override_callbacks')
    create_alignment_material_plan_column_callbacks = context.get('create_alignment_material_plan_column_callbacks')
    create_alignment_material_plan_final_preview_callbacks = context.get('create_alignment_material_plan_final_preview_callbacks')
    create_alignment_original_texture_material_callbacks = context.get('create_alignment_original_texture_material_callbacks')
    create_alignment_preview_pixmap_callbacks = context.get('create_alignment_preview_pixmap_callbacks')
    create_alignment_source_material_plan_refresh_callbacks = context.get('create_alignment_source_material_plan_refresh_callbacks')
    create_alignment_texture_detail_uv_callbacks = context.get('create_alignment_texture_detail_uv_callbacks')
    create_alignment_texture_table_callbacks = context.get('create_alignment_texture_table_callbacks')
    current = context.get('current')
    defer_original_texture_preview = context.get('defer_original_texture_preview')
    dialog = context.get('dialog')
    enumerate = _context_builtin(context, 'enumerate')
    expanded = context.get('expanded')
    getattr = _context_builtin(context, 'getattr')
    globals = _context_builtin(context, 'globals')
    group_replacement_texture_sets = context.get('group_replacement_texture_sets')
    index = context.get('index')
    inject_base_color_checkbox = _LateLocalProxy(context.get('inject_base_color_checkbox'), 'inject_base_color_checkbox')
    int = _context_builtin(context, 'int')
    is_shared_material_layer_texture = context.get('is_shared_material_layer_texture')
    kwargs = context.get('kwargs')
    len = _context_builtin(context, 'len')
    limit = context.get('limit')
    list = _context_builtin(context, 'list')
    locals = _context_builtin(context, 'locals')
    mapping_index = context.get('mapping_index')
    material_name = context.get('material_name')
    max = _context_builtin(context, 'max')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    name = context.get('name')
    normalize_texture_reference_for_sidecar_lookup = context.get('normalize_texture_reference_for_sidecar_lookup')
    obj_path = context.get('obj_path')
    object = _context_builtin(context, 'object')
    occupied_keys = context.get('occupied_keys')
    original_texture_preview_state = context.get('original_texture_preview_state')
    parsed_mappings = context.get('parsed_mappings')
    prune_unmapped_original_dds_checkbox = _LateLocalProxy(context.get('prune_unmapped_original_dds_checkbox'), 'prune_unmapped_original_dds_checkbox')
    reason = context.get('reason')
    rebuild_sidecar_checkbox = _LateLocalProxy(context.get('rebuild_sidecar_checkbox'), 'rebuild_sidecar_checkbox')
    refresh_status = context.get('refresh_status')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    rows_override = context.get('rows_override')
    scan_count = context.get('scan_count')
    seen_texture_file_keys = context.get('seen_texture_file_keys')
    selected_source_part = context.get('selected_source_part')
    set = _context_builtin(context, 'set')
    sidecar_bindings = context.get('sidecar_bindings')
    sidecar_key = context.get('sidecar_key')
    sidecar_text_values = context.get('sidecar_text_values')
    sidecar_texts_by_basename = context.get('sidecar_texts_by_basename')
    sidecar_texts_by_normalized_path = context.get('sidecar_texts_by_normalized_path')
    spin = context.get('spin')
    state = context.get('state')
    str = _context_builtin(context, 'str')
    suggested_mappings = context.get('suggested_mappings')
    texture_files_for_mapping = context.get('texture_files_for_mapping')
    texture_filter_refresh = context.get('texture_filter_refresh')
    texture_items_by_source = context.get('texture_items_by_source')
    texture_override_assignments = context.get('texture_override_assignments')
    texture_override_rows = context.get('texture_override_rows')
    textures_layout = context.get('textures_layout')
    textures_tab = context.get('textures_tab')
    title = context.get('title')
    tree = context.get('tree')
    tuple = _context_builtin(context, 'tuple')

    def _binding_matches_target(binding: object, target_name: str) -> bool:
        if callable(_binding_matches_target_callback):
            return bool(_binding_matches_target_callback(binding, target_name))
        if callable(_binding_matches_target_helper):
            return bool(_binding_matches_target_helper(binding, target_name))
        binding_names = (
            str(getattr(binding, "part_name", "") or ""),
            str(getattr(binding, "submesh_name", "") or ""),
            str(getattr(binding, "material_name", "") or ""),
        )
        target_key = str(target_name or "").strip().lower()
        return bool(target_key) and any(name.strip().lower() == target_key for name in binding_names)

    texture_sets = group_replacement_texture_sets(texture_files_for_mapping, obj_mesh=replacement_mesh_for_mapping)
    _apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets)

    selected_texture_plan_source: Dict[str, object] = _selected_texture_plan_source_initial_state_helper()




    sidecar_bindings_for_advanced = tuple(sidecar_bindings or ())
    donor_control_text = _material_authority_donor_control_text_helper()
    donor_material_group = QGroupBox(str(donor_control_text["group_title"]))
    donor_material_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    donor_material_group.setMaximumHeight(126)
    donor_material_group.setToolTip(str(donor_control_text["group_tooltip"]))
    donor_material_layout = QVBoxLayout(donor_material_group)
    donor_material_layout.setContentsMargins(5, 3, 5, 3)
    donor_material_layout.setSpacing(3)
    donor_material_hint = QLabel(str(donor_control_text["hint"]))
    donor_material_hint.setObjectName("HintLabel")
    donor_material_hint.setWordWrap(True)
    donor_material_layout.addWidget(donor_material_hint)
    donor_material_action_row = QHBoxLayout()
    donor_material_action_row.setContentsMargins(0, 0, 0, 0)
    donor_material_action_row.setSpacing(4)
    use_another_original_mesh_button = QPushButton(str(donor_control_text["use_button"]))
    use_another_original_mesh_button.setMinimumWidth(0)
    use_another_original_mesh_button.setToolTip(str(donor_control_text["use_button_tooltip"]))
    clear_donor_material_button = QPushButton(str(donor_control_text["clear_button"]))
    clear_donor_material_button.setMinimumWidth(0)
    clear_donor_material_button.setToolTip(str(donor_control_text["clear_button_tooltip"]))
    donor_material_action_row.addWidget(use_another_original_mesh_button)
    donor_material_action_row.addWidget(clear_donor_material_button)
    donor_material_action_row.addStretch(1)
    donor_material_layout.addLayout(donor_material_action_row)
    donor_material_plan_tree = QTreeWidget()
    donor_material_plan_tree.setHeaderLabels(list(donor_control_text["plan_headers"]))
    donor_material_plan_tree.setMinimumHeight(74)
    donor_material_plan_tree.setMaximumHeight(92)
    _configure_alignment_tree(
        donor_material_plan_tree,
        (160, 120, 180, 160, 110),
        max_height=92,
        stretch_columns=(0, 2, 3),
        persist_key="donor_material_sources",
    )
    donor_material_plan_tree.setVisible(False)
    donor_material_layout.addWidget(donor_material_plan_tree, 0)
    textures_layout.addWidget(donor_material_group, 0)

    alignment_original_texture_material_callbacks = create_alignment_original_texture_material_callbacks({**context, **globals(), **locals()})
    _stop_original_reference_texture_worker = alignment_original_texture_material_callbacks._stop_original_reference_texture_worker
    _cleanup_original_reference_texture_worker_refs = alignment_original_texture_material_callbacks._cleanup_original_reference_texture_worker_refs
    _handle_original_reference_texture_preview_error = alignment_original_texture_material_callbacks._handle_original_reference_texture_preview_error
    _load_original_reference_texture_preview = alignment_original_texture_material_callbacks._load_original_reference_texture_preview
    _highlight_texture_plan_item = alignment_original_texture_material_callbacks._highlight_texture_plan_item
    _source_material_names_for_mapping = alignment_original_texture_material_callbacks._source_material_names_for_mapping
    _material_routing_conflict_messages = alignment_original_texture_material_callbacks._material_routing_conflict_messages
    _refresh_donor_material_plan_tree = alignment_original_texture_material_callbacks._refresh_donor_material_plan_tree
    _clear_selected_donor_material_source = alignment_original_texture_material_callbacks._clear_selected_donor_material_source
    _load_donor_sidecar_texts = alignment_original_texture_material_callbacks._load_donor_sidecar_texts
    _open_original_material_source_picker = alignment_original_texture_material_callbacks._open_original_material_source_picker
    _set_original_texture_preview_enabled = alignment_original_texture_material_callbacks._set_original_texture_preview_enabled

    use_another_original_mesh_button.clicked.connect(_open_original_material_source_picker)
    clear_donor_material_button.clicked.connect(_clear_selected_donor_material_source)
    _refresh_donor_material_plan_tree()

    original_texture_preview_control_text = _original_texture_preview_control_text_helper()
    original_texture_preview_group = QGroupBox(original_texture_preview_control_text["group_title"])
    original_texture_preview_layout = QVBoxLayout(original_texture_preview_group)
    original_texture_preview_layout.setContentsMargins(5, 3, 5, 3)
    original_texture_preview_layout.setSpacing(3)
    original_texture_preview_checkbox = QCheckBox(original_texture_preview_control_text["checkbox_label"])
    original_texture_preview_checkbox.setChecked(
        _original_texture_preview_material_preview_enabled_helper(
            modify_original_clone_mode,
            original_texture_preview_state,
        )
    )
    original_texture_preview_checkbox.setEnabled(bool(modify_original_clone_mode))
    original_texture_preview_checkbox.setToolTip(_original_texture_preview_checkbox_tooltip_helper())
    original_texture_preview_row = QHBoxLayout()
    original_texture_preview_row.setContentsMargins(0, 0, 0, 0)
    original_texture_preview_row.addWidget(original_texture_preview_checkbox)
    original_texture_preview_row.addStretch(1)
    original_texture_preview_row.addWidget(
        _inline_help_button_helper(_original_texture_preview_help_text_helper())
    )
    original_texture_preview_layout.addLayout(original_texture_preview_row)
    original_texture_preview_note = QLabel(
        _original_texture_preview_note_text_helper(
            modify_original_clone_mode=modify_original_clone_mode,
            defer_original_texture_preview=defer_original_texture_preview,
        )
    )
    original_texture_preview_note.setObjectName("HintLabel")
    original_texture_preview_note.setWordWrap(True)
    original_texture_preview_note.setToolTip(
        _original_texture_preview_note_tooltip_helper(
            modify_original_clone_mode=modify_original_clone_mode,
            defer_original_texture_preview=defer_original_texture_preview,
        )
    )
    original_texture_preview_layout.addWidget(original_texture_preview_note)
    original_texture_preview_note.setVisible(bool(modify_original_clone_mode and defer_original_texture_preview))
    original_texture_preview_group.setVisible(bool(modify_original_clone_mode))
    textures_layout.addWidget(original_texture_preview_group, 0)

    original_texture_preview_checkbox.toggled.connect(_set_original_texture_preview_enabled)

    added_texture_control_text = _added_part_texture_control_text_helper()
    added_texture_group = QGroupBox(str(added_texture_control_text["group_title"]))
    added_texture_group.setToolTip(str(added_texture_control_text["group_tooltip"]))
    added_texture_layout = QVBoxLayout(added_texture_group)
    added_texture_layout.setContentsMargins(5, 3, 5, 3)
    added_texture_layout.setSpacing(3)
    added_texture_layout.setAlignment(Qt.AlignTop)
    added_texture_tree = QTreeWidget()
    added_texture_tree.setHeaderLabels(list(added_texture_control_text["headers"]))
    added_texture_tree.setMinimumHeight(116)
    added_texture_tree.setMaximumHeight(240)
    _configure_alignment_tree(
        added_texture_tree,
        (170, 170, 150, 130, 130, 130, 130, 120),
        max_height=240,
        stretch_columns=(0, 1, 2),
        persist_key="added_part_textures",
    )
    added_texture_layout.addWidget(added_texture_tree, 0)
    added_texture_empty_label = QLabel(str(added_texture_control_text["empty_label"]))
    added_texture_empty_label.setObjectName("HintLabel")
    added_texture_empty_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    added_texture_empty_label.setVisible(False)
    added_texture_layout.addWidget(added_texture_empty_label)

    added_texture_editor = QWidget()
    added_texture_editor_layout = QGridLayout(added_texture_editor)
    added_texture_editor_layout.setContentsMargins(0, 0, 0, 0)
    added_texture_editor_layout.setHorizontalSpacing(4)
    added_texture_editor_layout.setVerticalSpacing(2)
    added_texture_role_combo = QComboBox()
    for slot_kind, label in tuple(added_texture_control_text["slot_options"]):
        added_texture_role_combo.addItem(label, slot_kind)
    added_texture_source_combo = QComboBox()
    added_texture_source_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    added_texture_assign_button = QPushButton(str(added_texture_control_text["assign_button"]))
    added_texture_assign_detected_button = QPushButton(str(added_texture_control_text["assign_detected_button"]))
    added_texture_clear_button = QPushButton(str(added_texture_control_text["clear_button"]))
    added_texture_choose_base_button = QPushButton(str(added_texture_control_text["choose_base_button"]))
    added_texture_choose_normal_button = QPushButton(str(added_texture_control_text["choose_normal_button"]))
    added_texture_choose_mask_button = QPushButton(str(added_texture_control_text["choose_mask_button"]))
    added_texture_choose_height_button = QPushButton(str(added_texture_control_text["choose_height_button"]))
    for button in (
        added_texture_assign_button,
        added_texture_assign_detected_button,
        added_texture_clear_button,
        added_texture_choose_base_button,
        added_texture_choose_normal_button,
        added_texture_choose_mask_button,
        added_texture_choose_height_button,
    ):
        button.setMinimumWidth(0)
    added_texture_assign_detected_button.setToolTip(str(added_texture_control_text["assign_detected_tooltip"]))
    added_texture_choose_base_button.setToolTip(str(added_texture_control_text["choose_base_tooltip"]))
    added_texture_choose_normal_button.setToolTip(str(added_texture_control_text["choose_normal_tooltip"]))
    added_texture_choose_mask_button.setToolTip(str(added_texture_control_text["choose_mask_tooltip"]))
    added_texture_choose_height_button.setToolTip(str(added_texture_control_text["choose_height_tooltip"]))
    added_texture_clear_button.setToolTip(str(added_texture_control_text["clear_tooltip"]))
    added_texture_editor_layout.addWidget(QLabel(str(added_texture_control_text["role_label"])), 0, 0)
    added_texture_editor_layout.addWidget(added_texture_role_combo, 0, 1)
    added_texture_editor_layout.addWidget(QLabel(str(added_texture_control_text["source_label"])), 0, 2)
    added_texture_editor_layout.addWidget(added_texture_source_combo, 0, 3, 1, 3)
    added_texture_editor_layout.addWidget(added_texture_assign_button, 0, 6)
    added_texture_editor_layout.addWidget(added_texture_clear_button, 0, 7)
    added_texture_editor_layout.addWidget(added_texture_assign_detected_button, 1, 0, 1, 2)
    added_texture_editor_layout.addWidget(added_texture_choose_base_button, 1, 2)
    added_texture_editor_layout.addWidget(added_texture_choose_normal_button, 1, 3)
    added_texture_editor_layout.addWidget(added_texture_choose_mask_button, 1, 4)
    added_texture_editor_layout.addWidget(added_texture_choose_height_button, 1, 5)
    added_texture_editor_layout.setColumnStretch(3, 1)
    added_texture_layout.addWidget(added_texture_editor)
    textures_layout.addWidget(added_texture_group, 0)

    selected_added_part_texture_row: Dict[str, int] = _selected_added_part_texture_row_initial_state_helper()
    added_texture_editor_loading = _added_texture_editor_loading_initial_state_helper()






    alignment_added_part_texture_override_callbacks = create_alignment_added_part_texture_override_callbacks({**context, **globals(), **locals(), '_refresh_added_part_texture_tree': (lambda *args, **kwargs: _refresh_added_part_texture_tree(*args, **kwargs)), '_refresh_source_material_plan': (lambda *args, **kwargs: _refresh_source_material_plan(*args, **kwargs))})
    _set_added_part_texture_override = alignment_added_part_texture_override_callbacks._set_added_part_texture_override

    alignment_added_part_texture_callbacks = create_alignment_added_part_texture_callbacks({**context, **globals(), **locals()})
    _sync_added_part_texture_group_size = alignment_added_part_texture_callbacks._sync_added_part_texture_group_size
    _highlight_added_part_texture_source = alignment_added_part_texture_callbacks._highlight_added_part_texture_source
    _refresh_added_part_texture_editor = alignment_added_part_texture_callbacks._refresh_added_part_texture_editor
    _refresh_added_part_texture_tree = alignment_added_part_texture_callbacks._refresh_added_part_texture_tree
    _current_added_part_texture_source_index = alignment_added_part_texture_callbacks._current_added_part_texture_source_index
    _register_added_part_texture_file = alignment_added_part_texture_callbacks._register_added_part_texture_file
    _assign_added_part_selected_texture = alignment_added_part_texture_callbacks._assign_added_part_selected_texture
    _assign_detected_added_part_textures = alignment_added_part_texture_callbacks._assign_detected_added_part_textures
    _choose_added_part_texture = alignment_added_part_texture_callbacks._choose_added_part_texture
    _clear_added_part_texture_override = alignment_added_part_texture_callbacks._clear_added_part_texture_override
    _added_texture_tree_selection_changed = alignment_added_part_texture_callbacks._added_texture_tree_selection_changed
    _added_texture_role_changed = alignment_added_part_texture_callbacks._added_texture_role_changed

    alignment_added_part_texture_choice_callbacks = create_alignment_added_part_texture_choice_callbacks({**context, **globals(), **locals(), '_refresh_source_material_plan': (lambda *args, **kwargs: _refresh_source_material_plan(*args, **kwargs))})
    _choose_added_part_texture = alignment_added_part_texture_choice_callbacks._choose_added_part_texture






    added_texture_tree.currentItemChanged.connect(_added_texture_tree_selection_changed)
    added_texture_role_combo.currentIndexChanged.connect(_added_texture_role_changed)
    added_texture_assign_button.clicked.connect(_assign_added_part_selected_texture)
    added_texture_assign_detected_button.clicked.connect(_assign_detected_added_part_textures)
    added_texture_clear_button.clicked.connect(_clear_added_part_texture_override)
    added_texture_choose_base_button.clicked.connect(lambda: _choose_added_part_texture("base"))
    added_texture_choose_normal_button.clicked.connect(lambda: _choose_added_part_texture("normal"))
    added_texture_choose_mask_button.clicked.connect(lambda: _choose_added_part_texture("material"))
    added_texture_choose_height_button.clicked.connect(lambda: _choose_added_part_texture("height"))
    _refresh_added_part_texture_tree()

    material_plan_control_text = _material_plan_control_text_helper()
    material_plan_group = QGroupBox(str(material_plan_control_text["group_title"]))
    material_plan_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    material_plan_layout = QVBoxLayout(material_plan_group)
    material_plan_layout.setAlignment(Qt.AlignTop)
    material_plan_layout.setContentsMargins(5, 3, 5, 3)
    material_plan_layout.setSpacing(3)
    material_plan_summary = QLabel()
    material_plan_summary.setWordWrap(True)
    material_plan_summary.setTextFormat(Qt.RichText)
    material_plan_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
    material_plan_summary.setMaximumHeight(44)
    material_plan_layout.addWidget(material_plan_summary)
    material_contract_label = QLabel()
    material_contract_label.setWordWrap(True)
    material_contract_label.setTextFormat(Qt.RichText)
    material_contract_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    material_contract_label.setToolTip(str(material_plan_control_text["contract_tooltip"]))
    material_contract_label.setMaximumHeight(28)
    material_plan_layout.addWidget(material_contract_label)
    material_plan_action_row = QHBoxLayout()
    apply_texture_plan_button = QPushButton(str(material_plan_control_text["apply_suggested"]))
    apply_texture_plan_button.setMinimumWidth(0)
    apply_texture_plan_button.setToolTip(str(material_plan_control_text["apply_suggested_tooltip"]))
    apply_selected_source_textures_button = QPushButton(str(material_plan_control_text["use_selected"]))
    apply_selected_source_textures_button.setMinimumWidth(0)
    apply_selected_source_textures_button.setEnabled(False)
    apply_selected_source_textures_button.setToolTip(str(material_plan_control_text["use_selected_tooltip"]))
    material_use_route_source_button = QPushButton(str(material_plan_control_text["use_route_source"]))
    material_keep_original_button = QPushButton(str(material_plan_control_text["keep_original"]))
    material_choose_file_button = QPushButton(str(material_plan_control_text["choose_file"]))
    material_neutralize_button = QPushButton(str(material_plan_control_text["neutralize"]))
    material_do_not_emit_button = QPushButton(str(material_plan_control_text["do_not_emit"]))
    for texture_action_button in (
        material_use_route_source_button,
        material_keep_original_button,
        material_choose_file_button,
        material_neutralize_button,
        material_do_not_emit_button,
    ):
        texture_action_button.setMinimumWidth(0)
        texture_action_button.setEnabled(False)
    material_use_route_source_button.setToolTip(str(material_plan_control_text["use_route_source_tooltip"]))
    material_keep_original_button.setToolTip(str(material_plan_control_text["keep_original_tooltip"]))
    material_choose_file_button.setToolTip(str(material_plan_control_text["choose_file_tooltip"]))
    material_neutralize_button.setToolTip(str(material_plan_control_text["neutralize_tooltip"]))
    material_do_not_emit_button.setToolTip(str(material_plan_control_text["do_not_emit_tooltip"]))
    material_plan_action_row.addWidget(apply_texture_plan_button)
    material_plan_action_row.addWidget(apply_selected_source_textures_button)
    material_plan_action_row.addWidget(material_use_route_source_button)
    material_plan_action_row.addWidget(material_keep_original_button)
    material_plan_action_row.addWidget(material_choose_file_button)
    material_plan_action_row.addWidget(material_neutralize_button)
    material_plan_action_row.addWidget(material_do_not_emit_button)
    material_plan_action_row.addStretch(1)
    material_plan_action_row.addWidget(
        _inline_help_button_helper(
            str(material_plan_control_text["help"])
        )
    )
    material_plan_layout.addLayout(material_plan_action_row)

    material_plan_advanced_section = CollapsibleSection(
        str(material_plan_control_text["advanced_routes"]),
        expanded=False,
    )
    material_routing_tree = QTreeWidget()
    material_routing_tree.setHeaderLabels(list(material_plan_control_text["material_routing_headers"]))
    material_routing_tree.setMinimumHeight(80)
    material_routing_tree.setMinimumWidth(0)
    _configure_alignment_tree(
        material_routing_tree,
        (130, 130, 150, 90, 70, 180),
        max_height=180,
        stretch_columns=(2, 5),
        persist_key="replacement_material_routing",
    )
    material_plan_advanced_section.body_layout.addWidget(material_routing_tree)
    material_plan_tree = QTreeWidget()
    material_plan_tree.setHeaderLabels(list(material_plan_control_text["material_plan_headers"]))
    material_plan_tree.setMinimumHeight(76)
    material_plan_tree.setMinimumWidth(0)
    _configure_alignment_tree(
        material_plan_tree,
        (80, 64, 170, 240, 64, 120),
        max_height=190,
        stretch_columns=(2, 3),
        persist_key="replacement_texture_plan",
    )
    material_plan_layout.addWidget(material_plan_tree)
    dds_detail_panel = QFrame()
    dds_detail_panel.setObjectName("DDSDetailPane")
    dds_detail_panel.setMaximumHeight(150)
    dds_detail_layout = QHBoxLayout(dds_detail_panel)
    dds_detail_layout.setContentsMargins(0, 0, 0, 0)
    dds_detail_layout.setSpacing(8)
    dds_detail_thumbnail_label = QLabel(str(material_plan_control_text["dds_detail_no_preview"]))
    dds_detail_thumbnail_label.setObjectName("DDSDetailThumbnail")
    dds_detail_thumbnail_label.setAlignment(Qt.AlignCenter)
    dds_detail_thumbnail_label.setFixedSize(128, 128)
    dds_detail_thumbnail_label.setScaledContents(False)
    dds_detail_thumbnail_label.setStyleSheet(
        "QLabel#DDSDetailThumbnail { border: 1px solid #30363d; background: #0d1117; color: #8b949e; }"
    )
    dds_detail_label = QLabel(str(material_plan_control_text["dds_detail_select_row"]))
    dds_detail_label.setObjectName("HintLabel")
    dds_detail_label.setWordWrap(True)
    dds_detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    dds_detail_label.setTextFormat(Qt.RichText)
    dds_detail_layout.addWidget(dds_detail_thumbnail_label, 0)
    dds_detail_layout.addWidget(dds_detail_label, 1)
    material_plan_layout.addWidget(dds_detail_panel)
    dds_detail_panel.setVisible(False)
    material_plan_layout.addWidget(material_plan_advanced_section)

    alignment_preview_pixmap_callbacks = create_alignment_preview_pixmap_callbacks({**context, **globals(), **locals()})
    _read_preview_pixmap = alignment_preview_pixmap_callbacks._read_preview_pixmap

    texture_uv_control_text = _texture_uv_control_text_helper()
    texture_transform_group = QGroupBox(texture_uv_control_text["transform_group"])
    texture_transform_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    texture_transform_layout = QGridLayout(texture_transform_group)
    texture_transform_layout.setContentsMargins(5, 3, 5, 3)
    texture_transform_layout.setHorizontalSpacing(5)
    texture_transform_layout.setVerticalSpacing(2)
    texture_transform_layout.setColumnStretch(1, 1)
    texture_transform_note = QLabel(
        texture_uv_control_text["note"]
    )
    texture_transform_note.setObjectName("HintLabel")
    texture_transform_note.setWordWrap(True)
    texture_transform_note.setToolTip(texture_uv_control_text["help"])
    texture_transform_note.setVisible(False)
    texture_transform_header_row = QHBoxLayout()
    texture_transform_header_row.setContentsMargins(0, 0, 0, 0)
    texture_transform_header_row.addWidget(texture_transform_note, 1)
    texture_transform_header_row.addWidget(
        _inline_help_button_helper(texture_uv_control_text["help"])
    )
    texture_transform_layout.addLayout(texture_transform_header_row, 0, 0, 1, 6)
    texture_transform_material_combo = QComboBox()
    texture_transform_material_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    texture_transform_material_combo.setToolTip(texture_uv_control_text["material_tooltip"])
    texture_transform_rotate_combo = QComboBox()
    _populate_combo_options_helper(texture_transform_rotate_combo, TEXTURE_UV_ROTATION_OPTIONS)
    texture_transform_rotate_combo.setToolTip(texture_uv_control_text["rotate_tooltip"])
    texture_transform_flip_u_checkbox = QCheckBox(texture_uv_control_text["flip_u_label"])
    texture_transform_flip_u_checkbox.setToolTip(texture_uv_control_text["flip_u_tooltip"])
    texture_transform_flip_v_checkbox = QCheckBox(texture_uv_control_text["flip_v_label"])
    texture_transform_flip_v_checkbox.setToolTip(texture_uv_control_text["flip_v_tooltip"])

    texture_transform_offset_u_spin = _make_double_spin_helper(0.0, -10.0, 10.0, 4, 0.01)
    texture_transform_offset_v_spin = _make_double_spin_helper(0.0, -10.0, 10.0, 4, 0.01)
    texture_transform_scale_u_spin = _make_double_spin_helper(1.0, 0.01, 100.0, 4, 0.01)
    texture_transform_scale_v_spin = _make_double_spin_helper(1.0, 0.01, 100.0, 4, 0.01)
    for texture_transform_spin in (
        texture_transform_offset_u_spin,
        texture_transform_offset_v_spin,
        texture_transform_scale_u_spin,
        texture_transform_scale_v_spin,
    ):
        texture_transform_spin.setMinimumWidth(76)
        texture_transform_spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    texture_transform_offset_u_spin.setToolTip(texture_uv_control_text["offset_u_tooltip"])
    texture_transform_offset_v_spin.setToolTip(texture_uv_control_text["offset_v_tooltip"])
    texture_transform_scale_u_spin.setToolTip(texture_uv_control_text["scale_u_tooltip"])
    texture_transform_scale_v_spin.setToolTip(texture_uv_control_text["scale_v_tooltip"])
    texture_transform_reset_button = QPushButton(texture_uv_control_text["reset_button"])
    texture_transform_reset_button.setMinimumWidth(0)
    texture_transform_reset_button.setToolTip(texture_uv_control_text["reset_tooltip"])
    texture_transform_layout.addWidget(QLabel(texture_uv_control_text["material_label"]), 1, 0)
    texture_transform_layout.addWidget(texture_transform_material_combo, 1, 1, 1, 4)
    texture_transform_layout.addWidget(texture_transform_reset_button, 1, 5)
    texture_transform_layout.addWidget(QLabel(texture_uv_control_text["rotate_label"]), 2, 0)
    texture_transform_layout.addWidget(texture_transform_rotate_combo, 2, 1, 1, 2)
    texture_transform_layout.addWidget(texture_transform_flip_u_checkbox, 2, 3)
    texture_transform_layout.addWidget(texture_transform_flip_v_checkbox, 2, 4, 1, 2)
    texture_transform_layout.addWidget(QLabel(texture_uv_control_text["offset_u_label"]), 3, 0)
    texture_transform_layout.addWidget(texture_transform_offset_u_spin, 3, 1)
    texture_transform_layout.addWidget(QLabel(texture_uv_control_text["offset_v_label"]), 3, 2)
    texture_transform_layout.addWidget(texture_transform_offset_v_spin, 3, 3)
    texture_transform_layout.addWidget(QLabel(texture_uv_control_text["scale_u_label"]), 4, 0)
    texture_transform_layout.addWidget(texture_transform_scale_u_spin, 4, 1)
    texture_transform_layout.addWidget(QLabel(texture_uv_control_text["scale_v_label"]), 4, 2)
    texture_transform_layout.addWidget(texture_transform_scale_v_spin, 4, 3)
    material_routing_tree.currentItemChanged.connect(lambda current, _previous: _highlight_texture_plan_item(current))
    material_plan_tree.currentItemChanged.connect(lambda current, _previous: _highlight_texture_plan_item(current))

    texture_transform_controls_loading = _texture_transform_controls_loading_initial_state_helper()

    alignment_texture_detail_uv_callbacks = create_alignment_texture_detail_uv_callbacks({**context, **globals(), **locals()})
    _apply_dds_detail_thumbnail_state = alignment_texture_detail_uv_callbacks._apply_dds_detail_thumbnail_state
    _resolve_dds_detail_preview_path = alignment_texture_detail_uv_callbacks._resolve_dds_detail_preview_path
    _refresh_dds_detail_thumbnail = alignment_texture_detail_uv_callbacks._refresh_dds_detail_thumbnail
    _set_texture_transform_controls_enabled = alignment_texture_detail_uv_callbacks._set_texture_transform_controls_enabled
    _load_texture_transform_controls = alignment_texture_detail_uv_callbacks._load_texture_transform_controls
    _save_texture_transform_controls = alignment_texture_detail_uv_callbacks._save_texture_transform_controls
    _sync_texture_transform_materials = alignment_texture_detail_uv_callbacks._sync_texture_transform_materials
    _handle_texture_transform_material_changed = alignment_texture_detail_uv_callbacks._handle_texture_transform_material_changed
    _reset_selected_texture_transform = alignment_texture_detail_uv_callbacks._reset_selected_texture_transform







    texture_transform_material_combo.currentIndexChanged.connect(_handle_texture_transform_material_changed)
    texture_transform_rotate_combo.currentIndexChanged.connect(_save_texture_transform_controls)
    texture_transform_flip_u_checkbox.toggled.connect(_save_texture_transform_controls)
    texture_transform_flip_v_checkbox.toggled.connect(_save_texture_transform_controls)
    texture_transform_offset_u_spin.valueChanged.connect(_save_texture_transform_controls)
    texture_transform_offset_v_spin.valueChanged.connect(_save_texture_transform_controls)
    texture_transform_scale_u_spin.valueChanged.connect(_save_texture_transform_controls)
    texture_transform_scale_v_spin.valueChanged.connect(_save_texture_transform_controls)
    for texture_spin in (
        texture_transform_offset_u_spin,
        texture_transform_offset_v_spin,
        texture_transform_scale_u_spin,
        texture_transform_scale_v_spin,
    ):
        texture_spin.editingFinished.connect(
            lambda spin=texture_spin: (_commit_spinbox_text(spin), _save_texture_transform_controls())
        )
    texture_transform_reset_button.clicked.connect(_reset_selected_texture_transform)
    material_plan_layout.addWidget(texture_transform_group)
    texture_transform_group.setVisible(False)

    alignment_material_plan_column_callbacks = create_alignment_material_plan_column_callbacks({**context, **globals(), **locals()})
    _fit_material_routing_tree_columns = alignment_material_plan_column_callbacks._fit_material_routing_tree_columns
    _fit_material_plan_tree_columns = alignment_material_plan_column_callbacks._fit_material_plan_tree_columns
    _schedule_material_plan_column_refit = alignment_material_plan_column_callbacks._schedule_material_plan_column_refit

    alignment_original_texture_material_callbacks = create_alignment_original_texture_material_callbacks({**context, **globals(), **locals()})
    _highlight_texture_plan_item = alignment_original_texture_material_callbacks._highlight_texture_plan_item
    _source_material_names_for_mapping = alignment_original_texture_material_callbacks._source_material_names_for_mapping
    _material_routing_conflict_messages = alignment_original_texture_material_callbacks._material_routing_conflict_messages
    _refresh_donor_material_plan_tree = alignment_original_texture_material_callbacks._refresh_donor_material_plan_tree
    _clear_selected_donor_material_source = alignment_original_texture_material_callbacks._clear_selected_donor_material_source
    _load_donor_sidecar_texts = alignment_original_texture_material_callbacks._load_donor_sidecar_texts
    _open_original_material_source_picker = alignment_original_texture_material_callbacks._open_original_material_source_picker



    alignment_source_material_plan_refresh_callbacks = create_alignment_source_material_plan_refresh_callbacks({**context, **globals(), **locals()})
    _refresh_source_material_plan = alignment_source_material_plan_refresh_callbacks._refresh_source_material_plan

    _source_indices_for_target_contract = lambda target_name, material_name="": _source_indices_for_target_contract_helper(
        target_name,
        material_name,
        target_index_for_name=_target_index_for_name,
        mappings=_current_dialog_mappings_for_preview(),
        source_indices_for_material_name=lambda name: _source_indices_for_material_name_helper(
            name,
            replacement_mesh_for_mapping,
            texture_set_count=len(texture_sets),
            is_marker_source=_is_marker_source,
        ),
    )

    alignment_material_plan_final_preview_callbacks = create_alignment_material_plan_final_preview_callbacks({**context, **globals(), **locals()})
    _refresh_material_plan_from_final_preview = alignment_material_plan_final_preview_callbacks._refresh_material_plan_from_final_preview
    _ensure_source_material_plan_loaded = alignment_material_plan_final_preview_callbacks._ensure_source_material_plan_loaded

    _refresh_source_material_plan()

    control_tabs.currentChanged.connect(
        lambda index: _ensure_source_material_plan_loaded()
        if control_tabs.widget(index) is textures_tab
        else None
    )
    textures_layout.addWidget(material_plan_group, 0)
    _schedule_material_plan_column_refit()

    apply_texture_plan_button.setEnabled(bool(texture_sets and sidecar_bindings_for_advanced))
    texture_assignment_rows_skipped = False
    deferred_sidecar_bindings_for_advanced = tuple(sidecar_bindings_for_advanced or ())
    estimated_advanced_texture_work = (
        len(deferred_sidecar_bindings_for_advanced)
        * max(1, len(tuple(suggested_mappings or ())))
        * max(1, len(texture_files_for_mapping))
    )
    initial_static_preview_refreshed = False

    if sidecar_bindings_for_advanced:
        advanced_dds_control_text = _advanced_dds_control_text_helper()
        texture_group = QGroupBox(str(advanced_dds_control_text["group_title"]))
        texture_group.setObjectName("AdvancedDDSOverrides")
        texture_group.setToolTip(str(advanced_dds_control_text["group_tooltip"]))
        texture_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        texture_layout = QVBoxLayout(texture_group)
        texture_layout.setAlignment(Qt.AlignTop)
        texture_layout.setContentsMargins(0, 0, 0, 0)
        texture_layout.setSpacing(3)
        texture_hint = QLabel(str(advanced_dds_control_text["hint_label"]))
        texture_hint.setWordWrap(True)
        texture_hint.setTextFormat(Qt.RichText)
        texture_hint.setText(str(advanced_dds_control_text["hint_html"]))
        texture_hint.setToolTip(str(advanced_dds_control_text["hint_tooltip"]))
        texture_hint.setObjectName("HintLabel")
        texture_layout.addWidget(texture_hint)
        texture_hint.setVisible(False)
        if not texture_files_for_mapping:
            no_sources_hint = QLabel(
                str(advanced_dds_control_text["no_sources_hint"])
            )
            no_sources_hint.setWordWrap(True)
            no_sources_hint.setObjectName("HintLabel")
            texture_layout.addWidget(no_sources_hint)

        advanced_dds_lazy_placeholder = QWidget(texture_group)
        advanced_dds_lazy_layout = QHBoxLayout(advanced_dds_lazy_placeholder)
        advanced_dds_lazy_layout.setContentsMargins(5, 3, 5, 3)
        advanced_dds_lazy_layout.setSpacing(6)
        advanced_dds_lazy_label = QLabel(
            str(advanced_dds_control_text["lazy_label"])
        )
        advanced_dds_lazy_label.setWordWrap(True)
        advanced_dds_lazy_label.setObjectName("HintLabel")
        advanced_dds_lazy_label.setToolTip(str(advanced_dds_control_text["lazy_tooltip"]))
        advanced_dds_load_button = QPushButton(str(advanced_dds_control_text["load_button"]))
        advanced_dds_load_button.setToolTip(str(advanced_dds_control_text["load_tooltip"]))
        advanced_dds_lazy_layout.addWidget(advanced_dds_lazy_label, 1)
        advanced_dds_lazy_layout.addWidget(advanced_dds_load_button, 0)
        texture_layout.addWidget(advanced_dds_lazy_placeholder)

        texture_action_row = QHBoxLayout()
        texture_action_row.setContentsMargins(0, 0, 0, 0)
        texture_action_row.setSpacing(3)
        apply_all_suggested_overrides_button = QPushButton(str(advanced_dds_control_text["apply_all_button"]))
        apply_all_suggested_overrides_button.setText(str(advanced_dds_control_text["apply_all_short"]))
        clear_target_textures_button = QPushButton(str(advanced_dds_control_text["clear_target_button"]))
        keep_original_target_button = QPushButton(str(advanced_dds_control_text["keep_original_button"]))
        do_not_emit_texture_button = QPushButton(str(advanced_dds_control_text["do_not_emit_button"]))
        add_textures_button = QPushButton(str(advanced_dds_control_text["add_textures_button"]))
        add_texture_folder_button = QPushButton(str(advanced_dds_control_text["add_folder_button"]))
        apply_all_suggested_overrides_button.setToolTip(str(advanced_dds_control_text["apply_all_tooltip"]))
        clear_target_textures_button.setToolTip(str(advanced_dds_control_text["clear_target_tooltip"]))
        keep_original_target_button.setToolTip(str(advanced_dds_control_text["keep_original_tooltip"]))
        do_not_emit_texture_button.setToolTip(str(advanced_dds_control_text["do_not_emit_tooltip"]))
        add_textures_button.setToolTip(str(advanced_dds_control_text["add_textures_tooltip"]))
        add_texture_folder_button.setToolTip(str(advanced_dds_control_text["add_folder_tooltip"]))
        for texture_button in (
            apply_all_suggested_overrides_button,
            clear_target_textures_button,
            keep_original_target_button,
            do_not_emit_texture_button,
            add_textures_button,
            add_texture_folder_button,
        ):
            texture_button.setMinimumWidth(0)
            texture_action_row.addWidget(texture_button)
        texture_action_row.addStretch(1)
        texture_layout.addLayout(texture_action_row)

        texture_filter_selected_checkbox = QCheckBox(str(advanced_dds_control_text["filter_active_parts"]))
        texture_filter_selected_checkbox.setChecked(False)
        texture_filter_selected_checkbox.setToolTip(str(advanced_dds_control_text["filter_active_parts_tooltip"]))
        texture_show_advanced_checkbox = QCheckBox(str(advanced_dds_control_text["filter_advanced_slots"]))
        texture_show_advanced_checkbox.setToolTip(str(advanced_dds_control_text["filter_advanced_slots_tooltip"]))
        texture_filter_row = QHBoxLayout()
        texture_filter_row.setContentsMargins(0, 0, 0, 0)
        texture_filter_row.setSpacing(4)
        texture_filter_row.addWidget(texture_filter_selected_checkbox)
        texture_filter_row.addWidget(texture_show_advanced_checkbox)
        texture_filter_row.addStretch(1)
        texture_layout.addLayout(texture_filter_row)

        texture_rows_by_target: Dict[str, List[Dict[str, Any]]] = {}
        texture_target_source_indices: Dict[str, Tuple[int, ...]] = {}
        seen_texture_rows: set[tuple[str, str, str, str]] = set()
        advanced_dds_overrides_state = _advanced_dds_overrides_initial_state_helper()

        def _load_advanced_dds_override_rows(*, reason: str = "manual") -> bool:
            if _advanced_dds_overrides_loaded_helper(advanced_dds_overrides_state):
                return True
            if _advanced_dds_overrides_loading_helper(advanced_dds_overrides_state):
                return False
            _advanced_dds_overrides_mark_loading_helper(advanced_dds_overrides_state)
            try:
                _ensure_source_material_plan_loaded()
            except NameError:
                pass
            texture_busy_bar.setFormat(_advanced_dds_loading_busy_text_helper())
            texture_busy_bar.setVisible(True)
            QApplication.processEvents()
            try:
                _alignment_startup_step(_advanced_dds_loading_start_text_helper(reason))
                scan_state = _advanced_dds_override_row_scan_state_helper(
                    tuple(suggested_mappings or ()),
                    tuple(sidecar_bindings_for_advanced or ()),
                    texture_sets,
                    seen_texture_rows,
                    binding_matches_target=_binding_matches_target,
                    best_source_for_slot=_best_source_for_slot,
                    texture_is_shared=is_shared_material_layer_texture,
                    on_mapping_progress=lambda mapping_index: _alignment_startup_step(
                        _advanced_dds_preparing_rows_text_helper(mapping_index)
                    ),
                    on_scan_progress=lambda scan_count: _alignment_startup_step(
                        _advanced_dds_scanning_candidates_text_helper(scan_count)
                    ),
                )
                for target_name, rows in scan_state.rows_by_target.items():
                    texture_rows_by_target.setdefault(target_name, []).extend(rows)
                texture_target_source_indices.update(scan_state.target_source_indices)
                texture_override_rows.extend(scan_state.texture_override_rows)
                seen_texture_rows.clear()
                seen_texture_rows.update(scan_state.seen_texture_rows)
                _advanced_dds_overrides_mark_loaded_helper(advanced_dds_overrides_state)
                advanced_dds_lazy_placeholder.setVisible(False)
                try:
                    _refresh_texture_row_guidance()
                    _refresh_texture_table(selected_texture_row.get("row"))
                    _queue_texture_preview_refresh()
                except NameError:
                    pass
                return True
            finally:
                _advanced_dds_overrides_clear_loading_helper(advanced_dds_overrides_state)
                texture_busy_bar.setVisible(False)

        def _ensure_advanced_dds_overrides_loaded(reason: str = "manual") -> bool:
            return _load_advanced_dds_override_rows(reason=reason)

        texture_row_assigned = lambda state: _texture_row_is_assigned_helper(state, texture_override_assignments)
        texture_row_effective_source = lambda state: _texture_row_effective_source_helper(state, texture_override_assignments)
        sync_texture_row_assignment = lambda state: _sync_texture_row_assignment_state_helper(state, texture_override_assignments)
        texture_row_current_source_indices = lambda state: _texture_row_current_source_indices_helper(
            state,
            source_indices_for_target_name=_source_indices_for_target_name,
        )
        texture_row_source_summary = lambda state, limit=3: _texture_row_source_summary_helper(
            texture_row_current_source_indices(state),
            source_display_name=_source_display_name,
            limit=limit,
        )
        texture_source_choices_for_row = lambda state: _texture_source_choices_for_row_helper(
            state,
            texture_files_for_mapping,
            effective_source=texture_row_effective_source,
            source_key=_texture_source_key,
        )

        def _virtual_contract_prune_removed_targets_enabled() -> bool:
            try:
                return bool(
                    rebuild_sidecar_checkbox.isChecked()
                    and prune_unmapped_original_dds_checkbox.isChecked()
                )
            except NameError:
                return False

        def _virtual_contract_prune_unmapped_enabled() -> bool:
            try:
                return bool(
                    rebuild_sidecar_checkbox.isChecked()
                    and prune_unmapped_original_dds_checkbox.isChecked()
                )
            except NameError:
                return False

        def _copied_source_texture_slot_overrides(
            parsed_mappings: Sequence[StaticSubmeshMapping],
            *,
            occupied_keys: Optional[set[Tuple[str, str]]] = None,
        ) -> List[StaticTextureSlotOverride]:
            return list(
                _copied_source_texture_slot_overrides_helper(
                    parsed_mappings,
                    original_part_texture_intent_rows=_original_part_texture_intent_rows,
                    copied_original_texture_intents_by_source=copied_original_texture_intents_by_source,
                    copied_original_texture_disabled_sources=copied_original_texture_disabled_sources,
                    source_display_name=_source_display_name,
                    texture_slot_contract_key=_texture_slot_contract_key,
                    occupied_keys=occupied_keys,
                )
            )

        def _copied_source_texture_preview_specs(
            parsed_mappings: Sequence[StaticSubmeshMapping],
        ) -> List[tuple[str, str, str, str, Tuple[int, ...], str]]:
            return list(
                _copied_source_texture_preview_specs_helper(
                    parsed_mappings,
                    _copied_source_texture_slot_overrides(parsed_mappings),
                    source_preview_path=_source_preview_path,
                )
            )

        def _alignment_virtual_contract_rows(
            parsed_mappings: Sequence[StaticSubmeshMapping],
        ) -> List[Dict[str, object]]:
            occupied_copied_keys: set[Tuple[str, str]] = set()
            copied_overrides = _copied_source_texture_slot_overrides(
                parsed_mappings,
                occupied_keys=occupied_copied_keys,
            )
            return _alignment_virtual_contract_rows_helper(
                parsed_mappings,
                texture_override_rows=texture_override_rows,
                texture_override_assignments=texture_override_assignments,
                copied_overrides=copied_overrides,
                texture_rows_by_target=texture_rows_by_target,
                texture_row_assigned=texture_row_assigned,
                texture_row_current_source_indices=texture_row_current_source_indices,
                virtual_contract_prune_removed_targets_enabled=_virtual_contract_prune_removed_targets_enabled,
                virtual_contract_prune_unmapped_enabled=_virtual_contract_prune_unmapped_enabled,
                texture_row_effective_source=texture_row_effective_source,
                texture_row_is_shared=_texture_row_is_shared,
                texture_role_label_for_slot=_texture_role_label_for_slot,
                texture_row_override_key=_texture_row_override_key,
                texture_override_row_sort_key=_texture_override_row_sort_key,
                texture_slot_contract_key=_texture_slot_contract_key,
            )

        def _alignment_virtual_contract_preview_specs(
            parsed_mappings: Sequence[StaticSubmeshMapping],
            rows_override: Optional[Sequence[Mapping[str, object]]] = None,
        ) -> List[tuple[str, str, str, str, Tuple[int, ...], str]]:
            rows = rows_override if rows_override is not None else alignment_virtual_texture_contract.get("rows") or ()
            return _alignment_virtual_contract_preview_specs_helper(
                rows,
                alignment_contract_preview_path=_alignment_contract_preview_path,
            )

        def _refresh_alignment_virtual_sidecar_contract(
            parsed_mappings: Sequence[StaticSubmeshMapping],
        ) -> Dict[str, object]:
            rows = _alignment_virtual_contract_rows(parsed_mappings)
            preview_specs = _alignment_virtual_contract_preview_specs(parsed_mappings, rows)
            contract_state = _alignment_virtual_sidecar_contract_state_helper(
                rows,
                preview_specs,
                sidecar_text_for_path=lambda sidecar_key: _virtual_contract_sidecar_text_for_path_helper(
                    sidecar_key,
                    sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                    sidecar_texts_by_basename=sidecar_texts_by_basename,
                    sidecar_text_values=sidecar_text_values,
                    normalize_texture_reference=normalize_texture_reference_for_sidecar_lookup,
                ),
                prune_removed_targets_enabled=_virtual_contract_prune_removed_targets_enabled(),
                prune_unmapped_enabled=_virtual_contract_prune_unmapped_enabled(),
            )
            alignment_virtual_texture_contract.clear()
            alignment_virtual_texture_contract.update(contract_state)
            return alignment_virtual_texture_contract

        _alignment_startup_step(alignment_startup_text["advanced_dds_classification"])
        for row_index, row_state in enumerate(texture_override_rows):
            if row_index and row_index % 120 == 0:
                _alignment_startup_step(
                    _alignment_startup_advanced_dds_classification_progress_text_helper(row_index)
                )
        suggested_counts = _advanced_dds_suggested_source_counts_helper(texture_override_rows)
        for row_index, row_state in enumerate(texture_override_rows):
            if row_index and row_index % 120 == 0:
                _alignment_startup_step(
                    _alignment_startup_advanced_dds_guidance_progress_text_helper(row_index)
                )
            _advanced_dds_apply_guidance_state_helper(
                row_state,
                suggested_counts=suggested_counts,
                texture_row_is_shared=_texture_row_is_shared,
                reset_assignment_fields=True,
            )



        texture_workflow = QWidget()
        texture_workflow_layout = QVBoxLayout(texture_workflow)
        texture_workflow_layout.setContentsMargins(0, 0, 0, 0)
        texture_workflow_layout.setSpacing(3)
        texture_summary_label = QLabel()
        texture_summary_label.setWordWrap(True)
        texture_summary_label.setTextFormat(Qt.RichText)
        texture_summary_label.setObjectName("HintLabel")
        texture_workflow_layout.addWidget(texture_summary_label)
        texture_busy_bar = QProgressBar()
        texture_busy_bar.setRange(0, 0)
        texture_busy_bar.setTextVisible(True)
        texture_editor_control_text = _texture_editor_control_text_helper()
        texture_busy_bar.setFormat(str(texture_editor_control_text["texture_assignments_busy"]))
        texture_busy_bar.setVisible(False)
        texture_workflow_layout.addWidget(texture_busy_bar)
        texture_override_tree = QTreeWidget()
        texture_override_tree.setHeaderLabels(list(texture_editor_control_text["override_headers"]))
        texture_override_tree.setMinimumHeight(320)
        texture_override_tree.setMinimumWidth(0)
        _configure_alignment_tree(
            texture_override_tree,
            (120, 220, 96, 260, 180, 96, 240),
            max_height=0,
            stretch_columns=(1, 3, 6),
            persist_key="advanced_dds_overrides_v2",
        )
        selected_texture_editor = QWidget()
        selected_texture_editor_layout = QGridLayout(selected_texture_editor)
        selected_texture_editor_layout.setContentsMargins(0, 0, 0, 0)
        selected_texture_editor_layout.setHorizontalSpacing(4)
        selected_texture_editor_layout.setVerticalSpacing(2)
        selected_texture_editor_label = QLabel(str(texture_editor_control_text["selected_label"]))
        selected_texture_editor_label.setObjectName("HintLabel")
        selected_texture_editor_label.setMinimumWidth(0)
        selected_texture_editor_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        selected_role_combo = QComboBox()
        selected_role_combo.setMinimumWidth(118)
        selected_role_combo.setToolTip(str(texture_editor_control_text["role_tooltip"]))
        for role_kind in tuple(texture_editor_control_text["role_options"]):
            selected_role_combo.addItem(_texture_role_label_for_slot(role_kind), role_kind)
        selected_source_combo = QComboBox()
        selected_source_combo.setMinimumWidth(190)
        selected_source_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        selected_source_combo.setToolTip(str(texture_editor_control_text["source_tooltip"]))
        selected_choose_source_button = QPushButton(str(texture_editor_control_text["choose_button"]))
        selected_choose_source_button.setMinimumWidth(0)
        selected_choose_source_button.setMaximumWidth(82)
        selected_choose_source_button.setToolTip(str(texture_editor_control_text["choose_tooltip"]))
        selected_apply_suggestion_button = QPushButton(str(texture_editor_control_text["apply_suggestion_button"]))
        selected_apply_suggestion_button.setMinimumWidth(0)
        selected_apply_suggestion_button.setMaximumWidth(118)
        selected_apply_suggestion_button.setEnabled(False)
        selected_apply_suggestion_button.setToolTip(str(texture_editor_control_text["apply_suggestion_tooltip"]))
        selected_texture_editor_layout.addWidget(selected_texture_editor_label, 0, 0, 1, 6)
        selected_texture_editor_layout.addWidget(QLabel(str(texture_editor_control_text["role_label"])), 1, 0)
        selected_texture_editor_layout.addWidget(selected_role_combo, 1, 1)
        selected_texture_editor_layout.addWidget(QLabel(str(texture_editor_control_text["source_label"])), 1, 2)
        selected_texture_editor_layout.addWidget(selected_source_combo, 1, 3, 1, 2)
        selected_texture_editor_layout.addWidget(selected_choose_source_button, 1, 5)
        selected_texture_editor_layout.addWidget(selected_apply_suggestion_button, 1, 6)
        selected_texture_editor_layout.setColumnStretch(3, 1)
        texture_workflow_layout.addWidget(selected_texture_editor)
        texture_detail_browser = QTextBrowser()
        texture_detail_browser.setReadOnly(True)
        texture_detail_browser.setOpenExternalLinks(False)
        texture_detail_browser.setMinimumHeight(220)
        texture_detail_browser.setMinimumWidth(300)
        texture_detail_browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        texture_detail_browser.setTextInteractionFlags(Qt.TextSelectableByMouse)
        texture_detail_browser.setStyleSheet(
            texture_detail_browser.styleSheet()
            + "QTextBrowser { font-size: 8px; line-height: 1.08; }"
        )
        texture_details_splitter = QSplitter(Qt.Horizontal)
        texture_details_splitter.addWidget(texture_override_tree)
        texture_details_splitter.addWidget(texture_detail_browser)
        texture_details_splitter.setCollapsible(0, False)
        texture_details_splitter.setCollapsible(1, False)
        texture_details_splitter.setStretchFactor(0, 7)
        texture_details_splitter.setStretchFactor(1, 3)
        texture_details_splitter.setSizes([760, 320])
        texture_workflow_layout.addWidget(texture_details_splitter, 1)
        selected_texture_row: Dict[str, Optional[Dict[str, Any]]] = _selected_texture_row_initial_state_helper()
        selected_texture_editor_loading = _selected_texture_editor_loading_initial_state_helper()
        selected_texture_source_committing = _selected_texture_source_committing_initial_state_helper()






        def _refresh_texture_row_guidance() -> None:
            nonlocal texture_sets
            texture_sets = group_replacement_texture_sets(texture_files_for_mapping, obj_mesh=replacement_mesh_for_mapping)
            _apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets)
            for row_state in texture_override_rows:
                suggested_source = (
                    ""
                    if _texture_row_is_shared(row_state)
                    else _best_source_for_slot(
                        str(row_state.get("target_name", "") or ""),
                        tuple(row_state.get("source_indices", ()) or ()),
                        str(row_state.get("slot_kind", "") or "material"),
                        texture_sets,
                        parameter_name=str(row_state.get("parameter_name", "") or ""),
                        target_texture_path=str(row_state.get("target_path", "") or ""),
                        target_shader_family=str(row_state.get("shader_family", "") or ""),
                    )
                )
                row_state["suggested_source"] = suggested_source
            suggested_counts = _advanced_dds_suggested_source_counts_helper(texture_override_rows)
            for row_state in texture_override_rows:
                _advanced_dds_apply_guidance_state_helper(
                    row_state,
                    suggested_counts=suggested_counts,
                    texture_row_is_shared=_texture_row_is_shared,
                    texture_role_label_for_slot=_texture_role_label_for_slot,
                )
                sync_texture_row_assignment(row_state)
        alignment_texture_table_callbacks = create_alignment_texture_table_callbacks({**context, **globals(), **locals()})
        _sync_texture_selection_highlight = alignment_texture_table_callbacks._sync_texture_selection_highlight
        _diagnostics_for_target_html = alignment_texture_table_callbacks._diagnostics_for_target_html
        _current_texture_row = alignment_texture_table_callbacks._current_texture_row
        _current_texture_target_name = alignment_texture_table_callbacks._current_texture_target_name
        _sync_selected_texture_editor = alignment_texture_table_callbacks._sync_selected_texture_editor
        _refresh_texture_details = alignment_texture_table_callbacks._refresh_texture_details
        _set_texture_row_assignment = alignment_texture_table_callbacks._set_texture_row_assignment
        _update_texture_summary_label = alignment_texture_table_callbacks._update_texture_summary_label
        _apply_texture_row_to_item = alignment_texture_table_callbacks._apply_texture_row_to_item
        _refresh_texture_row_in_place = alignment_texture_table_callbacks._refresh_texture_row_in_place
        _refresh_texture_table = alignment_texture_table_callbacks._refresh_texture_table
        _texture_table_selection_changed = alignment_texture_table_callbacks._texture_table_selection_changed
        _selected_texture_role_changed = alignment_texture_table_callbacks._selected_texture_role_changed
        _commit_texture_row_source = alignment_texture_table_callbacks._commit_texture_row_source
        _selected_texture_source_changed = alignment_texture_table_callbacks._selected_texture_source_changed
        _choose_selected_texture_source = alignment_texture_table_callbacks._choose_selected_texture_source
        _clear_selected_texture_source = alignment_texture_table_callbacks._clear_selected_texture_source
        _apply_selected_texture_suggestion = alignment_texture_table_callbacks._apply_selected_texture_suggestion
        _texture_table_item_activated = alignment_texture_table_callbacks._texture_table_item_activated
        _apply_replacement_texture_plan_to_overrides = alignment_texture_table_callbacks._apply_replacement_texture_plan_to_overrides
        _apply_all_suggested_override_sources = alignment_texture_table_callbacks._apply_all_suggested_override_sources
        _clear_target_texture_assignments = alignment_texture_table_callbacks._clear_target_texture_assignments
        _selected_material_override_rows = alignment_texture_table_callbacks._selected_material_override_rows
        _clear_selected_material_texture_assignments = alignment_texture_table_callbacks._clear_selected_material_texture_assignments
        _choose_file_for_selected_material = alignment_texture_table_callbacks._choose_file_for_selected_material












        def _apply_texture_selected_part_filter() -> None:
            _refresh_texture_table()


        _confirm_texture_assignment_action = lambda title, planned_rows, *, reason: _confirm_texture_assignment_action_helper(
                dialog,
                title,
                planned_rows,
                reason=reason,
                summary_html=_texture_assignment_summary_html,
            )

        alignment_texture_table_callbacks = create_alignment_texture_table_callbacks({**context, **globals(), **locals()})
        _apply_replacement_texture_plan_to_overrides = alignment_texture_table_callbacks._apply_replacement_texture_plan_to_overrides
        _apply_all_suggested_override_sources = alignment_texture_table_callbacks._apply_all_suggested_override_sources
        _clear_target_texture_assignments = alignment_texture_table_callbacks._clear_target_texture_assignments
        _selected_material_override_rows = alignment_texture_table_callbacks._selected_material_override_rows
        _clear_selected_material_texture_assignments = alignment_texture_table_callbacks._clear_selected_material_texture_assignments
        _choose_file_for_selected_material = alignment_texture_table_callbacks._choose_file_for_selected_material


        def _apply_selected_source_material_textures() -> None:
            if not _ensure_advanced_dds_overrides_loaded(reason="use-selected"):
                return
            action_state = _selected_source_material_texture_action_state_helper(
                selected_texture_plan_source,
                texture_sets,
                texture_override_rows,
                texture_set_for_source_index=_texture_set_for_source_index,
                source_indices_for_material_name=lambda material_name: _source_indices_for_material_name_helper(
                    material_name,
                    replacement_mesh_for_mapping,
                    texture_set_count=len(texture_sets),
                    is_marker_source=_is_marker_source,
                ),
                texture_row_current_source_indices=texture_row_current_source_indices,
                source_slot_for_texture_row=_source_slot_for_texture_row_helper,
            )
            if action_state.message_key == "missing_selection":
                QMessageBox.information(
                    dialog,
                    str(material_plan_control_text["use_selected_missing_title"]),
                    str(material_plan_control_text["use_selected_missing_message"]),
                )
                return
            planned_rows = list(action_state.planned_rows)
            if not planned_rows:
                if action_state.message_key == "base_enabled":
                    rebuild_sidecar_checkbox.setChecked(True)
                    inject_base_color_checkbox.setChecked(True)
                    _queue_texture_preview_refresh()
                    QMessageBox.information(
                        dialog,
                        str(material_plan_control_text["use_selected_missing_title"]),
                        str(material_plan_control_text["use_selected_base_enabled"]),
                    )
                    return
                QMessageBox.information(
                    dialog,
                    str(material_plan_control_text["use_selected_missing_title"]),
                    str(material_plan_control_text["use_selected_no_rows"]),
                )
                return
            if not _confirm_texture_assignment_action(
                str(material_plan_control_text["use_selected"]),
                planned_rows,
                reason=str(material_plan_control_text["use_selected_reason"]).format(material_name=action_state.material_name),
            ):
                return
            for row_state, source_path, _decision in planned_rows:
                _set_texture_row_assignment(row_state, source_path, True)
            if action_state.saw_base:
                rebuild_sidecar_checkbox.setChecked(True)
                inject_base_color_checkbox.setChecked(True)
            _refresh_texture_table(selected_texture_row.get("row"))
            _queue_texture_preview_refresh()




        def _use_route_source_for_selected_material() -> None:
            _apply_selected_source_material_textures()



        def _add_missing_texture_sources() -> None:
            selected_files, _selected_filter = QFileDialog.getOpenFileNames(
                dialog,
                str(material_plan_control_text["add_replacement_textures_title"]),
                str(obj_path.parent),
                str(material_plan_control_text["texture_file_filter"]),
            )
            added = _register_texture_source_files_helper(
                selected_files or (),
                texture_files_for_mapping=texture_files_for_mapping,
                seen_texture_file_keys=seen_texture_file_keys,
                allowed_extensions=SCENE_TEXTURE_SOURCE_EXTENSIONS,
            )
            add_state = _registered_texture_sources_action_state_helper(
                added,
                has_texture_sets=bool(texture_sets),
                rebuild_sidecar_checked=bool(rebuild_sidecar_checkbox.isChecked()),
            )
            if add_state.message_key == "none_added":
                return
            _refresh_texture_row_guidance()
            _refresh_source_material_plan()
            if add_state.should_check_rebuild_sidecar:
                rebuild_sidecar_checkbox.setChecked(True)
            _refresh_texture_table(selected_texture_row.get("row"))
            _queue_texture_preview_refresh()

        def _add_missing_texture_folder() -> None:
            selected_dir = QFileDialog.getExistingDirectory(
                dialog,
                str(material_plan_control_text["add_replacement_folder_title"]),
                str(obj_path.parent),
            )
            if not selected_dir:
                return
            added = _register_texture_source_files_helper(
                _texture_source_files_in_folder_helper(
                    selected_dir,
                    allowed_extensions=SCENE_TEXTURE_SOURCE_EXTENSIONS,
                ),
                texture_files_for_mapping=texture_files_for_mapping,
                seen_texture_file_keys=seen_texture_file_keys,
                allowed_extensions=SCENE_TEXTURE_SOURCE_EXTENSIONS,
            )
            add_state = _registered_texture_sources_action_state_helper(
                added,
                has_texture_sets=bool(texture_sets),
                rebuild_sidecar_checked=bool(rebuild_sidecar_checkbox.isChecked()),
            )
            if add_state.message_key == "none_added":
                return
            _refresh_texture_row_guidance()
            _refresh_source_material_plan()
            if add_state.should_check_rebuild_sidecar:
                rebuild_sidecar_checkbox.setChecked(True)
            _refresh_texture_table(selected_texture_row.get("row"))
            _queue_texture_preview_refresh()

        texture_filter_refresh["func"] = _apply_texture_selected_part_filter
        texture_override_tree.currentItemChanged.connect(_texture_table_selection_changed)
        texture_override_tree.itemActivated.connect(_texture_table_item_activated)
        selected_role_combo.currentIndexChanged.connect(_selected_texture_role_changed)
        selected_source_combo.currentIndexChanged.connect(_selected_texture_source_changed)
        selected_choose_source_button.clicked.connect(_choose_selected_texture_source)
        selected_apply_suggestion_button.clicked.connect(_apply_selected_texture_suggestion)
        apply_texture_plan_button.clicked.connect(_apply_replacement_texture_plan_to_overrides)
        apply_selected_source_textures_button.clicked.connect(_apply_selected_source_material_textures)
        material_use_route_source_button.clicked.connect(_use_route_source_for_selected_material)
        material_keep_original_button.clicked.connect(_clear_selected_material_texture_assignments)
        material_choose_file_button.clicked.connect(_choose_file_for_selected_material)
        material_neutralize_button.clicked.connect(_clear_selected_material_texture_assignments)
        material_do_not_emit_button.clicked.connect(_clear_selected_material_texture_assignments)
        apply_all_suggested_overrides_button.clicked.connect(_apply_all_suggested_override_sources)
        texture_filter_selected_checkbox.toggled.connect(_apply_texture_selected_part_filter)
        texture_show_advanced_checkbox.toggled.connect(_apply_texture_selected_part_filter)
        clear_target_textures_button.clicked.connect(_clear_target_texture_assignments)
        keep_original_target_button.clicked.connect(_clear_target_texture_assignments)
        do_not_emit_texture_button.clicked.connect(_clear_target_texture_assignments)
        add_textures_button.clicked.connect(_add_missing_texture_sources)
        add_texture_folder_button.clicked.connect(_add_missing_texture_folder)
        advanced_dds_load_button.clicked.connect(
            lambda _checked=False: _ensure_advanced_dds_overrides_loaded(reason="button")
        )
        texture_layout.addWidget(texture_workflow, 1)
        _refresh_texture_table()
        advanced_texture_section = CollapsibleSection(
            str(advanced_dds_control_text["section_title"]),
            expanded=False,
        )
        advanced_texture_section.toggled.connect(
            lambda expanded: _ensure_advanced_dds_overrides_loaded(reason="section") if expanded else None
        )
        advanced_texture_section.body_layout.addWidget(texture_group)
        textures_layout.addWidget(advanced_texture_section, 0)
        _queue_alignment_post_open_task(_queue_static_preview_refresh)
        initial_static_preview_refreshed = True
    elif False and sidecar_bindings:
        advanced_dds_control_text = _advanced_dds_control_text_helper()
        texture_group = QGroupBox(str(advanced_dds_control_text["legacy_group_title"]))
        texture_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        texture_layout = QVBoxLayout(texture_group)
        texture_layout.setAlignment(Qt.AlignTop)
        texture_hint = QLabel(
            str(advanced_dds_control_text["legacy_hint"])
        )
        texture_hint.setWordWrap(True)
        texture_hint.setObjectName("HintLabel")
        texture_layout.addWidget(texture_hint)
        if not texture_files_for_mapping:
            no_sources_hint = QLabel(
                str(advanced_dds_control_text["legacy_no_sources_hint"])
            )
            no_sources_hint.setWordWrap(True)
            no_sources_hint.setObjectName("HintLabel")
            texture_layout.addWidget(no_sources_hint)
        texture_filter_selected_checkbox = QCheckBox(
            str(advanced_dds_control_text["legacy_filter_selected"])
        )
        texture_filter_selected_checkbox.setToolTip(
            str(advanced_dds_control_text["legacy_filter_selected_tooltip"])
        )
        texture_layout.addWidget(texture_filter_selected_checkbox)
        texture_sets = group_replacement_texture_sets(texture_files_for_mapping, obj_mesh=replacement_mesh_for_mapping)
        _apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets)
        texture_tree = QTreeWidget()
        texture_tree.setHeaderLabels(list(advanced_dds_control_text["legacy_headers"]))
        texture_tree.setMinimumHeight(150)
        _configure_texture_mapping_tree(texture_tree, persist_key="legacy_texture_slot_mapping")
        active_mappings = list(suggested_mappings or [])
        seen_texture_rows: set[tuple[str, str, str, str]] = set()
        row_index = 0
        for mapping in active_mappings:
            for binding in sidecar_bindings:
                target_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
                if not target_path.lower().endswith(".dds"):
                    continue
                if not _binding_matches_target(binding, mapping.target_submesh_name):
                    continue
                parameter_name = str(getattr(binding, "parameter_name", "") or "").strip()
                texture_classification = classify_texture_binding(parameter_name, target_path)
                slot_kind = texture_classification.slot_kind
                visualized = texture_classification.visualized
                row_key = (
                    mapping.target_submesh_name.lower(),
                    parameter_name.lower(),
                    target_path.lower(),
                    slot_kind,
                )
                if row_key in seen_texture_rows:
                    continue
                seen_texture_rows.add(row_key)
                binding_part_name = str(getattr(binding, "part_name", "") or getattr(binding, "submesh_name", "") or "").strip()
                binding_shader_family = str(getattr(binding, "shader_family", "") or "").strip()
                binding_sidecar_kind = str(getattr(binding, "sidecar_kind", "") or "").strip()
                binding_linked_mesh = str(getattr(binding, "linked_mesh_path", "") or "").strip()
                part_display = binding_part_name or mapping.target_submesh_name
                if binding_shader_family:
                    part_display = f"{part_display} / {binding_shader_family}"
                checkbox = QCheckBox()
                combo = QComboBox()
                combo.setMinimumContentsLength(10)
                combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                combo.addItem("Auto / keep original", "")
                for texture_file in texture_files_for_mapping:
                    combo.addItem(texture_file.name, str(texture_file))
                suggested_source = _best_source_for_slot(
                    mapping.target_submesh_name,
                    mapping.source_submesh_indices,
                    slot_kind,
                    texture_sets,
                    parameter_name=parameter_name,
                    target_texture_path=target_path,
                    target_shader_family=binding_shader_family,
                )
                is_shared_texture_layer = is_shared_material_layer_texture(target_path)
                can_auto_assign_texture = bool(
                    suggested_source
                    and visualized
                    and not is_shared_texture_layer
                    and slot_kind in {"base", "normal", "material", "material_mask", "detail_mask", "height"}
                )
                if can_auto_assign_texture:
                    source_index = combo.findData(suggested_source)
                    if source_index >= 0:
                        combo.setCurrentIndex(source_index)
                        checkbox.setChecked(True)
                parameter_display = parameter_name or texture_classification.slot_label or slot_kind
                source_indices = tuple(mapping.source_submesh_indices)
                texture_item = _texture_assignment_slot_item_helper(
                    part_display=part_display,
                    parameter_display=parameter_display,
                    target_path=target_path,
                    source_indices=source_indices,
                    target_name=str(mapping.target_submesh_name or ""),
                    binding_part_name=binding_part_name,
                    binding_shader_family=binding_shader_family,
                    binding_sidecar_kind=binding_sidecar_kind,
                    binding_linked_mesh=binding_linked_mesh,
                    slot_label=str(texture_classification.slot_label or ""),
                    slot_kind=slot_kind,
                    semantic_type=str(texture_classification.semantic_type or ""),
                    semantic_subtype=str(texture_classification.semantic_subtype or ""),
                    reason=str(texture_classification.reason or ""),
                )
                texture_items_by_source.append((texture_item, source_indices))
                texture_tree.addTopLevelItem(texture_item)

                def _refresh_texture_status(
                    *,
                    item: QTreeWidgetItem = texture_item,
                    checkbox: QCheckBox = checkbox,
                    combo: QComboBox = combo,
                    visualized: bool = visualized,
                    is_shared_texture_layer: bool = is_shared_texture_layer,
                ) -> None:
                    has_source = bool(str(combo.currentData() or "").strip())
                    if is_shared_texture_layer and not checkbox.isChecked():
                        state_text = "Optional shared layer"
                        state_color = "#facc15"
                    elif not visualized:
                        state_text = "Not visualized"
                        state_color = "#facc15"
                    elif checkbox.isChecked() and has_source:
                        state_text = "Assigned"
                        state_color = "#86efac"
                    elif checkbox.isChecked():
                        state_text = "Auto"
                        state_color = "#93c5fd"
                    elif has_source:
                        state_text = "Preview-only"
                        state_color = "#93c5fd"
                    else:
                        state_text = "Original"
                        state_color = "#94a3b8"
                    item.setText(4, state_text)
                    item.setForeground(4, QBrush(QColor(state_color)))

                def _texture_combo_changed(
                    _index: int,
                    *,
                    checkbox: QCheckBox = checkbox,
                    combo: QComboBox = combo,
                    refresh_status: Callable[[], None] = _refresh_texture_status,
                ) -> None:
                    if str(combo.currentData() or "").strip():
                        checkbox.setChecked(True)
                    refresh_status()
                    _queue_texture_preview_refresh()

                combo.currentIndexChanged.connect(_texture_combo_changed)
                checkbox.toggled.connect(lambda _checked, refresh_status=_refresh_texture_status: (refresh_status(), _queue_texture_preview_refresh()))
                _refresh_texture_status()
                texture_tree.setItemWidget(texture_item, 0, checkbox)
                texture_tree.setItemWidget(texture_item, 5, combo)
                texture_override_rows.append(
                    (
                        checkbox,
                        combo,
                        target_path,
                        slot_kind,
                        mapping.target_submesh_name,
                        tuple(mapping.source_submesh_indices),
                        bool(visualized),
                    )
                )
                row_index += 1
        if row_index == 0:
            texture_layout.addWidget(
                QLabel(str(texture_editor_control_text["no_editable_slots"]))
            )
        else:
            def _apply_texture_selected_part_filter() -> None:
                selected_index = int(selected_source_part.get("index", -1))
                enabled = bool(texture_filter_selected_checkbox.isChecked()) if texture_filter_selected_checkbox is not None else False
                for item, source_indices in texture_items_by_source:
                    target_name = str(item.data(0, Qt.UserRole + 1) or "")
                    current_source_indices = _source_indices_for_target_name(target_name) or tuple(source_indices)
                    item.setData(0, Qt.UserRole, tuple(current_source_indices))
                    item.setHidden(bool(enabled and selected_index >= 0 and selected_index not in current_source_indices))

            texture_filter_refresh["func"] = _apply_texture_selected_part_filter
            texture_filter_selected_checkbox.toggled.connect(_apply_texture_selected_part_filter)
            _apply_texture_selected_part_filter()
            texture_layout.addWidget(texture_tree, 0)
            QTimer.singleShot(
                0,
                lambda tree=texture_tree: _fit_alignment_tree_height_to_rows(
                    tree,
                    minimum=150,
                    screen_margin=300,
                ),
            )
        def _set_advanced_dds_overrides_expanded(checked: bool) -> None:
            for child_widget in texture_group.findChildren(QWidget):
                child_widget.setVisible(bool(checked))
            texture_group.setMaximumHeight(16777215 if checked else max(28, texture_group.fontMetrics().height() + 12))

        texture_group.toggled.connect(_set_advanced_dds_overrides_expanded)
        _set_advanced_dds_overrides_expanded(False)
        textures_layout.addWidget(texture_group, 0)
        _queue_alignment_post_open_task(_queue_static_preview_refresh)
        initial_static_preview_refreshed = True
    elif not texture_assignment_rows_skipped:
        texture_editor_control_text = _texture_editor_control_text_helper()
        textures_layout.addWidget(QLabel(str(texture_editor_control_text["no_sidecar_slots"])), 0)
    if not initial_static_preview_refreshed:
        _queue_alignment_post_open_task(_queue_static_preview_refresh)

    return SimpleNamespace(
        _copied_source_texture_slot_overrides=locals().get('_copied_source_texture_slot_overrides'),
        _load_original_reference_texture_preview=locals().get('_load_original_reference_texture_preview'),
        _save_texture_transform_controls=locals().get('_save_texture_transform_controls'),
        binding=locals().get('binding'),
        rows=locals().get('rows'),
        source_index=locals().get('source_index'),
        target_name=locals().get('target_name'),
        texture_transform_offset_u_spin=locals().get('texture_transform_offset_u_spin'),
        texture_transform_offset_v_spin=locals().get('texture_transform_offset_v_spin'),
        texture_transform_scale_u_spin=locals().get('texture_transform_scale_u_spin'),
        texture_transform_scale_v_spin=locals().get('texture_transform_scale_v_spin'),
    )

def create_alignment_source_parts_outliner_section(context: dict[str, object]) -> SimpleNamespace:
    Dict = context.get('Dict')
    MeshReplacementPartsOutlinerTree = context.get('MeshReplacementPartsOutlinerTree')
    QAbstractItemView = context.get('QAbstractItemView')
    QCheckBox = context.get('QCheckBox')
    QComboBox = context.get('QComboBox')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    QGridLayout = context.get('QGridLayout')
    QGroupBox = context.get('QGroupBox')
    QHBoxLayout = context.get('QHBoxLayout')
    QKeySequence = context.get('QKeySequence')
    QLabel = context.get('QLabel')
    QPushButton = context.get('QPushButton')
    QShortcut = context.get('QShortcut')
    QSizePolicy = context.get('QSizePolicy')
    QSlider = context.get('QSlider')
    QTimer = context.get('QTimer')
    QTreeWidget = context.get('QTreeWidget')
    QTreeWidgetItem = context.get('QTreeWidgetItem')
    QVBoxLayout = context.get('QVBoxLayout')
    QWidget = context.get('QWidget')
    Qt = context.get('Qt')
    SOURCE_ROLE_OPTIONS = context.get('SOURCE_ROLE_OPTIONS')
    _alignment_dialog_widgets_live = context.get('_alignment_dialog_widgets_live')
    _alignment_startup_original_part_list_progress_text_helper = context.get('_alignment_startup_original_part_list_progress_text_helper')
    _alignment_startup_step = context.get('_alignment_startup_step')
    _append_mesh_part_to_geometry = context.get('_append_mesh_part_to_geometry')
    _apply_dds_detail_thumbnail_state = context.get('_apply_dds_detail_thumbnail_state')
    _apply_source_material_grouped_routing = context.get('_apply_source_material_grouped_routing')
    _apply_source_part_preview_changes = context.get('_apply_source_part_preview_changes')
    _auto_fit_alignment_tree_columns = context.get('_auto_fit_alignment_tree_columns')
    _clear_all_part_selections = context.get('_clear_all_part_selections')
    _commit_spinbox_text = context.get('_commit_spinbox_text')
    _configure_alignment_tree = context.get('_configure_alignment_tree')
    _copied_original_source_indices_helper = context.get('_copied_original_source_indices_helper')
    _copy_original_part_payload_helper = context.get('_copy_original_part_payload_helper')
    _copy_source_part_with_adjustment_helper = context.get('_copy_source_part_with_adjustment_helper')
    _dds_detail_clear_state_helper = context.get('_dds_detail_clear_state_helper')
    _delete_selected_source_parts = context.get('_delete_selected_source_parts')
    _duplicate_selected_part = context.get('_duplicate_selected_part')
    _fit_alignment_tree_height_to_rows = context.get('_fit_alignment_tree_height_to_rows')
    _install_alignment_tree_column_autofit = context.get('_install_alignment_tree_column_autofit')
    _is_marker_source = context.get('_is_marker_source')
    _make_double_spin_helper = context.get('_make_double_spin_helper')
    _mapping_role_hint = context.get('_mapping_role_hint')
    _mapping_route_button_style_helper = context.get('_mapping_route_button_style_helper')
    _mapping_route_control_text_helper = context.get('_mapping_route_control_text_helper')
    _mapping_route_primary_button_specs_helper = context.get('_mapping_route_primary_button_specs_helper')
    _mapping_route_selection_button_specs_helper = context.get('_mapping_route_selection_button_specs_helper')
    _mapping_table_action_control_text_helper = context.get('_mapping_table_action_control_text_helper')
    _mapping_table_build_initial_state_helper = context.get('_mapping_table_build_initial_state_helper')
    _mapping_table_build_requested_initial_state_helper = context.get('_mapping_table_build_requested_initial_state_helper')
    _mapping_table_column_max_widths_helper = context.get('_mapping_table_column_max_widths_helper')
    _mapping_table_column_min_widths_helper = context.get('_mapping_table_column_min_widths_helper')
    _mapping_table_expand_columns_helper = context.get('_mapping_table_expand_columns_helper')
    _mapping_table_height_fit_kwargs_helper = context.get('_mapping_table_height_fit_kwargs_helper')
    _mapping_table_queued_progress_text_helper = context.get('_mapping_table_queued_progress_text_helper')
    _mirror_submesh_x_helper = context.get('_mirror_submesh_x_helper')
    _normalize = context.get('_normalize')
    _original_part_action_control_text_helper = context.get('_original_part_action_control_text_helper')
    _original_part_clipboard_action_text_helper = context.get('_original_part_clipboard_action_text_helper')
    _original_part_clipboard_can_paste_helper = context.get('_original_part_clipboard_can_paste_helper')
    _original_part_tree_control_text_helper = context.get('_original_part_tree_control_text_helper')
    _original_part_tree_item_helper = context.get('_original_part_tree_item_helper')
    _original_target_label_helper = context.get('_original_target_label_helper')
    _part_inspector_loading_initial_state_helper = context.get('_part_inspector_loading_initial_state_helper')
    _part_physics_review_reason_helper = context.get('_part_physics_review_reason_helper')
    _part_selection_clear_scope_state_helper = context.get('_part_selection_clear_scope_state_helper')
    _parts_outliner_cache_initial_state_helper = context.get('_parts_outliner_cache_initial_state_helper')
    _parts_outliner_control_text_helper = context.get('_parts_outliner_control_text_helper')
    _parts_outliner_item_update_guard_initial_state_helper = context.get('_parts_outliner_item_update_guard_initial_state_helper')
    _physics_status_tooltip_helper = context.get('_physics_status_tooltip_helper')
    _qt_object_is_valid = context.get('_qt_object_is_valid')
    _queue_alignment_post_open_task = context.get('_queue_alignment_post_open_task')
    _queue_part_transform_preview_update = context.get('_queue_part_transform_preview_update')
    _queue_selection_preview_refresh = context.get('_queue_selection_preview_refresh')
    _reference_vertices_for_appended_part_helper = context.get('_reference_vertices_for_appended_part_helper')
    _refresh_added_part_texture_tree = context.get('_refresh_added_part_texture_tree')
    _refresh_source_material_plan = context.get('_refresh_source_material_plan')
    _remap_selected_source_index_helper = context.get('_remap_selected_source_index_helper')
    _remap_source_index_collection_helper = context.get('_remap_source_index_collection_helper')
    _remap_source_index_dict_helper = context.get('_remap_source_index_dict_helper')
    _reset_geometry_changes = context.get('_reset_geometry_changes')
    _rotate_xyz = context.get('_rotate_xyz')
    _source_display_name = context.get('_source_display_name')
    _source_mirror_plane_x_helper = context.get('_source_mirror_plane_x_helper')
    _source_part_inspector_control_text_helper = context.get('_source_part_inspector_control_text_helper')
    _source_part_transform_control_text_helper = context.get('_source_part_transform_control_text_helper')
    _source_parts_action_control_text_helper = context.get('_source_parts_action_control_text_helper')
    _source_physics_status_text_helper = context.get('_source_physics_status_text_helper')
    _source_role_label = context.get('_source_role_label')
    _source_texture_slot_count_helper = context.get('_source_texture_slot_count_helper')
    _source_tree_context_selection_initial_state_helper = context.get('_source_tree_context_selection_initial_state_helper')
    _source_tree_control_text_helper = context.get('_source_tree_control_text_helper')
    _source_tree_item_update_guard_initial_state_helper = context.get('_source_tree_item_update_guard_initial_state_helper')
    _source_tree_layout_state_helper = context.get('_source_tree_layout_state_helper')
    _source_tree_population_initial_state_helper = context.get('_source_tree_population_initial_state_helper')
    _source_tree_population_queued_text_helper = context.get('_source_tree_population_queued_text_helper')
    _suggested_mappings_by_target_helper = context.get('_suggested_mappings_by_target_helper')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _target_contract_source_indices_helper = context.get('_target_contract_source_indices_helper')
    _target_display_name = context.get('_target_display_name')
    _target_physics_status_text_helper = context.get('_target_physics_status_text_helper')
    _target_texture_status_details_helper = context.get('_target_texture_status_details_helper')
    _target_texture_status_text_helper = context.get('_target_texture_status_text_helper')
    _tree_item_primary_index_helper = context.get('_tree_item_primary_index_helper')
    _undo_geometry_change = context.get('_undo_geometry_change')
    _update_selection_context = context.get('_update_selection_context')
    _wrap_spin_with_slider_helper = context.get('_wrap_spin_with_slider_helper')
    added_texture_tree = context.get('added_texture_tree')
    alignment_part_clipboard = context.get('alignment_part_clipboard')
    alignment_startup_text = context.get('alignment_startup_text')
    clear_alignment_selection_button = context.get('clear_alignment_selection_button')
    complete_external_swap_checkbox = context.get('complete_external_swap_checkbox')
    control_tabs = context.get('control_tabs')
    copied_original_physics_sensitive_sources = context.get('copied_original_physics_sensitive_sources')
    copied_original_source_indices = context.get('copied_original_source_indices')
    create_alignment_original_clipboard_callbacks = context.get('create_alignment_original_clipboard_callbacks')
    create_alignment_original_copy_payload_callbacks = context.get('create_alignment_original_copy_payload_callbacks')
    create_alignment_original_part_copy_callbacks = context.get('create_alignment_original_part_copy_callbacks')
    create_alignment_original_reference_preview_callbacks = context.get('create_alignment_original_reference_preview_callbacks')
    create_alignment_original_source_filter_callbacks = context.get('create_alignment_original_source_filter_callbacks')
    create_alignment_original_texture_intent_callbacks = context.get('create_alignment_original_texture_intent_callbacks')
    create_alignment_parts_outliner_mapping_callbacks = context.get('create_alignment_parts_outliner_mapping_callbacks')
    create_alignment_selected_part_adjustment_callbacks = context.get('create_alignment_selected_part_adjustment_callbacks')
    create_alignment_selected_part_control_callbacks = context.get('create_alignment_selected_part_control_callbacks')
    create_alignment_selected_part_glow_picker_callbacks = context.get('create_alignment_selected_part_glow_picker_callbacks')
    create_alignment_selection_clear_callbacks = context.get('create_alignment_selection_clear_callbacks')
    create_alignment_selection_route_callbacks = context.get('create_alignment_selection_route_callbacks')
    create_alignment_source_part_assignment_callbacks = context.get('create_alignment_source_part_assignment_callbacks')
    create_alignment_source_part_geometry_action_callbacks = context.get('create_alignment_source_part_geometry_action_callbacks')
    create_alignment_source_part_glow_callbacks = context.get('create_alignment_source_part_glow_callbacks')
    create_alignment_source_part_transform_control_callbacks = context.get('create_alignment_source_part_transform_control_callbacks')
    create_alignment_source_role_flush_callbacks = context.get('create_alignment_source_role_flush_callbacks')
    create_alignment_source_role_tree_callbacks = context.get('create_alignment_source_role_tree_callbacks')
    create_alignment_source_tree_role_callbacks = context.get('create_alignment_source_tree_role_callbacks')
    create_alignment_source_tree_selection_callbacks = context.get('create_alignment_source_tree_selection_callbacks')
    dds_detail_label = context.get('dds_detail_label')
    dds_detail_panel = context.get('dds_detail_panel')
    dialog = context.get('dialog')
    mapping_edits_by_target = context.get('mapping_edits_by_target')
    mapping_layout = context.get('mapping_layout')
    material_plan_control_text = context.get('material_plan_control_text')
    material_plan_tree = context.get('material_plan_tree')
    material_routing_tree = context.get('material_routing_tree')
    original_items_by_index = context.get('original_items_by_index')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    parts_tab = context.get('parts_tab')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    selected_added_part_texture_row = context.get('selected_added_part_texture_row')
    selected_original_part = context.get('selected_original_part')
    selected_texture_plan_source = context.get('selected_texture_plan_source')
    selected_texture_row = context.get('selected_texture_row')
    sidecar_bindings = context.get('sidecar_bindings')
    source_parts_apply_state = context.get('source_parts_apply_state')
    suggested_mappings = context.get('suggested_mappings')
    texture_override_tree = context.get('texture_override_tree')
    texture_sets = context.get('texture_sets')

    prompt_shell_context = context.get('prompt_shell_context')

    def _late_context_value(name: str) -> object:
        if isinstance(prompt_shell_context, dict) and name in prompt_shell_context:
            return prompt_shell_context.get(name)
        return context.get(name)

    source_tree_control_text = _source_tree_control_text_helper()
    source_tree_layout_state = _source_tree_layout_state_helper()
    source_tree = QTreeWidget()
    source_tree.setHeaderLabels(list(source_tree_control_text["source_tree_headers"]))
    source_tree.setMinimumHeight(source_tree_layout_state.minimum_height)
    _configure_alignment_tree(
        source_tree,
        source_tree_layout_state.configure_widths,
        max_height=source_tree_layout_state.max_height,
        stretch_columns=source_tree_layout_state.expand_columns,
        persist_key=source_tree_layout_state.persist_key,
    )
    source_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
    source_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
    source_parts_group = QGroupBox(str(source_tree_control_text["source_group_title"]))
    source_parts_group.setObjectName("MeshReplacementReferenceParts")
    source_parts_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    source_parts_layout = QVBoxLayout(source_parts_group)
    source_parts_layout.setContentsMargins(5, 3, 5, 3)
    source_parts_layout.setSpacing(3)
    source_parts_layout.setAlignment(Qt.AlignTop)

    _source_index_from_tree_item = lambda item: _tree_item_primary_index_helper(item)



    source_tree_context_selection_state = _source_tree_context_selection_initial_state_helper()

    alignment_original_source_filter_callbacks = create_alignment_original_source_filter_callbacks({**context, **globals(), **locals(), '_selected_source_indices_from_tree': (lambda *args, **kwargs: _selected_source_indices_from_tree(*args, **kwargs))})
    _SourceTreeContextSelectionFilter = alignment_original_source_filter_callbacks._SourceTreeContextSelectionFilter

    source_tree_context_selection_filter = _SourceTreeContextSelectionFilter(source_tree)
    source_tree.viewport().installEventFilter(source_tree_context_selection_filter)





    source_tree_item_update_guard = _source_tree_item_update_guard_initial_state_helper()













    _copied_original_source_indices = lambda: _copied_original_source_indices_helper(
        replacement_mesh_for_mapping,
        copied_original_source_indices,
    )

    alignment_original_reference_preview_callbacks = create_alignment_original_reference_preview_callbacks({**context, **globals(), **locals()})
    _refresh_original_reference_preview = alignment_original_reference_preview_callbacks._refresh_original_reference_preview

    original_tree = QTreeWidget()
    original_part_tree_control_text = _original_part_tree_control_text_helper()
    original_tree.setHeaderLabels(list(original_part_tree_control_text["headers"]))
    original_tree.setMinimumHeight(72)
    _configure_alignment_tree(
        original_tree,
        (36, 130, 68, 98, 92),
        max_height=128,
        stretch_columns=(1, 4),
        persist_key="original_parts",
    )
    _alignment_startup_step(alignment_startup_text["original_part_list"])
    for original_index, original_part in enumerate(original_mesh_for_mapping.submeshes):
        if original_index and original_index % 25 == 0:
            _alignment_startup_step(_alignment_startup_original_part_list_progress_text_helper(original_index))
        label = getattr(original_part, "material", "") or getattr(original_part, "name", "") or f"target {original_index}"
        role_hint = _mapping_role_hint(f"{getattr(original_part, 'name', '')} {getattr(original_part, 'material', '')}")
        geometry_text = (
            f"{len(getattr(original_part, 'vertices', ()) or ()):,.0f} vertices, "
            f"{len(getattr(original_part, 'faces', ()) or ()):,.0f} faces"
        )
        original_item = _original_part_tree_item_helper(
            original_index=original_index,
            label=label,
            role_hint=role_hint,
            geometry_text=geometry_text,
            source_name=str(getattr(original_part, "name", "") or ""),
            source_material=str(getattr(original_part, "material", "") or ""),
        )
        original_tree.addTopLevelItem(original_item)
        original_items_by_index[original_index] = original_item

    original_part_action_control_text = _original_part_action_control_text_helper()
    original_copy_button = QPushButton(original_part_action_control_text["copy"])
    original_copy_assign_button = QPushButton(original_part_action_control_text["copy_assign"])
    original_clear_selection_button = QPushButton(original_part_action_control_text["clear_selection"])
    original_copy_button.setToolTip(original_part_action_control_text["copy_tooltip"])
    original_copy_assign_button.setToolTip(original_part_action_control_text["copy_assign_tooltip"])
    original_clear_selection_button.setToolTip(original_part_action_control_text["clear_selection_tooltip"])
    for original_button in (original_copy_button, original_copy_assign_button, original_clear_selection_button):
        original_button.setMinimumWidth(0)

    _original_index_from_tree_item = lambda item: _tree_item_primary_index_helper(item)
    _original_target_label = lambda original_index: _original_target_label_helper(
        original_index,
        original_mesh_for_mapping,
    )

    alignment_original_texture_intent_callbacks = create_alignment_original_texture_intent_callbacks({**context, **globals(), **locals()})
    _selected_original_index_from_tree = alignment_original_texture_intent_callbacks._selected_original_index_from_tree
    _original_part_texture_intent_rows = alignment_original_texture_intent_callbacks._original_part_texture_intent_rows
    _copied_original_texture_tooltip = alignment_original_texture_intent_callbacks._copied_original_texture_tooltip
    _copied_original_dds_badge = alignment_original_texture_intent_callbacks._copied_original_dds_badge

    _part_physics_review_reason = lambda label_text, part: _part_physics_review_reason_helper(
        label_text,
        part,
    )

    _copy_original_part_payload = lambda original_index: _copy_original_part_payload_helper(
        original_index,
        original_mesh_for_mapping,
        target_label=_original_target_label,
        role_hint=_mapping_role_hint,
        texture_intent_rows=_original_part_texture_intent_rows,
        physics_review_reason=_part_physics_review_reason,
    )



    alignment_original_copy_payload_callbacks = create_alignment_original_copy_payload_callbacks({**context, **globals(), **locals(), '_add_source_tree_item': (lambda *args, **kwargs: _add_source_tree_item(*args, **kwargs)), '_load_selected_part_controls': (lambda *args, **kwargs: _load_selected_part_controls(*args, **kwargs)), '_parse_mapping_edit': (lambda *args, **kwargs: _parse_mapping_edit(*args, **kwargs)), '_refresh_added_part_texture_tree': (lambda *args, **kwargs: _refresh_added_part_texture_tree(*args, **kwargs)), '_refresh_parts_outliner': (lambda *args, **kwargs: _refresh_parts_outliner(*args, **kwargs)), '_refresh_source_material_plan': (lambda *args, **kwargs: _refresh_source_material_plan(*args, **kwargs)), '_selected_target_index': (lambda *args, **kwargs: _selected_target_index(*args, **kwargs)), '_set_mapping_indices': (lambda *args, **kwargs: _set_mapping_indices(*args, **kwargs)), '_set_transform_source_indices': (lambda *args, **kwargs: _set_transform_source_indices(*args, **kwargs))})
    _refresh_copied_original_texture_ui = alignment_original_copy_payload_callbacks._refresh_copied_original_texture_ui
    _append_original_part_payload_as_source = alignment_original_copy_payload_callbacks._append_original_part_payload_as_source

    original_part_clipboard_action_text = _original_part_clipboard_action_text_helper()

    alignment_original_clipboard_callbacks = create_alignment_original_clipboard_callbacks({**context, **globals(), **locals()})
    _copy_original_part_to_alignment_clipboard = alignment_original_clipboard_callbacks._copy_original_part_to_alignment_clipboard
    _paste_alignment_part_clipboard_as_replacement_source = alignment_original_clipboard_callbacks._paste_alignment_part_clipboard_as_replacement_source
    _show_original_parts_context_menu = alignment_original_clipboard_callbacks._show_original_parts_context_menu

    _alignment_part_clipboard_can_paste = lambda: _original_part_clipboard_can_paste_helper(
        alignment_part_clipboard,
        original_mesh_for_mapping,
    )

    alignment_original_clipboard_callbacks = create_alignment_original_clipboard_callbacks({**context, **globals(), **locals()})
    _copy_original_part_to_alignment_clipboard = alignment_original_clipboard_callbacks._copy_original_part_to_alignment_clipboard
    _paste_alignment_part_clipboard_as_replacement_source = alignment_original_clipboard_callbacks._paste_alignment_part_clipboard_as_replacement_source
    _show_original_parts_context_menu = alignment_original_clipboard_callbacks._show_original_parts_context_menu


    alignment_original_part_copy_callbacks = create_alignment_original_part_copy_callbacks({**context, **globals(), **locals()})
    _copy_selected_original_part = alignment_original_part_copy_callbacks._copy_selected_original_part


    alignment_source_role_tree_callbacks = create_alignment_source_role_tree_callbacks({**context, **globals(), **locals()})
    _apply_source_role_selection = alignment_source_role_tree_callbacks._apply_source_role_selection
    _show_replacement_sources_context_menu = alignment_source_role_tree_callbacks._show_replacement_sources_context_menu
    _populate_source_tree_chunk = alignment_source_role_tree_callbacks._populate_source_tree_chunk


    alignment_source_tree_role_callbacks = create_alignment_source_tree_role_callbacks({**context, **globals(), **locals()})
    _open_source_tree_role_dropdown = alignment_source_tree_role_callbacks._open_source_tree_role_dropdown
    _handle_source_tree_item_clicked = alignment_source_tree_role_callbacks._handle_source_tree_item_clicked
    _finish_source_tree_population = alignment_source_tree_role_callbacks._finish_source_tree_population

    alignment_source_role_tree_callbacks = create_alignment_source_role_tree_callbacks({**context, **globals(), **locals()})
    _apply_source_role_selection = alignment_source_role_tree_callbacks._apply_source_role_selection
    _show_replacement_sources_context_menu = alignment_source_role_tree_callbacks._show_replacement_sources_context_menu
    _populate_source_tree_chunk = alignment_source_role_tree_callbacks._populate_source_tree_chunk



    original_copy_button.clicked.connect(lambda _checked=False: _copy_selected_original_part(assign_to_target=False))
    original_copy_assign_button.clicked.connect(lambda _checked=False: _copy_selected_original_part(assign_to_target=True))
    original_tree.setContextMenuPolicy(Qt.CustomContextMenu)
    original_tree.customContextMenuRequested.connect(_show_original_parts_context_menu)
    source_tree.setContextMenuPolicy(Qt.CustomContextMenu)
    source_tree.itemClicked.connect(_handle_source_tree_item_clicked)
    original_parts_label = QLabel(str(source_tree_control_text["original_label_html"]))
    original_parts_label.setTextFormat(Qt.RichText)
    original_parts_label.setVisible(False)
    mapping_layout.addWidget(original_parts_label)
    _fit_alignment_tree_height_to_rows(original_tree, minimum=72, screen_margin=520, maximum=220)
    _auto_fit_alignment_tree_columns(
        original_tree,
        (34, 100, 60, 110, 80),
        (48, 220, 140, 180, 160),
        expand_column=1,
    )
    original_tree.setVisible(False)
    mapping_layout.addWidget(original_tree, 0)
    original_button_panel = QWidget()
    original_button_panel.setVisible(False)
    original_button_row = QHBoxLayout(original_button_panel)
    original_button_row.setContentsMargins(0, 0, 0, 0)
    original_button_row.addWidget(original_copy_button)
    original_button_row.addWidget(original_copy_assign_button)
    original_button_row.addWidget(original_clear_selection_button)
    original_button_row.addStretch(1)
    mapping_layout.addWidget(original_button_panel)
    mapping_layout.addWidget(source_parts_group, 0)
    source_parts_group.setVisible(False)

    _alignment_startup_step(alignment_startup_text["replacement_source_queue"])
    source_tree_population_timer = QTimer(dialog)
    source_tree_population_timer.setInterval(0)
    source_tree_population_state = _source_tree_population_initial_state_helper()
    replacement_source_count = len(getattr(replacement_mesh_for_mapping, "submeshes", ()) or ())
    source_tree_progress_label = QLabel(_source_tree_population_queued_text_helper(replacement_source_count))
    source_tree_progress_label.setObjectName("HintLabel")
    source_tree_progress_label.setWordWrap(True)
    replacement_sources_label = QLabel(str(source_tree_control_text["replacement_label_html"]))
    replacement_sources_label.setTextFormat(Qt.RichText)
    replacement_sources_label.setVisible(False)
    source_parts_layout.addWidget(source_tree_progress_label)
    _fit_alignment_tree_height_to_rows(source_tree, **source_tree_layout_state.height_fit_kwargs)
    _auto_fit_alignment_tree_columns(
        source_tree,
        source_tree_layout_state.autofit_min_widths,
        source_tree_layout_state.autofit_max_widths,
        expand_columns=source_tree_layout_state.expand_columns,
    )
    _install_alignment_tree_column_autofit(
        source_tree,
        source_tree_layout_state.autofit_min_widths,
        source_tree_layout_state.autofit_max_widths,
        expand_columns=source_tree_layout_state.expand_columns,
    )
    source_parts_layout.addWidget(source_tree, 0)
    source_parts_button_row = QHBoxLayout()
    source_parts_button_row.setContentsMargins(0, 0, 0, 0)
    source_parts_button_row.setSpacing(4)
    source_parts_action_control_text = _source_parts_action_control_text_helper()
    delete_source_parts_button = QPushButton(source_parts_action_control_text["delete_button"])
    apply_source_parts_button = QPushButton(source_parts_action_control_text["apply_button"])
    delete_source_parts_button.setObjectName(source_parts_action_control_text["delete_object"])
    apply_source_parts_button.setObjectName(source_parts_action_control_text["apply_object"])
    delete_source_parts_button.setToolTip(source_parts_action_control_text["delete_tooltip"])
    apply_source_parts_button.setToolTip(source_parts_action_control_text["apply_tooltip"])
    apply_source_parts_button.setEnabled(bool(source_parts_apply_state.get("pending")))
    for source_parts_button in (delete_source_parts_button, apply_source_parts_button):
        source_parts_button.setMinimumWidth(0)
        source_parts_button_row.addWidget(source_parts_button)
    source_parts_button_row.addStretch(1)
    source_parts_layout.addLayout(source_parts_button_row)
    source_parts_pending_label = QLabel(source_parts_action_control_text["pending_label"])
    source_parts_pending_label.setObjectName("HintLabel")
    source_parts_pending_label.setWordWrap(True)
    source_parts_pending_label.setVisible(False)
    source_parts_layout.addWidget(source_parts_pending_label)
    source_parts_group.setMaximumHeight(16777215)

    _alignment_startup_step(alignment_startup_text["routing_controls"])
    mapping_table_action_control_text = _mapping_table_action_control_text_helper()
    mapping_tree = QTreeWidget()
    mapping_tree.setHeaderLabels(list(mapping_table_action_control_text["headers"]))
    mapping_tree.setMinimumHeight(96)
    _configure_alignment_tree(
        mapping_tree,
        (170, 70, 118, 190, 76, 88, 72),
        max_height=0,
        stretch_columns=(0, 3),
        persist_key="target_routing",
    )
    mapping_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    mapping_tree.setColumnHidden(1, True)
    mapping_tree.setProperty("cdmw_defer_autofit", True)
    mappings_by_target = _suggested_mappings_by_target_helper(suggested_mappings)
    initial_mapping_text_by_target: Dict[int, str] = {}
    mapping_table_build_state = _mapping_table_build_initial_state_helper()
    mapping_table_build_timer = QTimer(dialog)
    mapping_table_build_timer.setInterval(0)
    mapping_targets = tuple(getattr(original_mesh_for_mapping, "submeshes", ()) or ())
    mapping_progress_label = QLabel(
        _mapping_table_queued_progress_text_helper(len(mapping_targets))
    )
    mapping_progress_label.setObjectName("HintLabel")
    mapping_progress_label.setWordWrap(True)

    _target_contract_source_indices = lambda target_label_text: _target_contract_source_indices_helper(
        target_label_text,
        original_mesh_for_mapping,
        mapping_edits_by_target,
        mappings_by_target,
    )
    _source_texture_slot_count = lambda source_indices: _source_texture_slot_count_helper(
        source_indices,
        replacement_mesh_for_mapping,
        texture_sets,
    )
    _target_texture_status_details = lambda target_label_text: _target_texture_status_details_helper(
        target_label_text,
        sidecar_bindings,
        _target_contract_source_indices(target_label_text),
        replacement_mesh_for_mapping,
        texture_sets,
    )
    _target_texture_status_text = lambda target_label_text: _target_texture_status_text_helper(
        target_label_text,
        sidecar_bindings,
        _source_texture_slot_count(_target_contract_source_indices(target_label_text)),
    )
    _target_physics_status_text = lambda target_label_text, target: _target_physics_status_text_helper(
        target_label_text,
        target,
        physics_review_reason=_part_physics_review_reason,
    )

    _source_physics_status_text = lambda source_index, target_index=-1: _source_physics_status_text_helper(
        source_index,
        target_index,
        replacement_mesh_for_mapping,
        copied_original_physics_sensitive_sources,
        source_role_label=_source_role_label,
        source_display_name=_source_display_name,
        physics_review_reason=_part_physics_review_reason,
    )

    _physics_status_tooltip = lambda status_text: _physics_status_tooltip_helper(status_text)

    parts_outliner_control_text = _parts_outliner_control_text_helper()
    parts_outliner_group = QGroupBox(str(parts_outliner_control_text["title"]))
    parts_outliner_group.setObjectName("MeshReplacementPartsOutliner")
    parts_outliner_group.setToolTip(str(parts_outliner_control_text["tooltip"]))
    parts_outliner_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    parts_outliner_layout = QVBoxLayout(parts_outliner_group)
    parts_outliner_layout.setContentsMargins(5, 3, 5, 3)
    parts_outliner_layout.setSpacing(3)
    parts_outliner_tree = MeshReplacementPartsOutlinerTree()
    parts_outliner_tree.setObjectName("MeshReplacementUnifiedPartsOutliner")
    parts_outliner_tree.setHeaderLabels(list(parts_outliner_control_text["headers"]))
    parts_outliner_tree.setMinimumHeight(128)
    parts_outliner_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    parts_outliner_tree.setSelectionMode(QAbstractItemView.SingleSelection)
    parts_outliner_tree.setDragEnabled(True)
    parts_outliner_tree.setAcceptDrops(True)
    parts_outliner_tree.viewport().setAcceptDrops(True)
    parts_outliner_tree.setDropIndicatorShown(True)
    parts_outliner_tree.setDragDropMode(QAbstractItemView.InternalMove)
    parts_outliner_tree.setDefaultDropAction(Qt.MoveAction)
    parts_outliner_tree.setDragDropOverwriteMode(False)
    parts_outliner_tree.setProperty("cdmw_defer_autofit", True)
    _configure_alignment_tree(
        parts_outliner_tree,
        (150, 124, 78, 76, 82, 62, 110),
        max_height=340,
        stretch_columns=(0, 1, 6),
        persist_key="unified_parts_outliner",
    )
    parts_outliner_tree.setRootIsDecorated(True)
    parts_outliner_layout.addWidget(parts_outliner_tree, 0)
    parts_outliner_item_update_guard = _parts_outliner_item_update_guard_initial_state_helper()
    parts_outliner_cache_state = _parts_outliner_cache_initial_state_helper()
    parts_outliner_source_items: Dict[int, QTreeWidgetItem] = {}
    parts_outliner_target_items: Dict[int, QTreeWidgetItem] = {}























    low_confidence_filter_checkbox = QCheckBox(mapping_table_action_control_text["low_confidence_filter"])
    empty_targets_filter_checkbox = QCheckBox(mapping_table_action_control_text["empty_targets_filter"])



    mapping_table_build_requested = _mapping_table_build_requested_initial_state_helper()









    QTimer.singleShot(
        0,
        lambda: (
            _fit_alignment_tree_height_to_rows(original_tree, minimum=72, screen_margin=520, maximum=220),
            _fit_alignment_tree_height_to_rows(source_tree, **source_tree_layout_state.height_fit_kwargs),
            _fit_alignment_tree_height_to_rows(mapping_tree, **_mapping_table_height_fit_kwargs_helper()),
            _auto_fit_alignment_tree_columns(original_tree, (34, 100, 60, 110, 80), (48, 220, 140, 180, 160), expand_column=1),
            _auto_fit_alignment_tree_columns(source_tree, source_tree_layout_state.autofit_min_widths, source_tree_layout_state.autofit_max_widths, expand_columns=source_tree_layout_state.expand_columns),
            _auto_fit_alignment_tree_columns(
                mapping_tree,
                _mapping_table_column_min_widths_helper(),
                _mapping_table_column_max_widths_helper(),
                expand_columns=_mapping_table_expand_columns_helper(),
            ),
        ),
    )
    mapping_layout.addWidget(parts_outliner_group, 0)
    target_slots_label = QLabel(mapping_table_action_control_text["target_slots_html"])
    target_slots_label.setWordWrap(True)
    target_slots_label.setTextFormat(Qt.RichText)
    target_slots_label.setToolTip(mapping_table_action_control_text["target_slots_tooltip"])
    target_slots_label.setVisible(False)
    mapping_layout.addWidget(target_slots_label)
    mapping_layout.addWidget(mapping_progress_label)
    mapping_progress_label.setVisible(False)
    mapping_filter_row = QHBoxLayout()
    mapping_filter_row.addWidget(low_confidence_filter_checkbox)
    mapping_filter_row.addWidget(empty_targets_filter_checkbox)
    mapping_filter_row.addStretch(1)
    mapping_layout.addLayout(mapping_filter_row)
    clear_all_guesses_button = QPushButton(mapping_table_action_control_text["clear_all_guesses"])
    apply_best_guesses_button = QPushButton(mapping_table_action_control_text["apply_best_guesses"])
    group_materials_button = QPushButton(mapping_table_action_control_text["group_materials"])
    preview_target_button = QPushButton(mapping_table_action_control_text["preview_target"])
    clear_all_guesses_button.setToolTip(mapping_table_action_control_text["clear_all_guesses_tooltip"])
    apply_best_guesses_button.setToolTip(mapping_table_action_control_text["apply_best_guesses_tooltip"])
    group_materials_button.setToolTip(mapping_table_action_control_text["group_materials_tooltip"])
    preview_target_button.setToolTip(mapping_table_action_control_text["preview_target_tooltip"])
    for mapping_action_button in (
        clear_all_guesses_button,
        apply_best_guesses_button,
        group_materials_button,
        preview_target_button,
    ):
        mapping_action_button.setMinimumWidth(0)
    mapping_action_row = QHBoxLayout()
    mapping_action_row.addWidget(clear_all_guesses_button)
    mapping_action_row.addWidget(apply_best_guesses_button)
    mapping_action_row.addWidget(group_materials_button)
    mapping_action_row.addWidget(preview_target_button)
    mapping_action_row.addStretch(1)
    mapping_layout.addLayout(mapping_action_row)
    show_advanced_mapping_checkbox = QCheckBox(mapping_table_action_control_text["advanced_mapping"])
    show_advanced_mapping_checkbox.setToolTip(mapping_table_action_control_text["advanced_mapping_tooltip"])
    show_advanced_mapping_checkbox.setProperty("cdmw_default_on_for_all_users", True)
    show_advanced_mapping_checkbox.setChecked(True)
    mapping_layout.addWidget(show_advanced_mapping_checkbox)
    mapping_tree.setColumnHidden(2, True)
    mapping_tree.setVisible(False)

    mapping_layout.addWidget(mapping_tree, 0)

    mapping_status_label = QLabel(mapping_table_action_control_text["mapping_status_initial"])
    mapping_status_label.setWordWrap(True)
    mapping_status_label.setTextFormat(Qt.RichText)
    mapping_status_label.setObjectName("MeshRoutingSelectedContractSummary")
    mapping_layout.addWidget(mapping_status_label)
    mapping_buttons = QHBoxLayout()
    mapping_route_control_text = _mapping_route_control_text_helper()
    primary_route_buttons: dict[str, QPushButton] = {}
    for button_spec in _mapping_route_primary_button_specs_helper(mapping_route_control_text):
        route_button = QPushButton(button_spec.label)
        route_button.setObjectName(button_spec.object_name)
        route_button.setToolTip(button_spec.tooltip)
        route_button.setStyleSheet(_mapping_route_button_style_helper(button_spec.object_name, button_spec.color))
        route_button.setMinimumWidth(0)
        mapping_buttons.addWidget(route_button)
        primary_route_buttons[button_spec.key] = route_button
    assign_source_button = primary_route_buttons["assign_source"]
    merge_source_button = primary_route_buttons["merge_source"]
    remove_source_button = primary_route_buttons["remove_source"]
    clear_target_button = primary_route_buttons["clear_target"]
    mapping_buttons.addStretch(1)
    mapping_layout.addLayout(mapping_buttons)
    mapping_selection_buttons = QHBoxLayout()
    selection_route_buttons: dict[str, QPushButton] = {}
    for button_spec in _mapping_route_selection_button_specs_helper(mapping_route_control_text):
        selection_button = QPushButton(button_spec.label)
        selection_button.setToolTip(button_spec.tooltip)
        selection_button.setMinimumWidth(0)
        mapping_selection_buttons.addWidget(selection_button)
        selection_route_buttons[button_spec.key] = selection_button
    clear_replacement_selection_button = selection_route_buttons["clear_replacement"]
    clear_all_selection_button = selection_route_buttons["clear_all"]
    mapping_selection_buttons.addStretch(1)
    mapping_layout.addLayout(mapping_selection_buttons)

    parts_outliner_mapping_callbacks = create_alignment_parts_outliner_mapping_callbacks({
        **context,
        **globals(),
        **locals(),
        "_parts_outliner_selection_changed": lambda *args, **kwargs: _parts_outliner_selection_changed(*args, **kwargs),
        "_select_source_part_from_viewport": lambda *args, **kwargs: _select_source_part_from_viewport(*args, **kwargs),
        "_target_selection_changed": lambda *args, **kwargs: _target_selection_changed(*args, **kwargs),
    })
    _parts_outliner_source_label = parts_outliner_mapping_callbacks._parts_outliner_source_label
    _parts_outliner_source_geometry = parts_outliner_mapping_callbacks._parts_outliner_source_geometry
    _selected_source_indices_from_tree = parts_outliner_mapping_callbacks._selected_source_indices_from_tree
    _set_transform_source_indices = parts_outliner_mapping_callbacks._set_transform_source_indices
    _clear_transform_source_indices = parts_outliner_mapping_callbacks._clear_transform_source_indices
    _set_source_parts_apply_pending = parts_outliner_mapping_callbacks._set_source_parts_apply_pending
    _clear_source_parts_apply_pending = parts_outliner_mapping_callbacks._clear_source_parts_apply_pending
    _set_source_parts_preview_rebuild_pending = parts_outliner_mapping_callbacks._set_source_parts_preview_rebuild_pending
    _clear_source_parts_preview_rebuild_pending = parts_outliner_mapping_callbacks._clear_source_parts_preview_rebuild_pending
    _add_source_tree_item = parts_outliner_mapping_callbacks._add_source_tree_item
    _source_item_check_state_changed = parts_outliner_mapping_callbacks._source_item_check_state_changed
    _outliner_source_index_from_item = parts_outliner_mapping_callbacks._outliner_source_index_from_item
    _parts_outliner_set_source_selection = parts_outliner_mapping_callbacks._parts_outliner_set_source_selection
    _refresh_parts_outliner = parts_outliner_mapping_callbacks._refresh_parts_outliner
    _show_parts_outliner_context_menu = parts_outliner_mapping_callbacks._show_parts_outliner_context_menu
    _apply_parts_outliner_source_target = parts_outliner_mapping_callbacks._apply_parts_outliner_source_target
    _parts_outliner_drop_target_index = parts_outliner_mapping_callbacks._parts_outliner_drop_target_index
    _handle_parts_outliner_source_drop = parts_outliner_mapping_callbacks._handle_parts_outliner_source_drop
    _apply_parts_outliner_source_role = parts_outliner_mapping_callbacks._apply_parts_outliner_source_role
    _open_parts_outliner_target_dropdown = parts_outliner_mapping_callbacks._open_parts_outliner_target_dropdown
    _open_parts_outliner_role_dropdown = parts_outliner_mapping_callbacks._open_parts_outliner_role_dropdown
    _handle_parts_outliner_item_clicked = parts_outliner_mapping_callbacks._handle_parts_outliner_item_clicked
    _append_mapping_target_row = parts_outliner_mapping_callbacks._append_mapping_target_row
    _build_mapping_table_chunk = parts_outliner_mapping_callbacks._build_mapping_table_chunk
    _apply_target_slot_filters = parts_outliner_mapping_callbacks._apply_target_slot_filters
    _ensure_mapping_table_building = parts_outliner_mapping_callbacks._ensure_mapping_table_building
    _clear_all_mapping_guesses = parts_outliner_mapping_callbacks._clear_all_mapping_guesses
    _apply_best_mapping_guesses = parts_outliner_mapping_callbacks._apply_best_mapping_guesses
    _preview_selected_target_slot = parts_outliner_mapping_callbacks._preview_selected_target_slot
    _selected_source_index = parts_outliner_mapping_callbacks._selected_source_index
    _selected_target_index = parts_outliner_mapping_callbacks._selected_target_index
    _parse_mapping_edit = parts_outliner_mapping_callbacks._parse_mapping_edit
    _texture_set_for_source_index = parts_outliner_mapping_callbacks._texture_set_for_source_index
    _source_material_group_label = parts_outliner_mapping_callbacks._source_material_group_label
    _mapped_target_vertex_count = parts_outliner_mapping_callbacks._mapped_target_vertex_count
    _mapped_source_vertex_counts = parts_outliner_mapping_callbacks._mapped_source_vertex_counts
    _mapping_preserve_split_group_count = parts_outliner_mapping_callbacks._mapping_preserve_split_group_count
    _mapping_vertex_limit_issues = parts_outliner_mapping_callbacks._mapping_vertex_limit_issues
    _routing_source_material_labels = parts_outliner_mapping_callbacks._routing_source_material_labels
    _routing_effect_lines = parts_outliner_mapping_callbacks._routing_effect_lines
    _set_advanced_mapping_visible = parts_outliner_mapping_callbacks._set_advanced_mapping_visible
    _update_mapping_status = parts_outliner_mapping_callbacks._update_mapping_status
    _sync_target_mapping_tree_item = parts_outliner_mapping_callbacks._sync_target_mapping_tree_item
    _set_mapping_indices = parts_outliner_mapping_callbacks._set_mapping_indices

    alignment_source_tree_population_role_callbacks = create_alignment_source_tree_role_callbacks({**context, **globals(), **locals()})
    _finish_source_tree_population = alignment_source_tree_population_role_callbacks._finish_source_tree_population

    alignment_source_role_tree_population_callbacks = create_alignment_source_role_tree_callbacks({**context, **globals(), **locals()})
    _show_replacement_sources_context_menu = alignment_source_role_tree_population_callbacks._show_replacement_sources_context_menu
    _populate_source_tree_chunk = alignment_source_role_tree_population_callbacks._populate_source_tree_chunk
    source_tree.customContextMenuRequested.connect(_show_replacement_sources_context_menu)
    source_tree_population_timer.timeout.connect(_populate_source_tree_chunk)
    _queue_alignment_post_open_task(source_tree_population_timer.start)

    source_tree.itemChanged.connect(_source_item_check_state_changed)
    parts_outliner_tree.setContextMenuPolicy(Qt.CustomContextMenu)
    parts_outliner_tree.customContextMenuRequested.connect(_show_parts_outliner_context_menu)
    parts_outliner_tree.itemClicked.connect(_handle_parts_outliner_item_clicked)
    parts_outliner_tree.set_source_drop_handler(_handle_parts_outliner_source_drop)
    mapping_table_build_timer.timeout.connect(_build_mapping_table_chunk)
    low_confidence_filter_checkbox.toggled.connect(_apply_target_slot_filters)
    empty_targets_filter_checkbox.toggled.connect(_apply_target_slot_filters)
    clear_all_guesses_button.clicked.connect(_clear_all_mapping_guesses)
    apply_best_guesses_button.clicked.connect(_apply_best_mapping_guesses)
    show_advanced_mapping_checkbox.toggled.connect(_set_advanced_mapping_visible)
    _set_advanced_mapping_visible(show_advanced_mapping_checkbox.isChecked())
    control_tabs.currentChanged.connect(
        lambda index: _ensure_mapping_table_building()
        if control_tabs.widget(index) is parts_tab
        else None
    )









    _remap_source_index_collection = lambda values, index_map: _remap_source_index_collection_helper(
        tuple(values or ()),
        index_map,
    )
    _remap_selected_source_index = lambda value, index_map: _remap_selected_source_index_helper(
        value,
        index_map,
    )
    _remap_source_index_dict = lambda values, index_map, *, copy_values=False: _remap_source_index_dict_helper(
        values,
        index_map,
        copy_values=copy_values,
    )

    alignment_source_part_mutation_callbacks = None
    def _delete_selected_source_parts(source_indices: Optional[Sequence[int]] = None) -> None:
        alignment_source_part_mutation_callbacks._delete_selected_source_parts(source_indices)

    def _apply_source_part_preview_changes() -> None:
        alignment_source_part_mutation_callbacks._apply_source_part_preview_changes()

    def _apply_source_material_grouped_routing() -> None:
        alignment_source_part_mutation_callbacks._apply_source_material_grouped_routing()

    def _duplicate_selected_part(*, mirrored: bool = False) -> None:
        alignment_source_part_mutation_callbacks._duplicate_selected_part(mirrored=mirrored)

    def _append_mesh_part_to_geometry() -> None:
        alignment_source_part_mutation_callbacks._append_mesh_part_to_geometry()




    def _complete_external_swap_enabled() -> bool:
        checkbox = _late_context_value("complete_external_swap_checkbox")
        return bool(
            checkbox is not None
            and callable(getattr(checkbox, "isChecked", None))
            and checkbox.isChecked()
        )





    alignment_selection_route_callbacks = create_alignment_selection_route_callbacks({**context, **globals(), **locals()})
    _assign_selected_source_to_target = alignment_selection_route_callbacks._assign_selected_source_to_target
    _merge_selected_source_into_target = alignment_selection_route_callbacks._merge_selected_source_into_target
    _remove_selected_source_from_target = alignment_selection_route_callbacks._remove_selected_source_from_target
    _clear_selected_target = alignment_selection_route_callbacks._clear_selected_target




    alignment_selection_clear_callbacks = create_alignment_selection_clear_callbacks({**context, **globals(), **locals()})
    _clear_tree_current_item = alignment_selection_clear_callbacks._clear_tree_current_item
    _apply_part_selection_clear_scope_state = alignment_selection_clear_callbacks._apply_part_selection_clear_scope_state
    _clear_original_selection = alignment_selection_clear_callbacks._clear_original_selection
    _clear_replacement_selection = alignment_selection_clear_callbacks._clear_replacement_selection
    _clear_target_selection = alignment_selection_clear_callbacks._clear_target_selection

    def _clear_replacement_selection() -> None:
        clear_state = _part_selection_clear_scope_state_helper("replacement")
        _apply_part_selection_clear_scope_state(clear_state)
        _clear_tree_current_item(source_tree)
        _load_selected_part_controls()
        _sync_highlight_sets()
        _update_mapping_status()
        _update_selection_context()
        _queue_selection_preview_refresh()

    def _clear_target_selection() -> None:
        clear_state = _part_selection_clear_scope_state_helper("target")
        _apply_part_selection_clear_scope_state(clear_state)
        _clear_tree_current_item(mapping_tree)
        _load_selected_part_controls()
        _sync_highlight_sets()
        _refresh_original_reference_preview()
        _update_mapping_status()
        _update_selection_context()
        _queue_selection_preview_refresh()



    def _clear_all_part_selections() -> None:
        if not _alignment_dialog_widgets_live():
            return
        for tree in (source_tree, original_tree, mapping_tree, parts_outliner_tree):
            if not _qt_object_is_valid(tree):
                return
            previous_blocked = tree.blockSignals(True)
            try:
                _clear_tree_current_item(tree)
            finally:
                tree.blockSignals(previous_blocked)
        _apply_part_selection_clear_scope_state(_part_selection_clear_scope_state_helper("all"))
        if _qt_object_is_valid(added_texture_tree):
            _clear_tree_current_item(added_texture_tree)
        if isinstance(selected_added_part_texture_row, dict):
            selected_added_part_texture_row["source_index"] = -1
        if _qt_object_is_valid(texture_override_tree):
            _clear_tree_current_item(texture_override_tree)
        if isinstance(selected_texture_row, dict):
            selected_texture_row["row"] = None
        if _qt_object_is_valid(material_plan_tree):
            _clear_tree_current_item(material_plan_tree)
        if _qt_object_is_valid(material_routing_tree):
            _clear_tree_current_item(material_routing_tree)
        if isinstance(selected_texture_plan_source, dict):
            selected_texture_plan_source["material_name"] = ""
            selected_texture_plan_source["source_indices"] = ()
        if _qt_object_is_valid(dds_detail_label) and _qt_object_is_valid(dds_detail_panel):
            clear_state = _dds_detail_clear_state_helper(material_plan_control_text)
            dds_detail_label.setText(clear_state.detail_text)
            if callable(_apply_dds_detail_thumbnail_state):
                _apply_dds_detail_thumbnail_state(clear_state.thumbnail)
            dds_detail_panel.setVisible(clear_state.panel_visible)
        _sync_highlight_sets()
        _refresh_original_reference_preview()
        _load_selected_part_controls()
        _update_mapping_status()
        _update_selection_context()
        _queue_selection_preview_refresh()

    assign_source_button.clicked.connect(_assign_selected_source_to_target)
    merge_source_button.clicked.connect(_merge_selected_source_into_target)
    remove_source_button.clicked.connect(_remove_selected_source_from_target)
    clear_target_button.clicked.connect(_clear_selected_target)
    delete_source_parts_button.clicked.connect(lambda _checked=False: _delete_selected_source_parts())
    apply_source_parts_button.clicked.connect(_apply_source_part_preview_changes)
    group_materials_button.clicked.connect(_apply_source_material_grouped_routing)
    preview_target_button.clicked.connect(_preview_selected_target_slot)
    original_clear_selection_button.clicked.connect(_clear_original_selection)
    clear_replacement_selection_button.clicked.connect(_clear_replacement_selection)
    clear_all_selection_button.clicked.connect(_clear_all_part_selections)
    clear_alignment_selection_button.clicked.connect(_clear_all_part_selections)

    source_part_inspector_control_text = _source_part_inspector_control_text_helper()
    part_inspector = QGroupBox(source_part_inspector_control_text["group_title"])
    part_layout = QGridLayout(part_inspector)
    part_layout.setContentsMargins(5, 3, 5, 3)
    part_layout.setHorizontalSpacing(4)
    part_layout.setVerticalSpacing(2)
    part_workflow_hint = QLabel(source_part_inspector_control_text["workflow_hint"])
    part_workflow_hint.setObjectName("HintLabel")
    part_workflow_hint.setWordWrap(True)
    part_workflow_hint.setToolTip(source_part_inspector_control_text["workflow_hint_tooltip"])
    part_workflow_hint.setVisible(False)
    part_source_combo = QComboBox()
    part_source_combo.addItem(source_part_inspector_control_text["source_select_label"], -1)
    if replacement_mesh_for_mapping is not None:
        for source_index, source in enumerate(replacement_mesh_for_mapping.submeshes):
            if _is_marker_source(source):
                continue
            part_source_combo.addItem(_source_display_name(source_index), source_index)
    part_source_combo.setMinimumContentsLength(16)
    part_source_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    part_source_combo.setToolTip(source_part_inspector_control_text["source_combo_tooltip"])
    part_name_label = QLabel(source_part_inspector_control_text["name_placeholder"])
    part_name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    part_target_label = QLabel(source_part_inspector_control_text["target_placeholder"])
    part_target_label.setObjectName("HintLabel")
    part_enabled_checkbox = QCheckBox(source_part_inspector_control_text["include_in_output"])
    part_enabled_checkbox.setChecked(True)
    part_role_combo = QComboBox()
    for role_label, role_value in SOURCE_ROLE_OPTIONS:
        part_role_combo.addItem(role_label, role_value)
    part_role_combo.setToolTip(source_part_inspector_control_text["role_tooltip"])
    part_target_combo = QComboBox()
    part_target_combo.addItem(source_part_inspector_control_text["no_target_selected"], -1)
    if original_mesh_for_mapping is not None:
        for target_index, _target in enumerate(original_mesh_for_mapping.submeshes):
            part_target_combo.addItem(_target_display_name(target_index), target_index)
    part_target_combo.setToolTip(source_part_inspector_control_text["target_tooltip"])
    part_replace_target_button = QPushButton(source_part_inspector_control_text["replace_target"])
    part_add_target_button = QPushButton(source_part_inspector_control_text["add_target"])
    part_remove_target_button = QPushButton(source_part_inspector_control_text["unmap_part"])
    part_replace_target_button.setToolTip(source_part_inspector_control_text["replace_target_tooltip"])
    part_add_target_button.setToolTip(source_part_inspector_control_text["add_target_tooltip"])
    part_remove_target_button.setToolTip(source_part_inspector_control_text["unmap_part_tooltip"])
    part_layout.addWidget(part_name_label, 0, 0, 1, 4)
    part_layout.addWidget(part_target_label, 1, 0, 1, 4)
    part_layout.addWidget(part_workflow_hint, 2, 0, 1, 4)
    part_source_row = QHBoxLayout()
    part_source_row.setContentsMargins(0, 0, 0, 0)
    part_source_row.setSpacing(4)
    part_source_row.addWidget(QLabel(source_part_inspector_control_text["part_label"]))
    part_source_row.addWidget(part_source_combo, 1)
    append_mesh_part_button = QPushButton(source_part_inspector_control_text["add_mesh_part"])
    append_mesh_part_button.setMinimumWidth(0)
    append_mesh_part_button.setToolTip(source_part_inspector_control_text["add_mesh_part_tooltip"])
    duplicate_part_button = QPushButton(source_part_inspector_control_text["duplicate_part"])
    duplicate_part_button.setMinimumWidth(0)
    duplicate_part_button.setToolTip(source_part_inspector_control_text["duplicate_part_tooltip"])
    mirror_duplicate_part_button = QPushButton(source_part_inspector_control_text["mirror_duplicate_part"])
    mirror_duplicate_part_button.setMinimumWidth(0)
    mirror_duplicate_part_button.setToolTip(source_part_inspector_control_text["mirror_duplicate_part_tooltip"])
    part_source_row.addWidget(append_mesh_part_button)
    part_source_row.addWidget(duplicate_part_button)
    part_source_row.addWidget(mirror_duplicate_part_button)
    part_layout.addLayout(part_source_row, 3, 0, 1, 4)
    part_top_row = QHBoxLayout()
    part_top_row.setContentsMargins(0, 0, 0, 0)
    part_top_row.setSpacing(4)
    part_top_row.addWidget(part_enabled_checkbox)
    part_top_row.addWidget(QLabel(source_part_inspector_control_text["role_label"]))
    part_top_row.addWidget(part_role_combo, 1)
    part_top_row.addWidget(QLabel(source_part_inspector_control_text["map_to_label"]))
    part_top_row.addWidget(part_target_combo, 1)
    part_layout.addLayout(part_top_row, 4, 0, 1, 4)
    part_map_button_row = QHBoxLayout()
    part_map_button_row.setContentsMargins(0, 0, 0, 0)
    part_map_button_row.setSpacing(3)
    part_map_button_row.addWidget(part_replace_target_button)
    part_map_button_row.addWidget(part_add_target_button)
    part_map_button_row.addWidget(part_remove_target_button)
    part_layout.addLayout(part_map_button_row, 5, 0, 1, 4)
    part_copied_texture_row = QHBoxLayout()
    part_copied_texture_row.setContentsMargins(0, 0, 0, 0)
    part_copied_texture_row.setSpacing(3)
    part_copied_texture_status_label = QLabel(source_part_inspector_control_text["texture_status_initial"])
    part_copied_texture_status_label.setObjectName("HintLabel")
    part_use_copied_texture_button = QPushButton(source_part_inspector_control_text["use_copied_texture"])
    part_use_route_texture_button = QPushButton(source_part_inspector_control_text["use_route_texture"])
    part_remove_copied_texture_button = QPushButton(source_part_inspector_control_text["remove_copied_texture"])
    for copied_texture_button in (
        part_use_copied_texture_button,
        part_use_route_texture_button,
        part_remove_copied_texture_button,
    ):
        copied_texture_button.setMinimumWidth(0)
    part_use_copied_texture_button.setToolTip(source_part_inspector_control_text["use_copied_texture_tooltip"])
    part_use_route_texture_button.setToolTip(source_part_inspector_control_text["use_route_texture_tooltip"])
    part_remove_copied_texture_button.setToolTip(source_part_inspector_control_text["remove_copied_texture_tooltip"])
    part_copied_texture_row.addWidget(part_copied_texture_status_label, 1)
    part_copied_texture_row.addWidget(part_use_copied_texture_button)
    part_copied_texture_row.addWidget(part_use_route_texture_button)
    part_copied_texture_row.addWidget(part_remove_copied_texture_button)
    part_layout.addLayout(part_copied_texture_row, 6, 0, 1, 4)

    part_offset_x_spin = _make_double_spin_helper(0.0, -10.0, 10.0, 5, 0.0005)
    part_offset_y_spin = _make_double_spin_helper(0.0, -10.0, 10.0, 5, 0.0005)
    part_offset_z_spin = _make_double_spin_helper(0.0, -10.0, 10.0, 5, 0.0005)
    part_rotate_x_spin = _make_double_spin_helper(0.0, -360.0, 360.0, 2, 0.10, " deg")
    part_rotate_y_spin = _make_double_spin_helper(0.0, -360.0, 360.0, 2, 0.10, " deg")
    part_rotate_z_spin = _make_double_spin_helper(0.0, -360.0, 360.0, 2, 0.10, " deg")
    part_scale_x_spin = _make_double_spin_helper(1.0, 0.001, 100.0, 4, 0.005)
    part_scale_y_spin = _make_double_spin_helper(1.0, 0.001, 100.0, 4, 0.005)
    part_scale_z_spin = _make_double_spin_helper(1.0, 0.001, 100.0, 4, 0.005)
    part_uniform_spin = _make_double_spin_helper(1.0, 0.001, 100.0, 4, 0.005)
    part_controls = (
        part_offset_x_spin,
        part_offset_y_spin,
        part_offset_z_spin,
        part_rotate_x_spin,
        part_rotate_y_spin,
        part_rotate_z_spin,
        part_scale_x_spin,
        part_scale_y_spin,
        part_scale_z_spin,
        part_uniform_spin,
    )
    for axis_label, spin in (
        ("X", part_offset_x_spin),
        ("Y", part_offset_y_spin),
        ("Z", part_offset_z_spin),
        ("X", part_rotate_x_spin),
        ("Y", part_rotate_y_spin),
        ("Z", part_rotate_z_spin),
        ("X", part_scale_x_spin),
        ("Y", part_scale_y_spin),
        ("Z", part_scale_z_spin),
    ):
        spin.setPrefix(f"{axis_label} ")
    source_part_transform_control_text = _source_part_transform_control_text_helper()
    part_uniform_spin.setPrefix(source_part_transform_control_text["uniform_prefix"])
    for spin in (part_offset_x_spin, part_offset_y_spin, part_offset_z_spin):
        spin.setToolTip(source_part_transform_control_text["translate_spin_tooltip"])
    for spin in (part_rotate_x_spin, part_rotate_y_spin, part_rotate_z_spin):
        spin.setToolTip(source_part_transform_control_text["rotate_spin_tooltip"])
    for spin in (part_scale_x_spin, part_scale_y_spin, part_scale_z_spin):
        spin.setToolTip(source_part_transform_control_text["axis_spin_tooltip"])
    part_uniform_spin.setToolTip(source_part_transform_control_text["uniform_spin_tooltip"])
    for part_spin in part_controls:
        part_spin.setMinimumWidth(0)
        part_spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    part_transform_sliders: Dict[QDoubleSpinBox, QSlider] = {}

    alignment_source_part_transform_control_callbacks = create_alignment_source_part_transform_control_callbacks({**context, **globals(), **locals()})
    _part_transform_slider = alignment_source_part_transform_control_callbacks._part_transform_slider
    _sync_part_slider_from_spin = alignment_source_part_transform_control_callbacks._sync_part_slider_from_spin

    _part_spin_with_slider = lambda spin, *, scale, tooltip, slider_minimum=None, slider_maximum=None: _wrap_spin_with_slider_helper(
        spin,
        _part_transform_slider(
            spin,
            scale=scale,
            tooltip=tooltip,
            slider_minimum=slider_minimum,
            slider_maximum=slider_maximum,
        ),
    )


    part_layout.addWidget(QLabel(source_part_transform_control_text["translate_label"]), 7, 0)
    part_layout.addWidget(_part_spin_with_slider(part_offset_x_spin, scale=2000.0, tooltip=source_part_transform_control_text["translate_x_tooltip"]), 7, 1)
    part_layout.addWidget(_part_spin_with_slider(part_offset_y_spin, scale=2000.0, tooltip=source_part_transform_control_text["translate_y_tooltip"]), 7, 2)
    part_layout.addWidget(_part_spin_with_slider(part_offset_z_spin, scale=2000.0, tooltip=source_part_transform_control_text["translate_z_tooltip"]), 7, 3)
    part_nudge_step_spin = _make_double_spin_helper(0.005, 0.00001, 1.0, 5, 0.0005)
    part_nudge_step_spin.setPrefix(source_part_transform_control_text["nudge_step_prefix"])
    part_nudge_step_spin.setToolTip(source_part_transform_control_text["nudge_step_tooltip"])
    part_nudge_x_minus_button = QPushButton(source_part_transform_control_text["nudge_x_minus"])
    part_nudge_x_plus_button = QPushButton(source_part_transform_control_text["nudge_x_plus"])
    part_nudge_y_minus_button = QPushButton(source_part_transform_control_text["nudge_y_minus"])
    part_nudge_y_plus_button = QPushButton(source_part_transform_control_text["nudge_y_plus"])
    part_nudge_z_minus_button = QPushButton(source_part_transform_control_text["nudge_z_minus"])
    part_nudge_z_plus_button = QPushButton(source_part_transform_control_text["nudge_z_plus"])
    center_part_button = QPushButton(source_part_transform_control_text["center_part"])
    center_part_button.setToolTip(source_part_transform_control_text["center_part_tooltip"])
    part_nudge_row = QHBoxLayout()
    part_nudge_row.setContentsMargins(0, 0, 0, 0)
    part_nudge_row.setSpacing(3)
    part_nudge_row.addWidget(part_nudge_step_spin)
    for nudge_button in (
        part_nudge_x_minus_button,
        part_nudge_x_plus_button,
        part_nudge_y_minus_button,
        part_nudge_y_plus_button,
        part_nudge_z_minus_button,
        part_nudge_z_plus_button,
    ):
        nudge_button.setMinimumWidth(0)
        nudge_button.setToolTip(source_part_transform_control_text["nudge_tooltip"])
        part_nudge_row.addWidget(nudge_button)
    part_nudge_row.addWidget(center_part_button)
    part_layout.addLayout(part_nudge_row, 8, 0, 1, 4)
    part_layout.addWidget(QLabel(source_part_transform_control_text["rotate_label"]), 9, 0)
    part_layout.addWidget(_part_spin_with_slider(part_rotate_x_spin, scale=10.0, tooltip=source_part_transform_control_text["rotate_x_tooltip"]), 9, 1)
    part_layout.addWidget(_part_spin_with_slider(part_rotate_y_spin, scale=10.0, tooltip=source_part_transform_control_text["rotate_y_tooltip"]), 9, 2)
    part_layout.addWidget(_part_spin_with_slider(part_rotate_z_spin, scale=10.0, tooltip=source_part_transform_control_text["rotate_z_tooltip"]), 9, 3)
    axis_scale_label = QLabel(source_part_transform_control_text["axis_scale_label"])
    axis_scale_label.setToolTip(source_part_transform_control_text["axis_scale_tooltip"])
    part_layout.addWidget(axis_scale_label, 10, 0)
    part_layout.addWidget(
        _part_spin_with_slider(
            part_scale_x_spin,
            scale=1000.0,
            slider_minimum=0.1,
            slider_maximum=3.0,
            tooltip=source_part_transform_control_text["scale_x_tooltip"],
        ),
        10,
        1,
    )
    part_layout.addWidget(
        _part_spin_with_slider(
            part_scale_y_spin,
            scale=1000.0,
            slider_minimum=0.1,
            slider_maximum=3.0,
            tooltip=source_part_transform_control_text["scale_y_tooltip"],
        ),
        10,
        2,
    )
    part_layout.addWidget(
        _part_spin_with_slider(
            part_scale_z_spin,
            scale=1000.0,
            slider_minimum=0.1,
            slider_maximum=3.0,
            tooltip=source_part_transform_control_text["scale_z_tooltip"],
        ),
        10,
        3,
    )
    uniform_scale_label = QLabel(source_part_transform_control_text["uniform_scale_label"])
    uniform_scale_label.setToolTip(source_part_transform_control_text["uniform_scale_tooltip"])
    part_layout.addWidget(uniform_scale_label, 11, 0)
    part_layout.addWidget(
        _part_spin_with_slider(
            part_uniform_spin,
            scale=1000.0,
            slider_minimum=0.1,
            slider_maximum=3.0,
            tooltip=source_part_transform_control_text["uniform_scale_slider_tooltip"],
        ),
        11,
        1,
    )
    reset_part_button = QPushButton(source_part_transform_control_text["reset_part"])
    remove_part_button = QPushButton(source_part_transform_control_text["remove_part"])
    fit_part_button = QPushButton(source_part_transform_control_text["fit_part"])
    undo_geometry_button = QPushButton(source_part_transform_control_text["undo_geometry"])
    reset_geometry_button = QPushButton(source_part_transform_control_text["reset_geometry"])
    remove_part_button.setToolTip(source_part_transform_control_text["remove_part_tooltip"])
    reset_part_button.setToolTip(source_part_transform_control_text["reset_part_tooltip"])
    fit_part_button.setToolTip(source_part_transform_control_text["fit_part_tooltip"])
    undo_geometry_button.setToolTip(source_part_transform_control_text["undo_geometry_tooltip"])
    reset_geometry_button.setToolTip(source_part_transform_control_text["reset_geometry_tooltip"])
    undo_geometry_button.setEnabled(False)
    reset_geometry_button.setEnabled(False)
    part_button_row = QHBoxLayout()
    part_button_row.addWidget(remove_part_button)
    part_button_row.addWidget(reset_part_button)
    part_button_row.addWidget(fit_part_button)
    part_button_row.addWidget(undo_geometry_button)
    part_button_row.addWidget(reset_geometry_button)
    part_button_row.addStretch(1)
    part_layout.addLayout(part_button_row, 12, 0, 1, 4)
    part_inspector_loading = _part_inspector_loading_initial_state_helper()

    alignment_source_part_glow_callbacks = create_alignment_source_part_glow_callbacks({**context, **globals(), **locals()})
    _selected_part_glow_rgb_from_controls = alignment_source_part_glow_callbacks._selected_part_glow_rgb_from_controls
    _sync_part_glow_color_button = alignment_source_part_glow_callbacks._sync_part_glow_color_button
    _refresh_part_glow_color_controls_enabled = alignment_source_part_glow_callbacks._refresh_part_glow_color_controls_enabled
    _load_part_glow_color_controls = alignment_source_part_glow_callbacks._load_part_glow_color_controls




    alignment_source_role_flush_callbacks = create_alignment_source_role_flush_callbacks({**context, **globals(), **locals()})
    _apply_current_glow_color_to_role_overrides = alignment_source_role_flush_callbacks._apply_current_glow_color_to_role_overrides
    _flush_source_role_overrides_for_export = alignment_source_role_flush_callbacks._flush_source_role_overrides_for_export
    _refresh_ui_texture_sets_after_source_part_material_override = alignment_source_role_flush_callbacks._refresh_ui_texture_sets_after_source_part_material_override
    _part_mapped_target_indices = alignment_source_role_flush_callbacks._part_mapped_target_indices







    alignment_selected_part_adjustment_callbacks = create_alignment_selected_part_adjustment_callbacks({**context, **globals(), **locals(), '_queue_part_transform_preview_update': (lambda *args, **kwargs: _queue_part_transform_preview_update(*args, **kwargs))})
    _update_selected_part_adjustment = alignment_selected_part_adjustment_callbacks._update_selected_part_adjustment
    alignment_selected_part_control_callbacks = create_alignment_selected_part_control_callbacks({**context, **globals(), **locals()})
    _refresh_selected_part_copied_texture_controls = alignment_selected_part_control_callbacks._refresh_selected_part_copied_texture_controls
    _use_copied_original_texture_for_selected_source = alignment_selected_part_control_callbacks._use_copied_original_texture_for_selected_source
    _use_route_texture_for_selected_copied_source = alignment_selected_part_control_callbacks._use_route_texture_for_selected_copied_source
    _remove_copied_texture_from_selected_source = alignment_selected_part_control_callbacks._remove_copied_texture_from_selected_source
    _load_selected_part_controls = alignment_selected_part_control_callbacks._load_selected_part_controls
    _selected_part_source_changed = alignment_selected_part_control_callbacks._selected_part_source_changed
    _set_selected_source_role = alignment_selected_part_control_callbacks._set_selected_source_role
    _set_selected_source_glow_color = alignment_selected_part_control_callbacks._set_selected_source_glow_color
    _selected_part_target_index = alignment_selected_part_control_callbacks._selected_part_target_index
    _select_part_target_row = alignment_selected_part_control_callbacks._select_part_target_row
    _map_selected_part_to_combo_target = alignment_selected_part_control_callbacks._map_selected_part_to_combo_target
    _remove_selected_part_from_combo_target = alignment_selected_part_control_callbacks._remove_selected_part_from_combo_target
    _reset_selected_part = alignment_selected_part_control_callbacks._reset_selected_part
    _remove_selected_part_from_output = alignment_selected_part_control_callbacks._remove_selected_part_from_output




    alignment_selected_part_glow_picker_callbacks = create_alignment_selected_part_glow_picker_callbacks({**context, **globals(), **locals()})
    _pick_selected_source_glow_color = alignment_selected_part_glow_picker_callbacks._pick_selected_source_glow_color







    _reference_vertices_for_appended_part = lambda: _reference_vertices_for_appended_part_helper(
        original_mesh_for_mapping,
        target_index=_selected_target_index(),
        original_index=int(selected_original_part.get("index", -1)),
    )

    alignment_source_part_geometry_action_callbacks = create_alignment_source_part_geometry_action_callbacks({**context, **globals(), **locals()})
    _normalize_appended_part_to_work_area = alignment_source_part_geometry_action_callbacks._normalize_appended_part_to_work_area
    _fit_selected_part_size = alignment_source_part_geometry_action_callbacks._fit_selected_part_size
    _nudge_selected_part = alignment_source_part_geometry_action_callbacks._nudge_selected_part
    _nudge_selected_part_axis = alignment_source_part_geometry_action_callbacks._nudge_selected_part_axis
    _center_selected_part_on_target = alignment_source_part_geometry_action_callbacks._center_selected_part_on_target
    _add_dialog_supplemental_file = alignment_source_part_geometry_action_callbacks._add_dialog_supplemental_file






    alignment_source_part_assignment_callbacks = create_alignment_source_part_assignment_callbacks({**context, **globals(), **locals()})
    _prompt_assign_appended_mesh_parts = alignment_source_part_assignment_callbacks._prompt_assign_appended_mesh_parts
    _maybe_flatten_scene_import_parts = alignment_source_part_assignment_callbacks._maybe_flatten_scene_import_parts
    _maybe_reduce_high_density_scene_import = alignment_source_part_assignment_callbacks._maybe_reduce_high_density_scene_import
    _rebuild_source_part_widgets = alignment_source_part_assignment_callbacks._rebuild_source_part_widgets
    _source_mapping_target_indices = alignment_source_part_assignment_callbacks._source_mapping_target_indices






    _source_mirror_plane_x = lambda source_vertices: _source_mirror_plane_x_helper(
        original_mesh_for_mapping,
        source_vertices,
    )

    _copy_source_part_with_adjustment = lambda source, adjustment: _copy_source_part_with_adjustment_helper(
        source,
        adjustment,
        rotate_vector=_rotate_xyz,
        normalize_vector=_normalize,
    )

    _mirror_submesh_x = lambda source, plane_x: _mirror_submesh_x_helper(
        source,
        plane_x,
        normalize_vector=_normalize,
    )



    for part_spin in part_controls:
        part_spin.valueChanged.connect(_update_selected_part_adjustment)
        part_spin.editingFinished.connect(
            lambda spin=part_spin: (_commit_spinbox_text(spin), _update_selected_part_adjustment())
        )
    part_source_combo.currentIndexChanged.connect(_selected_part_source_changed)
    part_enabled_checkbox.toggled.connect(_update_selected_part_adjustment)
    part_role_combo.currentIndexChanged.connect(_set_selected_source_role)
    part_target_combo.currentIndexChanged.connect(_select_part_target_row)
    part_replace_target_button.clicked.connect(lambda _checked=False: _map_selected_part_to_combo_target(replace=True))
    part_add_target_button.clicked.connect(lambda _checked=False: _map_selected_part_to_combo_target(replace=False))
    part_remove_target_button.clicked.connect(_remove_selected_part_from_combo_target)
    part_use_copied_texture_button.clicked.connect(_use_copied_original_texture_for_selected_source)
    part_use_route_texture_button.clicked.connect(_use_route_texture_for_selected_copied_source)
    part_remove_copied_texture_button.clicked.connect(_remove_copied_texture_from_selected_source)
    remove_part_button.clicked.connect(_remove_selected_part_from_output)
    reset_part_button.clicked.connect(_reset_selected_part)
    fit_part_button.clicked.connect(_fit_selected_part_size)
    undo_geometry_button.clicked.connect(_undo_geometry_change)
    reset_geometry_button.clicked.connect(_reset_geometry_changes)
    part_nudge_x_minus_button.clicked.connect(lambda _checked=False: _nudge_selected_part_axis("x", -1.0))
    part_nudge_x_plus_button.clicked.connect(lambda _checked=False: _nudge_selected_part_axis("x", 1.0))
    part_nudge_y_minus_button.clicked.connect(lambda _checked=False: _nudge_selected_part_axis("y", -1.0))
    part_nudge_y_plus_button.clicked.connect(lambda _checked=False: _nudge_selected_part_axis("y", 1.0))
    part_nudge_z_minus_button.clicked.connect(lambda _checked=False: _nudge_selected_part_axis("z", -1.0))
    part_nudge_z_plus_button.clicked.connect(lambda _checked=False: _nudge_selected_part_axis("z", 1.0))
    center_part_button.clicked.connect(_center_selected_part_on_target)
    QShortcut(QKeySequence("Ctrl+Left"), dialog).activated.connect(lambda: _nudge_selected_part_axis("x", -1.0))
    QShortcut(QKeySequence("Ctrl+Right"), dialog).activated.connect(lambda: _nudge_selected_part_axis("x", 1.0))
    QShortcut(QKeySequence("Ctrl+Down"), dialog).activated.connect(lambda: _nudge_selected_part_axis("y", -1.0))
    QShortcut(QKeySequence("Ctrl+Up"), dialog).activated.connect(lambda: _nudge_selected_part_axis("y", 1.0))
    QShortcut(QKeySequence("Ctrl+PageDown"), dialog).activated.connect(lambda: _nudge_selected_part_axis("z", -1.0))
    QShortcut(QKeySequence("Ctrl+PageUp"), dialog).activated.connect(lambda: _nudge_selected_part_axis("z", 1.0))
    append_mesh_part_button.clicked.connect(_append_mesh_part_to_geometry)
    duplicate_part_button.clicked.connect(lambda _checked=False: _duplicate_selected_part(mirrored=False))
    mirror_duplicate_part_button.clicked.connect(lambda _checked=False: _duplicate_selected_part(mirrored=True))

    alignment_source_tree_selection_callbacks = create_alignment_source_tree_selection_callbacks({**context, **globals(), **locals()})
    _refresh_source_tree_selection_state = alignment_source_tree_selection_callbacks._refresh_source_tree_selection_state
    _source_selection_changed = alignment_source_tree_selection_callbacks._source_selection_changed
    _ensure_source_tree_item_available = alignment_source_tree_selection_callbacks._ensure_source_tree_item_available
    _select_source_part_from_viewport = alignment_source_tree_selection_callbacks._select_source_part_from_viewport
    _d3d11_source_part_selected = alignment_source_tree_selection_callbacks._d3d11_source_part_selected
    _original_selection_changed = alignment_source_tree_selection_callbacks._original_selection_changed
    _target_selection_changed = alignment_source_tree_selection_callbacks._target_selection_changed
    _parts_outliner_selection_changed = alignment_source_tree_selection_callbacks._parts_outliner_selection_changed
    _clear_part_selections_when_leaving_geometry = alignment_source_tree_selection_callbacks._clear_part_selections_when_leaving_geometry

    return SimpleNamespace(
        _add_dialog_supplemental_file=locals().get('_add_dialog_supplemental_file'),
        _add_source_tree_item=locals().get('_add_source_tree_item'),
        _alignment_part_clipboard_can_paste=locals().get('_alignment_part_clipboard_can_paste'),
        _append_original_part_payload_as_source=locals().get('_append_original_part_payload_as_source'),
        _apply_current_glow_color_to_role_overrides=locals().get('_apply_current_glow_color_to_role_overrides'),
        _apply_source_role_selection=locals().get('_apply_source_role_selection'),
        _clear_part_selections_when_leaving_geometry=locals().get('_clear_part_selections_when_leaving_geometry'),
        _clear_source_parts_preview_rebuild_pending=locals().get('_clear_source_parts_preview_rebuild_pending'),
        _clear_transform_source_indices=locals().get('_clear_transform_source_indices'),
        _clear_tree_current_item=locals().get('_clear_tree_current_item'),
        _copied_original_dds_badge=locals().get('_copied_original_dds_badge'),
        _copied_original_texture_tooltip=locals().get('_copied_original_texture_tooltip'),
        _copy_original_part_payload=locals().get('_copy_original_part_payload'),
        _copy_source_part_with_adjustment=locals().get('_copy_source_part_with_adjustment'),
        _d3d11_source_part_selected=locals().get('_d3d11_source_part_selected'),
        _finish_source_tree_population=locals().get('_finish_source_tree_population'),
        _flush_source_role_overrides_for_export=locals().get('_flush_source_role_overrides_for_export'),
        _load_part_glow_color_controls=locals().get('_load_part_glow_color_controls'),
        _load_selected_part_controls=locals().get('_load_selected_part_controls'),
        _mapping_vertex_limit_issues=locals().get('_mapping_vertex_limit_issues'),
        _maybe_flatten_scene_import_parts=locals().get('_maybe_flatten_scene_import_parts'),
        _maybe_reduce_high_density_scene_import=locals().get('_maybe_reduce_high_density_scene_import'),
        _mirror_submesh_x=locals().get('_mirror_submesh_x'),
        _normalize_appended_part_to_work_area=locals().get('_normalize_appended_part_to_work_area'),
        _original_index_from_tree_item=locals().get('_original_index_from_tree_item'),
        _original_part_texture_intent_rows=locals().get('_original_part_texture_intent_rows'),
        _original_selection_changed=locals().get('_original_selection_changed'),
        _original_target_label=locals().get('_original_target_label'),
        _parse_mapping_edit=locals().get('_parse_mapping_edit'),
        _part_mapped_target_indices=locals().get('_part_mapped_target_indices'),
        _parts_outliner_selection_changed=locals().get('_parts_outliner_selection_changed'),
        _parts_outliner_set_source_selection=locals().get('_parts_outliner_set_source_selection'),
        _paste_alignment_part_clipboard_as_replacement_source=locals().get('_paste_alignment_part_clipboard_as_replacement_source'),
        _physics_status_tooltip=locals().get('_physics_status_tooltip'),
        _pick_selected_source_glow_color=locals().get('_pick_selected_source_glow_color'),
        _prompt_assign_appended_mesh_parts=locals().get('_prompt_assign_appended_mesh_parts'),
        _rebuild_source_part_widgets=locals().get('_rebuild_source_part_widgets'),
        _reference_vertices_for_appended_part=locals().get('_reference_vertices_for_appended_part'),
        _refresh_copied_original_texture_ui=locals().get('_refresh_copied_original_texture_ui'),
        _refresh_original_reference_preview=locals().get('_refresh_original_reference_preview'),
        _refresh_part_glow_color_controls_enabled=locals().get('_refresh_part_glow_color_controls_enabled'),
        _refresh_parts_outliner=locals().get('_refresh_parts_outliner'),
        _refresh_source_tree_selection_state=locals().get('_refresh_source_tree_selection_state'),
        _refresh_ui_texture_sets_after_source_part_material_override=locals().get('_refresh_ui_texture_sets_after_source_part_material_override'),
        _remap_selected_source_index=locals().get('_remap_selected_source_index'),
        _remap_source_index_collection=locals().get('_remap_source_index_collection'),
        _remap_source_index_dict=locals().get('_remap_source_index_dict'),
        _select_source_part_from_viewport=locals().get('_select_source_part_from_viewport'),
        _selected_original_index_from_tree=locals().get('_selected_original_index_from_tree'),
        _selected_part_glow_rgb_from_controls=locals().get('_selected_part_glow_rgb_from_controls'),
        _selected_source_index=locals().get('_selected_source_index'),
        _selected_source_indices_from_tree=locals().get('_selected_source_indices_from_tree'),
        _selected_target_index=locals().get('_selected_target_index'),
        _set_mapping_indices=locals().get('_set_mapping_indices'),
        _set_selected_source_glow_color=locals().get('_set_selected_source_glow_color'),
        _set_source_parts_apply_pending=locals().get('_set_source_parts_apply_pending'),
        _set_source_parts_preview_rebuild_pending=locals().get('_set_source_parts_preview_rebuild_pending'),
        _set_transform_source_indices=locals().get('_set_transform_source_indices'),
        _source_index_from_tree_item=locals().get('_source_index_from_tree_item'),
        _source_mapping_target_indices=locals().get('_source_mapping_target_indices'),
        _source_material_group_label=locals().get('_source_material_group_label'),
        _source_mirror_plane_x=locals().get('_source_mirror_plane_x'),
        _source_physics_status_text=locals().get('_source_physics_status_text'),
        _source_selection_changed=locals().get('_source_selection_changed'),
        _sync_part_slider_from_spin=locals().get('_sync_part_slider_from_spin'),
        _sync_target_mapping_tree_item=locals().get('_sync_target_mapping_tree_item'),
        _target_physics_status_text=locals().get('_target_physics_status_text'),
        _target_selection_changed=locals().get('_target_selection_changed'),
        _target_texture_status_details=locals().get('_target_texture_status_details'),
        _target_texture_status_text=locals().get('_target_texture_status_text'),
        _texture_set_for_source_index=locals().get('_texture_set_for_source_index'),
        _update_mapping_status=locals().get('_update_mapping_status'),
        _update_selected_part_adjustment=locals().get('_update_selected_part_adjustment'),
        alignment_original_texture_intent_callbacks=locals().get('alignment_original_texture_intent_callbacks'),
        apply_best_guesses_button=locals().get('apply_best_guesses_button'),
        apply_source_parts_button=locals().get('apply_source_parts_button'),
        assign_source_button=locals().get('assign_source_button'),
        center_part_button=locals().get('center_part_button'),
        clear_all_guesses_button=locals().get('clear_all_guesses_button'),
        clear_state=locals().get('clear_state'),
        clear_target_button=locals().get('clear_target_button'),
        duplicate_part_button=locals().get('duplicate_part_button'),
        empty_targets_filter_checkbox=locals().get('empty_targets_filter_checkbox'),
        fit_part_button=locals().get('fit_part_button'),
        group_materials_button=locals().get('group_materials_button'),
        index=locals().get('index'),
        index_map=locals().get('index_map'),
        initial_mapping_text_by_target=locals().get('initial_mapping_text_by_target'),
        label_text=locals().get('label_text'),
        low_confidence_filter_checkbox=locals().get('low_confidence_filter_checkbox'),
        mapping_progress_label=locals().get('mapping_progress_label'),
        mapping_status_label=locals().get('mapping_status_label'),
        mapping_table_action_control_text=locals().get('mapping_table_action_control_text'),
        mapping_table_build_requested=locals().get('mapping_table_build_requested'),
        mapping_table_build_state=locals().get('mapping_table_build_state'),
        mapping_table_build_timer=locals().get('mapping_table_build_timer'),
        mapping_targets=locals().get('mapping_targets'),
        mapping_tree=locals().get('mapping_tree'),
        mappings_by_target=locals().get('mappings_by_target'),
        merge_source_button=locals().get('merge_source_button'),
        mirror_duplicate_part_button=locals().get('mirror_duplicate_part_button'),
        mirrored=locals().get('mirrored'),
        original_button_panel=locals().get('original_button_panel'),
        original_part_clipboard_action_text=locals().get('original_part_clipboard_action_text'),
        original_parts_label=locals().get('original_parts_label'),
        original_tree=locals().get('original_tree'),
        part_add_target_button=locals().get('part_add_target_button'),
        part_controls=locals().get('part_controls'),
        part_copied_texture_status_label=locals().get('part_copied_texture_status_label'),
        part_enabled_checkbox=locals().get('part_enabled_checkbox'),
        part_inspector=locals().get('part_inspector'),
        part_inspector_loading=locals().get('part_inspector_loading'),
        part_name_label=locals().get('part_name_label'),
        part_nudge_step_spin=locals().get('part_nudge_step_spin'),
        part_nudge_x_minus_button=locals().get('part_nudge_x_minus_button'),
        part_nudge_x_plus_button=locals().get('part_nudge_x_plus_button'),
        part_nudge_y_minus_button=locals().get('part_nudge_y_minus_button'),
        part_nudge_y_plus_button=locals().get('part_nudge_y_plus_button'),
        part_nudge_z_minus_button=locals().get('part_nudge_z_minus_button'),
        part_nudge_z_plus_button=locals().get('part_nudge_z_plus_button'),
        part_offset_x_spin=locals().get('part_offset_x_spin'),
        part_offset_y_spin=locals().get('part_offset_y_spin'),
        part_offset_z_spin=locals().get('part_offset_z_spin'),
        part_remove_copied_texture_button=locals().get('part_remove_copied_texture_button'),
        part_remove_target_button=locals().get('part_remove_target_button'),
        part_replace_target_button=locals().get('part_replace_target_button'),
        part_role_combo=locals().get('part_role_combo'),
        part_rotate_x_spin=locals().get('part_rotate_x_spin'),
        part_rotate_y_spin=locals().get('part_rotate_y_spin'),
        part_rotate_z_spin=locals().get('part_rotate_z_spin'),
        part_scale_x_spin=locals().get('part_scale_x_spin'),
        part_scale_y_spin=locals().get('part_scale_y_spin'),
        part_scale_z_spin=locals().get('part_scale_z_spin'),
        part_source_combo=locals().get('part_source_combo'),
        part_target_combo=locals().get('part_target_combo'),
        part_target_label=locals().get('part_target_label'),
        part_transform_sliders=locals().get('part_transform_sliders'),
        part_uniform_spin=locals().get('part_uniform_spin'),
        part_use_copied_texture_button=locals().get('part_use_copied_texture_button'),
        part_use_route_texture_button=locals().get('part_use_route_texture_button'),
        parts_outliner_cache_state=locals().get('parts_outliner_cache_state'),
        parts_outliner_item_update_guard=locals().get('parts_outliner_item_update_guard'),
        parts_outliner_source_items=locals().get('parts_outliner_source_items'),
        parts_outliner_target_items=locals().get('parts_outliner_target_items'),
        parts_outliner_tree=locals().get('parts_outliner_tree'),
        preview_target_button=locals().get('preview_target_button'),
        previous_blocked=locals().get('previous_blocked'),
        remove_part_button=locals().get('remove_part_button'),
        remove_source_button=locals().get('remove_source_button'),
        reset_geometry_button=locals().get('reset_geometry_button'),
        reset_part_button=locals().get('reset_part_button'),
        role_value=locals().get('role_value'),
        scale=locals().get('scale'),
        slider_maximum=locals().get('slider_maximum'),
        slider_minimum=locals().get('slider_minimum'),
        source_part_inspector_control_text=locals().get('source_part_inspector_control_text'),
        source_parts_group=locals().get('source_parts_group'),
        source_parts_pending_label=locals().get('source_parts_pending_label'),
        source_tree=locals().get('source_tree'),
        source_tree_context_selection_state=locals().get('source_tree_context_selection_state'),
        source_tree_item_update_guard=locals().get('source_tree_item_update_guard'),
        source_tree_layout_state=locals().get('source_tree_layout_state'),
        source_tree_population_state=locals().get('source_tree_population_state'),
        source_tree_population_timer=locals().get('source_tree_population_timer'),
        source_tree_progress_label=locals().get('source_tree_progress_label'),
        target=locals().get('target'),
        target_slots_label=locals().get('target_slots_label'),
        tooltip=locals().get('tooltip'),
        tree=locals().get('tree'),
        undo_geometry_button=locals().get('undo_geometry_button'),
        value=locals().get('value'),
        values=locals().get('values'),
    )

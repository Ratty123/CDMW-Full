"""Material authority adjustment callbacks for static replacement dialogs."""

from __future__ import annotations

from types import SimpleNamespace
from collections.abc import Callable, Mapping, Sequence

from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
    apply_material_parameter_preview,
    resident_material_preview_blocks_package_fallback,
    resident_material_resources_available,
)
from cdmw.ui.archive_browser.static_replacement_manual_material_profile import (
    material_authority_resource_channels,
)
from cdmw.ui.archive_browser.static_replacement_texture_async import (
    MaterialAuthorityResourceResult,
    StaticReplacementMaterialAuthorityResourceController,
)


def _material_resource_bindings_for_preview_model(
    preview_model: object,
    bindings: Sequence[Mapping[str, object]],
) -> tuple[tuple[dict[str, object], ...], tuple[int, ...]]:
    meshes = tuple(getattr(preview_model, "meshes", ()) or getattr(preview_model, "submeshes", ()) or ())
    material_indices: dict[str, list[int]] = {}
    path_indices: dict[str, list[int]] = {}
    for index, mesh in enumerate(meshes):
        material = str(getattr(mesh, "material_name", "") or getattr(mesh, "material", "") or "").strip().casefold()
        if material:
            material_indices.setdefault(material, []).append(index)
        paths = {
            str(getattr(mesh, name, "") or "").replace("\\", "/").strip().casefold()
            for name in (
                "texture", "preview_texture_path", "preview_texture_dds_path",
                "preview_normal_texture_path", "preview_normal_texture_dds_path",
                "preview_material_texture_path", "preview_material_texture_dds_path",
                "preview_height_texture_path", "preview_height_texture_dds_path",
            )
        }
        paths.update(
            str(getattr(item, name, "") or "").replace("\\", "/").strip().casefold()
            for item in tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())
            for name in ("source_texture_path", "source_dds_path", "preview_texture_path")
        )
        for path in paths:
            if path:
                path_indices.setdefault(path, []).append(index)
    enriched: list[dict[str, object]] = []
    affected: set[int] = set()
    for binding in bindings:
        row = dict(binding)
        logical = str(row.get("logical_path", "") or "").replace("\\", "/").strip().casefold()
        material = str(row.get("material_name", "") or "").strip().casefold()
        indices = tuple(sorted(set(path_indices.get(logical, ()) or material_indices.get(material, ()))))
        if not indices and len(material_indices) <= 1:
            indices = tuple(range(len(meshes)))
        if not indices:
            continue
        row["affected_submeshes"] = indices
        enriched.append(row)
        affected.update(indices)
    return tuple(enriched), tuple(sorted(affected))


def _preview_model_has_material_inputs(getter: object, fallback: object) -> bool:
    model = fallback
    if callable(getter):
        try:
            model = getter()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    for mesh in tuple(getattr(model, "meshes", ()) or ()):
        if tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ()):
            return True
        if any(
            str(getattr(mesh, name, "") or "").strip()
            for name in (
                "preview_texture_path",
                "preview_normal_texture_path",
                "preview_material_texture_path",
                "preview_height_texture_path",
            )
        ):
            return True
    return False


def _queue_material_resource_update(
    controller: StaticReplacementMaterialAuthorityResourceController,
    dialog: object,
    resource_keys: Sequence[object],
    *,
    preview_model_getter: object,
    texture_sets_getter: Callable[[], Mapping[str, object]],
    profile_getter: Callable[[], object],
    status_hint: object,
) -> bool:
    channels = material_authority_resource_channels(resource_keys)
    sender = getattr(dialog, "_mesh_editor_embedded_apply_material_resources", None)
    if not channels or not resident_material_resources_available(dialog) or not callable(sender):
        return False
    try:
        preview_model = preview_model_getter() if callable(preview_model_getter) else None
    except (AttributeError, RuntimeError, TypeError, ValueError):
        preview_model = None
    if preview_model is None:
        return False

    def completed(result: MaterialAuthorityResourceResult) -> bool:
        bindings, affected = _material_resource_bindings_for_preview_model(preview_model, result.bindings)
        return bool(
            bindings
            and affected
            and sender(preview_model, bindings, affected_submeshes=affected, reason=result.reason)
        )

    def failed(message: str) -> None:
        status_hint.setText(
            f"Resident material resource update failed; previous resources remain active: {message}"
        )

    return controller.start(
        texture_sets=texture_sets_getter(),
        material_profile=profile_getter(),
        affected_channels=channels,
        reason="material_authority_resource",
        on_complete=completed,
        on_error=failed,
    )


def create_material_authority_adjustment_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Dict = context.get('Dict')
    QSlider = context.get('QSlider')
    QSpinBox = context.get('QSpinBox')
    _complete_external_swap_enabled = context.get('_complete_external_swap_enabled')
    _current_complete_swap_material_profile_token = context.get('_current_complete_swap_material_profile_token')
    _manual_material_profile_fallback_payload_helper = context.get('_manual_material_profile_fallback_payload_helper')
    _material_authority_adjustment_refresh_reason_helper = context.get('_material_authority_adjustment_refresh_reason_helper')
    _material_authority_adjustment_setting_state_helper = context.get('_material_authority_adjustment_setting_state_helper')
    _material_authority_adjustment_status_text_helper = context.get('_material_authority_adjustment_status_text_helper')
    _material_authority_apply_sidecar_control_state_helper = context.get('_material_authority_apply_sidecar_control_state_helper')
    _material_authority_basic_controls_hint_helper = context.get('_material_authority_basic_controls_hint_helper')
    _material_authority_basic_controls_profile_enabled_helper = context.get('_material_authority_basic_controls_profile_enabled_helper')
    _material_authority_clamped_int_helper = context.get('_material_authority_clamped_int_helper')
    _material_authority_controls_affect_visible_preview_helper = context.get('_material_authority_controls_affect_visible_preview_helper')
    _material_authority_edge_relief_source_helper = context.get('_material_authority_edge_relief_source_helper')
    _material_authority_edge_relief_source_setting_helper = context.get('_material_authority_edge_relief_source_setting_helper')
    _material_authority_global_gloss_reduction_hint_helper = context.get('_material_authority_global_gloss_reduction_hint_helper')
    _material_authority_preview_inactive_reason_helper = context.get('_material_authority_preview_inactive_reason_helper')
    _material_authority_preview_native_override_values_helper = context.get('_material_authority_preview_native_override_values_helper')
    _material_authority_preview_signature_helper = context.get('_material_authority_preview_signature_helper')
    _material_authority_profile_adjustment_kwargs_helper = context.get('_material_authority_profile_adjustment_kwargs_helper')
    _material_authority_reset_values_helper = context.get('_material_authority_reset_values_helper')
    _material_authority_sidecar_dependent_toggle_state_helper = context.get('_material_authority_sidecar_dependent_toggle_state_helper')
    _material_authority_sidecar_option_state_helper = context.get('_material_authority_sidecar_option_state_helper')
    _original_texture_preview_material_preview_enabled_helper = context.get('_original_texture_preview_material_preview_enabled_helper')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _queue_material_edit_refresh = context.get('_queue_material_edit_refresh')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _refresh_manual_material_profile_panel = context.get('_refresh_manual_material_profile_panel')
    _refresh_output_impact_review = context.get('_refresh_output_impact_review')
    _refresh_part_glow_color_controls_enabled = context.get('_refresh_part_glow_color_controls_enabled')
    _selected_part_glow_rgb_from_controls = context.get('_selected_part_glow_rgb_from_controls')
    _set_int_slider_spin_value_silently_helper = context.get('_set_int_slider_spin_value_silently_helper')
    _modify_original_texture_tuning_enabled = context.get('_modify_original_texture_tuning_enabled')
    accent_glow_slider = context.get('accent_glow_slider')
    accent_glow_spin = context.get('accent_glow_spin')
    alignment_d3d11_preview_host = context.get('alignment_d3d11_preview_host')
    apply_true_source_basic_controls_to_profile = context.get('apply_true_source_basic_controls_to_profile')
    auto_brightness_slider = context.get('auto_brightness_slider')
    auto_brightness_spin = context.get('auto_brightness_spin')
    complete_swap_material_profile_combo = context.get('complete_swap_material_profile_combo')
    complete_swap_material_profile_to_dict = context.get('complete_swap_material_profile_to_dict')
    dialog = context.get('dialog')
    edge_relief_slider = context.get('edge_relief_slider')
    edge_relief_source_combo = context.get('edge_relief_source_combo')
    edge_relief_spin = context.get('edge_relief_spin')
    external_material_reset_checkbox = context.get('external_material_reset_checkbox')
    get_complete_swap_material_profile = context.get('get_complete_swap_material_profile')
    global_gloss_reduction_hint = context.get('global_gloss_reduction_hint')
    global_gloss_reduction_slider = context.get('global_gloss_reduction_slider')
    global_gloss_reduction_spin = context.get('global_gloss_reduction_spin')
    inject_base_color_checkbox = context.get('inject_base_color_checkbox')
    material_authority_preview_texture_slots = context.get('material_authority_preview_texture_slots')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    original_texture_preview_state = context.get('original_texture_preview_state')
    part_glow_color_checkbox = context.get('part_glow_color_checkbox')
    prune_unmapped_original_dds_checkbox = context.get('prune_unmapped_original_dds_checkbox')
    rebuild_sidecar_checkbox = context.get('rebuild_sidecar_checkbox')
    self = context.get('self')
    source_brightness_slider = context.get('source_brightness_slider')
    source_brightness_spin = context.get('source_brightness_spin')
    source_color_faithful_checkbox = context.get('source_color_faithful_checkbox')
    source_part_adjustments = context.get('source_part_adjustments')
    _get_replacement_preview_model = context.get('_get_replacement_preview_model')
    _get_texture_sets = context.get('_get_texture_sets')
    texture_sets = context.get('texture_sets')
    texture_overrides_dirty = context.get('texture_overrides_dirty')
    tone_contrast_slider = context.get('tone_contrast_slider')
    tone_contrast_spin = context.get('tone_contrast_spin')
    true_source_basic_group = context.get('true_source_basic_group')
    true_source_basic_hint = context.get('true_source_basic_hint')
    true_source_basic_reset_button = context.get('true_source_basic_reset_button')
    unsafe_material_preflight_checkbox = context.get('unsafe_material_preflight_checkbox')
    material_resource_controller = StaticReplacementMaterialAuthorityResourceController(self, dialog)
    setattr(dialog, "_mesh_editor_embedded_material_resources_finished", material_resource_controller.finish)
    dialog.finished.connect(material_resource_controller.request_shutdown)

    def _set_global_gloss_reduction(value: int, *, refresh: bool = True) -> None:
        value = _material_authority_clamped_int_helper(value, default=0, minimum=-100, maximum=100)
        value = _set_int_slider_spin_value_silently_helper(
            global_gloss_reduction_slider,
            global_gloss_reduction_spin,
            value,
            minimum=-100,
            maximum=100,
        )
        self.settings.setValue("settings/complete_swap_global_gloss_reduction", value)
        _refresh_global_gloss_reduction_hint()
        if refresh:
            _refresh_output_impact_review()
            _queue_material_authority_adjustment_preview_refresh()

    def _refresh_global_gloss_reduction_hint() -> None:
        value = int(global_gloss_reduction_spin.value())
        profile_name = str(complete_swap_material_profile_combo.currentData() or "")
        global_gloss_reduction_hint.setText(
            _material_authority_global_gloss_reduction_hint_helper(
                complete_enabled=_complete_external_swap_enabled(),
                profile_name=profile_name,
                value=value,
            )
        )

    def _basic_controls_profile_enabled() -> bool:
        profile_name = str(complete_swap_material_profile_combo.currentData() or "")
        return _material_authority_basic_controls_profile_enabled_helper(profile_name)

    def _material_authority_preview_route_enabled() -> bool:
        if bool(modify_original_clone_mode) and callable(_modify_original_texture_tuning_enabled):
            return bool(_modify_original_texture_tuning_enabled())
        return bool(_complete_external_swap_enabled())

    def _current_material_authority_preview_profile() -> object:
        return apply_true_source_basic_controls_to_profile(
            get_complete_swap_material_profile(str(_current_complete_swap_material_profile_token())),
            **(
                _material_authority_profile_adjustment_kwargs_helper(
                    global_gloss_reduction=0,
                    edge_relief=0,
                    edge_relief_source="hybrid",
                    accent_glow=0,
                    auto_brightness=0,
                    source_brightness=0,
                    tone_contrast=0,
                )
                if modify_original_clone_mode
                else _material_authority_profile_adjustment_kwargs_helper(
                    global_gloss_reduction=global_gloss_reduction_spin.value(),
                    edge_relief=edge_relief_spin.value(),
                    edge_relief_source=edge_relief_source_combo.currentData(),
                    accent_glow=accent_glow_spin.value(),
                    auto_brightness=auto_brightness_spin.value(),
                    source_brightness=source_brightness_spin.value(),
                    tone_contrast=tone_contrast_spin.value(),
                )
            ),
        )

    def _current_texture_sets_for_material_authority() -> Mapping[str, object]:
        getter = _get_texture_sets
        if not callable(getter):
            getter = context.get('_get_texture_sets')
        if callable(getter):
            try:
                current = getter()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                # Best effort: material authority can still use the captured texture-set fallback.
                current = None
            if current:
                return current
        return texture_sets or {}

    def _material_authority_preview_signature() -> Dict[str, str]:
        current_texture_sets = _current_texture_sets_for_material_authority()
        return _material_authority_preview_signature_helper(
            texture_sets=current_texture_sets,
            profile=_current_material_authority_preview_profile(),
            source_part_adjustments=source_part_adjustments,
            global_gloss_reduction=0 if modify_original_clone_mode else global_gloss_reduction_spin.value(),
            auto_brightness=0 if modify_original_clone_mode else auto_brightness_spin.value(),
            source_brightness=0 if modify_original_clone_mode else source_brightness_spin.value(),
            tone_contrast=0 if modify_original_clone_mode else tone_contrast_spin.value(),
            edge_relief=0 if modify_original_clone_mode else edge_relief_spin.value(),
            edge_relief_source="hybrid" if modify_original_clone_mode else edge_relief_source_combo.currentData(),
            accent_glow=0 if modify_original_clone_mode else accent_glow_spin.value(),
            glow_color_enabled=part_glow_color_checkbox.isChecked(),
            glow_rgb=_selected_part_glow_rgb_from_controls(),
            texture_slots_resolver=material_authority_preview_texture_slots,
            profile_payload_builder=complete_swap_material_profile_to_dict,
            fallback_profile_payload_builder=_manual_material_profile_fallback_payload_helper,
        )

    def _material_authority_preview_inactive_reason() -> str:
        original_material_preview_active = False
        try:
            original_material_preview_active = _original_texture_preview_material_preview_enabled_helper(
                modify_original_clone_mode,
                original_texture_preview_state,
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            # Best effort: this only affects explanatory inactive-reason text.
            pass
        current_texture_sets = _current_texture_sets_for_material_authority()
        return _material_authority_preview_inactive_reason_helper(
            complete_enabled=_material_authority_preview_route_enabled(),
            basic_profile_enabled=_basic_controls_profile_enabled(),
            has_texture_sets=bool(current_texture_sets) or _preview_model_has_material_inputs(
                _get_replacement_preview_model or context.get('_get_replacement_preview_model'),
                context.get('replacement_preview_model'),
            ),
            original_material_preview_active=original_material_preview_active,
        )

    def _material_authority_controls_affect_visible_preview() -> bool:
        return _material_authority_controls_affect_visible_preview_helper(
            _material_authority_preview_inactive_reason()
        )

    def _try_apply_material_authority_live_preview() -> bool:
        if not callable(_material_authority_preview_native_override_values_helper):
            return False
        override_values = _material_authority_preview_native_override_values_helper(
            _current_material_authority_preview_profile(),
            enabled=_material_authority_preview_route_enabled() and _basic_controls_profile_enabled(),
            base_brightness=1.0,
        )
        if not override_values:
            return False
        try:
            preview_model = _get_replacement_preview_model() if callable(_get_replacement_preview_model) else None
        except (AttributeError, RuntimeError, TypeError, ValueError):
            preview_model = None
        return apply_material_parameter_preview(
            dialog,
            override_values,
            legacy_active=bool(callable(_alignment_d3d11_preview_active) and _alignment_d3d11_preview_active()),
            legacy_host=alignment_d3d11_preview_host,
            dirty_state=texture_overrides_dirty if isinstance(texture_overrides_dirty, dict) else None,
            preview_model=preview_model,
            profile=_current_material_authority_preview_profile(),
            part_adjustments=source_part_adjustments,
        )

    def _queue_material_authority_adjustment_preview_refresh(
        *,
        resource_keys: Sequence[object] = (),
    ) -> None:
        inactive_reason = _material_authority_preview_inactive_reason()
        if inactive_reason:
            status_text = _material_authority_adjustment_status_text_helper(
                basic_profile_enabled=_basic_controls_profile_enabled(),
                inactive_reason=inactive_reason,
            )
            if status_text:
                true_source_basic_hint.setText(status_text)
            return
        true_source_basic_hint.setText(
            _material_authority_adjustment_status_text_helper(
                basic_profile_enabled=True,
                inactive_reason="",
            )
        )
        parameter_updated = _try_apply_material_authority_live_preview()
        resource_queued = _queue_material_resource_update(
            material_resource_controller,
            dialog,
            resource_keys,
            preview_model_getter=_get_replacement_preview_model,
            texture_sets_getter=_current_texture_sets_for_material_authority,
            profile_getter=_current_material_authority_preview_profile,
            status_hint=true_source_basic_hint,
        )
        if parameter_updated or resource_queued or resident_material_preview_blocks_package_fallback(dialog, context.get('_alignment_mesh_edit_tab_active')):
            return
        _queue_material_edit_refresh(
            refresh_plan=False,
            refresh_preview=True,
            reason=_material_authority_adjustment_refresh_reason_helper(),
        )

    def _set_spin_slider_pair(
        slider: QSlider,
        spin: QSpinBox,
        value: int,
        settings_key: str,
        *,
        minimum: int = 0,
        maximum: int = 100,
        refresh: bool = True,
        resource_keys: Sequence[object] = (),
    ) -> None:
        state = _material_authority_adjustment_setting_state_helper(
            value,
            default=minimum,
            minimum=minimum,
            maximum=maximum,
            settings_key=settings_key,
        )
        value = _set_int_slider_spin_value_silently_helper(
            slider,
            spin,
            int(state["value"]),
            minimum=minimum,
            maximum=maximum,
        )
        if state["settings_key"]:
            self.settings.setValue(str(state["settings_key"]), value)
        if refresh:
            _refresh_output_impact_review()
            _queue_material_authority_adjustment_preview_refresh(resource_keys=resource_keys)

    def _set_edge_relief(value: int, *, refresh: bool = True) -> None:
        _set_spin_slider_pair(
            edge_relief_slider,
            edge_relief_spin,
            value,
            "settings/complete_swap_edge_relief_strength",
            refresh=refresh,
            resource_keys=("edge_relief",),
        )

    def _set_source_brightness(value: int, *, refresh: bool = True) -> None:
        _set_spin_slider_pair(
            source_brightness_slider,
            source_brightness_spin,
            value,
            "settings/complete_swap_source_brightness",
            minimum=-100,
            maximum=100,
            refresh=refresh,
        )

    def _set_tone_contrast(value: int, *, refresh: bool = True) -> None:
        _set_spin_slider_pair(
            tone_contrast_slider,
            tone_contrast_spin,
            value,
            "settings/complete_swap_tone_contrast",
            minimum=-100,
            maximum=100,
            refresh=refresh,
        )

    def _set_auto_brightness(value: int, *, refresh: bool = True) -> None:
        _set_spin_slider_pair(
            auto_brightness_slider,
            auto_brightness_spin,
            value,
            "settings/complete_swap_auto_brightness",
            refresh=refresh,
        )

    def _set_edge_relief_source(*, refresh: bool = True) -> None:
        state = _material_authority_edge_relief_source_setting_helper(edge_relief_source_combo.currentData())
        self.settings.setValue(str(state["settings_key"]), str(state["value"]))
        if refresh:
            _refresh_output_impact_review()
            _queue_material_authority_adjustment_preview_refresh(resource_keys=("edge_relief_source",))

    def _set_accent_glow(value: int, *, refresh: bool = True) -> None:
        _set_spin_slider_pair(
            accent_glow_slider,
            accent_glow_spin,
            value,
            "",
            refresh=refresh,
            resource_keys=("accent_glow",),
        )
        if callable(_refresh_part_glow_color_controls_enabled):
            _refresh_part_glow_color_controls_enabled()

    def _set_edge_relief_source_value(value: str, *, refresh: bool = True) -> None:
        index = edge_relief_source_combo.findData(_material_authority_edge_relief_source_helper(value))
        if index < 0:
            index = 0
        if edge_relief_source_combo.currentIndex() != index:
            edge_relief_source_combo.blockSignals(True)
            edge_relief_source_combo.setCurrentIndex(index)
            edge_relief_source_combo.blockSignals(False)
        _set_edge_relief_source(refresh=refresh)

    def _reset_material_authority_adjustments() -> None:
        reset_values = _material_authority_reset_values_helper()
        _set_global_gloss_reduction(int(reset_values["global_gloss_reduction"]), refresh=False)
        _set_auto_brightness(int(reset_values["auto_brightness"]), refresh=False)
        _set_source_brightness(int(reset_values["source_brightness"]), refresh=False)
        _set_tone_contrast(int(reset_values["tone_contrast"]), refresh=False)
        _set_edge_relief(int(reset_values["edge_relief"]), refresh=False)
        _set_edge_relief_source_value(str(reset_values["edge_relief_source"]), refresh=False)
        _set_accent_glow(int(reset_values["accent_glow"]), refresh=False)
        _refresh_output_impact_review()
        _refresh_global_gloss_reduction_hint()
        _queue_material_authority_adjustment_preview_refresh(resource_keys=("*",))

    def _refresh_true_source_basic_controls_state() -> None:
        visible = _basic_controls_profile_enabled()
        enabled = bool(visible)
        true_source_basic_group.setVisible(bool(visible))
        true_source_basic_group.setEnabled(enabled)
        true_source_basic_hint.setText(
            _material_authority_basic_controls_hint_helper(
                visible=bool(visible),
                enabled=bool(enabled),
                inactive_reason=_material_authority_preview_inactive_reason() if enabled else "",
            )
        )

    def _refresh_sidecar_option_state() -> None:
        enabled = rebuild_sidecar_checkbox.isChecked()
        complete_mode = _complete_external_swap_enabled()
        sidecar_state = _material_authority_apply_sidecar_control_state_helper(
            _material_authority_sidecar_option_state_helper(
                sidecar_enabled=bool(enabled),
                complete_mode=bool(complete_mode),
                unsafe_preflight_checked=bool(unsafe_material_preflight_checkbox.isChecked()),
            ),
            rebuild_sidecar_widget=rebuild_sidecar_checkbox,
            dependent_widgets=(
                prune_unmapped_original_dds_checkbox,
                inject_base_color_checkbox,
                source_color_faithful_checkbox,
                external_material_reset_checkbox,
            ),
            complete_widgets=(
                complete_swap_material_profile_combo,
                global_gloss_reduction_slider,
                global_gloss_reduction_spin,
                auto_brightness_slider,
                auto_brightness_spin,
                source_brightness_slider,
                source_brightness_spin,
                tone_contrast_slider,
                tone_contrast_spin,
                edge_relief_slider,
                edge_relief_spin,
                edge_relief_source_combo,
                accent_glow_slider,
                accent_glow_spin,
                true_source_basic_reset_button,
            ),
            unsafe_preflight_widget=unsafe_material_preflight_checkbox,
        )
        if sidecar_state["force_rebuild_sidecar"]:
            return
        if callable(_refresh_part_glow_color_controls_enabled):
            _refresh_part_glow_color_controls_enabled()
        _refresh_global_gloss_reduction_hint()
        _refresh_manual_material_profile_panel()
        _refresh_true_source_basic_controls_state()

    def _apply_sidecar_dependent_toggle(checked: bool, *, refresh_output: bool = False) -> None:
        state = _material_authority_sidecar_dependent_toggle_state_helper(
            checked=checked,
            rebuild_sidecar_checked=rebuild_sidecar_checkbox.isChecked(),
            refresh_output=refresh_output,
        )
        if state["force_rebuild_sidecar"]:
            rebuild_sidecar_checkbox.setChecked(True)
            return
        if state["refresh_output"]:
            _refresh_output_impact_review()
        if state["refresh_preview"]:
            _queue_texture_preview_refresh()

    return SimpleNamespace(
        material_resource_controller=material_resource_controller,
        _set_global_gloss_reduction=_set_global_gloss_reduction,
        _refresh_global_gloss_reduction_hint=_refresh_global_gloss_reduction_hint,
        _basic_controls_profile_enabled=_basic_controls_profile_enabled,
        _current_material_authority_preview_profile=_current_material_authority_preview_profile,
        _material_authority_preview_signature=_material_authority_preview_signature,
        _material_authority_preview_inactive_reason=_material_authority_preview_inactive_reason,
        _material_authority_controls_affect_visible_preview=_material_authority_controls_affect_visible_preview,
        _queue_material_authority_adjustment_preview_refresh=_queue_material_authority_adjustment_preview_refresh,
        _set_spin_slider_pair=_set_spin_slider_pair,
        _set_edge_relief=_set_edge_relief,
        _set_source_brightness=_set_source_brightness,
        _set_tone_contrast=_set_tone_contrast,
        _set_auto_brightness=_set_auto_brightness,
        _set_edge_relief_source=_set_edge_relief_source,
        _set_accent_glow=_set_accent_glow,
        _set_edge_relief_source_value=_set_edge_relief_source_value,
        _reset_material_authority_adjustments=_reset_material_authority_adjustments,
        _refresh_true_source_basic_controls_state=_refresh_true_source_basic_controls_state,
        _refresh_sidecar_option_state=_refresh_sidecar_option_state,
        _apply_sidecar_dependent_toggle=_apply_sidecar_dependent_toggle,
    )

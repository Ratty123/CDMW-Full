"""Material authority adjustment callbacks for static replacement dialogs."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from collections.abc import Callable, Mapping, Sequence

from cdmw.domain.textures.material_authority_state import (
    MATERIAL_AUTHORITY_CONTROL_REGISTRY,
    MaterialAuthorityCapability,
    MaterialAuthorityResolvedState,
    MaterialAuthoritySyncStatus,
    identity_residual_parameter_groups,
    material_authority_control_states,
    material_authority_status_text,
    resolved_material_authority_state,
)
from cdmw.ui.archive_browser.static_replacement_dotnet_material_bridge import (
    apply_material_parameter_preview,
    resident_material_parameter_groups_for_model,
    resident_material_preview_blocks_package_fallback,
    resident_material_resources_available,
)
from cdmw.ui.archive_browser.static_replacement_manual_material_profile import (
    material_authority_resource_channels,
    material_authority_target_height_supported,
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


def _material_resource_binding_key(binding: Mapping[str, object]) -> tuple[str, ...]:
    resource_id = str(binding.get("resource_id", "") or "").strip().casefold()
    channel = str(binding.get("channel", "") or "").strip().casefold()
    if resource_id:
        return ("resource", resource_id, channel)
    return (
        "material",
        str(binding.get("material_name", "") or "").strip().casefold(),
        channel,
        str(binding.get("logical_path", "") or "").replace("\\", "/").strip().casefold(),
    )


def _merge_material_resource_bindings(
    previous: Sequence[Mapping[str, object]],
    current: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Replace only refreshed channels while retaining acknowledged artifacts."""

    rows: dict[tuple[str, ...], dict[str, object]] = {}
    for binding in tuple(previous or ()) + tuple(current or ()):
        if isinstance(binding, Mapping):
            rows[_material_resource_binding_key(binding)] = dict(binding)
    return tuple(rows[key] for key in sorted(rows))


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
    profile_values_getter: Callable[[object], Mapping[str, object]],
    parameter_values_getter: Callable[[object], Mapping[str, object]],
    part_adjustments: Mapping[int, object],
    expert_overrides_active_getter: Callable[[], bool],
    unsafe_export_acknowledged_getter: Callable[[], bool],
    sync_state_setter: Callable[[MaterialAuthoritySyncStatus, str, MaterialAuthorityResolvedState | None], None],
    status_hint: object,
    target_sidecar_bindings: object = (),
) -> bool:
    channels = material_authority_resource_channels(resource_keys)
    acknowledged = getattr(dialog, "_material_authority_acknowledged_resolved_state", None)
    if not isinstance(acknowledged, MaterialAuthorityResolvedState) or not acknowledged.dds_bindings:
        channels = material_authority_resource_channels(("*",))
    sender = getattr(dialog, "_mesh_editor_embedded_apply_material_resources", None)
    if not channels or not resident_material_resources_available(dialog) or not callable(sender):
        return False
    try:
        preview_model = preview_model_getter() if callable(preview_model_getter) else None
    except (AttributeError, RuntimeError, TypeError, ValueError):
        preview_model = None
    if preview_model is None:
        return False
    texture_sets = texture_sets_getter()
    profile = profile_getter()
    expert_overrides_active = bool(expert_overrides_active_getter())
    unsafe_export_acknowledged = bool(unsafe_export_acknowledged_getter())
    sync_state_setter(
        MaterialAuthoritySyncStatus.FAST_PREVIEW,
        "Resolving exact preview…",
        None,
    )

    def completed(result: MaterialAuthorityResourceResult) -> bool:
        bindings, affected = _material_resource_bindings_for_preview_model(preview_model, result.bindings)
        if not bindings or not affected:
            sync_state_setter(
                MaterialAuthoritySyncStatus.BLOCKED,
                "No generated DDS binding could be matched to the active preview submeshes.",
                None,
            )
            return False
        previous = getattr(dialog, "_material_authority_acknowledged_resolved_state", None)
        previous_bindings = tuple(getattr(previous, "dds_bindings", ()) or ())
        merged_bindings = _merge_material_resource_bindings(previous_bindings, bindings)
        merged_affected = tuple(
            sorted(
                set(affected).union(tuple(getattr(previous, "affected_submeshes", ()) or ()))
            )
        )
        available_channels = {
            "material_mask"
            if str(binding.get("channel", "") or "").strip().lower() == "material"
            else str(binding.get("channel", "") or "").strip().lower()
            for binding in merged_bindings
            if not bool(binding.get("remove", False))
        }
        if not any(
            not bool(binding.get("remove", False))
            and bool(str(binding.get("content_sha256", "") or "").strip())
            for binding in merged_bindings
        ):
            sync_state_setter(
                MaterialAuthoritySyncStatus.BLOCKED,
                "No readable DDS artifact can represent the active Material Authority route.",
                None,
            )
            return False
        parameter_values = dict(parameter_values_getter(profile) or {})
        parameter_groups = resident_material_parameter_groups_for_model(
            parameter_values,
            preview_model,
            profile=profile,
            part_adjustments=part_adjustments,
        )
        residual_groups = identity_residual_parameter_groups(
            parameter_groups,
            baked_channels=tuple(available_channels),
        )
        texture_set_rows = tuple(texture_sets.values()) if isinstance(texture_sets, Mapping) else ()
        source_slot_sets = tuple(
            {
                str(slot_name or "").strip().lower()
                for slot_name in (getattr(texture_set, "slots", {}) or {})
            }
            for texture_set in texture_set_rows
        )
        source_slots = tuple(sorted(set().union(*source_slot_sets))) if source_slot_sets else ()
        base_source_keys = {"base", "albedo", "diffuse"}
        mask_source_keys = {
            "material", "material_mask", "detail_mask", "roughness", "metallic",
            "metalness", "ao", "occlusion",
        }
        capability_channels = set(available_channels)
        if any(slots.intersection(base_source_keys) for slots in source_slot_sets):
            capability_channels.update({"base", "height"})
        if any(slots.intersection(mask_source_keys) for slots in source_slot_sets):
            capability_channels.add("material_mask")
        if any("normal" in slots for slots in source_slot_sets):
            capability_channels.update({"normal", "height"})
        if any("height" in slots or "displacement" in slots for slots in source_slot_sets):
            capability_channels.add("height")
        if any("emissive" in slots for slots in source_slot_sets):
            capability_channels.add("emissive")
        factor_only_base_applicable = any(
            not slots.intersection(base_source_keys)
            and bool(tuple(getattr(texture_set, "base_color_factor", ()) or ()))
            for texture_set, slots in zip(texture_set_rows, source_slot_sets)
        )
        factor_only_mask_applicable = any(
            not slots.intersection(mask_source_keys)
            and any(
                getattr(texture_set, name, None) is not None
                for name in ("roughness_factor", "metallic_factor", "specular_factor", "glossiness_factor")
            )
            for texture_set, slots in zip(texture_set_rows, source_slot_sets)
        )
        neutral_support_gap_applicable = any(
            not slots.intersection({"normal", "height", "displacement"})
            for slots in source_slot_sets
        )
        if factor_only_base_applicable:
            capability_channels.add("base")
        if factor_only_mask_applicable:
            capability_channels.add("material_mask")
        source_authoritative_channels = (
            ("material_mask",)
            if source_slot_sets and all(slots.intersection(mask_source_keys) for slots in source_slot_sets)
            else ()
        )
        authoritative_default_keys: list[str] = []
        if source_slot_sets and all(
            slots.intersection({"material", "material_mask", "detail_mask", "roughness", "glossiness"})
            or getattr(texture_set, "roughness_factor", None) is not None
            for texture_set, slots in zip(texture_set_rows, source_slot_sets)
        ):
            authoritative_default_keys.append("roughness_default")
        if source_slot_sets and all(
            slots.intersection({"material", "material_mask", "detail_mask", "metallic", "metalness", "specular"})
            or getattr(texture_set, "metallic_factor", None) is not None
            or getattr(texture_set, "specular_factor", None) is not None
            for texture_set, slots in zip(texture_set_rows, source_slot_sets)
        ):
            authoritative_default_keys.append("metallic_default")
        if source_slot_sets and all(
            slots.intersection({"material", "material_mask", "detail_mask", "ao", "occlusion"})
            for slots in source_slot_sets
        ):
            authoritative_default_keys.append("ao_default")
        has_explicit_glow = any(
            str(getattr(adjustment, "material_role", "") or "").strip().lower() in {"glow", "emissive"}
            for adjustment in part_adjustments.values()
        )
        if has_explicit_glow:
            capability_channels.add("emissive")
        declared_target_height = material_authority_target_height_supported(target_sidecar_bindings)
        usable_target_height = (
            "height" in capability_channels and declared_target_height is not False
        )
        previous_hashes = {
            _material_resource_binding_key(binding): (
                "remove" if bool(binding.get("remove", False)) else str(binding.get("content_sha256", "") or "")
            )
            for binding in previous_bindings
            if isinstance(binding, Mapping)
        }
        current_hashes = {
            _material_resource_binding_key(binding): (
                "remove" if bool(binding.get("remove", False)) else str(binding.get("content_sha256", "") or "")
            )
            for binding in bindings
        }
        previous_current_hashes = {
            key: previous_hashes[key] for key in current_hashes if key in previous_hashes
        }
        no_artifact_delta = bool(current_hashes) and current_hashes == previous_current_hashes
        delta_keys = (
            tuple(
                key
                for key, spec in MATERIAL_AUTHORITY_CONTROL_REGISTRY.items()
                if spec.capability is not MaterialAuthorityCapability.EXPERT_ONLY
            )
            if "*" in {str(key or "").strip() for key in resource_keys}
            else tuple(str(key or "").strip() for key in resource_keys)
        )
        artifact_deltas = {
            key: not no_artifact_delta for key in delta_keys
        }
        previous_parameters = tuple(
            dict(group)
            for group in tuple(getattr(previous, "residual_parameter_groups", ()) or ())
            if isinstance(group, Mapping)
        )
        parameter_delta = not previous_parameters or previous_parameters != tuple(residual_groups)
        parameter_deltas = {key: parameter_delta for key in delta_keys}
        control_states = material_authority_control_states(
            profile_values_getter(profile),
            available_channels=tuple(capability_channels),
            source_authoritative_channels=source_authoritative_channels,
            authoritative_default_keys=authoritative_default_keys,
            has_emissive_source="emissive" in source_slots,
            has_explicit_glow_part=has_explicit_glow,
            target_height_supported=usable_target_height,
            target_support_readable=bool(capability_channels.intersection({"normal", "height", "material_mask"})),
            factor_only_base_applicable=factor_only_base_applicable,
            factor_only_mask_applicable=factor_only_mask_applicable,
            neutral_support_gap_applicable=neutral_support_gap_applicable,
            artifact_deltas=artifact_deltas,
            parameter_deltas=parameter_deltas,
        )
        if has_explicit_glow and "emissive" not in available_channels:
            control_states = tuple(
                replace(
                    state,
                    capability=MaterialAuthorityCapability.BLOCKED,
                    reason="The selected glow part has no safe emissive resource/sidecar binding.",
                )
                if "emissive" in state.artifact_channels
                else state
                for state in control_states
            )
        resolved = resolved_material_authority_state(
            profile_token=getattr(profile, "name", ""),
            revision=result.request_id,
            affected_submeshes=merged_affected,
            dds_bindings=merged_bindings,
            residual_parameter_groups=residual_groups,
            control_states=control_states,
            status=MaterialAuthoritySyncStatus.FAST_PREVIEW,
            status_reason="Resolving exact preview…",
            unsafe_expert_active=expert_overrides_active,
            unsafe_export_acknowledged=unsafe_export_acknowledged,
        )
        if any(state.capability is MaterialAuthorityCapability.BLOCKED for state in control_states):
            sync_state_setter(
                MaterialAuthoritySyncStatus.BLOCKED,
                next(state.reason for state in control_states if state.capability is MaterialAuthorityCapability.BLOCKED),
                resolved,
            )
            return False
        setattr(dialog, "_material_authority_pending_resolved_state", resolved)
        sent = bool(
            sender(
                preview_model,
                bindings,
                affected_submeshes=affected,
                reason=result.reason,
                parameter_groups=residual_groups,
                material_authority_fingerprint=resolved.fingerprint,
                material_authority_revision=resolved.revision,
            )
        )
        if not sent:
            sync_state_setter(
                MaterialAuthoritySyncStatus.BLOCKED,
                "The active .NET preview did not accept the resolved material state.",
                resolved,
            )
            return False
        sync_state_setter(
            MaterialAuthoritySyncStatus.FAST_PREVIEW,
            "Resolving exact preview…",
            resolved,
        )
        return True

    def failed(message: str) -> None:
        sync_state_setter(MaterialAuthoritySyncStatus.BLOCKED, message, None)
        status_hint.setText(
            f"Resident material resource update failed; previous resources remain active: {message}"
        )

    return controller.start(
        texture_sets=texture_sets,
        material_profile=profile,
        affected_channels=channels,
        reason="material_authority_resource",
        on_complete=completed,
        on_error=failed,
    )


def create_material_authority_adjustment_callbacks(context: dict[str, object]) -> SimpleNamespace:
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
    _refresh_manual_profile_control_effects = context.get('_refresh_manual_profile_control_effects')
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
    complete_external_swap_checkbox = context.get('complete_external_swap_checkbox')
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
    manual_profile_expert_warning = context.get('manual_profile_expert_warning')
    material_authority_preview_texture_slots = context.get('material_authority_preview_texture_slots')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    original_texture_preview_state = context.get('original_texture_preview_state')
    part_glow_color_checkbox = context.get('part_glow_color_checkbox')
    part_glow_color_pick_button = context.get('part_glow_color_pick_button')
    part_glow_color_spins = tuple(context.get('part_glow_color_spins') or ())
    part_glow_strength_checkbox = context.get('part_glow_strength_checkbox')
    part_glow_strength_spin = context.get('part_glow_strength_spin')
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

    automatic_control_widgets = {
        "global_gloss_reduction": (global_gloss_reduction_slider, global_gloss_reduction_spin),
        "auto_brightness": (auto_brightness_slider, auto_brightness_spin),
        "source_brightness": (source_brightness_slider, source_brightness_spin),
        "tone_contrast": (tone_contrast_slider, tone_contrast_spin),
        "edge_relief": (edge_relief_slider, edge_relief_spin),
        "edge_relief_source": (edge_relief_source_combo,),
        "accent_glow": (accent_glow_slider, accent_glow_spin),
        "part_glow_color": (
            part_glow_color_checkbox,
            *part_glow_color_spins,
            part_glow_color_pick_button,
        ),
        "part_glow_strength": (part_glow_strength_checkbox, part_glow_strength_spin),
    }

    def _apply_material_authority_control_capabilities(
        state: MaterialAuthorityResolvedState,
    ) -> None:
        states = {control.key: control for control in state.control_states}
        setattr(dialog, "_material_authority_control_states_by_key", states)
        if callable(_refresh_part_glow_color_controls_enabled):
            _refresh_part_glow_color_controls_enabled()
        for key, widgets in automatic_control_widgets.items():
            control = states.get(key)
            if control is None:
                continue
            active = control.capability is MaterialAuthorityCapability.ACTIVE
            for widget in widgets:
                if widget is None:
                    continue
                try:
                    base_tooltip = widget.property("material_authority_base_tooltip")
                    if base_tooltip is None:
                        base_tooltip = str(widget.toolTip() or "")
                        widget.setProperty("material_authority_base_tooltip", base_tooltip)
                    tooltip = str(base_tooltip or "")
                    if control.reason:
                        tooltip = f"{tooltip}\n\n{control.reason}".strip()
                    widget.setToolTip(tooltip)
                    if key not in {"part_glow_color", "part_glow_strength"} or not active:
                        widget.setEnabled(active)
                except RuntimeError:
                    pass
        if callable(_refresh_manual_profile_control_effects):
            _refresh_manual_profile_control_effects()

    def _set_material_authority_sync_state(
        status: MaterialAuthoritySyncStatus,
        reason: str = "",
        state: MaterialAuthorityResolvedState | None = None,
    ) -> None:
        current = state
        if current is not None:
            current = replace(current, status=status, status_reason=str(reason or ""))
            setattr(dialog, "_material_authority_resolved_state", current)
            _apply_material_authority_control_capabilities(current)
        setattr(dialog, "_material_authority_sync_status", status.value)
        setattr(dialog, "_material_authority_sync_reason", str(reason or ""))
        text = material_authority_status_text(status, reason)
        if status is MaterialAuthoritySyncStatus.FAST_PREVIEW and str(reason or "").strip():
            text = f"{text}"
        try:
            true_source_basic_hint.setText(text)
        except RuntimeError:
            pass
        build_button = getattr(dialog, "_material_authority_build_button", None)
        if build_button is not None:
            base_allowed = bool(getattr(dialog, "_material_authority_base_build_allowed", True))
            build_ready = status is MaterialAuthoritySyncStatus.INACTIVE or bool(
                current is not None and current.build_allowed
            )
            try:
                build_button.setEnabled(base_allowed and build_ready)
                build_button.setToolTip("" if build_ready else text)
            except RuntimeError:
                pass

    def _material_resources_finished(
        generation: int,
        committed: bool,
        bindings: Sequence[Mapping[str, object]],
        fingerprint: str = "",
        material_revision: int = 0,
    ) -> None:
        material_resource_controller.finish(generation, committed, bindings)
        pending = getattr(dialog, "_material_authority_pending_resolved_state", None)
        if not isinstance(pending, MaterialAuthorityResolvedState):
            return
        if fingerprint and fingerprint != pending.fingerprint:
            return
        if material_revision and int(material_revision) != int(pending.revision):
            return
        if committed:
            pending = replace(pending, preview_acknowledged=True)
            setattr(dialog, "_material_authority_acknowledged_resolved_state", pending)
            if pending.unsafe_expert_active:
                status = (
                    MaterialAuthoritySyncStatus.FAST_PREVIEW
                    if pending.unsafe_export_acknowledged
                    else MaterialAuthoritySyncStatus.BLOCKED
                )
                reason = (
                    "Expert overrides active; unsafe export acknowledged, so no normal WYSIWYG badge is available."
                    if pending.unsafe_export_acknowledged
                    else "Expert overrides active; unsafe export acknowledgement is required."
                )
                _set_material_authority_sync_state(status, reason, pending)
            else:
                _set_material_authority_sync_state(
                    MaterialAuthoritySyncStatus.EXACT,
                    "",
                    pending,
                )
        else:
            _set_material_authority_sync_state(
                MaterialAuthoritySyncStatus.BLOCKED,
                "The .NET preview did not acknowledge the latest resolved artifacts.",
                pending,
            )

    setattr(dialog, "_mesh_editor_embedded_material_resources_finished", _material_resources_finished)
    dialog.finished.connect(material_resource_controller.request_shutdown)

    def _ensure_material_authority_route_active(reason: str = "material_authority_edit") -> bool:
        """Activate the established source-owned route only for a user mutation."""
        if bool(modify_original_clone_mode) or bool(_complete_external_swap_enabled()):
            return False
        setter = getattr(complete_external_swap_checkbox, "setChecked", None)
        if not callable(setter):
            return False
        complete_external_swap_checkbox.setProperty(
            "material_authority_activation_reason",
            str(reason or "material_authority_edit"),
        )
        setter(True)
        return bool(_complete_external_swap_enabled())

    def _set_global_gloss_reduction(value: int, *, refresh: bool = True) -> None:
        if refresh:
            _ensure_material_authority_route_active("automatic_global_gloss_reduction")
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
            _queue_material_authority_adjustment_preview_refresh(
                resource_keys=("global_gloss_reduction",)
            )

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
            _set_material_authority_sync_state(
                MaterialAuthoritySyncStatus.INACTIVE,
                inactive_reason,
                None,
            )
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
            profile_values_getter=lambda profile: (
                complete_swap_material_profile_to_dict(profile)
                if callable(complete_swap_material_profile_to_dict)
                else {}
            ),
            parameter_values_getter=lambda profile: (
                _material_authority_preview_native_override_values_helper(
                    profile,
                    enabled=True,
                    base_brightness=1.0,
                )
                if callable(_material_authority_preview_native_override_values_helper)
                else {}
            ),
            part_adjustments=source_part_adjustments,
            expert_overrides_active_getter=lambda: bool(
                manual_profile_expert_warning is not None
                and manual_profile_expert_warning.property('expert_overrides_active')
            ),
            unsafe_export_acknowledged_getter=lambda: bool(
                unsafe_material_preflight_checkbox is not None
                and unsafe_material_preflight_checkbox.isChecked()
            ),
            sync_state_setter=_set_material_authority_sync_state,
            status_hint=true_source_basic_hint,
            target_sidecar_bindings=context.get("sidecar_bindings"),
        )
        if not resource_queued and resident_material_resources_available(dialog):
            _set_material_authority_sync_state(
                MaterialAuthoritySyncStatus.BLOCKED,
                "No exact DDS resource update was queued for this change.",
                None,
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
        if refresh:
            _ensure_material_authority_route_active(f"automatic_{settings_key or 'material_control'}")
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
            resource_keys=("source_brightness",),
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
            resource_keys=("tone_contrast",),
        )

    def _set_auto_brightness(value: int, *, refresh: bool = True) -> None:
        _set_spin_slider_pair(
            auto_brightness_slider,
            auto_brightness_spin,
            value,
            "settings/complete_swap_auto_brightness",
            refresh=refresh,
            resource_keys=("auto_brightness",),
        )

    def _set_edge_relief_source(*, refresh: bool = True) -> None:
        if refresh:
            _ensure_material_authority_route_active("automatic_edge_relief_source")
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
        _ensure_material_authority_route_active("automatic_reset")
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
        _ensure_material_authority_route_active=_ensure_material_authority_route_active,
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

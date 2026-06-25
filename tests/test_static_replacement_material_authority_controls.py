from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_material_authority_controls import (
    MATERIAL_AUTHORITY_PREVIEW_SIGNATURE_VISIBLE_SLOTS,
    MATERIAL_AUTHORITY_VISIBLE_COMPLETE_SWAP_PROFILE_NAMES,
    material_authority_adjustment_refresh_reason,
    material_authority_adjustment_labels,
    material_authority_adjustment_setting_state,
    material_authority_adjustment_status_text,
    material_authority_adjustment_tooltips,
    material_authority_apply_sidecar_control_state,
    material_authority_basic_controls_hint,
    material_authority_basic_controls_profile_enabled,
    material_authority_clamped_int,
    material_authority_complete_swap_forced_child_states,
    material_authority_complete_swap_next_transition_generation,
    material_authority_complete_swap_profile_name,
    material_authority_complete_swap_restored_child_states,
    material_authority_complete_swap_routing_progress_message,
    material_authority_complete_swap_routing_reason,
    material_authority_complete_swap_should_apply_checked,
    material_authority_complete_swap_source_output_size_index,
    material_authority_complete_swap_tooltip,
    material_authority_complete_swap_update_performance,
    material_authority_complete_swap_update_queued_message,
    material_authority_controls_affect_visible_preview,
    material_authority_control_tooltips,
    material_authority_donor_control_text,
    material_authority_edge_relief_source,
    material_authority_edge_relief_source_setting,
    material_authority_global_gloss_tooltip,
    material_authority_global_gloss_reduction_hint,
    material_authority_path_signature,
    material_authority_profile_adjustment_kwargs,
    material_authority_preview_controls_signature,
    material_authority_preview_inactive_reason,
    material_authority_preview_signature,
    material_authority_preview_signature_initial_state,
    material_authority_preview_signature_hashes,
    material_authority_preview_slot_signature_row,
    material_authority_reset_values,
    material_authority_requested_profile_name,
    material_authority_route_summary_text,
    material_authority_sidecar_option_state,
    material_authority_sidecar_control_application_state,
    material_authority_sidecar_dependent_toggle_state,
    material_authority_sidecar_warning_html,
    material_authority_sidecar_warning_tooltip,
    material_authority_setup_labels,
    material_authority_setup_tooltips,
    material_authority_source_role_signature_rows,
    material_authority_stale_glow_settings_keys,
)


class WidgetProbe:
    def __init__(self, *, checked: bool = True) -> None:
        self.enabled: bool | None = None
        self.checked = checked

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def setChecked(self, checked: bool) -> None:
        self.checked = bool(checked)


def test_material_authority_basic_controls_profile_gate() -> None:
    assert material_authority_basic_controls_profile_enabled("material_authority_detail_mask")
    assert material_authority_basic_controls_profile_enabled("material_authority_manual")
    assert not material_authority_basic_controls_profile_enabled("material_authority_runtime_xml")
    assert MATERIAL_AUTHORITY_VISIBLE_COMPLETE_SWAP_PROFILE_NAMES == (
        "material_authority_detail_mask",
        "material_authority_placeholder_safe_test",
        "material_authority_manual",
    )


def test_material_authority_requested_profile_name_normalizes_tokens() -> None:
    assert material_authority_requested_profile_name(
        "material_authority_manual:{json}",
        resolve_profile_name=lambda name: f"resolved:{name}",
    ) == "material_authority_manual"
    assert material_authority_requested_profile_name(
        " material_authority_detail_mask ",
        resolve_profile_name=lambda name: f"resolved:{name}",
    ) == "resolved:material_authority_detail_mask"
    assert material_authority_requested_profile_name(
        "",
        resolve_profile_name=lambda name: name,
    ) == "material_authority_detail_mask"
    assert material_authority_requested_profile_name(
        "unknown",
        resolve_profile_name=lambda _name: "",
    ) == "unknown"


def test_material_authority_value_normalizers() -> None:
    assert material_authority_clamped_int("42.6", default=0, minimum=-100, maximum=100) == 43
    assert material_authority_clamped_int("-200", default=0, minimum=-100, maximum=100) == -100
    assert material_authority_clamped_int("bad", default=50, minimum=0, maximum=100) == 50
    assert material_authority_edge_relief_source("generate_source") == "generate_source"
    assert material_authority_edge_relief_source("bad") == "hybrid"
    assert material_authority_reset_values() == {
        "global_gloss_reduction": 0,
        "auto_brightness": 50,
        "source_brightness": 0,
        "tone_contrast": 0,
        "edge_relief": 0,
        "edge_relief_source": "hybrid",
        "accent_glow": 0,
    }


def test_material_authority_option_text_helpers() -> None:
    assert "proven working-mod route" in material_authority_complete_swap_tooltip()
    assert "_detailMaskTexture" in material_authority_complete_swap_tooltip()
    assert "recommended source texture route" in material_authority_route_summary_text()
    assert "Signed gloss/matte bias" in material_authority_global_gloss_tooltip()
    assert "Shader wrappers preserved" in material_authority_sidecar_warning_html()
    assert "Source-driven patching keeps shader parameters" in material_authority_sidecar_warning_tooltip()


def test_material_authority_donor_control_text_preserves_picker_copy() -> None:
    text = material_authority_donor_control_text()

    assert text["group_title"] == "Cross-Original Material Sources"
    assert "Use Another Original Mesh" in text["group_tooltip"]
    assert text["use_button"] == "Use Another Original Mesh..."
    assert text["clear_button"] == "Clear Selected Target"
    assert text["plan_headers"] == ["Target", "Material source", "Donor", "Shader", "Status"]
    assert text["dialog_title"] == "Use Another Original Mesh"
    assert text["picker_prompt"] == "Search donor original mesh by name, path, package, or role"
    assert text["progress_message"] == "Reading donor original mesh..."
    assert text["part_headers"] == ["Donor part", "Shader", "Textures", "Emissive/glow"]
    assert text["texture_headers"] == ["Role", "Parameter", "DDS", "Shader", "State"]
    assert text["parts_label"] == "Donor parts / material wrappers"
    assert text["textures_label"] == "Donor sidecar texture bindings"
    assert text["mode_label"] == "Material source"
    assert text["apply_button"] == "Use Selected Donor Material"
    assert "Authoritative donor recipe is selected by default" in text["default_status"]
    assert text["assigned_status"] == "Assigned {donor_part_name} to {target_name}."


def test_material_authority_global_gloss_reduction_hint_branches() -> None:
    assert material_authority_global_gloss_reduction_hint(
        complete_enabled=False,
        profile_name="material_authority_detail_mask",
        value=0,
    ) == "Enable Complete source-owned mesh/material swap to use gloss/matte bias."
    assert "Legacy Runtime XML preserves stock material layers" in material_authority_global_gloss_reduction_hint(
        complete_enabled=True,
        profile_name="material_authority_runtime_xml",
        value=0,
    )
    assert "gloss boost lowers generated detail-mask roughness" in material_authority_global_gloss_reduction_hint(
        complete_enabled=True,
        profile_name="material_authority_detail_mask",
        value=-20,
    )
    assert "matte bias raises generated detail-mask roughness" in material_authority_global_gloss_reduction_hint(
        complete_enabled=True,
        profile_name="material_authority_detail_mask",
        value=20,
    )
    assert "strong gloss cut" in material_authority_global_gloss_reduction_hint(
        complete_enabled=True,
        profile_name="material_authority_pbr_source_test",
        value=95,
    )
    assert material_authority_global_gloss_reduction_hint(
        complete_enabled=True,
        profile_name="material_authority_detail_mask",
        value=0,
    ) == "0% keeps the proven Material Authority response."
    assert "Strong matte override" in material_authority_global_gloss_reduction_hint(
        complete_enabled=True,
        profile_name="material_authority_clean_source",
        value=90,
    )


def test_material_authority_preview_inactive_reason_priority() -> None:
    assert material_authority_preview_inactive_reason(
        complete_enabled=False,
        basic_profile_enabled=True,
        has_texture_sets=True,
        original_material_preview_active=True,
    ) == "Complete source-owned swap is off."
    assert material_authority_preview_inactive_reason(
        complete_enabled=True,
        basic_profile_enabled=False,
        has_texture_sets=True,
        original_material_preview_active=True,
    ) == "Selected material profile does not use Material Authority adjustments."
    assert material_authority_preview_inactive_reason(
        complete_enabled=True,
        basic_profile_enabled=True,
        has_texture_sets=False,
        original_material_preview_active=True,
    ) == "No source texture set is loaded."
    assert material_authority_preview_inactive_reason(
        complete_enabled=True,
        basic_profile_enabled=True,
        has_texture_sets=True,
        original_material_preview_active=True,
    ) == "Original-material preview is active."
    assert material_authority_preview_inactive_reason(
        complete_enabled=True,
        basic_profile_enabled=True,
        has_texture_sets=True,
        original_material_preview_active=False,
    ) == ""


def test_material_authority_control_status_text() -> None:
    assert material_authority_adjustment_status_text(
        basic_profile_enabled=True,
        inactive_reason="No source texture set is loaded.",
    ) == "Adjustments updated. Preview unchanged: No source texture set is loaded."
    assert material_authority_adjustment_status_text(
        basic_profile_enabled=False,
        inactive_reason="Selected material profile does not use Material Authority adjustments.",
    ) == ""
    assert material_authority_adjustment_status_text(
        basic_profile_enabled=True,
        inactive_reason="",
    ) == "Adjustments updated. Preview refresh queued."
    assert material_authority_adjustment_refresh_reason() == "material authority adjustment"
    assert material_authority_controls_affect_visible_preview("") is True
    assert material_authority_controls_affect_visible_preview("No source texture set is loaded.") is False


def test_material_authority_adjustment_setting_state_normalizes_values() -> None:
    assert material_authority_adjustment_setting_state(
        "42.6",
        default=0,
        minimum=-100,
        maximum=100,
        settings_key="settings/value",
    ) == {"value": 43, "settings_key": "settings/value"}
    assert material_authority_adjustment_setting_state(
        "bad",
        default=50,
        minimum=0,
        maximum=100,
    ) == {"value": 50, "settings_key": ""}
    assert material_authority_edge_relief_source_setting("generate_source") == {
        "value": "generate_source",
        "settings_key": "settings/complete_swap_edge_relief_source",
    }
    assert material_authority_edge_relief_source_setting("bad")["value"] == "hybrid"


def test_material_authority_complete_swap_status_text_helpers() -> None:
    assert material_authority_complete_swap_routing_progress_message() == (
        "Applying complete source-owned swap routing."
    )
    assert material_authority_complete_swap_routing_reason() == "complete source-owned swap routing"
    assert material_authority_complete_swap_update_queued_message() == (
        "Complete source-owned swap update queued."
    )

    performance = material_authority_complete_swap_update_performance()
    assert performance.summary == "Complete source-owned swap update queued."
    assert performance.details == (
        "Child material options are updated without firing their individual preview refreshes; "
        "one routing/material preview rebuild is queued after the UI repaints."
    )


def test_material_authority_complete_swap_transition_state_helpers() -> None:
    assert material_authority_complete_swap_next_transition_generation(0) == 1
    assert material_authority_complete_swap_next_transition_generation("4") == 5
    assert material_authority_complete_swap_next_transition_generation("bad") == 1

    assert material_authority_complete_swap_should_apply_checked(
        current_generation="3",
        expected_generation=3,
        checked=True,
    )
    assert not material_authority_complete_swap_should_apply_checked(
        current_generation=4,
        expected_generation=3,
        checked=True,
    )
    assert not material_authority_complete_swap_should_apply_checked(
        current_generation=3,
        expected_generation=3,
        checked=False,
    )


def test_material_authority_complete_swap_child_state_helpers() -> None:
    states = material_authority_complete_swap_forced_child_states(
        rebuild_sidecar=1,
        inject_base_color="yes",
        source_color_faithful=True,
        external_material_reset=0,
        prune_unmapped_original_dds=None,
    )

    assert states == (True, True, True, False, False)
    assert material_authority_complete_swap_restored_child_states(states) == {
        "rebuild_sidecar": True,
        "inject_base_color": True,
        "source_color_faithful": True,
        "external_material_reset": False,
        "prune_unmapped_original_dds": False,
    }
    assert material_authority_complete_swap_restored_child_states((True,)) is None
    assert material_authority_complete_swap_restored_child_states(["bad"] * 5) is None


def test_material_authority_complete_swap_control_selection_helpers() -> None:
    assert material_authority_complete_swap_source_output_size_index(5) == 5
    assert material_authority_complete_swap_source_output_size_index(-1) == 0
    assert material_authority_complete_swap_source_output_size_index("bad") == 0
    assert material_authority_complete_swap_profile_name(" material_authority_manual ") == (
        "material_authority_manual"
    )
    assert material_authority_complete_swap_profile_name("") == "material_authority_detail_mask"
    assert material_authority_complete_swap_profile_name("", fallback="fallback") == "fallback"


def test_material_authority_preview_signature_initial_state_preserves_defaults() -> None:
    assert material_authority_preview_signature_initial_state() == {"visible": "", "cache": ""}


def test_material_authority_control_tooltips_preserve_control_guidance() -> None:
    tooltips = material_authority_control_tooltips()

    assert tooltips["custom_glow_checkbox"] == (
        "Optional color override for source parts explicitly marked Role: Glow / emissive. "
        "Accent glow at 0% disables emissive output."
    )
    assert tooltips["custom_glow_channel"] == (
        "Custom glow/emissive color channel for source parts marked Role: Glow / emissive."
    )
    assert tooltips["custom_glow_pick"] == "Choose a custom glow/emissive color for glow-role source parts."
    assert tooltips["reset_adjustments"] == (
        "Reset Material Authority adjustment sliders to the recommended live-preview defaults."
    )
    assert "Expert loose-export override" in tooltips["unsafe_preflight"]
    assert "This is ignored for direct archive patch" in tooltips["unsafe_preflight"]


def test_material_authority_setup_tooltips_preserve_sidecar_guidance() -> None:
    tooltips = material_authority_setup_tooltips()

    assert "patched .pac_xml/.pami" in tooltips["rebuild_sidecar"]
    assert "delete original DDS parameters" in tooltips["prune_unmapped_original_dds"]
    assert "base-color texture" in tooltips["inject_base_color"]
    assert "old grime/detail/color-blend/tint layers" in tooltips["source_color_faithful"]
    assert "stubborn target shaders" in tooltips["external_material_reset"]
    assert "source sidecar binding" in tooltips["complete_external_swap"]


def test_material_authority_setup_labels_preserve_option_text() -> None:
    labels = material_authority_setup_labels()

    assert labels == {
        "rebuild_sidecar": "Bind source textures in target sidecar",
        "prune_unmapped_original_dds": "Remove unused original texture refs",
        "inject_base_color": "Create missing base-color slot",
        "source_color_faithful": "Neutralize original tint/detail layers",
        "external_material_reset": "Advanced: reset inherited material response",
        "complete_external_swap": "Complete source-owned mesh/material swap",
        "runtime_material_profile": "Runtime material profile",
        "unsafe_preflight": "Allow unsafe material preflight export",
        "texture_size": "Texture size",
        "texture_orientation": "Texture orientation",
    }


def test_material_authority_adjustment_tooltips_preserve_export_guidance() -> None:
    tooltips = material_authority_adjustment_tooltips()

    assert "Signed source base-color brightness" in tooltips["source_brightness"]
    assert "Manual tone curve" in tooltips["tone_contrast"]
    assert "stable in-game midrange" in tooltips["auto_brightness"]
    assert "does not edit mesh geometry" in tooltips["edge_relief"]
    assert "Generate from source builds simple support" in tooltips["edge_relief_source"]
    assert "gem, crystal, rune" in tooltips["accent_glow"]


def test_material_authority_adjustment_labels_preserve_control_text() -> None:
    labels = material_authority_adjustment_labels()

    assert labels["group_title"] == "Material Authority Adjustments"
    assert labels["global_gloss_bias"] == "Gloss / matte bias"
    assert labels["global_gloss_hint"] == "0% keeps the proven Material Authority response."
    assert labels["auto_brightness"] == "Auto brightness"
    assert labels["source_brightness"] == "Source brightness"
    assert labels["tone_contrast"] == "Tone contrast"
    assert labels["edge_relief"] == "Edge relief"
    assert labels["edge_relief_source"] == "Edge relief source"
    assert labels["accent_glow"] == "Accent glow"
    assert labels["glow_color"] == "Glow color"
    assert labels["custom_glow_color"] == "Custom glow color"
    assert labels["custom_glow_pick"] == "Pick"
    assert labels["reset_adjustments"] == "Reset Adjustments"
    assert "generated source-owned DDS/XML" in labels["hint"]


def test_material_authority_stale_glow_settings_keys_are_owned_by_helper() -> None:
    assert material_authority_stale_glow_settings_keys() == (
        "settings/complete_swap_accent_glow_strength",
        "settings/complete_swap_accent_glow_color_enabled",
        "settings/complete_swap_accent_glow_color_rgb",
    )


def test_material_authority_basic_controls_hint() -> None:
    assert material_authority_basic_controls_hint(
        visible=False,
        enabled=False,
        inactive_reason="",
    ) == "Select Material Authority or Manual to use material controls."
    assert material_authority_basic_controls_hint(
        visible=True,
        enabled=False,
        inactive_reason="",
    ) == "Select Material Authority or Manual to use material controls."
    assert material_authority_basic_controls_hint(
        visible=True,
        enabled=True,
        inactive_reason="Original-material preview is active.",
    ) == "Settings apply on export. Preview unchanged: Original-material preview is active."
    assert "Auto brightness normalizes source base DDS exposure" in material_authority_basic_controls_hint(
        visible=True,
        enabled=True,
        inactive_reason="",
    )


def test_material_authority_preview_signature_helpers(tmp_path) -> None:
    texture_path = tmp_path / "blade_base.dds"
    texture_path.write_bytes(b"dds")

    path_text, size, mtime = material_authority_path_signature(texture_path)

    assert path_text == str(texture_path)
    assert size == 3
    assert mtime > 0
    assert material_authority_path_signature("") == ("", 0, 0)
    assert material_authority_path_signature("missing.dds") == ("missing.dds", 0, 0)

    signature = material_authority_preview_signature_hashes(
        visible_payload=("profile", ("slot", material_authority_path_signature(texture_path))),
        controls=(0, 50, "hybrid"),
    )

    assert set(signature) == {"visible", "cache"}
    assert signature == material_authority_preview_signature_hashes(
        visible_payload=("profile", ("slot", material_authority_path_signature(texture_path))),
        controls=(0, 50, "hybrid"),
    )
    assert signature["visible"] != material_authority_preview_signature_hashes(
        visible_payload=("other",),
        controls=(0, 50, "hybrid"),
    )["visible"]


def test_material_authority_preview_signature_row_helpers(tmp_path) -> None:
    texture_path = tmp_path / "blade_base.dds"
    texture_path.write_bytes(b"dds")
    slot = SimpleNamespace(
        source_path=texture_path,
        slot_kind="base",
        material_name="blade",
        source_authority="source",
        base_color_factor=(1.0, 0.5, 0.25, 1.0),
        base_color_scale=0.9,
        base_color_lift=12,
        base_color_gamma=0.8,
        base_color_saturation=0.7,
        base_color_value_max=220,
    )

    assert "detail_mask" in MATERIAL_AUTHORITY_PREVIEW_SIGNATURE_VISIBLE_SLOTS
    row = material_authority_preview_slot_signature_row(
        material_key="Blade",
        slot_name="base",
        source_slot=slot,
    )
    assert row[:11] == (
        "Blade",
        "base",
        "base",
        "blade",
        "source",
        (1.0, 0.5, 0.25, 1.0),
        0.9,
        12,
        0.8,
        0.7,
        220,
    )
    assert row[11][0] == str(texture_path)

    source_role_rows = material_authority_source_role_signature_rows(
        {
            2: SimpleNamespace(material_role="emissive", emissive_color_rgb=(1, 2, 3)),
            3: SimpleNamespace(material_role="", emissive_color_rgb=()),
        }
    )
    assert source_role_rows == ((2, "emissive", (1, 2, 3)),)
    assert material_authority_preview_controls_signature(
        global_gloss_reduction=-5,
        auto_brightness=50,
        source_brightness=2,
        tone_contrast=3,
        edge_relief=4,
        edge_relief_source="hybrid",
        accent_glow=6,
        glow_color_enabled=True,
        glow_rgb=(7, 8, 9),
        source_role_rows=source_role_rows,
    ) == (-5, 50, 2, 3, 4, "hybrid", 6, True, (7, 8, 9), source_role_rows)


def test_material_authority_preview_signature_composes_visible_rows_and_controls(tmp_path) -> None:
    texture_path = tmp_path / "blade_base.dds"
    texture_path.write_bytes(b"dds")
    slot = SimpleNamespace(
        source_path=texture_path,
        slot_kind="base",
        material_name="blade",
        source_authority="source",
        base_color_factor=(1.0, 0.5, 0.25, 1.0),
        base_color_scale=0.9,
        base_color_lift=12,
        base_color_gamma=0.8,
        base_color_saturation=0.7,
        base_color_value_max=220,
    )
    profile = SimpleNamespace(name="material_authority_manual")

    def texture_slots_resolver(_texture_set, _profile=None, *, enabled=False):
        assert enabled
        return {"base": slot}

    def profile_payload_builder(_profile):
        raise RuntimeError("use fallback")

    signature = material_authority_preview_signature(
        texture_sets={"Blade": object()},
        profile=profile,
        source_part_adjustments={
            2: SimpleNamespace(material_role="emissive", emissive_color_rgb=(1, 2, 3)),
        },
        global_gloss_reduction=-5,
        auto_brightness=50,
        source_brightness=2,
        tone_contrast=3,
        edge_relief=4,
        edge_relief_source="hybrid",
        accent_glow=6,
        glow_color_enabled=True,
        glow_rgb=(7, 8, 9),
        texture_slots_resolver=texture_slots_resolver,
        profile_payload_builder=profile_payload_builder,
        fallback_profile_payload_builder=lambda item: {"name": getattr(item, "name", "")},
    )

    visible_payload = (
        "material_authority_manual",
        {"name": "material_authority_manual"},
        (
            material_authority_preview_slot_signature_row(
                material_key="Blade",
                slot_name="base",
                source_slot=slot,
            ),
        ),
    )
    controls = material_authority_preview_controls_signature(
        global_gloss_reduction=-5,
        auto_brightness=50,
        source_brightness=2,
        tone_contrast=3,
        edge_relief=4,
        edge_relief_source="hybrid",
        accent_glow=6,
        glow_color_enabled=True,
        glow_rgb=(7, 8, 9),
        source_role_rows=((2, "emissive", (1, 2, 3)),),
    )
    assert signature == material_authority_preview_signature_hashes(
        visible_payload=visible_payload,
        controls=controls,
    )


def test_material_authority_profile_adjustment_kwargs() -> None:
    assert material_authority_profile_adjustment_kwargs(
        global_gloss_reduction=-5,
        edge_relief=4,
        edge_relief_source="generate_source",
        accent_glow=6,
        auto_brightness=50,
        source_brightness=2,
        tone_contrast=3,
    ) == {
        "gloss_reduction": -5.0,
        "edge_relief_strength": 4.0,
        "edge_relief_source": "generate_source",
        "accent_glow_strength": 6.0,
        "auto_brightness_balance": 50.0,
        "dark_detail_lift": 2.0,
        "tone_contrast": 3.0,
    }
    assert material_authority_profile_adjustment_kwargs(
        global_gloss_reduction=0,
        edge_relief=0,
        edge_relief_source="bad",
        accent_glow=0,
        auto_brightness=50,
        source_brightness=0,
        tone_contrast=0,
    )["edge_relief_source"] == "hybrid"


def test_material_authority_sidecar_option_state_forces_complete_mode_sidecar() -> None:
    assert material_authority_sidecar_option_state(
        sidecar_enabled=False,
        complete_mode=True,
        unsafe_preflight_checked=False,
    ) == {
        "force_rebuild_sidecar": True,
        "clear_dependent_sidecar_options": False,
        "rebuild_sidecar_enabled": False,
        "dependent_sidecar_options_enabled": False,
        "complete_material_controls_enabled": True,
        "unsafe_preflight_enabled": True,
        "clear_unsafe_preflight": False,
    }


def test_material_authority_sidecar_option_state_regular_modes() -> None:
    assert material_authority_sidecar_option_state(
        sidecar_enabled=False,
        complete_mode=False,
        unsafe_preflight_checked=True,
    ) == {
        "force_rebuild_sidecar": False,
        "clear_dependent_sidecar_options": True,
        "rebuild_sidecar_enabled": True,
        "dependent_sidecar_options_enabled": False,
        "complete_material_controls_enabled": True,
        "unsafe_preflight_enabled": False,
        "clear_unsafe_preflight": True,
    }
    assert material_authority_sidecar_option_state(
        sidecar_enabled=True,
        complete_mode=False,
        unsafe_preflight_checked=False,
    )["dependent_sidecar_options_enabled"] is True
    assert material_authority_sidecar_option_state(
        sidecar_enabled=True,
        complete_mode=True,
        unsafe_preflight_checked=True,
    ) == {
        "force_rebuild_sidecar": False,
        "clear_dependent_sidecar_options": False,
        "rebuild_sidecar_enabled": False,
        "dependent_sidecar_options_enabled": False,
        "complete_material_controls_enabled": True,
        "unsafe_preflight_enabled": True,
        "clear_unsafe_preflight": False,
    }


def test_material_authority_sidecar_dependent_toggle_state() -> None:
    assert material_authority_sidecar_dependent_toggle_state(
        checked=True,
        rebuild_sidecar_checked=False,
    ) == {
        "force_rebuild_sidecar": True,
        "refresh_output": False,
        "refresh_preview": False,
    }
    assert material_authority_sidecar_dependent_toggle_state(
        checked=True,
        rebuild_sidecar_checked=True,
        refresh_output=True,
    ) == {
        "force_rebuild_sidecar": False,
        "refresh_output": True,
        "refresh_preview": True,
    }
    assert material_authority_sidecar_dependent_toggle_state(
        checked=False,
        rebuild_sidecar_checked=False,
        refresh_output=True,
    ) == {
        "force_rebuild_sidecar": False,
        "refresh_output": True,
        "refresh_preview": True,
    }


def test_material_authority_sidecar_control_application_state_groups_controls() -> None:
    state = material_authority_sidecar_control_application_state(
        {
            "force_rebuild_sidecar": False,
            "clear_dependent_sidecar_options": True,
            "rebuild_sidecar_enabled": True,
            "dependent_sidecar_options_enabled": False,
            "complete_material_controls_enabled": True,
            "unsafe_preflight_enabled": True,
            "clear_unsafe_preflight": False,
        }
    )

    assert state["clear_dependent_sidecar_options"] is True
    assert state["rebuild_sidecar_enabled"] is True
    assert state["dependent_sidecar_options_enabled"] is False
    assert state["complete_material_controls_enabled"] is True
    assert state["unsafe_preflight_enabled"] is True
    assert state["dependent_control_keys"] == (
        "prune_unmapped_original_dds",
        "inject_base_color",
        "source_color_faithful",
        "external_material_reset",
    )
    assert state["complete_control_keys"] == (
        "complete_swap_material_profile",
        "global_gloss_reduction",
        "auto_brightness",
        "source_brightness",
        "tone_contrast",
        "accent_glow",
        "reset_adjustments",
    )


def test_material_authority_apply_sidecar_control_state_updates_widgets() -> None:
    rebuild = WidgetProbe(checked=False)
    dependent = [WidgetProbe(), WidgetProbe()]
    complete = [WidgetProbe()]
    unsafe = WidgetProbe(checked=True)

    state = material_authority_apply_sidecar_control_state(
        material_authority_sidecar_option_state(
            sidecar_enabled=False,
            complete_mode=False,
            unsafe_preflight_checked=True,
        ),
        rebuild_sidecar_widget=rebuild,
        dependent_widgets=dependent,
        complete_widgets=complete,
        unsafe_preflight_widget=unsafe,
    )

    assert state["clear_dependent_sidecar_options"] is True
    assert rebuild.enabled is True
    assert [widget.checked for widget in dependent] == [False, False]
    assert [widget.enabled for widget in dependent] == [False, False]
    assert complete[0].enabled is True
    assert unsafe.enabled is False
    assert unsafe.checked is False

    enabled_complete = [WidgetProbe(), WidgetProbe()]
    material_authority_apply_sidecar_control_state(
        material_authority_sidecar_option_state(
            sidecar_enabled=True,
            complete_mode=True,
            unsafe_preflight_checked=False,
        ),
        rebuild_sidecar_widget=WidgetProbe(),
        dependent_widgets=[],
        complete_widgets=enabled_complete,
        unsafe_preflight_widget=WidgetProbe(),
    )
    assert [widget.enabled for widget in enabled_complete] == [True, True]

    forced_rebuild = WidgetProbe(checked=False)
    forced_state = material_authority_apply_sidecar_control_state(
        material_authority_sidecar_option_state(
            sidecar_enabled=False,
            complete_mode=True,
            unsafe_preflight_checked=False,
        ),
        rebuild_sidecar_widget=forced_rebuild,
        dependent_widgets=[],
        complete_widgets=[],
        unsafe_preflight_widget=WidgetProbe(),
    )
    assert forced_state["force_rebuild_sidecar"] is True
    assert forced_rebuild.checked is True

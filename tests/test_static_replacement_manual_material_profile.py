from __future__ import annotations

import json
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_manual_material_profile import (
    MODIFY_ORIGINAL_MANUAL_TEXTURE_TUNING_KEYS,
    coerce_manual_material_profile_values,
    delete_manual_material_profile_preset,
    load_manual_material_profile_presets,
    load_manual_material_profile_values,
    manual_material_profile_change_status_text,
    manual_material_profile_control_text,
    manual_material_profile_control_effect_states,
    manual_material_profile_default_values,
    manual_material_profile_delete_question,
    manual_material_profile_dirty_state,
    manual_material_profile_fallback_payload,
    manual_material_profile_inactive_reasons,
    manual_material_profile_initial_status_html,
    manual_material_profile_panel_state,
    manual_profile_dirty_initial_state,
    manual_profile_ready_initial_state,
    modify_original_advanced_texture_tuning_settings_key,
    modify_original_manual_texture_tuning_presets_key,
    modify_original_manual_texture_tuning_settings_key,
    modify_original_manual_texture_tuning_values,
    manual_material_profile_preset_from_fields,
    manual_material_profile_preset_metadata,
    manual_material_profile_preset_names,
    manual_material_profile_presets_payload,
    manual_material_profile_preview_warning_html,
    manual_material_profile_saved_message,
    manual_material_profile_token,
    manual_material_profile_tooltips,
    manual_material_profile_texture_impact_html,
    selected_manual_material_profile_preset,
    stored_manual_material_profile_values,
    upsert_manual_material_profile_preset,
)


def test_manual_profile_initial_states_preserve_defaults() -> None:
    assert manual_profile_ready_initial_state() == {"ready": False}
    assert manual_profile_dirty_initial_state() == {"dirty": False}
    assert manual_material_profile_fallback_payload(SimpleNamespace(name="Manual")) == {"name": "Manual"}


def test_manual_material_profile_default_values_follow_profile_attributes() -> None:
    defaults = manual_material_profile_default_values(
        SimpleNamespace(
            base_binding_mode="disabled",
            base_color_lift=12,
            emissive_color_scale=None,
            neutral_color_rgb=(1, 2, 3),
            roughness_inverted=True,
        )
    )

    assert defaults["base_binding_mode"] == "disabled"
    assert defaults["base_color_lift"] == 12
    assert defaults["emissive_color_scale"] == 1.0
    assert defaults["neutral_color_rgb"] == (1, 2, 3)
    assert defaults["roughness_inverted"] is True
    assert defaults["authority_contract"] == "true_source_authority_detail_mask"


def test_stored_and_loaded_manual_profile_values_merge_known_keys_only() -> None:
    defaults = {"base_binding_mode": "overlay_texture", "roughness_default": 240}
    stored = stored_manual_material_profile_values(
        "material_authority_manual",
        SimpleNamespace(base_binding_mode="disabled", unknown="skip"),
        defaults,
    )

    assert stored == {"base_binding_mode": "disabled"}
    assert stored_manual_material_profile_values("material_authority_detail_mask", object(), defaults) == {}
    assert load_manual_material_profile_values(
        defaults=defaults,
        stored_values=stored,
        raw_settings=json.dumps({"roughness_default": 128, "unknown": True}),
    ) == {"base_binding_mode": "disabled", "roughness_default": 128}
    assert load_manual_material_profile_values(
        defaults=defaults,
        stored_values=stored,
        raw_settings="{not-json",
    ) == {"base_binding_mode": "disabled", "roughness_default": 240}


def test_modify_original_manual_texture_tuning_values_keep_route_defaults() -> None:
    defaults = {
        "base_binding_mode": "overlay_texture",
        "mask_binding_mode": "detail_mask_material",
        "support_policy": "source_only",
        "emissive_mode": "intensity",
        "authority_contract": "true_source_authority_detail_mask",
        "source_color_layer_authority": False,
        "base_color_gamma": 1.0,
        "roughness_default": 240,
    }

    values = modify_original_manual_texture_tuning_values(
        {
            "base_binding_mode": "disabled",
            "mask_binding_mode": "disabled",
            "support_policy": "keep_original_support",
            "authority_contract": "runtime_xml_preserve",
            "source_color_layer_authority": True,
            "base_color_gamma": 0.72,
            "roughness_default": 180,
            "unknown": "skip",
        },
        defaults=defaults,
    )

    assert values == {
        "base_binding_mode": "overlay_texture",
        "mask_binding_mode": "detail_mask_material",
        "support_policy": "source_only",
        "emissive_mode": "intensity",
        "authority_contract": "true_source_authority_detail_mask",
        "source_color_layer_authority": False,
        "base_color_gamma": 0.72,
        "roughness_default": 180,
    }
    assert "base_binding_mode" not in MODIFY_ORIGINAL_MANUAL_TEXTURE_TUNING_KEYS
    assert "source_color_layer_authority" not in MODIFY_ORIGINAL_MANUAL_TEXTURE_TUNING_KEYS


def test_modify_original_manual_texture_tuning_uses_separate_settings_keys() -> None:
    assert modify_original_advanced_texture_tuning_settings_key() == "settings/modify_original_advanced_texture_tuning"
    assert modify_original_manual_texture_tuning_settings_key() == "settings/modify_original_manual_texture_tuning"
    assert modify_original_manual_texture_tuning_presets_key() == "settings/modify_original_manual_texture_tuning_presets"


def test_manual_profile_preset_helpers_parse_and_serialize_valid_presets() -> None:
    defaults = {"base_binding_mode": "overlay_texture", "roughness_default": 240}
    raw = json.dumps(
        [
            {
                "name": "  Clean ",
                "details": "  lower grime ",
                "recommended_models": " sword ",
                "values": {"base_binding_mode": "disabled", "unknown": True},
            },
            {"details": "missing name"},
            "bad",
        ]
    )

    presets = load_manual_material_profile_presets(raw, defaults=defaults)

    assert presets == [
        {
            "name": "Clean",
            "details": "lower grime",
            "recommended_models": "sword",
            "values": {"base_binding_mode": "disabled", "roughness_default": 240},
        }
    ]
    assert coerce_manual_material_profile_values({"roughness_default": 64}, defaults) == {
        "base_binding_mode": "overlay_texture",
        "roughness_default": 64,
    }
    assert manual_material_profile_presets_payload(presets + [{"name": ""}], defaults=defaults) == [
        {
            "schema": "cdmw_manual_material_profile_v1",
            "name": "Clean",
            "details": "lower grime",
            "recommended_models": "sword",
            "values": {"base_binding_mode": "disabled", "roughness_default": 240},
        }
    ]


def test_manual_material_profile_inactive_reasons_follow_modes() -> None:
    reasons = manual_material_profile_inactive_reasons(
        {
            "base_binding_mode": "disabled",
            "mask_binding_mode": "scratch_scalars",
            "support_policy": "keep_original_support",
            "emissive_mode": "disabled",
            "authority_contract": "runtime_xml_preserve",
            "allow_factor_only_authority": False,
        }
    )

    assert reasons["base_color_lift"] == "No effect: Color slot is disabled."
    assert reasons["emissive_color_scale"] == "No effect: Emissive routing is disabled."
    assert reasons["roughness_default"] == "No effect: PBR/mask slot is not generating a material-mask DDS."
    assert reasons["displacement_scale_multiplier"] == "No effect: Support maps are preserving original target height/detail."
    assert reasons["force_neutral_layer_support"] == "No effect: Runtime XML preserve keeps target/corpus support unless support maps are changed."


def test_manual_material_profile_control_effect_states_attach_inactive_reasons() -> None:
    states = manual_material_profile_control_effect_states(
        {
            "base_binding_mode": "disabled",
            "mask_binding_mode": "disabled",
            "allow_factor_only_authority": False,
        },
        control_keys=("base_color_lift", "factor_only_material_mask", "roughness_default", "unchanged"),
        control_tooltips={
            "base_color_lift": "Base lift",
            "factor_only_material_mask": "Factor mask",
            "roughness_default": "Roughness default",
            "unchanged": "Unchanged",
        },
    )

    assert states["base_color_lift"] == {
        "enabled": False,
        "tooltip": "Base lift\n\nNo effect: Color slot is disabled.",
    }
    assert states["factor_only_material_mask"] == {
        "enabled": False,
        "tooltip": "Factor mask\n\nNo effect: Use factor-only colors is off.",
    }
    assert states["roughness_default"] == {
        "enabled": False,
        "tooltip": "Roughness default\n\nNo effect: PBR/mask slot is not generating a material-mask DDS.",
    }
    assert states["unchanged"] == {"enabled": True, "tooltip": "Unchanged"}


def test_manual_material_profile_panel_dirty_and_token_state() -> None:
    assert manual_material_profile_dirty_state(True) == {
        "dirty": True,
        "apply_enabled": True,
        "status_text": "Manual settings changed. Preview refresh queued; press Apply Manual Settings to force it now.",
    }
    assert manual_material_profile_dirty_state(False) == {
        "dirty": False,
        "apply_enabled": False,
        "status_text": "Manual settings applied. Further slider changes queue live preview refresh.",
    }
    assert manual_material_profile_panel_state(
        "material_authority_manual",
        complete_enabled=True,
    ) == {"visible": True, "enabled": True}
    assert manual_material_profile_panel_state(
        "material_authority_manual",
        complete_enabled=False,
    ) == {"visible": True, "enabled": True}
    assert manual_material_profile_panel_state(
        "material_authority_detail_mask",
        complete_enabled=True,
    ) == {"visible": False, "enabled": False}
    assert manual_material_profile_token(
        "material_authority_manual",
        manual_token="material_authority_manual:{json}",
    ) == "material_authority_manual:{json}"
    assert manual_material_profile_token(
        "",
        manual_token="manual",
    ) == "material_authority_detail_mask"
    assert manual_material_profile_token(
        "material_authority_detail_mask",
        manual_token="manual",
    ) == "material_authority_detail_mask"


def test_manual_material_profile_preset_selection_upsert_and_delete() -> None:
    presets = [
        {"name": "Clean", "details": "old"},
        {"name": "Bright", "details": "old"},
    ]

    assert selected_manual_material_profile_preset(presets, " clean ") == {"name": "Clean", "details": "old"}
    assert selected_manual_material_profile_preset(presets, "") is None
    assert upsert_manual_material_profile_preset(
        presets,
        {"name": "clean", "details": "new"},
    ) == [
        {"name": "Bright", "details": "old"},
        {"name": "clean", "details": "new"},
    ]
    assert upsert_manual_material_profile_preset(
        presets,
        {"name": "Dark", "details": "new"},
    ) == [
        {"name": "Bright", "details": "old"},
        {"name": "Clean", "details": "old"},
        {"name": "Dark", "details": "new"},
    ]
    assert delete_manual_material_profile_preset(presets, "BRIGHT") == [{"name": "Clean", "details": "old"}]


def test_manual_material_profile_preset_display_helpers_normalize_ui_data() -> None:
    presets = [
        {"name": " Clean ", "details": " lower grime ", "recommended_models": " sword "},
        {"name": ""},
        {"details": "missing name"},
    ]

    assert manual_material_profile_preset_names(presets) == ["Clean"]
    assert manual_material_profile_preset_metadata(presets[0]) == {
        "name": " Clean ",
        "details": " lower grime ",
        "recommended_models": " sword ",
    }
    assert manual_material_profile_preset_from_fields(
        name=" Clean ",
        details=" lower grime ",
        recommended_models=" sword ",
        values={"roughness_default": 220},
    ) == {
        "name": "Clean",
        "details": "lower grime",
        "recommended_models": "sword",
        "values": {"roughness_default": 220},
    }


def test_manual_material_profile_text_helpers_preserve_user_facing_guidance() -> None:
    texture_html = manual_material_profile_texture_impact_html()
    warning_html = manual_material_profile_preview_warning_html()
    tooltips = manual_material_profile_tooltips()

    assert "<table cellspacing='0' cellpadding='3'" in texture_html
    assert "PBR mask" in texture_html
    assert "material mask DDS" in texture_html
    assert "<b>Conditional:</b>" in texture_html
    assert "may have no visible in-game effect" in texture_html
    assert "Shader roughness/metal/shine" in texture_html
    assert "Manual sliders queue preview refresh after input settles" in manual_material_profile_initial_status_html()
    assert "Preview refresh queued; press Apply Manual Settings to force it now." in manual_material_profile_change_status_text(True)
    assert "Manual settings applied." in manual_material_profile_change_status_text(False)
    assert tooltips["preset_combo"] == (
        "Saved manual material profiles. Pick one to inspect, then Load to apply its values."
    )
    assert tooltips["preset_name"] == "Name for this saved manual material profile."
    assert tooltips["preset_details"] == "Notes about the look this preset is trying to achieve."
    assert tooltips["preset_recommended"] == (
        "Optional model paths, source asset names, material names, or tags this preset works well with."
    )
    assert tooltips["preset_save"] == (
        "Save the current manual slider values plus name/details/recommended models."
    )
    assert tooltips["preset_load"] == "Apply the selected saved profile values to the manual controls."
    assert tooltips["preset_delete"] == "Delete the selected saved manual profile."
    assert tooltips["apply"] == (
        "Force the current manual values into the preview/build impact now. "
        "Slider edits also queue a debounced preview refresh."
    )
    assert tooltips["reset"] == "Reset every manual knob to the current Material Authority baseline."
    assert "Preview warning</div>" in warning_html
    assert "cannot render the exact same textured look as the in-game CD shader" in warning_html


def test_manual_material_profile_control_text_preserves_preset_copy() -> None:
    text = manual_material_profile_control_text()

    assert text["group_title"] == "Material Authority Manual"
    assert text["group_object"] == "MeshAlignmentManualMaterialProfileGroup"
    assert text["preset_group"] == "Saved Manual Profiles"
    assert text["preset_name_placeholder"] == "Profile name, e.g. Clean Dark Metal"
    assert text["preset_details_placeholder"] == "What this profile changes and why"
    assert text["preset_recommended_placeholder"] == "Recommended models/materials, paths, or tags"
    assert text["preset_save_button"] == "Save Current"
    assert text["preset_load_button"] == "Load"
    assert text["preset_delete_button"] == "Delete"
    assert text["saved_label"] == "Saved"
    assert text["name_label"] == "Name"
    assert text["details_label"] == "Details"
    assert text["recommended_label"] == "Recommended"
    assert text["apply_button"] == "Apply Manual Settings"
    assert text["reset_button"] == "Reset To Material Authority"
    assert text["no_saved_profile"] == "No saved profile"
    assert text["save_title"] == "Save Manual Profile"
    assert text["save_missing_name"] == "Enter a profile name before saving."
    assert text["load_title"] == "Load Manual Profile"
    assert text["load_missing_selection"] == "Select a saved manual profile first."
    assert text["delete_title"] == "Delete Manual Profile"
    assert text["delete_missing_selection"] == "Select a saved manual profile first."
    assert manual_material_profile_saved_message("Clean") == 'Saved manual material profile "Clean".'
    assert manual_material_profile_delete_question("Clean") == 'Delete saved manual material profile "Clean"?'

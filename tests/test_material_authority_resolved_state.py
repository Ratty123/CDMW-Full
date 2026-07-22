from __future__ import annotations

import re
from pathlib import Path

from cdmw.domain.textures.material_authority_state import (
    MATERIAL_AUTHORITY_AUTOMATIC_KEYS,
    MATERIAL_AUTHORITY_CONTROL_REGISTRY,
    MATERIAL_AUTHORITY_EXPERT_KEYS,
    MATERIAL_AUTHORITY_MANUAL_KEYS,
    MaterialAuthorityCapability,
    MaterialAuthoritySyncStatus,
    identity_residual_parameter_groups,
    material_authority_control_states,
    material_authority_status_text,
    resolved_material_authority_state,
)
from cdmw.ui.archive_browser.static_replacement_manual_material_profile import (
    manual_material_profile_default_values,
)


def test_registry_classifies_every_automatic_and_manual_key_once() -> None:
    expected_automatic = {
        "global_gloss_reduction",
        "auto_brightness",
        "source_brightness",
        "tone_contrast",
        "edge_relief",
        "edge_relief_source",
        "accent_glow",
        "part_glow_color",
        "part_glow_strength",
    }
    assert MATERIAL_AUTHORITY_AUTOMATIC_KEYS == expected_automatic
    assert MATERIAL_AUTHORITY_MANUAL_KEYS == set(manual_material_profile_default_values(None))
    assert len(MATERIAL_AUTHORITY_CONTROL_REGISTRY) == len(set(MATERIAL_AUTHORITY_CONTROL_REGISTRY))


def test_hidden_dotnet_parity_report_covers_every_normal_control_once() -> None:
    source = (
        Path(__file__).parents[1]
        / "tools"
        / "dotnet_mesh_editor_experiment"
        / "MaterialAuthorityParityReport.cs"
    ).read_text(encoding="utf-8")
    case_block = source.split("private static IReadOnlyList<CaseDefinition> Cases()", 1)[1]
    case_block = case_block.split("private static void ApplyState", 1)[0]
    case_keys = re.findall(r'new\("([a-z0-9_]+)"', case_block)
    normal_keys = {
        key
        for key, spec in MATERIAL_AUTHORITY_CONTROL_REGISTRY.items()
        if spec.capability is not MaterialAuthorityCapability.EXPERT_ONLY
    }

    assert len(case_keys) == len(set(case_keys))
    assert set(case_keys) == normal_keys


def test_expert_keys_are_never_enabled_in_normal_control_states() -> None:
    states = material_authority_control_states(
        manual_material_profile_default_values(None),
        available_channels=("base", "normal", "height", "material_mask", "emissive"),
        has_emissive_source=True,
    )
    by_key = {state.key: state for state in states}
    assert MATERIAL_AUTHORITY_EXPERT_KEYS
    assert all(
        by_key[key].capability is MaterialAuthorityCapability.EXPERT_ONLY
        and not by_key[key].enabled
        for key in MATERIAL_AUTHORITY_EXPERT_KEYS
    )


def test_capabilities_explain_missing_channels_and_zero_artifact_delta() -> None:
    states = material_authority_control_states(
        {"support_policy": "source_only"},
        available_channels=("base",),
        target_height_supported=False,
        artifact_deltas={"source_brightness": False},
    )
    by_key = {state.key: state for state in states}
    assert by_key["edge_relief"].capability is MaterialAuthorityCapability.INAPPLICABLE
    assert "height" in by_key["edge_relief"].reason.lower()
    assert by_key["source_brightness"].enabled
    assert by_key["source_brightness"].reason == "No artifact delta at this value."
    assert by_key["accent_glow"].capability is MaterialAuthorityCapability.INAPPLICABLE
    assert "emissive" in by_key["accent_glow"].reason.lower()


def test_route_controls_remain_editable_while_disabled_but_dependents_do_not() -> None:
    states = material_authority_control_states(
        {
            "base_binding_mode": "disabled",
            "mask_binding_mode": "disabled",
            "emissive_mode": "disabled",
        },
        available_channels=("base", "material_mask", "emissive"),
        has_emissive_source=True,
        has_explicit_glow_part=True,
    )
    by_key = {state.key: state for state in states}

    assert by_key["base_binding_mode"].enabled
    assert by_key["mask_binding_mode"].enabled
    assert by_key["emissive_mode"].enabled
    assert by_key["base_color_gamma"].capability is MaterialAuthorityCapability.INAPPLICABLE
    assert by_key["roughness_scale"].capability is MaterialAuthorityCapability.INAPPLICABLE
    assert by_key["emissive_color_scale"].capability is MaterialAuthorityCapability.INAPPLICABLE


def test_gap_only_controls_explain_when_the_source_has_no_gap() -> None:
    states = material_authority_control_states(
        {},
        available_channels=("base", "normal", "height", "material_mask"),
        factor_only_base_applicable=False,
        factor_only_mask_applicable=False,
        neutral_support_gap_applicable=False,
    )
    by_key = {state.key: state for state in states}

    assert not by_key["allow_factor_only_authority"].enabled
    assert "base-color factor" in by_key["allow_factor_only_authority"].reason
    assert not by_key["factor_only_material_mask"].enabled
    assert "roughness/metal factors" in by_key["factor_only_material_mask"].reason
    assert not by_key["force_neutral_layer_support"].enabled
    assert "no neutral gap fill" in by_key["force_neutral_layer_support"].reason


def test_missing_channel_defaults_are_classified_per_pbr_component() -> None:
    states = material_authority_control_states(
        {},
        available_channels=("material_mask",),
        authoritative_default_keys=("roughness_default",),
    )
    by_key = {state.key: state for state in states}

    assert not by_key["roughness_default"].enabled
    assert by_key["metallic_default"].enabled
    assert by_key["ao_default"].enabled


def test_baked_channels_force_identity_residual_parameters() -> None:
    groups = identity_residual_parameter_groups(
        (
            {
                "source_submesh_indices": [2],
                "texture_brightness": 1.8,
                "gamma": 0.5,
                "roughness_scale": 0.2,
                "emissive_intensity": 7.0,
                "visible": True,
            },
        ),
        baked_channels=("base", "material_mask", "emissive"),
    )
    assert groups == (
        {
            "source_submesh_indices": [2],
            "texture_brightness": 1.0,
            "gamma": 1.0,
            "roughness_scale": 1.0,
            "emissive_intensity": 7.0,
            "visible": True,
            "contrast": 1.0,
            "post_contrast_brightness": 1.0,
            "saturation": 1.0,
            "tint_color": [1.0, 1.0, 1.0],
            "base_color_lift": 0,
            "value_max": 255,
            "auto_balance": 0,
            "shadow_lift": 0,
            "roughness_inverted": False,
            "metalness_inverted": False,
            "roughness_min": 0,
            "roughness_max": 255,
            "metalness_scale": 1.0,
            "metalness_min": 0,
            "metalness_max": 255,
            "roughness_blend_strength": 0.0,
            "metalness_blend_strength": 0.0,
            "emissive_color": [1.0, 1.0, 1.0],
        },
    )


def test_resolved_fingerprint_uses_dds_content_not_temporary_path() -> None:
    controls = material_authority_control_states(
        {},
        available_channels=("base",),
    )
    common = dict(
        profile_token="material_authority_detail_mask",
        revision=4,
        affected_submeshes=(1,),
        residual_parameter_groups=({"source_submesh_indices": [1], "texture_brightness": 1.0},),
        control_states=controls,
        status=MaterialAuthoritySyncStatus.EXACT,
    )
    first = resolved_material_authority_state(
        **common,
        dds_bindings=(
            {
                "resource_id": "base:1",
                "channel": "base",
                "path": "C:/Temp/one.dds",
                "source_dds_path": "C:/Temp/one.dds",
                "content_sha256": "a" * 64,
            },
        ),
    )
    second = resolved_material_authority_state(
        **common,
        dds_bindings=(
            {
                "resource_id": "base:1",
                "channel": "base",
                "path": "D:/Elsewhere/two.dds",
                "source_dds_path": "D:/Elsewhere/two.dds",
                "content_sha256": "a" * 64,
            },
        ),
    )
    changed = resolved_material_authority_state(
        **common,
        dds_bindings=(
            {
                "resource_id": "base:1",
                "channel": "base",
                "path": "D:/Elsewhere/two.dds",
                "content_sha256": "b" * 64,
            },
        ),
    )
    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != changed.fingerprint
    assert first.build_allowed
    assert material_authority_status_text(first.status) == "Exact preview/export synchronized"


def test_unsafe_fast_state_is_not_buildable_until_preview_acknowledges_it() -> None:
    common = dict(
        profile_token="manual",
        revision=8,
        affected_submeshes=(0,),
        dds_bindings=(
            {
                "resource_id": "base:0",
                "channel": "base",
                "content_sha256": "c" * 64,
            },
        ),
        residual_parameter_groups=(),
        control_states=(),
        status=MaterialAuthoritySyncStatus.FAST_PREVIEW,
        unsafe_expert_active=True,
        unsafe_export_acknowledged=True,
    )
    pending = resolved_material_authority_state(**common)
    acknowledged = resolved_material_authority_state(
        **common,
        preview_acknowledged=True,
    )

    assert not pending.build_allowed
    assert acknowledged.build_allowed


def test_resolved_fingerprint_is_independent_of_binding_order() -> None:
    common = dict(
        profile_token="manual",
        revision=2,
        affected_submeshes=(1, 0),
        residual_parameter_groups=(),
        control_states=(),
        status=MaterialAuthoritySyncStatus.EXACT,
    )
    bindings = (
        {"resource_id": "material:0", "channel": "material", "content_sha256": "b" * 64},
        {"resource_id": "base:0", "channel": "base", "content_sha256": "a" * 64},
    )
    first = resolved_material_authority_state(**common, dds_bindings=bindings)
    second = resolved_material_authority_state(**common, dds_bindings=tuple(reversed(bindings)))

    assert first.fingerprint == second.fingerprint

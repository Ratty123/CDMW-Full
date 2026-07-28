from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import threading

from PIL import Image
import pytest

from cdmw.core.texture_native import find_directxtex_texture_binary
from cdmw.domain.textures.material_authority_state import (
    MATERIAL_AUTHORITY_AUTOMATIC_KEYS,
    MATERIAL_AUTHORITY_EXPERT_KEYS,
    MATERIAL_AUTHORITY_MANUAL_KEYS,
)
from cdmw.domain.textures.material_parameters import (
    evaluate_material_parameters,
    material_parameter_renderer_overrides,
)
from cdmw.modding.material_profiles import (
    apply_true_source_basic_controls_to_profile,
    get_complete_swap_material_profile,
    serialize_complete_swap_manual_material_profile,
)
from cdmw.modding.material_replacer import ReplacementTextureSet, ReplacementTextureSlot
from cdmw.services.material_authority_resource_service import (
    generate_material_authority_resource_bindings,
)


_ALL_CHANNELS = ("base", "normal", "height", "material_mask", "emissive")


def _manual(values: dict[str, object]) -> object:
    return get_complete_swap_material_profile(
        serialize_complete_swap_manual_material_profile(values)
    )


def _automatic(**values: object) -> object:
    return apply_true_source_basic_controls_to_profile(
        get_complete_swap_material_profile("material_authority_detail_mask"),
        **values,
    )


def _write_fixture(root: Path, variant: str) -> ReplacementTextureSet:
    root.mkdir(parents=True, exist_ok=True)
    slot_names = {
        "full": {"base", "normal", "height", "emissive", "roughness", "metallic", "ao"},
        "base_only": {"base"},
        "base_emissive": {"base", "emissive"},
        "missing_roughness": {"base", "normal", "height", "emissive", "metallic", "ao"},
        "missing_metallic": {"base", "normal", "height", "emissive", "roughness", "ao"},
        "missing_ao": {"base", "normal", "height", "emissive", "roughness", "metallic"},
        "factor_base": {"normal", "height"},
        "factor_mask": {"base", "normal", "height"},
    }[variant]
    slots: dict[str, ReplacementTextureSlot] = {}
    for slot_name in sorted(slot_names):
        path = root / f"{slot_name}.png"
        pixels: list[tuple[int, int, int, int]] = []
        for y in range(8):
            for x in range(8):
                value = 24 + x * 21 + y * 8
                if slot_name == "base":
                    pixel = (value, 220 - x * 14, 35 + y * 23, 255)
                elif slot_name == "emissive":
                    pixel = (40 + x * 23, 18 + y * 19, 210 - x * 11, 255)
                elif slot_name == "normal":
                    pixel = (128 + x, 128 - y, 245, 255)
                else:
                    pixel = (value, value, value, 255)
                pixels.append(tuple(max(0, min(255, component)) for component in pixel))
        image = Image.new("RGBA", (8, 8))
        image.putdata(pixels)
        image.save(path)
        slots[slot_name] = ReplacementTextureSlot("Blade", slot_name, path)
    if variant == "factor_base":
        factor_path = root / "blade_base_factor.png"
        Image.new("RGBA", (8, 8), (51, 178, 230, 255)).save(factor_path)
        slots["base"] = ReplacementTextureSlot(
            "Blade",
            "base",
            factor_path,
            source_authority="synthetic",
            base_color_factor=(0.2, 0.7, 0.9),
        )
    return ReplacementTextureSet(
        "Blade",
        slots=slots,
        base_color_factor=(0.2, 0.7, 0.9) if variant == "factor_base" else None,
        roughness_factor=0.25 if variant == "factor_mask" else None,
        metallic_factor=0.8 if variant == "factor_mask" else None,
        occlusion_strength=0.6 if variant == "factor_mask" else None,
    )


def _resource_signature(
    texture_set: ReplacementTextureSet,
    profile: object,
    output_root: Path,
) -> dict[str, tuple[object, ...]]:
    # These assertions are about what the real DirectXTex encoder writes into each
    # canonical channel, so there is nothing to check without it. The texture
    # backend has no Python fallback by design.
    if find_directxtex_texture_binary() is None:
        pytest.skip("cd-texture-dx is not built")
    bindings = generate_material_authority_resource_bindings(
        (("Blade", texture_set),),
        profile,
        _ALL_CHANNELS,
        output_root,
        threading.Event(),
    )
    signature: dict[str, tuple[object, ...]] = {}
    for binding in bindings:
        channel = str(binding.get("channel", "") or "")
        if channel == "material":
            channel = "material_mask"
        signature[channel] = (
            bool(binding.get("remove", False)),
            str(binding.get("content_sha256", "") or ""),
            str(binding.get("dds_format", "") or ""),
            str(binding.get("color_space", "") or ""),
            int(binding.get("mip_count", 0) or 0),
        )
    return signature


_ARTIFACT_CASES = (
    ("global_gloss_reduction", "full", {"material_mask"}, _automatic(), _automatic(gloss_reduction=100)),
    ("auto_brightness", "full", {"base"}, _automatic(), _automatic(auto_brightness_balance=100)),
    ("source_brightness", "full", {"base"}, _automatic(), _automatic(dark_detail_lift=100)),
    ("tone_contrast", "full", {"base"}, _automatic(), _automatic(tone_contrast=100)),
    ("edge_relief", "base_only", {"normal", "height", "material_mask"}, _automatic(), _automatic(edge_relief_strength=100, edge_relief_source="generate_source")),
    ("edge_relief_source", "base_only", {"normal", "height", "material_mask"}, _automatic(edge_relief_strength=100, edge_relief_source="preserve_target"), _automatic(edge_relief_strength=100, edge_relief_source="generate_source")),
    ("base_binding_mode", "full", {"base"}, _manual({"base_binding_mode": "overlay_texture"}), _manual({"base_binding_mode": "disabled"})),
    ("mask_binding_mode", "full", {"material_mask"}, _manual({"mask_binding_mode": "detail_mask_material"}), _manual({"mask_binding_mode": "disabled"})),
    ("support_policy", "base_only", {"normal", "height", "material_mask"}, _manual({"support_policy": "source_only"}), _manual({"support_policy": "generated_or_neutral"})),
    ("emissive_mode", "full", {"emissive"}, _manual({"emissive_mode": "intensity"}), _manual({"emissive_mode": "disabled"})),
    ("base_color_lift", "full", {"base"}, _manual({"base_color_lift": 0}), _manual({"base_color_lift": 110})),
    ("base_color_gamma", "full", {"base"}, _manual({"base_color_gamma": 1.0}), _manual({"base_color_gamma": 0.35})),
    ("base_color_saturation", "full", {"base"}, _manual({"base_color_saturation": 1.0}), _manual({"base_color_saturation": 0.0})),
    ("base_color_value_max", "full", {"base"}, _manual({"base_color_value_max": 255}), _manual({"base_color_value_max": 96})),
    ("base_color_scale", "full", {"base"}, _manual({"base_color_scale": 1.0}), _manual({"base_color_scale": 0.25})),
    ("emissive_color_scale", "full", {"emissive"}, _manual({"emissive_color_scale": 1.0}), _manual({"emissive_color_scale": 0.2})),
    ("emissive_color_saturation", "full", {"emissive"}, _manual({"emissive_color_saturation": 1.0}), _manual({"emissive_color_saturation": 0.0})),
    ("emissive_color_value_max", "full", {"emissive"}, _manual({"emissive_color_value_max": 255}), _manual({"emissive_color_value_max": 72})),
    ("roughness_default", "missing_roughness", {"material_mask"}, _manual({"roughness_default": 255}), _manual({"roughness_default": 32})),
    ("roughness_min", "full", {"material_mask"}, _manual({"roughness_min": 0}), _manual({"roughness_min": 200})),
    ("roughness_scale", "full", {"material_mask"}, _manual({"roughness_min": 0, "roughness_scale": 0.5}), _manual({"roughness_min": 0, "roughness_scale": 1.5})),
    ("roughness_max", "full", {"material_mask"}, _manual({"roughness_min": 0, "roughness_max": 255}), _manual({"roughness_min": 0, "roughness_max": 80})),
    ("metallic_default", "missing_metallic", {"material_mask"}, _manual({"metallic_default": 0}), _manual({"metallic_default": 220})),
    ("metallic_min", "full", {"material_mask"}, _manual({"metallic_min": 0}), _manual({"metallic_min": 180})),
    ("metallic_scale", "full", {"material_mask"}, _manual({"metallic_scale": 0.4}), _manual({"metallic_scale": 1.6})),
    ("metallic_max", "full", {"material_mask"}, _manual({"metallic_max": 255}), _manual({"metallic_max": 80})),
    ("ao_default", "missing_ao", {"material_mask"}, _manual({"ao_default": 255}), _manual({"ao_default": 32})),
    ("force_nonmetal", "full", {"material_mask"}, _manual({"force_nonmetal": False}), _manual({"force_nonmetal": True})),
    ("roughness_inverted", "full", {"material_mask"}, _manual({"roughness_min": 0, "roughness_inverted": False}), _manual({"roughness_min": 0, "roughness_inverted": True})),
    ("metallic_inverted", "full", {"material_mask"}, _manual({"metallic_inverted": False}), _manual({"metallic_inverted": True})),
    ("allow_factor_only_authority", "factor_base", {"base"}, _manual({"allow_factor_only_authority": False}), _manual({"allow_factor_only_authority": True})),
    ("factor_only_material_mask", "factor_mask", {"material_mask"}, _manual({"factor_only_material_mask": False}), _manual({"factor_only_material_mask": True})),
    ("force_neutral_layer_support", "base_only", {"normal", "height", "material_mask"}, _manual({"support_policy": "source_only", "force_neutral_layer_support": False}), _manual({"support_policy": "source_only", "force_neutral_layer_support": True})),
)


@pytest.mark.parametrize(
    ("control_key", "fixture", "affected_channels", "baseline", "changed"),
    _ARTIFACT_CASES,
    ids=[case[0] for case in _ARTIFACT_CASES],
)
def test_every_artifact_control_changes_only_its_declared_canonical_channels(
    tmp_path: Path,
    control_key: str,
    fixture: str,
    affected_channels: set[str],
    baseline: object,
    changed: object,
) -> None:
    texture_set = _write_fixture(tmp_path / "source", fixture)
    before = _resource_signature(texture_set, baseline, tmp_path / "before")
    after = _resource_signature(texture_set, changed, tmp_path / "after")
    changed_channels = {
        channel for channel in _ALL_CHANNELS if before.get(channel) != after.get(channel)
    }

    assert changed_channels, f"{control_key} produced no canonical DDS/binding delta"
    assert changed_channels <= affected_channels


def test_selected_part_glow_color_changes_only_emissive_dds(tmp_path: Path) -> None:
    texture_set = _write_fixture(tmp_path / "source", "full")
    texture_set.source_role_tags = ("glow",)
    profile = _manual({"emissive_mode": "intensity"})
    texture_set.accent_glow_color_rgb = (1.0, 0.0, 0.0)
    before = _resource_signature(texture_set, profile, tmp_path / "red")
    texture_set.accent_glow_color_rgb = (0.0, 0.0, 1.0)
    after = _resource_signature(texture_set, profile, tmp_path / "blue")

    assert before["emissive"] != after["emissive"]
    assert all(before[channel] == after[channel] for channel in _ALL_CHANNELS if channel != "emissive")


@pytest.mark.parametrize(
    ("control_key", "baseline", "changed", "parameter"),
    (
        (
            "accent_glow",
            evaluate_material_parameters(_automatic(), part_adjustment=SimpleNamespace(material_role="glow", emissive_strength=1.0, emissive_color_rgb=())),
            evaluate_material_parameters(_automatic(accent_glow_strength=100), part_adjustment=SimpleNamespace(material_role="glow", emissive_strength=1.0, emissive_color_rgb=())),
            "emissive_intensity",
        ),
        (
            "part_glow_strength",
            evaluate_material_parameters(_automatic(), part_adjustment=SimpleNamespace(material_role="glow", emissive_strength=1.0, emissive_color_rgb=())),
            evaluate_material_parameters(_automatic(), part_adjustment=SimpleNamespace(material_role="glow", emissive_strength=3.0, emissive_color_rgb=())),
            "emissive_intensity",
        ),
        (
            "displacement_scale_multiplier",
            evaluate_material_parameters(_manual({"displacement_scale_multiplier": 0.2, "displacement_scale_max": 1.0})),
            evaluate_material_parameters(_manual({"displacement_scale_multiplier": 0.8, "displacement_scale_max": 1.0})),
            "height_scale",
        ),
        (
            "displacement_scale_max",
            evaluate_material_parameters(_manual({"displacement_scale_multiplier": 1.0, "displacement_scale_max": 0.2})),
            evaluate_material_parameters(_manual({"displacement_scale_multiplier": 1.0, "displacement_scale_max": 0.8})),
            "height_scale",
        ),
    ),
)
def test_parameter_backed_controls_change_the_canonical_parameter(
    control_key: str,
    baseline: object,
    changed: object,
    parameter: str,
) -> None:
    before = material_parameter_renderer_overrides(baseline)
    after = material_parameter_renderer_overrides(changed)

    assert before.get(parameter) != after.get(parameter), control_key


def test_effect_matrix_covers_every_normal_control_exactly_once() -> None:
    # Per-part controls are authored on the source-part adjustment rather than
    # the material profile, so they have no profile-driven generation case
    # above; they are still artifact controls that rewrite the baked channel.
    artifact_keys = {case[0] for case in _ARTIFACT_CASES} | {
        "part_glow_color",
        "part_colourise_color",
        "part_colourise_strength",
    }
    parameter_keys = {
        "accent_glow",
        "part_glow_strength",
        "displacement_scale_multiplier",
        "displacement_scale_max",
    }
    normal_keys = (MATERIAL_AUTHORITY_AUTOMATIC_KEYS | MATERIAL_AUTHORITY_MANUAL_KEYS) - MATERIAL_AUTHORITY_EXPERT_KEYS

    assert artifact_keys | parameter_keys == normal_keys
    assert not artifact_keys & parameter_keys

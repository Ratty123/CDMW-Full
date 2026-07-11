from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from cdmw.domain.textures.material_parameters import (
    evaluate_material_parameters,
    material_parameter_renderer_overrides,
)
from cdmw.modding.material_replacer import ReplacementTextureSet, ReplacementTextureSlot
from cdmw.modding.material_base_color_evaluator import shader_equivalent_base_color_rgba
from cdmw.modding.material_profiles import get_complete_swap_material_profile, serialize_complete_swap_manual_material_profile
from cdmw.modding.material_source_driven import _complete_swap_runtime_material_mask_png_path
from cdmw.modding.material_texture_payloads import _source_slot_png_with_base_color_factor_path
from cdmw.modding.material_texture_payloads import material_authority_preview_texture_slots
from cdmw.modding.material_texture_routing import _source_part_adjusted_slot


def test_evaluator_composes_profile_and_per_part_values() -> None:
    profile = SimpleNamespace(
        base_color_scale=1.5,
        base_color_lift=12,
        base_color_gamma=0.8,
        base_color_saturation=0.5,
        base_color_value_max=210,
        base_color_auto_balance=30,
        base_color_shadow_lift=20,
        base_color_tone_contrast=-10,
        scratch_roughness=0.0,
        scratch_metallic=0.0,
        shine_scalar=0.0,
        roughness_inverted=True,
        metallic_invert=True,
        force_nonmetal=False,
        roughness_min=0,
        roughness_scale=0.0,
        roughness_max=255,
        metallic_min=0,
        metallic_scale=0.0,
        metallic_max=255,
        global_gloss_reduction=0,
        gloss_reduction_mode="source roughness high",
        displacement_scale_multiplier=0.0,
        edge_relief_strength=25,
        edge_relief_source="generate",
        emissive_mode="intensity",
        name="material_authority_manual",
        authority_contract="true_source_authority",
        accent_glow_strength=50,
        accent_glow_intensity_max=4.0,
    )
    part = SimpleNamespace(
        material_brightness=-20,
        material_contrast=30,
        material_saturation=50,
        material_gamma=0.5,
        material_tint_rgb=(128, 255, 0),
        material_role="glow",
        emissive_color_rgb=(0, 64, 255),
    )

    values = evaluate_material_parameters(profile, part_adjustment=part)

    assert values.base_color_scale == pytest.approx(1.2)
    assert values.base_color_lift == 12
    assert values.gamma == 0.4
    assert values.saturation == 0.75
    assert values.value_max == 210
    assert values.auto_balance == 30
    assert values.shadow_lift == 20
    assert values.tone_contrast == 20
    assert values.tint_color == (128 / 255, 1.0, 0.0)
    assert values.tint_adjustment == values.tint_color
    assert values.roughness == 0.0
    assert values.metalness == 0.0
    assert values.specular == 0.0
    assert values.roughness_inverted is True
    assert values.metalness_inverted is True
    assert values.roughness_min == 0
    assert values.roughness_scale == 0.0
    assert values.metallic_scale == 0.0
    assert values.height_scale == 0.25
    assert values.relief_source == "generate_source"
    assert values.emissive_intensity == 2.5
    assert values.emissive_color == (0.0, 64 / 255, 1.0)
    assert values.emissive_role == "emissive"


def test_renderer_serializer_retains_present_zero_values() -> None:
    profile = SimpleNamespace(
        base_color_scale=0.0,
        base_color_gamma=1.0,
        base_color_saturation=0.0,
        base_color_tone_contrast=-100,
        scratch_roughness=0.0,
        scratch_metallic=0.0,
        shine_scalar=0.0,
        displacement_scale_multiplier=0.0,
        edge_relief_strength=0.0,
        emissive_mode="intensity",
        name="runtime",
        authority_contract="",
        accent_glow_strength=0.0,
    )
    values = evaluate_material_parameters(
        profile,
        emissive_role=True,
        emissive_intensity=0.0,
        emissive_color=(0, 0, 0),
    )

    payload = material_parameter_renderer_overrides(values)

    assert payload["texture_brightness"] == 0.1
    assert payload["contrast"] == pytest.approx(0.45)
    assert payload["post_contrast_brightness"] == pytest.approx(1.1)
    assert payload["saturation"] == 0.0
    assert payload["base_color_lift"] == 0
    assert payload["value_max"] == 255
    assert payload["roughness_inverted"] is False
    assert payload["roughness"] == 0.0
    assert payload["metalness"] == 0.0
    assert payload["specular"] == 0.0
    assert payload["height_scale"] == 0.0
    assert payload["emissive_intensity"] == 0.0
    assert payload["emissive_color"] == [0.0, 0.0, 0.0]
    assert payload["material_role"] == "emissive"


def test_detail_mask_profiles_transform_sampled_pbr_instead_of_overriding_it() -> None:
    detail_profile = SimpleNamespace(
        mask_binding_mode="detail_mask_material",
        scratch_roughness=0.2,
        scratch_metallic=0.8,
        roughness_scale=0.5,
        roughness_min=20,
        roughness_max=220,
        metallic_scale=0.25,
        metallic_min=0,
        metallic_max=128,
        force_nonmetal=False,
    )
    payload = material_parameter_renderer_overrides(evaluate_material_parameters(detail_profile))
    assert "roughness" not in payload
    assert "metalness" not in payload
    assert payload["roughness_scale"] == 0.5
    assert payload["metalness_scale"] == 0.25

    scalar_payload = material_parameter_renderer_overrides(
        evaluate_material_parameters(SimpleNamespace(**{**vars(detail_profile), "mask_binding_mode": "scratch_scalars"}))
    )
    assert scalar_payload["roughness"] == 0.2
    assert scalar_payload["metalness"] == 0.8

    nonmetal_payload = material_parameter_renderer_overrides(
        evaluate_material_parameters(SimpleNamespace(**{**vars(detail_profile), "force_nonmetal": True}))
    )
    assert "roughness" not in nonmetal_payload
    assert nonmetal_payload["metalness"] == 0.0


def test_per_part_export_slot_uses_shared_evaluation(tmp_path: Path) -> None:
    source = ReplacementTextureSlot(
        "body",
        "base",
        tmp_path / "body.png",
        base_color_factor=(0.5, 0.25, 1.0),
        base_color_scale=1.25,
        base_color_gamma=0.8,
        base_color_saturation=0.5,
        base_color_tone_contrast=-20,
    )
    adjustment = SimpleNamespace(
        material_brightness=20,
        material_contrast=40,
        material_saturation=50,
        material_gamma=0.5,
        material_tint_rgb=(128, 255, 64),
    )

    adjusted = _source_part_adjusted_slot(source, adjustment)
    expected = evaluate_material_parameters(source_slot=source, part_adjustment=adjustment)

    assert adjusted.base_color_factor == expected.tint_color
    assert adjusted.base_color_scale == expected.base_color_scale
    assert adjusted.base_color_gamma == expected.gamma
    assert adjusted.base_color_saturation == expected.saturation
    assert adjusted.base_color_tone_contrast == expected.tone_contrast


def test_force_nonmetal_is_exact_zero_in_export_mask(tmp_path: Path) -> None:
    profile = get_complete_swap_material_profile(
        serialize_complete_swap_manual_material_profile(
            {"force_nonmetal": True, "metallic_default": 255, "metallic_min": 200, "metallic_scale": 2.0}
        )
    )
    output = _complete_swap_runtime_material_mask_png_path(
        ReplacementTextureSet(material_name=f"force_nonmetal_{tmp_path.name}"),
        profile,
    )
    with Image.open(output) as image:
        assert image.convert("RGBA").getpixel((0, 0))[2] == 0


def test_cpu_export_keeps_factor_gamma_lift_cap_order(tmp_path: Path, monkeypatch) -> None:
    from cdmw.modding import material_texture_payloads

    monkeypatch.setattr(material_texture_payloads.tempfile, "gettempdir", lambda: str(tmp_path))
    source_path = tmp_path / "source.png"
    Image.new("RGBA", (1, 1), (64, 128, 192, 200)).save(source_path)
    slot = ReplacementTextureSlot(
        "body",
        "base",
        source_path,
        base_color_factor=(0.5, 1.0, 0.25),
        base_color_scale=0.75,
        base_color_lift=10,
        base_color_gamma=0.8,
        base_color_saturation=1.0,
        base_color_value_max=180,
    )

    output = _source_slot_png_with_base_color_factor_path(slot)

    def channel(value: int, factor: float) -> int:
        factored = round(value * factor * 0.75)
        gamma = round(((factored / 255.0) ** 0.8) * 255.0)
        lifted = round(10.0 + gamma * ((255.0 - 10.0) / 255.0))
        return min(180, lifted)

    with Image.open(output) as image:
        assert image.convert("RGBA").getpixel((0, 0)) == (
            channel(64, 0.5),
            channel(128, 1.0),
            channel(192, 0.25),
            200,
        )


def test_preview_slots_prune_disabled_base_emissive_and_mask_resources(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (2, 2), (64, 96, 128, 255)).save(source)
    texture_set = ReplacementTextureSet(
        "body",
        slots={
            channel: ReplacementTextureSlot("body", channel, source)
            for channel in ("base", "emissive", "material_mask")
        },
    )
    disabled = get_complete_swap_material_profile(
        serialize_complete_swap_manual_material_profile(
            {
                "base_binding_mode": "disabled",
                "mask_binding_mode": "scratch_scalars",
                "emissive_mode": "disabled",
            }
        )
    )

    slots = material_authority_preview_texture_slots(
        texture_set,
        disabled,
        output_root=tmp_path / "generated",
    )

    assert not {"base", "emissive", "material", "material_mask", "detail_mask"}.intersection(slots)
    assert set(material_authority_preview_texture_slots(texture_set, disabled, enabled=False)) == {
        "base",
        "emissive",
        "material_mask",
    }


@pytest.mark.parametrize(
    ("tone_contrast", "base_color_scale", "expected"),
    (
        (-65.0, 0.75, ((87, 115, 123, 100), (119, 145, 119, 64), (147, 154, 106, 32))),
        (70.0, 1.2, ((32, 119, 145, 100), (111, 183, 111, 64), (156, 192, 68, 32))),
        (0.0, 0.0, ((48, 56, 59, 100), (62, 72, 62, 64), (77, 81, 57, 32))),
    ),
)
def test_cpu_base_color_evaluator_matches_resident_shader_golden(
    tone_contrast: float,
    base_color_scale: float,
    expected: tuple[tuple[int, int, int, int], ...],
) -> None:
    source = Image.new("RGBA", (3, 1))
    source.putdata(((20, 40, 80, 200), (120, 140, 160, 128), (230, 200, 170, 64)))
    values = SimpleNamespace(
        base_brightness=1.0,
        base_color_scale=base_color_scale,
        tint_color=(0.8, 1.0, 0.6),
        gamma=0.8,
        base_color_lift=24,
        saturation=1.3,
        auto_balance=80,
        shadow_lift=35,
        tone_contrast=tone_contrast,
        value_max=220,
    )

    actual = tuple(shader_equivalent_base_color_rgba(source, values, alpha_factor=0.5).get_flattened_data())

    assert all(abs(actual[index][channel] - expected[index][channel]) <= 1 for index in range(3) for channel in range(4))

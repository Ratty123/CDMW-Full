"""Per-part recolour: preview parameters, CPU bake, and shader parity.

The recolour operator exists twice: once in `D3D11MaterialShaders.hlsl` for the
fast preview lane, and once on the CPU in `material_base_color_evaluator` for
the DDS that Build Mod publishes. These tests pin the CPU port to an
independent transcription of the shader block so the two cannot drift.
"""

from __future__ import annotations

from pathlib import Path
import re
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from cdmw.domain.textures.material_parameters import (
    evaluate_material_parameters,
    material_parameter_renderer_overrides,
    normalize_colourise_strength,
)
from cdmw.modding.material_base_color_evaluator import shader_equivalent_base_color_rgba


LUMA_WEIGHTS = (0.299, 0.587, 0.114)
SHADER_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "dotnet_mesh_editor_experiment"
    / "D3D11MaterialShaders.hlsl"
)


def _saturate(value):
    return np.clip(value, 0.0, 1.0)


def _reference_shader_colourise(rgb, tint, strength):
    """Independent transcription of the HLSL recolour block, non-metal path.

    Deliberately written from the shader source rather than by calling the
    production helper, so a change to one side fails this test.
    """
    weights = np.asarray(LUMA_WEIGHTS, dtype=np.float64)
    preview_tint = np.clip(np.asarray(tint, dtype=np.float64), 0.0, 1.0)
    tint_luma = max(float(preview_tint @ weights), 0.08)
    tint_bias = np.clip(preview_tint / tint_luma, 0.38, 1.72)
    strength = min(max(float(strength), 0.0), 1.0)
    albedo_luma = np.sum(rgb * weights, axis=-1, keepdims=True)
    lifted_luma = _saturate(albedo_luma * (1.05 + strength * 0.35) + 0.10 * strength)
    multiplied = _saturate(rgb * tint_bias)
    colorized = _saturate(lifted_luma * tint_bias)
    colorize_strength = 0.58
    inner = multiplied + (colorized - multiplied) * colorize_strength
    return rgb + (inner - rgb) * strength


def _bake(source_rgb, *, colour, strength, size=(8, 8)):
    image = Image.new("RGBA", size, (*source_rgb, 255))
    values = evaluate_material_parameters(
        part_adjustment=SimpleNamespace(
            material_colourise_rgb=colour,
            material_colourise_strength=strength,
        )
    )
    baked = shader_equivalent_base_color_rgba(image, values, alpha_factor=1.0)
    return np.asarray(baked, dtype=np.uint8)[0, 0, :3]


@pytest.mark.parametrize(
    "source_rgb,colour,strength",
    [
        ((72, 48, 30), (220, 30, 30), 1.0),
        ((72, 48, 30), (220, 30, 30), 0.5),
        ((18, 18, 20), (40, 120, 255), 0.9),
        ((210, 205, 198), (12, 160, 90), 0.75),
        ((128, 128, 128), (255, 255, 255), 1.0),
        ((90, 20, 140), (255, 200, 40), 0.33),
    ],
)
def test_cpu_bake_matches_shader_transcription(source_rgb, colour, strength):
    """The published DDS pixel must equal the shader's recolour result."""
    baked = _bake(source_rgb, colour=colour, strength=strength)

    rgb = np.asarray(source_rgb, dtype=np.float64) / 255.0
    tint = np.asarray(colour, dtype=np.float64) / 255.0
    expected = _reference_shader_colourise(rgb, tint, strength)
    expected_bytes = np.floor(np.clip(expected, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)

    assert np.max(np.abs(baked.astype(int) - expected_bytes.astype(int))) <= 1, (
        f"baked={baked.tolist()} expected={expected_bytes.tolist()}"
    )


def test_zero_strength_is_pixel_exact_identity():
    """Strength 0 must not perturb a single byte, so an unused control is free."""
    source = (137, 64, 201)
    assert _bake(source, colour=(255, 0, 0), strength=0.0).tolist() == list(source)


def test_recolour_beats_multiply_on_a_dark_source():
    """The whole point: multiply muddies a dark texture, recolour repaints it."""
    source = (72, 48, 30)
    recoloured = _bake(source, colour=(220, 30, 30), strength=1.0)

    multiply_values = evaluate_material_parameters(
        part_adjustment=SimpleNamespace(material_tint_rgb=(220, 30, 30))
    )
    multiplied = np.asarray(
        shader_equivalent_base_color_rgba(
            Image.new("RGBA", (4, 4), (*source, 255)), multiply_values, alpha_factor=1.0
        ),
        dtype=np.uint8,
    )[0, 0, :3]

    assert int(recoloured[0]) > int(multiplied[0]) + 60
    assert int(recoloured[0]) > int(source[0])


def test_renderer_overrides_carry_the_fast_preview_parameters():
    values = evaluate_material_parameters(
        part_adjustment=SimpleNamespace(
            material_colourise_rgb=(220, 30, 30),
            material_colourise_strength=0.8,
        )
    )
    overrides = material_parameter_renderer_overrides(values)
    assert overrides["base_tint_strength"] == pytest.approx(0.8)
    assert overrides["base_tint_color"] == pytest.approx([220 / 255, 30 / 255, 30 / 255], abs=1e-6)


def test_a_recolour_is_declared_authored_so_the_shader_skips_metal_damping():
    """Without this the preview under-applies ~20x on metal-classified parts.

    Measured on a real sword blade: chroma 4.6 damped vs 15.9 authored.
    """
    values = evaluate_material_parameters(
        part_adjustment=SimpleNamespace(
            material_colourise_rgb=(220, 30, 30),
            material_colourise_strength=1.0,
        )
    )
    assert material_parameter_renderer_overrides(values)["base_tint_authored"] is True


def test_the_shader_honours_the_authored_flag_before_classifying_metal():
    """The flag only works if it gates `earlyCategoryMetal` itself.

    Everything downstream -- the 0.05 multiplier and the colorize blend -- is
    derived from that bool, so gating it is what makes the authored path equal
    the non-metal path this file's CPU port implements.
    """
    source = SHADER_PATH.read_text(encoding="utf-8", errors="ignore")
    assert "float4 MaterialBaseTintAuthored;" in source
    block = source[source.index("MaterialBaseTintPolicy.x > 0.001f"):]
    block = block[: block.index("MaterialBaseAdjustments.x")]
    collapsed = re.sub(r"\s+", "", block)
    assert "boolauthoredBaseTint=MaterialBaseTintAuthored.x>0.5f;" in collapsed
    assert "boolearlyCategoryMetal=!authoredBaseTint" in collapsed


def test_the_baked_identity_clears_the_authored_flag():
    """The baked DDS already carries the recolour; the parameter must reset."""
    from cdmw.domain.textures.material_authority_state import (
        identity_residual_parameter_groups,
    )

    group = identity_residual_parameter_groups(
        ({"source_submesh_indices": [0], "base_tint_authored": True},),
        baked_channels=("base",),
    )[0]
    assert group["base_tint_authored"] is False
    assert group["base_tint_strength"] == 0.0


def test_renderer_overrides_omit_the_parameters_when_unused():
    overrides = material_parameter_renderer_overrides(
        evaluate_material_parameters(part_adjustment=SimpleNamespace())
    )
    assert "base_tint_color" not in overrides
    assert "base_tint_strength" not in overrides


def test_slot_carries_the_operand_for_bake_time_re_evaluation():
    """A cloned texture set re-evaluates from the slot, not the adjustment."""
    slot = SimpleNamespace(base_colourise_rgb=(0.5, 0.25, 0.75), base_colourise_strength=0.6)
    values = evaluate_material_parameters(source_slot=slot)
    assert values.colourise_strength == pytest.approx(0.6)
    assert values.colourise_color == pytest.approx((0.5, 0.25, 0.75))


def test_part_adjustment_overrides_the_slot_operand():
    slot = SimpleNamespace(base_colourise_rgb=(0.5, 0.5, 0.5), base_colourise_strength=0.6)
    part = SimpleNamespace(material_colourise_rgb=(255, 0, 0), material_colourise_strength=1.0)
    values = evaluate_material_parameters(source_slot=slot, part_adjustment=part)
    assert values.colourise_color == pytest.approx((1.0, 0.0, 0.0))
    assert values.colourise_strength == pytest.approx(1.0)


def test_recolouring_one_part_clones_its_texture_set_instead_of_repainting_siblings():
    """The clone gate is what keeps a recolour local to the edited part."""
    from pathlib import Path

    from cdmw.modding.material_replacer import ReplacementTextureSet, ReplacementTextureSlot
    from cdmw.modding.material_texture_routing import _apply_source_part_role_overrides

    texture_sets = {
        "steel": ReplacementTextureSet(
            material_name="steel",
            slots={"base": ReplacementTextureSlot("steel", "base", Path("steel_base.dds"))},
        )
    }
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(material="steel", name="pauldron", faces=[1]),
            SimpleNamespace(material="steel", name="greave", faces=[1]),
        ]
    )
    adjustment = SimpleNamespace(
        source_submesh_index=0,
        material_role="",
        material_colourise_rgb=(220, 30, 30),
        material_colourise_strength=1.0,
    )

    _apply_source_part_role_overrides(texture_sets, mesh, [adjustment])

    alias = "__source_part_0_steel"
    assert alias in texture_sets, "the recoloured part did not get its own texture set"
    assert getattr(mesh.submeshes[0], "cdmw_source_texture_set_key", "") == alias
    assert texture_sets[alias].slots["base"].base_colourise_strength == pytest.approx(1.0)
    # The sibling keeps the untouched shared material.
    assert texture_sets["steel"].slots["base"].base_colourise_strength == pytest.approx(0.0)
    assert texture_sets["steel"].slots["base"].base_colourise_rgb == ()
    assert not hasattr(mesh.submeshes[1], "cdmw_source_texture_set_key")


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, 0.0),
        ("", 0.0),
        (-3.0, 0.0),
        (0.42, 0.42),
        (1.0, 1.0),
        (55, 0.55),
        (100, 1.0),
        (250, 1.0),
        (float("nan"), 0.0),
    ],
)
def test_strength_normalization_accepts_fraction_or_percent(raw, expected):
    assert normalize_colourise_strength(raw) == pytest.approx(expected)


def test_shader_still_implements_the_constants_this_port_assumes():
    """Guard the CPU port against a silent shader-side constant change.

    Source-string checks are not proof of behaviour, but these five literals
    are the only coupling between the two implementations, so a change to them
    must break a test rather than the render.
    """
    source = SHADER_PATH.read_text(encoding="utf-8", errors="ignore")
    block = source[source.index("MaterialBaseTintPolicy.x > 0.001f"):]
    block = block[: block.index("MaterialBaseAdjustments.x")]
    collapsed = re.sub(r"\s+", "", block)

    assert "max(dot(previewTint,float3(0.299f,0.587f,0.114f)),0.08f)" in collapsed
    assert "float3(0.38f,0.38f,0.38f)" in collapsed
    assert "float3(1.72f,1.72f,1.72f)" in collapsed
    assert "albedoLuma*(1.05f+strength*0.35f)+0.10f*strength" in collapsed
    assert "lerp(0.58f,0.96f,neutralMetalTint)" in collapsed

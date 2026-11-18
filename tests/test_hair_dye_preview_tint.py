"""The hair dye reaches the renderer as the game applies it.

The game's hair shaders overlay `_hairDyeingColor` on the greyed base texture
and mix the result in by the colour's alpha (SkinnedMeshHair and its kin,
permutation 75b7a093c17d73a3). The colour is the texture tint; its alpha is
the tint's strength, and alpha zero is "no dye".
"""

from __future__ import annotations

from cdmw.models import (
    PreparedModelPreviewBatch,
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
from cdmw.rendering.native_preview_material_contract import (
    sidecar_hair_dye_for_batch,
    sidecar_preview_texture_tint_for_batch,
)
from cdmw.rendering.preview_tint_contract import resolve_preview_tint_contract


def _hair_batch(value: str, *, shader_family: str = "SkinnedMeshHair") -> PreparedModelPreviewBatch:
    rgb = tuple(int(value[index:index + 2], 16) / 255.0 for index in (1, 3, 5))
    return PreparedModelPreviewBatch(
        material_name="CD_PHM_00_Mask_Belt_side_0207",
        texture_name="phm_00_hair_base_0001",
        preview_material_texture_inputs=(
            PreviewMaterialTextureInput(
                slot_kind="base",
                parameter_name="_baseColorTexture",
                material_name="CD_PHM_00_Mask_Belt_side_0207",
                shader_family=shader_family,
                sidecar_kind="pac_xml",
                owner_slot_index=0,
                owner_wrapper_item_id="151",
                binding_authority="authoritative",
                material_parameters=(
                    PreviewMaterialParameterInput(
                        parameter_kind="color",
                        parameter_name="_hairDyeingColor",
                        value=value,
                        color_value=rgb,
                    ),
                ),
            ),
        ),
    )


def test_a_hair_dye_is_the_tint_and_its_alpha_the_strength() -> None:
    batch = _hair_batch("#d2bb6080")

    assert sidecar_hair_dye_for_batch(batch) == (210 / 255.0, 187 / 255.0, 96 / 255.0, 128 / 255.0)
    contract = resolve_preview_tint_contract(batch)

    assert contract.hair_dye
    assert contract.texture_tint == (210 / 255.0, 187 / 255.0, 96 / 255.0)
    # Not the 0.85 every other promoted tint gets: the game mixes by the alpha.
    assert contract.base_tint_strength == 128 / 255.0
    assert resolve_preview_tint_contract(_hair_batch("#d2bb60ff")).base_tint_strength == 1.0
    # Preview Core states base_tint_strength 0 for a part without a tinted base;
    # that is not the dye's strength (0 made the renderer multiply, not dye).
    assert resolve_preview_tint_contract(batch, base_tint_strength=0.0).base_tint_strength == 128 / 255.0


def test_a_hair_dye_with_alpha_zero_is_no_dye() -> None:
    batch = _hair_batch("#93020200")

    assert sidecar_hair_dye_for_batch(batch) == (147 / 255.0, 2 / 255.0, 2 / 255.0, 0.0)
    assert sidecar_preview_texture_tint_for_batch(batch) == ()
    contract = resolve_preview_tint_contract(batch)
    assert not contract.texture_tint_active
    assert contract.base_tint_strength == 0.0


def test_only_hair_families_read_the_hair_dye() -> None:
    assert sidecar_hair_dye_for_batch(_hair_batch("#d2bb60ff", shader_family="SkinnedMeshAnimalHair")) is not None
    assert sidecar_hair_dye_for_batch(_hair_batch("#d2bb60ff", shader_family="SkinnedMeshWhiteHornHair")) is not None
    assert sidecar_hair_dye_for_batch(_hair_batch("#d2bb60ff", shader_family="SkinnedMeshStandard")) is None


def test_a_dye_stated_as_the_parts_tint_already_keeps_the_dyes_alpha() -> None:
    # The archive sidecar rules copy a binding's tint colour onto the part.
    batch = _hair_batch("#d2bb6080")
    batch.preview_texture_tint = (210 / 255.0, 187 / 255.0, 96 / 255.0)

    contract = resolve_preview_tint_contract(batch, base_tint_strength=0.0)
    assert contract.hair_dye
    assert contract.base_tint_strength == 128 / 255.0

    switched_off = _hair_batch("#d2bb6000")
    switched_off.preview_texture_tint = (210 / 255.0, 187 / 255.0, 96 / 255.0)
    contract = resolve_preview_tint_contract(switched_off)
    assert not contract.texture_tint_active
    assert contract.texture_tint == ()
    assert contract.base_tint_strength == 0.0


def test_another_tint_on_a_hair_part_is_not_the_dye() -> None:
    batch = _hair_batch("#d2bb6080")
    batch.preview_texture_tint = (0.2, 0.4, 0.9)

    contract = resolve_preview_tint_contract(batch)
    assert not contract.hair_dye
    assert contract.texture_tint == (0.2, 0.4, 0.9)
    assert contract.base_tint_strength == 0.85

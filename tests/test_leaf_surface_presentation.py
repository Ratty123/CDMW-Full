"""Parts of the game's leaf shaders draw by their own rule, not as Standard parts.

GrassLeaf, TreeLeaf and TreeFrond share one pixel shader (c148717afa198273,
0bfb2ab3479b9972, c37dd47c3db87f5d and their AlphaTest twins): the texture
tinted toward `_grassColor`, roughness a constant per family and face, no
metal, and with AlphaTest a cut at base alpha 0.5. `_materialTexture` is not a
roughness and metal map there (TreeFrond and TreeLeaf often bind a
`_subsurface.dds` to it), so the preview must not read it as one.
"""

from __future__ import annotations

import pytest

from cdmw.services.mesh_rust_preview_package import (
    LEAF_SHADER_KIND,
    _apply_preview_core_leaf_surfaces,
    leaf_surface_presentation,
)

SCOPE = "character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_mace_0035.pac#model_property=0"


def test_each_leaf_family_states_its_roughness_by_face_and_no_tint_by_default() -> None:
    for family, front, back in (
        ("SkinnedMeshGrassLeaf", 0.45, 0.45),
        ("SkinnedMeshTreeLeaf", 1.0, 0.30),
        ("SkinnedMeshTreeFrond", 1.0, 0.60),
    ):
        surface = leaf_surface_presentation(family, {"AlphaTest": "1"})
        controls = surface["shader_controls"]
        assert len(controls) == 32
        assert controls[0] == LEAF_SHADER_KIND == 20.0
        assert controls[4:6] == pytest.approx([front, back])
        # No _grassColor: the default 0x00000000, strength 0, the texture unchanged.
        assert controls[6:10] == [0.0, 0.0, 0.0, 0.0]
        assert surface["alpha_mode"] == "cutout"
        assert surface["alpha_cutoff"] == 0.5
    assert leaf_surface_presentation("SkinnedMeshStandard", {"AlphaTest": "1"}) is None


def test_the_grass_colour_is_the_tint_and_its_alpha_the_strength() -> None:
    surface = leaf_surface_presentation("SkinnedMeshGrassLeaf", {"_grassColor": "#356e14ce", "AlphaTest": "1"})
    controls = surface["shader_controls"]
    assert controls[6] == pytest.approx(0xCE / 255)
    assert controls[7:10] == pytest.approx([0x35 / 255, 0x6E / 255, 0x14 / 255])


def test_without_the_alpha_test_permutation_nothing_is_cut() -> None:
    surface = leaf_surface_presentation("SkinnedMeshGrassLeaf", {})
    assert surface["alpha_mode"] == "opaque"
    assert surface["alpha_cutoff"] == 0.0


def test_a_leaf_batch_is_found_by_its_base_layer_wrapper() -> None:
    def parameter(owner, index, family, name, value):
        return {"component_scope_id": SCOPE, "owner_wrapper_item_id": owner, "material_wrapper_index": index,
                "shader_family": family, "parameter_name": name, "value": value}

    parameters = [
        parameter("517", 0, "SkinnedMeshTreeFrond", "AlphaTest", "1"),
        parameter("518", 1, "SkinnedMeshTreeLeaf", "AlphaTest", "1"),
        parameter("518", 1, "SkinnedMeshTreeLeaf", "_grassColor", "#6c6231e6"),
        parameter("519", 2, "SkinnedMeshStandard_Ver2", "_dyeingGlobalOpacity", "16777215"),
    ]
    batches = [
        {"index": index, "material_layers": [{"layer_role": "base", "component_scope_id": SCOPE,
                                              "owner_wrapper_item_id": owner, "material_wrapper_index": index}]}
        for index, owner in ((0, "517"), (1, "518"), (2, "519"))
    ]
    graph = {"materials": [{"lod_index": 0, "material_index": index} for index in range(3)]}
    presentations = [
        {"lod_index": 0, "material_index": index, "alpha_mode": "cutout", "alpha_cutoff": 0.08,
         "shader_controls": None, "roughness": 0.0, "metalness": 0.0}
        for index in range(3)
    ]

    _apply_preview_core_leaf_surfaces(presentations, graph, batches, parameters)

    frond, leaf, stick = presentations
    assert frond["shader_controls"][0] == 20.0
    assert frond["shader_controls"][4:6] == pytest.approx([1.0, 0.6])
    assert frond["alpha_cutoff"] == 0.5
    assert leaf["shader_controls"][4:6] == pytest.approx([1.0, 0.3])
    assert leaf["shader_controls"][6] == pytest.approx(0xE6 / 255)
    # A part of another family is left as it was.
    assert stick == {"lod_index": 0, "material_index": 2, "alpha_mode": "cutout", "alpha_cutoff": 0.08,
                     "shader_controls": None, "roughness": 0.0, "metalness": 0.0}

"""The BlendHeight families state their own layer rule on their colour rows.

SkinnedMeshBlendHeight and SkinnedMeshStaticBlendHeight (permutations
31455db8225afaa7, 0020a35384b0db70) sample a layer's maps at the mesh UV
divided by bytes 0 and 1 of its transform property, with no rotation and no
offset, and blend by height: `_detailScreenSpaceDisplacementScale` is the blend
width (at least 0.01), `_screenSpaceDisplacementScale` scales the base height.
"""

from __future__ import annotations

import pytest

from cdmw.domain.material_layer_uv import pac_blend_height_uv_transform, pac_layer_uv_transform
from cdmw.services.mesh_rust_preview_package import _preview_core_blend_height_layer

# cd_phm_02_spear_0117, wrapper cd_m0006_00_landspider_bismuthqueen_rock_0001.
SPEAR_CRYSTAL = (
    ("_dyeingPropertyBlend", "2147483647"),
    ("_dyeingTransformProperty0", "4369"),  # bytes 17, 17
    ("_dyeingTransformProperty1", "4278193164"),  # bytes 12, 12
    ("_dyeingTransformProperty3", "5140"),  # bytes 20, 20
    ("_detailScreenSpaceDisplacementScale", "0.392000"),
    ("_screenSpaceDisplacementScale", "0.168000"),
)


def test_blend_height_layers_scale_the_mesh_uv_without_turning_it() -> None:
    assert pac_blend_height_uv_transform(SPEAR_CRYSTAL, "r") == pytest.approx((15.0, 0.0, 0.0, 15.0, 0.0, 0.0))
    assert pac_blend_height_uv_transform(SPEAR_CRYSTAL, "g") == pytest.approx((21.25, 0.0, 0.0, 21.25, 0.0, 0.0))
    assert pac_blend_height_uv_transform(SPEAR_CRYSTAL, "b") == pytest.approx((12.75, 0.0, 0.0, 12.75, 0.0, 0.0))
    # U by byte 0, V by byte 1.
    assert pac_blend_height_uv_transform((("_dyeingTransformProperty0", str(0x33_0C)),), "r") == pytest.approx(
        (255 / 12, 0.0, 0.0, 5.0, 0.0, 0.0))
    # An unauthored property is scale 1.
    assert pac_blend_height_uv_transform((), "r") == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    # The Standard rule turns the same layer by _dyeingPropertyBlend: not this family's.
    assert pac_layer_uv_transform(SPEAR_CRYSTAL, "r")[0] == pytest.approx(-15.0, abs=1e-3)


def test_a_blend_height_row_carries_its_width_and_base_height_scale() -> None:
    values = {name.casefold(): value for name, value in SPEAR_CRYSTAL}
    row = {"uv_transform": [-15.0, 0.0, 0.0, -15.0, 8.0, 8.0]}
    _preview_core_blend_height_layer(row, "r", SPEAR_CRYSTAL, values)
    assert row["uv_transform"] == pytest.approx([15.0, 0.0, 0.0, 15.0, 0.0, 0.0])
    assert row["blend_height"] == pytest.approx([0.392, 0.168])
    # The material defaults: width 0 is 0.01, no base height.
    bare = {}
    _preview_core_blend_height_layer(bare, "g", (), {})
    assert bare["blend_height"] == [0.01, 0.0]
    assert bare["uv_transform"] == [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]

"""Detail layers repeat by their wrapper's Mask transform in the Mesh Editor's composed preview.

The November 2026 wedding veil moved its lace into the Ver2 detail layers:
_dyeingTransformProperty0 = 11565 (bytes 45, 45, 0, 0) and the R byte of
_dyeingPropertyBlend = 2139062016 is 0. Composed without that transform the
lace was drawn once across the whole veil instead of about 5.7 times.
"""
import math
from types import SimpleNamespace

import pytest

from cdmw.rendering.material_combiner_images import _pac_layer_sampling_transform
from cdmw.services.mesh_rust_preview_package import _preview_core_layer_uv_transform

VEIL = [{"parameter_name": "_dyeingTransformProperty0", "value": "11565", "integer_value": 11565},
        {"parameter_name": "_dyeingPropertyBlend", "value": "2139062016", "integer_value": 2139062016},
        {"parameter_name": "_netPitch", "value": "0.142000", "numeric_value": 0.142, "integer_value": None}]


def test_the_patched_veils_lace_repeats_about_five_point_seven_times_with_a_half_turn():
    scale_x, scale_y, offset_x, offset_y, angle = _preview_core_layer_uv_transform(VEIL, "r")
    assert scale_x == scale_y == pytest.approx(45 / 255)
    assert 1 / scale_x == pytest.approx(5.667, abs=0.01)
    assert (offset_x, offset_y) == (0.0, 0.0)
    assert angle == pytest.approx(-math.pi)


def test_it_matches_the_material_combiners_decoding():
    for channel, name in (("r", "_dyeingTransformProperty0"), ("g", "_dyeingTransformProperty1"), ("b", "_dyeingTransformProperty3")):
        parameters = [{"parameter_name": name, "value": "2151694377", "integer_value": 2151694377},
                      {"parameter_name": "_dyeingPropertyBlend", "value": "2139062016", "integer_value": 2139062016}]
        item = SimpleNamespace(layer_channel=channel, parameter_name=f"_detailDiffuseMask{channel.upper()}",
                               material_parameters=tuple(SimpleNamespace(parameter_name=row["parameter_name"], value=row["value"])
                                                         for row in parameters))
        assert _preview_core_layer_uv_transform(parameters, channel) == pytest.approx(list(_pac_layer_sampling_transform(item)))


@pytest.mark.parametrize("parameters, channel", [
    ([], "r"),
    ([{"parameter_name": "_dyeingTransformProperty0", "integer_value": None, "value": ""}], "r"),
    # Scale 1, offset 0 and the byte nearest zero rotation is no transform.
    ([{"parameter_name": "_dyeingTransformProperty0", "integer_value": 255 | 255 << 8},
      {"parameter_name": "_dyeingPropertyBlend", "integer_value": 128}], "r"),
    (VEIL, "a"),
    (VEIL, "g"),
])
def test_identity_or_unauthored_transforms_are_left_out(parameters, channel):
    assert _preview_core_layer_uv_transform(parameters, channel) is None


def test_the_package_graph_gives_the_detail_layer_its_wrappers_transform(tmp_path):
    from cdmw.services.mesh_rust_preview_package import _copy_preview_core_material_layers

    raw_batches = [{
        "index": 0, "material_name": "cd_phw_00_hel_00_0219",
        "material_layers": [
            {"layer_role": "base", "mask_channel": "", "owner_wrapper_item_id": "848", "material_wrapper_index": 2},
            {"layer_role": "detail", "mask_channel": "r", "owner_wrapper_item_id": "848", "material_wrapper_index": 2,
             "source_parameter": "_detailHeightMaskR", "mask_parameter": "_colorBlendingMaskTexture"},
            {"layer_role": "detail", "mask_channel": "r", "owner_wrapper_item_id": "846", "material_wrapper_index": 0,
             "source_parameter": "_detailHeightMaskR", "mask_parameter": "_colorBlendingMaskTexture"},
        ],
        # The ring's wrapper (846) authors no transform; its layer keeps the mesh UV.
        "material_inputs": [{"owner_wrapper_item_id": "848", "material_parameters": VEIL},
                            {"owner_wrapper_item_id": "846", "material_parameters": [
                                {"parameter_name": "_netPitch", "value": "0.5"}]}],
    }]
    materials = []
    _copy_preview_core_material_layers(raw_batches, tmp_path, tmp_path, "metadata", {}, 0, 0, {}, materials, 0, None, None)

    base, veil_detail, ring_detail = materials[0]["layers"]
    assert "uv_transform" not in base and "uv_transform" not in ring_detail
    assert veil_detail["uv_transform"] == pytest.approx([45 / 255, 45 / 255, 0.0, 0.0, -math.pi])

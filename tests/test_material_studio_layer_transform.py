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
from cdmw.domain.material_layer_uv import pac_layer_sampling_parameters, pac_layer_uv_transform


def _preview_core_layer_uv_transform(parameters, channel):
    """The decoded detail transform as the package step reads it (scale, offset, angle)."""
    pairs = [(row["parameter_name"], row.get("integer_value", row.get("value"))) for row in parameters]
    values = pac_layer_sampling_parameters(pairs, channel)
    return None if values is None else list(values)

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


def test_the_veil_lace_affine_repeats_it_about_five_point_seven_times():
    pairs = [(row["parameter_name"], row.get("integer_value", row.get("value"))) for row in VEIL]
    a0, a1, a2, a3, _a4, _a5 = pac_layer_uv_transform(pairs, "r")
    # A half turn: u' = -u / scale, v' = -v / scale.
    assert a0 == pytest.approx(-255 / 45) and a3 == pytest.approx(-255 / 45)
    assert a1 == pytest.approx(0.0, abs=1e-9) and a2 == pytest.approx(0.0, abs=1e-9)

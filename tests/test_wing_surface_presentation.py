"""Parts of the game's Wing shader draw with its alpha test and flow-map discard.

SkinnedMeshWing (permutation 20670511ba45c617, the only one shipped: ALPHA_TEST
is a define of the material file) is the Standard albedo path plus two
discards: base alpha under 0.5, then a cut by `_wingFlowTex1` and
`_wingFlowProgress`. No shipped wrapper sets the progress; the material's
default (-0.1) would keep 0.5% of the wing, so the preview states 2.0, where
the formula shows all of it, unless the wrapper sets its own.
"""

from __future__ import annotations

import pytest

from cdmw.services.mesh_rust_preview_package import (
    WING_DEFAULT_PROGRESS,
    _apply_preview_core_family_surfaces,
    wing_flow_discard,
    wing_surface_presentation,
)

SCOPE = "character/model/1_pc/1_phm/armor/19_cloak/cd_phm_00_cloak_0054_14.pac#model_property=0"


def test_a_wing_without_a_progress_is_drawn_whole_and_cut_at_half_alpha() -> None:
    surface = wing_surface_presentation({"_renderSettingFlag": "1"})
    controls = surface["shader_controls"]
    assert controls[0] == 1.0
    assert controls[4] == WING_DEFAULT_PROGRESS == 2.0
    assert controls[5] == 0.0
    assert controls[20] == 1.0, "rgb / a after the alpha test"
    assert surface["alpha_mode"] == "cutout"
    assert surface["alpha_cutoff"] == 0.5


def test_an_authored_progress_and_inverse_are_kept() -> None:
    controls = wing_surface_presentation({"_wingFlowProgress": "0.75", "_wingFlowInverse": "1"})["shader_controls"]
    assert controls[4] == pytest.approx(0.75)
    assert controls[5] == 1.0


def test_the_flow_map_discard_follows_the_traced_rule() -> None:
    # p = saturate(2 g - progress) * 2; the pixel goes where p exceeds the red at uv * 4.
    for red in (0.0, 0.3, 1.0):
        for blue in (0.0, 0.5, 1.0):
            assert not wing_flow_discard(red, blue, WING_DEFAULT_PROGRESS, 0.0)
    # The material default, -0.1: p is at least 0.2, so a low red goes.
    assert wing_flow_discard(0.1, 0.0, -0.1, 0.0)
    assert not wing_flow_discard(0.25, 0.0, -0.1, 0.0)
    # Blue 0.6 at progress 1: p = 0.4; inverted, g = 0.4 and p = 0.
    assert wing_flow_discard(0.3, 0.6, 1.0, 0.0)
    assert not wing_flow_discard(0.3, 0.6, 1.0, 1.0)


def test_a_wing_batch_is_found_by_its_base_layer_wrapper() -> None:
    parameters = [
        {"component_scope_id": SCOPE, "owner_wrapper_item_id": "7", "material_wrapper_index": 0,
         "shader_family": "SkinnedMeshWing", "parameter_name": "_renderSettingFlag", "value": "1"},
    ]
    batches = [{"index": 0, "material_layers": [{"layer_role": "base", "component_scope_id": SCOPE,
                                                 "owner_wrapper_item_id": "7", "material_wrapper_index": 0}]}]
    graph = {"materials": [{"lod_index": 0, "material_index": 0}]}
    presentations = [{"lod_index": 0, "material_index": 0, "alpha_mode": "opaque", "alpha_cutoff": 0.0,
                      "shader_controls": None}]
    _apply_preview_core_family_surfaces(presentations, graph, batches, parameters)
    assert presentations[0]["shader_controls"][0] == 1.0
    assert presentations[0]["alpha_cutoff"] == 0.5

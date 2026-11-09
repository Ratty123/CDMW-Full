"""Painted pins hold guides made by Create cloth guides, alone or with a height."""

import pytest

from cdmw.domain.mesh.cloth_guides import PacClothGuideRule
from cdmw.modding.pac_cloth_guide_builder import create_pac_cloth_guides
from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides
from tests.test_pac_cloth_guide_builder import PALETTE, POINTS, guide_free_pac


def fixed_points(data):
    guides = decode_pac_cloth_guides(data)
    return {guides.vertices[i] for i, value in enumerate(guides.channel_b) if value == 255}


def test_painted_pins_alone_pin_exactly_those_guides():
    rule = PacClothGuideRule(0, None, PALETTE, pinned_points=((0., 1., 0.),))
    result = create_pac_cloth_guides(guide_free_pac(lods=3), {0: rule})
    assert fixed_points(result) == {(0., 1., 0.)}


def test_painted_pins_add_to_a_height():
    rule = PacClothGuideRule(0, .5, PALETTE, pinned_points=((1., 0., 0.),))
    result = create_pac_cloth_guides(guide_free_pac(lods=3), {0: rule})
    assert fixed_points(result) == {(0., 1., 0.), (1., 1., 0.), (1., 0., 0.)}


def test_lower_source_lod_takes_the_nearest_lod0_pin():
    rule = PacClothGuideRule(2, None, PALETTE, pinned_points=((1., 1., 0.),))
    assert fixed_points(create_pac_cloth_guides(guide_free_pac(lods=3), {0: rule})) == {(1., 1., 0.)}


def test_pins_that_no_longer_line_up_are_refused():
    rule = PacClothGuideRule(0, None, PALETTE, pinned_points=((.5, .5, 0.),))
    with pytest.raises(ValueError, match="no longer line up"):
        create_pac_cloth_guides(guide_free_pac(lods=3), {0: rule})


def test_every_guide_pinned_is_refused():
    rule = PacClothGuideRule(0, None, PALETTE, pinned_points=POINTS)
    with pytest.raises(ValueError, match="both fixed and moving"):
        create_pac_cloth_guides(guide_free_pac(lods=3), {0: rule})


def test_rule_needs_an_anchor_and_round_trips_old_and_new_drafts():
    with pytest.raises(ValueError, match="by height or paint pins"):
        PacClothGuideRule(0, None, PALETTE)
    old = {"source_lod": 1, "fixed_above": .5, "bone_palette": list(PALETTE), "reduce_skinning": False}
    assert PacClothGuideRule.from_dict(old).to_dict() == old
    assert not PacClothGuideRule.from_dict(old).needs_new_draft_version
    new = PacClothGuideRule(0, None, PALETTE, pinned_points=((0., 1., 0.),))
    assert PacClothGuideRule.from_dict(new.to_dict()) == new and new.needs_new_draft_version
    for bad in ({**old, "pinned_points": []}, {**old, "pinned_points": [[0, 1]]},
                {**old, "pinned_points": [[0, float("inf"), 0]]}, {**old, "extra": 1}):
        with pytest.raises(ValueError):
            PacClothGuideRule.from_dict(bad)

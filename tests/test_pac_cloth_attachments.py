"""Cloth anchor selection from owned geometry and decoded particle channels."""

from dataclasses import replace
import json
import math

import pytest

from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides, inspect_guide_attachment_candidates
from tests.test_pac_cloth_guides import guide_fixture
from tools.pac_cloth_guide_study import main


def guides_with(positions, *, fixed=(), groups=None, triangles=()):
    guide = decode_pac_cloth_guides(guide_fixture(count=len(positions))[0])
    return replace(guide, cpu_unskinned_vertices=tuple(positions), triangles=tuple(triangles),
                   channel_a=bytes(groups or [0] * len(positions)),
                   channel_b=bytes(255 if i in fixed else 127 for i in range(len(positions))))


def test_component_path_does_not_attach_to_a_closer_disconnected_piece():
    guides = guides_with([(0, 0, 0), (10, 0, 0), (10, 1, 0),
                          (9, 0, 0), (9, 1, 0), (9, 0, 1)],
                         fixed=(0, 3), triangles=((0, 1, 2), (3, 4, 5)))
    report = inspect_guide_attachment_candidates(guides)
    assert report['component_ids'] == [0, 0, 0, 1, 1, 1]
    assert report['component_count'] == 2
    assert report['by_connected_component'][1]['guide_indices'] == [0]
    assert report['by_connected_component'][1]['rest_lengths_before_half_upload'] == [10]
    assert report['whole_mesh'][1]['guide_indices'] == [3, 0]
    assert report['whole_mesh'][1]['rest_lengths_before_half_upload'] == [1, 10]


def test_eligibility_uses_initial_mass_or_group_membership_not_fractional_blending():
    guides = guides_with([(i, 0, 0) for i in range(6)],
                         fixed=(5,), groups=[0, 1, 31, 32, 255, 255])
    report = inspect_guide_attachment_candidates(guides)
    assert report['eligible_guide_indices'] == [1, 2, 5]
    assert report['whole_mesh'][0]['guide_indices'] == [1, 2, 5]
    # An isolated eligible vertex remains its own component and can select itself.
    assert report['by_connected_component'][1]['guide_indices'] == [1]
    assert report['by_connected_component'][0]['guide_indices'] == []


def test_four_nearest_distinct_distances_keep_first_equal_distance_candidate():
    guides = guides_with([(0, 0, 0), (1, 0, 0), (-1, 0, 0),
                          (0, 2, 0), (0, 0, 3), (4, 0, 0), (5, 0, 0)],
                         fixed=(1, 2, 3, 4, 5, 6))
    row = inspect_guide_attachment_candidates(guides)['whole_mesh'][0]
    assert row['guide_indices'] == [1, 3, 4, 5]
    assert row['squared_distances'] == [1, 4, 9, 16]
    assert row['rest_lengths_before_half_upload'] == [1, 2, 3, 4]


def test_float32_distance_ties_are_not_split_by_python_double_precision():
    guides = guides_with([(0, 0, 0), (1, 0, 0), (1, 2**-13, 0)], fixed=(1, 2))
    assert 1 + (2**-13)**2 > 1
    row = inspect_guide_attachment_candidates(guides)['whole_mesh'][0]
    assert row['guide_indices'] == [1]
    assert row['squared_distances'] == [1]


def test_no_candidates_does_not_invent_height_based_anchors():
    guides = guides_with([(0, 0, 0), (0, 10, 0), (0, 20, 0)], triangles=((0, 1, 2),))
    report = inspect_guide_attachment_candidates(guides)
    assert report['eligible_guide_indices'] == []
    assert all(row['guide_indices'] == [] for row in report['whole_mesh'])


def test_report_uses_cpu_positions_or_explicit_caller_positions():
    guides = guides_with([(0, 0, 0), (2, 0, 0), (3, 0, 0)], fixed=(0,))
    original = inspect_guide_attachment_candidates(guides)
    supplied = inspect_guide_attachment_candidates(guides, particle_positions=[(0, 0, 0), (6, 0, 0), (9, 0, 0)])
    assert original['position_basis'] == 'cpu_unskinned'
    assert supplied['position_basis'] == 'caller_supplied'
    assert original['whole_mesh'][1]['rest_lengths_before_half_upload'] == [2]
    assert supplied['whole_mesh'][1]['rest_lengths_before_half_upload'] == [6]
    assert guides.cpu_unskinned_vertices[1] == (2, 0, 0)


@pytest.mark.parametrize('positions', [[], [(0, 0, 0)] * 2 + [(math.nan, 0, 0)],
                                       [(0, 0, 0)] * 2 + [(1e40, 0, 0)]])
def test_invalid_geometry_is_reported_instead_of_producing_attachments(positions):
    guides = guides_with([(0, 0, 0)] * 3, fixed=(0,))
    with pytest.raises(ValueError, match='finite'):
        inspect_guide_attachment_candidates(guides, particle_positions=positions)


def test_invalid_triangle_indices_are_not_reinterpreted_as_components():
    guides = guides_with([(0, 0, 0)] * 3, triangles=((0, 1, 3),))
    with pytest.raises(ValueError, match='triangle indices'):
        inspect_guide_attachment_candidates(guides)


def test_inspector_cli_emits_both_scenarios_and_preserves_source(tmp_path, capsys):
    source = guide_fixture()[0]
    pac = tmp_path / 'owned.pac'
    pac.write_bytes(source)
    assert main([str(pac)]) == 0
    asset = json.loads(capsys.readouterr().out)['assets'][0]
    report = asset['cloth_attachment_candidates']
    assert report['eligible_guide_indices'] == [0, 1, 2]
    assert report['component_count'] == 1
    assert report['by_connected_component'] == report['whole_mesh']
    assert 'not active runtime attachments' in report['limitations']
    assert pac.read_bytes() == source

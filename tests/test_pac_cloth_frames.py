"""Analytic result-frame cases and the prepared-guide/render handoff."""

from dataclasses import replace
import math
import struct

import pytest

from cdmw.modding.pac_cloth_frames import select_guide_result_positions, update_guide_result_frames
from cdmw.modding.pac_cloth_preparation import prepare_guide_cloth_attachments
from cdmw.modding.pac_cloth_skinning import (
    blend_render_cloth_matrix, guide_runtime_blend_factor, prepare_guide_skinning_matrices,
)
from tests.test_pac_cloth_attachments import guides_with
from tests.test_pac_cloth_skinning import IDENTITY, frame, point, record


BASIS = tuple(row[:3] for row in IDENTITY[:3])
INVALID = (65535, 65535)
ROTATE = 0x4000
SINGLE = ROTATE | 0x80000
Z90 = ((0, 1, 0), (-1, 0, 0), (0, 0, 1))


def update(animation, simulated, neighbors, *, flags=ROTATE, result=None, **overrides):
    count = len(animation)
    arguments = dict(animation_frames=tuple(frame(p) for p in animation),
                     animation_positions=animation, simulated_positions=simulated,
                     result_positions=simulated if result is None else result,
                     orientation_neighbors=neighbors, per_frame_flags=flags,
                     world_basis=BASIS, inverse_world_basis=BASIS,
                     pbd_space_offset=(0, 0, 0), runtime_blend_factors=(1.,) * count)
    arguments.update(overrides)
    return update_guide_result_frames(**arguments)


def assert_basis(frame_value, expected):
    for actual, row in zip(frame_value[:3], expected):
        assert actual[:3] == pytest.approx(row, abs=1e-7)


@pytest.mark.parametrize("flags,ratio,blend,expected", [
    (0, .25, .5, 6.5), (0x800, .25, .5, 8),
    (0, -1, 0, 2), (0, 2, -1, 6), (0, .25, 2, 10),
])
def test_output_interpolates_previous_to_simulation_then_animation(flags, ratio, blend, expected):
    result = select_guide_result_positions([(10, 0, 0)], [(2, 0, 0)], [(6, 0, 0)],
                                          per_frame_flags2=flags, interpolation_ratio=ratio,
                                          animation_blend=blend)
    assert result[0] == pytest.approx((expected, 0, 0))


def test_interpolation_bypass_uses_simulation_directly_without_subtraction_cancellation():
    result = select_guide_result_positions([(0, 0, 0)], [(1e20, 0, 0)], [(1, 0, 0)],
                                          per_frame_flags2=0x800, interpolation_ratio=0,
                                          animation_blend=0)
    assert result == ((1., 0., 0.),)


def test_rotation_disabled_preserves_basis_but_updates_position_and_metadata():
    source = ((2, 1, 0, .1), (0, 3, 0, .2), (0, 0, 4, .3), (99, 99, 99, .4))
    result = update([(0, 0, 0)], [(1, 2, 3)], [None], flags=0,
                    animation_frames=[source], pbd_space_offset=(4, 5, 6), runtime_blend_factors=[.7])
    assert_basis(result[0], [row[:3] for row in source[:3]])
    assert [row[3] for row in result[0]] == [.7, .2, .3, .4]
    assert result[0][3][:3] == (5, 7, 9)


def test_update_suppression_keeps_the_entire_frame_without_consuming_runtime_inputs():
    source = frame((10, 20, 30), .3)
    result = update([], [], [], flags=0x10000 | SINGLE, animation_frames=[source],
                    runtime_blend_factors=[], world_basis=(), inverse_world_basis=())
    assert result == (source,)


def test_two_edge_rotation_maps_animation_toward_simulation_not_the_reverse():
    animation = [(0, 0, 0), (0, 1, 0), (1, 0, 0)]
    simulated = [(0, 0, 0), (-1, 0, 0), (0, 1, 0)]
    result = update(animation, simulated, [(1, 2), INVALID, INVALID],
                    result=[(100, 200, 300), (-100, 0, 0), (0, 100, 0)])
    assert_basis(result[0], Z90)
    assert result[0][3][:3] == (100, 200, 300)


@pytest.mark.parametrize('xml,runtime,rotated', [
    ('<SimulationMode>cloth</SimulationMode>', True, True),
    ('<SimulationMode>cloth</SimulationMode>', False, False),
    ('<SimulationMode>cloth</SimulationMode><UseRotationCorrection>0</UseRotationCorrection>', True, False),
    ('<SimulationMode>spline</SimulationMode><UseRotationCorrection>1</UseRotationCorrection>', True, True),
])
def test_authored_rotation_and_cpu_runtime_gate_select_actual_frame_basis(xml, runtime, rotated):
    from cdmw.core.pbd_cloth import parse_pbd_material_settings
    from cdmw.modding.pac_cloth_runtime import update_cloth_material_frame_flags

    material = parse_pbd_material_settings('<SimulationParameters>' + xml + '</SimulationParameters>')
    data = bytearray(100)
    struct.pack_into('<I', data, 32, ROTATE)  # An old enabled frame must not keep rotation on.
    flags = update_cloth_material_frame_flags(
        data, use_rotation_correction=material.use_rotation_correction, is_cloak=material.is_cloak,
        shrink_when_shield_is_in_socket=material.shrink_when_shield_is_in_socket,
        use_input_position_collision=material.use_input_position_collision,
        rotation_correction_enabled=runtime, cloak_enabled=False,
    )
    result = update([(0, 0, 0), (0, 1, 0), (1, 0, 0)],
                    [(0, 0, 0), (-1, 0, 0), (0, 1, 0)], [(1, 2), INVALID, INVALID],
                    flags=struct.unpack_from('<I', flags['per_frame'], 32)[0])
    assert_basis(result[0], Z90 if rotated else BASIS)


def test_two_edge_compression_reduces_rotation_before_frame_construction():
    animation = [(0, 0, 0), (0, 1, 0), (1, 0, 0)]
    # Half of the shader's float32 0.8 threshold gives an exact 50/50 direction.
    compressed = .800000011920929 / 2
    simulated = [(0, 0, 0), (-compressed, 0, 0), (0, compressed, 0)]
    result = update(animation, simulated, [(1, 2), INVALID, INVALID])
    diagonal = math.sqrt(.5)
    assert_basis(result[0], ((diagonal, diagonal, 0), (-diagonal, diagonal, 0), (0, 0, 1)))


def test_rotation_respects_non_axis_aligned_animation_and_actor_space():
    # Animated neighbors form a rotated frame already. A second 90-degree turn
    # must be measured relative to that input, not the model's fixed axes.
    animation = [(0, 0, 0), (-3, 0, 0), (0, 2, 0)]
    simulated = [(0, 0, 0), (0, -3, 0), (-2, 0, 0)]
    result = update(animation, simulated, [(1, 2), INVALID, INVALID],
                    world_basis=((2, 0, 0), (0, 3, 0), (0, 0, 4)),
                    inverse_world_basis=((.5, 0, 0), (0, 1/3, 0), (0, 0, .25)),
                    result=[(2, 3, 4)] * 3, pbd_space_offset=(2, 3, 4))
    assert_basis(result[0], ((0, 2/3, 0), (-1.5, 0, 0), (0, 0, 1)))
    assert result[0][3][:3] == pytest.approx((2, 2, 2))


@pytest.mark.parametrize("second,short,expected", [(2, False, BASIS), (65535, False, Z90), (2, True, BASIS)])
def test_single_edge_prefers_second_and_only_falls_back_when_index_is_invalid(second, short, expected):
    animation = [(0, 0, 0), (-1, 0, 0), (0, -1, 0)]
    simulated = [(0, 0, 0), (0, -1, 0), (0, -.001 if short else -1, 0)]
    result = update(animation, simulated, [(1, second), INVALID, INVALID], flags=SINGLE)
    assert_basis(result[0], expected)


def test_single_edge_uses_smoothed_self_but_raw_neighbor_position():
    result = update([(0, 0, 0), (-1, 0, 0)], [(0, 0, 0), (-1, 0, 0)],
                    [(1, 65535), INVALID], flags=SINGLE, result=[(0, 1, 0), (99, 99, 99)])
    diagonal = math.sqrt(.5)
    assert_basis(result[0], ((diagonal, diagonal, 0), (-diagonal, diagonal, 0), (0, 0, 1)))


def test_single_edge_rotation_handles_a_non_axis_aligned_target():
    result = update([(0, 0, 0), (-1, 0, 0)], [(0, 0, 0), (0, -1, -1)],
                    [(1, 65535), INVALID], flags=SINGLE)
    diagonal = math.sqrt(.5)
    assert_basis(result[0], ((0, diagonal, diagonal), (-diagonal, .5, -.5), (-diagonal, -.5, .5)))


def test_single_edge_opposite_direction_uses_negative_identity():
    result = update([(0, 0, 0), (-1, 0, 0)], [(0, 0, 0), (1, 0, 0)],
                    [(1, 65535), INVALID], flags=SINGLE)
    assert_basis(result[0], ((-1, 0, 0), (0, -1, 0), (0, 0, -1)))


@pytest.mark.parametrize("flags", [ROTATE, SINGLE])
def test_invalid_neighbor_sentinels_have_defined_identity_behavior(flags):
    result = update([(0, 0, 0)], [(1, 2, 3)], [INVALID], flags=flags)
    assert_basis(result[0], BASIS)


@pytest.mark.parametrize("neighbors,animation,simulated", [
    ([None] * 3, [(0, 0, 0), (0, 1, 0), (1, 0, 0)], [(0, 0, 0), (0, 1, 0), (1, 0, 0)]),
    ([(1, 2), INVALID, INVALID], [(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 0, 0), (1, 0, 0), (2, 0, 0)]),
    ([(1, 2), INVALID, INVALID], [(0, 0, 0), (0, 1, 0), (1, 0, 0)], [(0, 0, 0)] * 3),
])
def test_unknown_or_degenerate_rotation_is_not_silently_treated_as_identity(neighbors, animation, simulated):
    with pytest.raises(ValueError, match="unknown|Degenerate"):
        update(animation, simulated, neighbors)


def test_prepared_neighbors_feed_rotated_frames_and_actual_render_binding():
    positions = ((2., 3., 0.), (2., 4., 0.), (3., 3., 0.))
    guides = replace(guides_with(positions, fixed=(0,), triangles=((0, 1, 2),)), vertices=positions)
    prepared = prepare_guide_cloth_attachments(guides, separate_components=True,
                                             use_vertex_alpha_position_blending=True,
                                             auto_weighting_enabled=False)
    simulated = tuple((7 - y, 8 + x, z) for x, y, z in positions)
    frames = update(positions, simulated, prepared['orientation_neighbor_indices'],
                    runtime_blend_factors=[guide_runtime_blend_factor(
                        inverse_mass=1., particle_flags=0x80, underwater_coefficient=.5)] * 3)
    matrices = prepare_guide_skinning_matrices(guides, frames)
    result = blend_render_cloth_matrix(record(), 0, skeletal_matrix=IDENTITY, guide_matrices=matrices)
    # A point one unit along X from guide 0 moves one unit along Y after rotation.
    assert point(result, (3, 3, 0)) == pytest.approx((4, 11, 0))
    # The row0.w factor survives rotation and preparation, then scales the
    # vertex's authored skeletal fraction in the real blending function.
    result = blend_render_cloth_matrix(record(42), 0, skeletal_matrix=IDENTITY, guide_matrices=matrices)
    assert point(result, (3, 3, 0)) == pytest.approx((11/3, 25/3, 0))


@pytest.mark.parametrize("changes", [
    {'per_frame_flags': -1}, {'orientation_neighbors': [(-1, 65535)]},
    {'orientation_neighbors': [(0, 65536)]}, {'animation_positions': []},
    {'simulated_positions': [(math.nan, 0, 0)]}, {'world_basis': ()},
    {'inverse_world_basis': ((math.inf, 0, 0),) * 3}, {'runtime_blend_factors': [1.1]},
])
def test_malformed_frame_inputs_are_rejected(changes):
    with pytest.raises(ValueError):
        update([(0, 0, 0)], [(0, 0, 0)], [INVALID], **changes)


def test_position_selection_rejects_nonfinite_blending():
    with pytest.raises(ValueError, match="finite"):
        select_guide_result_positions([], [], [], per_frame_flags2=0,
                                      interpolation_ratio=math.nan, animation_blend=0)

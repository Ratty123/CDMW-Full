"""Whole-rig pose and solver composition using parsed, owned PAB fixtures."""

import math
import struct

import pytest

from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.pac_jiggle_rig import compose_jiggle_pose, prepare_jiggle_rig, step_jiggle_rig
from cdmw.modding.pac_jiggle_skinning import blend_render_jiggle_matrix
from cdmw.modding.skeleton_parser import parse_pab
from tests.test_pab_bind_transforms import IDENTITY, fixture, translated
from tests.test_pac_jiggle_bones import character, shader


def skeleton():
    return parse_pab(fixture()[0], 'owned.pab')


def step(rig, previous=None, **changes):
    args = dict(shader_data=shader(), character_transform=character(),
                view_position=(0, 0, 0), previous_view_position=(0, 0, 0),
                bone_scale=1., character_space_scales=((1, 1, 1),) * len(rig.parents),
                update_frame_index=1, delta_time=.25, reset_requested=False)
    args.update(changes)
    return step_jiggle_rig(rig, previous, **args)


def test_unchanged_pose_is_exact_and_rig_is_detached_from_mutable_source():
    source = skeleton()
    rig = prepare_jiggle_rig(source, (1, 0))
    original = tuple(b.bind_matrix for b in source.bones)
    assert rig.bone_palette == (1, 0)
    assert compose_jiggle_pose(rig) == original
    assert compose_jiggle_pose(rig, {1: source.bones[1].local_bind_matrix}) == original
    source.bones[1].bind_matrix = (math.nan,) * 16
    assert compose_jiggle_pose(rig) == original


def test_forward_parent_reference_keeps_original_indices_for_pose_and_masks():
    source = skeleton()
    source.bones.reverse()
    source.bones[0].index, source.bones[0].parent_index = 0, 1
    source.bones[1].index, source.bones[1].parent_index = 1, -1
    rig = prepare_jiggle_rig(source, (0, 1))
    assert rig.order == (1, 0)
    moved_root = translated(source.bones[1].local_bind_matrix, 10, 21)
    poses = compose_jiggle_pose(rig, {1: moved_root})
    assert poses[0][12:15] == pytest.approx((10, 23, 0))
    assert poses[1][12:15] == pytest.approx((10, 21, 0))
    frame = step(rig, shader_data=shader(flags=2, masks=((0, .4),)), local_pose_overrides={1: moved_root})
    assert frame['skeletal_matrices'][0][1][3] == pytest.approx(.4)
    assert frame['skeletal_matrices'][1][1][3] == 0


def test_neutral_appearance_uses_original_inverse_binds_and_does_not_skin_twice():
    source = skeleton()
    appearance = NeutralMeshAppearance('owned.pabc', (1, 0),
                                       (translated(IDENTITY, 2, 0), translated(IDENTITY, 5, 1)))
    rig = prepare_jiggle_rig(source, appearance.bone_palette, appearance=appearance)
    assert rig.neutral_global_matrices[0][12:15] == (12, 20, 0)
    assert rig.neutral_global_matrices[1][12:15] == (15, 23, 0)
    assert rig.neutral_local_matrices[1][12:15] == pytest.approx((3, -3, 0))
    assert rig.inverse_bind_matrices[1] == source.bones[1].inv_bind_matrix
    frame = step(rig)

    mesh = ParsedMesh(submeshes=[SubMesh(name='owned', vertices=[(10., 22., 0.)],
                                       bone_indices=[(0, 1)], bone_weights=[(.5, .5)])])
    displayed = appearance.to_neutral(mesh)
    restored = appearance.to_source(displayed, mesh)
    assert restored.submeshes[0].vertices == mesh.submeshes[0].vertices
    data = bytearray(40)
    struct.pack_into('<I', data, 20, 1 << 10)
    data[28:30], data[39] = bytes((128, 128)), 63
    transform = blend_render_jiggle_matrix(
        data, 0, render_flags=128, bone_palette=rig.bone_palette, skinning_index_map=(0, 1),
        skeletal_matrices=frame['skeletal_matrices'], jiggle_matrices=frame['jiggle_matrices'])
    point = (*restored.submeshes[0].vertices[0], 1.)
    moved = tuple(sum(point[i] * transform[i][j] for i in range(4)) for j in range(3))
    assert moved == pytest.approx((13.5, 22.5, 0))
    assert moved == pytest.approx(displayed.submeshes[0].vertices[0])


def test_timed_effect_persists_without_reinjecting_or_moving_child_animation_targets():
    rig = prepare_jiggle_rig(skeleton(), (0, 1))
    command = bytearray(116)
    struct.pack_into('<3f', command, 48, 4., 0., 0.)
    struct.pack_into('<3fI', command, 72, 1., 2., 1., 4)
    struct.pack_into('<I', command, 108, 3)
    first = step(rig, commands={0: command})
    second = step(rig, first['bone_states'], update_frame_index=2)
    assert first['reset_bones'] == (0, 1)
    assert second['reset_bones'] == ()
    assert first['jiggle_matrices'][0][3][:3] == pytest.approx((1, 0, 0), abs=2e-5)
    assert second['jiggle_matrices'][0][3][:3] == pytest.approx((2, 0, 0), abs=2e-5)
    assert second['jiggle_matrices'][1][3][:3] == pytest.approx((0, 0, 0), abs=2e-5)
    assert struct.unpack_from('<f', second['bone_states'][0], 104)[0] == .5
    assert struct.unpack_from('<3f', second['bone_states'][0], 12) == (4, 0, 0)


@pytest.mark.parametrize('fault', ['legacy', 'partial', 'index', 'cycle', 'missing', 'inverse', 'hierarchy', 'column'])
def test_unresolved_or_inconsistent_rigs_are_rejected(fault):
    source = skeleton()
    if fault == 'legacy':
        source.parser_mode = 'legacy_scan'
    elif fault == 'partial':
        source.bone_count += 1
    elif fault == 'index':
        source.bones[1].index = 7
    elif fault == 'cycle':
        source.bones[0].parent_index = 1
    elif fault == 'missing':
        source.bones[1].local_bind_matrix = ()
    elif fault == 'inverse':
        source.bones[1].inv_bind_matrix = IDENTITY
    elif fault == 'hierarchy':
        source.bones[1].local_bind_matrix = translated(IDENTITY, 3, 0)
        source.bones[1].inv_local_bind_matrix = translated(IDENTITY, -3, 0)
    elif fault == 'column':
        old = source.bones[0].bind_matrix
        source.bones[0].bind_matrix = tuple(old[j * 4 + i] for i in range(4) for j in range(4))
    with pytest.raises(ValueError):
        prepare_jiggle_rig(source, (0, 1))


def test_palette_and_appearance_ownership_are_required():
    source = skeleton()
    for palette in ((), (2,), (True,)):
        with pytest.raises(ValueError):
            prepare_jiggle_rig(source, palette)
    for appearance in (
        NeutralMeshAppearance('wrong.pabc', (1, 0), (IDENTITY, IDENTITY)),
        NeutralMeshAppearance('partial.pabc', (0, 1), (IDENTITY,)),
        NeutralMeshAppearance('singular.pabc', (0, 1), ((0.,) * 16, IDENTITY)),
        NeutralMeshAppearance('overflow.pabc', (0, 1),
                              (translated(IDENTITY, 1e308, 0), translated(IDENTITY, -1e308, 0))),
    ):
        with pytest.raises(ValueError):
            prepare_jiggle_rig(source, (0, 1), appearance=appearance)


def test_incomplete_runtime_buffers_and_unknown_pose_or_command_indices_fail():
    rig = prepare_jiggle_rig(skeleton(), (0, 1))
    for changes in ({'previous': (bytes(116),)}, {'character_space_scales': ((1, 1, 1),)},
                    {'local_pose_overrides': {2: IDENTITY}}, {'commands': {-1: bytes(116)}},
                    {'local_pose_overrides': {0: (0.,) * 16}}):
        with pytest.raises(ValueError):
            step(rig, **changes)

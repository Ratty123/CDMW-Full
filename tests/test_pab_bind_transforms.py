"""PAB stores separate global/local bind pairs, not duplicate matrices."""

import math
import struct

import pytest

from cdmw.modding.skeleton_parser import Bone, _parse_pab_legacy_scan, parse_pab
from cdmw.modding.pac_jiggle_skinning import blend_render_jiggle_matrix, prepare_jiggle_bone_skinning
from tests.test_pac_jiggle_bones import matrix, run


IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)


def translated(matrix, x, y):
    return (*matrix[:12], x, y, 0., 1.)


def fixture():
    root = (0., 1., 0., 0., -1., 0., 0., 0., 0., 0., 1., 0., 10., 20., 0., 1.)
    root_inverse = (0., -1., 0., 0., 1., 0., 0., 0., 0., 0., 1., 0., -20., 10., 0., 1.)
    child = translated(root, 10., 22.)
    child_inverse = translated(root_inverse, -22., 10.)
    child_local = translated(IDENTITY, 2., 0.)
    child_local_inverse = translated(IDENTITY, -2., 0.)
    rows = [(b'Root', -1, root, root_inverse, root, root_inverse,
             (0., 0., math.sqrt(.5), math.sqrt(.5)), (10., 20., 0.)),
            (b'Child', 0, child, child_inverse, child_local, child_local_inverse,
             (0., 0., 0., 1.), (2., 0., 0.))]
    data = bytearray(b'PAR ' + bytes(16) + struct.pack('<H', 2))
    for index, (name, parent, global_bind, inverse_bind, local, inverse_local, rotation, position) in enumerate(rows):
        data.extend(struct.pack('<IB', 0xA2000000 + index, len(name)))
        data.extend(name)
        data.extend(struct.pack('<i64f3f4f3f', parent,
                                *global_bind, *inverse_bind, *local, *inverse_local,
                                1., 1., 1., *rotation, *position))
    return bytes(data), rows


@pytest.mark.parametrize('parser', [parse_pab, _parse_pab_legacy_scan])
def test_pab_preserves_both_bind_pairs_and_following_fields(parser):
    data, rows = fixture()
    skeleton = parser(data + b'owned-tail', 'owned.pab')
    assert len(skeleton.bones) == 2
    for bone, row in zip(skeleton.bones, rows, strict=True):
        _, parent, global_bind, inverse_bind, local, inverse_local, rotation, position = row
        assert bone.parent_index == parent
        assert bone.bind_matrix == global_bind
        assert bone.inv_bind_matrix == inverse_bind
        assert bone.local_bind_matrix == local
        assert bone.inv_local_bind_matrix == inverse_local
        assert bone.rotation == pytest.approx(rotation)
        assert bone.scale == (1., 1., 1.)
        assert bone.position == position
        if skeleton.parser_mode == 'fixed':
            assert bone.file_end - bone.file_offset == 305 + len(bone.name)
    assert skeleton.tail_offset == len(data)
    assert skeleton.tail_data == b'owned-tail'
    # Child local +X rotates into global +Y through its parent.
    child, parent = skeleton.bones[1], skeleton.bones[0]
    composed = tuple(sum(child.local_bind_matrix[row * 4 + k] * parent.bind_matrix[k * 4 + col]
                         for k in range(4)) for row in range(4) for col in range(4))
    assert composed == child.bind_matrix
    assert child.local_bind_matrix != child.bind_matrix


def test_parsed_local_hierarchy_drives_the_bone_and_vertex_reference():
    skeleton = parse_pab(fixture()[0])
    root, child = skeleton.bones
    # Move the parent +Y. The child retains its authored local offset/orientation.
    parent_pose = translated(root.bind_matrix, 10., 21.)
    pose = tuple(tuple(sum(child.local_bind_matrix[row * 4 + k] * parent_pose[k * 4 + col]
                           for k in range(4)) for col in range(4)) for row in range(4))
    step = run(None, animation_matrix=matrix(pose))
    rows = lambda flat: tuple(tuple(flat[i:i + 4]) for i in range(0, 16, 4))
    prepared = prepare_jiggle_bone_skinning(
        inverse_bind_matrix=rows(child.inv_bind_matrix), animation_matrix=rows(child.bind_matrix),
        jiggle_matrix=step['matrix'], character_space_scale=(1, 1, 1))
    data = bytearray(40)
    data[28], data[39] = 255, 63
    blended = blend_render_jiggle_matrix(
        data, 0, render_flags=128, bone_palette=(1,), skinning_index_map=(0, 0),
        skeletal_matrices=(prepared['skeletal_matrix'],), jiggle_matrices=(prepared['jiggle_matrix'],))
    point = (10., 22., 0., 1.)
    moved = tuple(sum(point[i] * blended[i][j] for i in range(4)) for j in range(3))
    assert moved == pytest.approx((10., 23., 0.))


def test_manual_bones_have_no_invented_local_transform_and_keep_positional_arguments():
    bone = Bone(7, 'Old', 123, -1, IDENTITY, IDENTITY,
                (1., 1., 1.), (0., 0., 0., 1.), (0., 0., 0.), 12, 321)
    assert (bone.file_offset, bone.file_end) == (12, 321)
    assert bone.local_bind_matrix == bone.inv_local_bind_matrix == ()

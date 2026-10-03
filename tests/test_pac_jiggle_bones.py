"""Synthetic dynamics, lifecycle and matrix cases for the decoded bone path."""

import math
import struct

import pytest

from cdmw.modding.pac_jiggle_bones import jiggle_bone_blend_override, step_jiggle_bone


IDENTITY = ((1., 0., 0., 0.), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.))
PI = 3.1415927410125732
TAU = 6.2831854820251465


def matrix(rows=IDENTITY):
    return struct.pack('<16f', *(x for row in rows for x in row))


def state(*, p=(0, 0, 0), v=(0, 0, 0), r=(0, 0, 0), rv=(0, 0, 0), flags=0, frame=0):
    result = bytearray(116)
    for offset, vector in ((0, p), (12, v), (24, r), (36, rv)):
        struct.pack_into('<3f', result, offset, *vector)
    struct.pack_into('<2I', result, 108, flags, frame)
    return result


def shader(*, settings=(0, 1, 100, 100, 0, 1, 100, 100), platform=(0, 0, 0),
           flags=0, masks=()):
    result = bytearray(264)
    struct.pack_into('<3f', result, 0, *platform)
    struct.pack_into('<8f', result, 32, *settings)
    struct.pack_into('<2I', result, 64, flags, len(masks))
    for index, (bone, weight) in enumerate(masks):
        struct.pack_into('<H', result, 72 + 2 * index, bone)
        struct.pack_into('<f', result, 136 + 4 * index, weight)
    return result


def character(*, world=IDENTITY, inverse=IDENTITY, origin=(0, 0, 0),
              old_origin=(0, 0, 0), bound_a=(0, 0, 0), bound_b=(0, 0, 0)):
    result = bytearray(272)
    result[:64] = matrix(world)
    result[192:256] = matrix(inverse)
    for offset, value in ((48, origin), (112, old_origin), (128, bound_a), (144, bound_b)):
        struct.pack_into('<3f', result, offset, *value)
    return result


def run(previous, **changes):
    args = dict(command_bone=state(), shader_data=shader(), animation_matrix=matrix(),
                character_transform=character(), view_position=(0, 0, 0), previous_view_position=(0, 0, 0),
                bone_scale=1., original_bone_index=0, update_frame_index=1, delta_time=.25,
                reset_requested=False)
    args.update(changes)
    return step_jiggle_bone(previous, **args)


def vector(result, offset):
    return struct.unpack_from('<3f', result['bone'], offset)


def assert_matrix(actual, expected):
    for row, reference in zip(actual, expected, strict=True):
        assert row == pytest.approx(reference, abs=2e-6)


def rotated(x, y, z):
    # Independent elementary row rotations: Rz * Rx * Ry.
    rx = ((1, 0, 0), (0, math.cos(x), math.sin(x)), (0, -math.sin(x), math.cos(x)))
    ry = ((math.cos(y), 0, -math.sin(y)), (0, 1, 0), (math.sin(y), 0, math.cos(y)))
    rz = ((math.cos(z), math.sin(z), 0), (-math.sin(z), math.cos(z), 0), (0, 0, 1))
    product = lambda a, b: tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3))
                                     for j in range(3)) for i in range(3))
    return tuple((*row, 0.) for row in product(product(rz, rx), ry)) + (IDENTITY[3],)


@pytest.mark.parametrize('flags,expected', [(0, (0, .25)), (1, (1, .25)),
                                          (2, (1, -.5)), (3, (1, .25)), (0x80, (0, .25))])
def test_mask_mode_and_last_duplicate_override_without_clamping(flags, expected):
    data = shader(flags=flags, masks=((4, 2.), (8, .5), (4, -.5)))
    assert jiggle_bone_blend_override(data, 4, .25) == expected

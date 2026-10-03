"""Command-to-effect transitions, fading and the two angular solver paths."""

import math
import struct

import pytest

from cdmw.modding.pac_jiggle_bones import prepare_jiggle_command
from tests.test_pac_jiggle_bones import shader, state
from tests.test_pac_jiggle_bones import IDENTITY, assert_matrix, character, matrix, rotated, run, vector


EPSILON = 9.999999747378752e-05


def command(*, velocity=(0, 0, 0), angular_velocity=(0, 0, 0), weight=1., duration=2.,
            fade_range=.5, mode=4, packed_skeleton=0, bone_index=0):
    result = bytearray(48)
    struct.pack_into('<9f3I', result, 0, *velocity, *angular_velocity, weight, duration, fade_range,
                     mode, packed_skeleton, bone_index)
    return result


def trigger(**values):
    return prepare_jiggle_command(command(**values), skeleton_data=bytes(124),
                                  object_data=bytes(128), shader_data=shader())['bone']


def continuing(*, elapsed=0., axis=(0, 0, 0), angle=0., flags=1, motion=None, **effect):
    result = state(flags=flags) if motion is None else bytearray(motion)
    result[48:88] = command(**effect)[:40]
    struct.pack_into('<5fI', result, 88, *axis, angle, elapsed, flags)
    return result


def tail(result):
    return struct.unpack_from('<5fII', result['bone'], 88)


def test_command_copies_exact_payload_into_a_cleared_record_and_uses_lod0_offset():
    payload = command(velocity=(1, 2, 3), angular_velocity=(4, 5, 6), weight=.7,
                      duration=3, fade_range=.4, mode=14, bone_index=6, packed_skeleton=0x20009)
    skeleton, obj, data = bytearray(124), bytearray(128), shader()
    struct.pack_into('<2I', skeleton, 32, 7, 99)
    struct.pack_into('<I', obj, 0, 0x101)  # LOD1 plus an unrelated high-byte flag.
    struct.pack_into('<I', data, 12, 20)
    result = prepare_jiggle_command(payload, skeleton_data=skeleton, object_data=obj, shader_data=data)
    assert result['state_index'] == 33
    assert result['bone'][:48] == bytes(48)
    assert result['bone'][48:88] == payload[:40]
    assert result['bone'][88:108] == bytes(20)
    assert struct.unpack_from('<2I', result['bone'], 108) == (3, 0)


def rodrigues_rows(axis, angle):
    # Row-vector Rodrigues formula is independent of the implementation's quaternion construction.
    x, y, z = axis
    skew = ((0, z, -y), (-z, 0, x), (y, -x, 0))
    c, s = math.cos(angle), math.sin(angle)
    return tuple(tuple(c * (i == j) + (1-c) * axis[i] * axis[j] + s * skew[i][j]
                       for j in range(3)) for i in range(3))

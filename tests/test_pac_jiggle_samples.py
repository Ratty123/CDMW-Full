"""Analytic UpdateJiggleBoneSample cases; synthetic records, no game assets."""

import math
import struct

import pytest

from cdmw.modding.pac_jiggle_samples import step_jiggle_sample
from tests.test_pac_jiggle_bones import IDENTITY


FREE = (0, 1, 100, 100, 0, 1, 100, 100)


def globals_record(*, dt=.25, cpu_mode=0, boundary=256):
    data = bytearray(224)
    struct.pack_into('<4I', data, 0, 0, boundary, 512, 512)
    struct.pack_into('<f', data, 76, 1)
    struct.pack_into('<f', data, 84, dt)
    struct.pack_into('<f', data, 104, 1)
    struct.pack_into('<I', data, 140, cpu_mode)
    struct.pack_into('<16f', data, 160, *FREE, *FREE)
    return data


def sample(*, elapsed=0., duration=2., p=(0, 0, 0), v=(0, 0, 0),
           r=(0, 0, 0), rv=(0, 0, 0), linear=(1, 0, 0, 7), angular=(0, 0, 0, 8)):
    return struct.pack('<24f', *linear, *angular, elapsed, duration, 11, 12, *p, *v, *r, *rv)


def motion(result):
    return struct.unpack_from('<12f', result['sample'], 48)


@pytest.mark.parametrize('index', [0, 255, 256, 511])
def test_both_sample_kinds_integrate_spring_velocity_twice_and_preserve_unused_cycle(index):
    source = sample(p=(1, 0, 0), v=(4, 0, 0), r=(.1, 0, 0), rv=(.5, 0, 0))
    result = step_jiggle_sample(source, global_data=globals_record(), sample_index=index)
    assert motion(result) == pytest.approx((3, 0, 0, 4, 0, 0, .35, 0, 0, .5, 0, 0))
    assert result['sample'][:32] == source[:32]
    assert result['sample'][40:48] == source[40:48]
    assert struct.unpack_from('<2f', result['sample'], 32) == (.25, 2)
    assert result['matrix_index'] == 1024 + index
    assert result['matrix'][3] == (3, 0, 0, 1)

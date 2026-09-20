"""Analytic UpdateJiggleBoneSample cases; synthetic records, no game assets."""

import math
import struct

import pytest

from cdmw.modding.pac_jiggle_samples import step_jiggle_sample
from tests.test_pac_jiggle_bones import IDENTITY
from tests.test_pac_jiggle_skinning import blend, record


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


def test_cpu_mode_preserves_state_but_still_emits_its_transform():
    source = sample(p=(2, 3, 4), v=(10, 20, 30), r=(0, 0, math.pi / 2), rv=(4, 5, 6))
    result = step_jiggle_sample(source, global_data=globals_record(dt=math.nan, cpu_mode=9), sample_index=511)
    assert result['sample'] == source
    assert result['matrix'][0] == pytest.approx((0, 1, 0, 0), abs=1e-7)
    assert result['matrix'][1] == pytest.approx((-1, 0, 0, 0), abs=1e-7)
    assert result['matrix'][3] == (2, 3, 4, 1)


def test_runtime_boundary_selects_separate_water_settings():
    data = globals_record(boundary=10)
    struct.pack_into('<f', data, 196, .5)  # Water linear damping, not wind damping.
    wind = step_jiggle_sample(sample(v=(4, 0, 0)), global_data=data, sample_index=9)
    water = step_jiggle_sample(sample(v=(4, 0, 0)), global_data=data, sample_index=10)
    assert motion(wind)[:6] == (2, 0, 0, 4, 0, 0)
    assert motion(water)[:6] == (1, 0, 0, 2, 0, 0)


@pytest.mark.parametrize('elapsed,sign', [(0., 1), (.5, -1), (.75, -1)])
def test_wind_uses_perturbed_direction_and_strict_positive_cycle_sign(elapsed, sign):
    data = globals_record()
    struct.pack_into('<3f', data, 16, 1, 0, 0)
    struct.pack_into('<3f', data, 32, 0, 2, 0)
    struct.pack_into('<2f', data, 48, 2, .5)
    struct.pack_into('<3f', data, 64, 1, 0, 4)
    # These reflected fields are upstream inputs, not reread by this shader.
    struct.pack_into('<f', data, 56, 999)
    struct.pack_into('<3f', data, 88, -8, -9, -10)
    result = step_jiggle_sample(sample(elapsed=elapsed, duration=1), global_data=data, sample_index=0)
    assert motion(result) == pytest.approx((.25, 0, 0, 1, 0, 0, 0, sign * .0625, 0, 0, sign * .25, 0))


def test_environment_is_applied_after_caps_without_a_second_cap():
    data = globals_record()
    struct.pack_into('<8f', data, 160, 0, 1, 1, .2, 0, 1, 1, .2)
    struct.pack_into('<3f', data, 16, 1, 0, 0)
    struct.pack_into('<3f', data, 32, 4, 0, 0)
    struct.pack_into('<2f', data, 48, 1, 1)
    struct.pack_into('<3f', data, 64, 1, 0, 16)
    result = step_jiggle_sample(sample(v=(4, 0, 0), rv=(4, 0, 0)), global_data=data, sample_index=0)
    assert motion(result) == pytest.approx((1.45, 0, 0, 5, 0, 0, .7, 0, 0, 2, 0, 0))


def test_water_uses_retained_cycle_vectors_between_rollovers():
    data = globals_record()
    struct.pack_into('<f', data, 108, 4)
    source = sample(linear=(0, 0, 2, 7), angular=(1, 2, 3, 8))
    result = step_jiggle_sample(source, global_data=data, sample_index=256)
    assert motion(result) == pytest.approx((0, 0, .5, 0, 0, 2, .25, .5, .75, 1, 2, 3))
    assert result['sample'][:32] == source[:32]


def test_water_rollover_rotates_previous_direction_and_advances_the_random_sequence():
    data = globals_record()
    struct.pack_into('<2f', data, 104, .5, 4)
    struct.pack_into('<4f', data, 112, 1, 0, .2, .4)
    struct.pack_into('<f', data, 132, 2)
    source = sample(elapsed=1, duration=1, angular=(1, 2, 3, 8))
    result = step_jiggle_sample(source, global_data=data, sample_index=256)
    # Seed zero's first five integer outputs are 15476,12300,26597,16941,17880.
    # Duration consumes the first; yaw/pitch and angular X/Y consume the rest.
    direction = (math.cos(.24922174215316772), 0, math.sin(.24922174215316772))
    angular = (.006811928749084473, .03655009269714356, 0)
    values = struct.unpack('<24f', result['sample'])
    assert values[:4] == pytest.approx((*direction, 7))
    assert values[4:8] == pytest.approx((*angular, 0))
    assert values[8:12] == pytest.approx((0, .9723188877105713, 11, 12))
    assert values[12:18] == pytest.approx((*[x * .25 for x in direction], *direction))
    assert values[18:24] == pytest.approx((*[x * .25 for x in angular], *angular))


@pytest.mark.parametrize('index', [0, 256])
def test_cycle_rollover_has_a_minimum_duration_and_discards_overshoot(index):
    data = globals_record(dt=1)
    struct.pack_into('<f', data, 76, 0)
    struct.pack_into('<f', data, 104, -1)
    result = step_jiggle_sample(sample(elapsed=.5, duration=.6), global_data=data, sample_index=index)
    assert struct.unpack_from('<2f', result['sample'], 32) == pytest.approx((0, .0333000011742115))


def test_generated_wind_matrix_reaches_the_existing_vertex_blend():
    data = globals_record()
    struct.pack_into('<3f', data, 16, 1, 0, 0)
    struct.pack_into('<2f', data, 48, 1, 1)
    struct.pack_into('<3f', data, 64, 1, 0, 4)
    result = step_jiggle_sample(sample(), global_data=data, sample_index=0)
    matrix = blend(record(jiggle=9), jiggle_matrices=(IDENTITY,), wind_weight=1,
                   wind_samples=(IDENTITY,) * result['matrix_index'] + (result['matrix'],))
    # Byte 38 low nibble 9 contributes 0.4 of the generated 0.25 translation.
    assert matrix[3] == pytest.approx((.1, 0, 0, 1))


def test_unsupported_records_indices_and_consumed_nonfinite_values_are_rejected():
    data = globals_record()
    with pytest.raises(ValueError, match='96-byte'):
        step_jiggle_sample(bytes(95), global_data=data, sample_index=0)
    with pytest.raises(ValueError, match='224-byte'):
        step_jiggle_sample(sample(), global_data=bytes(340), sample_index=0)
    with pytest.raises(ValueError, match='0..511'):
        step_jiggle_sample(sample(), global_data=data, sample_index=512)
    with pytest.raises(ValueError, match='nonnegative'):
        step_jiggle_sample(sample(), global_data=globals_record(dt=-1), sample_index=0)
    with pytest.raises(ValueError, match='finite'):
        step_jiggle_sample(sample(), global_data=globals_record(dt=math.nan), sample_index=0)

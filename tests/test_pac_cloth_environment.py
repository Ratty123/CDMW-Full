"""Analytic wind, water, surface-response and force-integration scenarios."""

import math
import struct

import pytest

from cdmw.modding.pac_cloth_base import integrate_cloth_forces, predict_cloth_position
from cdmw.modding.pac_cloth_environment import cloth_environment_acceleration
from cdmw.modding.pac_cloth_movement import finalize_cloth_motion


def runtime(*, flags=0, flags2=0, guide=True, mass=1., bone=(2, 0, 0), frame_wind=(0, 0, 0),
            response=1., resistance=1., wind_scale=None, extra_flags=0, phase=0., amplitude=0.,
            water=(0, 0, 0), viscosity=.5, drag=.25, shallow_scale=0., turbulence_scale=2.,
            neighbors=(0xFFFF, 0xFFFF), head=(5, 0, 0), ground_height=0.):
    particle, frame, scene, parameter = bytearray(152), bytearray(100), bytearray(108), bytearray(312)
    struct.pack_into('<f', particle, 60, mass)
    struct.pack_into('<2H', particle, 112, *neighbors)
    struct.pack_into('<I', frame, 32, flags)
    struct.pack_into('<I', frame, 36, flags2)
    struct.pack_into('<f', frame, 24, ground_height)
    struct.pack_into('<3e', frame, 48, *frame_wind)
    struct.pack_into('<e', frame, 54, 100.)
    struct.pack_into('<3e', frame, 56, *bone)
    struct.pack_into('<e', frame, 64, phase)
    struct.pack_into('<3f', scene, 16, *head)
    struct.pack_into('<3f', scene, 28, *water)
    struct.pack_into('<e', scene, 94, 1.)
    struct.pack_into('<H', parameter, 216, 0xFFFF if guide else 0)
    struct.pack_into('<H', parameter, 236, 3)
    struct.pack_into('<e', parameter, 268, response)
    struct.pack_into('<e', parameter, 280, resistance)
    struct.pack_into('<e', parameter, 284, amplitude)
    struct.pack_into('<4e', parameter, 288, turbulence_scale, viscosity, drag, shallow_scale)
    extra = None
    if wind_scale is not None or extra_flags:
        extra = bytearray(28)
        struct.pack_into('<H', extra, 0, extra_flags)
        struct.pack_into('<e', extra, 20, 1. if wind_scale is None else wind_scale)
    return particle, dict(per_frame=frame, per_scene=scene, simulation_parameter=parameter, particle_extra=extra)


def environment(*, settings=None, **changes):
    particle, records = runtime(**(settings or {}))
    arguments = dict(working_position=(0, 0, 0), velocity_after_inertia=(0, 0, 0),
                     particle_positions=((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                     underwater=False, head_underwater=True, sampled_voxel_wind=None, sky_visibility=None,
                     sampled_shallow_water_velocity=None, turbulence_sample=None,
                     apply_sky_visibility_to_voxel_wind=False, acceleration_limit=100.)
    arguments.update(records)
    arguments.update(changes)
    return cloth_environment_acceleration(particle, **arguments)


def wind(*, settings=None, **changes):
    options = dict(bone=(0, 0, 0), flags2=8, frame_wind=(4, 0, 0))
    options.update(settings or {})
    values = dict(sampled_voxel_wind=(0, 0, 0), sky_visibility=1.)
    values.update(changes)
    return environment(settings=options, **values)


def test_air_resistance_uses_relative_velocity_even_when_wind_is_disabled():
    assert environment() == (-4., 0., 0.)
    speed = math.sqrt(41.)
    assert environment(settings={'flags': 0x40000000}, velocity_after_inertia=(3, 4, 0)) == pytest.approx((-5*speed, -4*speed, 0.))
    assert environment(settings={'frame_wind': (100, 100, 100), 'wind_scale': 0.},
                       sampled_voxel_wind=(100, 100, 100), sky_visibility=1.) == (-4., 0., 0.)


def test_voxel_response_precedes_speed_squared_and_uses_separate_sky_switch():
    settings = dict(response=2., frame_wind=(3, 0, 0), wind_scale=2., mass=2.)
    assert wind(settings=settings, sampled_voxel_wind=(1, 0, 0), sky_visibility=.5) == (22., 0., 0.)
    assert wind(settings=settings, sampled_voxel_wind=(1, 0, 0), sky_visibility=.5,
                apply_sky_visibility_to_voxel_wind=True) == (14., 0., 0.)


@pytest.mark.parametrize('visibility,expected', [
    (-1., 0.), (.05, 0.), (.10000000149011612, .4000000059604645),
    (.5, 2.), (.800000011920929, 4.), (2., 4.),
])
def test_guide_frame_wind_has_low_and_high_sky_thresholds(visibility, expected):
    assert wind(sky_visibility=visibility) == pytest.approx((expected, 0, 0))


def test_static_frame_wind_does_not_use_guide_sky_thresholds():
    assert wind(settings={'guide': False}, sky_visibility=0.) == (4., 0., 0.)


def test_central_wind_mask_removes_inward_force_and_attenuates_other_directions():
    settings = dict(flags2=0x18, frame_wind=(-10, 0, 0))
    assert wind(settings=settings, working_position=(1, 0, 0)) == pytest.approx((0, 0, 0), abs=1e-10)
    settings['frame_wind'] = (10, 0, 0)
    assert wind(settings=settings, working_position=(1, 0, 0)) == pytest.approx((4, 0, 0))
    settings['head'] = (0, 0, 0)
    assert wind(settings=settings, working_position=(1, 0, 0)) == (10., 0., 0.)
    settings['guide'] = False  # Static path uses radius 5 regardless of the head offset.
    assert wind(settings=settings, working_position=(1, 0, 0)) == pytest.approx((4, 0, 0))


def test_acceleration_cap_precedes_surface_response_using_particle_p1():
    positions = ((0, 0, 0), (0, 1, 0), (math.sqrt(.75), 0, -.5))
    # Triangle normal has |dot(n, +X)|=.5. Cap 10 to4, THEN multiply by.5.
    # The working position is deliberately different from the raw p[1] origin.
    result = wind(settings={'neighbors': (1, 2), 'frame_wind': (10, 0, 0)},
                  particle_positions=positions, working_position=(100, 0, 0), acceleration_limit=4.)
    assert result == pytest.approx((2., 0., 0.))


def test_single_edge_response_and_extra_flag_choose_different_formulations():
    positions = ((0, 0, 0), (1, 1, 0), (0, 0, 1))
    options = dict(flags=0x80000, neighbors=(1, 2))
    assert wind(settings=options, particle_positions=positions) == pytest.approx((4*(1-1/math.sqrt(2)), 0, 0))
    options['extra_flags'] = 4
    assert wind(settings=options, particle_positions=positions) == pytest.approx((4/math.sqrt(2), 0, 0))


@pytest.mark.parametrize('flags,neighbors,positions,expected', [
    (0x80000, (0xFFFF, 1), ((0, 0, 0), (1, 0, 0), (0, 1, 0)), 4.),
    (0x80000, (1, 0xFFFF), ((0, 0, 0), (1, 0, 0), (0, 1, 0)), 0.),
    (0x80000, (1, 0xFFFF), ((0, 0, 0), (0, 0, 0), (0, 1, 0)), 4.),
    (0, (1, 2), ((0, 0, 0), (1, 0, 0), (2, 0, 0)), 0.),
])
def test_invalid_neighbors_and_degenerate_edges_follow_distinct_branches(flags, neighbors, positions, expected):
    assert wind(settings={'flags': flags, 'neighbors': neighbors}, particle_positions=positions) == (expected, 0., 0.)


def test_wave_uses_working_position_plus_phase_and_saturates_amplitude():
    assert wind(settings={'phase': .25, 'amplitude': 1.}) == pytest.approx((2., 0, 0), abs=6e-6)
    assert wind(settings={'phase': .25, 'amplitude': 2.}, working_position=(0, 0, .25)) == pytest.approx((0, 0, 0), abs=1e-10)
    assert wind(settings={'phase': .5, 'amplitude': -1.}) == (4., 0., 0.)


def test_water_drag_combines_capped_quadratic_and_uncapped_linear_terms():
    settings = dict(bone=(0, 0, 0), mass=2., viscosity=.25, drag=.5)
    assert environment(settings=settings, underwater=True, velocity_after_inertia=(3, 0, 4)) == (-16.5, 0., -22.)
    settings['flags'] = 0x20000000
    assert environment(settings=settings, underwater=True, velocity_after_inertia=(3, 0, 4)) == pytest.approx((-3.9, 0., -5.2))


def test_water_flow_uses_half_scene_velocity_and_optional_horizontal_shallow_sample():
    settings = dict(bone=(4, 1, 2), water=(4, 4, 2), viscosity=1., drag=0., shallow_scale=2.)
    values = dict(underwater=True, velocity_after_inertia=(1, 1, 1), sampled_shallow_water_velocity=(1, -1))
    assert environment(settings=settings, **values) == (-3., 0., -2.)
    assert environment(settings=settings, **values, head_underwater=False) == (-1., 0., -4.)


def test_water_dead_zone_precedes_turbulence():
    settings = dict(bone=(0, 0, 0), viscosity=1., drag=0.)
    assert environment(settings=settings, underwater=True, velocity_after_inertia=(.25, 0, 0)) == (0., 0., 0.)
    settings['flags2'] = 0x4000
    assert environment(settings=settings, underwater=True, velocity_after_inertia=(.25, 0, 0),
                       turbulence_sample=.25) == (-.25, -.25, -.25)


def test_dry_turbulence_is_scaled_by_bone_speed_and_can_suppress_vertical_perturbation():
    settings = dict(bone=(1, 0, 0), flags2=0x4000)
    speed = math.sqrt(2.5**2 + 1.5**2 + 1.5**2)
    assert environment(settings=settings, turbulence_sample=.5) == pytest.approx((-2.5*speed, -1.5*speed, -1.5*speed))
    settings['ground_height'] = -501.
    noise = 10. / math.sqrt(3.)
    speed = math.hypot(1. + noise, noise)
    assert environment(settings=settings, turbulence_sample=10.) == pytest.approx((-(1+noise)*speed, 0, -noise*speed))


def test_resolved_environment_connects_inertia_to_prediction_and_final_velocity():
    particle, records = runtime(flags=0x40000000, bone=(1, 0, 0), resistance=.25)
    common = dict(gravity_direction=(0, -1, 0), gravity=0., delta_time=.5, inverse_mass=1., underwater=False,
                  underwater_density=1., bone_acceleration=(2, 0, 0), inertial_scale=1., inertial_acceleration_limit=10.,
                  skip_external_forces=False)
    before_environment = integrate_cloth_forces((0, 0, 0), environmental_acceleration=(0, 0, 0), **common)
    # Air drag must observe the velocity AFTER this step's inertia: relative=-2X,
    # giving -.25*2*2=-1X acceleration. Using the old velocity would give -.25X.
    resolved = environment(settings={'flags': 0x40000000, 'bone': (1, 0, 0), 'resistance': .25},
                           velocity_after_inertia=before_environment['velocity'])
    assert resolved == (-1., 0., 0.)
    integrated = integrate_cloth_forces((0, 0, 0), environmental_acceleration=resolved, **common)
    predicted = predict_cloth_position((0, 0, 0), integrated['velocity'], delta_time=.5,
                                      gravity_direction=(0, -1, 0), ground_height=-10., ground_thickness=0.,
                                      ground_collision_enabled=True)
    result = finalize_cloth_motion(
        predicted['position'], animation_position=(0, 0, 0), previous_position=(0, 0, 0),
        velocity_reference_position=(0, 0, 0), attachment_correction=(0, 0, 0), animation_blend=0.,
        inverse_mass=1., particle_flags=0, per_frame=records['per_frame'], per_scene=records['per_scene'],
        simulation_parameter=records['simulation_parameter'], fixed_substep_delta_time=.5,
        variable_substep_delta_time=.5, minimum_velocity_delta_time=.01)
    assert result['position'] == (.25, 0., 0.)
    assert result['velocity'] == (.5, 0., 0.)


@pytest.mark.parametrize('changes,match', [
    ({'settings': {'flags2': 8}}, 'voxel-wind'),
    ({'settings': {'flags2': 8}, 'sampled_voxel_wind': (0, 0, 0)}, 'sky-visibility'),
    ({'settings': {'flags2': 0x4000}}, 'procedural-noise'),
    ({'settings': {'shallow_scale': 1.}, 'underwater': True, 'head_underwater': False}, 'shallow-water'),
    ({'settings': {'flags2': 0x4000, 'bone': (0, 0, 0)}, 'turbulence_sample': .5}, 'zero perturbation'),
    ({'settings': {'bone': (0, 1, 0)}}, 'horizontal-wave'),
    ({'particle_positions': ()}, 'particle-position count'),
    ({'acceleration_limit': 0.}, 'positive acceleration cap'),
])
def test_missing_active_samples_and_unsupported_math_are_rejected(changes, match):
    with pytest.raises(ValueError, match=match):
        environment(**changes)

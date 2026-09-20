"""Analytic volume, contact-plane and friction cases for decoded cloth geometry."""

import math
import struct

import pytest

from cdmw.modding.pac_cloth_collisions import (
    cloth_collider_contact_surface, cloth_collider_proximity_distance,
    project_static_cloth_collider, resolve_cloth_moving_contact,
)


def distance(kind, point, **changes):
    options = dict(collider_type=kind, center1=(0., 0., 0.), center2=(0., 4., 0.), radius=1.)
    options.update(changes)
    return cloth_collider_proximity_distance(point, **options)


def surface(kind, point, **changes):
    options = dict(collider_type=kind, center1=(0., 0., 0.), center2=(0., 4., 0.), radius=1., thickness=0.)
    options.update(changes)
    return cloth_collider_contact_surface(point, **options)


@pytest.mark.parametrize('kind,point,expected', [
    (1, (0., 0., 0.), -1.), (1, (2., 0., 0.), 1.), (1, (0., 4., 0.), 3.),
    (3, (0., 2., 0.), -1.), (3, (.5, 2., 0.), -.5), (3, (0., .25, 0.), -.25),
    (3, (0., 0., 0.), 0.), (3, (2., 2., 0.), 1.), (3, (0., 5., 0.), 1.),
    (3, (2., 5., 0.), math.sqrt(2)), (3, (.5, 0., 0.), 0.),
    (5, (0., 2., 0.), -1.), (5, (.5, 2., 0.), -.5), (5, (0., -2., 0.), 1.),
    (5, (0., 5., 0.), 0.), (5, (2., 5., 0.), math.sqrt(5) - 1), (5, (0., 0., 0.), -1.),
])
def test_proximity_is_signed_distance_to_the_decoded_volume(kind, point, expected):
    assert distance(kind, point) == pytest.approx(expected)


@pytest.mark.parametrize('kind,point', [(1, (1.2, .9, .5)), (3, (1.2, 2., .5)), (5, (1.2, 2., .5))])
def test_smooth_surface_normals_match_independent_finite_difference_distance_gradients(kind, point):
    _, normal = surface(kind, point)
    gradient = []
    for axis in range(3):
        plus, minus = list(point), list(point)
        plus[axis] += 1e-5
        minus[axis] -= 1e-5
        gradient.append((distance(kind, plus) - distance(kind, minus))/2e-5)
    assert normal == pytest.approx(gradient, abs=1e-8)


def test_sphere_surface_expands_radius_and_does_not_consume_a_second_center():
    point, normal = surface(1, (3., 4., 0.), center2=None, radius=2., thickness=.5)
    assert point == pytest.approx((1.5, 2., 0.))
    assert normal == pytest.approx((.6, .8, 0.))
    assert distance(1, (3., 4., 0.), center2=None, radius=2.) == 3.


@pytest.mark.parametrize('point,expected_point,expected_normal', [
    ((.5, 2., 0.), (1., 2., 0.), (1., 0., 0.)),
    ((.25, 3.75, 0.), (.25, 4., 0.), (0., 1., 0.)),
    ((.5, 3.5, 0.), (.5, 4., 0.), (0., 1., 0.)),  # Exact band boundary and side/cap tie.
    ((.75, 3.75, 0.), (.75, 4., 0.), (2**-.5, 2**-.5, 0.)),
    ((.75, .25, 0.), (.75, 0., 0.), (2**-.5, -2**-.5, 0.)),
    ((1.5, 4.25, 0.), (1., 4.25, 0.), (.8, .6, 0.)),  # Selected side point stays above cap.
    ((0., 3.75, 0.), (0., 4., 0.), (0., 1., 0.)),  # Unused radial normalization is singular.
])
def test_cylinder_selected_surface_and_edge_normal_blend_are_distinct(point, expected_point, expected_normal):
    result, normal = surface(3, point)
    assert result == pytest.approx(expected_point)
    assert normal == pytest.approx(expected_normal)


def test_cylinder_thickness_expands_both_ends_and_radius_and_can_shrink():
    assert surface(3, (.5, 2., 0.), thickness=.25)[0] == (1.25, 2., 0.)
    assert surface(3, (.25, 4.1, 0.), thickness=.25)[0] == pytest.approx((.25, 4.25, 0.))
    assert surface(3, (.5, 2., 0.), thickness=-.25)[0] == (.75, 2., 0.)
    with pytest.raises(ValueError, match='Degenerate'):
        surface(3, (.5, 2., 0.), thickness=-2.)


@pytest.mark.parametrize('point,expected_point,normal', [
    ((2., 2., 0.), (1.25, 2., 0.), (1., 0., 0.)),
    ((0., -2., 0.), (0., -1.25, 0.), (0., -1., 0.)),
    ((0., 6., 0.), (0., 5.25, 0.), (0., 1., 0.)),
    ((2., 0., 0.), (1.25, 0., 0.), (1., 0., 0.)),
    ((2., 4., 0.), (1.25, 4., 0.), (1., 0., 0.)),
])
def test_capsule_uses_side_and_spherical_end_surfaces(point, expected_point, normal):
    assert surface(5, point, thickness=.25) == (expected_point, normal)


def test_short_capsule_surface_fallback_is_strict_and_absent_from_proximity_query():
    epsilon = struct.unpack('<f', struct.pack('<f', 1e-6))[0]
    p, n = surface(5, (1., epsilon, 0.), center2=(0., epsilon, 0.), radius=2.)
    assert p == (2., epsilon, 0.) and n == (1., 0., 0.)
    p, n = surface(5, (1., epsilon, 0.), center2=(0., epsilon*.5, 0.), radius=2.)
    assert p[1] == pytest.approx(2*epsilon, abs=1e-15)
    assert n[1] == pytest.approx(epsilon, abs=1e-15)
    assert surface(5, (2., 0., 0.), center2=(0., 0., 0.))[0] == (1., 0., 0.)
    with pytest.raises(ValueError, match='Degenerate proximity'):
        distance(5, (2., 0., 0.), center2=(0., 0., 0.))


@pytest.mark.parametrize('kind', [1, 3, 5])
def test_volume_and_surface_follow_rotation_and_translation(kind):
    def transform(point, translate=True):
        x, y, z = point
        return (y + (10 if translate else 0), -x + (20 if translate else 0), z + (-30 if translate else 0))
    point = (1.2, 2., .3)
    a, b = transform((0., 0., 0.)), transform((0., 4., 0.))
    assert distance(kind, transform(point), center1=a, center2=b) == pytest.approx(distance(kind, point))
    projected, normal = surface(kind, point)
    transformed, rotated_normal = surface(kind, transform(point), center1=a, center2=b)
    assert transformed == pytest.approx(transform(projected))
    assert rotated_normal == pytest.approx(transform(normal, False))


@pytest.mark.parametrize('kind', [0, 2, 4, 0xFFFF])
def test_unhandled_shapes_retain_the_specific_prepass_and_response_sentinels(kind):
    assert distance(kind, None, center1=None, center2=None, radius=float('nan')) == 1000.
    assert surface(kind, None, center1=None, center2=None, radius=float('nan')) == ((0., 0., 0.), (0., 0., 0.))


def moving(target, reference=(0., 1., 0.), *, damping=True, displacement=(0., 0., 0.)):
    return resolve_cloth_moving_contact(target, reference, surface_position=(0., 0., 0.),
                                        surface_normal=(0., 1., 0.), collider_displacement=displacement,
                                        apply_tangential_damping=damping)


def test_moving_contact_uses_relative_motion_and_only_applies_requested_tangent_damping():
    assert moving((2., -.5, 0.), damping=False) == {'position': (2., 0., 0.), 'contact': True}
    assert moving((2., -.5, 0.))['position'] == pytest.approx((1.7, 0., 0.))
    assert moving((2., -.5, 0.), displacement=(1., -.5, 0.))['position'] == pytest.approx((1.775, 0., 0.))
    assert moving((2., -.5, 0.), reference=(0., -.5, 0.))['position'] == pytest.approx((1.1, 0., 0.))
    assert moving((2., 0., 0.)) == {'position': (2., 0., 0.), 'contact': False}
    assert moving((2., .25, 0.)) == {'position': (2., .25, 0.), 'contact': False}


def test_surface_composes_with_moving_contact_using_reference_not_target_direction():
    point, normal = surface(1, (2., 0., 0.))
    result = resolve_cloth_moving_contact((.5, .25, 0.), (2., 0., 0.), surface_position=point,
                                          surface_normal=normal, collider_displacement=(0., 0., 0.),
                                          apply_tangential_damping=True)
    assert result['contact']
    assert result['position'] == pytest.approx((1., .2125, 0.))


def records(kind=1, static=.5, kinetic=.25):
    definition, group = bytearray(range(104)), bytearray(range(16))
    struct.pack_into('<Hf', definition, 2, kind, 1.)
    struct.pack_into('<6f', definition, 76, 0., 0., 0., 0., 4., 0.)
    struct.pack_into('<2e', group, 4, static, kinetic)
    return definition, group


def static_project(target, *, kind=1, static=.5, kinetic=.25, reference=(2., 0., 0.), data=None, **changes):
    data = records(kind, static, kinetic) if data is None else data
    options = dict(translation_to_collider_space=(0., 0., 0.), collision_thickness=0.)
    options.update(changes)
    return project_static_cloth_collider(target, reference, *data, **options)


@pytest.mark.parametrize('target,static,kinetic,expected', [
    ((.5, .2, 0.), .5, .25, (1., 0., 0.)),
    ((.5, .25, 0.), .5, .25, (1., 0., 0.)),  # Static friction includes equality.
    ((.5, 1., 0.), .5, .25, (1., .875, 0.)),
    ((.5, 1., 0.), .125, .75, (1., .9375, 0.)),  # Kinetic coefficient capped by active static.
    ((.5, 1., 0.), 0., .5, (1., .75, 0.)),
    ((.5, .1, 0.), 0., 4., (1., 0., 0.)),  # Tangent correction cannot exceed tangent length.
    ((.5, 1., 0.), -.5, -.25, (1., 1., 0.)),
    ((.5, 1., 0.), .0009, .0009, (1., 1., 0.)),
    ((.5, 1e-7, 0.), .5, .25, (1., 1e-7, 0.)),
])
def test_static_contact_preserves_separate_static_and_kinetic_friction_rules(target, static, kinetic, expected):
    result = static_project(target, static=static, kinetic=kinetic)
    assert result['contact']
    assert result['position'] == pytest.approx(expected)


def test_attached_static_colliders_use_local_centers_translation_and_preserve_records():
    data = records()
    struct.pack_into('<3f', data[0], 76, 10., 20., 30.)
    before = tuple(bytes(x) for x in data)
    result = static_project((.5, .2, 0.), data=data, translation_to_collider_space=(10., 20., 30.))
    assert result == {'position': (1., 0., 0.), 'contact': True}
    assert tuple(bytes(x) for x in data) == before
    assert not static_project((1., 1., 0.))['contact']


def test_static_plane_uses_raw_normal_and_bypasses_radius_and_friction():
    data = records(kind=4, static=float('nan'), kinetic=float('nan'))
    struct.pack_into('<f', data[0], 4, float('nan'))
    struct.pack_into('<6f', data[0], 76, 10., 20., 30., 0., 2., 0.)
    options = dict(data=data, translation_to_collider_space=(10., 20., 30.), collision_thickness=.5)
    assert static_project((3., -1., 5.), **options) == {'position': (3., 4., 5.), 'contact': True}
    assert static_project((3., .25, 5.), **options) == {'position': (3., .25, 5.), 'contact': False}
    struct.pack_into('<3f', data[0], 88, 0., 0., 0.)
    assert static_project((3., -1., 5.), **options) == {'position': (3., -1., 5.), 'contact': True}


@pytest.mark.parametrize('kind,reference,target,expected', [
    (3, (2., 2., 0.), (.5, 2.25, 0.), (1., 2., 0.)),
    (5, (0., 6., 0.), (.25, 4.5, 0.), (0., 5., 0.)),
    (2, (2., 0., 0.), (.5, .2, 0.), (.5, .2, 0.)),
])
def test_static_cylinder_capsule_and_unhandled_type_compose_with_response(kind, reference, target, expected):
    result = static_project(target, kind=kind, reference=reference)
    assert result['position'] == pytest.approx(expected)
    assert result['contact'] is (kind != 2)


def test_undefined_geometry_missing_centers_and_invalid_consumed_inputs_are_rejected():
    for kind, point in ((1, (0., 0., 0.)), (3, (0., 2., 0.)), (5, (0., 2., 0.))):
        with pytest.raises(ValueError, match='Degenerate'):
            surface(kind, point)
    with pytest.raises(ValueError, match='second center'):
        surface(3, (1., 2., 0.), center2=None)
    with pytest.raises(ValueError, match='second center'):
        distance(5, (1., 2., 0.), center2=None)
    with pytest.raises(ValueError, match='unsigned 16-bit'):
        surface(True, (1., 2., 0.))
    with pytest.raises(ValueError, match='finite'):
        surface(1, (1., 0., 0.), radius=float('nan'))
    data = records()
    with pytest.raises(ValueError, match='104-byte'):
        static_project((.5, 1., 0.), data=(data[0][:-1], data[1]))
    with pytest.raises(ValueError, match='16-byte'):
        static_project((.5, 1., 0.), data=(data[0], data[1][:-1]))

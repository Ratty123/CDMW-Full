"""Ordered attached-static contacts from explicit runtime buffer snapshots."""

import copy
import struct

import pytest

from cdmw.modding.pac_cloth_collisions import apply_attached_static_cloth_collisions


def definition(kind=4, a=(0., 0., 0.), b=(0., 1., 0.)):
    value = bytearray(104)
    struct.pack_into('<Hf', value, 2, kind, 1.)
    struct.pack_into('<6f', value, 76, *a, *b)
    return value


def group(count=1, srv=17, start=23, friction=(.5, .25), flags=0):
    value = bytearray(16)
    struct.pack_into('<2H2e2I', value, 0, flags, count, *friction, srv, start)
    return value


def snapshots():
    parameter, frame, scene, host = bytearray(312), bytearray(100), bytearray(108), bytearray(64)
    struct.pack_into('<2I', parameter, 88, 13, 99)  # Host element, unrelated attaching element.
    struct.pack_into('<2H', parameter, 214, (1 << 11) | 7, 0xFFFF)
    struct.pack_into('<2I', scene, 48, 9, 777)  # Host buffer, unrelated transform buffer.
    return dict(simulation_parameter=parameter, per_frame=frame, per_scene=scene,
                frame_number_y=0, previous_contact=False, static_instances={(9, 13): host},
                reference_collidables={7: 31}, collider_groups={31: group()},
                collidables={(17, 23): definition()})


def apply(data, position=(2., -1., 3.), reference=(2., 2., 3.), **changes):
    return apply_attached_static_cloth_collisions(position, reference, **(data | changes))


@pytest.mark.parametrize('mesh_index', [0, 12, 0xFFFE, 0xFFFF])
def test_guide_uses_authored_thickness_while_static_meshes_use_fixed_point_zero_one(mesh_index):
    data = snapshots()
    struct.pack_into('<H', data['simulation_parameter'], 216, mesh_index)
    struct.pack_into('<f', data['simulation_parameter'], 204, .25 if mesh_index == 0xFFFF else float('nan'))
    expected = .25 if mesh_index == 0xFFFF else struct.unpack('<f', struct.pack('<f', .01))[0]
    assert apply(data) == {'position': (2., expected, 3.), 'contact': True}


@pytest.mark.parametrize('previous_contact', [False, True])
def test_disabled_sentinel_does_not_require_host_or_lists_and_preserves_contact(previous_contact):
    data = snapshots()
    struct.pack_into('<H', data['simulation_parameter'], 214, 0xFFFF)
    assert apply(data, static_instances=None, reference_collidables=None, collider_groups=None,
                 collidables=None, previous_contact=previous_contact) == {
                     'position': (2., -1., 3.), 'contact': previous_contact}


def test_zero_count_still_requires_host_record_but_not_its_unused_coordinates():
    data = snapshots()
    struct.pack_into('<H', data['simulation_parameter'], 214, 7)
    with pytest.raises(ValueError, match='static-instance'):
        apply(data, static_instances=None)
    assert apply(data, static_instances={(9, 13): b'\xff'*64}, reference_collidables=None) == {
        'position': (2., -1., 3.), 'contact': False}


def test_invalid_references_and_empty_groups_skip_unconsumed_data_without_clearing_contact():
    data = snapshots()
    struct.pack_into('<H', data['simulation_parameter'], 214, (2 << 11) | 7)
    struct.pack_into('<f', data['simulation_parameter'], 204, float('nan'))
    data['reference_collidables'] = {7: 0xFFFFFFFF, 8: 31}
    data['collider_groups'][31] = group(0, friction=(float('nan'), float('nan')))
    assert apply(data, static_instances={(9, 13): b'\xff'*64}, collidables=None, previous_contact=True) == {
        'position': (2., -1., 3.), 'contact': True}


@pytest.mark.parametrize('start,count', [(2047, 2), (13, 31)])
def test_packed_list_uses_low_eleven_bits_and_high_five_bits_without_wrapping_reference_indices(start, count):
    data = snapshots()
    struct.pack_into('<H', data['simulation_parameter'], 214, (count << 11) | start)
    data['reference_collidables'] = {i: 0xFFFFFFFF for i in range(start, start + count)}
    data['reference_collidables'][start + count - 1] = 0x10001
    data['collider_groups'] = {0x10001: group()}
    assert apply(data) == {'position': (2., 0., 3.), 'contact': True}


@pytest.mark.parametrize('sequence,expected', [((0, 1), (-1., 0., 0.)),
                                               ((1, 0), (0., -1., 0.)),
                                               ((0, 1, 0), (0., 0., 0.))])
@pytest.mark.parametrize('within_group', [False, True])
def test_reference_and_element_order_feed_forward_and_repeated_groups_are_not_deduplicated(sequence, expected, within_group):
    data = snapshots()
    shapes = [definition(b=(1., 0., 0.)), definition(b=(-1., 1., 0.))]
    if within_group:
        data['collider_groups'][31] = group(len(sequence))
        data['collidables'] = {(17, 23 + i): shapes[k] for i, k in enumerate(sequence)}
    else:
        struct.pack_into('<H', data['simulation_parameter'], 214, (len(sequence) << 11) | 7)
        data['reference_collidables'] = {7 + i: k for i, k in enumerate(sequence)}
        data['collider_groups'] = {i: group(start=23 + i) for i in range(2)}
        data['collidables'] = {(17, 23 + i): shape for i, shape in enumerate(shapes)}
    assert apply(data, position=(-1., -1., 0.)) == {'position': expected, 'contact': True}


def test_reference_stays_fixed_across_contacts_and_records_remain_unchanged():
    data = snapshots()
    data['collider_groups'][31] = group(2, flags=0xFFFF)
    data['collidables'] = {(17, 23): definition(1), (17, 24): definition(1)}
    before = copy.deepcopy(data)
    assert apply(data, position=(.5, 1., 0.), reference=(2., 0., 0.)) == {
        'position': (1., .875, 0.), 'contact': True}
    assert data == before


@pytest.mark.parametrize('frame_number_y,expected_y', [(0, -4.), (1, -6.), (2, -6.), (0xFFFFFFFF, -6.)])
def test_host_bank_uses_nonzero_frame_number_y_not_even_odd_parity(frame_number_y, expected_y):
    data = snapshots()
    first, second = bytearray(64), bytearray(64)
    struct.pack_into('<f', first, 52, 4.)
    struct.pack_into('<f', second, 52, 6.)
    assert apply(data, position=(0., -10., 0.), frame_number_y=frame_number_y,
                 static_instances={(9, 13): first, (10, 13): second}) == {
                     'position': (0., expected_y, 0.), 'contact': True}


@pytest.mark.parametrize('buffer,frame_number_y,selected', [(64999, 0, 64999), (64999, 1, 0),
                                                           (65000, 0, 0), (0xFFFFFFFF, 1, 0)])
def test_host_resource_addition_precedes_buffer_zero_selection(buffer, frame_number_y, selected):
    data = snapshots()
    struct.pack_into('<I', data['per_scene'], 48, buffer)
    assert apply(data, frame_number_y=frame_number_y, static_instances={(selected, 13): bytearray(64)})['contact']


@pytest.mark.parametrize('srv,selected', [(64999, 64999), (65000, 0), (0xFFFFFFFF, 0)])
def test_definition_resources_select_buffer_zero_and_element_addition_wraps_u32(srv, selected):
    data = snapshots()
    data['collider_groups'][31] = group(2, srv=srv, start=0xFFFFFFFF)
    data['collidables'] = {(selected, 0xFFFFFFFF): definition(b=(1., 0., 0.)),
                           (selected, 0): definition(b=(-1., 1., 0.))}
    assert apply(data, position=(-1., -1., 0.)) == {'position': (-1., 0., 0.), 'contact': True}


def test_signed_host_tiles_and_frame_offset_define_translation_without_scene_or_matrix_basis():
    data = snapshots()
    host = bytearray(b'\xff'*64)  # Matrix basis is not consumed by this loop.
    struct.pack_into('<2h', host, 12, 3, -2)  # Low Z, high X, unlike scene-object tile order.
    struct.pack_into('<3f', host, 48, 4., 5., 6.)
    struct.pack_into('<3f', data['per_frame'], 0, 1., 2., 3.)
    struct.pack_into('<3f', data['per_scene'], 0, float('nan'), float('nan'), float('nan'))
    data['static_instances'][(9, 13)] = host
    data['collidables'][(17, 23)] = definition(1, a=(-1995., 7., 3009.))
    assert apply(data, position=(.5, 1., 0.), reference=(2., 0., 0.)) == {
        'position': (1., .875, 0.), 'contact': True}


def test_contact_aggregate_is_not_inferred_from_position_changes():
    data = snapshots()
    struct.pack_into('<f', data['simulation_parameter'], 204, .125)
    data['collidables'][(17, 23)] = definition(b=(0., 0., 0.))
    assert apply(data) == {'position': (2., -1., 3.), 'contact': True}
    assert apply(snapshots(), position=(2., 1., 3.), previous_contact=True) == {
        'position': (2., 1., 3.), 'contact': True}


@pytest.mark.parametrize('missing,message', [('static_instances', 'static-instance'),
                                           ('reference_collidables', 'reference entry 7'),
                                           ('collider_groups', 'attached-static group'),
                                           ('collidables', 'collidable-definition')])
def test_missing_selected_snapshots_are_not_silently_treated_as_empty(missing, message):
    with pytest.raises(ValueError, match=message):
        apply(snapshots(), **{missing: None})


@pytest.mark.parametrize('invalid', [-1, 0x100000000, True])
def test_unsigned_runtime_selectors_are_not_coerced(invalid):
    with pytest.raises(ValueError, match='frame-number y'):
        apply(snapshots(), frame_number_y=invalid)
    data = snapshots()
    data['reference_collidables'][7] = invalid
    with pytest.raises(ValueError, match='attached-static references'):
        apply(data)

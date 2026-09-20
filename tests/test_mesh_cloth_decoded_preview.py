"""Real PAC guide decoding through the owned native-preview snapshot boundary."""

import copy
import struct

import pytest

from cdmw.modding.pac_cloth_preview import build_cloth_preview_snapshot
from cdmw.services.mesh_rust_authoring import read_owned_payload_reference
from tests.test_mesh_jiggle_decoded_preview import rig_session, decoded
from tests.test_mesh_jiggle import jiggle_session
from tests.test_pac_cloth_guides import guide_fixture


def source():
    data, offsets = guide_fixture()
    data = bytearray(data)
    for i, xyz in enumerate(((0, 0, 0), (32767, 0, 0), (0, 32767, 0))):
        struct.pack_into('<4HI4B', data, offsets['vertices'] + 16*i, *xyz, 0, 0, 255, 0, 0, 0)
    data[offsets['channel_b']:offsets['channel_b'] + 3] = bytes((255, 0, 128))
    struct.pack_into('<5H', data, offsets['records_10'] + 2, 0, 1, 0, 0, 0)
    return bytes(data), offsets


def rig():
    identity = [[float(i == j) for j in range(4)] for i in range(4)]
    neutral = copy.deepcopy(identity)
    neutral[1][1] = 2.
    neutral[3][:3] = [10., 20., 30.]
    return dict(bone_palette=[0], inverse_bind_matrices=[identity], neutral_global_matrices=[neutral])


def test_snapshot_uses_real_guides_neutral_pose_fixed_channel_and_half_blends():
    data, _ = source()
    result = build_cloth_preview_snapshot(data, rig())
    assert result['version'] == 1
    assert result['fixed'] == [True, False, False]
    assert result['source_positions'] == [[-2., 3., 5.], [2., 3., 5.], [-2., 11., 5.]]
    assert [frame[3][:3] for frame in result['animation_frames']] == [[8., 26., 35.], [12., 26., 35.], [8., 42., 35.]]
    assert result['animation_frames'][0][1] == [0., 2., 0., 0.]
    assert result['alpha_blends'] == [1., 0., struct.unpack('<e', struct.pack('<e', 128/255))[0]]
    assert result['constraints'] == [{'kind': 'pair', 'indices': [0, 1], 'rest': 4.}]


def test_shader_weights_remain_unnormalized_while_cpu_reference_length_uses_normalized_weights():
    data, offsets = source()
    modified = bytearray(data)
    modified[offsets['vertices'] + 12] = 254
    result = build_cloth_preview_snapshot(bytes(modified), rig())
    assert result['animation_frames'][0][0][0] == pytest.approx(254/255)
    assert result['animation_frames'][0][3][:3] == pytest.approx([8*254/255, 26*254/255, 35*254/255])
    assert result['constraints'][0]['rest'] == 4.
    struct.pack_into('<H', modified, offsets['vertices'], 0x8000)
    result = build_cloth_preview_snapshot(bytes(modified), rig())
    assert result['source_positions'][0][0] == -2.  # Shader masks to15 bits.
    assert result['constraints'][0]['rest'] < .001  # CPU keeps all16 bits.


def test_undecoded_constraints_and_zero_weight_or_invalid_palette_are_rejected():
    data, offsets = source()
    for offset, value, message in (
        (offsets['vertices'] + 12, 0, 'zero skeletal weight'),
        (offsets['records_10'] + 10, 2, 'undecoded cloth constraint'),
        (offsets['vertices'] + 8, 1, 'bone palette'),
    ):
        bad = bytearray(data)
        bad[offset] = value
        with pytest.raises(ValueError, match=message):
            build_cloth_preview_snapshot(bytes(bad), rig())


def test_host_caches_guide_transport_with_the_rig_without_changing_pac_or_existing_record_lanes(rig_session, monkeypatch):
    original, session, host = rig_session
    data, _ = source()
    from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides
    guides = decode_pac_cloth_guides(data)
    calls = []

    def decode(_):
        calls.append(1)
        return guides

    monkeypatch.setattr('cdmw.modding.pac_cloth_preview.decode_pac_cloth_guides', decode)
    state = decoded(host)
    assert state['available'] and state['cloth'] == {
        'available': True, 'reason': '', 'guide_count': 3, 'fixed_count': 1, 'area_constraint_count': 0,
    }
    payload = read_owned_payload_reference(host.root, state['file'])
    assert payload['cloth']['fixed'] == [True, False, False]
    assert payload['cloth']['constraints'][0]['kind'] == 'pair'
    assert decoded(host) == state and calls == [1]
    assert session.original_data == original
    host.cancel()  # The existing owned payload cleanup remains valid.


def test_unavailable_guides_do_not_disable_decoded_jiggle(rig_session, monkeypatch):
    _, _, host = rig_session
    monkeypatch.setattr('cdmw.modding.pac_cloth_preview.decode_pac_cloth_guides', lambda _: None)
    state = decoded(host)
    assert state['available'] and not state['cloth']['available']
    assert 'no decoded cloth guide' in state['cloth']['reason']
    assert 'cloth' not in read_owned_payload_reference(host.root, state['file'])

"""Rigid spline preparation through the real owned host payload; no game files."""
import struct

import pytest

from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.modding.pac_cloth_preview import rigid_attachment_preview_rig
from cdmw.services.mesh_rust_authoring import read_owned_payload_reference
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session
from tests.test_pac_cloth_guides import guide_fixture


def spline_fixture():
    data, offsets = guide_fixture()
    data = bytearray(data)
    flags = struct.unpack_from('<I', data, 80)[0]
    struct.pack_into('<I', data, 80, flags | 0x8000)
    for i in range(3):
        struct.pack_into('<4HI4B', data, offsets['vertices'] + i * 16,
                         0, 0, i * 16383, 0, 0, 255, 0, 0, 0)
    data[offsets['channel_b']:offsets['channel_b'] + 3] = bytes((255, 0, 0))
    struct.pack_into('<5H', data, offsets['groups_a'], 1, 3, 0, 1, 2)
    struct.pack_into('<H5H', data, offsets['records_10'], 2, 0, 1, 0, 0, 0)
    data[offsets['records_10'] + 12:offsets['records_10'] + 12] = struct.pack('<5H', 1, 2, 0, 0, 0)
    size = struct.unpack_from('<I', data, 16)[0] + 10
    struct.pack_into('<2I', data, 16, size, size)
    for level in pac_cloth_lods(data):
        for part in level.submeshes:
            for i, offset in enumerate(part.source_vertex_offsets):
                data[offset + 28] = 255
                data[offset + 38:offset + 40] = bytes((255, 63))
                if i:
                    struct.pack_into('<2e', data, offset + 12, 0., 0.)
                    struct.pack_into('<I', data, offset + 24, i << 10)
                    data[offset + 32] = 255
                    data[offset + 39] = 0
    return bytes(data)


@pytest.fixture
def spline_host(tmp_path, monkeypatch):
    source = spline_fixture()
    monkeypatch.setattr('tests.test_mesh_rust_authoring_exact_output._pac_fixture', lambda **_: source)
    _, service, host = _open_exact_session(tmp_path / 'spline')
    yield source, host
    if not host.closed:
        host.cancel()
    service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


def test_standalone_rigid_spline_publishes_an_owned_chain_without_a_pab(spline_host):
    source, host = spline_host
    session = host.shadow_service._session(host.shadow_session_id)
    assert session.skeleton is None
    state = host.state_payload(include_document=False)['jiggle']['decoded']
    assert state['available'], state
    assert state['rig_mode'] == 'rigid_attachment'
    assert state['cloth']['spline_available'] and state['cloth']['chain_count'] == 1
    assert not state['cloth']['body_collider_count']
    payload = read_owned_payload_reference(host.root, state['file'])
    assert payload['cloth']['spline_chains'] == [[0, 1, 2]]
    assert payload['cloth']['fixed'] == [True, False, False]
    assert payload['rig']['parents'] == [-1]
    part = pac_cloth_lods(source)[0].submeshes[0]
    assert payload['parts'][0]['records'] == [source[offset:offset + 40].hex() for offset in part.source_vertex_offsets]
    assert session.original_data == source
    assert host.state_payload(include_document=False)['jiggle']['decoded'] == state


@pytest.mark.parametrize('lod', range(4))
def test_standalone_rejects_a_second_attachment_on_any_stored_lod(lod):
    data = bytearray(spline_fixture())
    offset = pac_cloth_lods(data)[lod].submeshes[0].source_vertex_offsets[0]
    struct.pack_into('<I', data, offset + 20, 1)
    with pytest.raises(ValueError, match='one rigid skeletal attachment'):
        rigid_attachment_preview_rig(bytes(data))


def test_standalone_rejects_guide_attachments_and_incomplete_weights():
    data, offsets = guide_fixture()
    rigid = bytearray(spline_fixture())
    struct.pack_into('<I', rigid, offsets['vertices'] + 8, 1)
    with pytest.raises(ValueError, match='one rigid skeletal attachment'):
        rigid_attachment_preview_rig(bytes(rigid))
    rigid = bytearray(spline_fixture())
    offset = pac_cloth_lods(rigid)[3].submeshes[0].source_vertex_offsets[0]
    rigid[offset + 28] = 254
    with pytest.raises(ValueError, match='complete rigid skeletal weights'):
        rigid_attachment_preview_rig(bytes(rigid))
    with pytest.raises(ValueError, match='complete ordered guides'):
        rigid_attachment_preview_rig(data)


def test_standalone_rejects_current_attachment_edits_without_replacing_payload(spline_host):
    _, host = spline_host
    before = host.state_payload(include_document=False)['jiggle']['decoded']
    session = host.shadow_service._session(host.shadow_session_id)
    part = session.working_mesh.submeshes[0]
    part.bone_indices[0] = (1,)
    part.bone_weights[0] = (1.,)
    session.revision += 1
    after = host.state_payload(include_document=False)['jiggle']['decoded']
    assert not after['available'] and 'edited skeletal attachments' in after['reason']
    assert read_owned_payload_reference(host.root, before['file'])['cloth']['spline_chains'] == [[0, 1, 2]]


def test_standalone_requires_a_spline_source_or_an_explicit_spline_profile():
    data = bytearray(spline_fixture())
    struct.pack_into('<I', data, 80, struct.unpack_from('<I', data, 80)[0] & ~0x8000)
    with pytest.raises(ValueError, match='spline source or an explicit spline profile'):
        rigid_attachment_preview_rig(bytes(data))
    assert rigid_attachment_preview_rig(bytes(data), spline_profile=True)['parents'] == [-1]


def test_standalone_body_inputs_still_require_a_matching_rig(spline_host):
    from cdmw.services.mesh_rust_jiggle import set_cloth_collision_input
    _, host = spline_host
    with pytest.raises(ValueError, match='matching rig'):
        set_cloth_collision_input(host, {'role': 'body', 'path': str(host.root / 'missing.pabv')}, None)
    assert not host.cloth_collision_inputs


def test_zero_packed_spline_rest_lengths_keep_ordinary_guide_preparation_available():
    from cdmw.modding.pac_cloth_preview import build_cloth_preview_snapshot
    _, offsets = guide_fixture()
    data = bytearray(spline_fixture())
    struct.pack_into('<f', data, offsets['bbox'] + 10 + 20, 4e-8)
    data = bytes(data)
    snapshot = build_cloth_preview_snapshot(data, rigid_attachment_preview_rig(data))
    assert len(snapshot['source_positions']) == 3
    assert snapshot['spline_chains'] == []
    assert all(row['rest'] == 0 for row in snapshot['constraints'])

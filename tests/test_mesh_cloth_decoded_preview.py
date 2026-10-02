"""Real PAC guide decoding through the owned native-preview snapshot boundary."""

import copy
import struct
from contextlib import ExitStack

import pytest

from cdmw.modding.pac_cloth_preview import (
    build_cloth_body_collider_snapshot, build_cloth_preview_snapshot, select_cloth_body_volumes,
)
from cdmw.services.mesh_rust_authoring import read_owned_payload_reference
from tests.test_mesh_jiggle_decoded_preview import rig_session, decoded
from tests.test_mesh_jiggle import jiggle_session
from tests.test_pac_cloth_guides import guide_fixture


@pytest.mark.parametrize("neutral", [False, True])
def test_cloth_preview_comparisons_follow_export_rules_and_original_neutral_heights(tmp_path, monkeypatch, neutral):
    from cdmw.domain.mesh.cloth import PacClothRule
    from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
    from cdmw.modding.pac_cloth import pac_cloth_lods
    from tests.test_mesh_cloth_influence import apply_rule, cloth_fixture, shadow_output
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session
    from tests.test_mesh_rust_replacement import command

    source = bytearray(cloth_fixture())
    for level in pac_cloth_lods(source):
        for part in level.submeshes:
            for offset in part.source_vertex_offsets:
                source[offset + 38] = 255  # Cloth remains available without jiggle flags.
    source = bytes(source)
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    matrix = (1., 0., 0., 0., 0., 2., 0., 0., 0., 0., 1., 0., 0., 10., 0., 1.)
    appearance = NeutralMeshAppearance("owned", tuple(range(8)), (matrix,) * 8) if neutral else None
    with ExitStack() as stack:
        _, service, host = _open_exact_session(tmp_path / "session", neutral_appearance=appearance)
        stack.callback(service.close_edit_session, host.authoritative_session_id, force_without_saving=True)
        stack.callback(lambda: host.cancel() if not host.closed else None)
        state = host.state_payload()["jiggle"]
        assert not state["available"] and state["parts"] == []
        preview = state["overlay_parts"][0]["preview"]
        assert preview["original_cloth_bytes"] == preview["current_cloth_bytes"] == [63, 0, 0, 0]
        offsets = pac_cloth_lods(source)[0].submeshes[0].source_vertex_offsets
        rule = PacClothRule(.5, 11. if neutral else .5, .5 if neutral else .25)
        apply_rule(host, tmp_path, rule)
        current = host.state_payload()["jiggle"]["overlay_parts"][0]["preview"]
        exported = shadow_output(host)
        assert current["current_cloth_bytes"] == [exported[offset + 39] & 63 for offset in offsets]
        assert current["current_cloth_bytes"] == [63, 32, 63, 63]
        assert current["original_cloth_bytes"] == preview["original_cloth_bytes"]
        part = host.shadow_service._session(host.shadow_session_id).working_mesh.submeshes[0]
        part.vertices = [(x, y + 50., z) for x, y, z in part.vertices]
        assert host.state_payload()["jiggle"]["overlay_parts"][0]["preview"]["current_cloth_bytes"] == current["current_cloth_bytes"]
        command(host, "undo")
        assert host.state_payload()["jiggle"]["overlay_parts"][0]["preview"] == preview
        apply_rule(host, tmp_path, PacClothRule(0))
        assert host.state_payload()["jiggle"]["overlay_parts"][0]["preview"]["current_cloth_bytes"] == [63, 63, 63, 63]
        apply_rule(host, tmp_path, PacClothRule(), reset=True)
        assert host.state_payload()["jiggle"]["overlay_parts"][0]["preview"] == preview
        assert host.shadow_service.capture_export_snapshot(host.shadow_session_id).original_data == source


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
    assert result['orientation_neighbors'] == [(1, 2), (2, 0), (0, 1)]
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
    mock_model_volumes(monkeypatch, original)
    state = decoded(host)
    assert state['available'] and state['cloth'] == {
        'available': True, 'reason': '', 'guide_count': 3, 'fixed_count': 1, 'area_constraint_count': 0,
        'rotation_available': True,
        'spline_available': False, 'chain_count': 0,
        'body_collider_count': 0, 'body_collider_source': '',
        'body_collider_reason': 'Embedded volumes require a fixed-layout PAB with the known PAR 1/5 header.',
        'weapon_collider_count': 0, 'weapon_collider_source': '',
        'weapon_collider_reason': 'Embedded model volumes require the known PAC 3/9 header.',
    }
    payload = read_owned_payload_reference(host.root, state['file'])
    assert payload['cloth']['fixed'] == [True, False, False]
    assert payload['cloth']['body_colliders'] == []
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


@pytest.mark.parametrize('tag, parameters, kind, a, b, radius', [
    (5, (.25, 2.), 5, [8., 20., 39.], [8., 24., 39.], .75),
    (1, (.5, 4.), 3, [8., 18., 39.], [8., 26., 39.], 1.5),
    (4, (.5,), 1, [8., 22., 39.], [8., 22., 39.], 1.5),
])
def test_primary_body_colliders_follow_neutral_rotation_scale_and_translation(tag, parameters, kind, a, b, radius):
    from cdmw.modding.skeleton_parser import parse_pab
    from tests.test_pab_embedded_volumes import fixture, section
    from tests.test_pabv_parser import IDENTITY, record

    local = (*IDENTITY[:12], 1., 2., 3., 1.)
    volume = record(tag, parameters, key=1, matrix=local)
    # Duplicate primary geometry is coalesced; rendering volumes are not used.
    data = fixture(section(volume, volume), section(record(0, (1., 2., 3.), key=0)))
    skeleton = parse_pab(data)
    pose = [[0., 2., 0., 0.], [-1., 0., 0., 0.], [0., 0., 3., 0.], [10., 20., 30., 1.]]
    result = build_cloth_body_collider_snapshot(skeleton, {'neutral_global_matrices': [pose, pose]})
    assert result == [{'kind': kind, 'center1': a, 'center2': b, 'radius': radius,
                       'bone_index': 1, 'source_ordinal': 0}]
    assert skeleton.tail_data == data[skeleton.tail_offset:]


def mock_model_volumes(monkeypatch, original, *records):
    from cdmw.modding.pabv_parser import decode_pac_embedded_volumes
    from tests.test_pac_embedded_volumes import fixture

    model = decode_pac_embedded_volumes(fixture(*records, layout=3)[0])
    calls = []

    def decode(data):
        assert data == original
        calls.append(1)
        return model

    monkeypatch.setattr('cdmw.modding.pabv_parser.decode_pac_embedded_volumes', decode)
    return calls


@pytest.mark.parametrize('model_source', [True, False])
@pytest.mark.parametrize('supported', [True, False])
def test_host_body_volumes_are_optional_cached_and_never_change_source(rig_session, monkeypatch, supported, model_source):
    from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides
    from cdmw.modding.skeleton_parser import parse_pab
    from tests.test_pab_embedded_volumes import fixture, section
    from tests.test_pabv_parser import record

    original, session, host = rig_session
    volume = record(key=1) if supported else record(0, (1., 2., 3.), key=1)
    session.skeleton = parse_pab(fixture(section(record(key=1) if model_source else volume)))
    records = ()
    if model_source:
        key = session.skeleton.bones[1].name_hash
        records = (record(key=key, flags=0) if supported else record(0, (1., 2., 3.), key=key, flags=0),)
    calls = mock_model_volumes(monkeypatch, original, *records)
    guides = decode_pac_cloth_guides(source()[0])
    monkeypatch.setattr('cdmw.modding.pac_cloth_preview.decode_pac_cloth_guides', lambda _: guides)
    state = decoded(host)
    assert state['available'] and state['cloth']['available']
    assert state['cloth']['body_collider_count'] == int(supported)
    assert state['cloth']['body_collider_source'] == ('pac_model' if model_source else 'pab_primary')
    assert bool(state['cloth']['body_collider_reason']) == (not supported)
    payload = read_owned_payload_reference(host.root, state['file'])
    assert len(payload['cloth']['body_colliders']) == int(supported)
    if supported:
        collider, = payload['cloth']['body_colliders']
        assert collider['bone_index'] == 1
        assert collider['center1'] == pytest.approx([10., 21., 0.])
        assert collider['center2'] == pytest.approx([10., 23., 0.])
    assert decoded(host) == state and calls == [1]
    assert session.original_data == original
    offsets = session.working_mesh.submeshes[0].source_vertex_offsets
    assert payload['parts'][0]['records'] == [original[o:o + 40].hex() for o in offsets]


def test_body_collider_preview_rejects_empty_oversized_and_degenerate_sets():
    from cdmw.modding.skeleton_parser import parse_pab
    from tests.test_pab_embedded_volumes import fixture, section
    from tests.test_pabv_parser import record

    poses = {'neutral_global_matrices': rig()['neutral_global_matrices'] * 2}
    for records, message in (([], 'between 1 and 128'),
                             ([record(key=0)] * 129, 'between 1 and 128'),
                             ([record(parameters=(.25, 0.), key=0)], 'Degenerate')):
        with pytest.raises(ValueError, match=message):
            build_cloth_body_collider_snapshot(parse_pab(fixture(section(*records))), poses)


def test_model_volume_precedence_hash_binding_and_unchanged_pac_and_rig():
    from cdmw.modding.skeleton_parser import parse_pab
    from tests.test_pab_embedded_volumes import fixture, section
    from tests.test_pabv_parser import record
    from tests.test_pac_embedded_volumes import fixture as pac_fixture

    pab = fixture(section(record(key=0, parameters=(.75, 2.))))
    skeleton = parse_pab(pab)
    # PAB order differs from the model's palette and the volume's ordinal.
    key = skeleton.bones[1].name_hash
    pac, _ = pac_fixture(record(key=key, parameters=(.25, 2.), flags=0), layout=3)
    poses = {'neutral_global_matrices': rig()['neutral_global_matrices'] * 2}
    volumes, source_name = select_cloth_body_volumes(pac, skeleton)
    assert source_name == 'pac_model' and volumes.uses_bone_hashes
    colliders = build_cloth_body_collider_snapshot(skeleton, poses, volumes=volumes)
    assert [(row['bone_index'], row['radius']) for row in colliders] == [(1, .25)]
    assert skeleton.tail_data == pab[skeleton.tail_offset:]
    assert pac == pac_fixture(record(key=key, parameters=(.25, 2.), flags=0), layout=3)[0]
    # An explicitly empty model set permits the rig's primary set.
    empty = pac_fixture()[0]
    defaults, source_name = select_cloth_body_volumes(empty, skeleton)
    assert source_name == 'pab_primary'
    assert build_cloth_body_collider_snapshot(skeleton, poses, volumes=defaults)[0]['radius'] == .75


@pytest.mark.parametrize('kind', ['unknown_metadata', 'low_key', 'missing_hash', 'ambiguous_hash', 'unsupported_shape'])
def test_unsupported_model_source_never_silently_uses_valid_rig_defaults(kind):
    from cdmw.modding.skeleton_parser import parse_pab
    from tests.test_pab_embedded_volumes import fixture, section
    from tests.test_pabv_parser import record
    from tests.test_pac_embedded_volumes import fixture as pac_fixture

    skeleton = parse_pab(fixture(section(record(key=0))))
    key = skeleton.bones[1].name_hash
    if kind == 'ambiguous_hash':
        skeleton.bones[0].name_hash = key
    if kind in ('low_key', 'missing_hash'):
        key = 1 if kind == 'low_key' else 0xFFFFFFFF
    volume = record(0, (1., 2., 3.), key=key, flags=0) if kind == 'unsupported_shape' else record(key=key, flags=0)
    data, _ = pac_fixture(volume)
    if kind == 'unknown_metadata':
        data = bytearray(data)
        data[80] |= 0x20
    poses = {'neutral_global_matrices': rig()['neutral_global_matrices'] * 2}
    with pytest.raises(ValueError, match='bone-group|missing or ambiguous|sphere, cylinder or capsule'):
        volumes, source_name = select_cloth_body_volumes(bytes(data), skeleton)
        assert source_name == 'pac_model'
        build_cloth_body_collider_snapshot(skeleton, poses, volumes=volumes)


def test_host_unknown_model_metadata_keeps_playback_without_claiming_rig_fallback(rig_session, monkeypatch):
    from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides
    from cdmw.modding.skeleton_parser import parse_pab
    from tests.test_pab_embedded_volumes import fixture, section
    from tests.test_pabv_parser import record
    from tests.test_pac_embedded_volumes import fixture as pac_fixture

    original, session, host = rig_session
    session.skeleton = parse_pab(fixture(section(record(key=1))))
    guides = decode_pac_cloth_guides(source()[0])
    monkeypatch.setattr('cdmw.modding.pac_cloth_preview.decode_pac_cloth_guides', lambda _: guides)
    bad, _ = pac_fixture()
    bad = bytearray(bad)
    bad[80] |= 0x20
    select = select_cloth_body_volumes

    def select_unknown(data, skeleton):
        assert data == original
        return select(bytes(bad), skeleton)

    monkeypatch.setattr('cdmw.modding.pac_cloth_preview.select_cloth_body_volumes', select_unknown)
    state = decoded(host)
    assert state['available'] and state['cloth']['available']
    assert state['cloth']['body_collider_count'] == 0
    assert state['cloth']['body_collider_source'] == ''
    assert 'bone-group' in state['cloth']['body_collider_reason']
    assert read_owned_payload_reference(host.root, state['file'])['cloth']['body_colliders'] == []
    assert session.original_data == original


@pytest.fixture
def collision_session(rig_session, monkeypatch):
    from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides
    from cdmw.modding.skeleton_parser import parse_pab
    from tests.test_pab_embedded_volumes import fixture, section
    from tests.test_pabv_parser import record

    original, session, host = rig_session
    session.skeleton = parse_pab(fixture(section(record(key=1))))
    session.skeleton.bones[1].name_hash = 0xA23A288E
    mock_model_volumes(monkeypatch, original)
    guides = decode_pac_cloth_guides(source()[0])
    monkeypatch.setattr('cdmw.modding.pac_cloth_preview.decode_pac_cloth_guides', lambda _: guides)
    return original, session, host


def test_collision_inputs_replace_body_merge_first_head_and_clear_without_mesh_or_output_edits(collision_session, tmp_path):
    from cdmw.services.mesh_rust_authoring import RustMeshProtocolError
    from tests.test_mesh_rust_replacement import command
    from tests.test_mesh_jiggle import shadow_output
    from tests.test_mesh_rust_authoring_exact_output import _request
    from tests.test_pabv_parser import container, record

    original, session, host = collision_session
    before = decoded(host)
    mesh = copy.deepcopy(session.working_mesh)
    output = shadow_output(host)
    history = (len(session.undo_stack), len(session.redo_stack))
    stale = {**_request(host, 'command_request', 9), 'command': 'state'}
    body = tmp_path / 'body.pabv'
    head = tmp_path / 'head.pabv'
    body_data = container(record(key=session.skeleton.bones[0].name_hash, parameters=(.5, 2.)),
                          record(key=0xA23A288E))
    head_data = container(record(key=0xA23A288E, parameters=(.75, 2.)),
                          record(key=0xA23A288E, parameters=(.875, 2.)))
    body.write_bytes(body_data)
    head.write_bytes(head_data)
    result = command(host, 'cloth_collision_input', {'role': 'body', 'path': str(body)})
    assert result['result'] == {'changed': True}
    assert result['state']['jiggle']['collision_inputs'] == {'body': 'body.pabv'}
    assert 'document' not in result['state']
    with pytest.raises(RustMeshProtocolError, match='revision'):
        host.run_command(stale)
    result = command(host, 'cloth_collision_input', {'role': 'head', 'path': str(head)})
    state = result['state']['jiggle']['decoded']
    payload = read_owned_payload_reference(host.root, state['file'])
    assert state['cloth']['body_collider_source'] == 'appearance'
    assert [(v['bone_index'], v['radius']) for v in payload['cloth']['body_colliders']] == [(0, .5), (1, .75)]
    # Prepared input bytes stay immutable even if the chosen file later changes.
    body.write_bytes(b'changed externally')
    assert decoded(host) == state
    revision = session.revision
    command(host, 'cloth_collision_input', {'role': 'head', 'path': str(head)})
    assert session.revision == revision
    host.jiggle_source_cache = None
    assert decoded(host) == state
    result = command(host, 'cloth_collision_input', {'clear': True})
    assert result['state']['jiggle']['collision_inputs'] == {}
    assert result['state']['jiggle']['decoded'] == before
    assert session.working_mesh == mesh and session.original_data == original
    assert shadow_output(host) == output
    assert (len(session.undo_stack), len(session.redo_stack)) == history
    assert head.read_bytes() == head_data


@pytest.mark.parametrize('failure', ['legacy', 'missing_hash', 'head_missing', 'unsupported', 'cancel', 'publish'])
def test_collision_input_failure_preserves_last_valid_snapshot(collision_session, tmp_path, monkeypatch, failure):
    import threading
    from tests.test_mesh_rust_replacement import command
    from tests.test_mesh_rust_authoring_exact_output import _request
    from tests.test_pabv_parser import container, record
    from cdmw.modding import pabv_parser
    from cdmw.services import mesh_rust_authoring

    original, session, host = collision_session
    path = tmp_path / 'body.pabv'
    path.write_bytes(container(record(key=0xA23A288E)))
    command(host, 'cloth_collision_input', {'role': 'body', 'path': str(path)})
    before = decoded(host)
    contents = (host.root / 'jiggle-rig.json').read_bytes()
    inputs, revision = dict(host.cloth_collision_inputs), session.revision
    stop = threading.Event()
    role = 'body'
    if failure == 'legacy':
        path.write_bytes(container(record(key=1), flags=0))
    elif failure in ('missing_hash', 'head_missing'):
        path.write_bytes(container(record(key=0xFFFFFFFF)))
        if failure == 'head_missing':
            role = 'head'
    elif failure == 'unsupported':
        path.write_bytes(container(record(0, (1., 2., 3.), key=0xA23A288E)))
    else:
        path.write_bytes(container(record(key=0xA23A288E, parameters=(.5, 2.))))
    if failure == 'cancel':
        decode = pabv_parser.decode_pabv
        def cancel(data):
            stop.set()
            return decode(data)
        monkeypatch.setattr(pabv_parser, 'decode_pabv', cancel)
    if failure == 'publish':
        def fail(*args, **kwargs):
            raise OSError('owned payload write failed')
        monkeypatch.setattr(mesh_rust_authoring, '_atomic_write_payload', fail)
    request = {**_request(host, 'command_request', 3), 'command': 'cloth_collision_input',
               'arguments': {'role': role, 'path': str(path)}}
    with pytest.raises((ValueError, OSError, mesh_rust_authoring.RustMeshCancellationError)):
        host.run_command(request, stop_event=stop)
    assert host.cloth_collision_inputs == inputs and session.revision == revision
    assert decoded(host) == before and (host.root / 'jiggle-rig.json').read_bytes() == contents
    assert session.original_data == original


def test_collision_input_cannot_override_embedded_model_or_unknown_model_metadata(collision_session, tmp_path, monkeypatch):
    from dataclasses import replace
    from cdmw.modding import pabv_parser
    from tests.test_mesh_rust_replacement import command
    from tests.test_pabv_parser import record, container

    original, session, host = collision_session
    path = tmp_path / 'override.pabv'
    path.write_bytes(container(record(key=0xA23A288E)))
    model = replace(pabv_parser.decode_pac_embedded_volumes(original),
                    volumes=pabv_parser.decode_pabv(container(record(key=0xA23A288E))).volumes)
    monkeypatch.setattr(pabv_parser, 'decode_pac_embedded_volumes', lambda _: model)
    before = decoded(host)
    with pytest.raises(ValueError, match='take precedence'):
        command(host, 'cloth_collision_input', {'role': 'body', 'path': str(path)})
    assert decoded(host) == before and not host.cloth_collision_inputs
    def unknown(_):
        raise ValueError('Unknown model metadata')
    monkeypatch.setattr('cdmw.modding.pabv_parser.decode_pac_embedded_volumes', unknown)
    host.jiggle_source_cache = None
    before = decoded(host)
    with pytest.raises(ValueError, match='Unknown model metadata'):
        command(host, 'cloth_collision_input', {'role': 'body', 'path': str(path)})
    assert decoded(host) == before and not host.cloth_collision_inputs


def test_collision_input_finishes_atomic_publication_when_cancel_arrives_after_write(collision_session, tmp_path, monkeypatch):
    import threading
    from cdmw.services import mesh_rust_authoring
    from tests.test_mesh_rust_authoring_exact_output import _request
    from tests.test_pabv_parser import container, record

    _, session, host = collision_session
    decoded(host)
    path = tmp_path / 'body.pabv'
    path.write_bytes(container(record(key=0xA23A288E, parameters=(.5, 2.))))
    stop = threading.Event()
    atomic = mesh_rust_authoring._atomic_write_payload
    def publish(*args, **kwargs):
        reference = atomic(*args, **kwargs)
        stop.set()
        return reference
    monkeypatch.setattr(mesh_rust_authoring, '_atomic_write_payload', publish)
    result = host.run_command({**_request(host, 'command_request', 7), 'command': 'cloth_collision_input',
                               'arguments': {'role': 'body', 'path': str(path)}}, stop_event=stop)
    assert result['result']['changed'] and stop.is_set()
    assert result['state']['jiggle']['collision_inputs'] == {'body': 'body.pabv'}
    state = result['state']['jiggle']['decoded']
    assert read_owned_payload_reference(host.root, state['file'])['cloth']['body_colliders'][0]['radius'] == .5

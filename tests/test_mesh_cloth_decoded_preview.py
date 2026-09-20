"""Real PAC guide decoding through the owned native-preview snapshot boundary."""

import copy
import struct
from contextlib import ExitStack

import pytest

from cdmw.modding.pac_cloth_preview import build_cloth_preview_snapshot
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

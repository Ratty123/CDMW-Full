"""Relative byte-38 edits through PAC output, history and recovered drafts."""
import copy
from contextlib import ExitStack
import json

import pytest

from cdmw.domain.mesh.jiggle import PacJiggleRule
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.modding.pac_jiggle import apply_pac_jiggle_rules, reduce_pac_jiggle_byte
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from tests.test_mesh_cloth_influence import shadow_output
from tests.test_mesh_editor_replacement_sequences import open_editor
from tests.test_mesh_jiggle import archive_context, jiggle_fixture, jiggle_session, set_jiggle
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_replacement import command


def _retain(host, amount, below_y=None):
    key = host.state_payload()["jiggle"]["parts"][0]["id"]
    return command(host, "replacement_jiggle", {
        "part_ids": [key], "rule": {"below_y": below_y, "retained": amount},
        **archive_context(host),
    })


@pytest.mark.parametrize("value, half", [(240, 247), (246, 250), (249, 252), (252, 253), (254, 254), (255, 255)])
def test_known_half_contribution_and_rounding(value, half):
    assert reduce_pac_jiggle_byte(value, .5) == half
    assert reduce_pac_jiggle_byte(value, 0) == 255
    assert reduce_pac_jiggle_byte(value, 1) == value
    for amount in (.1, .25, .5, .75):
        result = reduce_pac_jiggle_byte(value, amount)
        assert value <= result <= 255
        assert result & 0xF0 == value & 0xF0
        # The inverse weights use different denominators but the same ratio.
        if value != 255:
            full_ratio = ((255 - result) / 255) / ((255 - value) / 255)
            nibble_ratio = ((15 - (result & 15)) / 15) / ((15 - (value & 15)) / 15)
            assert full_ratio == pytest.approx(nibble_ratio)


def test_selected_reduction_preserves_every_other_channel_at_all_lods():
    source = jiggle_fixture()
    result = apply_pac_jiggle_rules(source, {0: PacJiggleRule(.5, .5)})
    addresses = set()
    changed_lods = set()
    for lod, level in enumerate(pac_cloth_lods(source)):
        part = level.submeshes[0]
        for point, offset in zip(part.vertices, part.source_vertex_offsets):
            address = offset + 38
            if point[1] < .5:
                addresses.add(address)
                assert result[address] >= source[address]
                if result[address] != source[address]:
                    changed_lods.add(lod)
            else:
                assert result[address] == source[address]
    assert changed_lods == set(range(4))
    assert all(a == b or i in addresses for i, (a, b) in enumerate(zip(source, result, strict=True)))


def test_edits_rebuild_from_source_and_weight_preview_matches_output(jiggle_session):
    source, _, host = jiggle_session
    original = host.state_payload()["jiggle"]["parts"][0]["preview"]
    assert host.state_payload()["jiggle"]["parts"][0]["relative_available"]
    for amount in (.5, .25, .5):
        _retain(host, amount)
        output = shadow_output(host)
        assert output == apply_pac_jiggle_rules(source, {0: PacJiggleRule(None, amount)})
        preview = host.state_payload()["jiggle"]["parts"][0]["preview"]
        assert preview["original_bytes"] == original["original_bytes"]
        assert preview["current_bytes"] == [output[offset + 38] for offset in pac_cloth_lods(output)[0].submeshes[0].source_vertex_offsets]
    command(host, "undo")
    assert shadow_output(host) == apply_pac_jiggle_rules(source, {0: PacJiggleRule(None, .25)})
    command(host, "redo")
    assert shadow_output(host) == apply_pac_jiggle_rules(source, {0: PacJiggleRule(None, .5)})
    set_jiggle(host, reset=True)
    assert shadow_output(host) == source


def test_relative_finish_and_recovered_draft(jiggle_session, tmp_path):
    source, service, host = jiggle_session
    _retain(host, .5, .5)
    expected = shadow_output(host)
    host.finish(_request(host, "finish_request", 22))
    final = service.capture_export_snapshot(host.authoritative_session_id)
    draft = tmp_path / "draft" / "mesh_layers.json"
    service._session(host.authoritative_session_id).mesh_layer_project_path = draft
    service.retry_mesh_layer_autosave(host.authoritative_session_id)
    with ExitStack() as stack:
        reopened, sid = open_editor(stack, source, final.mesh.path, draft)
        restored = reopened.capture_export_snapshot(sid)
        assert restored.replacement_state.parts[0].jiggle == PacJiggleRule(.5, .5)
        assert reopened.rebuild_result_from_snapshot(restored)[0].data == expected
    descriptor = json.loads(draft.read_text())
    generation = json.loads((draft.parent / descriptor["current_generation"] / "generation.json").read_text())
    assert generation["replacement"]["version"] == 6


def test_relative_draft_rejects_missing_contribution_and_downgrade(jiggle_session, tmp_path):
    _, _, host = jiggle_session
    _retain(host, .5)
    state = host.shadow_service.capture_export_snapshot(host.shadow_session_id).replacement_state
    payload = save_replacement_state(state, tmp_path, tmp_path)
    assert load_replacement_state(payload, tmp_path) == state
    missing = copy.deepcopy(payload)
    missing["parts"][0]["jiggle"].pop("retained")
    with pytest.raises(ValueError, match="missing the retained"):
        load_replacement_state(missing, tmp_path)
    payload["version"] = 5
    with pytest.raises(ValueError, match="version 6"):
        load_replacement_state(payload, tmp_path)


def test_unproven_source_encoding_rejects_reduction_before_history_changes(tmp_path, monkeypatch):
    source = bytearray(jiggle_fixture())
    source[pac_cloth_lods(source)[-1].submeshes[0].source_vertex_offsets[0] + 38] = 128
    source = bytes(source)
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    _, service, host = _open_exact_session(tmp_path / "session")
    try:
        before = host.shadow_service.session_view(host.shadow_session_id)
        assert not host.state_payload()["jiggle"]["parts"][0]["relative_available"]
        with pytest.raises(ValueError, match="F0-FF"):
            _retain(host, .5)
        after = host.shadow_service.session_view(host.shadow_session_id)
        assert (before.revision, before.undo_count) == (after.revision, after.undo_count)
        assert shadow_output(host) == source
        set_jiggle(host)
        set_jiggle(host, reset=True)
        assert shadow_output(host) == source
    finally:
        host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


@pytest.mark.parametrize("bad", [True, None, "0.5", -.01, 1.01, float("nan")])
def test_invalid_relative_fraction_is_rejected(bad):
    with pytest.raises(ValueError):
        PacJiggleRule.from_dict({"below_y": None, "retained": bad})

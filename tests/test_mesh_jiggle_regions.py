"""Independent weighted regions through the existing Jiggle authoring path."""
from contextlib import ExitStack
from dataclasses import replace
import copy
import struct
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.jiggle import PacJiggleRule
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.modding.pac_jiggle import apply_pac_jiggle_rules, reduce_pac_jiggle_byte
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from cdmw.ui.mesh_editor.replacement_flow import prepare_replacement_event
from tests.test_mesh_jiggle import jiggle_fixture, jiggle_session, archive_context, shadow_output
from tests.test_mesh_jiggle_decoded_preview import rig_session
from tests.test_mesh_rust_replacement import command
from tests.test_mesh_rust_authoring_exact_output import _request
from tests.test_mesh_editor_replacement_sequences import open_editor
from tests.test_mesh_cloth_guide_authoring import guide_host
from tests.test_pac_cloth_guide_builder import guide_free_pac


def edit_region(host, slots, retained=.5, *, reset=False):
    key = host.state_payload()["jiggle"]["parts"][0]["id"]
    return command(host, "replacement_jiggle", {"part_ids": [key], "bone_slots": slots,
        "rule": {"below_y": None, "retained": retained}, "reset": reset, **archive_context(host)})


def test_regional_contribution_blends_skin_weights_and_keeps_source_limits():
    rule = PacJiggleRule(None, 1., ((1, 0.), (3, .5)))
    assert rule.contribution((0, 1, 3), (2., 4., 4.)) == pytest.approx(.4)
    assert rule.contribution((0,), (1.,)) == 1
    assert PacJiggleRule.from_dict(rule.to_dict()) == rule
    for value in range(256):
        assert reduce_pac_jiggle_byte(value, .4) & 0xF0 == value & 0xF0
    assert reduce_pac_jiggle_byte(0xFF, .4) == 0xFF


@pytest.mark.parametrize("rows", [[], [[1, .5], [1, .2]], [[True, .5]], [[1024, .5]], [[1, float("nan")]], [[1, 1.1]], [[1, True]], [[1]]])
def test_invalid_region_rules_are_rejected(rows):
    with pytest.raises(ValueError, match="regional"):
        PacJiggleRule.from_dict({"below_y": None, "retained": 1., "bone_retained": rows})


def test_regional_output_changes_only_contribution_at_every_lod():
    source = jiggle_fixture()
    rule = PacJiggleRule(.5, 1., ((0, 0.), (1, .25), (2, .4), (3, .6)))
    output = apply_pac_jiggle_rules(source, {0: rule})
    addresses, changed_lods = set(), set()
    for lod, mesh in enumerate(pac_cloth_lods(source)):
        part = mesh.submeshes[0]
        for vertex, offset in enumerate(part.source_vertex_offsets):
            if part.vertices[vertex][1] < .5:
                amount = rule.contribution(part.bone_indices[vertex], part.bone_weights[vertex])
                assert output[offset + 38] == reduce_pac_jiggle_byte(source[offset + 38], amount)
                addresses.add(offset + 38)
                if output[offset + 38] != source[offset + 38]:
                    changed_lods.add(lod)
    assert changed_lods == set(range(4))
    assert all(a == b or i in addresses for i, (a, b) in enumerate(zip(source, output, strict=True)))


def test_region_edits_accumulate_restore_independently_and_follow_history(rig_session):
    source, session, host = rig_session
    regions = host.state_payload()["jiggle"]["bone_regions"]
    assert [row["slots"] for row in regions] == [[0, 2, 4, 6], [1, 3, 5, 7]]
    edit_region(host, regions[0]["slots"], .2)
    first = shadow_output(host)
    edit_region(host, regions[1]["slots"], .7)
    rule = session.replacement_state.parts[0].jiggle
    assert rule.retained == 1
    assert dict(rule.bone_retained) == {**dict.fromkeys(regions[0]["slots"], .2), **dict.fromkeys(regions[1]["slots"], .7)}
    both = shadow_output(host)
    assert both == apply_pac_jiggle_rules(source, {0: rule})
    preview = host.state_payload()["jiggle"]["parts"][0]["preview"]
    offsets = pac_cloth_lods(source)[0].submeshes[0].source_vertex_offsets
    assert preview["current_bytes"] == [both[offset + 38] for offset in offsets]
    command(host, "undo")
    assert shadow_output(host) == first
    command(host, "redo")
    assert shadow_output(host) == both
    edit_region(host, regions[0]["slots"], reset=True)
    assert dict(session.replacement_state.parts[0].jiggle.bone_retained) == dict.fromkeys(regions[1]["slots"], .7)
    edit_region(host, regions[1]["slots"], reset=True)
    assert session.replacement_state.parts[0].jiggle is None
    assert shadow_output(host) == source


def test_region_rule_keeps_height_and_whole_part_apply_clears_overrides(rig_session):
    _, session, host = rig_session
    key = host.state_payload()["jiggle"]["parts"][0]["id"]
    args = {"part_ids": [key], "rule": {"below_y": .5, "retained": .3}, **archive_context(host)}
    command(host, "replacement_jiggle", args)
    edit_region(host, [0, 2, 4, 6], .9)
    assert session.replacement_state.parts[0].jiggle == PacJiggleRule(.5, .3, tuple((i, .9) for i in (0, 2, 4, 6)))
    command(host, "replacement_jiggle", args)
    assert session.replacement_state.parts[0].jiggle == PacJiggleRule(.5, .3)


def test_region_draft_requires_its_version_and_reopens_without_the_skeleton(rig_session, tmp_path):
    source, session, host = rig_session
    edit_region(host, [0, 2, 4, 6], .4)
    state = session.replacement_state
    payload = save_replacement_state(state, tmp_path, tmp_path)
    assert payload["version"] == 15
    assert load_replacement_state(payload, tmp_path) == state
    combined = replace(state, weapon_collisions=True)
    assert load_replacement_state(save_replacement_state(combined, tmp_path, tmp_path), tmp_path) == combined
    downgraded = copy.deepcopy(payload)
    downgraded["version"] = 14
    downgraded["weapon_collisions"] = True
    with pytest.raises(ValueError, match="version 15"):
        load_replacement_state(downgraded, tmp_path)
    stripped = copy.deepcopy(payload)
    del stripped["parts"][0]["jiggle"]["bone_retained"]
    with pytest.raises(ValueError, match="no regional"):
        load_replacement_state(stripped, tmp_path)
    expected = shadow_output(host)
    host.finish(_request(host, "finish_request", 22))
    service = host.authoritative_service
    final = service.capture_export_snapshot(host.authoritative_session_id)
    draft = tmp_path / "saved" / "mesh_layers.json"
    service._session(host.authoritative_session_id).mesh_layer_project_path = draft
    service.retry_mesh_layer_autosave(host.authoritative_session_id)
    with ExitStack() as stack:
        reopened, sid = open_editor(stack, source, final.mesh.path, draft)
        recovered = reopened.capture_export_snapshot(sid)
        assert recovered.replacement_state.parts[0].jiggle == state.parts[0].jiggle
        assert reopened.rebuild_result_from_snapshot(recovered)[0].data == expected
        editor = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=reopened, active_session_id=sid),
                                                tmp_path / "recovered", process_generation=2)
        stack.callback(lambda: editor.cancel() if not editor.closed else None)
        assert editor.shadow_service._session(editor.shadow_session_id).skeleton is None
        assert editor.state_payload()["jiggle"]["bone_regions"] == []
        # The real UI event path must use the retained target, without an archive tab.
        tab = SimpleNamespace(standalone_rust_authoring_session=editor, standalone_rust_closing=False)
        event = prepare_replacement_event(tab, editor, {**_request(editor, "command_request", 23),
            "command": "replacement_jiggle", "arguments": {"part_ids": [state.parts[0].part_id], "reset": True}})
        editor.run_command(event)
        assert shadow_output(editor) == source
        command(editor, "undo")
        assert shadow_output(editor) == expected


@pytest.mark.parametrize("slots", [[], [999], [0, 0], [True], "0"])
def test_bad_region_selection_does_not_change_output(rig_session, slots):
    source, _, host = rig_session
    with pytest.raises(ValueError, match="bone region"):
        edit_region(host, slots)
    assert shadow_output(host) == source


def test_regional_preview_uses_export_quantization_after_skin_weight_edits(rig_session):
    source, session, host = rig_session
    part = session.working_mesh.submeshes[0]
    part.bone_indices[0], part.bone_weights[0] = (0, 1), (.51111, .48889)
    session.revision += 1
    edit_region(host, [0, 2, 4, 6], 0.)
    output = shadow_output(host)
    preview = host.state_payload()["jiggle"]["parts"][0]["preview"]
    offsets = pac_cloth_lods(source)[0].submeshes[0].source_vertex_offsets
    assert preview["current_bytes"] == [output[offset + 38] for offset in offsets]


def test_regional_preview_matches_composed_output_after_guide_skin_reduction(monkeypatch, request):
    def source_with_jiggle():
        data = bytearray(guide_free_pac())
        for level in pac_cloth_lods(data):
            for offset in level.submeshes[0].source_vertex_offsets:
                struct.pack_into("<2I", data, offset + 20, 1 << 10 | 2 << 20, 3 | 4 << 10 | 5 << 20)
                data[offset + 28:offset + 34] = bytes((100, 70, 40, 20, 15, 10))
                data[offset + 38] = 0xF0
        return bytes(data)
    monkeypatch.setattr("tests.test_mesh_cloth_guide_authoring.guide_free_pac", source_with_jiggle)
    case = request.getfixturevalue("guide_host")
    # Slot 0 gains weight when the two smallest influences are removed.
    edit_region(case.host, [0], 0.)
    before = case.host.state_payload()["jiggle"]["parts"][0]["preview"]["current_bytes"]
    command(case.host, "replacement_guides", {**case.args, "reduce_skinning": True})
    output = shadow_output(case.host)
    part = pac_cloth_lods(output)[0].submeshes[0]
    preview = case.host.state_payload()["jiggle"]["parts"][0]["preview"]
    assert preview["current_bytes"] != before
    assert preview["current_bytes"] == [output[offset + 38] for offset in part.source_vertex_offsets]

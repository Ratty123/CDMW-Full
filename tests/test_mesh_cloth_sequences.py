"""Cloth output survives replacement formats, coordinate frames and recovery."""

from contextlib import ExitStack
import hashlib
import json
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
from cdmw.modding.mesh_parser import parse_pac
from cdmw.modding.pac_cloth import pac_cloth_binding, pac_cloth_lods
from cdmw.services.mesh_layer_project_service import load_mesh_layer_project
from cdmw.services.mesh_replacement_import import commit_replacement
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from tests.test_mesh_cloth_influence import apply_rule, cloth_fixture, shadow_output
from tests.test_mesh_editor_replacement_sequences import open_editor, source_variants
from tests.test_mesh_editor_replacement_regressions import _distinct_lods
from tests.test_pac_skin_extra_influences import _record
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_replacement import command


def all_cloth_fixture():
    data = bytearray(cloth_fixture())
    for mesh in pac_cloth_lods(data):
        first, donor = mesh.submeshes[0].source_vertex_offsets[:2]
        for start, end in ((12, 16), (24, 28), (32, 36), (39, 40)):
            data[first + start:first + end] = data[donor + start:donor + end]
    return bytes(data)


@pytest.mark.parametrize("neutral", [False, True])
def test_new_import_after_recovered_draft_preserves_cloth_and_source(tmp_path, monkeypatch, neutral):
    data = all_cloth_fixture()
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: data)
    matrix = (1., 0., 0., 0., 0., 2., 0., 0., 0., 0., 1., 0., 0., 10., 0., 1.)
    appearance = NeutralMeshAppearance("owned", tuple(range(8)), (matrix,) * 8) if neutral else None
    paths = source_variants(tmp_path / "sources")
    _, service, host = _open_exact_session(tmp_path / "host", neutral_appearance=appearance)
    with ExitStack() as stack:
        stack.callback(service.close_edit_session, host.authoritative_session_id, force_without_saving=True)
        stack.callback(lambda: host.cancel() if not host.closed else None)
        apply_rule(host, tmp_path, PacClothRule(.5))
        key = host.state_payload()["cloth"]["parts"][0]["id"]
        command(host, "replacement_choose", {"scope": "entire", "source_path": str(paths[0])})
        command(host, "replacement_apply", {"targets": [key], "materials": "original"})
        expected = shadow_output(host)
        draft = tmp_path / "draft" / "mesh_layers.json"
        host.shadow_service._session(host.shadow_session_id).mesh_layer_project_path = draft
        host.shadow_service.retry_mesh_layer_autosave(host.shadow_session_id)
        host.cancel()
        loaded, sid = open_editor(stack, data, "owned-rust-exact.pac", draft)
        recovered = RustMeshAuthoringSession.create(
            SimpleNamespace(mesh_service=loaded, active_session_id=sid),
            tmp_path / "recovered", process_generation=15)
        stack.callback(lambda: recovered.cancel() if not recovered.closed else None)
        assert shadow_output(recovered) == expected
        for path in (paths[1], paths[3], paths[0]):
            before = shadow_output(recovered)
            command(recovered, "replacement_choose", {"scope": "entire", "source_path": str(path)})
            command(recovered, "replacement_apply", {"targets": [key], "materials": "original"})
            after = shadow_output(recovered)
            command(recovered, "undo")
            assert shadow_output(recovered) == before
            command(recovered, "redo")
            assert shadow_output(recovered) == after
        assert after == expected
        recovered.finish(_request(recovered, "finish_request", 35))
        snapshot = loaded.capture_export_snapshot(sid)
        assert loaded.rebuild_result_from_snapshot(snapshot)[0].data == expected
        assert snapshot.original_data == data


@pytest.mark.parametrize("skin_draft", ["unedited", "current", "legacy"])
def test_part_reorder_keeps_cloth_rules_and_replacement_bound_to_target(tmp_path, monkeypatch, skin_draft):
    skin_edit = skin_draft != "unedited"
    data = bytearray(_distinct_lods())
    for level in pac_cloth_lods(data):
        for index, part in enumerate(level.submeshes):
            record = _record(palette=(1, 2, 3, 4, 5 + index * 10, 6 + index * 10),
                             weights=(60, 50, 40, 30, 20, 10, 25, 20), extra=(0., 7.), gate=0)
            for offset in part.source_vertex_offsets:
                for start, end in ((12, 16), (20, 36), (39, 40)):
                    data[offset + start:offset + end] = record[start:end]
    data = bytes(data)
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: data)
    paths = source_variants(tmp_path / "sources")
    data, service, host = _open_exact_session(tmp_path / "host", resolved_rig=skin_edit)
    try:
        if skin_edit:
            command(host, "rig_select_bone", {"bone_index": 7})
            command(host, "rig_adjust_weight", {
                "selection": {"vertices_by_submesh": {"0": [0]}, "source_indices": []}, "delta": 1,
            })
        apply_rule(host, tmp_path, PacClothRule(.5))
        shadow, sid = host.shadow_service, host.shadow_session_id
        snapshot = shadow.capture_export_snapshot(sid)
        first, second = (part.part_id for part in snapshot.replacement_state.parts)
        expected = shadow_output(host)
        snapshot.mesh.submeshes.reverse()
        commit_replacement(shadow, snapshot, snapshot.mesh, snapshot.replacement_state, label="Reorder parts")
        assert shadow_output(host) == expected
        rows = host.state_payload()["cloth"]["parts"]
        assert [(part["id"], part["index"]) for part in rows] == [(second, 0), (first, 1)]
        command(host, "replacement_choose", {"scope": "selected", "source_path": str(paths[1]), "part_ids": [second]})
        command(host, "replacement_apply", {"targets": [second], "materials": "original"})
        command(host, "replacement_cloth", {"part_ids": [second], "rule": PacClothRule(.25).to_dict()})
        output = shadow_output(host)
        original_levels = pac_cloth_lods(data)
        for lod, level in enumerate(pac_cloth_lods(output)):
            expected_indices = list(original_levels[lod].submeshes[0].bone_indices)
            if skin_edit and lod == 0:
                expected_indices[0] = (7,)
            assert level.submeshes[0].bone_indices == expected_indices
            assert level.submeshes[0].vertices == original_levels[lod].submeshes[0].vertices
            if lod > 0:
                assert level.submeshes[0].bone_weights == original_levels[lod].submeshes[0].bone_weights
            for index, part in enumerate(level.submeshes):
                for offset in part.source_vertex_offsets:
                    gate, guides, _ = pac_cloth_binding(output, offset)
                    assert gate == (32 if index == 0 else 47)
                    assert guides[:2] == (5 + index * 10, 6 + index * 10)
        command(host, "undo")
        command(host, "redo")
        assert shadow_output(host) == output
        for key in (first, second):
            command(host, "replacement_include", {"part_ids": [key], "included": False})
            command(host, "replacement_include", {"part_ids": [key], "included": True})
            assert shadow_output(host) == output
        draft = tmp_path / "draft" / "mesh_layers.json"
        shadow._session(sid).mesh_layer_project_path = draft
        shadow.retry_mesh_layer_autosave(sid)
        descriptor = json.loads(draft.read_text())
        manifest = draft.parent / descriptor["current_generation"] / "generation.json"
        generation = json.loads(manifest.read_text())
        retained = next(part for part in generation["snapshot"]["submeshes"]
                        if part["metadata"]["extra_attrs"]["_cdmw_replacement_part_id"] == first)
        assert retained["metadata"]["source_vertex_stride"] == 40
        if skin_draft == "legacy":
            for part in generation["snapshot"]["submeshes"]:
                for name in tuple(part["metadata"]):
                    if name.startswith("source_"):
                        part["metadata"].pop(name)
            manifest.write_text(json.dumps(generation))
            descriptor["current_generation_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
            draft.write_text(json.dumps(descriptor))
        with ExitStack() as stack:
            loaded, loaded_sid = open_editor(stack, data, "owned-rust-exact.pac", draft)
            recovered = RustMeshAuthoringSession.create(
                SimpleNamespace(mesh_service=loaded, active_session_id=loaded_sid),
                tmp_path / "recovered", process_generation=16)
            stack.callback(recovered.cancel)
            assert shadow_output(recovered) == output
            command(recovered, "replacement_cloth", {"part_ids": [first], "rule": PacClothRule(0).to_dict()})
            command(recovered, "undo")
            assert shadow_output(recovered) == output
        host.finish(_request(host, "finish_request", 35))
        snapshot = service.capture_export_snapshot(host.authoritative_session_id)
        assert service.rebuild_result_from_snapshot(snapshot)[0].data == output
        assert snapshot.original_data == data
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


@pytest.mark.parametrize("neutral", [False, True])
def test_cloth_survives_format_switches_draft_finish_and_reopen(tmp_path, monkeypatch, neutral):
    data = all_cloth_fixture()
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: data)
    matrix = (1., 0., 0., 0., 0., 2., 0., 0., 0., 0., 1., 0., 0., 10., 0., 1.)
    appearance = NeutralMeshAppearance("owned", tuple(range(8)), (matrix,) * 8) if neutral else None
    paths = source_variants(tmp_path / "sources")
    _, service, host = _open_exact_session(tmp_path / "host", neutral_appearance=appearance)
    with ExitStack() as stack:
        stack.callback(service.close_edit_session, host.authoritative_session_id, force_without_saving=True)
        stack.callback(lambda: host.cancel() if not host.closed else None)
        apply_rule(host, tmp_path, PacClothRule(.5))
        key = host.state_payload()["cloth"]["parts"][0]["id"]
        previous = shadow_output(host)
        by_source = {}
        for step, index in enumerate((0, 1, 2, 3, 0)):
            command(host, "replacement_choose", {"scope": "entire", "source_path": str(paths[index])})
            command(host, "replacement_apply", {"targets": [key], "materials": "original"})
            current = shadow_output(host)
            if index in by_source:
                assert current == by_source[index]
            by_source[index] = current
            for level in pac_cloth_lods(current):
                assert all(pac_cloth_binding(current, offset)[0] == 32
                           for offset in level.submeshes[0].source_vertex_offsets)
            command(host, "undo")
            assert shadow_output(host) == previous
            command(host, "redo")
            assert shadow_output(host) == current
            command(host, "replacement_fit")
            command(host, "replacement_reset")
            assert shadow_output(host) == current
            previous = current
            if step == 2:
                draft = tmp_path / "draft" / "mesh_layers.json"
                host.shadow_service._session(host.shadow_session_id).mesh_layer_project_path = draft
                host.shadow_service.retry_mesh_layer_autosave(host.shadow_session_id)
                loaded, sid = open_editor(stack, data, "owned-rust-exact.pac", draft)
                assert loaded.rebuild_result_from_snapshot(loaded.capture_export_snapshot(sid))[0].data == current
        host.finish(_request(host, "finish_request", 23))
        final = service.capture_export_snapshot(host.authoritative_session_id)
        assert service.rebuild_result_from_snapshot(final)[0].data == previous
        reopened = RustMeshAuthoringSession.create(
            SimpleNamespace(mesh_service=service, active_session_id=host.authoritative_session_id),
            tmp_path / "reopened", process_generation=12)
        stack.callback(reopened.cancel)
        assert shadow_output(reopened) == previous
        apply_rule(reopened, tmp_path, PacClothRule(), reset=True)
        restored = shadow_output(reopened)
        for level in pac_cloth_lods(restored):
            assert all(pac_cloth_binding(restored, offset)[0] == 0
                       for offset in level.submeshes[0].source_vertex_offsets)
        command(reopened, "undo")
        assert shadow_output(reopened) == previous


@pytest.mark.parametrize("fault", ["missing_part_field", "null_part", "huge_cloth_value",
                                   "duplicate_part", "invalid_target"])
def test_malformed_cloth_generation_recovers_previous_draft(tmp_path, monkeypatch, fault):
    data = cloth_fixture()
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: data)
    _, service, host = _open_exact_session(tmp_path / "host")
    try:
        apply_rule(host, tmp_path, PacClothRule(.5))
        shadow = host.shadow_service
        expected = shadow_output(host)
        draft = tmp_path / "draft" / "mesh_layers.json"
        shadow._session(host.shadow_session_id).mesh_layer_project_path = draft
        shadow.retry_mesh_layer_autosave(host.shadow_session_id)
        previous = json.loads(draft.read_text())["current_generation"]
        shadow.retry_mesh_layer_autosave(host.shadow_session_id)
        descriptor = json.loads(draft.read_text())
        assert descriptor["previous_generation"] == previous
        path = draft.parent / descriptor["current_generation"] / "generation.json"
        current = json.loads(path.read_text())
        if fault == "missing_part_field":
            current["replacement"]["parts"][0].pop("part_id")
        elif fault == "null_part":
            current["replacement"]["parts"][0] = None
        elif fault == "huge_cloth_value":
            current["replacement"]["parts"][0]["cloth"]["fixed_above"] = 10 ** 400
        elif fault == "duplicate_part":
            current["replacement"]["parts"].append(dict(current["replacement"]["parts"][0]))
        else:
            current["replacement"]["parts"][0]["target_index"] = -1
        path.write_text(json.dumps(current))
        descriptor["current_generation_manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        draft.write_text(json.dumps(descriptor))
        loaded = load_mesh_layer_project(parse_pac(data, "owned-rust-exact.pac"), draft,
            expected_source_asset_sha256=hashlib.sha256(data).hexdigest())
        assert loaded["loaded_generation"] == previous
        assert loaded["replacement_state"].parts[0].cloth == PacClothRule(.5)
        with ExitStack() as stack:
            reopened, sid = open_editor(stack, data, "owned-rust-exact.pac", draft)
            assert reopened.rebuild_result_from_snapshot(reopened.capture_export_snapshot(sid))[0].data == expected
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)

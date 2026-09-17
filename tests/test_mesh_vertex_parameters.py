from __future__ import annotations

import copy
import threading
from unittest.mock import patch

import pytest

from cdmw.domain.mesh.vertex_parameters import channel_edit, edit_weights, selected_vertices
from cdmw.services.mesh_vertex_parameters import inspection_token
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request


@pytest.fixture
def editor(tmp_path):
    _, _, session = _open_exact_session(tmp_path / "editor", resolved_rig=True)
    yield session
    session.cancel()


def select(editor, **selection):
    request = _request(editor, "command_request", 1)
    request.update(command="select", arguments={"selection": selection, "operation": "replace"})
    editor.run_command(request)


def inspect(editor, **args):
    request = _request(editor, "vertex_inspect", 2)
    request["arguments"] = {"token": inspection_token(editor), **args}
    return editor.vertex_inspect(request)


def edit(editor, edits, token=None):
    request = _request(editor, "command_request", 3)
    request.update(command="vertex_edit", arguments={"token": token or inspection_token(editor), "edits": edits})
    return editor.run_command(request)


def shadow(editor):
    return editor.shadow_service._session(editor.shadow_session_id)


def test_inspect_exact_host_values_without_state_history_or_documents(editor):
    select(editor, vertices_by_submesh={"0": [0]})
    session = shadow(editor)
    token = inspection_token(editor)
    history = (len(session.undo_stack), len(session.redo_stack))
    with patch.object(type(editor), "state_payload", side_effect=AssertionError("inspection published state")):
        result = inspect(editor)
    row = result["rows"][0]
    assert row["position"] == session.working_mesh.submeshes[0].vertices[0]
    assert row["uv0"] == session.working_mesh.submeshes[0].uvs[0]
    assert row["source"]["original_index"] == 0
    assert row["weights"]["resolved"]
    assert result["space"] == "Model editing space"
    assert result["token"] == token == inspection_token(editor)
    assert history == (len(session.undo_stack), len(session.redo_stack))


def test_selection_union_missing_channels_and_empty_selection(editor):
    assert inspect(editor)["count"] == 0
    select(editor, vertices_by_submesh={"0": [0]}, edges_by_submesh={"0": [[0, 1]]}, faces_by_submesh={"0": [0]})
    session = shadow(editor)
    selected = selected_vertices(session.working_mesh, session.selection)
    assert selected[0] == (0, 1, 2)
    session.working_mesh.submeshes[0].normals = []
    result = inspect(editor, page_size=2)
    assert len(result["rows"]) == 2 and result["count"] == 3
    assert result["rows"][0]["normal"] is None
    assert not result["capabilities"]["normal"]["editable"]
    assert result["summaries"]["position"]["mixed"][0]
    assert len(inspect(editor, page=1, page_size=2)["rows"]) == 1
    with pytest.raises(ValueError, match="128"):
        inspect(editor, page_size=129)


def test_atomic_multi_channel_edit_undo_redo_and_untouched_data(editor):
    select(editor, vertices_by_submesh={"0": [0, 1]})
    session = shadow(editor)
    before = copy.deepcopy(session.working_mesh)
    count = len(session.undo_stack)
    result = edit(editor, {"position": {"mode": "offset", "values": [0.125, None, None]},
                           "uv0": {"mode": "set", "values": [2.5, None]},
                           "normal": {"mode": "set", "values": [0, 3, 4]}})
    assert result["result"]["changed"]
    assert len(session.undo_stack) == count + 1
    part = session.working_mesh.submeshes[0]
    assert part.vertices[0] == (before.submeshes[0].vertices[0][0] + 0.125, *before.submeshes[0].vertices[0][1:])
    assert part.normals[0] == (0, 0.6, 0.8)
    assert part.uvs[0][0] == 2.5
    assert part.vertices[2:] == before.submeshes[0].vertices[2:]
    assert part.faces == before.submeshes[0].faces
    assert part.bone_weights == before.submeshes[0].bone_weights
    assert part.material == before.submeshes[0].material
    for command in ("undo", "redo"):
        request = _request(editor, "command_request", 4)
        request.update(command=command, arguments={})
        editor.run_command(request)
        assert session.working_mesh.submeshes[0].uvs[0][0] == (before.submeshes[0].uvs[0][0] if command == "undo" else 2.5)


@pytest.mark.parametrize("edits", [
    {"normal": {"mode": "set", "values": [0, 0, 0]}},
    {"uv0": {"mode": "set", "values": [65505, None]}},
    {"position": {"mode": "offset", "values": [float("nan"), None, None]}},
    {"weights": {"mode": "set", "bone": 9000, "value": 0.5}},
])
def test_rejected_batch_preserves_mesh_and_history(editor, edits):
    select(editor, source_indices=[0])
    session = shadow(editor)
    before = copy.deepcopy(session.working_mesh)
    token = inspection_token(editor)
    history = len(session.undo_stack), len(session.redo_stack)
    edits = {"position": {"mode": "offset", "values": [0.1, None, None]}, **edits}
    with pytest.raises(ValueError):
        edit(editor, edits)
    assert session.working_mesh.submeshes == before.submeshes
    assert token == inspection_token(editor)
    assert history == (len(session.undo_stack), len(session.redo_stack))


def test_stale_target_and_noop(editor):
    select(editor, vertices_by_submesh={"0": [0]})
    token = inspect(editor)["token"]
    select(editor, vertices_by_submesh={"0": [1]})
    changes = {"position": {"mode": "offset", "values": [0, None, None]}}
    with pytest.raises(ValueError, match="changed"):
        edit(editor, changes, token)
    fresh = inspection_token(editor)
    assert not edit(editor, changes)["result"]["changed"]
    assert fresh == inspection_token(editor)


def test_cancelled_inspection_and_unresolved_bones(editor):
    event = threading.Event()
    event.set()
    request = _request(editor, "vertex_inspect", 5)
    request["arguments"] = {"token": inspection_token(editor)}
    with pytest.raises(RuntimeError, match="cancelled"):
        editor.vertex_inspect(request, stop_event=event)
    select(editor, source_indices=[0])
    shadow(editor).skeleton = None
    result = inspect(editor)
    assert not result["capabilities"]["weights"]["editable"]
    assert not result["rows"][0]["weights"]["resolved"]


def test_numeric_rules_and_weight_redistribution():
    assert channel_edit((1, 2, 3), {"mode": "set", "values": [None, 8, None]}, channel="position") == (1, 8, 3)
    assert channel_edit((1, 2), {"mode": "offset", "values": [-3, None]}, channel="uv0", uv_limit=65504) == (-2, 2)
    indices, weights = edit_weights((0, 1, 2), (0.5, 0.3, 0.2), {"mode": "set", "value": 0.75}, slot=0, capacity=4)
    assert indices == (0, 1, 2)
    assert weights == pytest.approx((0.75, 0.15, 0.1))
    with pytest.raises(ValueError, match="last influence"):
        edit_weights((0,), (1.0,), {"mode": "remove"}, slot=0, capacity=4)
    with pytest.raises(ValueError, match="1 to 4"):
        edit_weights((0, 1, 2, 3), (0.25,) * 4, {"mode": "set", "value": 0.1}, slot=4, capacity=4)


@pytest.mark.parametrize("extension", ["pam", "pamlod"])
def test_inspection_and_edits_follow_static_format_capabilities(tmp_path, extension):
    from types import SimpleNamespace
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_service import MeshService
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from cdmw.domain.mesh.replacement import ReplacementFile
    from cdmw.services.mesh_replacement_import import initial_replacement_state, prepare_import, compose_import, commit_replacement
    from tests.test_mesh_editor_replacement import source_obj
    from tests.test_mesh_editor_replacement_formats import static_fixture
    data = static_fixture(extension)
    mesh = parse_mesh(data, f"owned.{extension}")
    mesh.lod_levels = []  # The normal authoring handoff exposes editable LOD0.
    mesh._cdmw_original_data = data
    mesh._cdmw_no_op_roundtrip_report = {"result": "PASS", "byte_identical": True, "unexpected_differences": 0}
    service = MeshService()
    sid = service.open_edit_session(mesh).session_id
    host = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=service, active_session_id=sid),
                                          tmp_path / "static", process_generation=17)
    try:
        select(host, vertices_by_submesh={"0": [0]})
        result = inspect(host)
        assert not result["capabilities"]["position"]["editable"]
        assert "source mapping" in result["capabilities"]["position"]["reason"]
        snapshot = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        key = initial_replacement_state(snapshot).parts[0].part_id
        dependencies = (ReplacementFile("owned.pamlod", static_fixture("pamlod")),) if extension == "pam" else ()
        pending = prepare_import(snapshot, source_obj(tmp_path), target_part_ids=(key,), dependencies=dependencies)
        candidate, state = compose_import(pending, (key,))
        commit_replacement(host.shadow_service, snapshot, candidate, state, label="Replace")
        select(host, vertices_by_submesh={"0": [0]})
        result = inspect(host)
        assert result["capabilities"]["position"]["editable"]
        assert result["capabilities"]["uv0"]["editable"]
        assert not result["capabilities"]["normal"]["editable"]
        assert not result["capabilities"]["weights"]["editable"]
        assert result["rows"][0]["position"] == shadow(host).working_mesh.submeshes[0].vertices[0]
        edit(host, {"uv0": {"mode": "set", "values": [2.5, -.5]}})
        host.finish(_request(host, "finish_request", 18))
        output, report = service.rebuild_result_from_snapshot(service.capture_export_snapshot(sid))
        assert report.validation_status == "passed"
        assert parse_mesh(output.data, f"owned.{extension}").submeshes[0].uvs[0] == pytest.approx((2.5, -.5))
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(sid, force_without_saving=True)


@pytest.mark.parametrize("cloth", [False, True])
@pytest.mark.parametrize("neutral", [False, True])
def test_vertex_edit_draft_finish_reparse_preserves_other_records(tmp_path, monkeypatch, cloth, neutral):
    from contextlib import ExitStack
    from types import SimpleNamespace
    from cdmw.domain.mesh.cloth import PacClothRule
    from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
    from cdmw.modding.mesh_parser import parse_pac
    from cdmw.modding.pac_cloth import pac_cloth_binding
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from tests.test_mesh_cloth_sequences import all_cloth_fixture
    from tests.test_mesh_cloth_influence import apply_rule
    from tests.test_mesh_rust_replacement import command
    matrix = (1., 0., 0., 0., 0., 2., 0., 0., 0., 0., 1., 0., 0., 10., 0., 1.)
    appearance = NeutralMeshAppearance("owned", tuple(range(8)), (matrix,) * 8) if neutral else None
    if cloth:
        monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: all_cloth_fixture())
    data, service, host = _open_exact_session(tmp_path / "host", resolved_rig=True, neutral_appearance=appearance)
    with ExitStack() as stack:
        stack.callback(service.close_edit_session, host.authoritative_session_id, force_without_saving=True)
        stack.callback(lambda: host.cancel() if not host.closed else None)
        if cloth:
            apply_rule(host, tmp_path, PacClothRule(.5, fixed_above=11.0 if neutral else .75, fade=.5))
        select(host, vertices_by_submesh={"0": [0, 1]})
        before = copy.deepcopy(shadow(host).working_mesh)
        base_snapshot = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        baseline = host.shadow_service.rebuild_result_from_snapshot(host._source_coordinate_snapshot(base_snapshot))[0].data
        edits = {"position": {"mode": "offset", "values": [.125, None, None]},
                 "uv0": {"mode": "set", "values": [2.5, -.75]},
                 "normal": {"mode": "set", "values": [0, 0, 2]}}
        if not cloth:
            edits["weights"] = {"mode": "set", "bone": 7, "value": .25}
        edit(host, edits)
        assert shadow(host).working_mesh.submeshes[0].uvs[:2] == [(2.5, -.75)] * 2
        snapshot = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        assert snapshot.mesh.submeshes[0].uvs[:2] == [(2.5, -.75)] * 2
        output = host.shadow_service.rebuild_result_from_snapshot(host._source_coordinate_snapshot(snapshot))[0].data
        current = parse_pac(output, "owned-rust-exact.pac")
        old = parse_pac(baseline, "owned-rust-exact.pac")
        a, b = old.submeshes[0], current.submeshes[0]
        assert b.uvs[:2] == [(2.5, -.75)] * 2
        assert b.normals[0] == pytest.approx((0, 0, 1), abs=.003)
        # The x axis is unchanged by the synthetic neutral appearance matrix.
        assert b.vertices[0][0] == pytest.approx(before.submeshes[0].vertices[0][0] + .125, abs=.0001)
        assert b.material == a.material and b.faces == a.faces
        assert current.lod_levels[1:] == old.lod_levels[1:]
        for vertex in range(2, len(a.vertices)):
            x, y = a.source_vertex_offsets[vertex], b.source_vertex_offsets[vertex]
            assert baseline[x+6:x+40] == output[y+6:y+40]
            assert a.vertices[vertex] == pytest.approx(b.vertices[vertex], abs=.0001)
        if cloth:
            inspected = inspect(host)
            assert "neutral" in inspected["space"] if neutral else "neutral" not in inspected["space"]
            for row in inspected["rows"]:
                saved = pac_cloth_binding(output, b.source_vertex_offsets[row["vertex"]])
                assert row["cloth"]["effective_influence"] == (63 - saved[0]) / 63 if saved else row["cloth"]["effective_influence"] == 0
                original = pac_cloth_binding(data, parse_pac(data).submeshes[0].source_vertex_offsets[row["vertex"]])
                assert row["cloth"]["guide_indices"] == list(original[1])
            assert b.bone_weights == a.bone_weights
        else:
            assert b.bone_weights[0][-1] == pytest.approx(.25, abs=.004)
        command(host, "undo")
        assert host.shadow_service.rebuild_result_from_snapshot(host._source_coordinate_snapshot(host.shadow_service.capture_export_snapshot(host.shadow_session_id)))[0].data == baseline
        command(host, "redo")
        draft = tmp_path / "draft" / "mesh_layers.json"
        if neutral and not cloth:
            # Ordinary neutral sessions save source coordinates at Finish; only
            # replacement drafts retain an explicit neutral-coordinate frame.
            host.finish(_request(host, "finish_request", 31))
            draft_service, draft_sid = service, host.authoritative_session_id
        else:
            draft_service, draft_sid = host.shadow_service, host.shadow_session_id
        draft_service._session(draft_sid).mesh_layer_project_path = draft
        draft_service.retry_mesh_layer_autosave(draft_sid)
        if not host.closed:
            host.cancel()
        from cdmw.services.mesh_service import MeshService
        seed = parse_pac(data, "owned-rust-exact.pac")
        seed._cdmw_original_data = data
        seed._cdmw_mesh_layer_project_path = str(draft)
        seed._cdmw_mesh_asset_inferred_bone_count = 8
        seed._cdmw_no_op_roundtrip_report = service._session(host.authoritative_session_id).no_op_roundtrip_report
        loaded = MeshService()
        sid = loaded.open_edit_session(seed).session_id
        assert loaded.working_mesh(sid).submeshes[0].uvs[:2] == [(2.5, -.75)] * 2
        stack.callback(loaded.close_edit_session, sid, force_without_saving=True)
        loaded.attach_skeleton(sid, service._session(host.authoritative_session_id).skeleton)
        loaded._session(sid).neutral_appearance = appearance
        loaded._session(sid).no_op_roundtrip_report = service._session(host.authoritative_session_id).no_op_roundtrip_report
        recovered = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=loaded, active_session_id=sid), tmp_path / "recovered", process_generation=16)
        assert shadow(recovered).edit_operations
        assert shadow(recovered).working_mesh.submeshes[0].uvs[:2] == [(2.5, -.75)] * 2
        stack.callback(lambda: recovered.cancel() if not recovered.closed else None)
        recovered.finish(_request(recovered, "finish_request", 33))
        final = loaded.capture_export_snapshot(sid)
        assert final.mesh.submeshes[0].uvs[:2] == [(2.5, -.75)] * 2
        assert final.mesh.submeshes[0].vertices[0][0] == pytest.approx(before.submeshes[0].vertices[0][0] + .125)
        assert loaded.rebuild_result_from_snapshot(final)[0].data == output
        assert final.original_data == data


def test_weight_remove_normalize_offset_and_noop(editor):
    select(editor, vertices_by_submesh={"0": [0]})
    edit(editor, {"weights": {"mode": "set", "bone": 7, "value": .25}})
    row = inspect(editor)["rows"][0]["weights"]
    assert row["influences"][-1]["bone"] == 7
    edit(editor, {"weights": {"mode": "offset", "bone": 7, "value": .25}})
    assert inspect(editor)["rows"][0]["weights"]["influences"][-1]["weight"] == .5
    token = inspection_token(editor)
    assert not edit(editor, {"weights": {"mode": "offset", "bone": 7, "value": 0}})["result"]["changed"]
    assert token == inspection_token(editor)
    edit(editor, {"weights": {"mode": "remove", "bone": 7}})
    edit(editor, {"weights": {"mode": "normalize"}})
    assert inspect(editor)["rows"][0]["weights"]["total"] == pytest.approx(1)


def test_inspection_generated_mapping_requires_original_provenance(editor):
    from cdmw.domain.mesh.topology import SubmeshTopologyProvenance, VertexOrigin, TOPOLOGY_PROVENANCE_VERSION
    select(editor, source_indices=[0])
    part = shadow(editor).working_mesh.submeshes[0]
    part.topology_provenance = SubmeshTopologyProvenance(TOPOLOGY_PROVENANCE_VERSION, len(part.vertices), len(part.faces),
        tuple([VertexOrigin((0, 1), (.5, .5))] + [VertexOrigin((i,), (1.,)) for i in range(1, len(part.vertices))]), tuple(range(len(part.faces))))
    result = inspect(editor)
    assert result["rows"][0]["source"]["kind"] == "generated"
    assert result["rows"][0]["source"]["original_index"] is None
    assert not result["rows"][0]["cloth"]["available"]
    assert result["rows"][1]["source"]["original_index"] == 1
    # A topology record alone cannot identify its original part.
    part.source_descriptor_offset = -1
    result = inspect(editor)
    assert all(row["source"]["original_index"] is None for row in result["rows"])
    assert all(row["source"]["part"] is None for row in result["rows"])
    assert result["rows"][0]["source"]["parents"] == []


def test_inspection_replacement_mapping_and_stale_edit(editor, tmp_path):
    from tests.test_mesh_rust_replacement import command, prepare_source
    select(editor, vertices_by_submesh={"0": [0]})
    old_token = inspect(editor)["token"]
    pending = prepare_source(editor, tmp_path)["state"]["replacement"]["pending"]
    command(editor, "replacement_apply", {"targets": [pending["targets"][0]["id"]], "materials": "original"})
    select(editor, source_indices=[0])
    part = shadow(editor).working_mesh.submeshes[0]
    result = inspect(editor)
    assert result["count"] == len(part.vertices)
    # This import has no persisted donor map. Do not infer one from proximity.
    assert all(row["source"]["kind"] == "replaced" for row in result["rows"])
    assert all(row["source"]["original_index"] is None for row in result["rows"])
    with pytest.raises(ValueError, match="changed"):
        edit(editor, {"position": {"mode": "offset", "values": [1, None, None]}}, old_token)
    # A fixture with explicit target-donor authority can expose those indices.
    from cdmw.modding.mesh_skinning import SOURCE_VERTEX_MAP_TARGET_DONOR
    part.source_vertex_map_authority = SOURCE_VERTEX_MAP_TARGET_DONOR
    part.source_vertex_map = [0] * len(part.vertices)
    part.source_descriptor_offset = shadow(editor).base_mesh.submeshes[0].source_descriptor_offset
    result = inspect(editor)
    assert all(row["source"]["kind"] == "replacement donor" for row in result["rows"])
    assert all(row["source"]["original_index"] == 0 for row in result["rows"])


def test_mixed_capability_rejection_keeps_redo(editor):
    from tests.test_mesh_rust_replacement import command
    select(editor, vertices_by_submesh={"0": [0]})
    edit(editor, {"position": {"mode": "offset", "values": [.1, None, None]}})
    command(editor, "undo")
    session = shadow(editor)
    count = len(session.redo_stack)
    # A selected part with no UV channel must reject the entire position+UV batch.
    session.working_mesh.submeshes[0].uvs = []
    before = copy.deepcopy(session.working_mesh)
    with pytest.raises(ValueError, match="missing"):
        edit(editor, {"position": {"mode": "offset", "values": [.2, None, None]}, "uv0": {"mode": "set", "values": [1, 1]}})
    assert session.working_mesh.submeshes == before.submeshes
    assert len(session.redo_stack) == count == 1

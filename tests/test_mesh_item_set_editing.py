"""Owned PACs exercise set ownership; no installed archives are written."""
from dataclasses import replace
import copy
import threading

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_asset_context import ASSET_ATTRIBUTE, PART_ATTRIBUTE, ORIGIN_ATTRIBUTE, item_set_bindings
from cdmw.services.mesh_item_set_editing import compose_item_set, item_set_snapshots, set_item_set_inclusion
from cdmw.services.mesh_archive_refit import save_archive_refit_context, load_archive_refit_context
from cdmw.services.mesh_service import MeshService
from tests.test_mesh_item_set_references import _sources
from types import SimpleNamespace


def _set(tmp_path, *, two_parts=False, qualified=False):
    source, service, controller, contexts = _sources(tmp_path)
    if two_parts:
        from tests.test_static_mesh_replacer_preview import _minimal_two_part_pac_original
        from tests.test_mesh_rust_authoring import _prepared_dds_entry
        source, _ = _minimal_two_part_pac_original()
        raw = bytearray(source)
        for part in parse_pac(source, "fixture.pac").submeshes:
            for offset in part.source_vertex_offsets:
                raw[offset + 28] = 255
        source = bytes(raw)
        service.close_edit_session(controller.active_session_id, force_without_saving=True)
        mesh = service.load_mesh_bytes(source, "upper.pac", run_roundtrip=True)
        controller.active_session_id = service.open_edit_session(mesh, mode="edit", load_layer_project=False).session_id
        contexts = tuple(replace(context, selected_entry=_prepared_dds_entry(tmp_path, name, source))
                         for context, name in zip(contexts, ("upper.pac", "lower.pac")))
    primary = replace(service.capture_export_snapshot(controller.active_session_id), skeleton_bone_count=8)
    if qualified:
        contexts = tuple(replace(context, selected_entry=replace(context.selected_entry, path="character/" + context.selected_entry.path))
                         for context in contexts)
        primary.mesh.path = primary.base_mesh.path = contexts[0].selected_entry.path
    secondary = replace(primary, mesh=copy.deepcopy(primary.mesh), base_mesh=copy.deepcopy(primary.base_mesh))
    secondary.mesh.path = secondary.base_mesh.path = contexts[1].selected_entry.path
    mesh, context = compose_item_set([(contexts[0].selected_entry, primary, None, None),
                                      (contexts[1].selected_entry, secondary, None, None)])
    view = service.open_edit_session(mesh, mode="edit", load_layer_project=False)
    session = service._session(view.session_id)
    session.archive_refit_context = context
    service.close_edit_session(controller.active_session_id, force_without_saving=True)
    return source, service, view.session_id, context


def test_topology_mapping_and_exact_output_are_per_asset(tmp_path):
    source, service, key, context = _set(tmp_path)
    try:
        before = tuple(getattr(part, PART_ATTRIBUTE) for part in service.working_mesh(key).submeshes)
        result = service.apply_command(key, MeshEditCommand("subdivide",
            selection=MeshEditSelection.from_maps(source_indices=(1,)), mode="edit"))
        assert result.ok and result.topology_changed
        snapshot = service.capture_export_snapshot(key)
        assert tuple(getattr(part, PART_ATTRIBUTE) for part in snapshot.mesh.submeshes) == before
        components = item_set_snapshots(snapshot)
        unchanged, _ = service.rebuild_result_from_snapshot(components[0][1])
        changed, _ = service.rebuild_result_from_snapshot(components[1][1])
        assert unchanged.data == source and changed.data != source
        reparsed = parse_pac(changed.data, components[1][0].path)
        assert len(reparsed.submeshes[0].vertices) == len(snapshot.mesh.submeshes[1].vertices)
        assert reparsed.submeshes[0].faces == snapshot.mesh.submeshes[1].faces
        # Reordering Parts cannot change which file receives edited geometry.
        snapshot.mesh.submeshes.reverse()
        swapped = item_set_snapshots(snapshot)
        assert swapped[1][1].mesh.submeshes[0].faces == reparsed.submeshes[0].faces
    finally:
        service.close_edit_session(key, force_without_saving=True)


@pytest.mark.parametrize("action,params", [("subdivide", {}), ("merge", {}), ("delete", {"delete_parts": True})])
def test_cross_asset_topology_refused_before_mutation(tmp_path, action, params):
    _source, service, key, context = _set(tmp_path)
    try:
        with pytest.raises(ValueError, match="one source file"):
            service.apply_command(key, MeshEditCommand(action, mode="edit", params=params,
                selection=MeshEditSelection.from_maps(source_indices=(0, 1))))
        assert service.session_view(key).revision == 0
    finally:
        service.close_edit_session(key, force_without_saving=True)


@pytest.mark.parametrize("action,selection,params", [
    ("loop_cut", MeshEditSelection.from_maps(edges_by_submesh={1: ((1, 2),)}), {}),
    ("split", MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}), {}),
    ("merge", MeshEditSelection.from_maps(vertices_by_submesh={1: (0, 1)}), {}),
    ("transform", MeshEditSelection.from_maps(source_indices=(0, 1)), {"translate": (0.0, 0.0, 0.1)}),
    ("brush", MeshEditSelection.from_maps(source_indices=(0, 1)), {"tool": "grab", "radius": 5.0, "delta": (0.0, 0.0, 0.1)}),
    ("brush", MeshEditSelection.from_maps(source_indices=(0, 1)), {"tool": "smooth", "radius": 5.0, "strength": 0.25}),
    ("flip_normals", MeshEditSelection.from_maps(source_indices=(0, 1)), {}),
])
def test_set_tools_save_through_each_original_pac(tmp_path, action, selection, params):
    source, service, key, context = _set(tmp_path)
    try:
        result = service.apply_command(key, MeshEditCommand(action, selection=selection, params=params,
                                                            mode="sculpt" if action == "brush" else "edit"))
        assert result.ok and result.status != "noop", result
        components = item_set_snapshots(service.capture_export_snapshot(key))
        outputs = [service.rebuild_result_from_snapshot(component)[0].data for _entry, component in components]
        for data, (entry, component) in zip(outputs, components):
            parsed = parse_pac(data, entry.path)
            assert parsed.submeshes[0].faces == component.mesh.submeshes[0].faces
            assert len(parsed.submeshes[0].vertices) == len(component.mesh.submeshes[0].vertices)
        assert outputs[1] != source
        assert (outputs[0] != source) is (action in {"transform", "brush", "flip_normals"})
    finally:
        service.close_edit_session(key, force_without_saving=True)


@pytest.mark.parametrize("selection", [MeshEditSelection.from_maps(source_indices=(1,)),
    MeshEditSelection.from_maps(faces_by_submesh={1: (0, 1)}),
    MeshEditSelection.from_maps(vertices_by_submesh={1: (0, 1, 2, 3)})])
def test_deleting_all_faces_or_vertices_refuses_before_mutation(tmp_path, selection):
    _source, service, key, _context = _set(tmp_path)
    try:
        before = service.session_view(key).revision
        with pytest.raises(ValueError, match="Cannot delete every part.*lower.pac"):
            service.apply_command(key, MeshEditCommand("delete", selection=selection, mode="edit"))
        assert service.session_view(key).revision == before
    finally:
        service.close_edit_session(key, force_without_saving=True)


def test_last_part_rig_and_identity_refusals(tmp_path):
    _source, service, key, context = _set(tmp_path)
    try:
        with pytest.raises(ValueError, match="every part.*upper.pac"):
            service.apply_command(key, MeshEditCommand("delete", mode="edit", params={"delete_parts": True},
                selection=MeshEditSelection.from_maps(source_indices=(0,))))
        snapshot = service.capture_export_snapshot(key)
        snapshot.mesh.submeshes[1].source_bone_palette = (99,)
        with pytest.raises(ValueError, match="rig.*lower.pac"):
            item_set_snapshots(snapshot)
        setattr(snapshot.mesh.submeshes[1], PART_ATTRIBUTE, getattr(snapshot.mesh.submeshes[0], PART_ATTRIBUTE))
        with pytest.raises(ValueError, match="identity"):
            item_set_bindings(snapshot.mesh, context)
    finally:
        service.close_edit_session(key, force_without_saving=True)


def test_context_draft_identity_and_include_undo(tmp_path):
    _source, service, key, context = _set(tmp_path)
    try:
        identity = getattr(service.working_mesh(key).submeshes[1], PART_ATTRIBUTE)
        set_item_set_inclusion(service, key, [identity], False)
        edited = service._session(key).archive_refit_context
        assert edited.excluded_part_ids == {identity}
        payload = save_archive_refit_context(edited, tmp_path, threading.Event())
        restored = load_archive_refit_context(payload, tmp_path)
        assert restored.draft_identity == context.draft_identity
        assert restored.excluded_part_ids == {identity}
        assert replace(context, assets=context.assets[::-1]).draft_identity == context.draft_identity
        service.undo(key)
        assert not service._session(key).archive_refit_context.excluded_part_ids
        service.redo(key)
        assert service._session(key).archive_refit_context.excluded_part_ids == {identity}
        payload["source_identity"] = "0" * 64
        with pytest.raises(ValueError, match="source identity"):
            load_archive_refit_context(payload, tmp_path)
    finally:
        service.close_edit_session(key, force_without_saving=True)


def test_separate_paste_and_undo_keep_source_ownership(tmp_path):
    source, service, key, context = _set(tmp_path)
    try:
        result = service.apply_command(key, MeshEditCommand("separate", mode="edit",
            selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)})))
        assert result.ok
        parts = service.working_mesh(key).submeshes
        ids = [getattr(part, PART_ATTRIBUTE) for part in parts]
        assert len(set(ids)) == 3
        assert getattr(parts[2], ASSET_ATTRIBUTE) == context.assets[1].asset_id
        assert getattr(parts[2], ORIGIN_ATTRIBUTE) == context.assets[1].source_part_id(0)
        # Further topology on the separated part retains original-relative
        # lineage, including through native history rather than Python indices.
        result = service.apply_command(key, MeshEditCommand("subdivide", mode="edit",
            selection=MeshEditSelection.from_maps(source_indices=(2,))))
        assert result.ok
        components = item_set_snapshots(service.capture_export_snapshot(key))
        unchanged, _ = service.rebuild_result_from_snapshot(components[0][1])
        rebuilt, _ = service.rebuild_result_from_snapshot(components[1][1])
        assert unchanged.data == source
        assert len(parse_pac(rebuilt.data, "lower.pac").submeshes[0].faces) == 5
        service.undo(key)
        service.undo(key)
        assert len(service.working_mesh(key).submeshes) == 2
        service.redo(key)
        assert [getattr(part, PART_ATTRIBUTE) for part in service.working_mesh(key).submeshes] == ids
        service.copy_selection(key, target="face", selection=MeshEditSelection.from_maps(source_indices=(2,)))
        service.apply_command(key, MeshEditCommand("select", selection=MeshEditSelection.from_maps(source_indices=(0,))))
        with pytest.raises(ValueError, match="paste geometry between"):
            service.paste_selection(key)
        service.apply_command(key, MeshEditCommand("select", selection=MeshEditSelection.from_maps(source_indices=(2,))))
        assert service.paste_selection(key).ok
        components = item_set_snapshots(service.capture_export_snapshot(key))
        rebuilt, _ = service.rebuild_result_from_snapshot(components[1][1])
        assert len(parse_pac(rebuilt.data, "lower.pac").submeshes[0].faces) == 3
    finally:
        service.close_edit_session(key, force_without_saving=True)


def test_real_authoring_preparation_opens_all_files_and_groups(tmp_path, monkeypatch):
    from cdmw.workers.mesh_editor_aux_workers import MeshArchiveMaterialContextWorker
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    monkeypatch.setattr(MeshArchiveMaterialContextWorker, "run", lambda worker:
        worker.context_resolved.emit(worker.request_id, SimpleNamespace(
            preview_model=None, material_package_path="", material_package_lease=None)))
    _source, service, controller, contexts = _sources(tmp_path)
    session = None
    try:
        session = RustMeshAuthoringSession.create(controller, tmp_path / "authoring", process_generation=1,
            item_set_contexts=contexts, edit_item_set=True)
        state = session.state_payload(include_document=False)
        assert state["submesh_count"] == 2
        assert state["replacement"]["item_set"]
        assert [group["name"] for group in state["replacement"]["groups"]] == ["upper.pac", "lower.pac"]
        assert len({part["id"] for part in state["replacement"]["parts"]}) == 2
        shadow = session.shadow_service._session(session.shadow_session_id)
        assert shadow.geometry_layers[0].submesh_indices == (0, 1)
        assert len(service.working_mesh(controller.active_session_id).submeshes) == 1
    finally:
        if session is not None:
            session.cancel()
        service.close_edit_session(controller.active_session_id, force_without_saving=True)


@pytest.mark.parametrize("delete", [False, True])
def test_part_exclusion_and_deletion_write_only_the_owned_file(tmp_path, delete):
    source, service, key, context = _set(tmp_path, two_parts=True)
    try:
        if delete:
            assert service.apply_command(key, MeshEditCommand("delete", mode="edit", params={"delete_parts": True},
                selection=MeshEditSelection.from_maps(source_indices=(0,)))).ok
        else:
            set_item_set_inclusion(service, key, [context.assets[0].source_part_id(0)], False)
        components = item_set_snapshots(service.capture_export_snapshot(key))
        rebuilt, report = service.rebuild_result_from_snapshot(components[0][1])
        untouched, _ = service.rebuild_result_from_snapshot(components[1][1])
        assert untouched.data == source
        written = parse_pac(rebuilt.data, "upper.pac")
        # Existing PAC inclusion uses a tiny hidden runtime placeholder and
        # retains section slots, including skeletal/cloth records.
        assert len(written.submeshes) == 2
        assert max(written.submeshes[0].source_bbox_extent) <= 0.0001
        import hashlib
        assert report.rebuilt_asset_hash == hashlib.sha256(rebuilt.data).hexdigest()
        for actual, expected in zip(written.submeshes[1].vertices, context.assets[0].source.mesh.submeshes[1].vertices):
            assert actual == pytest.approx(expected, abs=0.0001)
    finally:
        service.close_edit_session(key, force_without_saving=True)


def test_native_draft_generation_restores_set_after_separate(tmp_path):
    from cdmw.services.mesh_layer_project_service import load_mesh_layer_project
    source, service, key, context = _set(tmp_path)
    try:
        assert service.apply_command(key, MeshEditCommand("separate", mode="edit",
            selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}))).ok
        identity = getattr(service.working_mesh(key).submeshes[2], PART_ATTRIBUTE)
        set_item_set_inclusion(service, key, [identity], False)
        session = service._session(key)
        session.mesh_layer_project_path = tmp_path / "draft" / "mesh_layer_project.json"
        service._save_mesh_layer_project_locked(session)
        mesh = parse_pac(source, "upper.pac")
        loaded = load_mesh_layer_project(mesh, session.mesh_layer_project_path,
            expected_source_asset_sha256=session.mesh_asset_source_hash)
        assert loaded is not None
        restored = loaded["archive_refit_context"]
        assert restored.draft_identity == context.draft_identity
        assert restored.excluded_part_ids == {identity}
        assert len(item_set_bindings(mesh, restored)[context.assets[1].asset_id]) == 2
    finally:
        service.close_edit_session(key, force_without_saving=True)


def test_named_weight_edits_use_each_files_palette_and_one_undo(tmp_path):
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _rig_command
    from tests.test_mesh_rust_authoring import _with_resolvable_bone_palette, _prepared_dds_entry
    from tests.test_mesh_pac_topology_serializer import _pac_fixture
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    source, authority, initial = _open_exact_session(tmp_path / "initial", resolved_rig=True)
    initial.cancel()
    first = authority.capture_export_snapshot(initial.authoritative_session_id)
    skeleton = first.mesh.interchange_skeleton
    second_data = _with_resolvable_bone_palette(_pac_fixture(skinned=True), tuple(bone.name_hash for bone in reversed(skeleton.bones)))
    mesh = authority.load_mesh_bytes(second_data, "lower.pac", run_roundtrip=True)
    second_id = authority.open_edit_session(mesh, mode="edit", load_layer_project=False).session_id
    authority.attach_skeleton(second_id, skeleton)
    second = authority.capture_export_snapshot(second_id)
    authority.close_edit_session(second_id, force_without_saving=True)
    entries = [_prepared_dds_entry(tmp_path, name, data) for name, data in ((first.mesh.path, source), ("lower.pac", second_data))]
    combined, context = compose_item_set([(entries[0], first, None, None), (entries[1], second, None, None)])
    key = authority.open_edit_session(combined, mode="edit", load_layer_project=False).session_id
    authority._session(key).archive_refit_context = context
    authority.attach_skeleton(key, skeleton)
    editor = None
    try:
        editor = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=authority, active_session_id=key),
                                                tmp_path / "weights", process_generation=2)
        service, sid = editor.shadow_service, editor.shadow_session_id
        service._session(sid).selected_bone_index = 3
        before = copy.deepcopy(service.working_mesh(sid))
        result = _rig_command(editor, 1, "rig_adjust_weight", {"delta": 0.125, "selection": {
            "source_indices": [0, 1], "vertices_by_submesh": {"0": [0], "1": [0]},
            "edges_by_submesh": {}, "faces_by_submesh": {}}})
        assert result["state"]["skeleton"]["weight_edit_capability"]["enabled"]
        edited = service.working_mesh(sid)
        assert 3 in edited.submeshes[0].bone_indices[0]
        assert 4 in edited.submeshes[1].bone_indices[0]  # Bone 3 is slot 4 in the second PAC.
        influence = result["state"]["rig_influence"]
        assert influence["available"]
        displayed = {part["submesh_index"]: dict(part["weights"])[0] for part in influence["parts"]}
        for index, slot in ((0, 3), (1, 4)):
            part = edited.submeshes[index]
            expected = sum(weight for bone, weight in zip(part.bone_indices[0], part.bone_weights[0]) if bone == slot)
            assert displayed[index] == pytest.approx(expected)
        for _entry, component in item_set_snapshots(service.capture_export_snapshot(sid)):
            service.rebuild_result_from_snapshot(component)
        saved = save_archive_refit_context(service._session(sid).archive_refit_context, tmp_path / "rig-draft", threading.Event())
        restored = load_archive_refit_context(saved, tmp_path / "rig-draft")
        for original_asset, restored_asset in zip(context.assets, restored.assets, strict=True):
            assert [(bone.name, bone.name_hash) for bone in restored_asset.source.mesh.interchange_skeleton.bones] == [
                (bone.name, bone.name_hash) for bone in original_asset.source.mesh.interchange_skeleton.bones]
        service.undo(sid)
        for original, restored in zip(before.submeshes, service.working_mesh(sid).submeshes):
            assert restored.bone_weights == original.bone_weights
            assert restored.bone_indices == original.bone_indices
    finally:
        if editor is not None:
            editor.cancel()
        authority.close_edit_session(key, force_without_saving=True)
        authority.close_edit_session(initial.authoritative_session_id, force_without_saving=True)


def test_build_mod_routes_only_changed_pac_requests(tmp_path, monkeypatch):
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker, MeshDirectOutputResult
    _source, service, key, context = _set(tmp_path)
    try:
        assert service.apply_command(key, MeshEditCommand("subdivide", mode="edit",
            selection=MeshEditSelection.from_maps(source_indices=(1,)))).ok
        requests, errors, completed = [], [], []
        worker = MeshDirectOutputWorker(1, service, key, context.assets[0].entry,
            kind="loose_mod", output_path=tmp_path / "mod")
        def publish(rows, metadata, report):
            requests.extend(rows)
            return MeshDirectOutputResult(kind="loose_mod", output_path=tmp_path / "mod", rebuild_report=report)
        # Keep this a routing test; existing output-service tests own atomic
        # folder publication and package history, which has a known baseline failure.
        monkeypatch.setattr(worker, "_write_loose_mod", publish)
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, result: completed.append(result))
        worker.run()
        assert not errors and completed
        assert [request.entry.path for request in requests] == ["lower.pac"]
        assert len(parse_pac(requests[0].payload_data, "lower.pac").submeshes[0].faces) == 8
    finally:
        service.close_edit_session(key, force_without_saving=True)


def test_build_mod_publishes_only_changed_owned_pac_and_history(tmp_path, monkeypatch):
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
    from cdmw.core import mod_export_history
    monkeypatch.setattr(mod_export_history, "_history_root", lambda: tmp_path / "history")
    _source, service, key, context = _set(tmp_path, qualified=True)
    try:
        assert service.apply_command(key, MeshEditCommand("subdivide", mode="edit",
            selection=MeshEditSelection.from_maps(source_indices=(1,)))).ok
        errors, completed = [], []
        output = tmp_path / "mod"
        worker = MeshDirectOutputWorker(1, service, key, context.assets[0].entry,
            kind="loose_mod", output_path=output, manager_profile="dmm")
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, result: completed.append(result))
        worker.run()
        assert not errors and completed
        assert not (output / "character/upper.pac").exists()
        data = (output / "character/lower.pac").read_bytes()
        assert len(parse_pac(data, "character/lower.pac").submeshes[0].faces) == 8
        assert list((tmp_path / "history").glob("*/mesh-editor-session.json"))
    finally:
        service.close_edit_session(key, force_without_saving=True)


def test_clipboard_owner_survives_other_file_part_deletion(tmp_path):
    _source, service, key, context = _set(tmp_path, two_parts=True)
    try:
        service.copy_selection(key, selection=MeshEditSelection.from_maps(source_indices=(3,)))
        assert service.apply_command(key, MeshEditCommand("delete", mode="edit", params={"delete_parts": True},
            selection=MeshEditSelection.from_maps(source_indices=(0,)))).ok
        assert service.apply_command(key, MeshEditCommand("paste", mode="edit",
            selection=MeshEditSelection.from_maps(source_indices=(1,)))).ok
        snapshot = service.capture_export_snapshot(key)
        assert getattr(snapshot.mesh.submeshes[-1], ORIGIN_ATTRIBUTE) == context.assets[1].source_part_id(1)
        components = item_set_snapshots(snapshot)
        for entry, component in components:
            data = service.rebuild_result_from_snapshot(component)[0].data
            assert parse_pac(data, entry.path).submeshes
        assert len(components[1][1].mesh.submeshes[1].faces) == 2 * len(context.assets[1].source.mesh.submeshes[1].faces)
    finally:
        service.close_edit_session(key, force_without_saving=True)


def test_output_diagnostics_map_source_sections_after_deletion(tmp_path):
    from cdmw.services.mesh_archive_refit import validate_archive_refit
    _source, service, key, _context = _set(tmp_path, two_parts=True)
    try:
        service.apply_command(key, MeshEditCommand("delete", mode="edit", params={"delete_parts": True},
            selection=MeshEditSelection.from_maps(source_indices=(0,))))
        snapshot = service.capture_export_snapshot(key)
        snapshot.mesh.submeshes[0].normals = []
        report = validate_archive_refit(service, snapshot)
        issue, = [issue for issue in report.issues if issue.code == "missing_normals"]
        assert issue.submesh_index == 0 and "upper.pac" in issue.message
    finally:
        service.close_edit_session(key, force_without_saving=True)


def test_finish_accepts_set_topology_atomically_and_reopens(tmp_path, monkeypatch):
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _rig_command, _request
    from tests.test_mesh_rust_authoring import _prepared_dds_entry
    from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from cdmw.workers import mesh_archive_refit_worker
    source, authority, initial = _open_exact_session(tmp_path / "initial", resolved_rig=True)
    initial.cancel()
    key = initial.authoritative_session_id
    first = authority.capture_export_snapshot(key)
    second = replace(first, mesh=copy.deepcopy(first.mesh), base_mesh=copy.deepcopy(first.base_mesh))
    second.mesh.path = second.base_mesh.path = "lower.pac"
    entries = [_prepared_dds_entry(tmp_path, name, source) for name in (first.mesh.path, "lower.pac")]
    contexts = tuple(ArchiveWorkflowDependencyContext(entry, (entry,), {entry.path: entry},
        {entry.basename: (entry,)}, True) for entry in entries)
    monkeypatch.setattr(mesh_archive_refit_worker, "prepare_archive_refit_source",
        lambda args, stop_event: {"_archive_snapshot": second})
    editor = reopened = None
    try:
        controller = SimpleNamespace(mesh_service=authority, active_session_id=key)
        editor = RustMeshAuthoringSession.create(controller, tmp_path / "set", process_generation=2,
            item_set_contexts=contexts, edit_item_set=True)
        _rig_command(editor, 1, "topology", {"action": "separate", "selection": {
            "source_indices": [], "vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {"1": [0]}}})
        result = editor.finish(_request(editor, "finish_request", 2))
        assert all(asset["status"] == "passed" for asset in result["exact_output_validation"]["assets"])
        assert len(authority.working_mesh(key).submeshes) == 3
        assert authority._session(key).archive_refit_context.workflow == "item_set"
        assert authority.undo(key).ok
        assert len(authority.working_mesh(key).submeshes) == 1
        assert authority._session(key).archive_refit_context is None
        assert authority.redo(key).ok
        reopened = RustMeshAuthoringSession.create(controller, tmp_path / "reopened", process_generation=3,
            item_set_contexts=contexts, edit_item_set=True)
        assert len(reopened.shadow_service.working_mesh(reopened.shadow_session_id).submeshes) == 3
        import json
        assert not json.loads(reopened.manifest_path.read_text()).get("reference_pieces")
    finally:
        if editor is not None:
            editor.cancel()
        if reopened is not None:
            reopened.cancel()
        authority.close_edit_session(key, force_without_saving=True)


def _set_preparation_stubs(tmp_path, monkeypatch, piece):
    from cdmw.services import mesh_item_set_budget, mesh_preview_material_source
    from cdmw.workers import mesh_archive_refit_worker

    _source, service, controller, contexts = _sources(tmp_path)
    primary = service.capture_export_snapshot(controller.active_session_id)
    lower = replace(primary, mesh=copy.deepcopy(primary.mesh), base_mesh=copy.deepcopy(primary.base_mesh))
    lower.mesh.path = lower.base_mesh.path = contexts[1].selected_entry.path
    started = threading.Barrier(2, timeout=10)

    def material_source(mesh, context, cache_root, stop_event):
        started.wait()  # passes only while the piece is being prepared too
        return None

    monkeypatch.setattr(mesh_preview_material_source, "prepare_item_set_material_source", material_source)
    monkeypatch.setattr(mesh_archive_refit_worker, "prepare_archive_refit_source",
                        lambda args, stop_event: piece(args, lower, started))
    monkeypatch.setattr(mesh_item_set_budget, "prepare_item_set_budget",
                        lambda sources, root, identity, stop: (frozenset(range(len(sources))), {}, None))
    return service, controller, contexts, primary


def test_set_pieces_are_prepared_side_by_side_in_set_order(tmp_path, monkeypatch):
    from cdmw.services.mesh_item_set_editing import prepare_editable_item_set

    threads = []

    def piece(args, lower, started):
        threads.append(threading.current_thread().name)
        return {"_archive_snapshot": lower}

    service, controller, contexts, primary = _set_preparation_stubs(tmp_path, monkeypatch, piece)
    try:
        mesh, context, references, _bounded, _materials = prepare_editable_item_set(
            service, controller.active_session_id, copy.deepcopy(primary.mesh), contexts, threading.Event(),
            lambda _message: None, tmp_path / "root", None)
        assert [asset.entry.path for asset in context.assets] == ["upper.pac", "lower.pac"]
        assert references == ()
        assert threads and threads[0].startswith("cdmw-item-set")
    finally:
        service.close_edit_session(controller.active_session_id, force_without_saving=True)


def test_a_failed_set_piece_still_fails_the_preparation(tmp_path, monkeypatch):
    from cdmw.services.mesh_item_set_editing import prepare_editable_item_set

    def piece(args, lower, started):
        started.wait()
        raise ValueError("lower.pac could not be read")

    service, controller, contexts, primary = _set_preparation_stubs(tmp_path, monkeypatch, piece)
    try:
        with pytest.raises(ValueError, match="lower.pac could not be read"):
            prepare_editable_item_set(
                service, controller.active_session_id, copy.deepcopy(primary.mesh), contexts, threading.Event(),
                lambda _message: None, tmp_path / "root", None)
    finally:
        service.close_edit_session(controller.active_session_id, force_without_saving=True)


def test_set_pieces_use_browse_s_preview_core_cache_when_the_session_is_in_the_workspace(tmp_path):
    from cdmw.services.cache_layout import runtime_cache_layout
    from cdmw.services.mesh_item_set_editing import item_set_material_cache

    cache = tmp_path / "cache"
    session = cache / "mesh_editor_sessions" / "session-1"
    session.mkdir(parents=True)
    # No Browse cache yet: the sessions' own.
    assert item_set_material_cache(session) == cache / "mesh_editor_sessions" / "item-set-native-cache"
    native = runtime_cache_layout(cache).native_preview_root
    native.mkdir(parents=True)
    assert item_set_material_cache(session) == native
    # Sessions outside the workspace cache keep their own.
    elsewhere = tmp_path / "temp" / "cdmw-rust-mesh-editor" / "session-2"
    elsewhere.mkdir(parents=True)
    assert item_set_material_cache(elsewhere) == elsewhere.parent / "item-set-native-cache"


def test_a_saved_history_step_restores_into_the_set(tmp_path):
    """P14: a journal step back keeps the set's assets and part identities."""
    from cdmw.services.mesh_history_journal import read_journal

    source, service, key, context = _set(tmp_path)
    try:
        session = service._session(key)
        session.mesh_layer_project_path = tmp_path / "draft" / "mesh_layer_project.json"
        service._save_mesh_layer_project_locked(session)  # the set as opened
        before = [getattr(part, PART_ATTRIBUTE) for part in service.working_mesh(key).submeshes]
        assert service.apply_command(key, MeshEditCommand("separate", mode="edit",
            selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}))).ok
        identity = getattr(service.working_mesh(key).submeshes[2], PART_ATTRIBUTE)
        set_item_set_inclusion(service, key, [identity], False)
        service._save_mesh_layer_project_locked(session)
        assert len(read_journal(tmp_path / "draft").records) == 2
        # Drop the in-memory history, as a restart does.
        while session.undo_stack:
            session.undo_stack.pop()
        result = service.undo(key)
        assert result.action == "journal_undo"
        after = [getattr(part, PART_ATTRIBUTE) for part in service.working_mesh(key).submeshes]
        assert after == before
        restored = service._session(key).archive_refit_context
        assert restored.draft_identity == context.draft_identity and not restored.excluded_part_ids
        assert len(item_set_bindings(service.working_mesh(key), restored)[context.assets[1].asset_id]) == 1
        assert service.redo(key).action == "journal_redo"
        assert service._session(key).archive_refit_context.excluded_part_ids == {identity}
    finally:
        service.close_edit_session(key, force_without_saving=True)

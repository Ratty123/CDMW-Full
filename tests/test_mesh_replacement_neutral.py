"""Experimental neutral replacement through the actual shadow and writer path."""

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_parser import parse_mesh
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from tests.test_mesh_neutral_face_editing import _appearance
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_replacement import command, prepare_source
from tests.test_mesh_editor_replacement_regressions import _distinct_lods, _lod_part_records
from cdmw.services.mesh_service import MeshService
from cdmw.models import ArchiveEntry


def import_replacement(host, tmp_path):
    result = prepare_source(host, tmp_path)
    key = result["state"]["replacement"]["pending"]["targets"][0]["id"]
    command(host, "replacement_apply", {"targets": [key]})
    return key


def test_experimental_import_is_immediately_available_and_survives_finish_preview_and_reopen(tmp_path):
    original, service, host = _open_exact_session(tmp_path / "host", neutral_appearance=_appearance())
    try:
        ui = host.state_payload()["replacement"]
        assert ui["available"] and ui["experimental"]
        assert ui["reason"] == ""
        assert host.shadow_service._session(host.shadow_session_id).replacement_state is None
        key = import_replacement(host, tmp_path)
        snapshot = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        assert snapshot.replacement_state.neutral_coordinates
        positions = [(12, 3, 7), (16, 3, 7), (12, 5, 8)]
        assert list(snapshot.mesh.submeshes[0].vertices) == positions
        assert len(snapshot.mesh.submeshes[0].bone_weights) == 3
        expected = host.shadow_service._replacement_output_for_snapshot(snapshot)
        result = command(host, "replacement_compare", {"mode": "output"})
        document = json.loads((host.root / result["state"]["document"]["path"]).read_bytes())
        shown = _appearance().to_neutral(parse_mesh(expected.data, snapshot.mesh.path))
        assert document["lods"][0]["submeshes"][0]["positions"] == [list(p) for p in shown.submeshes[0].vertices]
        command(host, "replacement_compare", {"mode": "edit"})
        command(host, "replacement_include", {"part_ids": [key], "included": False})
        assert list(host.shadow_service.working_mesh(host.shadow_session_id).submeshes[0].vertices) == positions
        command(host, "undo")
        assert host.shadow_service._replacement_output_for_snapshot(host.shadow_service.capture_export_snapshot(host.shadow_session_id)).data == expected.data
        host.finish(_request(host, "finish_request", 20))
        committed = service.capture_export_snapshot(host.authoritative_session_id)
        assert not committed.replacement_state.neutral_coordinates
        assert service.rebuild_result_from_snapshot(committed)[0].data == expected.data
        assert committed.original_data == original
        reopened = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=service, active_session_id=host.authoritative_session_id), tmp_path / "reopened", process_generation=2)
        try:
            assert reopened.state_payload()["replacement"]["experimental"]
            for actual, target in zip(reopened.shadow_service.working_mesh(reopened.shadow_session_id).submeshes[0].vertices, positions):
                assert actual == pytest.approx(target)
            command(reopened, "replacement_reset")
            assert list(reopened.shadow_service.working_mesh(reopened.shadow_session_id).submeshes[0].vertices) == positions
        finally:
            reopened.cancel()
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(host.authoritative_session_id)


def test_experimental_cancel_undo_and_failed_writer_preserve_state(tmp_path, monkeypatch):
    _, service, host = _open_exact_session(tmp_path / "host", neutral_appearance=_appearance())
    try:
        before = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        prepare_source(host, tmp_path)
        command(host, "replacement_cancel")
        assert host.shadow_service.session_view(host.shadow_session_id).undo_count == 0
        key = import_replacement(host, tmp_path)
        after = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        command(host, "undo")
        restored = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        assert restored.replacement_state is None
        assert list(restored.mesh.submeshes[0].vertices) == list(before.mesh.submeshes[0].vertices)
        command(host, "redo")
        assert host.shadow_service.capture_export_snapshot(host.shadow_session_id).replacement_state == after.replacement_state
        with monkeypatch.context() as patch:
            patch.setattr("cdmw.services.mesh_replacement_output.build_static_mesh_replacement", lambda *a, **kw: (_ for _ in ()).throw(ValueError("writer rejected")))
            with pytest.raises(ValueError, match="writer rejected"):
                command(host, "replacement_include", {"part_ids": [key], "included": False})
        assert host.shadow_service.capture_export_snapshot(host.shadow_session_id).replacement_state == after.replacement_state
        host.cancel()
        assert service.capture_export_snapshot(host.authoritative_session_id).replacement_state is None
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(host.authoritative_session_id)


def test_experimental_draft_requires_versioned_transform(tmp_path):
    _, service, host = _open_exact_session(tmp_path / "host", neutral_appearance=_appearance())
    try:
        import_replacement(host, tmp_path)
        state = host.shadow_service.capture_export_snapshot(host.shadow_session_id).replacement_state
        generation = tmp_path / "generation"
        generation.mkdir()
        payload = save_replacement_state(state, tmp_path, generation)
        assert payload["version"] == 3
        assert load_replacement_state(payload, tmp_path) == state
        with pytest.raises(ValueError, match="Unsupported"):
            load_replacement_state({**payload, "version": 2}, tmp_path)
        with pytest.raises(ValueError, match="neutral appearance"):
            load_replacement_state({**payload, "neutral_appearance": None}, tmp_path)
        with pytest.raises(ValueError, match="coordinate frame"):
            load_replacement_state({**payload, "neutral_coordinates": "true"}, tmp_path)
        ordinary = save_replacement_state(replace(state, neutral_appearance=None, neutral_coordinates=False), tmp_path, generation)
        assert ordinary["version"] == 2
    finally:
        host.cancel()
        service.close_edit_session(host.authoritative_session_id)


@pytest.mark.parametrize("finish", [False, True])
def test_experimental_full_draft_reopens_the_saved_coordinate_frame(tmp_path, finish):
    data, service, host = _open_exact_session(tmp_path / "host", neutral_appearance=_appearance())
    reopened_service = MeshService()
    loaded_id = None
    try:
        import_replacement(host, tmp_path)
        if finish:
            host.finish(_request(host, "finish_request", 4))
        owner = service if finish else host.shadow_service
        sid = host.authoritative_session_id if finish else host.shadow_session_id
        snapshot = owner.capture_export_snapshot(sid)
        expected = owner._replacement_output_for_snapshot(snapshot).data
        path = tmp_path / "draft" / "mesh_layers.json"
        owner._session(sid).mesh_layer_project_path = path
        owner.retry_mesh_layer_autosave(sid)
        assert json.loads(path.read_text())["format"] == "mesh_layer_project_v3"
        seed = parse_mesh(data, snapshot.mesh.path)
        seed._cdmw_original_data = data
        seed._cdmw_mesh_layer_project_path = str(path)
        loaded_id = reopened_service.open_edit_session(seed).session_id
        loaded = reopened_service.capture_export_snapshot(loaded_id)
        assert loaded.replacement_state == snapshot.replacement_state
        assert reopened_service._replacement_output_for_snapshot(loaded).data == expected
        restored_host = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=reopened_service, active_session_id=loaded_id), tmp_path / "restored", process_generation=6)
        try:
            command(restored_host, "replacement_reset")
            assert list(restored_host.shadow_service.working_mesh(restored_host.shadow_session_id).submeshes[0].vertices) == [(12, 3, 7), (16, 3, 7), (12, 5, 8)]
        finally:
            restored_host.cancel()
    finally:
        if not host.closed:
            host.cancel()
        if loaded_id is not None:
            reopened_service.close_edit_session(loaded_id)
        service.close_edit_session(host.authoritative_session_id)


def test_neutral_selected_import_preserves_other_parts_and_all_exclusion_is_reversible(tmp_path):
    data = _distinct_lods()
    mesh = parse_mesh(data, "character/model/lods.pac")
    mesh._cdmw_original_data = data
    service = MeshService()
    sid = service.open_edit_session(mesh).session_id
    matrices = list(_appearance().skin_matrices)
    matrices[0] = matrices[3]
    service._session(sid).neutral_appearance = replace(_appearance(), skin_matrices=tuple(matrices))
    host = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=service, active_session_id=sid), tmp_path / "host", process_generation=1)
    try:
        keys = [p["id"] for p in host.state_payload()["replacement"]["parts"]]
        entry = ArchiveEntry(mesh.path, tmp_path / "0.pamt", tmp_path / "0.paz", 0, 0, 0, 0, 0)
        context = SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})
        path = tmp_path / "part.obj"
        path.write_text("v 12 3 7\nv 16 3 7\nv 12 5 8\nf 1 2 3\n")
        # Inclusion works before any replacement import, including all parts.
        command(host, "replacement_include", {"part_ids": keys, "included": False, "_archive_entry": entry, "_archive_dependencies": context})
        excluded = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        assert len(parse_mesh(host.shadow_service._replacement_output_for_snapshot(excluded).data, mesh.path).submeshes) == 2
        command(host, "undo")
        command(host, "replacement_choose", {"scope": "selected", "part_ids": keys[:1], "source_path": str(path), "_archive_entry": entry, "_archive_dependencies": context})
        command(host, "replacement_apply", {"targets": keys[:1]})
        result = host.shadow_service._replacement_output_for_snapshot(host.shadow_service.capture_export_snapshot(host.shadow_session_id))
        for lod in range(4):
            assert _lod_part_records(result.data, lod) == _lod_part_records(data, lod)
        command(host, "replacement_fit")
        command(host, "replacement_reset")
        assert list(host.shadow_service.working_mesh(host.shadow_session_id).submeshes[0].vertices) == [(12, 3, 7), (16, 3, 7), (12, 5, 8)]
    finally:
        host.cancel()
        service.close_edit_session(sid)


def test_experimental_replacement_keeps_singular_transform_rejection(tmp_path):
    _, service, host = _open_exact_session(tmp_path / "host", neutral_appearance=_appearance())
    try:
        host.neutral_appearance = replace(_appearance(), skin_matrices=((0.0,) * 16,) * 8)
        prepared = prepare_source(host, tmp_path)
        key = prepared["state"]["replacement"]["pending"]["targets"][0]["id"]
        before = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        with pytest.raises(ValueError, match="singular"):
            command(host, "replacement_apply", {"targets": [key]})
        after = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        assert after.mesh_revision == before.mesh_revision
        assert after.replacement_state is None
        assert list(after.mesh.submeshes[0].vertices) == list(before.mesh.submeshes[0].vertices)
    finally:
        host.cancel()
        service.close_edit_session(host.authoritative_session_id)

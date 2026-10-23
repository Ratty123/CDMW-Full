"""Recovery proves indexed source correspondence before staging an edit."""
from copy import deepcopy
from contextlib import contextmanager

import numpy as np
import pytest

from cdmw.domain.mesh.morph_targets import match_refit_shape_source
from tests.test_native_mesh_editor_morph_refit import _driver_garment_mesh


@contextmanager
def _recovery_session(tmp_path, raw=None):
    from cdmw.services.mesh_service import MeshService
    from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
    from tests.test_mesh_morph_service import _Settings
    from tests.test_mesh_pac_topology_serializer import _pac_fixture

    raw = raw if raw is not None else _pac_fixture(skinned=True)
    source = tmp_path / "unbaked.pac"
    source.write_bytes(raw)
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    mesh = service.load_mesh_bytes(raw, "saved.pac", run_roundtrip=True)
    session_id = service.open_edit_session(mesh, mode="edit", load_layer_project=False).session_id
    try:
        service.apply_command(session_id, MeshEditCommand("transform", selection=MeshEditSelection.from_maps(
            source_indices=(0,)), params={"delta": (0., 0., .03)}))
        yield service, session_id, mesh, source
    finally:
        service.close_edit_session(session_id, force_without_saving=True)


def test_recovery_matches_source_identity_despite_sculpted_positions_and_names():
    source = _driver_garment_mesh()
    reference = deepcopy(source)
    reference.submeshes[2].vertices = [(x + .3, y - .1, z + .2) for x, y, z in reference.submeshes[2].vertices]
    reference.submeshes[2].name = "saved fitted shape"
    reference.submeshes[2].material = "edited material label"
    source.submeshes = [source.submeshes[i] for i in (2, 0, 1, 3)]
    assert match_refit_shape_source(reference, source, submesh_indices=(2,)) == ((2, 0),)


def test_recovery_matches_retained_face_subset_without_reinstating_unused_vertices():
    source = _driver_garment_mesh()
    reference = deepcopy(source)
    reference.submeshes[2].faces = reference.submeshes[2].faces[:1]
    before = deepcopy(reference.submeshes[2])
    assert match_refit_shape_source(reference, source, submesh_indices=(2,)) == ((2, 2),)
    assert reference.submeshes[2] == before


@pytest.mark.parametrize("channel", ("uvs", "bone_indices", "bone_weights", "source_bone_palette",
                                      "source_skin_weight_layout", "source_vertex_map", "faces"))
def test_recovery_refuses_same_names_with_different_structural_or_source_identity(channel):
    reference = _driver_garment_mesh()
    source = deepcopy(reference)
    part = source.submeshes[2]
    replacement = {
        "uvs": [(0.25, 0.75)] * len(part.vertices),
        "bone_indices": [(1, 0)] * len(part.vertices),
        "bone_weights": [(.5, .5)] * len(part.vertices),
        "source_bone_palette": (8, 4), "source_skin_weight_layout": "different",
        "source_vertex_map": list(reversed(part.source_vertex_map)),
        "faces": [(0, 1, 3), (3, 4, 5)],
    }[channel]
    setattr(part, channel, replacement)
    with pytest.raises(ValueError, match="Part 2.*no matching source identity"):
        match_refit_shape_source(reference, source, submesh_indices=(2,))


def test_recovery_refuses_ambiguous_source_parts_even_with_different_names():
    reference = _driver_garment_mesh()
    source = deepcopy(reference)
    duplicate = deepcopy(source.submeshes[2])
    duplicate.name = "another garment"
    source.submeshes.append(duplicate)
    with pytest.raises(ValueError, match="Part 2.*ambiguous source Parts"):
        match_refit_shape_source(reference, source, submesh_indices=(2,))


@pytest.mark.parametrize("failure", ("empty_selection", "empty_surface", "missing_map", "duplicate_map", "nonfinite"))
def test_recovery_refuses_unprovable_or_empty_requests(failure):
    reference = _driver_garment_mesh()
    source = deepcopy(reference)
    indices = (2,)
    if failure == "empty_selection":
        indices = ()
    elif failure == "empty_surface":
        reference.submeshes[2].faces = []
    elif failure == "missing_map":
        reference.submeshes[2].source_vertex_map = []
    elif failure == "duplicate_map":
        reference.submeshes[2].source_vertex_map[1] = reference.submeshes[2].source_vertex_map[0]
    else:
        source.submeshes[2].vertices[0] = (float("nan"), 0., 0.)
    with pytest.raises(ValueError):
        match_refit_shape_source(reference, source, submesh_indices=indices)


def test_recovery_preview_cancel_retains_geometry_settings_and_history(tmp_path):
    with _recovery_session(tmp_path) as (service, sid, source_mesh, source):
        session = service._session(sid)
        before = service.working_mesh(sid, clone=True)
        stacks = (len(session.undo_stack), len(session.redo_stack))
        _result, state = service.preview_refit_shape_restore(sid, source, (0,))
        assert state.shape_restore_source == source.name
        assert state.shape_restore_parts == (0,)
        assert state.shape_restore_vertex_count == len(source_mesh.submeshes[0].vertices)
        np.testing.assert_allclose(service.working_mesh(sid).submeshes[0].vertices,
                                   source_mesh.submeshes[0].vertices, atol=1e-7, rtol=0.)
        assert (len(session.undo_stack), len(session.redo_stack)) == stacks
        with pytest.raises(RuntimeError, match="Apply or Cancel"):
            service.undo(sid)
        with pytest.raises(RuntimeError, match="Apply or Cancel"):
            service.bake_morph(sid)
        _result, state = service.cancel_refit_shape_restore(sid)
        assert not state.shape_restore_source
        np.testing.assert_allclose(service.working_mesh(sid).submeshes[0].vertices,
                                   before.submeshes[0].vertices, atol=1e-7, rtol=0.)
        assert (len(session.undo_stack), len(session.redo_stack)) == stacks


def test_recovery_apply_is_one_edit_with_undo_redo_and_exact_writer(tmp_path):
    with _recovery_session(tmp_path) as (service, sid, source_mesh, source):
        from cdmw.modding.mesh_parser import parse_pac
        session = service._session(sid)
        before = service.working_mesh(sid, clone=True)
        count = len(session.undo_stack)
        service.preview_refit_shape_restore(sid, source, (0,))
        _result, state = service.apply_refit_shape_restore(sid)
        assert not state.shape_restore_source
        assert len(session.undo_stack) == count + 1
        recovered = service.working_mesh(sid, clone=True)
        service.undo(sid)
        np.testing.assert_allclose(service.working_mesh(sid).submeshes[0].vertices,
                                   before.submeshes[0].vertices, atol=1e-7, rtol=0.)
        service.redo(sid)
        np.testing.assert_allclose(service.working_mesh(sid).submeshes[0].vertices,
                                   recovered.submeshes[0].vertices, atol=1e-7, rtol=0.)
        snapshot = service.capture_export_snapshot(sid)
        rebuilt, report = service.rebuild_result_from_snapshot(snapshot)
        assert report.validation_status == "passed"
        reopened = parse_pac(rebuilt.data, "recovered.pac")
        for channel in ("faces", "uvs", "bone_indices", "bone_weights", "material", "name"):
            assert getattr(reopened.submeshes[0], channel) == getattr(source_mesh.submeshes[0], channel)


def test_recovery_island_selection_retains_unselected_sculpted_positions(tmp_path):
    from cdmw.domain.mesh.islands import mesh_islands
    from tests.test_mesh_islands import _island_lods, _island_pac
    raw, _ = _island_pac(_island_lods(simplified=False, count=3))
    with _recovery_session(tmp_path, raw) as (service, sid, source_mesh, source):
        before = service.working_mesh(sid, clone=True)
        group = mesh_islands(before.submeshes[0])[0]
        selected = {v for f in group for v in before.submeshes[0].faces[f]}
        service.preview_refit_shape_restore(sid, source, islands=({"submesh_index": 0, "face_indices": group},))
        service.apply_refit_shape_restore(sid)
        after = service.working_mesh(sid)
        for i, point in enumerate(after.submeshes[0].vertices):
            expected = source_mesh.submeshes[0].vertices[i] if i in selected else before.submeshes[0].vertices[i]
            assert point == pytest.approx(expected, abs=1e-7)
        with pytest.raises(ValueError, match="stale island"):
            service.preview_refit_shape_restore(sid, source, islands=({"submesh_index": 0, "face_indices": group[:1]},))


@pytest.mark.parametrize("whole_part", (False, True))
def test_recovery_retains_include_exclusions_without_restoring_their_positions(tmp_path, whole_part):
    import hashlib
    from cdmw.domain.mesh.islands import mesh_islands
    from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementPart, PART_ID_ATTRIBUTE
    from tests.test_mesh_islands import _island_lods, _island_pac
    raw, _ = _island_pac(_island_lods(simplified=False, count=3))
    with _recovery_session(tmp_path, raw) as (service, sid, source_mesh, source):
        session = service._session(sid)
        before = service.working_mesh(sid, clone=True)
        group = mesh_islands(before.submeshes[0])[0]
        excluded = {v for f in group for v in before.submeshes[0].faces[f]}
        setattr(session.working_mesh.submeshes[0], PART_ID_ATTRIBUTE, "garment")
        setattr(session.base_mesh.submeshes[0], PART_ID_ATTRIBUTE, "garment")
        intent = MeshReplacementState("saved.pac", hashlib.sha256(raw).hexdigest(), (
            ReplacementPart("garment", 0, included=not whole_part, excluded_island_faces=tuple(group)),))
        session.replacement_state = intent
        if whole_part:
            with pytest.raises(ValueError, match="no selected included"):
                service.preview_refit_shape_restore(sid, source, (0,))
            assert service.working_mesh(sid).submeshes[0].vertices == before.submeshes[0].vertices
        else:
            service.preview_refit_shape_restore(sid, source, (0,))
            service.apply_refit_shape_restore(sid)
            for i, point in enumerate(service.working_mesh(sid).submeshes[0].vertices):
                expected = before.submeshes[0].vertices[i] if i in excluded else source_mesh.submeshes[0].vertices[i]
                assert point == pytest.approx(expected, abs=1e-7)
            assert session.replacement_state == intent


def test_recovery_cancelled_after_native_preview_rolls_back_without_history(tmp_path, monkeypatch):
    import threading
    from cdmw.models import RunCancelled
    from cdmw.services import mesh_service_morph
    with _recovery_session(tmp_path) as (service, sid, _source_mesh, source):
        before = service.working_mesh(sid, clone=True)
        session = service._session(sid)
        count = len(session.undo_stack)
        stop = threading.Event()
        native = mesh_service_morph.native_mesh_editor_session_command

        def cancel_after_preview(command, *args, **kwargs):
            reply = native(command, *args, **kwargs)
            if command == "morph_restore_shape":
                stop.set()
            return reply

        monkeypatch.setattr(mesh_service_morph, "native_mesh_editor_session_command", cancel_after_preview)
        with pytest.raises(RunCancelled):
            service.preview_refit_shape_restore(sid, source, (0,), stop_event=stop)
        assert not service._refit_shape_recoveries
        assert len(session.undo_stack) == count
        np.testing.assert_allclose(service.working_mesh(sid).submeshes[0].vertices,
                                   before.submeshes[0].vertices, atol=1e-7, rtol=0.)


def test_recovery_preview_cannot_be_autosaved_and_close_discards_it(tmp_path):
    import threading
    with _recovery_session(tmp_path) as (service, sid, _source_mesh, source):
        session = service._session(sid)
        session.mesh_layer_project_path = tmp_path / "draft.json"
        session.mesh_layer_autosave_requested_key = session.mesh_layer_autosave_saved_key
        service.preview_refit_shape_restore(sid, source, (0,))
        service._schedule_mesh_layer_autosave(session)
        service._run_mesh_layer_autosave(sid, session.mesh_layer_autosave_requested_key, threading.Event())
        assert session.mesh_layer_autosave_timer is None
        assert not session.mesh_layer_project_path.exists()
        service.close_edit_session(sid, force_without_saving=True)
        assert not service._refit_shape_recoveries
        assert not session.mesh_layer_project_path.exists()


def test_native_recovery_retains_skipped_settings_and_unselected_geometry():
    from tests.test_mesh_refit_tightening_native import _arm, _bound, _mesh, _sleeve
    from tests.test_native_mesh_editor_morph_refit import _command, _snapshot, _state
    mesh = _mesh(_arm(), _sleeve(), _sleeve(offset=.3))
    with _bound(mesh) as sid:
        _command(sid, "morph_configure_refit", {"garment_submesh_indices": [1], "enabled": False,
            "mode": "rigid_component", "intensity_percent": 37., "tightness_percent": 63., "clearance_percent": .2})
        before, settings = _snapshot(mesh, sid), _state(sid)["refit"]["garment_settings"]
        original = before.submeshes[1].vertices[0]
        restored = (original[0] + .01, original[1], original[2])
        _command(sid, "morph_restore_shape", {"restored_positions": [{"submesh_index": 1,
            "vertex_indices": [0], "positions": [restored]}]})
        after = _snapshot(mesh, sid)
        assert after.submeshes[1].vertices[0] == pytest.approx(restored)
        assert after.submeshes[1].vertices[1:] == before.submeshes[1].vertices[1:]
        assert after.submeshes[2].vertices == before.submeshes[2].vertices
        assert after.submeshes[0].vertices == before.submeshes[0].vertices
        assert _state(sid)["refit"]["garment_settings"] == settings
        _command(sid, "undo")
        assert _snapshot(mesh, sid).submeshes[1].vertices == before.submeshes[1].vertices
        _command(sid, "redo")
        assert _snapshot(mesh, sid).submeshes[1].vertices == after.submeshes[1].vertices


@pytest.mark.parametrize("part,vertex", ((0, 0), (2, 6)))
def test_native_recovery_refuses_body_and_unused_vertices_atomically(part, vertex):
    from tests.test_native_mesh_editor_morph_refit import _command, _open, _snapshot, _state, mesh_native_core
    mesh = _driver_garment_mesh()
    sid = _open(mesh)
    try:
        _command(sid, "morph_set_driver", {"submesh_indices": [0, 1]})
        before, state = _snapshot(mesh, sid), _state(sid)
        assert mesh_native_core.native_mesh_editor_session_command("morph_restore_shape", sid,
            {"restored_positions": [{"submesh_index": part, "vertex_indices": [vertex], "positions": [[0., 0., .3]]}]}) is None
        assert _state(sid) == state
        assert _snapshot(mesh, sid).submeshes[2].vertices == before.submeshes[2].vertices
    finally:
        mesh_native_core.close_native_mesh_editor_session(sid)


def test_recovery_host_preserves_the_neutral_display_frame_and_exact_source_output(tmp_path):
    from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
    from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
    from cdmw.modding.mesh_parser import parse_pac
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request, _rig_command
    matrices = tuple((1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., .1 * (i + 1), 0., 0., 0., 1.) for i in range(8))
    appearance = NeutralMeshAppearance("owned-frame", tuple(range(8)), matrices)
    raw, authority, host = _open_exact_session(tmp_path / "edit", neutral_appearance=appearance)
    source = tmp_path / "unbaked-source.pac"
    source.write_bytes(raw)
    try:
        shadow, sid = host.shadow_service, host.shadow_session_id
        shadow.apply_command(sid, MeshEditCommand("transform", selection=MeshEditSelection.from_maps(source_indices=(0,)),
                                                 params={"delta": (0., 0., .03)}))
        _rig_command(host, 1, "refit_restore_shape_preview", {"path": str(source), "submesh_indices": [0]})
        restored = shadow.working_mesh(sid, clone=True)
        original = parse_pac(raw, "source.pac")
        np.testing.assert_allclose(restored.submeshes[0].vertices,
                                   appearance.to_neutral(original).submeshes[0].vertices, atol=1e-7, rtol=0.)
        _rig_command(host, 2, "refit_restore_shape_apply", {})
        result = host.finish(_request(host, "finish_request", 3))
        assert result["exact_output_validation"]["status"] == "passed"
        np.testing.assert_allclose(authority.working_mesh(host.authoritative_session_id).submeshes[0].vertices,
                                   original.submeshes[0].vertices, atol=1e-7, rtol=0.)
    finally:
        if not host.closed:
            host.cancel()
        authority.close_edit_session(host.authoritative_session_id, force_without_saving=True)


def test_recovery_host_preserves_include_exclusions_through_finish_and_reopen(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
    from cdmw.models import ArchiveEntry
    from cdmw.modding.mesh_parser import parse_pac
    from tests.test_mesh_islands import _island_lods, _island_pac
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request, _rig_command
    from tests.test_mesh_rust_replacement import command
    raw, _ = _island_pac(_island_lods(simplified=False, count=3))
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: raw)
    _raw, authority, host = _open_exact_session(tmp_path / "edit")
    source = tmp_path / "unbaked-source.pac"
    source.write_bytes(raw)
    try:
        shadow, sid = host.shadow_service, host.shadow_session_id
        shadow.apply_command(sid, MeshEditCommand("transform", selection=MeshEditSelection.from_maps(source_indices=(0,)),
                                                 params={"delta": (0., 0., .03)}))
        part_id = host.state_payload()["replacement"]["parts"][0]["id"]
        command(host, "replacement_islands", {"part_id": part_id, "faces": [0, 1], "included": False,
            "_archive_entry": ArchiveEntry("owned-rust-exact.pac", tmp_path / "0009/0.pamt", tmp_path / "0009/0.paz", 0, 0, 0, 0, 0),
            "_archive_dependencies": SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})})
        intent = shadow._session(sid).replacement_state
        _rig_command(host, 2, "refit_restore_shape_preview", {"path": str(source), "submesh_indices": [0]})
        _rig_command(host, 3, "refit_restore_shape_apply", {})
        assert shadow._session(sid).replacement_state == intent
        host.finish(_request(host, "finish_request", 4))
        assert host.closed
        rebuilt, report = authority.rebuild_result_from_snapshot(authority.capture_export_snapshot(host.authoritative_session_id))
        assert report.validation_status == "passed"
        reopened = parse_pac(rebuilt.data, "recovered-exclusions.pac")
        assert len(reopened.submeshes[0].faces) == 4
        used = {v for face in reopened.submeshes[0].faces for v in face}
        assert not used.intersection(range(6))
    finally:
        if not host.closed:
            host.cancel()
        authority.close_edit_session(host.authoritative_session_id, force_without_saving=True)

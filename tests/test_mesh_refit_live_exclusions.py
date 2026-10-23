"""Fitting respects live Include intent before Finish, including saved drafts."""
import json
import struct
from types import SimpleNamespace

import numpy as np
import pytest

from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementPart, PART_ID_ATTRIBUTE
from cdmw.models import ArchiveEntry
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_morph_draft import capture_morph_draft, persist_morph_draft, load_morph_draft, restore_morph_draft
from tests.test_mesh_morph_authoring_native import resident
from tests.test_mesh_refit_islands import _islands_mesh, _service_session, _configure
from tests.test_mesh_refit_tightening_native import _bound
from tests.test_native_mesh_editor_morph_refit import _command, _snapshot, _state, mesh_native_core


@pytest.mark.parametrize("mode", ["surface", "rigid_component", "rigid"])
@pytest.mark.parametrize("overrides", [False, True])
def test_excluded_island_never_follows_or_fits_even_with_an_enabled_override(mode, overrides):
    mesh = _islands_mesh()
    with _bound(mesh) as session:
        _command(session, "morph_bind", {"garment_submesh_indices": [1],
            "excluded_faces": [{"submesh_index": 1, "face_indices": [0, 1]}]})
        _configure(session, [{"face_indices": [0, 1], "enabled": True, "tightness_percent": 100.}]
                   if overrides else [], mode=mode)
        fitted = _snapshot(mesh, session)
        assert fitted.submeshes[1].vertices[:4] == mesh.submeshes[1].vertices[:4]
        if mode != "rigid":
            assert np.asarray(fitted.submeshes[1].vertices)[4:, 2].max() < .01
        assert fitted.submeshes[1].faces == mesh.submeshes[1].faces
        _command(session, "undo", {})
        assert _snapshot(mesh, session).submeshes[1].vertices == mesh.submeshes[1].vertices
        _command(session, "redo", {})
        assert _snapshot(mesh, session).submeshes[1].vertices == fitted.submeshes[1].vertices
        report = _command(session, "morph_state", {"include_refit_diagnostics": True,
            "submesh_indices": [1], "diagnostic_sample_limit": 100})
        assert report["refit_diagnostics"]["candidate_sample_count"] == 12


@pytest.mark.parametrize("excluded", [
    [{"submesh_index": 1, "all": False}],
    [{"submesh_index": 1, "face_indices": [0]}],
    [{"submesh_index": 1, "face_indices": [99]}],
    [{"submesh_index": 1, "all": True}, {"submesh_index": 1, "all": True}],
])
def test_invalid_exclusions_reject_without_changing_geometry_bindings_or_history(excluded):
    mesh = _islands_mesh()
    with _bound(mesh) as session:
        before = _state(session)
        report = mesh_native_core.native_mesh_editor_session_command("morph_bind", session,
            {"garment_submesh_indices": [1], "excluded_faces": excluded})
        assert report is None or report.get("status") == "error"
        assert _state(session) == before
        assert _snapshot(mesh, session).submeshes[1].vertices == mesh.submeshes[1].vertices


@pytest.mark.parametrize("whole_part", [False, True])
def test_exclusions_survive_service_binding_recipe_draft_and_bake(resident, tmp_path, whole_part):
    def open_tagged(mesh):
        for index, part in enumerate(mesh.submeshes):
            setattr(part, PART_ID_ATTRIBUTE, str(index))
        return resident[1](mesh)

    service, sid, mesh = _service_session((resident[0], open_tagged))
    owner = service._session(sid)
    owner.replacement_state = MeshReplacementState("owned.pac", "a"*64, (
        ReplacementPart("0", 0), ReplacementPart("1", 1, included=not whole_part,
            excluded_island_faces=() if whole_part else (0, 1))))
    # Rebinding derives exclusions from the current output intent rather than a recipe.
    assert service.bind_refit(sid, (1,))[0].ok
    assert service.configure_refit(sid, (1,), tightness_percent=100., clearance_percent=.1)[0].ok
    assert service.set_morph_value(sid, "shape", 50.)[0].ok
    fitted = service.working_mesh(sid, clone=True)
    unchanged = slice(None) if whole_part else slice(0, 4)
    assert fitted.submeshes[1].vertices[unchanged] == mesh.submeshes[1].vertices[unchanged]
    recipe = tmp_path / "fit.json"
    neutral = service._native_neutral_mesh_locked(owner, (0, 1))
    service.export_refit_recipe(sid, recipe, "Included surface")
    payload = capture_morph_draft(service, owner)
    assert payload["format"] == "cdmw.morph_draft.v4"
    assert json.loads(payload["native"])["version"] == 4
    generation = tmp_path / "generation"
    generation.mkdir()
    payload = load_morph_draft(persist_morph_draft(payload, generation, tmp_path), tmp_path)
    # A draft reload starts from the loaded source, then restores its saved
    # editable geometry. The fitted clone is not the source identity authority.
    reopened = resident[1](mesh)
    service.commit_prepared_working_mesh_replacement(service.prepare_working_mesh_replacement(reopened, fitted))
    restored = service._session(reopened)
    restored.replacement_state = owner.replacement_state
    restore_morph_draft(service, restored, payload)
    assert service.fit_refit_to_body(reopened)[0].ok
    assert service.working_mesh(reopened, clone=True).submeshes[1].vertices[unchanged] == mesh.submeshes[1].vertices[unchanged]
    assert service.reset_morph(reopened)[0].ok
    current_neutral = service._native_neutral_mesh_locked(restored, (0, 1))
    for before, after in zip(neutral.submeshes, current_neutral.submeshes, strict=True):
        np.testing.assert_array_equal(np.asarray(before.vertices, dtype=np.float32),
                                      np.asarray(after.vertices, dtype=np.float32))
    assert service.import_refit_recipe(reopened, recipe)[0].ok
    assert service.working_mesh(reopened, clone=True).submeshes[1].vertices[unchanged] == mesh.submeshes[1].vertices[unchanged]
    assert service.bake_morph(reopened)[0].ok
    assert service.fit_refit_to_body(reopened)[0].ok
    assert service.working_mesh(reopened, clone=True).submeshes[1].vertices[unchanged] == mesh.submeshes[1].vertices[unchanged]


def _included_parts_pac():
    from tests.test_mesh_pac_deleted_parts import _parts_pac
    from cdmw.modding.pac_cloth import pac_cloth_lods
    raw = bytearray(_parts_pac())
    for lod in pac_cloth_lods(raw):
        for index, part in enumerate(lod.submeshes):
            lo, hi, z = (.1, .9, .4) if index == 0 else ((.3, .5, .35) if index == 1 else (.6, .8, .35))
            points = [(lo, lo, z), (hi, lo, z), (lo, hi, z), (hi, hi, z)]
            for offset, point in zip(part.source_vertex_offsets, points):
                struct.pack_into("<3H", raw, offset, *(round(v*65535) for v in point))
    return bytes(raw)


@pytest.mark.parametrize("exclude_body", [False, True])
def test_host_include_fit_undo_bake_exact_finish_and_reopen(tmp_path, monkeypatch, exclude_body):
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request, _rig_command
    from tests.test_mesh_rust_replacement import command
    raw = _included_parts_pac()
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: raw)
    _, authority, host = _open_exact_session(tmp_path / "edit")
    try:
        service, sid = host.shadow_service, host.shadow_session_id
        initial = service.working_mesh(sid, clone=True)
        parts = host.state_payload()["replacement"]["parts"]
        excluded_ids = [parts[2]["id"]] + ([parts[0]["id"]] if exclude_body else [])
        command(host, "replacement_include", {"part_ids": excluded_ids, "included": False,
            "_archive_entry": ArchiveEntry("owned-rust-exact.pac", tmp_path / "0009/0.pamt",
                                            tmp_path / "0009/0.paz", 0, 0, 0, 0, 0),
            "_archive_dependencies": SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})})
        intent = service._session(sid).replacement_state
        _rig_command(host, 1, "refit_set_driver", {"submesh_indices": [0]})
        _rig_command(host, 2, "refit_bind", {"submesh_indices": [1, 2]})
        _rig_command(host, 3, "refit_fit_to_body", {})
        fitted = service.working_mesh(sid, clone=True)
        assert min(p[2] for p in fitted.submeshes[1].vertices) > .4
        assert fitted.submeshes[2].vertices == initial.submeshes[2].vertices
        assert fitted.submeshes[0].vertices == initial.submeshes[0].vertices
        assert service._session(sid).replacement_state == intent
        _rig_command(host, 4, "undo", {})
        assert service.working_mesh(sid, clone=True).submeshes[1].vertices == initial.submeshes[1].vertices
        _rig_command(host, 5, "redo", {})
        assert service.working_mesh(sid, clone=True).submeshes[1].vertices == fitted.submeshes[1].vertices
        _rig_command(host, 6, "morph_bake", {})
        host.finish(_request(host, "finish_request", 7))
        output, report = authority.rebuild_result_from_snapshot(authority.capture_export_snapshot(host.authoritative_session_id))
        assert report.validation_status == "passed"
        reopened = parse_pac(output.data, "fit-with-exclusion.pac")
        assert min(p[2] for p in reopened.submeshes[1].vertices) > .4
        assert len(reopened.submeshes[2].faces) == 1
        if exclude_body:
            assert len(reopened.submeshes[0].faces) == 1
        else:
            assert reopened.submeshes[0].vertices == initial.submeshes[0].vertices
    finally:
        if not host.closed:
            host.cancel()
        authority.close_edit_session(host.authoritative_session_id, force_without_saving=True)

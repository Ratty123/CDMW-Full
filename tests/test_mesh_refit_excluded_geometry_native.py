"""Fit the actual PAC produced by Include, Finish and a fresh edit session."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from cdmw.models import ArchiveEntry
from cdmw.modding.mesh_importer import rebuild_mesh_with_report
from cdmw.modding.mesh_parser import parse_pac
from tests.test_mesh_islands import _island_lods, _island_pac
from tests.test_mesh_refit_tightening_native import _arm, _bound, _fit, _mesh, _sleeve
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_replacement import command
from tests.test_native_mesh_editor_morph_refit import _part, _snapshot, mesh_native_core


def test_unused_vertex_record_near_another_layer_is_not_a_surface():
    original = _sleeve()
    unused = (.105, .25, 0.)
    inner = _part("wrap", original.vertices + [unused], original.faces, material="cloth", texture="")
    mesh = _mesh(_arm(), inner, _sleeve(radius=.11))
    with _bound(mesh) as session:
        _fit(session, (1, 2))
        fitted = _snapshot(mesh, session)
        assert fitted.submeshes[1].vertices[-1] == unused
        assert fitted.submeshes[1].faces == inner.faces


@pytest.mark.parametrize("whole_part", (False, True), ids=("island", "whole-part"))
def test_fit_after_finishing_exclusions_and_reopening(tmp_path, monkeypatch, whole_part):
    source, _ = _island_pac(_island_lods(simplified=False, count=3))
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    _, service, host = _open_exact_session(tmp_path / "edit")
    try:
        original = deepcopy(service.working_mesh(host.authoritative_session_id).submeshes[0])
        part_id = host.state_payload()["replacement"]["parts"][0]["id"]
        arguments = {
            "included": False,
            "_archive_entry": ArchiveEntry("owned-rust-exact.pac", tmp_path / "0009/0.pamt",
                                            tmp_path / "0009/0.paz", 0, 0, 0, 0, 0),
            "_archive_dependencies": SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={}),
        }
        if whole_part:
            command(host, "replacement_include", {**arguments, "part_ids": [part_id]})
        else:
            command(host, "replacement_islands", {**arguments, "part_id": part_id, "faces": [0, 1]})
        host.finish(_request(host, "finish_request", 22))
        result, _ = service.rebuild_result_from_snapshot(
            service.capture_export_snapshot(host.authoritative_session_id))
        reopened = parse_pac(result.data, "finished-exclusions.pac")
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)

    garment = reopened.submeshes[0]
    used = {vertex for face in garment.faces for vertex in face}
    unused = set(range(len(garment.vertices))) - used
    if not whole_part:
        assert unused == set(range(6))
        assert garment.vertices == original.vertices
        assert garment.faces == original.faces[2:]
    else:
        assert len(garment.faces) == 1
    # Extend the supporting body beyond the garment, so open-body-rim
    # protection does not intentionally retain every corner of these panels.
    x0, x1 = min(p[0] for p in original.vertices) - .1, max(p[0] for p in original.vertices) + .1
    y0, y1 = min(p[1] for p in original.vertices) - .1, max(p[1] for p in original.vertices) + .1
    z = original.vertices[0][2] - .03
    body = _part("body", [(x0, y0, z), (x1, y0, z), (x0, y1, z), (x1, y1, z)],
                 [(0, 1, 2), (1, 3, 2)], material="skin", texture="")
    mesh = _mesh(body, garment)
    with _bound(mesh) as session:
        _fit(session)
        fitted = _snapshot(mesh, session)
        assert fitted.submeshes[0].vertices == body.vertices
        after = fitted.submeshes[1]
        if whole_part:
            # Whole-part exclusion stores a tiny valid draw. Fitting must not
            # expand it back into the removed part.
            assert max(max(p[axis] for p in after.vertices) - min(p[axis] for p in after.vertices)
                       for axis in range(3)) < .002
        else:
            assert all(after.vertices[v][2] < garment.vertices[v][2] - .02 for v in used)
        assert all(after.vertices[v] == garment.vertices[v] for v in unused)
        for channel in ("faces", "uvs", "bone_indices", "bone_weights", "name", "material"):
            assert getattr(after, channel) == getattr(garment, channel)
        edited = deepcopy(reopened)
        edited.submeshes[0].vertices = deepcopy(after.vertices)
        edited.submeshes[0].normals = deepcopy(after.normals)
        exported = rebuild_mesh_with_report(edited, result.data, original_mesh=reopened)
        reparsed = parse_pac(exported.data, "fitted-exclusions.pac")
        assert reparsed.submeshes[0].faces == garment.faces
        start = garment.source_index_offset
        end = start + garment.source_index_count * 2
        assert exported.data[start:end] == result.data[start:end]
        assert mesh_native_core.undo_native_mesh_editor_session(session)
        assert _snapshot(mesh, session).submeshes[1].vertices == garment.vertices
        assert mesh_native_core.redo_native_mesh_editor_session(session)
        assert _snapshot(mesh, session).submeshes[1].vertices == after.vertices

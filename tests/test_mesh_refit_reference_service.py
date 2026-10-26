"""Fit to body through the editor host: the authored body, its opt-out and the fallback reason."""
import numpy as np
import pytest

from cdmw.modding.mesh_refit_reference import RefitReferenceBody
from cdmw.services import mesh_refit_reference_lookup as lookup
from tests.test_mesh_archive_refit import _load_pair
from tests.test_mesh_rust_authoring_exact_output import _rig_command

LABEL = "character/model/test/nude/authored.pac"


@pytest.fixture
def editor(tmp_path):
    _source, authority, editor, _primary, _armor, _loaded = _load_pair(tmp_path, assign_body=False, role="body")
    try:
        _rig_command(editor, 3, "refit_bind", {"submesh_indices": [0]})
        yield editor
    finally:
        editor.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)


def _reference(editor, scale=.97):
    driver = editor.shadow_service.working_mesh(editor.shadow_session_id, clone=True).submeshes[1]
    points = np.asarray(driver.vertices, float)
    # Authored on a slightly smaller body than the driver it is fitted to.
    authored = points.mean(0) + (points - points.mean(0)) * scale
    return RefitReferenceBody(LABEL, authored, points, np.asarray(driver.faces))


def _garment(editor):
    return list(editor.shadow_service.working_mesh(editor.shadow_session_id, clone=True).submeshes[0].vertices)


def test_fit_to_body_uses_the_authored_body_as_one_undoable_fit(editor, monkeypatch):
    calls = []
    reference = _reference(editor)
    monkeypatch.setattr(lookup, "find_refit_reference_body", lambda context, garments, drivers, **_: (
        calls.append((tuple(garments), tuple(drivers))), lookup.RefitReferenceLookup(reference))[1])
    service, session_id = editor.shadow_service, editor.shadow_session_id
    before = _garment(editor)
    result = _rig_command(editor, 4, "refit_fit_to_body", {})
    assert calls == [((0,), (1,))]
    published = result["state"]["morph_refit"]["refit"]["reference_body"]
    assert published["label"] == LABEL and published["vertex_count"] == len(reference.source_positions)
    state = service.morph_state(session_id)
    assert dict(state.refit.reference_body.last_fit)["method"] == "reference_body"
    assert service._session(session_id).undo_stack[-1].history_label == "Fit to body"
    fitted = _garment(editor)
    assert fitted != before
    _rig_command(editor, 5, "undo", {})
    assert _garment(editor) == pytest.approx(before)
    assert service.morph_state(session_id).refit.reference_body is None
    _rig_command(editor, 6, "redo", {})
    assert _garment(editor) == pytest.approx(fitted)
    assert service.morph_state(session_id).refit.reference_body.label == LABEL
    # Opting out clears the reference within the same single Fit step.
    depth = len(service._session(session_id).undo_stack)
    _rig_command(editor, 7, "refit_fit_to_body", {"reference_body": False})
    assert service.morph_state(session_id).refit.reference_body is None
    assert len(service._session(session_id).undo_stack) == depth + 1
    assert service._session(session_id).undo_stack[-1].history_label == "Fit to body"


def test_fit_to_body_without_a_findable_authored_body_fits_the_driver_and_says_why(editor):
    service, session_id = editor.shadow_service, editor.shadow_session_id
    lookup.clear_refit_reference_cache()
    result, state = service.fit_refit_to_body(session_id)
    assert state.refit.reference_body is None
    assert any("Fit to body used only the current body: the game archive index is not available" in item
               for item in result.diagnostics)


def test_fit_to_body_rejects_unknown_arguments(editor):
    from cdmw.services.mesh_rust_authoring import RustMeshProtocolError

    for arguments in ({"reference_body": "yes"}, {"surprise": True}):
        with pytest.raises(RustMeshProtocolError):
            _rig_command(editor, 8, "refit_fit_to_body", arguments)


def _rows(editor):
    garment = editor.shadow_service.working_mesh(editor.shadow_session_id, clone=True).submeshes[0]
    return [(tuple(i), tuple(w)) for i, w in zip(garment.bone_indices, garment.bone_weights)]


def _weights(editor):
    from cdmw.services.mesh_refit_weights import RefitWeightTransfer

    mesh = editor.shadow_service.working_mesh(editor.shadow_session_id, clone=True)
    garment, driver = mesh.submeshes[0], mesh.submeshes[1]
    driver_slots = 1 + max(max(row) for row in driver.bone_indices)
    palette = 1 + max(max(row) for row in garment.bone_indices)
    # Every body slot is one bone, which the garment's palette carries in slot 0.
    return RefitWeightTransfer({1: (0,) * driver_slots}, {0: (0,)}, {0: (6,) * len(garment.vertices)}, {0: palette})


def _skin_operations(editor):
    from cdmw.domain.mesh.operations import mesh_edit_operations_from_dicts

    session = editor.shadow_service._session(editor.shadow_session_id)
    return [row for row in mesh_edit_operations_from_dicts(session.edit_operations)
            if row.operation == "replace_skin_weights_same_count"]


def test_fit_to_body_gives_the_garment_the_body_weights_for_the_exact_writer(editor, monkeypatch):
    weights = _weights(editor)
    # Authored on this very body, so the garment stays on the skin.
    monkeypatch.setattr(lookup, "find_refit_reference_body", lambda *_args, **_kwargs: lookup.RefitReferenceLookup(
        _reference(editor, 1.), weights=weights))
    own = _rows(editor)
    _rig_command(editor, 4, "refit_fit_to_body", {})
    # The garment lies on the body, so it takes the body's single bone throughout.
    assert set(_rows(editor)) == {((0,), (1.,))} != set(own)
    [operation] = _skin_operations(editor)
    assert operation.submesh_index == 0 and operation.lod_index == 0
    assert operation.metadata["palette_size"] == weights.palette_sizes[0]
    assert operation.metadata["contract"] == "cdmw_exact_pac_skin_weights_v1"
    _rig_command(editor, 5, "undo", {})
    assert _rows(editor) == own and not _skin_operations(editor)


def test_fit_to_body_keeps_the_garment_weights_when_turned_off(editor, monkeypatch):
    monkeypatch.setattr(lookup, "find_refit_reference_body", lambda *_args, **_kwargs: lookup.RefitReferenceLookup(
        _reference(editor, 1.), weights=_weights(editor)))
    own = _rows(editor)
    _rig_command(editor, 4, "refit_fit_to_body", {"body_weights": False})
    assert _rows(editor) == own and not _skin_operations(editor)


def test_body_weights_survive_finish_through_the_exact_writer(editor, monkeypatch):
    from cdmw.services.mesh_archive_refit import archive_refit_snapshots
    from tests.test_mesh_archive_refit import _request

    monkeypatch.setattr(lookup, "find_refit_reference_body", lambda *_args, **_kwargs: lookup.RefitReferenceLookup(
        _reference(editor, 1.), weights=_weights(editor)))
    _rig_command(editor, 4, "refit_fit_to_body", {})
    from cdmw.modding.mesh_parser import parse_pac

    snapshot = editor.shadow_service.capture_export_snapshot(editor.shadow_session_id)
    written = []
    for entry, component in archive_refit_snapshots(snapshot):
        result, _report = editor.shadow_service.rebuild_result_from_snapshot(component)
        written.append({tuple(row) for row in parse_pac(bytes(result.data), entry.path).submeshes[0].bone_indices})
    # The garment's PAC is written with the body's single bone; the body's PAC keeps its own rows.
    assert {(0,)} in written and any(rows != {(0,)} for rows in written)
    finished = editor.finish(_request(editor, "finish_request", 21))
    assert all(asset["status"] == "passed" for asset in finished["exact_output_validation"]["assets"])

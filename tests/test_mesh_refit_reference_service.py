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


def _reference(editor):
    driver = editor.shadow_service.working_mesh(editor.shadow_session_id, clone=True).submeshes[1]
    points = np.asarray(driver.vertices, float)
    # Authored on a slightly smaller body than the driver it is fitted to.
    authored = points.mean(0) + (points - points.mean(0)) * .97
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

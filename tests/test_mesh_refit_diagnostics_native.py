"""Bounded, read-only measurements of the published Refit geometry."""
from copy import deepcopy

import pytest

from tests.test_mesh_refit_layer_boundaries_native import _combined_part
from tests.test_mesh_refit_tightening_native import _arm, _bound, _fit, _mesh, _sleeve
from tests.test_native_mesh_editor_morph_refit import (
    _command, _open, _snapshot, _state, mesh_native_core,
)


def _analyze(session, parts=(1,), *, samples=128, details=4):
    return _command(session, "morph_state", {
        "include_refit_diagnostics": True,
        "submesh_indices": list(parts),
        "diagnostic_sample_limit": samples,
        "diagnostic_detail_limit": details,
    })["refit_diagnostics"]


def _positions(mesh):
    return [part.vertices for part in mesh.submeshes]


def test_diagnostics_are_opt_in_and_preserve_state_geometry_masks_and_history():
    mesh = _mesh(_arm(), _sleeve())
    with _bound(mesh) as session:
        _fit(session, tightness=50., vertex_masks=[{
            "submesh_index": 1,
            "vertex_indices": list(range(1, len(mesh.submeshes[1].vertices))),
            "weights": [1.] * (len(mesh.submeshes[1].vertices) - 1),
        }])
        before_state = deepcopy(_state(session))
        before_mesh = _snapshot(mesh, session)
        report = _analyze(session, samples=96, details=3)
        assert report["available"]
        assert report["session_id"] == session
        assert report["state_revision"] == before_state["state_revision"]
        assert report["edit_revision"] == before_state["edit_revision"]
        assert report["planned_sample_count"] == 96
        assert report["body_clearance"]["evaluated_sample_count"] == 96
        assert report["candidate_sample_count"] > 96
        assert report["sampled"] is True
        assert report["global_collision_proof"] is False
        assert report["parts"][0]["submesh_index"] == 1
        assert report["parts"][0]["has_influence_mask"] is True
        assert report["parts"][0]["minimum_distance_sample"]["submesh_index"] == 1
        assert not report["layer_spacing"]["available"]
        assert report["triangle_tests"] <= report["limits"]["triangle_tests"]
        assert report["queries"] <= report["limits"]["queries"]
        assert "refit_diagnostics" not in _command(session, "morph_state")
        assert _state(session) == before_state
        after_mesh = _snapshot(mesh, session)
        for before, after in zip(before_mesh.submeshes, after_mesh.submeshes):
            for channel in ("vertices", "faces", "normals", "uvs", "bone_weights", "bone_indices", "name", "material"):
                assert getattr(before, channel) == getattr(after, channel)
        # Analysis must not insert a history step ahead of the fit.
        assert mesh_native_core.undo_native_mesh_editor_session(session)
        assert _positions(_snapshot(mesh, session)) == _positions(mesh)
        assert mesh_native_core.redo_native_mesh_editor_session(session)
        assert _positions(_snapshot(mesh, session)) == _positions(before_mesh)


def test_diagnostics_measure_current_clearance_and_identify_new_revisions():
    mesh = _mesh(_arm(), _sleeve())
    with _bound(mesh) as session:
        before_binding = deepcopy(_state(session)["refit"])
        loose = _analyze(session, samples=256)
        assert .039 < loose["body_clearance"]["minimum_distance"] < .041
        _fit(session)
        fitted = _analyze(session, samples=256)
        assert fitted["body_clearance"]["minimum_distance"] < .003
        assert fitted["state_revision"] > loose["state_revision"]
        assert fitted["edit_revision"] > loose["edit_revision"]
        assert fitted["state_revision"] == _state(session)["state_revision"]
        for key in ("maximum_distance", "p95_distance", "warning_distance"):
            assert _state(session)["refit"][key] == before_binding[key]


@pytest.mark.parametrize("packed", (False, True), ids=("separate-parts", "one-part-islands"))
def test_diagnostics_distinguish_layer_collapse_with_unchanged_binding_metadata(packed):
    inner, outer = _sleeve(), _sleeve(radius=.11)
    mesh = _mesh(_arm(), _combined_part("layers", (inner, outer))) if packed else _mesh(_arm(), inner, outer)
    target = 1 if packed else 2
    offset = len(inner.vertices) if packed else 0
    garments = (1,) if packed else (1, 2)
    with _bound(mesh) as session:
        # An authored field provides a controlled bad current shape without
        # changing the retained neutral surface or the original binding data.
        # No tightening/clearance is active, so this isolates the diagnostic.
        _command(session, "morph_upload", {"profile": {
            "profile_id": "fit", "name": "Fit", "topology_fingerprint": "a" * 64,
            "definitions": [{"definition_id": "collapse", "label": "Collapse",
                             "min_percent": 0., "max_percent": 100., "default_percent": 0.}],
            "fields": [{"definition_id": "collapse", "submesh_index": target,
                        "vertex_indices": list(range(offset, offset + len(outer.vertices))),
                        "deltas": [[x * (.10001 / .11 - 1.), 0., z * (.10001 / .11 - 1.)]
                                   for x, _, z in outer.vertices]}],
        }})
        preserved = _analyze(session, garments, samples=512, details=3)
        binding = deepcopy(_state(session)["refit"])
        assert preserved["layer_spacing"]["available"]
        assert preserved["layer_spacing"]["minimum_retained_ratio"] == pytest.approx(1., abs=1e-9)
        assert preserved["layer_spacing"]["minimum_current_gap"] > .009
        _command(session, "morph_change", {
            "definition_id": "collapse", "value": 100., "phase": "end", "change_id": "collapse-probe",
        })
        current = _snapshot(mesh, session)
        state = deepcopy(_state(session))
        collapsed = _analyze(session, garments, samples=512, details=3)
        layers = collapsed["layer_spacing"]
        assert layers["available"]
        assert layers["minimum_retained_ratio"] < .01
        assert layers["minimum_current_gap"] < .0001
        assert layers["recognized_correspondence_count"] > len(layers["details"])
        assert len(layers["details"]) == 3
        assert layers["details_truncated"]
        assert {row["submesh_index"] for row in collapsed["parts"]} == set(garments)
        for row in layers["details"]:
            assert row["sample"]["submesh_index"] in garments
            assert row["target_submesh_index"] in garments
            assert len(row["sample"]["vertex_indices"]) == 3
            assert len(row["target_vertex_indices"]) == 3
        for key in ("maximum_distance", "p95_distance", "warning_distance"):
            assert state["refit"][key] == binding[key]
        assert _state(session) == state
        assert _positions(_snapshot(mesh, session)) == _positions(current)


def test_diagnostics_do_not_turn_local_normals_or_ambiguous_layers_into_collision_proof():
    mesh = _mesh(_arm(), _sleeve(radius=.02), _sleeve(radius=.020001))
    with _bound(mesh) as session:
        report = _analyze(session, (1, 2), samples=64)
        assert report["body_clearance"]["minimum_distance"] > .03
        assert report["body_clearance"]["minimum_normal_offset"] < -.03
        assert "not an inside-body test" in report["body_clearance"]["normal_offset_method"]
        assert report["global_collision_proof"] is False
        assert report["layer_spacing"]["available"] is False
        assert report["layer_spacing"]["ambiguous_candidate_count"] > 0
        assert report["layer_spacing"]["minimum_retained_ratio"] is None
        assert report["layer_spacing"]["reason"]


@pytest.mark.parametrize("arguments", (
    {},
    {"submesh_indices": []},
    {"submesh_indices": [0]},
    {"submesh_indices": [1, 1]},
    {"submesh_indices": [1.5]},
    {"submesh_indices": [1], "diagnostic_sample_limit": 0},
    {"submesh_indices": [1], "diagnostic_sample_limit": 4097},
    {"submesh_indices": [1], "diagnostic_detail_limit": 65},
    {"submesh_indices": [1], "diagnostic_sample_limit": 1.5},
))
def test_invalid_diagnostic_requests_leave_runtime_unchanged(arguments):
    mesh = _mesh(_arm(), _sleeve())
    with _bound(mesh) as session:
        before = deepcopy(_state(session))
        result = mesh_native_core.native_mesh_editor_session_command("morph_state", session, {
            "include_refit_diagnostics": True, **arguments,
        })
        assert result is None
        assert "diagnostic" in mesh_native_core.last_native_mesh_core_job_error().lower()
        assert _state(session) == before
        assert _positions(_snapshot(mesh, session)) == _positions(mesh)


def test_diagnostics_without_a_binding_report_unavailable():
    mesh = _mesh(_arm(), _sleeve())
    session = _open(mesh)
    try:
        report = _analyze(session)
        assert not report["available"]
        assert report["status"] == "unavailable"
        assert "Bind garments" in report["reason"]
        assert not report["body_clearance"]["available"]
        assert not report["layer_spacing"]["available"]
        assert _positions(_snapshot(mesh, session)) == _positions(mesh)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session)

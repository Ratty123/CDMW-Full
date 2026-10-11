"""Service contract checks that do not start a resident native session."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh import (
    MeshEditCommand, MeshEditResult, MeshEditSelection, MeshMorphDefinition, MeshMorphFittingRecipe,
    MeshMorphProfile, MeshMorphRule, MeshMorphSparseField, MeshMorphState,
    MeshMorphValuePreset, MeshMorphVertexWeight, MeshRefitBindingSummary,
    MeshRefitDriverRegion, MeshRefitGarmentSettings, create_authored_morph_definition,
    mesh_morph_base_fingerprint, mesh_morph_driver_topology_fingerprint,
    mesh_morph_role_topology_fingerprint, with_morph_garment_corrections,
)
from cdmw.services.mesh_service import MeshService  # Loads the shared snapshot helpers.
from cdmw.services.mesh_service_morph import MeshMorphServiceMixin, _MeshMorphSessionData
from cdmw.services.mesh_service_morph_authoring import (
    _MorphAuthoringBaseline, _MorphCorrectionCapture, _merged_correction_fields,
    _neutral_rows, _refit_masks_from_report, _selected_vertices, _settings_payload,
    _updated_vertex_mask, clone_authoring_baseline, clone_correction_capture,
)
from cdmw.services.mesh_service_morph_recipes import (
    fitting_recipe_from_payload, fitting_recipe_payload, read_fitting_recipe,
    serialized_fitting_recipe,
)
from tests.test_native_mesh_editor_morph_refit import _driver_garment_mesh


def _profile(mesh):
    definition = MeshMorphDefinition(
        definition_id="lift", label="Lift", category="Body",
        vertices=(MeshMorphVertexWeight(0, 0),),
        pivot=(0.0, 0.0, 0.0),
        local_basis=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        rule=MeshMorphRule("move", axis="z", amount=0.25, feather=0, falloff="constant"),
    )
    return MeshMorphProfile(
        profile_id="body", name="Body", definitions=(definition,),
        topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, (definition,)),
    )


def _recipe(mesh, profile=None):
    profile = profile or _profile(mesh)
    return MeshMorphFittingRecipe(
        recipe_id="outfit", name="Outfit", profile=profile,
        preset=MeshMorphValuePreset(
            preset_id="half", name="Half", profile_id=profile.profile_id,
            topology_fingerprint=profile.topology_fingerprint, values=(("lift", 50.0),),
        ),
        driver_submesh_indices=(0, 1),
        garment_settings=(
            MeshRefitGarmentSettings(2, vertex_mask=()),
            MeshRefitGarmentSettings(3, mode="rigid_component", vertex_mask=None),
        ),
        garment_regions=((2, (MeshRefitDriverRegion(0, (0, 1, 2)),)),),
        topology_fingerprint=mesh_morph_role_topology_fingerprint(mesh, (0, 1, 2, 3)),
        base_geometry_fingerprint=mesh_morph_base_fingerprint(mesh, (0, 1, 2, 3)),
    )


class Harness(MeshMorphServiceMixin):
    def __init__(self, root, mesh=None):
        self.root = Path(root)
        mesh = mesh or _driver_garment_mesh()
        self.neutral = deepcopy(mesh)
        self.session = SimpleNamespace(
            session_id="mock", working_mesh=deepcopy(mesh), base_mesh=deepcopy(mesh),
            selection=MeshEditSelection(), export_lock=threading.RLock(),
            revision=0, morph_session_revision=0, undo_stack=[],
        )
        profile = _profile(mesh)
        self._morph_sessions = {"mock": _MeshMorphSessionData(
            profile=profile, known_profiles={profile.profile_id: profile}, profiles_frozen=True,
            topology_mesh=deepcopy(mesh),
            state=MeshMorphState(
                session_id="mock", profile_id=profile.profile_id, definitions=profile.definitions,
                values=(("lift", 0.0),), driver_submesh_indices=(0, 1),
                refit=MeshRefitBindingSummary(
                    driver_submesh_indices=(0, 1), garment_submesh_indices=(2, 3),
                    garment_settings=(MeshRefitGarmentSettings(2), MeshRefitGarmentSettings(3, mode="rigid", intensity_percent=70)),
                ),
            ),
        )}
        self.commands = []
        self.captures = 0
        self.rollbacks = 0
        self.fail_part = None

    @property
    def data(self):
        return self._morph_sessions["mock"]

    def _session(self, session_id):
        assert session_id == "mock"
        return self.session

    def _profile_root(self):
        return self.root

    def _working_mesh_locked(self, session, *, clone):
        return deepcopy(session.working_mesh) if clone else session.working_mesh

    def _native_neutral_mesh_locked(self, session, indices):
        return deepcopy(self.neutral)

    def _ensure_native_morph_session_locked(self, session):
        pass

    def _profiles_locked(self, session, **kwargs):
        return tuple(self.data.known_profiles.values()), ()

    def _refresh_cached_morph_metadata_locked(self, session):
        state = replace(
            self.data.state, profile_id=self.data.profile.profile_id if self.data.profile else "",
            definitions=self.data.profile.definitions if self.data.profile else (),
            authoring_baseline_ready=self.data.authoring_baseline is not None,
            authoring_driver_submesh_indices=self.data.authoring_baseline.driver_submesh_indices if self.data.authoring_baseline else (),
            correction_definition_id=self.data.correction_capture.definition_id if self.data.correction_capture else "",
            correction_garment_submesh_indices=self.data.correction_capture.garment_submesh_indices if self.data.correction_capture else (),
        )
        self.data.state = state
        return state

    def _result(self, session, action, **kwargs):
        return MeshEditResult(action, "ok", session.revision)

    def _capture_morph_profile_history_locked(self, session, **kwargs):
        self.captures += 1
        return deepcopy(self.data), deepcopy(session.working_mesh), session.revision

    def _publish_morph_profile_history_locked(self, session, snapshot, *, base_revision):
        session.undo_stack.append(snapshot)
        if session.revision == base_revision:
            session.revision += 1

    def _rollback_unpublished_morph_profile_history_locked(self, session, snapshot):
        self.rollbacks += 1
        self._morph_sessions["mock"], session.working_mesh, session.revision = snapshot

    def _run_morph_command_locked(self, session, command, payload, **kwargs):
        self.commands.append((command, deepcopy(payload), dict(kwargs)))
        targets = payload.get("garment_submesh_indices", ())
        if self.fail_part is not None and self.fail_part in targets:
            raise RuntimeError("injected garment failure")
        if command == "morph_configure_refit":
            settings = {item.submesh_index: item for item in self.data.state.refit.garment_settings}
            if "garment_settings" in payload:
                assert not {"enabled", "intensity_percent", "mode", "clearance_percent", "vertex_masks"}.intersection(payload)
                rows = payload["garment_settings"]
                assert len(rows) == len(targets)
                assert {row["submesh_index"] for row in rows} == set(targets)
                for row in rows:
                    index = row["submesh_index"]
                    previous = settings[index]
                    mask = previous.vertex_mask
                    if "vertex_mask" in row:
                        raw_mask = row["vertex_mask"]
                        mask = None if raw_mask is None else _refit_masks_from_report({
                            "vertex_masks": [{"submesh_index": index, **raw_mask}],
                        })[index]
                    settings[index] = MeshRefitGarmentSettings(
                        index, row.get("enabled", previous.enabled),
                        row.get("intensity_percent", previous.intensity_percent),
                        row.get("mode", previous.mode), row.get("clearance_percent", previous.clearance_percent), mask,
                    )
            else:
                masks = _refit_masks_from_report(payload)
                for index in targets:
                    mask = settings[index].vertex_mask
                    if "vertex_masks" in payload:
                        mask = masks.get(index)
                    settings[index] = MeshRefitGarmentSettings(
                        index, payload["enabled"], payload["intensity_percent"], payload["mode"], payload["clearance_percent"], mask,
                    )
            self.data.state = replace(self.data.state, refit=replace(self.data.state.refit, garment_settings=tuple(settings.values())))
        if "values" in payload:
            self.data.state = replace(self.data.state, values=tuple(sorted(payload["values"].items())))
        session.morph_session_revision += 1
        return {"status": "ok"}

    def _morph_result_and_state_locked(self, session, action, report):
        return self._result(session, action), self._refresh_cached_morph_metadata_locked(session)


def test_selection_mask_preserves_unselected_full_influence_and_clear_distinction():
    unmasked = MeshRefitGarmentSettings(2)
    changed = _updated_vertex_mask(unmasked, 4, (1,), 0.0)
    assert changed == ((0, 1.0), (2, 1.0), (3, 1.0))
    protected = MeshRefitGarmentSettings(2, vertex_mask=())
    assert _updated_vertex_mask(protected, 4, (1,), 0.5) == ((1, 0.5),)
    assert _settings_payload(unmasked, include_mask=True)["vertex_masks"] == []
    assert _settings_payload(protected, include_mask=True)["vertex_masks"] == [
        {"submesh_index": 2, "vertex_indices": [], "weights": []}
    ]


def test_influence_is_one_transaction_and_retains_other_garment_settings(tmp_path):
    service = Harness(tmp_path)
    untouched = service.data.state.refit.garment_settings[1]
    result, state = service.set_refit_vertex_influence(
        "mock", selection=MeshEditSelection.from_maps(vertices_by_submesh={2: (0,)}), weight=0.25,
    )
    assert result.ok and len(service.session.undo_stack) == 1
    settings = {item.submesh_index: item for item in state.refit.garment_settings}
    assert dict(settings[2].vertex_mask)[0] == 0.25
    assert dict(settings[2].vertex_mask)[1] == 1.0
    assert settings[3] == untouched
    assert all(call[2]["record_history"] is False for call in service.commands)


def test_multi_garment_failure_rolls_back_prior_configuration(tmp_path):
    service = Harness(tmp_path)
    before = deepcopy(service.data)
    service.fail_part = 3
    with pytest.raises(RuntimeError, match="injected garment"):
        service.set_refit_vertex_influence(
            "mock", selection=MeshEditSelection.from_maps(source_indices=(2, 3)), weight=0.0,
        )
    assert service.rollbacks == 1
    assert not service.session.undo_stack
    assert service.data.state == before.state
    assert not service.data.authoring_operation


@pytest.mark.parametrize("selection", [MeshEditSelection(), MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)})])
def test_driver_region_never_broadens_empty_or_partial_selection(tmp_path, selection):
    service = Harness(tmp_path)
    with pytest.raises(ValueError):
        service.set_refit_driver_region("mock", (2,), selection=selection)
    assert not service.commands and not service.captures


def test_driver_region_uses_explicit_garment_destination_and_preserves_existing(tmp_path):
    service = Harness(tmp_path)
    service.set_refit_driver_region("mock", (3,), selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}))
    command, payload, _options = service.commands[-1]
    assert command == "morph_bind"
    assert payload == {
        "garment_submesh_indices": [3], "preserve_existing": True,
        "driver_regions": [{"submesh_index": 0, "vertex_indices": [0, 1, 2]}],
    }


def test_authored_upload_sends_base_and_correction_stages_once(tmp_path):
    service = Harness(tmp_path)
    neutral = deepcopy(service.neutral)
    target = deepcopy(neutral)
    target.submeshes[0].vertices[0] = (0.0, 0.0, 0.3)
    definition = create_authored_morph_definition(neutral, target, definition_id="shape", label="Shape", submesh_indices=(0,))
    definition = with_morph_garment_corrections(definition, neutral, (
        MeshMorphSparseField("shape", 2, (0,), ((0.0, 0.0, 0.2),)),
    ))
    profile = MeshMorphProfile("shape", "Shape", mesh_morph_driver_topology_fingerprint(neutral, (definition,)), (definition,))
    service._activate_morph_profile_locked(
        service.session, profile, preserve_runtime=True, record_history=False,
        neutral_positions=_neutral_rows(neutral, (0, 2)), values={"shape": 100.0}, base_mesh=neutral,
    )
    assert len(service.commands) == 1
    command, payload, _options = service.commands[0]
    assert command == "morph_upload"
    assert payload["preserve_runtime"] is True
    assert payload["values"] == {"shape": 100.0}
    assert [(item["submesh_index"], item["stage"]) for item in payload["profile"]["fields"]] == [(0, "base"), (2, "post_refit")]


def test_authored_target_source_mismatch_preserves_pending_baseline(tmp_path):
    service = Harness(tmp_path)
    service.capture_morph_baseline("mock", (0,))
    service.session.working_mesh.submeshes[0].source_vertex_map.reverse()
    service.session.working_mesh.submeshes[0].vertices[0] = (0.0, 0.0, 0.2)
    before = len(service.session.undo_stack)
    with pytest.raises(ValueError, match="source/skin"):
        service.capture_authored_morph_definition("mock", definition_id="shape", label="Shape")
    assert service.data.authoring_baseline is not None
    assert len(service.session.undo_stack) == before
    assert not service.commands


def test_discard_baseline_preserves_sculpt_and_history_can_restore_capture(tmp_path):
    service = Harness(tmp_path)
    service.capture_morph_baseline("mock", (0,))
    service.session.working_mesh.submeshes[0].vertices[0] = (0.0, 0.0, 0.2)
    result, state = service.cancel_morph_baseline("mock")
    assert result.ok and not state.authoring_baseline_ready
    assert service.session.working_mesh.submeshes[0].vertices[0][2] == 0.2
    assert service.session.undo_stack[-1][0].authoring_baseline is not None


def test_pending_authoring_guard_runs_before_native_work(tmp_path):
    service = Harness(tmp_path)
    service.data.authoring_baseline = _MorphAuthoringBaseline(deepcopy(service.neutral), (0,))
    with pytest.raises(RuntimeError, match="baseline"):
        MeshMorphServiceMixin._run_morph_command_locked(
            service, service.session, "morph_finish", {}, history_label="Finish", record_history=True,
        )
    assert not service.commands


def test_recipe_roundtrip_preserves_none_empty_masks_and_per_garment_regions():
    recipe = _recipe(_driver_garment_mesh())
    restored = fitting_recipe_from_payload(fitting_recipe_payload(recipe))
    assert restored == recipe
    assert restored.garment_settings[0].vertex_mask == ()
    assert restored.garment_settings[1].vertex_mask is None
    assert restored.garment_regions[0][1][0].vertex_indices == (0, 1, 2)


def test_recipe_wrong_neutral_geometry_rejected_before_transaction_or_files(tmp_path):
    service = Harness(tmp_path / "profiles")
    recipe = _recipe(service.neutral)
    path = tmp_path / "recipe.json"
    path.write_text(serialized_fitting_recipe(recipe), encoding="utf-8")
    service.neutral.submeshes[3].vertices[0] = (10.0, 0.0, 0.3)
    with pytest.raises(ValueError, match="neutral geometry"):
        service.import_refit_recipe("mock", path, (2,))
    assert not service.commands and not service.captures
    assert not service.root.exists()


def test_recipe_batch_preflights_all_targets_and_preserves_binding_scope(tmp_path):
    service = Harness(tmp_path / "profiles")
    path = tmp_path / "recipe.json"
    path.write_text(serialized_fitting_recipe(_recipe(service.neutral)), encoding="utf-8")
    result, _state = service.import_refit_recipe("mock", path, (2,))
    assert result.ok and len(service.session.undo_stack) == 1
    binds = [payload for command, payload, _options in service.commands if command == "morph_bind"]
    assert len(binds) == 1 and binds[0]["garment_submesh_indices"] == [2]
    assert binds[0]["preserve_existing"] is True
    assert binds[0]["driver_regions"][0]["vertex_indices"] == [0, 1, 2]
    assert all(command != "morph_set_driver" for command, _payload, _options in service.commands)
    assert service.data.state.values == (("lift", 50.0),)
    assert (service.root / "definitions" / "body.json").is_file()


def test_active_recipe_export_uses_neutral_identity_and_current_values(tmp_path):
    service = Harness(tmp_path / "profiles")
    service.data.state = replace(service.data.state, values=(("lift", 50.0),), unbaked=True)
    service.session.working_mesh.submeshes[0].vertices[0] = (0.0, 0.0, 0.125)
    path = service.export_refit_recipe("mock", tmp_path / "recipe.json", "Preview")
    recipe = read_fitting_recipe(path)
    assert recipe.preset.values == (("lift", 50.0),)
    assert recipe.base_geometry_fingerprint == mesh_morph_base_fingerprint(service.neutral, (0, 1, 2, 3))
    assert recipe.base_geometry_fingerprint != mesh_morph_base_fingerprint(service.session.working_mesh, (0, 1, 2, 3))


def test_recipe_read_and_serialization_respect_size_limits(tmp_path):
    recipe = _recipe(_driver_garment_mesh())
    with pytest.raises(ValueError, match="limit"):
        serialized_fitting_recipe(recipe, max_bytes=20)
    path = tmp_path / "oversize.json"
    path.write_bytes(b" " * 21)
    with pytest.raises(ValueError, match="limit"):
        read_fitting_recipe(path, max_bytes=20)


def test_native_state_decoder_keeps_mask_and_region_identity(tmp_path):
    service = Harness(tmp_path)
    report = {"morph_state": {
        "profile_id": "body", "driver_submesh_indices": [0, 1],
        "refit": {
            "driver_submesh_indices": [0, 1], "garment_submesh_indices": [2, 3],
            "garment_settings": [{"submesh_index": 2}, {"submesh_index": 3}],
            "vertex_masks": [{"submesh_index": 2, "vertex_indices": [], "weights": []}],
            "garment_regions": [{"garment_submesh_index": 2, "driver_regions": [{"submesh_index": 0, "vertex_indices": [0, 1, 2]}]}],
        },
    }}
    state = service._morph_state_from_report_locked(service.session, report)
    assert state.refit.garment_settings[0].vertex_mask == ()
    assert state.refit.garment_settings[1].vertex_mask is None
    assert state.refit.garment_regions[0][1][0] == MeshRefitDriverRegion(0, (0, 1, 2))


def test_native_neutral_query_is_read_only_and_requires_complete_positions(tmp_path, monkeypatch):
    service = Harness(tmp_path)
    service.session.working_mesh.submeshes[0].vertices[0] = (0.0, 0.0, 5.0)
    calls = []

    def query(command, session_id, payload, **kwargs):
        calls.append((command, payload))
        return {"status": "ok", "neutral_positions": _neutral_rows(service.neutral, (0,))}

    monkeypatch.setattr("cdmw.services.mesh_service_morph.native_mesh_editor_session_command", query)
    neutral = MeshMorphServiceMixin._native_neutral_mesh_locked(service, service.session, (0,))
    assert neutral.submeshes[0].vertices[0][2] == 0.0
    assert service.session.working_mesh.submeshes[0].vertices[0][2] == 5.0
    assert calls == [("morph_state", {"include_neutral_positions": True, "submesh_indices": [0]})]
    monkeypatch.setattr("cdmw.services.mesh_service_morph.native_mesh_editor_session_command", lambda *args, **kwargs: {"status": "ok", "neutral_positions": []})
    with pytest.raises(RuntimeError, match="omitted"):
        MeshMorphServiceMixin._native_neutral_mesh_locked(service, service.session, (0,))


def test_correction_normalization_uses_effective_cohort_influence():
    mesh = _driver_garment_mesh()
    definition = with_morph_garment_corrections(_profile(mesh).definitions[0], mesh, (
        MeshMorphSparseField("lift", 2, (3,), ((0.0, 0.0, 0.3),)),
        MeshMorphSparseField("lift", 3, (0,), ((0.0, 0.0, 0.1),)),
    ))
    changes = (MeshMorphSparseField("lift", 2, (3,), ((0.0, 0.0, 0.2),)),)
    fields = _merged_correction_fields(definition, changes, {2: ((3, 0.25),)})
    by_part = {item.submesh_index: item for item in fields}
    assert by_part[2].deltas[0][2] == pytest.approx(1.1)
    assert by_part[3] == definition.garment_corrections[1]
    with pytest.raises(ValueError, match="protected"):
        _merged_correction_fields(definition, changes, {2: ((3, 0.0),)})


def test_capture_history_clones_preview_base_and_effective_masks(monkeypatch):
    mesh = _driver_garment_mesh()
    monkeypatch.setattr(
        "cdmw.services.mesh_service_morph_authoring._clone_authoring_mesh",
        lambda source, operation: deepcopy(source),
    )
    baseline = _MorphAuthoringBaseline(mesh, (0,))
    capture = _MorphCorrectionCapture("lift", (2,), mesh, deepcopy(mesh), (("lift", 0.0),), ((2, ((0, 0.25),)),))
    cloned_base = clone_authoring_baseline(baseline)
    cloned_capture = clone_correction_capture(capture)
    assert cloned_base.mesh is not mesh
    assert cloned_capture.preview_mesh is not capture.preview_mesh
    assert cloned_capture.neutral_mesh is not capture.neutral_mesh
    assert cloned_capture.effective_vertex_masks == ((2, ((0, 0.25),)),)
    mesh.submeshes[0].vertices[0] = (0.0, 0.0, 3.0)
    assert cloned_base.mesh.submeshes[0].vertices[0][2] == 0.0
    assert cloned_capture.preview_mesh.submeshes[0].vertices[0][2] == 0.0


def test_explicit_recapture_is_undoable_and_uses_current_zero_base(tmp_path):
    service = Harness(tmp_path)
    service.capture_morph_baseline("mock", (0,))
    service.session.working_mesh.submeshes[0].vertices[0] = (0.0, 0.0, 0.2)
    service.capture_morph_baseline("mock", (0,))
    assert service.data.authoring_baseline.mesh.submeshes[0].vertices[0][2] == 0.2
    assert service.session.undo_stack[-1][0].authoring_baseline.mesh.submeshes[0].vertices[0][2] == 0.0


def test_influence_rejects_stale_authored_base_before_bypass_transaction(tmp_path):
    service = Harness(tmp_path)
    target = deepcopy(service.neutral)
    target.submeshes[0].vertices[0] = (0.0, 0.0, 0.2)
    definition = create_authored_morph_definition(
        service.neutral, target, definition_id="lift", label="Lift", submesh_indices=(0,),
    )
    service.data.profile = replace(service.data.profile, definitions=(definition,))
    service.neutral.submeshes[0].vertices[0] = (0.0, 0.0, 0.5)
    with pytest.raises(ValueError, match="base geometry"):
        service.set_refit_vertex_influence(
            "mock", selection=MeshEditSelection.from_maps(vertices_by_submesh={2: (0,)}), weight=0.0,
        )
    assert not service.commands and not service.captures


def test_recipe_driver_change_clears_only_when_all_existing_bindings_are_targets(tmp_path):
    service = Harness(tmp_path / "profiles")
    service.data.state = replace(
        service.data.state, driver_submesh_indices=(0,),
        refit=replace(service.data.state.refit, driver_submesh_indices=(0,)),
    )
    path = tmp_path / "recipe.json"
    path.write_text(serialized_fitting_recipe(_recipe(service.neutral)), encoding="utf-8")
    with pytest.raises(ValueError, match="other bound garments"):
        service.import_refit_recipe("mock", path, (2,))
    assert not service.commands and not service.captures
    service.import_refit_recipe("mock", path)
    names = [command for command, _payload, _options in service.commands]
    assert names.index("morph_upload") < names.index("morph_clear_refit") < names.index("morph_set_driver") < names.index("morph_bind")


def test_identity_snapshot_normalizes_only_proven_authority_promotion(tmp_path):
    from cdmw.domain.mesh.topology import identity_topology_provenance
    service = Harness(tmp_path)
    mesh = deepcopy(service.session.working_mesh)
    mesh.submeshes[0].source_vertex_map_authority = "topology"
    mesh.submeshes[0].topology_provenance = identity_topology_provenance(3, 1)
    normalized = service._morph_identity_mesh_locked(service.session, mesh, (0,))
    assert normalized.submeshes[0].source_vertex_map_authority == "test"
    assert normalized.submeshes[0].topology_provenance is None
    assert service.session.working_mesh.submeshes[0].source_vertex_map_authority == "test"
    assert mesh_morph_base_fingerprint(normalized, (0,)) == mesh_morph_base_fingerprint(service.neutral, (0,))


def test_identity_snapshot_rejects_discarded_or_reordered_loaded_map(tmp_path):
    from cdmw.domain.mesh.topology import identity_topology_provenance
    service = Harness(tmp_path)
    service.session.base_mesh.submeshes[0].source_vertex_map = [2, 1, 0]
    mesh = deepcopy(service.session.working_mesh)
    mesh.submeshes[0].source_vertex_map_authority = "topology"
    mesh.submeshes[0].topology_provenance = identity_topology_provenance(3, 1)
    with pytest.raises(ValueError, match="source vertex mapping"):
        service._morph_identity_mesh_locked(service.session, mesh, (0,))


def test_history_identity_requests_native_proof_when_python_provenance_is_missing(tmp_path, monkeypatch):
    from cdmw.domain.mesh.topology import identity_topology_provenance
    service = Harness(tmp_path)
    service.session.working_mesh.submeshes[0].source_vertex_map_authority = "topology"
    service.session.working_mesh.submeshes[0].topology_provenance = None
    calls = []

    def export_proof(name, mesh, session_id, **kwargs):
        calls.append(name)
        mesh.submeshes[0].topology_provenance = identity_topology_provenance(3, 1)
        return True

    monkeypatch.setattr("cdmw.services.mesh_service_morph._service_call", export_proof)
    snapshot = service._current_morph_identity_mesh_locked(service.session, (0,))
    assert calls == ["export_native_mesh_editor_session_to_mesh"]
    assert snapshot.submeshes[0].source_vertex_map_authority == "test"
    assert service.session.working_mesh.submeshes[0].source_vertex_map_authority == "topology"
    assert service.session.working_mesh.submeshes[0].topology_provenance is None


@pytest.mark.parametrize("edited", [
    {"label": "Renamed lift"},
    {"amount": 0.5},
    {"definition_id": "renamed-lift"},
])
def test_procedural_definition_edit_retains_saved_garment_corrections(tmp_path, edited):
    from cdmw.services.mesh_morph_profiles import mesh_morph_profile_from_payload, mesh_morph_profile_payload
    service = Harness(tmp_path)
    original = with_morph_garment_corrections(service.data.profile.definitions[0], service.neutral, (
        MeshMorphSparseField("lift", 2, (0,), ((0.0, 0.0, 0.2),)),
    ))
    service.data.profile = replace(service.data.profile, definitions=(original,))
    params = {
        "profile_id": "body", "profile_name": "Body", "definition_id": "lift",
        "source_definition_id": "lift", "label": "Lift", "category": "Body",
        "rule": "move", "axis": "z", "amount": 0.25, "feather": 0,
        "falloff": "constant", "preserve_selection": True,
    }
    params.update(edited)
    profile = service.create_morph_definition("mock", **params)
    definition = profile.definitions[0]
    assert definition.garment_corrections == tuple(
        replace(field, definition_id=definition.definition_id) for field in original.garment_corrections
    )
    assert definition.correction_topology_fingerprint == original.correction_topology_fingerprint
    assert definition.correction_base_geometry_fingerprint == original.correction_base_geometry_fingerprint
    assert profile.format == "cdmw.mesh_morph_profile.v3"
    assert mesh_morph_profile_from_payload(mesh_morph_profile_payload(profile)) == profile


@pytest.mark.parametrize("invalid_change", ["garment_role", "garment_base"])
def test_procedural_definition_edit_rejects_incompatible_correction_without_publication(tmp_path, invalid_change):
    service = Harness(tmp_path)
    original = with_morph_garment_corrections(service.data.profile.definitions[0], service.neutral, (
        MeshMorphSparseField("lift", 2, (0,), ((0.0, 0.0, 0.2),)),
    ))
    service.data.profile = replace(service.data.profile, definitions=(original,))
    before = service.data.profile
    revision = service.session.morph_session_revision
    if invalid_change == "garment_role":
        service.session.selection = MeshEditSelection.from_maps(source_indices=(2,))
        message = "driver part"
    else:
        service.neutral.submeshes[2].vertices[0] = (0.0, 0.0, 1.0)
        message = "base geometry"
    with pytest.raises(ValueError, match=message):
        service.create_morph_definition(
            "mock", profile_id="body", profile_name="Body", definition_id="lift",
            source_definition_id="lift", label="Lift", rule="move", axis="z",
            amount=0.25, feather=0, falloff="constant",
            preserve_selection=invalid_change != "garment_role",
        )
    assert service.data.profile is before
    assert service.session.morph_session_revision == revision
    assert not service.commands and not service.session.undo_stack


def test_procedural_definition_edit_cannot_replace_an_authored_target(tmp_path):
    service = Harness(tmp_path)
    target = deepcopy(service.neutral)
    target.submeshes[0].vertices[0] = (0.0, 0.0, 0.2)
    original = create_authored_morph_definition(
        service.neutral, target, definition_id="lift", label="Lift", submesh_indices=(0,),
    )
    service.data.profile = replace(service.data.profile, definitions=(original,))
    before = service.data.profile
    with pytest.raises(ValueError, match="capturing a new target"):
        service.create_morph_definition(
            "mock", profile_id="body", profile_name="Body", definition_id="lift",
            source_definition_id="lift", label="Lift", preserve_selection=True,
        )
    assert service.data.profile is before
    assert not service.commands and not service.session.undo_stack


@pytest.mark.parametrize("entry", ["service", "command"])
def test_definition_authoring_snapshots_original_cache_before_one_activation(tmp_path, entry):
    service = Harness(tmp_path)
    original = service.data.profile
    params = {
        "profile_id": "body", "profile_name": "Body", "definition_id": "renamed-lift",
        "source_definition_id": "lift", "label": "Renamed Lift", "preserve_selection": True,
    }
    if entry == "service":
        profile, (result, state) = service.author_morph_definition("mock", **params)
    else:
        result = service._apply_morph_edit_command_locked(
            service.session, MeshEditCommand("morph_author_definition", params=params),
        )
        profile, state = service.data.profile, service.data.state
    assert result.ok and state.definitions == profile.definitions
    assert state.edit_revision == service.session.revision
    assert profile.definitions[0].definition_id == "renamed-lift"
    assert len(service.session.undo_stack) == 1
    assert service.session.undo_stack[0][0].profile == original
    assert len(service.commands) == 1
    assert service.commands[0][2]["record_history"] is False


@pytest.mark.parametrize("failure_stage", ["definition", "preflight", "accepted"])
def test_definition_authoring_failure_restores_cache_and_valid_history(tmp_path, monkeypatch, failure_stage):
    from cdmw.services.mesh_service_state import _MeshMorphSessionState
    service = Harness(tmp_path)
    original_profile = service.data.profile
    original_mesh = service.session.working_mesh
    original_selection = service.session.selection
    original_morph_revision = service.session.morph_session_revision
    failed_revisions = []
    python_history = SimpleNamespace(native_editor_history=False)
    native_history = SimpleNamespace(native_editor_history=True)
    redo_history = SimpleNamespace(native_editor_history=True)
    service.session.undo_stack = [python_history, native_history]
    service.session.redo_stack = [redo_history]
    service.session.native_history_undo_count = 1
    service.session.native_history_redo_count = 1
    service.session.native_history_retained_bytes = 512
    disposed = []

    def capture(session, **kwargs):
        before = Harness._capture_morph_profile_history_locked(service, session, **kwargs)
        return SimpleNamespace(
            before=before, selection=session.selection,
            morph_session_state=_MeshMorphSessionState(present=True, cache=before[0]),
        )

    def fail_activation(*args, **kwargs):
        if failure_stage == "accepted":
            service.session.morph_session_revision += 1
        failed_revisions.append(service.session.morph_session_revision)
        raise RuntimeError("injected definition activation failure")

    def rollback(session, history):
        Harness._rollback_unpublished_morph_profile_history_locked(service, session, history.before)
        # The production snapshot rollback restores the captured revision.
        session.morph_session_revision = original_morph_revision

    monkeypatch.setattr(service, "_capture_morph_profile_history_locked", capture)
    monkeypatch.setattr(service, "_rollback_unpublished_morph_profile_history_locked", rollback)
    monkeypatch.setattr(
        "cdmw.services.mesh_service_morph._dispose_history_snapshot_without_state_failure",
        lambda history: disposed.append(history) or True,
    )
    monkeypatch.setattr(service, "_activate_morph_profile_locked", fail_activation)
    if failure_stage == "definition":
        monkeypatch.setattr(service, "create_morph_definition", fail_activation)
    with pytest.raises(RuntimeError, match="injected definition activation failure"):
        service.author_morph_definition(
            "mock", selection=MeshEditSelection.from_maps(source_indices=(0,)),
            profile_id="body", profile_name="Body", definition_id="renamed-lift",
            source_definition_id="lift", label="Renamed Lift", preserve_selection=True,
        )
    assert service.data.profile == original_profile
    if failure_stage == "accepted":
        assert service.rollbacks == 1
        assert service.session.morph_session_revision > failed_revisions[-1]
        assert service.session.undo_stack == [python_history]
        assert service.session.redo_stack == []
        assert native_history in disposed and redo_history in disposed
        assert service.session.native_history_retained_bytes == 0
    else:
        assert service.rollbacks == 0
        assert service.session.working_mesh is original_mesh
        assert service.session.selection == original_selection
        assert service.session.undo_stack == [python_history, native_history]
        assert service.session.redo_stack == [redo_history]
        assert service.session.native_history_undo_count == 1
        assert service.session.native_history_redo_count == 1
        assert service.session.native_history_retained_bytes == 512

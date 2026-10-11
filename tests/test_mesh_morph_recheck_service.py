"""Focused follow-up service regressions without a resident native session."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from cdmw.domain.mesh import (
    MeshEditSelection,
    MeshRefitGarmentSettings,
    create_authored_morph_definition,
    mesh_morph_driver_topology_fingerprint,
)
from cdmw.services.mesh_service_morph_authoring import _neutral_rows, _refit_settings_batch_payload
from tests.test_mesh_morph_authoring_service import Harness


class CorrectionHarness(Harness):
    """Keep queried neutral rows distinct from unrelated current preview rows."""

    def __init__(self, root):
        super().__init__(root)
        self.neutral_queries = []
        self.fail_upload = False
        target = deepcopy(self.neutral)
        target.submeshes[0].vertices[0] = (0.0, 0.0, 0.3)
        definition = create_authored_morph_definition(
            self.neutral, target, definition_id="lift", label="Lift",
            submesh_indices=(0,),
        )
        profile = replace(
            self.data.profile, definitions=(definition,),
            topology_fingerprint=mesh_morph_driver_topology_fingerprint(self.neutral, (definition,)),
        )
        self.data.profile = profile
        self.data.known_profiles[profile.profile_id] = profile
        self.data.state = replace(
            self.data.state, definitions=profile.definitions, values=(("lift", 35.0),),
        )

    def _native_neutral_mesh_locked(self, session, indices):
        self.neutral_queries.append(tuple(indices))
        mesh = deepcopy(session.working_mesh)
        for index in indices:
            mesh.submeshes[index].vertices = list(self.neutral.submeshes[index].vertices)
        return mesh

    def _effective_refit_masks_locked(self, session, indices):
        return tuple(
            (index, tuple((vertex, 1.0) for vertex in range(len(session.working_mesh.submeshes[index].vertices))))
            for index in indices
        )

    def _run_morph_command_locked(self, session, command, payload, **kwargs):
        report = super()._run_morph_command_locked(session, command, payload, **kwargs)
        if command == "morph_upload" and self.fail_upload:
            raise RuntimeError("injected correction upload failure")
        return report

    def move_vertex(self, part, distance):
        for mesh in (self.session.working_mesh, self.neutral):
            x, y, z = mesh.submeshes[part].vertices[0]
            mesh.submeshes[part].vertices[0] = (x, y, z + distance)


def _positions(mesh):
    return tuple(tuple(tuple(point) for point in part.vertices) for part in mesh.submeshes)


def test_begin_correction_captures_every_parts_neutral_before_isolation(tmp_path):
    service = CorrectionHarness(tmp_path)
    # An unselected garment has a preview from the previously active percentages.
    x, y, z = service.session.working_mesh.submeshes[3].vertices[0]
    service.session.working_mesh.submeshes[3].vertices[0] = (x, y, z + 1.25)

    result, state = service.begin_morph_correction("mock", "lift", (2,))

    assert result.ok and state.correction_definition_id == "lift"
    assert service.neutral_queries == [(0, 1, 2, 3)]
    capture = service.data.correction_capture
    assert capture is not None
    assert _positions(capture.neutral_mesh) == _positions(service.neutral)
    assert capture.neutral_mesh.submeshes[3].vertices[0] != capture.preview_mesh.submeshes[3].vertices[0]
    assert capture.return_values == (("lift", 35.0),)


def test_cancel_after_body_and_other_part_edits_restores_all_rows_and_keeps_undo_capture(tmp_path):
    service = CorrectionHarness(tmp_path)
    service.begin_morph_correction("mock", "lift", (2,))
    original_neutral = deepcopy(service.data.correction_capture.neutral_mesh)
    for part in (0, 2, 3):
        service.move_vertex(part, 0.4 + part)
    edited = _positions(service.session.working_mesh)
    service.commands.clear()
    previous_history = len(service.session.undo_stack)

    result, state = service.cancel_morph_correction("mock")

    assert result.ok and not state.correction_definition_id
    assert state.values == (("lift", 35.0),)
    assert len(service.commands) == 1
    command, payload, options = service.commands[0]
    assert command == "morph_upload"
    assert payload["preserve_runtime"] is True
    assert payload["values"] == {"lift": 35.0}
    assert payload["neutral_positions"] == _neutral_rows(original_neutral, (0, 1, 2, 3))
    assert options["record_history"] is False
    assert len(service.session.undo_stack) == previous_history + 1
    # The same transaction records all edited geometry and the pending workflow
    # for the production history restore path, which native tests exercise.
    before_data, before_mesh, _revision = service.session.undo_stack[-1]
    assert _positions(before_mesh) == edited
    assert before_data.correction_capture is not None
    assert before_data.state.values == (("lift", 100.0),)
    assert _positions(service.data.topology_mesh) == _positions(original_neutral)


@pytest.mark.parametrize("part", [0, 2, 3])
@pytest.mark.parametrize("change", ["faces", "source_map"])
def test_cancel_rejects_identity_changes_on_every_part_without_discarding_edits(tmp_path, part, change):
    service = CorrectionHarness(tmp_path)
    service.begin_morph_correction("mock", "lift", (2,))
    service.move_vertex(2, 0.5)
    mesh_part = service.session.working_mesh.submeshes[part]
    if change == "faces":
        mesh_part.faces[0] = tuple(reversed(mesh_part.faces[0]))
    else:
        mesh_part.source_vertex_map.reverse()
    before_mesh = deepcopy(service.session.working_mesh)
    previous_history = len(service.session.undo_stack)
    previous_commands = len(service.commands)
    previous_captures = service.captures

    with pytest.raises(ValueError):
        service.cancel_morph_correction("mock")

    assert service.data.correction_capture is not None
    assert service.session.working_mesh == before_mesh
    assert len(service.session.undo_stack) == previous_history
    assert len(service.commands) == previous_commands
    assert service.captures == previous_captures


def test_cancel_upload_failure_restores_pending_values_and_edited_geometry(tmp_path):
    service = CorrectionHarness(tmp_path)
    service.begin_morph_correction("mock", "lift", (2,))
    service.move_vertex(0, 0.5)
    service.move_vertex(2, 0.8)
    before = deepcopy(service.data)
    edited = _positions(service.session.working_mesh)
    previous_history = len(service.session.undo_stack)
    service.fail_upload = True

    with pytest.raises(RuntimeError, match="injected correction upload"):
        service.cancel_morph_correction("mock")

    assert service.rollbacks == 1
    assert service.data.state == before.state
    assert service.data.correction_capture == before.correction_capture
    assert not service.data.authoring_operation
    assert _positions(service.session.working_mesh) == edited
    assert len(service.session.undo_stack) == previous_history


def test_multi_part_influence_recomposes_once_and_preserves_individual_settings(tmp_path):
    service = Harness(tmp_path)
    before = {item.submesh_index: item for item in service.data.state.refit.garment_settings}

    result, state = service.set_refit_vertex_influence(
        "mock", selection=MeshEditSelection.from_maps(vertices_by_submesh={2: (0,), 3: (1,)}),
        weight=0.25,
    )

    assert result.ok and len(service.session.undo_stack) == 1
    assert len(service.commands) == 1
    command, payload, options = service.commands[0]
    assert command == "morph_configure_refit"
    assert payload["garment_submesh_indices"] == [2, 3]
    assert set(payload) == {"garment_submesh_indices", "garment_settings"}
    assert options["record_history"] is False
    settings = {item.submesh_index: item for item in state.refit.garment_settings}
    for part, vertex in ((2, 0), (3, 1)):
        assert replace(settings[part], vertex_mask=before[part].vertex_mask) == before[part]
        assert dict(settings[part].vertex_mask)[vertex] == 0.25
    assert dict(settings[2].vertex_mask)[1] == 1.0
    assert dict(settings[3].vertex_mask)[0] == 1.0


def test_clear_masks_on_multiple_parts_is_one_configuration_and_preserves_modes(tmp_path):
    service = Harness(tmp_path)
    old_settings = tuple(
        replace(item, vertex_mask=((0, 0.5),))
        for item in service.data.state.refit.garment_settings
    )
    service.data.state = replace(
        service.data.state, refit=replace(service.data.state.refit, garment_settings=old_settings),
    )

    result, state = service.clear_refit_vertex_influence("mock", (2, 3))

    assert result.ok and len(service.session.undo_stack) == 1
    assert len(service.commands) == 1
    command, payload, _options = service.commands[0]
    assert command == "morph_configure_refit"
    assert payload["garment_submesh_indices"] == [2, 3]
    assert all(row["vertex_mask"] is None for row in payload["garment_settings"])
    assert state.refit.garment_settings == tuple(replace(item, vertex_mask=None) for item in old_settings)


def test_batch_settings_distinguish_protection_from_mask_removal():
    settings = (MeshRefitGarmentSettings(2, vertex_mask=()), MeshRefitGarmentSettings(3))
    payload = _refit_settings_batch_payload(settings)
    assert payload["garment_settings"][0]["vertex_mask"] == {"vertex_indices": [], "weights": []}
    assert payload["garment_settings"][1]["vertex_mask"] is None
    preserved = _refit_settings_batch_payload(settings, include_masks=False)
    assert all("vertex_mask" not in row for row in preserved["garment_settings"])

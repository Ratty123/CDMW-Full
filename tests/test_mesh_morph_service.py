from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection, mesh_topology_fingerprint
from cdmw.services.mesh_service import MeshService
from tests.test_native_mesh_editor_morph_refit import _driver_garment_mesh


class _Settings:
    def __init__(self, path: Path) -> None:
        self._path = path

    def fileName(self) -> str:
        return str(self._path)


def _author_command() -> MeshEditCommand:
    return MeshEditCommand(
        "morph_author_definition",
        selection=MeshEditSelection.from_maps(
            vertices_by_submesh={
                0: (0, 1, 2),
                1: (0, 1, 2),
            }
        ),
        params={
            "profile_id": "resident-body",
            "profile_name": "Resident Body",
            "definition_id": "volume",
            "label": "Volume",
            "category": "Torso",
            "rule": "move",
            "axis": "z",
            "amount": 1.0,
            "feather": 0,
            "falloff": "constant",
            "mirror_mode": "off",
            "min_percent": -50.0,
            "max_percent": 125.0,
            "default_percent": 0.0,
        },
    )


def test_mesh_service_owns_authoring_resident_values_refit_persistence_history_and_cleanup(tmp_path) -> None:
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    view = service.open_edit_session(_driver_garment_mesh(), mode="edit")
    session_id = view.session_id
    profile_path = tmp_path / "mesh_slider_profiles" / "definitions" / "resident-body.json"
    try:
        authored = service.apply_command(session_id, _author_command())
        authored_state = service.cached_morph_state(session_id)
        assert authored.ok
        assert authored_state is not None
        assert authored_state.profile_id == "resident-body"
        assert tuple((item.category, item.rule.kind, item.rule.axis) for item in authored_state.definitions) == (
            ("Torso", "move", "z"),
        )
        assert authored_state.available_profiles == (("resident-body", "Resident Body"),)
        assert not profile_path.exists()

        saved = service.apply_command(session_id, MeshEditCommand("morph_save_profile"))
        assert saved.ok
        assert profile_path.is_file()

        driver = service.apply_command(
            session_id,
            MeshEditCommand(
                "morph_set_driver",
                selection=MeshEditSelection.from_maps(source_indices=(0, 1)),
            ),
        )
        bound = service.apply_command(
            session_id,
            MeshEditCommand(
                "morph_bind",
                selection=MeshEditSelection.from_maps(source_indices=(2,)),
            ),
        )
        assert driver.ok
        assert bound.ok
        assert service.cached_morph_state(session_id).refit.garment_submesh_indices == (2,)  # type: ignore[union-attr]

        history_before_drag = service.history_usage(session_id)["undo_count"]
        with patch(
            "cdmw.services.mesh_service_morph.list_mesh_morph_profiles",
            side_effect=AssertionError("slider ticks must use cached profile metadata"),
        ):
            begin = service.apply_command(
                session_id,
                MeshEditCommand(
                    "morph_change",
                    params={"definition_id": "volume", "value": 25.0, "phase": "begin", "change_id": "drag"},
                ),
            )
            update = service.apply_command(
                session_id,
                MeshEditCommand(
                    "morph_change",
                    params={"definition_id": "volume", "value": 75.0, "phase": "update", "change_id": "drag"},
                ),
            )
            end = service.apply_command(
                session_id,
                MeshEditCommand(
                    "morph_change",
                    params={"definition_id": "volume", "value": 100.0, "phase": "end", "change_id": "drag"},
                ),
            )
        assert begin.ok and update.ok and end.ok
        assert end.native_preview_vertex_update_groups
        assert service.cached_morph_state(session_id).values == (("volume", 100.0),)  # type: ignore[union-attr]
        assert service.history_usage(session_id)["undo_count"] == history_before_drag + 1

        visible = service.working_mesh(session_id, clone=True)
        assert visible.submeshes[0].vertices[0][2] == pytest.approx(1.0)
        assert visible.submeshes[2].vertices[0][2] == pytest.approx(1.1)

        preset_saved = service.apply_command(
            session_id,
            MeshEditCommand(
                "morph_save_preset",
                params={"preset_id": "full", "name": "Full"},
            ),
        )
        assert preset_saved.ok
        service.apply_command(
            session_id,
            MeshEditCommand(
                "morph_change",
                params={"definition_id": "volume", "value": 10.0, "phase": "end", "change_id": "numeric"},
            ),
        )
        preset_applied = service.apply_command(
            session_id,
            MeshEditCommand("morph_apply_preset", params={"preset_id": "full"}),
        )
        assert preset_applied.ok
        assert service.cached_morph_state(session_id).preset_id == "full"  # type: ignore[union-attr]
        assert service.cached_morph_state(session_id).values == (("volume", 100.0),)  # type: ignore[union-attr]

        assert service.undo(session_id).ok
        assert service.cached_morph_state(session_id).preset_id == ""  # type: ignore[union-attr]
        assert service.cached_morph_state(session_id).values == (("volume", 10.0),)  # type: ignore[union-attr]
        assert service.redo(session_id).ok
        assert service.cached_morph_state(session_id).preset_id == "full"  # type: ignore[union-attr]

        finished, finished_state = service.finish_morph(session_id)
        assert finished.ok
        assert finished_state.unbaked is False
        assert finished_state.values == (("volume", 0.0),)
        output = service.working_mesh(session_id, clone=True)
        assert output.submeshes[0].vertices == visible.submeshes[0].vertices
        assert output.submeshes[2].vertices == visible.submeshes[2].vertices
    finally:
        service.close_edit_session(session_id)

    assert session_id not in service._morph_sessions
    with pytest.raises(KeyError):
        service.morph_state(session_id)


def test_definition_delete_recomputes_driver_identity_even_when_profile_becomes_empty(tmp_path) -> None:
    mesh = _driver_garment_mesh()
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    session_id = service.open_edit_session(mesh, mode="edit").session_id
    try:
        assert service.apply_command(session_id, _author_command()).ok
        original_definition = service.cached_morph_state(session_id).definitions[0]  # type: ignore[union-attr]
        edited = service.apply_command(
            session_id,
            MeshEditCommand(
                "morph_author_definition",
                selection=MeshEditSelection(),
                params={
                    "profile_id": "resident-body",
                    "profile_name": "Resident Body",
                    "source_definition_id": "volume",
                    "definition_id": "volume",
                    "label": "Edited Volume",
                    "category": "Shape",
                    "rule": "move",
                    "axis": "z",
                    "amount": 0.5,
                    "feather": 0,
                    "falloff": "constant",
                    "mirror_mode": "off",
                    "min_percent": -25.0,
                    "max_percent": 75.0,
                    "default_percent": 0.0,
                    "preserve_selection": True,
                },
            ),
        )
        edited_definition = service.cached_morph_state(session_id).definitions[0]  # type: ignore[union-attr]
        assert edited.ok
        assert edited_definition.label == "Edited Volume"
        assert edited_definition.category == "Shape"
        assert (edited_definition.min_percent, edited_definition.max_percent) == (-25.0, 75.0)
        assert edited_definition.vertices == original_definition.vertices
        assert edited_definition.pivot == original_definition.pivot
        assert edited_definition.local_basis == original_definition.local_basis
        deleted = service.apply_command(
            session_id,
            MeshEditCommand("morph_delete_definition", params={"definition_id": "volume"}),
        )
        state = service.cached_morph_state(session_id)
        assert deleted.ok
        assert state is not None
        assert state.profile_id == "resident-body"
        assert state.definitions == ()
        assert state.topology_fingerprint == mesh_topology_fingerprint(mesh)
    finally:
        service.close_edit_session(session_id)


def test_preset_and_active_profile_delete_clear_runtime_state_without_hidden_history(tmp_path) -> None:
    mesh = _driver_garment_mesh()
    baseline = tuple(mesh.submeshes[0].vertices)
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    session_id = service.open_edit_session(mesh, mode="edit").session_id
    profile_path = tmp_path / "mesh_slider_profiles" / "definitions" / "resident-body.json"
    try:
        assert service.apply_command(session_id, _author_command()).ok
        assert service.apply_command(session_id, MeshEditCommand("morph_save_profile")).ok
        assert service.apply_command(
            session_id,
            MeshEditCommand(
                "morph_change",
                params={"definition_id": "volume", "value": 100.0, "phase": "end", "change_id": "delete"},
            ),
        ).ok
        assert service.apply_command(
            session_id,
            MeshEditCommand("morph_save_preset", params={"preset_id": "full", "name": "Full"}),
        ).ok
        assert service.apply_command(
            session_id,
            MeshEditCommand("morph_apply_preset", params={"preset_id": "full"}),
        ).ok
        assert service.cached_morph_state(session_id).preset_id == "full"  # type: ignore[union-attr]

        assert service.apply_command(
            session_id,
            MeshEditCommand("morph_delete_preset", params={"preset_id": "full"}),
        ).ok
        preset_state = service.cached_morph_state(session_id)
        assert preset_state is not None
        assert preset_state.preset_id == ""
        assert preset_state.available_presets == ()

        history_before_delete = service.history_usage(session_id)["undo_count"]
        deleted = service.apply_command(
            session_id,
            MeshEditCommand("morph_delete_profile", params={"profile_id": "resident-body"}),
        )
        deleted_state = service.cached_morph_state(session_id)
        assert deleted.ok
        assert deleted.native_preview_vertex_update_groups
        assert deleted_state is not None
        assert deleted_state.profile_id == ""
        assert deleted_state.definitions == ()
        assert deleted_state.available_profiles == ()
        assert tuple(service.working_mesh(session_id, clone=True).submeshes[0].vertices) == baseline
        assert service.history_usage(session_id)["undo_count"] == history_before_delete
        assert not profile_path.exists()
    finally:
        service.close_edit_session(session_id)

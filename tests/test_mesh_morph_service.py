from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection, mesh_topology_fingerprint
from cdmw.services import mesh_service_morph
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


def test_morph_runtime_state_capture_is_absent_without_initializing_native_morph(tmp_path) -> None:
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    session_id = service.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    try:
        with patch(
            "cdmw.services.mesh_service_morph.create_native_mesh_editor_morph_runtime_snapshot",
            side_effect=AssertionError("unused Morph & Refit sessions must not open native runtime"),
        ):
            captured = service.capture_morph_session_state(session_id)
        assert captured.present is False
        assert captured.native_snapshot is None
        assert captured.cache is None
        assert captured.retained_bytes == 0
        assert service.install_morph_session_state(session_id, captured) is None
        assert session_id not in service._morph_sessions
    finally:
        service.close_edit_session(session_id)


def test_morph_runtime_state_transfers_unsaved_profile_refit_without_recomposition(tmp_path) -> None:
    mesh = _driver_garment_mesh()
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    source_session_id = service.open_edit_session(mesh, mode="edit").session_id
    target_session_id = ""
    captured = None
    try:
        assert service.apply_command(source_session_id, _author_command()).ok
        assert service.set_refit_driver(source_session_id, (0, 1))[0].ok
        assert service.bind_refit(source_session_id, (2,))[0].ok
        assert service.configure_refit(
            source_session_id,
            (2,),
            enabled=True,
            intensity_percent=125.0,
            mode="rigid",
            clearance_percent=1.0,
        )[0].ok
        assert service.set_morph_value(
            source_session_id,
            "volume",
            75.0,
            phase="end",
            change_id="state-transfer",
        )[0].ok

        deformed = service.working_mesh(source_session_id, clone=True)
        source_cache = service._morph_sessions[source_session_id]
        captured = service.capture_morph_session_state(source_session_id)
        captured_cache = captured.cache
        snapshot_path = Path(str(captured.native_snapshot["path"]))  # type: ignore[index]

        assert captured.present is True
        assert captured.retained_bytes > 0
        assert snapshot_path.is_file()
        assert captured_cache is not source_cache
        assert captured_cache.profile is not source_cache.profile  # type: ignore[union-attr]
        assert captured_cache.known_profiles is not source_cache.known_profiles  # type: ignore[union-attr]
        assert captured_cache.topology_mesh is not source_cache.topology_mesh  # type: ignore[union-attr]
        assert not (tmp_path / "mesh_slider_profiles" / "definitions" / "resident-body.json").exists()

        target_session_id = service.open_edit_session(deformed, mode="edit").session_id
        before_install = service.working_mesh(target_session_id, clone=True)
        installed = service.install_morph_session_state(target_session_id, captured)
        after_install = service.working_mesh(target_session_id, clone=True)
        target_cache = service._morph_sessions[target_session_id]

        assert installed is not None
        assert installed.session_id == target_session_id
        assert installed.profile_id == "resident-body"
        assert installed.values == (("volume", 75.0),)
        assert installed.refit.driver_submesh_indices == (0, 1)
        assert installed.refit.garment_submesh_indices == (2,)
        assert installed.refit.garment_settings[0].intensity_percent == pytest.approx(125.0)
        assert installed.refit.garment_settings[0].mode == "rigid"
        assert installed.refit.garment_settings[0].clearance_percent == pytest.approx(1.0)
        assert tuple(submesh.vertices for submesh in after_install.submeshes) == tuple(
            submesh.vertices for submesh in before_install.submeshes
        )
        assert target_cache is not captured_cache
        assert target_cache.profile is not captured_cache.profile  # type: ignore[union-attr]
        assert target_cache.known_profiles is not captured_cache.known_profiles  # type: ignore[union-attr]
        assert target_cache.topology_mesh is not captured_cache.topology_mesh  # type: ignore[union-attr]

        changed, changed_state = service.set_morph_value(
            target_session_id,
            "volume",
            50.0,
            phase="end",
            change_id="state-transfer-target",
        )
        assert changed.ok
        assert changed_state.values == (("volume", 50.0),)
        changed_mesh = service.working_mesh(target_session_id, clone=True)
        assert changed_mesh.submeshes[0].vertices[0][2] == pytest.approx(
            after_install.submeshes[0].vertices[0][2] - 0.25
        )
    finally:
        if target_session_id:
            service.close_edit_session(target_session_id)
        service.close_edit_session(source_session_id)
        if captured is not None:
            snapshot_path = Path(str(captured.native_snapshot["path"]))  # type: ignore[index]
            service.dispose_morph_session_state(captured)
            assert captured.native_snapshot is None
            assert captured.retained_bytes == 0
            assert not snapshot_path.exists()


def test_morph_runtime_state_capture_disposes_native_snapshot_when_cache_clone_fails(tmp_path) -> None:
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    session_id = service.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    try:
        assert service.apply_command(session_id, _author_command()).ok
        from cdmw.services import mesh_service_morph

        real_dispose = mesh_service_morph.dispose_native_mesh_editor_morph_runtime_snapshot
        with (
            patch(
                "cdmw.services.mesh_service_morph._clone_mesh_for_service_native_snapshot",
                side_effect=RuntimeError("injected topology clone failure"),
            ),
            patch(
                "cdmw.services.mesh_service_morph.dispose_native_mesh_editor_morph_runtime_snapshot",
                wraps=real_dispose,
            ) as dispose,
            pytest.raises(RuntimeError, match="injected topology clone failure"),
        ):
            service.capture_morph_session_state(session_id)

        assert dispose.call_count == 1
        disposed_snapshot = dispose.call_args.args[0]
        assert not Path(str(disposed_snapshot["path"])).exists()
    finally:
        service.close_edit_session(session_id)


def test_morph_authoring_expands_selected_parts_inside_service_boundary(tmp_path) -> None:
    mesh = _driver_garment_mesh()
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    view = service.open_edit_session(mesh, mode="edit")
    try:
        result = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "morph_author_definition",
                selection=MeshEditSelection.from_maps(source_indices=(2,)),
                params={
                    "profile_id": "part-profile",
                    "profile_name": "Part Profile",
                    "definition_id": "volume",
                    "label": "Volume",
                },
            ),
        )
        state = service.cached_morph_state(view.session_id)
    finally:
        service.close_edit_session(view.session_id)

    assert result.ok
    assert state is not None
    assert {(item.submesh_index, item.vertex_index) for item in state.definitions[0].vertices} == {
        (2, vertex_index) for vertex_index in range(len(mesh.submeshes[2].vertices))
    }


def test_morph_authoring_expands_face_and_edge_selection_to_vertices(tmp_path) -> None:
    mesh = _driver_garment_mesh()
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    session_id = service.open_edit_session(mesh, mode="edit").session_id
    try:
        result = service.apply_command(
            session_id,
            MeshEditCommand(
                "morph_author_definition",
                selection=MeshEditSelection.from_maps(
                    edges_by_submesh={2: ((0, 1),)},
                    faces_by_submesh={2: (0,)},
                ),
                params={
                    "profile_id": "region-profile",
                    "profile_name": "Region Profile",
                    "definition_id": "region",
                    "label": "Region",
                    "feather": 0,
                },
            ),
        )
        state = service.cached_morph_state(session_id)
    finally:
        service.close_edit_session(session_id)

    assert result.ok
    assert state is not None
    expected = {int(vertex) for vertex in mesh.submeshes[2].faces[0][:3]} | {0, 1}
    assert {item.vertex_index for item in state.definitions[0].vertices} == expected


def test_unsaved_active_morph_profile_can_be_deleted(tmp_path) -> None:
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    session_id = service.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    profile_path = tmp_path / "mesh_slider_profiles" / "definitions" / "resident-body.json"
    try:
        assert service.apply_command(session_id, _author_command()).ok
        assert not profile_path.exists()
        deleted = service.apply_command(
            session_id,
            MeshEditCommand("morph_delete_profile", params={"profile_id": "resident-body"}),
        )
        state = service.cached_morph_state(session_id)
    finally:
        service.close_edit_session(session_id)

    assert deleted.ok
    assert state is not None
    assert state.profile_id == ""
    assert state.available_profiles == ()


def test_refit_rejects_a_part_used_as_both_driver_and_garment(tmp_path) -> None:
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    view = service.open_edit_session(_driver_garment_mesh(), mode="edit")
    try:
        assert service.apply_command(view.session_id, _author_command()).ok
        assert service.set_refit_driver(view.session_id, (0,))[0].ok
        with pytest.raises(ValueError, match="cannot also be refit driver"):
            service.bind_refit(view.session_id, (0,))
    finally:
        service.close_edit_session(view.session_id)


def test_refit_garment_settings_are_validated_and_preserved_in_service_state(tmp_path) -> None:
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    session_id = service.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    try:
        assert service.apply_command(session_id, _author_command()).ok
        assert service.set_refit_driver(session_id, (0, 1))[0].ok
        assert service.bind_refit(session_id, (2,))[0].ok
        result = service.apply_command(
            session_id,
            MeshEditCommand(
                "morph_configure_refit",
                selection=MeshEditSelection.from_maps(source_indices=(2,)),
                params={
                    "enabled": True,
                    "intensity_percent": 65.0,
                    "mode": "rigid",
                    "clearance_percent": 0.75,
                },
            ),
        )
        state = service.cached_morph_state(session_id)
        with pytest.raises(ValueError, match="bound garment"):
            service.configure_refit(
                session_id,
                (3,),
                enabled=True,
                intensity_percent=100.0,
                mode="surface",
                clearance_percent=0.0,
            )
    finally:
        service.close_edit_session(session_id)

    assert result.ok
    assert state is not None
    assert len(state.refit.garment_settings) == 1
    settings = state.refit.garment_settings[0]
    assert settings.submesh_index == 2
    assert settings.enabled is True
    assert settings.intensity_percent == pytest.approx(65.0)
    assert settings.mode == "rigid"
    assert settings.clearance_percent == pytest.approx(0.75)


def test_refit_and_following_slider_share_a_bounded_budget_and_reject_failed_output(tmp_path) -> None:
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    session_id = service.open_edit_session(_driver_garment_mesh(), mode="edit").session_id
    try:
        assert service.apply_command(session_id, _author_command()).ok
        assert service.set_refit_driver(session_id, (0, 1))[0].ok
        assert service.bind_refit(session_id, (2,))[0].ok
        with patch.object(
            mesh_service_morph, "native_mesh_editor_session_command",
            wraps=mesh_service_morph.native_mesh_editor_session_command,
        ) as native_command:
            assert service.configure_refit(
                session_id, (2,), enabled=True, intensity_percent=100.0,
                mode="surface", clearance_percent=0.1,
            )[0].ok
            assert service.set_morph_value(session_id, "volume", 25.0, phase="end", change_id="refit-budget")[0].ok
        mutation_calls = [call for call in native_command.call_args_list
                          if call.args[0] in {"morph_configure_refit", "morph_change"}]
        assert {call.args[0] for call in mutation_calls} == {"morph_configure_refit", "morph_change"}
        assert all(call.kwargs["timeout_seconds"] == 90.0 for call in mutation_calls)

        before_mesh = service.working_mesh(session_id, clone=True)
        before_view = service.session_view(session_id)
        before_state = service.cached_morph_state(session_id)
        before_revision = service._session(session_id).morph_session_revision
        with patch.object(mesh_service_morph, "native_mesh_editor_session_command", return_value=None):
            with pytest.raises(RuntimeError, match="morph_configure_refit failed"):
                service.configure_refit(
                    session_id, (2,), enabled=True, intensity_percent=100.0,
                    mode="surface", clearance_percent=0.2,
                )
        assert service.session_view(session_id) == before_view
        assert service.cached_morph_state(session_id) == before_state
        assert service._session(session_id).morph_session_revision == before_revision
        after_mesh = service.working_mesh(session_id, clone=True)
        assert [part.vertices for part in after_mesh.submeshes] == [part.vertices for part in before_mesh.submeshes]
    finally:
        service.close_edit_session(session_id, force_without_saving=True)


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


def test_preset_and_active_profile_delete_are_reversible_history_transactions(tmp_path) -> None:
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
        assert service.history_usage(session_id)["undo_count"] == history_before_delete + 1
        assert not profile_path.exists()

        assert service.undo(session_id).ok
        restored_state = service.cached_morph_state(session_id)
        assert restored_state is not None
        assert restored_state.profile_id == "resident-body"
        assert profile_path.is_file()
        assert tuple(service.working_mesh(session_id, clone=True).submeshes[0].vertices) != baseline

        assert service.redo(session_id).ok
        redone_state = service.cached_morph_state(session_id)
        assert redone_state is not None
        assert redone_state.profile_id == ""
        assert not profile_path.exists()
        assert tuple(service.working_mesh(session_id, clone=True).submeshes[0].vertices) == baseline
    finally:
        service.close_edit_session(session_id)

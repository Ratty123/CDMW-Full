from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.domain.mesh import MeshEditSelection, MeshObjectTransformState
from cdmw.services import mesh_service as mesh_service_module
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_service_history import (
    _history_snapshot_retained_bytes,
    _mesh_morph_profile_directory_state,
    _mesh_morph_profile_state_fingerprint,
    _restore_mesh_morph_profile_directory_state,
)
from cdmw.services.mesh_service_state import (
    _MeshGeometryLayer,
    _MeshMorphSessionState,
)
from tests.test_mesh_service_editing import _quad_mesh


class _Settings:
    def __init__(self, path: Path) -> None:
        self._path = path

    def fileName(self) -> str:
        return str(self._path)


def _history_marker_for_current_mesh(service: MeshService, session_id: str):
    session = service._session(session_id)
    marker = mesh_service_module._snapshot(session)
    marker.morph_session_state = _MeshMorphSessionState(present=False)
    marker.history_action = "rust_edit_session"
    marker.history_label = "Rust Edit Session"
    return marker


def test_failed_profile_restore_rolls_back_full_mesh_session_checkpoint(tmp_path) -> None:
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    view = service.open_edit_session(
        _quad_mesh(),
        session_id="atomic-profile-history",
        mode="object",
    )
    session = service._session(view.session_id)
    profile_root = tmp_path / "mesh_slider_profiles"
    profile_path = profile_root / "definitions" / "profile.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_bytes(b'{"name":"Before Rust"}')
    original_layer = _MeshGeometryLayer(
        "base",
        "Before Rust",
        (0,),
        visible=True,
        base=True,
    )
    session.geometry_layers = (original_layer,)
    session.active_geometry_layer_id = "base"
    session.geometry_layer_copy_counter = 2
    session.output_policy = "read_only"
    session.output_destination = "before-rust.pac"
    session.output_destination_ready = False
    session.object_transform = MeshObjectTransformState(location=(1.0, 2.0, 3.0))
    marker = _history_marker_for_current_mesh(service, view.session_id)
    marker.geometry_layers = session.geometry_layers
    marker.active_geometry_layer_id = session.active_geometry_layer_id
    marker.geometry_layer_copy_counter = session.geometry_layer_copy_counter
    marker.restore_geometry_layer_state = True
    marker.output_policy = session.output_policy
    marker.output_destination = session.output_destination
    marker.output_destination_ready = session.output_destination_ready
    marker.object_transform = session.object_transform
    marker.morph_profile_root = str(profile_root)
    marker.morph_profile_root_existed = True
    marker.morph_profile_files = (
        ("definitions/profile.json", b'{"name":"Before Rust"}'),
    )

    current_mesh = _quad_mesh()
    current_mesh.submeshes[0].vertices[0] = (0.75, 0.0, 0.0)
    current_layer = _MeshGeometryLayer(
        "base",
        "Rust Result",
        (0,),
        visible=False,
        base=True,
    )
    current_selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 2)})
    current_transform = MeshObjectTransformState(
        location=(4.0, 5.0, 6.0),
        rotation_degrees=(10.0, 20.0, 30.0),
        scale=(1.5, 1.5, 1.5),
    )
    session.working_mesh = current_mesh
    session.mode = "edit"
    session.selection = current_selection
    session.edit_operations = ("rust-edit",)
    session.object_transform = current_transform
    session.geometry_layers = (current_layer,)
    session.active_geometry_layer_id = "base"
    session.geometry_layer_copy_counter = 9
    session.output_policy = "free_edit_rebuild"
    session.output_destination = "rust-result"
    session.output_destination_ready = True
    session.revision = 7
    session.selection_revision = 8
    session.geometry_layer_revision = 11
    session.morph_session_revision = 13
    session.material_generation = 17
    session.native_editor_selection_signature = ("rust-current",)
    session.native_history_undo_count = 2
    session.native_history_redo_count = 3
    session.native_history_retained_bytes = 4096
    profile_path.write_bytes(b'{"name":"Rust Result"}')
    marker.morph_profile_expected_fingerprint = _mesh_morph_profile_state_fingerprint(
        True,
        (("definitions/profile.json", b'{"name":"Rust Result"}'),),
    )
    marker.retained_bytes = _history_snapshot_retained_bytes(marker)
    session.undo_stack.append(marker)

    expected_scalars = (
        session.revision,
        session.selection_revision,
        session.geometry_layer_revision,
        session.morph_session_revision,
        session.material_generation,
        session.native_editor_selection_signature,
        session.native_history_undo_count,
        session.native_history_redo_count,
        session.native_history_retained_bytes,
    )
    real_restore_session_state = mesh_service_module._restore_history_session_state

    def fail_after_target_profile_publication(restored_session, restored_snapshot) -> None:
        real_restore_session_state(restored_session, restored_snapshot)
        if restored_snapshot is marker:
            raise RuntimeError("injected profile restore failure")

    try:
        with (
            patch.object(
                mesh_service_module,
                "_restore_history_session_state",
                side_effect=fail_after_target_profile_publication,
            ),
            pytest.raises(RuntimeError, match="injected profile restore failure"),
        ):
            service.undo(view.session_id)

        restored = service._session(view.session_id)
        assert restored.working_mesh.submeshes[0].vertices[0] == (0.75, 0.0, 0.0)
        assert restored.mode == "edit"
        assert restored.selection == current_selection
        assert restored.edit_operations == ("rust-edit",)
        assert restored.object_transform == current_transform
        assert restored.geometry_layers == (current_layer,)
        assert restored.geometry_layer_copy_counter == 9
        assert restored.output_policy == "free_edit_rebuild"
        assert restored.output_destination == "rust-result"
        assert restored.output_destination_ready is True
        assert profile_path.read_bytes() == b'{"name":"Rust Result"}'
        assert (
            restored.revision,
            restored.selection_revision,
            restored.geometry_layer_revision,
            restored.morph_session_revision,
            restored.material_generation,
            restored.native_editor_selection_signature,
            restored.native_history_undo_count,
            restored.native_history_redo_count,
            restored.native_history_retained_bytes,
        ) == expected_scalars
        assert restored.undo_stack == [marker]
        assert restored.redo_stack == []
    finally:
        service.close_edit_session(view.session_id, force_without_saving=True)


def test_consumed_morph_cleanup_runs_after_reciprocal_and_revision_publication() -> None:
    service = MeshService()
    view = service.open_edit_session(
        _quad_mesh(),
        session_id="published-history-cleanup",
        mode="edit",
    )
    session = service._session(view.session_id)
    marker = _history_marker_for_current_mesh(service, view.session_id)
    current_mesh = _quad_mesh()
    current_mesh.submeshes[0].vertices[0] = (0.5, 0.0, 0.0)
    session.working_mesh = current_mesh
    session.revision = 4
    marker.retained_bytes = _history_snapshot_retained_bytes(marker)
    session.undo_stack.append(marker)
    real_dispose = mesh_service_module._dispose_history_snapshot
    publication_at_cleanup: tuple[int, int, int] | None = None

    def fail_consumed_cleanup(snapshot) -> None:
        nonlocal publication_at_cleanup
        if snapshot is marker:
            publication_at_cleanup = (
                session.revision,
                len(session.undo_stack),
                len(session.redo_stack),
            )
            raise RuntimeError("injected consumed Morph cleanup failure")
        real_dispose(snapshot)

    try:
        with patch.object(
            mesh_service_module,
            "_dispose_history_snapshot",
            side_effect=fail_consumed_cleanup,
        ):
            undone = service.undo(view.session_id)

        assert undone.ok
        assert undone.revision == 5
        assert undone.metrics["history_snapshot_cleanup_deferred"] == 1.0
        assert publication_at_cleanup == (5, 0, 1)
        assert service._session(view.session_id).redo_stack
        assert service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0] == (
            0.0,
            0.0,
            0.0,
        )

        redone = service.redo(view.session_id)
        assert redone.ok
        assert redone.revision == 6
        assert service._session(view.session_id).undo_stack
        assert service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0] == (
            0.5,
            0.0,
            0.0,
        )
    finally:
        # The injected failure deliberately prevented the native snapshot part
        # of the consumed marker from being released by the production helper.
        real_dispose(marker)
        service.close_edit_session(view.session_id, force_without_saving=True)


def test_failed_speculative_history_trims_never_dispose_live_snapshots() -> None:
    service = MeshService(max_history=1, max_history_bytes=1024 * 1024)
    view = service.open_edit_session(
        _quad_mesh(),
        session_id="speculative-history-trim",
        mode="edit",
    )
    session = service._session(view.session_id)
    existing = mesh_service_module._snapshot(session)
    reciprocal = mesh_service_module._snapshot(session)
    existing.retained_bytes = _history_snapshot_retained_bytes(existing)
    reciprocal.retained_bytes = _history_snapshot_retained_bytes(reciprocal)
    session.undo_stack.append(existing)
    real_retained = mesh_service_module._history_stack_retained_bytes
    retained_calls = 0
    disposed_ids: set[int] = set()
    real_dispose = mesh_service_module._dispose_history_snapshot

    def fail_after_each_speculative_pop(stack) -> int:
        nonlocal retained_calls
        retained_calls += 1
        if retained_calls in {3, 6}:
            raise RuntimeError("injected speculative history sizing failure")
        return real_retained(stack)

    def record_dispose(snapshot) -> None:
        disposed_ids.add(id(snapshot))
        real_dispose(snapshot)

    try:
        with (
            patch(
                "cdmw.services.mesh_service_history._history_stack_retained_bytes",
                side_effect=fail_after_each_speculative_pop,
            ),
            patch.object(
                mesh_service_module,
                "_dispose_history_snapshot",
                side_effect=record_dispose,
            ),
        ):
            cleanup_ok = service._publish_history_reciprocal_locked(
                session,
                reciprocal,
                target="redo",
                metrics={},
            )

        assert cleanup_ok is False
        assert session.undo_stack == [existing]
        assert session.redo_stack == [reciprocal]
        assert disposed_ids.isdisjoint(
            id(snapshot) for snapshot in (*session.undo_stack, *session.redo_stack)
        )
    finally:
        service.close_edit_session(view.session_id, force_without_saving=True)


def test_profile_history_rejects_oversized_file_before_reading_it(
    tmp_path: Path,
) -> None:
    profile_root = tmp_path / "mesh_slider_profiles"
    profile_path = profile_root / "definitions" / "oversized.json"
    profile_path.parent.mkdir(parents=True)
    with profile_path.open("wb") as stream:
        stream.truncate((8 * 1024 * 1024) + 1)

    with pytest.raises(RuntimeError, match="exceeds the 8 MiB limit"):
        _mesh_morph_profile_directory_state(profile_root)


def test_failed_history_rollback_poisons_cas_tokens() -> None:
    service = MeshService()
    view = service.open_edit_session(
        _quad_mesh(),
        session_id="failed-history-rollback-cas",
        mode="edit",
    )
    session = service._session(view.session_id)
    marker = _history_marker_for_current_mesh(service, view.session_id)
    marker.retained_bytes = _history_snapshot_retained_bytes(marker)
    session.undo_stack.append(marker)
    before = (
        session.revision,
        session.selection_revision,
        session.geometry_layer_revision,
        session.morph_session_revision,
        session.material_generation,
    )

    try:
        with (
            patch.object(
                mesh_service_module,
                "_restore_snapshot",
                side_effect=[
                    RuntimeError("injected target restore failure"),
                    RuntimeError("injected rollback restore failure"),
                ],
            ),
            pytest.raises(RuntimeError, match="atomic rollback could not be completed"),
        ):
            service.undo(view.session_id)

        after = (
            session.revision,
            session.selection_revision,
            session.geometry_layer_revision,
            session.morph_session_revision,
            session.material_generation,
        )
        assert all(current > previous for current, previous in zip(after, before))
        assert session.undo_stack == [marker]
        assert session.native_history_undo_count == 0
        assert session.native_history_redo_count == 0
    finally:
        service.close_edit_session(view.session_id, force_without_saving=True)


def test_profile_history_staging_race_restores_original_tree(
    tmp_path: Path,
) -> None:
    profile_root = tmp_path / "mesh_slider_profiles"
    profile_path = profile_root / "definitions" / "profile.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_bytes(b'{"name":"Current"}')
    expected = _mesh_morph_profile_directory_state(profile_root)[2]
    real_replace = os.replace

    def race_staging_replace(raw_source, raw_destination) -> None:
        source = Path(raw_source)
        if ".history-stage-" in source.name:
            (source / "definitions" / "profile.json").write_bytes(
                b'{"name":"Raced"}'
            )
        real_replace(raw_source, raw_destination)

    with (
        patch(
            "cdmw.services.mesh_service_history.os.replace",
            side_effect=race_staging_replace,
        ),
        pytest.raises(RuntimeError, match="publication validation failed"),
    ):
        _restore_mesh_morph_profile_directory_state(
            profile_root,
            existed=True,
            files=(("definitions/profile.json", b'{"name":"Target"}'),),
            expected_fingerprint=expected,
        )

    assert profile_path.read_bytes() == b'{"name":"Current"}'


def test_profile_history_rejects_linked_root_without_touching_target(
    tmp_path: Path,
) -> None:
    external_parent = tmp_path / "external"
    external_root = external_parent / "mesh_slider_profiles"
    external_file = external_root / "definitions" / "profile.json"
    external_file.parent.mkdir(parents=True)
    external_file.write_bytes(b'{"name":"External"}')
    lexical_root = tmp_path / "owned" / "mesh_slider_profiles"
    lexical_root.parent.mkdir()
    try:
        lexical_root.symlink_to(external_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory links are unavailable: {exc}")

    with pytest.raises(RuntimeError, match="does not accept symbolic links"):
        _restore_mesh_morph_profile_directory_state(
            lexical_root,
            existed=True,
            files=(("definitions/profile.json", b'{"name":"Target"}'),),
            expected_fingerprint=_mesh_morph_profile_state_fingerprint(
                True,
                (("definitions/profile.json", b'{"name":"External"}'),),
            ),
        )

    assert external_file.read_bytes() == b'{"name":"External"}'

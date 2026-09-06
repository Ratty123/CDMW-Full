from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.domain.mesh import MeshObjectTransformState
from cdmw.services import mesh_service as mesh_service_module
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_service_state import (
    _MeshGeometryLayer,
    _MeshMorphSessionState,
)
from tests.test_mesh_service_editing import _quad_mesh


class MeshServicePreparedReplacementTests(unittest.TestCase):
    def test_preparation_is_inert_until_atomic_commit(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="prepared-replacement", mode="edit")
        imported = _quad_mesh()
        imported.submeshes[0].vertices[0] = (0.5, 0.0, 0.0)

        prepared = service.prepare_working_mesh_replacement(view.session_id, imported)

        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual(
            (0.0, 0.0, 0.0),
            service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0],
        )
        committed = service.commit_prepared_working_mesh_replacement(prepared)
        self.assertEqual(1, committed.revision)
        self.assertEqual(1, committed.undo_count)
        self.assertEqual(
            (0.5, 0.0, 0.0),
            service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0],
        )

    def test_stale_revision_is_rejected_without_mutation(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="stale-prepared-replacement", mode="edit")
        stale_import = _quad_mesh()
        stale_import.submeshes[0].vertices[0] = (0.5, 0.0, 0.0)
        prepared = service.prepare_working_mesh_replacement(view.session_id, stale_import)
        newer_import = _quad_mesh()
        newer_import.submeshes[0].vertices[0] = (0.75, 0.0, 0.0)
        service.replace_working_mesh(view.session_id, newer_import)

        with self.assertRaisesRegex(RuntimeError, "Prepared mesh replacement is stale"):
            service.commit_prepared_working_mesh_replacement(prepared)

        self.assertEqual(1, service.session_view(view.session_id).revision)
        self.assertEqual(
            (0.75, 0.0, 0.0),
            service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0],
        )

    def test_stale_geometry_layer_revision_is_rejected_under_commit_lock(self) -> None:
        service = MeshService()
        view = service.open_edit_session(
            _quad_mesh(two_parts=True),
            session_id="stale-layer-prepared-replacement",
            mode="edit",
        )
        session = service._session(view.session_id)
        session.geometry_layers = (
            _MeshGeometryLayer("base", "Base mesh", (0,), visible=True, base=True),
            _MeshGeometryLayer("detail", "Detail", (1,), visible=True),
        )
        expected_layer_revision = session.geometry_layer_revision
        imported = _quad_mesh(two_parts=True)
        imported.submeshes[0].vertices[0] = (0.5, 0.0, 0.0)
        prepared = service.prepare_working_mesh_replacement(view.session_id, imported)

        service.rename_geometry_layer(view.session_id, "detail", "Authoritative Detail")

        with self.assertRaisesRegex(
            RuntimeError,
            "geometry layers are stale",
        ):
            service.commit_prepared_working_mesh_replacement(
                prepared,
                geometry_layers=(
                    _MeshGeometryLayer("base", "Base mesh", (0,), visible=True, base=True),
                    _MeshGeometryLayer("detail", "Detail", (1,), visible=True),
                ),
                expected_geometry_layer_revision=expected_layer_revision,
            )

        current = service._session(view.session_id)
        self.assertEqual(0, current.revision)
        self.assertEqual(0, len(current.undo_stack))
        self.assertEqual(
            ("Base mesh", "Authoritative Detail"),
            tuple(layer.name for layer in current.geometry_layers),
        )
        self.assertEqual(
            (0.0, 0.0, 0.0),
            current.working_mesh.submeshes[0].vertices[0],
        )

    def test_stale_morph_revision_is_rejected_under_commit_lock(self) -> None:
        service = MeshService()
        view = service.open_edit_session(
            _quad_mesh(),
            session_id="stale-morph-prepared-replacement",
            mode="edit",
        )
        imported = _quad_mesh()
        imported.submeshes[0].vertices[0] = (0.5, 0.0, 0.0)
        prepared = service.prepare_working_mesh_replacement(view.session_id, imported)
        service._session(view.session_id).morph_session_revision = 1

        with self.assertRaisesRegex(RuntimeError, "Morph & Refit state is stale"):
            service.commit_prepared_working_mesh_replacement(
                prepared,
                expected_morph_session_revision=0,
                morph_session_state=_MeshMorphSessionState(present=False),
            )

        current = service.session_view(view.session_id)
        self.assertEqual(0, current.revision)
        self.assertEqual(0, current.undo_count)
        self.assertEqual(
            (0.0, 0.0, 0.0),
            service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0],
        )

    def test_reversible_commit_rejects_candidate_that_cannot_fit_redo_history(self) -> None:
        service = MeshService(max_history_bytes=1024 * 1024)
        view = service.open_edit_session(
            _quad_mesh(),
            session_id="candidate-history-budget",
            mode="edit",
        )
        imported = _quad_mesh()
        imported.submeshes[0].vertices.extend(
            (float(index), float(index % 7), 0.0) for index in range(10_000)
        )
        prepared = service.prepare_working_mesh_replacement(view.session_id, imported)
        before_snapshot = mesh_service_module._snapshot(
            service._session(view.session_id),
            prefer_native=True,
        )
        try:
            before_bytes = mesh_service_module._history_snapshot_retained_bytes(
                before_snapshot
            )
        finally:
            mesh_service_module._dispose_history_snapshot(before_snapshot)
        service.max_history_bytes = before_bytes + 4096

        with self.assertRaisesRegex(RuntimeError, "result cannot fit"):
            service.commit_prepared_working_mesh_replacement(
                prepared,
                require_reversible_history=True,
            )

        current = service.session_view(view.session_id)
        self.assertEqual(0, current.revision)
        self.assertEqual(0, current.undo_count)
        self.assertEqual(4, current.vertex_count)

    def test_preparation_carries_export_blocker_without_mutation(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="blocked-prepared-replacement", mode="edit")
        imported = _quad_mesh()
        imported.submeshes[0].vertices[0] = (0.5, 0.0, 0.0)
        prepared = service.prepare_working_mesh_replacement(view.session_id, imported)
        blocked = replace(
            prepared,
            validation_report=SimpleNamespace(
                blockers=(SimpleNamespace(message="invalid export"),),
                warnings=(),
                ok=False,
            ),
        )

        self.assertEqual("invalid export", blocked.validation_report.blockers[0].message)
        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual(
            (0.0, 0.0, 0.0),
            service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0],
        )

    def test_unexpected_publish_exception_rolls_back_session_and_history(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="rollback-prepared-replacement", mode="edit")
        imported = _quad_mesh()
        imported.submeshes[0].vertices[0] = (0.5, 0.0, 0.0)
        prepared = service.prepare_working_mesh_replacement(view.session_id, imported)

        def fail_after_partial_publish(session, candidate) -> None:
            session.working_mesh = candidate.working_mesh
            raise RuntimeError("injected publish failure")

        with patch(
            "cdmw.services.mesh_service_replacement._publish_prepared_replacement",
            side_effect=fail_after_partial_publish,
        ):
            with self.assertRaisesRegex(RuntimeError, "injected publish failure"):
                service.commit_prepared_working_mesh_replacement(prepared)

        self.assertEqual(0, service.session_view(view.session_id).revision)
        self.assertEqual(0, service.session_view(view.session_id).undo_count)
        self.assertEqual(
            (0.0, 0.0, 0.0),
            service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0],
        )

    def test_commit_prunes_dead_native_history_and_keeps_rust_undo_usable(self) -> None:
        service = MeshService()
        view = service.open_edit_session(
            _quad_mesh(),
            session_id="prune-native-history-replacement",
            mode="edit",
        )
        session = service._session(view.session_id)
        dead_native_marker = mesh_service_module._snapshot(
            session,
            prefer_native=False,
        )
        dead_native_marker.native_editor_history = True
        dead_native_marker.history_action = "native_edit"
        dead_native_marker.history_label = "Dead Native Edit"
        dead_native_marker.retained_bytes = (
            mesh_service_module._history_snapshot_retained_bytes(
                dead_native_marker
            )
        )
        session.undo_stack.append(dead_native_marker)
        imported = _quad_mesh()
        imported.submeshes[0].vertices[0] = (0.5, 0.0, 0.0)
        prepared = service.prepare_working_mesh_replacement(
            view.session_id,
            imported,
        )

        committed = service.commit_prepared_working_mesh_replacement(
            prepared,
            history_action="rust_edit_session",
            history_label="Edit Session",
            require_reversible_history=True,
        )

        self.assertEqual(1, committed.undo_count)
        self.assertFalse(
            any(snapshot.native_editor_history for snapshot in session.undo_stack)
        )
        self.assertEqual("Edit Session", session.undo_stack[-1].history_label)
        self.assertTrue(service.undo(view.session_id).ok)
        self.assertEqual(
            (0.0, 0.0, 0.0),
            service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0],
        )
        self.assertTrue(service.redo(view.session_id).ok)
        self.assertEqual(
            (0.5, 0.0, 0.0),
            service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0],
        )

    def test_publish_failure_rolls_back_even_when_rollback_native_close_throws(self) -> None:
        service = MeshService()
        view = service.open_edit_session(
            _quad_mesh(),
            session_id="rollback-close-failure-replacement",
            mode="edit",
        )
        session = service._session(view.session_id)
        surviving_marker = mesh_service_module._snapshot(
            session,
            prefer_native=False,
        )
        surviving_marker.history_action = "prior_edit"
        surviving_marker.history_label = "Prior Edit"
        surviving_marker.retained_bytes = (
            mesh_service_module._history_snapshot_retained_bytes(surviving_marker)
        )
        dead_native_marker = mesh_service_module._snapshot(
            session,
            prefer_native=False,
        )
        dead_native_marker.native_editor_history = True
        dead_native_marker.history_action = "native_edit"
        dead_native_marker.history_label = "Dead Native Edit"
        dead_native_marker.retained_bytes = (
            mesh_service_module._history_snapshot_retained_bytes(
                dead_native_marker
            )
        )
        session.undo_stack[:] = [surviving_marker, dead_native_marker]
        previous_selection = session.selection
        previous_transform = session.object_transform
        previous_sidecar_warnings = session.sidecar_warnings
        previous_edit_operations = session.edit_operations
        previous_requires_edit_operations = session.requires_edit_operations
        imported = _quad_mesh()
        imported.submeshes[0].vertices[0] = (0.5, 0.0, 0.0)
        prepared = service.prepare_working_mesh_replacement(
            view.session_id,
            imported,
        )

        def fail_after_full_geometry_publish(session, candidate) -> None:
            session.working_mesh = candidate.working_mesh
            session.selection = candidate.selection
            session.object_transform = MeshObjectTransformState(
                location=(9.0, 8.0, 7.0)
            )
            session.sidecar_warnings = candidate.sidecar_warnings
            session.edit_operations = candidate.edit_operations
            session.requires_edit_operations = candidate.requires_edit_operations
            session.revision += 1
            raise RuntimeError("injected publish failure")

        with (
            patch(
                "cdmw.services.mesh_service_replacement._publish_prepared_replacement",
                side_effect=fail_after_full_geometry_publish,
            ),
            patch(
                "cdmw.services.mesh_service._close_native_editor_session",
                side_effect=[None, RuntimeError("injected rollback close failure")],
            ) as close_native,
        ):
            with self.assertRaisesRegex(RuntimeError, "injected publish failure"):
                service.commit_prepared_working_mesh_replacement(prepared)

        self.assertEqual(2, close_native.call_count)
        self.assertGreater(session.revision, 0)
        self.assertGreater(session.geometry_layer_revision, 0)
        self.assertGreater(session.morph_session_revision, 0)
        self.assertIs(previous_selection, session.selection)
        self.assertEqual(previous_transform, session.object_transform)
        self.assertEqual(previous_sidecar_warnings, session.sidecar_warnings)
        self.assertEqual(previous_edit_operations, session.edit_operations)
        self.assertEqual(
            previous_requires_edit_operations,
            session.requires_edit_operations,
        )
        self.assertEqual([surviving_marker], session.undo_stack)
        self.assertEqual([], session.redo_stack)
        self.assertIn(
            "injected rollback close failure",
            session.mesh_layer_autosave_error,
        )
        self.assertEqual(
            (0.0, 0.0, 0.0),
            service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0],
        )

    def test_morph_runtime_install_failure_restores_authoritative_state(self) -> None:
        service = MeshService()
        view = service.open_edit_session(
            _quad_mesh(),
            session_id="morph-rollback-prepared-replacement",
            mode="edit",
        )
        imported = _quad_mesh()
        imported.submeshes[0].vertices[0] = (0.5, 0.0, 0.0)
        prepared = service.prepare_working_mesh_replacement(view.session_id, imported)
        incoming = _MeshMorphSessionState(present=False)
        previous = _MeshMorphSessionState(present=False)

        with (
            patch.object(
                service,
                "_capture_morph_session_state_locked",
                return_value=previous,
            ),
            patch.object(
                service,
                "_install_morph_session_state_locked",
                side_effect=[RuntimeError("injected morph install failure"), None],
            ) as install,
            self.assertRaisesRegex(RuntimeError, "injected morph install failure"),
        ):
            service.commit_prepared_working_mesh_replacement(
                prepared,
                morph_session_state=incoming,
            )

        self.assertEqual(2, install.call_count)
        self.assertIs(incoming, install.call_args_list[0].args[1])
        self.assertIs(previous, install.call_args_list[1].args[1])
        current = service.session_view(view.session_id)
        self.assertEqual(0, current.revision)
        self.assertEqual(0, current.undo_count)
        self.assertEqual(0, current.redo_count)
        self.assertEqual(
            (0.0, 0.0, 0.0),
            service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0],
        )

    def test_rust_session_metadata_is_published_with_the_same_atomic_rollback(self) -> None:
        service = MeshService()
        view = service.open_edit_session(_quad_mesh(), session_id="rust-state-replacement", mode="edit")
        imported = _quad_mesh()
        imported.submeshes[0].vertices[0] = (0.5, 0.0, 0.0)
        prepared = service.prepare_working_mesh_replacement(view.session_id, imported)
        layer = _MeshGeometryLayer("rust-layer", "Layer", (0,), visible=True)
        original_session = service._session(view.session_id)
        original_session.output_destination = "original-" + ("o" * 2048) + ".pac"
        original_layers = original_session.geometry_layers
        original_active_layer = original_session.active_geometry_layer_id
        original_copy_counter = original_session.geometry_layer_copy_counter
        original_policy = original_session.output_policy
        original_destination = original_session.output_destination
        original_destination_ready = original_session.output_destination_ready
        rust_destination = "candidate-" + ("x" * 2048) + ".pac"
        original_transform = original_session.object_transform
        rust_transform = MeshObjectTransformState(
            location=(1.0, 2.0, 3.0),
            rotation_degrees=(4.0, 5.0, 6.0),
            scale=(1.25, 1.25, 1.25),
            pivot=(0.5, 0.5, 0.0),
        )

        with self.assertRaises(TypeError):
            service.commit_prepared_working_mesh_replacement(
                prepared,
                history_action="rust_edit_session",
                history_label="Edit Session",
                geometry_layers=(layer,),
                geometry_layer_copy_counter=object(),
                output_policy="free_edit",
                output_destination=rust_destination,
                output_destination_ready=True,
            )

        session = service._session(view.session_id)
        self.assertEqual(0, session.revision)
        self.assertEqual(original_policy, session.output_policy)
        self.assertNotEqual((layer,), session.geometry_layers)
        self.assertEqual(
            (0.0, 0.0, 0.0),
            service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0],
        )

        committed = service.commit_prepared_working_mesh_replacement(
            prepared,
            history_action="rust_edit_session",
            history_label="Edit Session",
            geometry_layers=(layer,),
            active_geometry_layer_id="rust-layer",
            geometry_layer_copy_counter=3,
            object_transform=rust_transform,
            output_policy="free_edit",
            output_destination=rust_destination,
            output_destination_ready=True,
        )

        self.assertEqual(1, committed.revision)
        session = service._session(view.session_id)
        self.assertEqual((layer,), session.geometry_layers)
        self.assertEqual("rust-layer", session.active_geometry_layer_id)
        self.assertEqual(3, session.geometry_layer_copy_counter)
        self.assertEqual("free_edit", session.output_policy)
        self.assertEqual(rust_destination, session.output_destination)
        self.assertTrue(session.output_destination_ready)
        self.assertEqual(rust_transform, session.object_transform)
        self.assertEqual("Edit Session", committed.history_entries[-1].label)

        rust_marker = session.undo_stack[-1]
        marker_without_destination = replace(
            rust_marker,
            output_destination=None,
            retained_bytes=0,
        )
        self.assertGreater(
            rust_marker.retained_bytes,
            mesh_service_module._history_snapshot_retained_bytes(marker_without_destination),
        )

        service.undo(view.session_id)
        session = service._session(view.session_id)
        self.assertEqual(original_layers, session.geometry_layers)
        self.assertEqual(original_active_layer, session.active_geometry_layer_id)
        self.assertEqual(original_copy_counter, session.geometry_layer_copy_counter)
        self.assertEqual(original_policy, session.output_policy)
        self.assertEqual(original_destination, session.output_destination)
        self.assertEqual(original_destination_ready, session.output_destination_ready)
        self.assertEqual(original_transform, session.object_transform)
        self.assertEqual(
            (0.0, 0.0, 0.0),
            service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0],
        )

        service.redo(view.session_id)
        session = service._session(view.session_id)
        self.assertEqual((layer,), session.geometry_layers)
        self.assertEqual("rust-layer", session.active_geometry_layer_id)
        self.assertEqual(3, session.geometry_layer_copy_counter)
        self.assertEqual("free_edit", session.output_policy)
        self.assertEqual(rust_destination, session.output_destination)
        self.assertTrue(session.output_destination_ready)
        self.assertEqual(rust_transform, session.object_transform)
        self.assertEqual(
            (0.5, 0.0, 0.0),
            service.working_mesh(view.session_id, clone=False).submeshes[0].vertices[0],
        )
        self.assertEqual("Edit Session", service.session_view(view.session_id).history_entries[-1].label)


if __name__ == "__main__":
    unittest.main()

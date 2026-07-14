from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.services.mesh_service import MeshService
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


if __name__ == "__main__":
    unittest.main()

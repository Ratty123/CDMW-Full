"""A dead resident session must not kill the editor with it.

One refused native apply used to leave `native_editor_mesh_dirty` true with
`native_editor_session_ready` false, and nothing could ever clear that pair:
`_sync_native_editor_session_to_working_mesh` returned False on sight of it, so
every read of the working mesh raised, and `_apply_native_editor_session_geometry_action`
refused on the same condition, so no later apply could reopen the session
either. Reading the working mesh is what the Parts list, the preview, Move,
Clear Selection and Finish Edit Mesh all do, so a single failure took the whole
session down and kept it down.
"""

import unittest

from cdmw.services.mesh_service import _sync_native_editor_session_to_working_mesh
from cdmw.services.mesh_service_state import _MeshEditSession


def _session_with_dead_native_editor(vertices: int = 6, faces: int = 2) -> _MeshEditSession:
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

    submesh = SubMesh(
        name="part",
        vertices=[(float(i), 0.0, 0.0) for i in range(vertices)],
        normals=[(0.0, 0.0, 1.0)] * vertices,
        uvs=[(0.0, 0.0)] * vertices,
        faces=[(0, 1, 2)] * faces,
    )
    mesh = ParsedMesh(path="test.pac", format="pac", submeshes=[submesh])
    session = _MeshEditSession(session_id="s1", base_mesh=mesh, working_mesh=mesh)
    # The state a refused apply leaves behind: the resident side is gone, and
    # the totals were moved ahead of the real geometry by the dirty counts.
    session.native_editor_mesh_dirty = True
    session.native_editor_mesh_dirty_counts = ((999, 999),)
    session.native_editor_session_ready = False
    session.working_mesh.total_vertices = 999
    session.working_mesh.total_faces = 999
    return session


class NativeEditorSessionRecoveryTests(unittest.TestCase):
    def test_a_dead_session_no_longer_fails_the_sync_forever(self) -> None:
        session = _session_with_dead_native_editor()
        self.assertTrue(
            _sync_native_editor_session_to_working_mesh(session),
            "the sync still refuses a session it can never repair",
        )
        self.assertFalse(session.native_editor_mesh_dirty)
        self.assertEqual(session.native_editor_mesh_dirty_counts, ())

    def test_recovery_puts_the_totals_back_in_agreement_with_the_geometry(self) -> None:
        """Only the totals were moved ahead; recomputing them is the whole repair."""

        session = _session_with_dead_native_editor(vertices=6)
        _sync_native_editor_session_to_working_mesh(session)
        real_vertices = sum(len(part.vertices or ()) for part in session.working_mesh.submeshes)
        self.assertEqual(session.working_mesh.total_vertices, real_vertices)
        self.assertNotEqual(session.working_mesh.total_vertices, 999)

    def test_the_loss_is_counted_rather_than_hidden(self) -> None:
        session = _session_with_dead_native_editor()
        self.assertEqual(session.native_editor_lost_recoveries, 0)
        _sync_native_editor_session_to_working_mesh(session)
        self.assertEqual(session.native_editor_lost_recoveries, 1)

    def test_a_clean_session_is_left_alone(self) -> None:
        session = _session_with_dead_native_editor()
        session.native_editor_mesh_dirty = False
        self.assertTrue(_sync_native_editor_session_to_working_mesh(session))
        self.assertEqual(session.native_editor_lost_recoveries, 0)

    def test_recovery_clears_the_stroke_and_selection_signatures(self) -> None:
        """A stroke id surviving the session it belonged to reuses dead state."""

        session = _session_with_dead_native_editor()
        session.native_editor_active_stroke_id = "7"
        session.native_editor_selection_signature = ("stale",)
        _sync_native_editor_session_to_working_mesh(session)
        self.assertEqual(session.native_editor_active_stroke_id, "")
        self.assertEqual(session.native_editor_selection_signature, ())

    def test_recovery_is_repeatable(self) -> None:
        """A session can die more than once in a sitting."""

        session = _session_with_dead_native_editor()
        _sync_native_editor_session_to_working_mesh(session)
        session.native_editor_mesh_dirty = True
        session.native_editor_session_ready = False
        self.assertTrue(_sync_native_editor_session_to_working_mesh(session))
        self.assertEqual(session.native_editor_lost_recoveries, 2)


if __name__ == "__main__":
    unittest.main()

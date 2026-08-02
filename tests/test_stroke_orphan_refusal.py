"""A stroke whose session died under it must not be carried on regardless.

When a native apply fails, the session is abandoned back to its last exported
state and reopened. The renderer knows nothing about that and keeps sending the
rest of the stroke, so the next `update` arrives at a session that never saw a
`begin`. The C++ guard rejects it -- "mesh editor stroke phase requires matching
active stroke" -- and that rejection abandons the session again.

The result was a run of identical refusals in which only the first described the
actual fault and every later one described the recovery. Ten failures, one
cause. This refuses an orphaned continuation locally and names it, so the log
keeps one line per real failure.

It deliberately does not restart the stroke: reinterpreting an orphaned `update`
as a fresh `begin` would hide the lifecycle defect and write history for a
stroke the reader never made.
"""

import unittest

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_service import _apply_native_editor_session_geometry_action
from cdmw.services.mesh_service_state import _MeshEditSession
from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection


def _session(*, lost: int, active_stroke: str) -> _MeshEditSession:
    submesh = SubMesh(
        name="part",
        vertices=[(0.0, 0.0, 0.0)] * 3,
        normals=[(0.0, 0.0, 1.0)] * 3,
        uvs=[(0.0, 0.0)] * 3,
        faces=[(0, 1, 2)],
    )
    mesh = ParsedMesh(path="t.pac", format="pac", submeshes=[submesh])
    session = _MeshEditSession(session_id="s1", base_mesh=mesh, working_mesh=mesh)
    session.native_editor_lost_recoveries = lost
    session.native_editor_active_stroke_id = active_stroke
    session.native_editor_session_ready = True
    return session


def _command(phase: str, stroke_id: str) -> MeshEditCommand:
    return MeshEditCommand(
        action="transform",
        selection=MeshEditSelection(),
        params={"stroke_phase": phase, "stroke_id": stroke_id},
        mode="edit",
    )


class StrokeOrphanRefusalTests(unittest.TestCase):
    def test_an_orphaned_update_is_refused_and_named(self) -> None:
        session = _session(lost=1, active_stroke="")
        result = _apply_native_editor_session_geometry_action(
            session, _command("update", "3"), MeshEditSelection()
        )
        self.assertIsNone(result)
        self.assertIn("stroke_orphaned_by_session_loss", session.native_editor_last_refusal)
        self.assertIn("stroke_id='3'", session.native_editor_last_refusal)

    def test_an_orphaned_end_is_refused_too(self) -> None:
        session = _session(lost=2, active_stroke="")
        self.assertIsNone(
            _apply_native_editor_session_geometry_action(
                session, _command("end", "3"), MeshEditSelection()
            )
        )
        self.assertIn("stroke_orphaned_by_session_loss", session.native_editor_last_refusal)

    def test_a_stroke_matching_the_live_session_is_not_refused_here(self) -> None:
        """A recovered session that owns this stroke must still be editable."""

        session = _session(lost=1, active_stroke="3")
        session.native_editor_last_refusal = ""
        _apply_native_editor_session_geometry_action(
            session, _command("update", "3"), MeshEditSelection()
        )
        self.assertNotIn("stroke_orphaned_by_session_loss", session.native_editor_last_refusal)

    def test_a_session_that_never_lost_anything_is_not_refused_here(self) -> None:
        """Without a recovery there is no orphan; the guard must not fire."""

        session = _session(lost=0, active_stroke="")
        session.native_editor_last_refusal = ""
        _apply_native_editor_session_geometry_action(
            session, _command("update", "3"), MeshEditSelection()
        )
        self.assertNotIn("stroke_orphaned_by_session_loss", session.native_editor_last_refusal)

    def test_a_begin_is_never_treated_as_an_orphan(self) -> None:
        """A new stroke after a recovery is exactly how editing resumes."""

        session = _session(lost=1, active_stroke="")
        session.native_editor_last_refusal = ""
        _apply_native_editor_session_geometry_action(
            session, _command("begin", "4"), MeshEditSelection()
        )
        self.assertNotIn("stroke_orphaned_by_session_loss", session.native_editor_last_refusal)


if __name__ == "__main__":
    unittest.main()

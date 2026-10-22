from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from cdmw.services.mesh_rust_authoring import (
    RUST_MESH_CANDIDATE,
    RustMeshAuthoringSession,
    RustMeshProtocolError,
)
from tests import test_mesh_rust_authoring as fixtures


def _reference(session, request_id, updates):
    mesh = session.shadow_service.working_mesh(session.shadow_session_id, clone=False)
    parts = [dict(vertex_indices=[], positions=[], normals=[], uvs=[], indices=[])
             for _ in mesh.submeshes]
    parts[0].update(updates)
    data = json.dumps(dict(schema=RUST_MESH_CANDIDATE, session_id=session.session_id,
                          submeshes=parts, selection={})).encode()
    name = f"candidate-{request_id}-sparse.json"
    (session.root / name).write_bytes(data)
    return dict(path=name, data_type="mesh_candidate_json", count=len(parts),
                byte_length=len(data), sha256=hashlib.sha256(data).hexdigest(),
                content_type="application/json")


class RustSculptUpdateTests(unittest.TestCase):
    def test_sparse_strokes_undo_redo_and_return_to_original_position(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, session = fixtures.RustMeshAuthoringTests()._create(Path(temporary) / "session")
            try:
                service, sid = session.shadow_service, session.shadow_session_id
                before = service.working_mesh(sid, clone=True)
                original = before.submeshes[0].vertices[0]
                changed = (original[0] + .25, original[1], original[2])
                request = fixtures._request(session, "transaction_request", 1)
                request.update(label="Grab", candidate=_reference(session, 1, dict(vertex_indices=[0], positions=[changed])))
                state = session.apply_candidate(request)
                after = service.working_mesh(sid, clone=True)
                self.assertEqual(1, state["undo_count"])
                self.assertEqual(changed, after.submeshes[0].vertices[0])
                self.assertEqual(before.submeshes[0].vertices[1:], after.submeshes[0].vertices[1:])
                self.assertEqual(before.submeshes[0].uvs, after.submeshes[0].uvs)
                for command, expected in [("undo", original), ("redo", changed)]:
                    req = fixtures._request(session, "command_request", 2 if command == "undo" else 3)
                    req.update(command=command, arguments={})
                    session.run_command(req)
                    self.assertEqual(expected, service.working_mesh(sid, clone=False).submeshes[0].vertices[0])
                # A later stroke can restore a vertex to its loaded position;
                # updates are relative to the last committed gesture, not the initial document.
                request = fixtures._request(session, "transaction_request", 4)
                request.update(label="Bend", candidate=_reference(session, 4, dict(vertex_indices=[0], positions=[original])))
                session.apply_candidate(request)
                self.assertEqual(original, service.working_mesh(sid, clone=False).submeshes[0].vertices[0])
                self.assertEqual(2, service.session_view(sid).undo_count)
            finally:
                session.cancel()

    def test_invalid_sparse_updates_leave_geometry_and_history_unchanged(self):
        invalid = [
            dict(vertex_indices=[0, 0], positions=[[.5, 0, 0]] * 2),
            dict(vertex_indices=[1, 0], positions=[[.5, 0, 0]] * 2),
            dict(vertex_indices=[10**9], positions=[[.5, 0, 0]]),
            dict(vertex_indices=[True], positions=[[.5, 0, 0]]),
            dict(vertex_indices=[0], positions=[]),
            dict(vertex_indices=[0], positions=[[float("nan"), 0, 0]]),
            dict(vertex_indices=[0], positions=[[.5, 0, 0]], indices=[0, 1, 2]),
            dict(vertex_indices=[0], positions=[[.5, 0, 0]], normals=[[0, 1, 0]] * 2),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            _, session = fixtures.RustMeshAuthoringTests()._create(Path(temporary) / "session")
            try:
                sid, service = session.shadow_session_id, session.shadow_service
                before = service.working_mesh(sid, clone=True)
                for request_id, updates in enumerate(invalid, 1):
                    with self.subTest(updates=updates):
                        request = fixtures._request(session, "transaction_request", request_id)
                        request["candidate"] = _reference(session, request_id, updates)
                        with self.assertRaises(RustMeshProtocolError):
                            session.apply_candidate(request)
                        self.assertEqual(before.submeshes[0].vertices, service.working_mesh(sid, clone=False).submeshes[0].vertices)
                        self.assertEqual(0, service.session_view(sid).undo_count)
                        self.assertFalse((session.root / request["candidate"]["path"]).exists())
            finally:
                session.cancel()

    def test_sparse_channels_preserve_source_precision_and_other_parts(self):
        first = SimpleNamespace(vertices=[(1 / 3, 0., 0.), (2., 0., 0.)], normals=[(0., 1., 0.)] * 2, uvs=[])
        second = SimpleNamespace(vertices=[(3., 0., 0.)], normals=[(0., 0., 1.)], uvs=[])
        raw = [dict(vertex_indices=[0], positions=[[0.33333334, .5, 0.]], normals=[[0., 0., 1.]], indices=[]),
               dict(vertex_indices=[], positions=[], normals=[], indices=[])]
        operations = []
        changed, parts, _ = RustMeshAuthoringSession._apply_candidate_geometry(
            None, SimpleNamespace(submeshes=[first, second]), raw, operations, 0)
        self.assertTrue(changed)
        self.assertEqual({0}, parts)
        self.assertEqual((1 / 3, .5, 0.), first.vertices[0])
        self.assertEqual((2., 0., 0.), first.vertices[1])
        self.assertEqual([(3., 0., 0.)], second.vertices)
        self.assertEqual([(0., 0., 1.)], second.normals)
        self.assertEqual([2, 2], [item["vertex_count"] for item in operations])

    def test_stale_sparse_revision_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, session = fixtures.RustMeshAuthoringTests()._create(Path(temporary) / "session")
            try:
                request = fixtures._request(session, "transaction_request", 1)
                request["candidate"] = _reference(session, 1, dict(vertex_indices=[0], positions=[[.5, 0, 0]]))
                request["base_revision"] += 1
                with self.assertRaises(RustMeshProtocolError):
                    session.apply_candidate(request)
                self.assertEqual(0, session.shadow_service.session_view(session.shadow_session_id).undo_count)
            finally:
                session.cancel()

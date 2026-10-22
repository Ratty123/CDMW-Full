from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cdmw.domain.mesh import MeshEditSelection
from cdmw.domain.mesh import skeleton as skinning
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.services import mesh_island_authoring, mesh_rust_authoring, mesh_rust_rig
from cdmw.services.mesh_rust_state_cache import RustMeshStateCache
from cdmw.services.mesh_service_state import _MeshGeometryLayer
from tests import test_mesh_rust_authoring as fixtures


def _rig():
    return Skeleton(path="owned-cache-rig.pab", bone_count=8, bones=[
        Bone(index=100 + index, name=f"Bone {index}", name_hash=0xA1000000 + index, parent_index=-1)
        for index in range(8)
    ])


class RustMeshDerivedStateTests(unittest.TestCase):
    def _create(self, root):
        return fixtures.RustMeshAuthoringTests()._create(root, skeleton=_rig())

    def _command(self, session, command, arguments, request_id=1):
        request = fixtures._request(session, "command_request", request_id)
        request.update(command=command, arguments=arguments)
        return session.run_command(request)["state"]

    def test_selection_labels_and_active_bone_reuse_static_inspector_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, session = self._create(Path(temporary) / "session")
            try:
                shadow = session.shadow_service._session(session.shadow_session_id)
                shadow.geometry_layers = (*shadow.geometry_layers, _MeshGeometryLayer("detail", "Detail", ()))
                with (
                    patch.object(mesh_rust_authoring, "_rust_skin_weight_capability",
                                 wraps=mesh_rust_authoring._rust_skin_weight_capability) as capability,
                    patch.object(skinning, "_part_summary", wraps=skinning._part_summary) as part_summary,
                    patch.object(mesh_rust_rig, "selected_bone_influence",
                                 wraps=mesh_rust_rig.selected_bone_influence) as influence,
                ):
                    self._command(session, "select", {"selection": {
                        "source_indices": [0], "vertices_by_submesh": {"0": [0]},
                    }})
                    first = self._command(session, "rig_select_bone", {"bone_index": 107}, 2)
                    self._command(session, "layer_rename", {"layer_id": "detail", "name": "Display name"}, 3)
                    second = session.state_payload(include_document=False)
                    self.assertEqual(0, capability.call_count)
                    self.assertEqual(0, part_summary.call_count)
                    self.assertEqual(1, influence.call_count)
                    self.assertEqual(107, second["skeleton"]["selected_bone_index"])
                    self.assertEqual(first["rig_influence"], second["rig_influence"])
                    self.assertEqual(1, len(second["skeleton"]["selected_vertex_weights"]))
                # A response does not expose the cached influence rows for mutation.
                second["rig_influence"]["parts"][0]["weights"][0][1] = 123.0
                self.assertEqual(first["rig_influence"], session.state_payload(include_document=False)["rig_influence"])
            finally:
                session.cancel()

    def test_unknown_weight_revision_revalidates_current_rows_but_reuses_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, session = self._create(Path(temporary) / "session")
            try:
                shadow = session.shadow_service._session(session.shadow_session_id)
                self._command(session, "rig_select_bone", {"bone_index": 107})
                original_parts = set(map(id, shadow.base_mesh.submeshes))
                with shadow.export_lock:
                    shadow.working_mesh.submeshes[0].bone_weights[0] = (float("nan"), 0.0)
                    shadow.revision += 1
                with (
                    patch.object(mesh_rust_authoring, "resolve_pac_bone_palette",
                                 wraps=mesh_rust_authoring.resolve_pac_bone_palette) as palette,
                    patch.object(mesh_rust_authoring, "_safe_pac_skin_rows",
                                 wraps=mesh_rust_authoring._safe_pac_skin_rows) as rows,
                ):
                    state = session.state_payload(include_document=False)
                    self.assertEqual(0, palette.call_count)
                    self.assertTrue(rows.call_count)
                    self.assertFalse(any(id(call.args[0]) in original_parts for call in rows.call_args_list))
                    self.assertGreater(state["skeleton"]["invalid_row_count"], 0)
                    expected = mesh_rust_authoring._rust_skin_weight_capability(shadow)
                    self.assertEqual(expected.payload(), state["skeleton"]["weight_edit_capability"])
            finally:
                session.cancel()

    def test_policy_and_attached_rig_changes_invalidate_capability(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, session = self._create(root / "session")
            try:
                free = self._command(session, "configure_output_policy", {
                    "policy": "free_edit_rebuild", "destination": str(root / "output"),
                })
                self.assertFalse(free["skeleton"]["weight_edit_capability"]["enabled"])
                self.assertIn("Exact Game Asset", free["skeleton"]["weight_edit_capability"]["reason"])
                changed = _rig()
                changed.bones[0].name = "New attached bone"
                session.shadow_service.attach_skeleton(session.shadow_session_id, changed)
                state = session.state_payload(include_document=False)
                self.assertEqual("New attached bone", state["skeleton"]["bones"][0]["name"])
            finally:
                session.cancel()

    def test_island_cache_invalidates_positions_but_not_selection_or_weights(self):
        part = SimpleNamespace(name="Seam", vertices=[
            (0., 0., 0.), (1., 0., 0.), (0., 1., 0.),
            (1., 0., 0.), (1., 1., 0.), (0., 1., 0.),
        ], faces=[(0, 1, 2), (3, 4, 5)])
        mesh = SimpleNamespace(submeshes=[part], lod_levels=[])
        session = SimpleNamespace(session_id="owned", working_mesh=mesh, revision=0, mesh_format="pac",
                                  selection=MeshEditSelection(source_indices=(0,)),
                                  replacement_state=None, hair_state=None, output_policy="fixed",
                                  base_mesh=mesh, base_mesh_is_original_parse=True)
        service = SimpleNamespace(_session=lambda _: session, _morph_sessions={})
        authoring = SimpleNamespace(shadow_service=service, authoritative_service=service, authoritative_session_id="owned",
            shadow_session_id="owned", state_cache=RustMeshStateCache(), mesh_island_cache={},
            mesh_island_focus=(), _cancel_event=threading.Event())
        replacement = {"reason": "", "parts": [{"id": "0", "index": 0}]}
        with patch.object(mesh_island_authoring, "mesh_islands", wraps=mesh_island_authoring.mesh_islands) as discover:
            first = mesh_island_authoring.island_ui_state(authoring, replacement)
            self.assertEqual(1, len(first["parts"][0]["islands"]))
            session.revision += 1
            authoring.state_cache.transition(session, before_revision=0, change="none")
            mesh_island_authoring.island_ui_state(authoring, replacement)
            session.revision += 1
            authoring.state_cache.transition(session, before_revision=1, change="weights")
            mesh_island_authoring.island_ui_state(authoring, replacement)
            self.assertEqual(1, discover.call_count)
            for index in (3, 4, 5):
                x, y, z = part.vertices[index]
                part.vertices[index] = x + 10., y, z
            session.revision += 1
            moved = mesh_island_authoring.island_ui_state(authoring, replacement)
            self.assertEqual(2, discover.call_count)
            self.assertEqual(2, len(moved["parts"][0]["islands"]))
            # Active fitting addresses neutral islands, even if a live preview
            # separates a material seam. Leaving fitting restores live discovery.
            neutral = SimpleNamespace(submeshes=[SimpleNamespace(vertices=[
                (0., 0., 0.), (1., 0., 0.), (0., 1., 0.),
                (1., 0., 0.), (1., 1., 0.), (0., 1., 0.),
            ], faces=part.faces)])
            authoring.shadow_service._morph_sessions["owned"] = SimpleNamespace(topology_mesh=neutral)
            fitting = mesh_island_authoring.island_ui_state(authoring, replacement)
            self.assertEqual(1, len(fitting["parts"][0]["islands"]))
            authoring.shadow_service._morph_sessions.clear()
            self.assertEqual(2, len(mesh_island_authoring.island_ui_state(authoring, replacement)["parts"][0]["islands"]))

    def test_preflight_and_publication_share_exact_prepared_binary(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, session = self._create(Path(temporary) / "session")
            try:
                original_builder = mesh_rust_authoring.encode_mesh_document
                current = session.shadow_service.working_mesh(session.shadow_session_id, clone=False)
                with patch.object(mesh_rust_authoring, "encode_mesh_document", wraps=original_builder) as build:
                    session._preflight_mesh_document_capacity(current)
                    self.assertEqual(0, build.call_count)
                    request = fixtures._request(session, "transaction_request", 1)
                    request["candidate"] = fixtures._candidate_reference(session, request_id=1, first_x=0.5)
                    session.apply_candidate(request)
                    self.assertEqual(1, build.call_count)
                    reference = session._write_mesh_document("state-1-0123456789.bin")
                    self.assertEqual(1, build.call_count)
                    current = session.shadow_service.working_mesh(session.shadow_session_id, clone=False)
                    expected_bytes = original_builder(mesh_rust_authoring._mesh_document_arrays(current))
                    self.assertEqual(expected_bytes, (session.root / reference["path"]).read_bytes())
                    decoded = mesh_rust_authoring.read_owned_payload_reference(session.root, reference)
                    legacy = json.loads(mesh_rust_authoring._canonical_json_bytes(mesh_rust_authoring._mesh_document_payload(current)))
                    legacy["structural_fingerprint"] = decoded["structural_fingerprint"]
                    self.assertEqual(legacy, decoded)
                    self.assertEqual(len(expected_bytes), reference["byte_length"])
                session.cancel()
                self.assertIsNone(session.state_cache.document)
                self.assertIsNone(session.state_cache.observed_mesh)
            finally:
                session.cancel()

    def test_new_revision_cannot_reuse_previous_or_stale_preflight_document(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, session = self._create(Path(temporary) / "session")
            try:
                shadow = session.shadow_service._session(session.shadow_session_id)
                candidate = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
                prepared = session.shadow_service.prepare_working_mesh_replacement(session.shadow_session_id, candidate)
                session._preflight_mesh_document_capacity(prepared.working_mesh)
                with shadow.export_lock:
                    x, y, z = shadow.working_mesh.submeshes[0].vertices[0]
                    shadow.working_mesh.submeshes[0].vertices[0] = x + 0.125, y, z
                    shadow.revision += 1
                with self.assertRaisesRegex(RuntimeError, "stale"):
                    session.shadow_service.commit_prepared_working_mesh_replacement(prepared)
                original_builder = mesh_rust_authoring.encode_mesh_document
                with patch.object(mesh_rust_authoring, "encode_mesh_document", wraps=original_builder) as build:
                    reference = session._write_mesh_document("state-1-0123456789.bin")
                    self.assertEqual(1, build.call_count)
                actual = mesh_rust_authoring.read_owned_payload_reference(session.root, reference)
                expected_bytes = original_builder(mesh_rust_authoring._mesh_document_arrays(shadow.working_mesh))
                self.assertEqual(expected_bytes, (session.root / reference["path"]).read_bytes())
                self.assertEqual(mesh_rust_authoring.decode_mesh_document(expected_bytes), actual)
            finally:
                session.cancel()

    def test_cancelled_candidate_discards_only_its_unpublished_encoding(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, session = self._create(Path(temporary) / "session")
            try:
                recovery = session._write_mesh_document("state-0-0123456789.bin")
                request = fixtures._request(session, "transaction_request", 1)
                request["candidate"] = fixtures._candidate_reference(session, request_id=1, first_x=0.5)
                with (
                    patch.object(mesh_rust_authoring.RustMeshAuthoringSession,
                                 "_commit_morph_preserving_replacement",
                                 side_effect=mesh_rust_authoring.RustMeshCancellationError("cancelled")),
                    self.assertRaises(mesh_rust_authoring.RustMeshCancellationError),
                ):
                    session.apply_candidate(request)
                self.assertIsNone(session.state_cache.document)
                self.assertEqual(0, session.shadow_service.session_view(session.shadow_session_id).revision)
                mesh_rust_authoring.read_owned_payload_reference(session.root, recovery)
            finally:
                session.cancel()

    def test_prepared_document_requires_explicit_commit_admission_and_same_channels(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, session = self._create(Path(temporary) / "session")
            try:
                shadow = session.shadow_service._session(session.shadow_session_id)
                candidate = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
                prepared = session.shadow_service.prepare_working_mesh_replacement(session.shadow_session_id, candidate)
                session._preflight_mesh_document_capacity(prepared.working_mesh)
                session.shadow_service.commit_prepared_working_mesh_replacement(prepared)
                self.assertIsNone(session.state_cache.document_payload(shadow, shadow.working_mesh))
                prepared.working_mesh.submeshes[0].vertices = list(prepared.working_mesh.submeshes[0].vertices)
                session.state_cache.adopt_prepared_document(shadow, prepared)
                self.assertIsNone(session.state_cache.document)
            finally:
                session.cancel()

    def test_binary_publication_keeps_legacy_json_readable_and_prunes_owned_old_states(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, session = self._create(Path(temporary) / "session")
            try:
                mesh = session.shadow_service.working_mesh(session.shadow_session_id, clone=False)
                legacy_document = mesh_rust_authoring._mesh_document_payload(mesh)
                legacy = mesh_rust_authoring._atomic_write_payload(
                    session.root, "state-0-0123456789.json", legacy_document,
                    data_type="mesh_document_json", element_count=len(mesh.submeshes),
                    expected_root_identity=session.root_identity,
                )
                legacy_decoded = mesh_rust_authoring.read_owned_payload_reference(session.root, legacy)
                # The private publication helper accepts the old name template
                # while returning the explicit versioned binary reference.
                current = session._write_mesh_document("state-0-9876543210.json")
                binary_decoded = mesh_rust_authoring.read_owned_payload_reference(session.root, current)
                legacy_decoded["structural_fingerprint"] = binary_decoded["structural_fingerprint"]
                self.assertEqual(legacy_decoded, binary_decoded)
                self.assertEqual("mesh_document_binary_v1", current["data_type"])
                self.assertEqual("state-0-9876543210.bin", current["path"])
                self.assertFalse((session.root / legacy["path"]).exists())
                self.assertTrue((session.root / "document.bin").is_file())
            finally:
                session.cancel()

    def test_binary_owned_reference_rejects_wrong_hash_count_type_path_and_candidate_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, session = self._create(Path(temporary) / "session")
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                reference = manifest["document"]
                for updates in (
                    {"sha256": "0" * 64}, {"byte_length": reference["byte_length"] + 1},
                    {"count": reference["count"] + 1}, {"content_type": "application/json"},
                    {"data_type": "mesh_document_binary_v2"}, {"path": "channels.bin"},
                    {"path": "../document.bin"},
                ):
                    with self.subTest(updates=updates), self.assertRaises(mesh_rust_authoring.RustMeshProtocolError):
                        mesh_rust_authoring.read_owned_payload_reference(session.root, {**reference, **updates})
                with self.assertRaises(mesh_rust_authoring.RustMeshProtocolError):
                    mesh_rust_authoring.read_owned_payload_reference(session.root, reference, candidate_only=True)
            finally:
                session.cancel()

    def test_failed_direct_binary_preflight_discards_pending_candidate_and_keeps_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, session = self._create(Path(temporary) / "session")
            try:
                manifest = json.loads(session.manifest_path.read_text(encoding="utf-8"))
                candidate = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
                prepared = session.shadow_service.prepare_working_mesh_replacement(session.shadow_session_id, candidate)
                session._preflight_mesh_document_capacity(prepared.working_mesh)
                self.assertTrue(session.state_cache.document.pending)
                invalid = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
                invalid.submeshes[0].vertices[0] = (float("inf"), 0.0, 0.0)
                with self.assertRaisesRegex(mesh_rust_authoring.RustMeshProtocolError, "non-finite"):
                    session._preflight_mesh_document_capacity(invalid)
                self.assertIsNone(session.state_cache.document)
                mesh_rust_authoring.read_owned_payload_reference(session.root, manifest["document"])
            finally:
                session.cancel()

    def test_vertex_edit_reuses_its_exact_preflight_document_after_owned_commit(self):
        from cdmw.services.mesh_vertex_parameters import inspection_token

        with tempfile.TemporaryDirectory() as temporary:
            _, session = self._create(Path(temporary) / "session")
            try:
                self._command(session, "select", {"selection": {"vertices_by_submesh": {"0": [0]}}})
                request = fixtures._request(session, "command_request", 2)
                request.update(command="vertex_edit", arguments={
                    "token": inspection_token(session),
                    "edits": {"position": {"mode": "set", "values": [0.5, None, None]}},
                })
                with patch.object(mesh_rust_authoring, "encode_mesh_document",
                                  wraps=mesh_rust_authoring.encode_mesh_document) as encode:
                    result = session.run_command(request)
                    self.assertEqual(1, encode.call_count)
                self.assertEqual({"changed": True, "count": 1}, result["result"])
                reference = result["state"]["document"]
                decoded = mesh_rust_authoring.read_owned_payload_reference(session.root, reference)
                self.assertEqual(0.5, decoded["lods"][0]["submeshes"][0]["positions"][0][0])
                self.assertEqual(session.state_cache.document.data.data,
                                 (session.root / reference["path"]).read_bytes())
                self.assertFalse(session.state_cache.document.pending)
            finally:
                session.cancel()


if __name__ == "__main__":
    unittest.main()

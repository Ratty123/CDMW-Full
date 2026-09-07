"""Regressions for selection precision and resident authoring state updates."""
from __future__ import annotations

import hashlib
import json
import struct
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.modding.mesh_parser import parse_pac
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession, _mesh_document_payload
from cdmw.services.mesh_service import MeshService
from tests import test_mesh_rust_authoring as support
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from tests.test_mesh_service_editing import _quad_mesh


@contextmanager
def fractional_session(root):
    source = bytearray(_pac_fixture(skinned=True))
    parsed = parse_pac(bytes(source), "fractional.pac")
    struct.pack_into("<H", source, parsed.submeshes[0].source_vertex_offsets[0], 3276)
    with patch.object(support, "_pac_fixture", return_value=bytes(source)):
        _, session = support.RustMeshAuthoringTests()._create(root)
    try:
        yield session
    finally:
        session.cancel()


def command(session, name, arguments):
    request = support._request(session, "command_request", 1)
    request.update(command=name, arguments=arguments)
    return session.run_command(request)["state"]


def test_selection_roundtrip_preserves_fractional_pac_coordinates(tmp_path):
    with fractional_session(tmp_path / "session") as session:
        before = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
        request = support._request(session, "transaction_request", 1)
        # Actual serde_json f32 spelling from the review reproduction.
        request["candidate"] = support._candidate_reference(session, request_id=1, first_x=0.09997864)
        result = session.apply_candidate(request)
        after = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
        assert after.submeshes[0].vertices == before.submeshes[0].vertices
        assert result["selection"]["vertices_by_submesh"] == {"0": [0]}
        assert not session.shadow_service._session(session.shadow_session_id).edit_operations


def test_edit_preserves_untouched_components_and_vertices(tmp_path):
    with fractional_session(tmp_path / "session") as session:
        before = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
        original = before.submeshes[0].vertices[0][0]
        bits = struct.unpack("<I", struct.pack("<f", original))[0]
        next_float = struct.unpack("<f", struct.pack("<I", bits + 1))[0]
        request = support._request(session, "transaction_request", 1)
        reference = support._candidate_reference(session, request_id=1, first_x=0.09997864)
        path = session.root / reference["path"]
        payload = json.loads(path.read_bytes())
        # Change Y while leaving fractional X untouched in the same row.
        payload["submeshes"][0]["positions"][0][1] = next_float
        data = json.dumps(payload).encode()
        path.write_bytes(data)
        reference.update(byte_length=len(data), sha256=hashlib.sha256(data).hexdigest())
        request["candidate"] = reference
        session.apply_candidate(request)
        after = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
        assert after.submeshes[0].vertices[0] == (original, next_float, 0.0)
        assert after.submeshes[0].vertices[1:] == before.submeshes[0].vertices[1:]


def test_adjacent_f32_position_is_not_discarded_as_rounding(tmp_path):
    with fractional_session(tmp_path / "session") as session:
        before = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
        original = before.submeshes[0].vertices[0][0]
        bits = struct.unpack("<I", struct.pack("<f", original))[0]
        next_float = struct.unpack("<f", struct.pack("<I", bits + 1))[0]
        request = support._request(session, "transaction_request", 1)
        request["candidate"] = support._candidate_reference(session, request_id=1, first_x=next_float)
        session.apply_candidate(request)
        after = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
        assert after.submeshes[0].vertices[0][0] == next_float
        assert session.shadow_service._session(session.shadow_session_id).edit_operations


def test_restricted_lod_allows_selection_after_f32_roundtrip(tmp_path):
    mesh = _quad_mesh()
    mesh.submeshes[0].vertices[0] = (struct.unpack("<f", struct.pack("<f", 0.1))[0], 0.0, 0.0)
    mesh.active_lod_index = 1
    service = MeshService(settings=support._Settings(tmp_path / "settings.ini"))
    view = service.open_edit_session(mesh, session_id="restricted", mode="edit")
    session = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=service, active_session_id=view.session_id),
        tmp_path / "session", process_generation=1,
    )
    try:
        request = support._request(session, "transaction_request", 1)
        request["candidate"] = support._candidate_reference(session, request_id=1, first_x=0.1)
        result = session.apply_candidate(request)
        assert result["selection"]["vertices_by_submesh"] == {"0": [0]}
        assert not session.shadow_service._session(session.shadow_session_id).edit_operations
    finally:
        session.cancel()


def test_selection_bone_and_layer_commands_do_not_republish_geometry(tmp_path):
    skeleton = Skeleton(path="review.pab", bones=[Bone(index=i, name=f"Bone {i}") for i in range(8)], bone_count=8)
    _, session = support.RustMeshAuthoringTests()._create(tmp_path / "session", skeleton=skeleton)
    try:
        def state_only(name, arguments):
            before = _mesh_document_payload(session.shadow_service.working_mesh(session.shadow_session_id, clone=True))
            with patch.object(RustMeshAuthoringSession, "_write_mesh_document", side_effect=AssertionError("state-only command rewrote geometry")):
                result = command(session, name, arguments)
            after = _mesh_document_payload(session.shadow_service.working_mesh(session.shadow_session_id, clone=True))
            assert before == after
            assert "document" not in result
            return result

        selection = {"source_indices": [0]}
        state_only("select", {"selection": selection, "operation": "replace"})
        state_only("rig_select_bone", {"bone_index": 1})
        state_only("configure_output_policy", {"policy": "free_edit_rebuild", "destination": str(tmp_path / "output")})
        state_only("layer_copy", {"selection": selection, "target": "face"})
        pasted = command(session, "layer_paste", {})
        assert "document" in pasted
        active = pasted["geometry_layers"]["active_layer_id"]
        state_only("layer_rename", {"layer_id": active, "name": "Renamed"})
        state_only("layer_move", {"layer_id": active, "direction": -1})
        state_only("layer_visibility", {"layer_id": active, "visible": False})
        state_only("layer_visibility", {"layer_id": active, "visible": True})
        state_only("layer_activate", {"layer_id": active})
        assert "document" in command(session, "undo", {})
        assert "document" in command(session, "state", {})
    finally:
        session.cancel()


def test_parts_duplicate_delete_and_history_publish_the_changed_document(tmp_path):
    mesh = _quad_mesh(two_parts=True)
    service = MeshService(settings=support._Settings(tmp_path / "settings.ini"))
    view = service.open_edit_session(mesh, session_id="parts", mode="edit")
    session = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=service, active_session_id=view.session_id),
        tmp_path / "session", process_generation=1,
    )
    try:
        command(session, "configure_output_policy", {
            "policy": "free_edit_rebuild", "destination": str(tmp_path / "output"),
        })
        command(session, "select", {"selection": {"vertices_by_submesh": {"0": [0]}}})

        def published_parts(state):
            document = support.read_owned_payload_reference(session.root, state["document"])
            parts = document["lods"][0]["submeshes"]
            current = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
            assert parts == _mesh_document_payload(current)["lods"][0]["submeshes"]
            return parts

        # These are the complete part-only requests emitted by the painted buttons,
        # even when a previous viewport element selection remains in host state.
        duplicated = published_parts(command(session, "topology", {
            "action": "duplicate", "selection": {"source_indices": [1],
                "vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {}},
            "params": {}, "label": "Duplicate part",
        }))
        assert [part["material"] for part in duplicated] == ["mat_a", "mat_b", "mat_b"]
        assert duplicated[2]["positions"] == duplicated[1]["positions"]
        assert duplicated[2]["indices"] == duplicated[1]["indices"]
        deleted_state = command(session, "topology", {
            "action": "delete", "selection": {"source_indices": [0],
                "vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {}},
            "params": {"delete_parts": True}, "label": "Delete part",
        })
        deleted = published_parts(deleted_state)
        assert deleted == duplicated[1:]
        assert deleted_state["selection"]["source_indices"] == []
        assert published_parts(command(session, "undo", {})) == duplicated
        assert published_parts(command(session, "redo", {})) == deleted
        assert service.session_view(view.session_id).submesh_count == 2
    finally:
        session.cancel()

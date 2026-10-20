from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_parser import parse_pac
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.services.mesh_rust_authoring import (
    RustMeshAuthoringSession, RustMeshValidationError, read_owned_payload_reference,
)
from cdmw.services.mesh_service import MeshService, _attach_mesh_asset_status
from tests import test_mesh_rust_authoring as fixtures
from tests import test_mesh_rust_authoring_exact_output as exact_fixtures
from tests.test_mesh_pac_deleted_parts import _parts_pac


@pytest.mark.parametrize("skinned", [False, True])
def test_last_vertex_delete_retains_history_and_finishes_exact_export(tmp_path, skinned):
    authoritative, session = fixtures.RustMeshAuthoringTests()._create(
        tmp_path / "session", skinned_source=skinned
    )
    original = authoritative.working_mesh("authoritative-rust-test", clone=True)

    def command(request_id, name, arguments):
        request = fixtures._request(session, "command_request", request_id)
        request.update(command=name, arguments=arguments)
        return session.run_command(request)

    def delete(request_id, vertices):
        return command(request_id, "topology", {
            "action": "delete",
            "selection": {
                "vertices_by_submesh": {"0": vertices},
                "edges_by_submesh": {}, "faces_by_submesh": {}, "source_indices": [],
            },
            "params": {},
        })

    try:
        delete(1, [0])
        partial = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
        assert len(partial.submeshes[0].faces) == 1
        response = delete(2, list(range(len(partial.submeshes[0].vertices))))
        document = read_owned_payload_reference(session.root, response["state"]["document"])
        part = document["lods"][0]["submeshes"][0]
        assert part["positions"] == part["indices"] == []
        assert part["name"] == original.submeshes[0].name
        assert response["state"]["undo_count"] == 2
        assert not session.closed

        # Rebuilding is an output projection and never populates the live slot.
        revision = session.shadow_service.session_view(session.shadow_session_id).revision
        snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        rebuilt, report = session.shadow_service.rebuild_result_from_snapshot(snapshot)
        assert report.validation_status == "passed"
        assert report.topology_rebuild["deleted_submesh_indices"] == (0,)
        assert all(len(lod.submeshes[0].faces) == 1 for lod in pac_cloth_lods(rebuilt.data))
        assert not session.closed
        assert session.shadow_service.session_view(session.shadow_session_id).revision == revision
        report = session.shadow_service.validate_export(session.shadow_session_id)
        assert report.ok, report.blockers
        assert authoritative.session_view("authoritative-rust-test").revision == 0

        command(4, "undo", {})
        restored = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
        assert restored.submeshes[0].vertices == partial.submeshes[0].vertices
        assert restored.submeshes[0].faces == partial.submeshes[0].faces
        assert restored.submeshes[0].shader_masks == partial.submeshes[0].shader_masks
        assert restored.submeshes[0].bone_indices == partial.submeshes[0].bone_indices
        assert restored.submeshes[0].bone_weights == partial.submeshes[0].bone_weights
        command(5, "redo", {})
        assert not session.shadow_service.working_mesh(
            session.shadow_session_id, clone=False
        ).submeshes[0].vertices
        command(6, "undo", {})
        command(7, "undo", {})
        restored = session.shadow_service.working_mesh(session.shadow_session_id, clone=True)
        for actual, expected in zip(restored.submeshes, original.submeshes):
            assert actual.vertices == expected.vertices
            assert actual.faces == expected.faces
            assert actual.uvs == expected.uvs
            assert actual.normals == expected.normals
            assert actual.shader_masks == expected.shader_masks
            assert actual.bone_indices == expected.bone_indices
            assert actual.bone_weights == expected.bone_weights
            assert actual.source_vertex_offsets == expected.source_vertex_offsets
        assert authoritative.capture_export_snapshot("authoritative-rust-test").original_data == (
            session.shadow_service.capture_export_snapshot(session.shadow_session_id).original_data
        )
        command(8, "redo", {})
        command(9, "redo", {})
        finished = session.finish(fixtures._request(session, "finish_request", 10))
        assert finished["exact_output_validation"]["status"] == "passed"
        assert finished["exact_output_validation"]["fallback_used"] is False
        assert authoritative.session_view("authoritative-rust-test").revision == 1
        assert not authoritative.working_mesh("authoritative-rust-test").submeshes[0].vertices
        accepted = authoritative.capture_export_snapshot("authoritative-rust-test")
        assert authoritative.rebuild_result_from_snapshot(accepted)[0].data == rebuilt.data
        assert authoritative.undo("authoritative-rust-test").ok
        assert authoritative.working_mesh("authoritative-rust-test").submeshes[0].vertices == original.submeshes[0].vertices
        assert authoritative.redo("authoritative-rust-test").ok
        assert not authoritative.working_mesh("authoritative-rust-test").submeshes[0].vertices
    finally:
        session.cancel()
        authoritative.close_edit_session("authoritative-rust-test", force_without_saving=True)


@pytest.mark.parametrize("unsupported_bounds", [False, True])
def test_exact_finish_keeps_an_earlier_other_part_edit_and_refuses_unsafe_draws(tmp_path, unsupported_bounds):
    source = _parts_pac()
    if unsupported_bounds:
        raw = bytearray(source)
        descriptor = parse_pac(source, "parts.pac").submeshes[2].source_descriptor_offset
        struct.pack_into("<3f", raw, descriptor + 23, 1000, 1000, 1000)
        source = bytes(raw)
    mesh = parse_pac(source, "parts.pac")
    _attach_mesh_asset_status(mesh, source, run_roundtrip=True)
    assert mesh._cdmw_no_op_roundtrip_report["byte_identical"]
    service = MeshService()
    view = service.open_edit_session(mesh, session_id="exact-other-part", mode="edit")
    session = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=service, active_session_id=view.session_id),
        tmp_path / "session", process_generation=1,
    )
    try:
        request = fixtures._request(session, "transaction_request", 1)
        request["candidate"] = exact_fixtures._candidate_reference(session, request_id=1, first_x=.125)
        session.apply_candidate(request)
        request = fixtures._request(session, "command_request", 2)
        request.update(command="topology", arguments={"action": "delete", "params": {}, "selection": {
            "vertices_by_submesh": {"2": [0, 1, 2, 3]}, "edges_by_submesh": {},
            "faces_by_submesh": {}, "source_indices": [],
        }})
        session.run_command(request)
        finish = fixtures._request(session, "finish_request", 3)
        if unsupported_bounds:
            with pytest.raises(RustMeshValidationError, match="Exact game-asset writer rejected"):
                session.finish(finish)
            assert not session.closed
            assert service.session_view(view.session_id).revision == 0
            shadow = session.shadow_service.working_mesh(session.shadow_session_id)
            assert shadow.submeshes[0].vertices[0][0] == .125
            assert shadow.submeshes[2].vertices == []
            assert session.shadow_service.undo(session.shadow_session_id).ok
            assert session.shadow_service.working_mesh(session.shadow_session_id).submeshes[2].vertices == mesh.submeshes[2].vertices
            return
        finished = session.finish(finish)
        assert finished["exact_output_validation"]["status"] == "passed"
        output = tmp_path / "deleted.pac"
        report = service.rebuild_asset(view.session_id, output)
        assert report.validation_status == "passed"
        levels = pac_cloth_lods(output.read_bytes())
        assert levels[0].submeshes[0].vertices[0][0] == pytest.approx(.125, abs=2e-5)
        for before, after in zip(pac_cloth_lods(source)[1:], levels[1:], strict=True):
            assert after.submeshes[0].vertices == before.submeshes[0].vertices
            assert after.submeshes[1].vertices == before.submeshes[1].vertices
            assert len(after.submeshes[2].faces) == 1
        assert service.undo(view.session_id).ok
        restored = service.working_mesh(view.session_id)
        assert restored.submeshes[0].vertices == mesh.submeshes[0].vertices
        assert restored.submeshes[2].vertices == mesh.submeshes[2].vertices
        assert service.redo(view.session_id).ok
        restored = service.working_mesh(view.session_id)
        assert restored.submeshes[0].vertices[0][0] == .125
        assert restored.submeshes[2].vertices == []
    finally:
        session.cancel()
        service.close_edit_session(view.session_id, force_without_saving=True)

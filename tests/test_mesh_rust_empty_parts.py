from __future__ import annotations

import pytest

from cdmw.services.mesh_rust_authoring import (
    RustMeshValidationError,
    read_owned_payload_reference,
)
from tests import test_mesh_rust_authoring as fixtures


@pytest.mark.parametrize("skinned", [False, True])
def test_last_vertex_delete_retains_session_history_and_exact_export_guards(tmp_path, skinned):
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

        # An editable empty slot is not permission to emit an unsupported PAC.
        revision = session.shadow_service.session_view(session.shadow_session_id).revision
        with pytest.raises(RustMeshValidationError):
            session.finish(fixtures._request(session, "finish_request", 3))
        assert not session.closed
        assert session.shadow_service.session_view(session.shadow_session_id).revision == revision
        report = session.shadow_service.validate_export(session.shadow_session_id)
        assert "empty_part" in {issue.code for issue in report.blockers}
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
    finally:
        session.cancel()

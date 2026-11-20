"""Generate Tangents on a mirrored UV seam splits vertices, and history has to hold that.

The native editor treated tangent generation as a channel-only edit and kept no
copy of the part before it ran. When the tangents could not share a vertex
across a mirrored seam the part gained vertices, and the commit threw "mesh
editor topology history missed an affected submesh" on about half of the real
meshes tried.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def _mirrored_seam_quad() -> ParsedMesh:
    # The second triangle's UVs are mirrored in U, so the two shared corners
    # (1 and 2) need opposite tangents and cannot stay single vertices.
    part = SubMesh(
        name="seam",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (0.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[(0, 1, 2), (1, 3, 2)],
    )
    return ParsedMesh(path="seam.obj", format="obj", submeshes=[part])


@pytest.fixture
def service():
    from cdmw.modding import mesh_native_core
    from cdmw.services.mesh_service import MeshService

    if not mesh_native_core.native_mesh_core_available():
        pytest.skip("native mesh core binary not available")
    return MeshService()


def test_a_tangent_split_is_recorded_and_undoes(service):
    view = service.open_edit_session(_mirrored_seam_quad(), session_id=f"tangent-split-{uuid4().hex}", mode="edit")
    try:
        result = service.apply_command(view.session_id, MeshEditCommand(
            "generate_tangents", selection=MeshEditSelection.from_maps(source_indices=(0,))))
        assert result.ok, result.message
        split = service.working_mesh(view.session_id).submeshes[0]
        assert len(split.vertices) > 4
        assert len(split.tangents) == len(split.vertices)
        assert len(split.faces) == 2
        assert service.undo(view.session_id).ok
        restored = service.working_mesh(view.session_id).submeshes[0]
        assert len(restored.vertices) == 4
        assert [tuple(face) for face in restored.faces] == [(0, 1, 2), (1, 3, 2)]
        assert service.redo(view.session_id).ok
        assert len(service.working_mesh(view.session_id).submeshes[0].vertices) == len(split.vertices)
    finally:
        service.close_edit_session(view.session_id)


def test_tangents_without_a_split_still_use_channel_history(service):
    flat = _mirrored_seam_quad()
    flat.submeshes[0].uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
    view = service.open_edit_session(flat, session_id=f"tangent-plain-{uuid4().hex}", mode="edit")
    try:
        result = service.apply_command(view.session_id, MeshEditCommand(
            "generate_tangents", selection=MeshEditSelection.from_maps(source_indices=(0,))))
        assert result.ok, result.message
        assert not result.topology_changed
        assert len(service.working_mesh(view.session_id).submeshes[0].vertices) == 4
        assert service.undo(view.session_id).ok
        assert len(service.working_mesh(view.session_id).submeshes[0].tangents or ()) in (0, 4)
    finally:
        service.close_edit_session(view.session_id)

from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_native_core import find_native_mesh_core_binary
from cdmw.ui.mesh_editor.native_topology_updates import _material_source_index
from cdmw.ui.mesh_editor.static_replacement_adapter import StaticReplacementMeshEditSession
from tools.mesh_editor_dev_harness import _build_two_part_synthetic_mesh


ROOT = Path(__file__).resolve().parents[1]
DOTNET = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET / name).read_text(encoding="utf-8")


def test_vertex_update_applies_all_channels_and_retains_affected_gpu_ranges() -> None:
    protocol = _source("ExperimentForm.Protocol.cs")
    geometry = _source("D3D11MaterialViewport.Geometry.cs")
    soak = _source("HeadlessGpuSparseSoak.cs")
    parser = _source("ExperimentForm.GeometryProtocol.cs")

    assert 'JsonOrBinaryDoubles(group, "normals", "normals_binary")' in parser
    assert 'JsonOrBinaryDoubles(group, "uvs", "uvs_binary")' in parser
    assert protocol.index("TryParsePreviewVertexGroups") < protocol.index("submesh.Normals[vertexIndex] =")
    assert "submesh.Normals[vertexIndex] =" in protocol
    assert "submesh.Uvs[vertexIndex] =" in protocol
    assert geometry.count("AddDirtyFaces(dirtyFaces, batch.SourceVertexToRenderCorners") == 3
    assert "UpdateSubresource(" in geometry
    assert "new MeshVertexChannelChanges(dirtyIndex, dirtyIndex, dirtyIndex)" in soak
    assert "EnsureVertexAlignedNormals(submesh)" in protocol
    assert "EnsureVertexAlignedUvs(submesh)" in protocol
    assert "face.Corners[cornerIndex] = corner with { NormalIndex = corner.VertexIndex };" in parser
    assert "face.Corners[cornerIndex] = corner with { UvIndex = corner.VertexIndex };" in parser


def test_ordinary_topology_update_rebuilds_only_affected_d3d_batch() -> None:
    protocol = _source("ExperimentForm.Protocol.cs")
    parser = _source("ExperimentForm.GeometryProtocol.cs")
    viewport = _source("MeshViewport.Topology.cs")
    geometry = _source("D3D11MaterialViewport.Geometry.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")

    assert "TryApplyPreviewTriangleGroups" in protocol
    assert 'JsonInt(root, "final_submesh_count", -1)' in parser
    assert "var referenceSubmeshes = document.Submeshes.Skip(previousEditableCount).ToArray();" in parser
    assert "document.Submeshes.AddRange(referenceSubmeshes);" in parser
    assert "editableSubmeshes[item.SubmeshIndex] = item.Submesh" in parser
    assert "previousEditableSubmeshCount" in protocol
    assert "out var topologySources" in protocol
    topology_refresh = viewport.split("public void RefreshTopologyGeometry(", 1)[1].split(
        "public void RefreshVertexGeometry(", 1
    )[0]
    assert "RefreshTopologyGeometry(affectedSubmeshes, materialSources, replaceAll)" in topology_refresh
    assert "_d3d11Viewport?.RefreshGeometry()" not in topology_refresh
    assert "ApplyPendingTopologyUpdates" in geometry
    assert "var replaced = requested.ToHashSet();" in geometry
    assert "batch.SubmeshIndex >= _document.Submeshes.Count" in geometry
    assert "_materialSourceBySubmesh.Remove(staleIndex);" in geometry
    assert "editableSubmeshes.RemoveRange(finalCount" in parser
    assert "Math.Min(_scene.EditableSubmeshCount, _document.Submeshes.Count)" in viewport
    assert "DisposeBatches();" not in geometry.split("private void ApplyPendingTopologyUpdates()", 1)[1].split(
        "private int MaterialSourceFor", 1
    )[0]
    assert '"partial_topology_rebuilds"' in metrics
    soak = _source("HeadlessGpuSparseSoak.cs")
    assert "ResidentTopologyPacketProof()" in soak
    assert 'gates["resident_topology_add_remove_packets"]' in soak
    assert '"partial_tail_shrink_applied"' in soak
    assert '"incomplete_replace_all_rejected"' in soak
    assert '"missing_vertex_channels_initialized"' in soak
    assert '"equal_count_channels_remapped"' in soak
    assert '"malformed_vertex_channel_rejected"' in soak
    assert '"material_parameter_lineage_remapped"' in soak
    assert '"combined_scene_references_preserved_after_delete"' in soak
    assert '"combined_scene_references_preserved_after_add"' in soak
    assert protocol.index("_scene.RemapTopologyState(") < protocol.index("_viewport.RefreshTopologyGeometry(")
    assert "RemapTopologyState(materialSources, _document.Submeshes.Count)" in protocol
    scene = _source("NetSceneState.cs")
    assert "public void RemapTopologyState(" in scene
    assert "EditableSubmeshCount = nextEditableCount;" in scene
    assert "ReferenceSubmeshCount = totalCount - nextEditableCount;" in scene
    resident_materials = _source("NetMaterialSet.Resident.cs")
    assert "public IReadOnlySet<int> RemapTopologyState(" in resident_materials
    assert "binding with { SubmeshIndex = targetIndex }" in resident_materials
    assert "ParameterStates = nextParameters;" in resident_materials


def test_whole_part_delete_sends_affected_only_shrink() -> None:
    # `delete` is a native mesh-edit command and the Python fallback is disabled
    # by design, so without the core built there is no topology update to assert.
    if find_native_mesh_core_binary() is None:
        pytest.skip("cdmw_mesh_core is not built")
    session = StaticReplacementMeshEditSession(session_id="dotnet-partial-delete")
    session.open(_build_two_part_synthetic_mesh())
    try:
        deleted = session.apply("delete", source_indices=(0,), delete_parts=True)
        update = deleted.native_update

        assert not update.replace_all_triangles
        assert update.final_submesh_count == 1
        assert update.triangle_source_submesh_indices == (0, 1)
        assert len(update.triangle_groups) == 1
        group = update.triangle_groups[0]
        assert group["source_submesh_index"] == 0
        assert not (group.get("positions") or group.get("positions_binary"))
        assert not (group.get("indices") or group.get("indices_binary"))
    finally:
        session.close()


def test_dotnet_packet_forwards_explicit_final_submesh_count() -> None:
    sender = (ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_payloads.py").read_text(encoding="utf-8")
    update = (ROOT / "cdmw" / "ui" / "mesh_editor" / "controller.py").read_text(encoding="utf-8")
    topology = (ROOT / "cdmw" / "ui" / "mesh_editor" / "controller_topology.py").read_text(encoding="utf-8")

    assert "final_submesh_count: int | None = None" in update
    assert '"final_submesh_count": update.final_submesh_count' in sender
    assert "final_submesh_count(self, result)" in update
    assert "shrink_source_indices(result, requested, final_count)" in update
    assert "return tuple(range(first_affected, last_affected))" in topology


def test_material_lineage_beats_ambiguous_duplicate_labels() -> None:
    duplicate = SimpleNamespace(name="same", material="same", texture="same.dds")
    current = SimpleNamespace(
        name="same",
        material="same",
        texture="same.dds",
        cdmw_mesh_edit_material_source_submesh_index=1,
    )

    assert _material_source_index(current, 0, (duplicate, duplicate)) == 1

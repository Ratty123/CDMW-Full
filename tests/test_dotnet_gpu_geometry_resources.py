from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET_EDITOR = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET_EDITOR / name).read_text(encoding="utf-8")


def _method(source: str, signature: str, next_signature: str) -> str:
    return source.split(signature, maxsplit=1)[1].split(next_signature, maxsplit=1)[0]


def test_sparse_vertex_refresh_retains_topology_and_uploads_only_incident_ranges() -> None:
    geometry = _source("D3D11MaterialViewport.Geometry.cs")
    topology = _source("MeshViewport.Topology.cs")
    sparse_refresh = _method(
        topology,
        "public void RefreshVertexGeometry(IReadOnlyDictionary<int, IReadOnlyCollection<int>> changedVertices)",
        "public void RefreshVertexGeometry(IEnumerable<int> changedSubmeshes)",
    )

    assert "SourceVertexToRenderCorners" in geometry
    assert "renderCorner / 3" in geometry
    assert "PatchBatchVertexRanges" in geometry
    assert "UploadFaceRange" in geometry
    assert "ArrayPool<D3D11MaterialVertex>.Shared.Rent" in geometry
    assert "UpdateSubresource(" in geometry
    assert "new Box(byteStart, 0, 0, byteEnd, 1, 1)" in geometry
    assert "batch.TopologyGeneration != _topologyGeneration" in geometry
    assert "RefreshModelBounds" not in sparse_refresh
    assert "RebuildEdgeTopology" not in sparse_refresh
    assert "ExpandModelBounds(changed)" in sparse_refresh
    expand_bounds = _method(topology, "private void ExpandModelBounds(", "private void RefreshModelBounds()")
    assert "_document.Bounds()" not in expand_bounds
    assert "_center =" not in expand_bounds


def test_topology_refresh_rebuilds_buffers_but_camera_frame_does_not() -> None:
    geometry = _source("D3D11MaterialViewport.Geometry.cs")
    topology = _source("MeshViewport.Topology.cs")
    refresh = _method(topology, "public void RefreshBounds()", "public void RefreshVertexGeometry(")
    frame = _method(topology, "public void FrameMesh()", "private static void ReplaceSelectionMap")

    assert "_d3d11Viewport.RefreshGeometry();" in refresh
    assert "RebuildEdgeTopology();" in refresh
    assert "RebuildPartAdjacency();" in refresh
    assert "var nextGeneration = _topologyGeneration + 1;" in geometry
    assert "DisposeBatches();" in geometry
    assert "RefreshBounds();" not in frame


def test_draw_resources_and_renderer_metrics_are_cached_and_exposed() -> None:
    renderer = _source("D3D11MaterialViewport.cs")
    resources = _source("D3D11MaterialViewport.Resources.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")
    viewport_metrics = _source("MeshViewport.RendererResources.cs")
    status = _source("MeshViewport.Status.cs")

    assert "batch.Materials.ShaderResources" in renderer
    assert "ToSrvArray" not in renderer
    assert "ShaderResources = new[]" in resources
    assert "RefreshTextures()" in resources
    assert "_geometryDirty = true" not in _method(resources, "public void RefreshTextures()", "private void RebuildMaterialResourcesIfDirty()")
    assert '"full_geometry_rebuilds"' in metrics
    assert '"sparse_vertex_updates"' in metrics
    assert '"peak_geometry_old_plus_new_bytes_estimate"' in metrics
    assert '"oldest_live_texture_srv_ms"' in metrics
    assert '"peak_old_plus_new_vram_bytes_estimate"' in metrics
    assert "RendererResourceMetricsPayload" in viewport_metrics
    assert '["geometry_resources"] = RendererResourceMetricsPayload()' in status


def test_hidden_gpu_sparse_soak_uses_real_d3d_resources_and_versioned_evidence() -> None:
    entry = _source("ProgramEntry.cs")
    soak = _source("HeadlessGpuSparseSoak.cs")
    headless = _source("D3D11MaterialViewport.Headless.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")

    assert entry.index("HeadlessGpuSparseSoak.IsRequested(args)") < entry.index("LaunchOptions.Parse(args)")
    assert '"--headless-gpu-sparse-soak"' in entry
    assert '"cdmw_dotnet_gpu_sparse_soak_v1"' in soak
    assert 'Integer(values, "gpu-soak-vertices", 1_000_000' in soak
    assert 'Integer(values, "gpu-soak-updates", 1_000' in soak
    assert 'TargetUpdatesPerSecond)\n' in soak
    assert "BuildSyntheticDocument(options.VertexCount)" in soak
    assert "durations[update] = ApplySparseUpdate(" in soak
    assert "Hidden D3D11 final sparse frame failed" in soak
    assert '"frame_sample_count"' in soak
    assert "checked_in_asset_used" in soak
    assert "Application.Run" not in soak
    assert "Show()" not in soak
    assert "IsWindowVisible(host.Handle)" in soak
    assert 'gates["native_windows_remained_hidden"]' in soak
    assert 'gates["production_d3d11_backend"]' in soak
    assert "TryRunHeadlessFrame" in headless
    assert "RenderFrame()" in headless
    assert '"geometry_buffer_identity"' in metrics
    assert '"dxgi_local_memory_current_usage_bytes"' in metrics
    assert '"material_binding_array_identity"' in metrics


def test_sparse_bounds_rebase_when_an_extremum_moves_inward() -> None:
    topology = _source("MeshViewport.Topology.cs")
    bounds = _source("MeshViewport.Bounds.cs")
    soak = _source("HeadlessGpuSparseSoak.cs")

    assert "SparseBounds.Update(changedVertices);" in topology
    assert "ApplySparseBounds();" in topology
    assert "TouchesExtremumOwner(changedVertices)" in bounds
    assert "BoundaryTriggeredRebaseCount++" in bounds
    assert "Rebase();" in bounds
    assert "Center = BoundsCenter(min, max);" in bounds
    assert "SparseBoundsProof()" in soak
    assert '"inward_bounds_and_center_exact"' in soak

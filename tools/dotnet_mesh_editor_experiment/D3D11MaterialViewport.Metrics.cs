using System.Runtime.CompilerServices;
using Vortice.DXGI;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private ulong _peakDxgiLocalUsageBytes;

    public Dictionary<string, object?> ResourceMetricsPayload()
    {
        var videoMemory = QueryLocalVideoMemory();
        _peakDxgiLocalUsageBytes = Math.Max(_peakDxgiLocalUsageBytes, videoMemory.CurrentUsage);
        var oldestGeometryAgeMs = _batches.Count == 0
            ? 0.0
            : _batches.Max(batch => ElapsedMilliseconds(batch.CreatedTimestamp));
        var oldestTextureAgeMs = _textureSrvCache.Count == 0
            ? 0.0
            : _textureSrvCache.Values.Max(entry => ElapsedMilliseconds(entry.CreatedTimestamp));
        return new Dictionary<string, object?>
        {
            ["available"] = true,
            ["topology_generation"] = _topologyGeneration,
            ["full_geometry_rebuilds"] = _fullGeometryRebuildCount,
            ["partial_topology_rebuilds"] = _partialTopologyRebuildCount,
            ["topology_batches_rebuilt"] = _topologyBatchesRebuilt,
            ["sparse_vertex_updates"] = _sparseVertexUpdateCount,
            ["vertex_patch_ranges"] = _vertexPatchRangeCount,
            ["source_vertices_patched"] = _sourceVerticesPatched,
            ["render_vertices_uploaded"] = _renderVerticesUploaded,
            ["vertex_buffer_creates"] = _vertexBufferCreateCount,
            ["index_buffer_creates"] = _indexBufferCreateCount,
            ["geometry_buffer_disposals"] = _bufferDisposeCount,
            ["geometry_buffer_identity"] = GeometryBufferIdentity(),
            ["live_geometry_batches"] = _batches.Count,
            ["textured_solid_batch_draws"] = _texturedSolidBatchDrawCount,
            ["untextured_solid_batch_draws"] = _untexturedSolidBatchDrawCount,
            ["transparent_solid_batch_draws"] = _transparentSolidBatchDrawCount,
            ["alpha_blend_pass"] = "back_to_front_submesh_depth_read_no_write",
            ["wire_overlay_draws"] = _wireOverlayDrawCount,
            ["vertex_overlay_batch_draws"] = _vertexOverlayBatchDrawCount,
            ["vertex_marker_size_pixels"] = VertexMarkerSizePixels,
            ["overlay_vertex_buffer_creates"] = _overlayVertexBufferCreateCount,
            ["overlay_vertex_buffer_maps"] = _overlayVertexBufferMapCount,
            ["overlay_vertex_buffer_no_overwrite_maps"] = _overlayVertexBufferNoOverwriteCount,
            ["overlay_vertices_uploaded"] = _overlayVerticesUploaded,
            ["overlay_vertex_capacity"] = _overlayVertexCapacity,
            ["overlay_vertex_buffer_reused"] = _overlayVertexBufferCreateCount > 0
                && _overlayVertexBufferMapCount > _overlayVertexBufferCreateCount,
            ["resident_geometry_bytes_estimate"] = _residentGeometryBytes,
            ["peak_resident_geometry_bytes_estimate"] = _peakResidentGeometryBytes,
            ["peak_geometry_old_plus_new_bytes_estimate"] = _peakGeometryRebuildBytesEstimate,
            ["oldest_live_geometry_resource_ms"] = oldestGeometryAgeMs,
            ["max_disposed_geometry_resource_ms"] = _maxDisposedGeometryResourceLifetimeMs,
            ["texture_srv_creates"] = _textureSrvCreateCount,
            ["texture_srv_disposals"] = _textureSrvDisposeCount,
            ["texture_srv_reuses"] = _textureSrvReuseCount,
            ["native_dds_srv_creates"] = _nativeDdsSrvCreateCount,
            ["bitmap_texture_srv_creates"] = _bitmapTextureSrvCreateCount,
            ["native_dds_upload_fallbacks"] = _nativeDdsFallbackCount,
            ["native_dds_texture_resources"] = NativeDdsTextureCount,
            ["bitmap_fallback_texture_resources"] = BitmapFallbackTextureCount,
            ["texture_resource_diagnostics"] = TextureResourceDiagnosticsPayload(),
            ["superseded_texture_srv_prunes"] = _supersededTextureSrvPruneCount,
            ["material_binding_array_creates"] = _materialBindingArrayCreateCount,
            ["material_state_apply_count"] = _materialStateApplyCount,
            ["material_state_apply_failure_count"] = _materialStateApplyFailureCount,
            ["affected_material_batch_rebinds"] = _affectedMaterialBatchRebindCount,
            ["material_parameter_apply_count"] = _materialParameterApplyCount,
            ["material_parameter_apply_failure_count"] = _materialParameterApplyFailureCount,
            ["affected_material_parameter_batches"] = _affectedMaterialParameterBatchCount,
            ["live_texture_srvs"] = _textureSrvCache.Count,
            ["resident_texture_bytes_estimate"] = _textureResidentBytes,
            ["peak_resident_texture_bytes_estimate"] = _peakTextureResidentBytes,
            ["peak_texture_old_plus_new_bytes_estimate"] = _peakTextureRefreshBytesEstimate,
            ["oldest_live_texture_srv_ms"] = oldestTextureAgeMs,
            ["max_disposed_texture_srv_ms"] = _maxDisposedTextureResourceLifetimeMs,
            ["texture_region_patch_count"] = _textureRegionPatchCount,
            ["texture_region_bytes_uploaded"] = _textureRegionBytesUploaded,
            ["texture_region_failure_count"] = _textureRegionFailureCount,
            ["texture_region_affected_batch_rebinds"] = _textureRegionAffectedBatchRebindCount,
            ["texture_region_mip_generation_count"] = _textureRegionMipGenerationCount,
            ["editable_texture_resources"] = _editableTextureRegions.Count,
            ["editable_texture_mip_levels"] = _editableTextureRegions.ToDictionary(
                pair => pair.Key,
                pair => pair.Value.MipCount,
                StringComparer.Ordinal),
            ["cached_material_binding_arrays"] = _batches.Count,
            ["material_binding_array_identity"] = MaterialBindingArrayIdentity(),
            ["resident_topology_mapping_bytes_estimate"] = _batches.Sum(batch => batch.SourceVertexToRenderCorners.EstimatedBytes),
            ["resident_vram_bytes_estimate"] = _residentGeometryBytes + _textureResidentBytes,
            ["peak_old_plus_new_vram_bytes_estimate"] = Math.Max(
                _peakGeometryRebuildBytesEstimate + _peakTextureResidentBytes,
                _peakTextureRefreshBytesEstimate + _peakResidentGeometryBytes),
            ["dxgi_local_memory_available"] = videoMemory.Available,
            ["dxgi_local_memory_current_usage_bytes"] = videoMemory.CurrentUsage,
            ["dxgi_local_memory_budget_bytes"] = videoMemory.Budget,
            ["peak_sampled_dxgi_local_memory_usage_bytes"] = _peakDxgiLocalUsageBytes,
        };
    }

    private int MaterialBindingArrayIdentity()
    {
        var identity = new HashCode();
        foreach (var batch in _batches)
        {
            identity.Add(RuntimeHelpers.GetHashCode(batch.Materials.ShaderResources));
        }
        return identity.ToHashCode();
    }

    private int GeometryBufferIdentity()
    {
        var identity = new HashCode();
        foreach (var batch in _batches)
        {
            identity.Add(RuntimeHelpers.GetHashCode(batch.VertexBuffer));
            identity.Add(RuntimeHelpers.GetHashCode(batch.IndexBuffer));
        }
        return identity.ToHashCode();
    }

    private (bool Available, ulong CurrentUsage, ulong Budget) QueryLocalVideoMemory()
    {
        if (_device is null)
        {
            return (false, 0, 0);
        }
        try
        {
            using var dxgiDevice = _device.QueryInterface<IDXGIDevice>();
            using var adapter = dxgiDevice.GetAdapter();
            using var adapter3 = adapter.QueryInterface<IDXGIAdapter3>();
            var info = adapter3.QueryVideoMemoryInfo(0, MemorySegmentGroup.Local);
            return (true, info.CurrentUsage, info.Budget);
        }
        catch
        {
            return (false, 0, 0);
        }
    }
}

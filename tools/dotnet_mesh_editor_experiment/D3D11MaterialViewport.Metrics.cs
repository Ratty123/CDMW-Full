using System.Runtime.CompilerServices;
using Vortice.DXGI;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private ulong _peakDxgiLocalUsageBytes;

    public Dictionary<string, object?> LiveMetricsPayload()
    {
        return new Dictionary<string, object?>
        {
            ["available"] = true,
            ["topology_generation"] = _topologyGeneration,
            ["sparse_vertex_updates"] = _sparseVertexUpdateCount,
            ["vertex_patch_ranges"] = _vertexPatchRangeCount,
            ["textured_solid_batch_draws"] = _texturedSolidBatchDrawCount,
            ["untextured_solid_batch_draws"] = _untexturedSolidBatchDrawCount,
            ["transparent_solid_batch_draws"] = _transparentSolidBatchDrawCount,
            ["wire_overlay_draws"] = _wireOverlayDrawCount,
            ["vertex_overlay_batch_draws"] = _vertexOverlayBatchDrawCount,
            ["xray_wire_no_depth_draws"] = _xRayWireNoDepthDrawCount,
            ["xray_vertex_no_depth_passes"] = _xRayVertexNoDepthPassCount,
            ["gizmo_overlay_draws"] = _gizmoOverlayDrawCount,
            ["overlay_vertex_buffer_maps"] = _overlayVertexBufferMapCount,
            ["overlay_vertices_uploaded"] = _overlayVerticesUploaded,
            ["overlay_batch_flushes"] = _overlayBatchFlushCount,
            ["overlay_batched_draws"] = _overlayBatchedDrawCount,
            ["retained_overlay_cache_hits"] = _retainedOverlayCacheHitCount,
            ["retained_overlay_rebuilds"] = _retainedOverlayRebuildCount,
            ["texture_region_patch_count"] = _textureRegionPatchCount,
            ["texture_region_bytes_uploaded"] = _textureRegionBytesUploaded,
            ["texture_region_mip_generation_count"] = _textureRegionMipGenerationCount,
            ["texture_region_gpu_upload_pass_count"] = _textureRegionGpuUploadPassCount,
            ["texture_region_coalesced_count"] = _textureRegionCoalescedCount,
            ["texture_region_pending_depth"] = _pendingTextureRegions.Count,
            ["resident_geometry_bytes_estimate"] = _residentGeometryBytes,
            ["resident_texture_bytes_estimate"] = _textureResidentBytes,
            ["device_reset_count"] = _deviceResetCount,
            ["gpu_timestamp_queries_issued"] = _gpuTimingQueryIssuedCount,
            ["gpu_timestamp_queries_resolved"] = _gpuTimingQueryResolvedCount,
            ["gpu_timestamp_queries_disjoint"] = _gpuTimingQueryDisjointCount,
            ["gpu_timestamp_queries_dropped"] = _gpuTimingQueryDroppedCount,
            ["swap_chain_resize_deferred_count"] = _swapChainResizeDeferredCount,
            ["swap_chain_resize_coalesced_count"] = _swapChainResizeCoalescedCount,
            ["swap_chain_resize_commit_count"] = _swapChainResizeCommitCount,
            ["render_sample_count"] = _renderSampleCount,
            ["render_sample_quality"] = _renderSampleQuality,
            ["anti_aliasing_mode"] = AntiAliasingMode,
            ["multisample_resolve_count"] = _multisampleResolveCount,
            ["offscreen_multisample_resolve_count"] = _offscreenMultisampleResolveCount,
            ["render_surface_identity"] = RenderSurfaceIdentity,
            ["render_surface_bytes_estimate"] = _renderSurfaceBytesEstimate,
            ["offscreen_capture_surface_bytes_estimate"] = _offscreenCaptureSurfaceBytesEstimate,
        };
    }

    public Dictionary<string, object?> ResourceMetricsPayload()
    {
        var overlayStyle = FitRelativeOverlayPolicy.ForCamera(_camera, _overlaySettings.Sizing);
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
            ["fit_relative_overlay_zoom_ratio"] = overlayStyle.ZoomRatio,
            ["vertex_marker_size_pixels"] = overlayStyle.VertexMarkerSizePixels,
            ["vertex_marker_fit_size_pixels"] = _overlaySettings.Sizing.VertexMarkerSizePixels,
            ["wire_overlay_opacity_scale"] = overlayStyle.WireOpacityScale,
            ["wire_overlay_width_pixels"] = _overlaySettings.Sizing.WireWidthPixels,
            ["wire_overlay_color"] = MeshOverlayColors.Hex(_overlaySettings.Colors.Wire),
            ["vertex_overlay_color"] = MeshOverlayColors.Hex(_overlaySettings.Colors.Vertex),
            ["xray_wire_overlay_color"] = MeshOverlayColors.Hex(MeshOverlayColors.AutomaticXRayWire),
            ["xray_vertex_overlay_color"] = MeshOverlayColors.Hex(MeshOverlayColors.AutomaticXRayVertex),
            ["xray_overlay_active"] = _overlayShowXRay,
            ["xray_wire_no_depth_draws"] = _xRayWireNoDepthDrawCount,
            ["xray_vertex_no_depth_passes"] = _xRayVertexNoDepthPassCount,
            ["gizmo_overlay_draws"] = _gizmoOverlayDrawCount,
            ["gizmo_x_axis_color"] = GizmoAppearance.Hex(_gizmoAppearance.XAxis),
            ["gizmo_y_axis_color"] = GizmoAppearance.Hex(_gizmoAppearance.YAxis),
            ["gizmo_z_axis_color"] = GizmoAppearance.Hex(_gizmoAppearance.ZAxis),
            ["gizmo_highlight_color"] = GizmoAppearance.Hex(_gizmoAppearance.Highlight),
            ["gizmo_label_color"] = GizmoAppearance.Hex(_gizmoAppearance.Label),
            ["gizmo_line_thickness_pixels"] = _gizmoAppearance.LineThicknessPixels,
            ["gizmo_size_scale"] = _gizmoAppearance.SizeScale,
            ["gizmo_label_size_pixels"] = _gizmoAppearance.LabelSizePixels,
            ["gizmo_handle_size_pixels"] = _gizmoAppearance.HandleSizePixels,
            ["overlay_vertex_buffer_creates"] = _overlayVertexBufferCreateCount,
            ["overlay_vertex_buffer_maps"] = _overlayVertexBufferMapCount,
            ["overlay_vertex_buffer_no_overwrite_maps"] = 0L,
            ["overlay_vertices_uploaded"] = _overlayVerticesUploaded,
            ["overlay_batch_flushes"] = _overlayBatchFlushCount,
            ["overlay_batched_draws"] = _overlayBatchedDrawCount,
            ["retained_overlay_cache_hits"] = _retainedOverlayCacheHitCount,
            ["retained_overlay_rebuilds"] = _retainedOverlayRebuildCount,
            ["overlay_vertex_capacity"] = _overlayVertexCapacity,
            ["overlay_vertex_buffer_reused"] = _overlayVertexBufferCreateCount > 0
                && _overlayVertexBufferMapCount > _overlayVertexBufferCreateCount,
            ["overlay_uploads_batched"] = _overlayBatchedDrawCount > _overlayBatchFlushCount,
            ["gpu_timestamp_query_slots"] = _gpuTimingQuerySets.Length,
            ["gpu_timestamp_queries_issued"] = _gpuTimingQueryIssuedCount,
            ["gpu_timestamp_queries_resolved"] = _gpuTimingQueryResolvedCount,
            ["gpu_timestamp_queries_disjoint"] = _gpuTimingQueryDisjointCount,
            ["gpu_timestamp_queries_dropped"] = _gpuTimingQueryDroppedCount,
            ["swap_chain_resize_deferred_count"] = _swapChainResizeDeferredCount,
            ["swap_chain_resize_coalesced_count"] = _swapChainResizeCoalescedCount,
            ["swap_chain_resize_commit_count"] = _swapChainResizeCommitCount,
            ["render_sample_count"] = _renderSampleCount,
            ["render_sample_quality"] = _renderSampleQuality,
            ["anti_aliasing_mode"] = AntiAliasingMode,
            ["anti_aliasing_fallback_reason"] = _antiAliasingFallbackReason,
            ["multisample_resolve_count"] = _multisampleResolveCount,
            ["offscreen_multisample_resolve_count"] = _offscreenMultisampleResolveCount,
            ["render_surface_create_count"] = _renderSurfaceCreateCount,
            ["render_surface_dispose_count"] = _renderSurfaceDisposeCount,
            ["render_surface_identity"] = RenderSurfaceIdentity,
            ["render_surface_bytes_estimate"] = _renderSurfaceBytesEstimate,
            ["peak_render_surface_bytes_estimate"] = _peakRenderSurfaceBytesEstimate,
            ["offscreen_capture_surface_bytes_estimate"] = _offscreenCaptureSurfaceBytesEstimate,
            ["peak_offscreen_capture_surface_bytes_estimate"] = _peakOffscreenCaptureSurfaceBytesEstimate,
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
            ["texture_region_gpu_upload_pass_count"] = _textureRegionGpuUploadPassCount,
            ["texture_region_coalesced_count"] = _textureRegionCoalescedCount,
            ["texture_region_pending_depth"] = _pendingTextureRegions.Count,
            ["texture_region_maximum_pending_depth"] = _maximumPendingTextureRegionDepth,
            ["editable_texture_resources"] = _editableTextureRegions.Count,
            ["editable_texture_mip_levels"] = _editableTextureRegions.ToDictionary(
                pair => pair.Key,
                pair => pair.Value.MipCount,
                StringComparer.Ordinal),
            ["cached_material_binding_arrays"] = _batches.Count,
            ["material_binding_array_identity"] = MaterialBindingArrayIdentity(),
            ["resident_topology_mapping_bytes_estimate"] = _batches.Sum(batch => batch.SourceVertexToRenderCorners.EstimatedBytes),
            ["resident_vram_bytes_estimate"] = _residentGeometryBytes
                + _textureResidentBytes
                + _renderSurfaceBytesEstimate,
            ["peak_old_plus_new_vram_bytes_estimate"] = Math.Max(
                _peakGeometryRebuildBytesEstimate
                    + _peakTextureResidentBytes
                    + _peakRenderSurfaceBytesEstimate,
                _peakTextureRefreshBytesEstimate
                    + _peakResidentGeometryBytes
                    + _peakRenderSurfaceBytesEstimate),
            ["peak_resident_plus_capture_vram_bytes_estimate"] = Math.Max(
                _peakGeometryRebuildBytesEstimate
                    + _peakTextureResidentBytes
                    + _peakRenderSurfaceBytesEstimate,
                _peakTextureRefreshBytesEstimate
                    + _peakResidentGeometryBytes
                    + _peakRenderSurfaceBytesEstimate)
                + _peakOffscreenCaptureSurfaceBytesEstimate,
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

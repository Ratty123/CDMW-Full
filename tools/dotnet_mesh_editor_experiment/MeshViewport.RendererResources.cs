namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private long _retiredGeometryUploadCount;
    private long _retiredDeviceResetAttemptCount;
    private long _retiredDeviceResetCount;

    public long GeometryUploadCount => _retiredGeometryUploadCount + (_d3d11Viewport?.GeometryUploadCount ?? 0);
    public long DeviceResetAttemptCount => _retiredDeviceResetAttemptCount + (_d3d11Viewport?.DeviceResetAttemptCount ?? 0);
    public long DeviceResetCount => _retiredDeviceResetCount + (_d3d11Viewport?.DeviceResetCount ?? 0);
    public string RendererBackendName => RendererBackend;

    private void RetainD3D11LifecycleCounts(D3D11MaterialViewport viewport)
    {
        _retiredGeometryUploadCount += viewport.GeometryUploadCount;
        _retiredDeviceResetAttemptCount += viewport.DeviceResetAttemptCount;
        _retiredDeviceResetCount += viewport.DeviceResetCount;
    }

    public Dictionary<string, object?> RendererResourceMetricsPayload()
    {
        return _d3d11Viewport?.ResourceMetricsPayload()
            ?? new Dictionary<string, object?> { ["available"] = false };
    }

    public void PrepareRendererPerformanceCapture() => _d3d11Viewport?.PreparePerformanceCapture();

    public Dictionary<string, object?> RendererLiveMetricsPayload()
    {
        return new Dictionary<string, object?>
        {
            ["backend"] = RendererBackend,
            ["gpu_backed"] = !_rendererBlocked && (_d3d11Viewport is not null || _gpuViewport is not null),
            ["renderer_blocked"] = _rendererBlocked,
            ["present_sync_interval"] = _d3d11Viewport?.PresentSyncInterval,
            ["maximum_frame_latency"] = _d3d11Viewport?.MaximumFrameLatency,
            ["presentation_model"] = _d3d11Viewport?.PresentationModel,
            ["geometry_upload_count"] = GeometryUploadCount,
            ["device_reset_attempt_count"] = DeviceResetAttemptCount,
            ["device_reset_count"] = DeviceResetCount,
            ["geometry_resources"] = _d3d11Viewport?.LiveMetricsPayload()
                ?? new Dictionary<string, object?> { ["available"] = false },
        };
    }
}

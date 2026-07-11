namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private long _retiredGeometryUploadCount;
    private long _retiredDeviceResetAttemptCount;
    private long _retiredDeviceResetCount;

    public long GeometryUploadCount => _retiredGeometryUploadCount + (_d3d11Viewport?.GeometryUploadCount ?? 0);
    public long DeviceResetAttemptCount => _retiredDeviceResetAttemptCount + (_d3d11Viewport?.DeviceResetAttemptCount ?? 0);
    public long DeviceResetCount => _retiredDeviceResetCount + (_d3d11Viewport?.DeviceResetCount ?? 0);

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
}

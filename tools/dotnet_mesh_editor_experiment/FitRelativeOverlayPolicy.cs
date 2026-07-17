namespace Cdmw.MeshEditorExperiment;

internal readonly record struct FitRelativeOverlayStyle(
    float ZoomRatio,
    float VertexMarkerSizePixels,
    float WireOpacityScale);

internal static class FitRelativeOverlayPolicy
{
    internal const float MinimumVertexMarkerSizePixels = 2.0f;
    internal const float MinimumWireOpacityScale = 0.2f;

    internal static FitRelativeOverlayStyle ForCamera(NetViewportCamera camera) =>
        ForCamera(camera, MeshOverlaySizing.Default);

    internal static FitRelativeOverlayStyle ForCamera(NetViewportCamera camera, MeshOverlaySizing sizing) =>
        ForZoom(
            camera.Zoom,
            CameraZoomPolicy.FitZoomForSceneSize(camera.SceneSize),
            sizing.VertexMarkerSizePixels);

    internal static FitRelativeOverlayStyle ForZoom(float currentZoom, float fitZoom) =>
        ForZoom(currentZoom, fitZoom, MeshOverlaySizing.DefaultVertexMarkerSizePixels);

    internal static FitRelativeOverlayStyle ForZoom(
        float currentZoom,
        float fitZoom,
        float fitVertexMarkerSizePixels)
    {
        var zoomRatio = CameraZoomPolicy.FitRelativeRatio(currentZoom, fitZoom);
        var zoomedOutScale = Math.Min(1.0f, zoomRatio);
        var normalizedFitSize = Math.Clamp(
            fitVertexMarkerSizePixels,
            MeshOverlaySizing.MinimumVertexMarkerSizePixels,
            MeshOverlaySizing.MaximumVertexMarkerSizePixels);
        var minimumSize = Math.Min(MinimumVertexMarkerSizePixels, normalizedFitSize);
        return new FitRelativeOverlayStyle(
            zoomRatio,
            Math.Clamp(
                normalizedFitSize * zoomedOutScale,
                minimumSize,
                normalizedFitSize),
            Math.Clamp(zoomedOutScale, MinimumWireOpacityScale, 1.0f));
    }
}

namespace Cdmw.MeshEditorExperiment;

internal readonly record struct FitRelativeOverlayStyle(
    float ZoomRatio,
    float VertexMarkerSizePixels,
    float WireOpacityScale);

internal static class FitRelativeOverlayPolicy
{
    internal const float FitVertexMarkerSizePixels = 7.0f;
    internal const float MinimumVertexMarkerSizePixels = 2.0f;
    internal const float MinimumWireOpacityScale = 0.2f;

    internal static FitRelativeOverlayStyle ForCamera(NetViewportCamera camera) =>
        ForZoom(camera.Zoom, CameraZoomPolicy.FitZoomForSceneSize(camera.SceneSize));

    internal static FitRelativeOverlayStyle ForZoom(float currentZoom, float fitZoom)
    {
        var zoomRatio = CameraZoomPolicy.FitRelativeRatio(currentZoom, fitZoom);
        var zoomedOutScale = Math.Min(1.0f, zoomRatio);
        return new FitRelativeOverlayStyle(
            zoomRatio,
            Math.Clamp(
                FitVertexMarkerSizePixels * zoomedOutScale,
                MinimumVertexMarkerSizePixels,
                FitVertexMarkerSizePixels),
            Math.Clamp(zoomedOutScale, MinimumWireOpacityScale, 1.0f));
    }
}

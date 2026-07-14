namespace Cdmw.MeshEditorExperiment;

internal static class CameraZoomPolicy
{
    private const float MouseWheelDeltaPerNotch = 120.0f;
    private const float WheelZoomPerNotch = 1.1f;
    private const float AbsoluteMinimumZoom = 0.001f;
    private const float LegacyMinimumZoom = 1.0f;
    private const float MinimumFitZoomRatio = 0.05f;
    private const float LegacyMaximumZoom = 500000.0f;
    private const float MaximumFitZoomRatio = 100.0f;

    internal static float ApplyWheelDelta(float currentZoom, float fitZoom, int delta)
    {
        if (delta == 0)
        {
            return Clamp(currentZoom, fitZoom);
        }
        var wheelNotches = delta / MouseWheelDeltaPerNotch;
        var zoomFactor = MathF.Pow(WheelZoomPerNotch, wheelNotches);
        return ApplyZoomFactor(currentZoom, fitZoom, zoomFactor);
    }

    internal static float ApplyZoomFactor(float currentZoom, float fitZoom, float zoomFactor)
    {
        var safeFitZoom = SafeFitZoom(fitZoom);
        var safeCurrentZoom = float.IsFinite(currentZoom) && currentZoom > 0.0f
            ? currentZoom
            : safeFitZoom;
        var safeZoomFactor = float.IsFinite(zoomFactor) && zoomFactor > 0.0f
            ? zoomFactor
            : 1.0f;
        return Clamp(safeCurrentZoom * safeZoomFactor, safeFitZoom);
    }

    internal static float MinimumZoom(float fitZoom)
    {
        var safeFitZoom = SafeFitZoom(fitZoom);
        return Math.Max(
            AbsoluteMinimumZoom,
            Math.Min(LegacyMinimumZoom, safeFitZoom * MinimumFitZoomRatio));
    }

    internal static float MaximumZoom(float fitZoom)
    {
        var safeFitZoom = SafeFitZoom(fitZoom);
        return Math.Max(LegacyMaximumZoom, safeFitZoom * MaximumFitZoomRatio);
    }

    private static float Clamp(float zoom, float fitZoom)
    {
        var safeFitZoom = SafeFitZoom(fitZoom);
        var candidate = float.IsFinite(zoom) && zoom > 0.0f ? zoom : safeFitZoom;
        return Math.Clamp(candidate, MinimumZoom(safeFitZoom), MaximumZoom(safeFitZoom));
    }

    private static float SafeFitZoom(float fitZoom) =>
        float.IsFinite(fitZoom) && fitZoom > 0.0f
            ? Math.Max(AbsoluteMinimumZoom, fitZoom)
            : LegacyMinimumZoom;
}

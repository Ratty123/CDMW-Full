namespace Cdmw.MeshEditorExperiment;

internal static class CameraZoomPolicy
{
    private const float MinimumFitZoomRatio = 0.1f;
    private const float MaximumFitZoomRatio = 64.0f;
    private static readonly float[] ArchiveBrowserZoomSteps =
    {
        0.1f,
        0.25f,
        0.5f,
        0.75f,
        1.0f,
        1.5f,
        2.0f,
        3.0f,
        4.0f,
        6.0f,
        8.0f,
        12.0f,
        16.0f,
        24.0f,
        32.0f,
        48.0f,
        64.0f,
    };

    internal static ReadOnlySpan<float> FitRelativeSteps => ArchiveBrowserZoomSteps;

    internal static float ApplyWheelDelta(float currentZoom, float fitZoom, int delta)
    {
        if (delta == 0)
        {
            return Clamp(currentZoom, fitZoom);
        }
        var safeFitZoom = SafeFitZoom(fitZoom);
        var currentRatio = Clamp(currentZoom, safeFitZoom) / safeFitZoom;
        var nearestIndex = 0;
        var nearestDistance = Math.Abs(currentRatio - ArchiveBrowserZoomSteps[0]);
        for (var index = 1; index < ArchiveBrowserZoomSteps.Length; index++)
        {
            var distance = Math.Abs(currentRatio - ArchiveBrowserZoomSteps[index]);
            if (distance < nearestDistance)
            {
                nearestIndex = index;
                nearestDistance = distance;
            }
        }
        var targetIndex = Math.Clamp(
            nearestIndex + (delta > 0 ? 1 : -1),
            0,
            ArchiveBrowserZoomSteps.Length - 1);
        return Clamp(safeFitZoom * ArchiveBrowserZoomSteps[targetIndex], safeFitZoom);
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
        return Math.Max(float.Epsilon, safeFitZoom * MinimumFitZoomRatio);
    }

    internal static float MaximumZoom(float fitZoom)
    {
        var safeFitZoom = SafeFitZoom(fitZoom);
        return Math.Max(MinimumZoom(safeFitZoom), safeFitZoom * MaximumFitZoomRatio);
    }

    private static float Clamp(float zoom, float fitZoom)
    {
        var safeFitZoom = SafeFitZoom(fitZoom);
        var candidate = float.IsFinite(zoom) && zoom > 0.0f ? zoom : safeFitZoom;
        return Math.Clamp(candidate, MinimumZoom(safeFitZoom), MaximumZoom(safeFitZoom));
    }

    private static float SafeFitZoom(float fitZoom) =>
        float.IsFinite(fitZoom) && fitZoom > 0.0f
            ? fitZoom
            : 1.0f;
}

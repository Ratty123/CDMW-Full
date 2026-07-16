using System.Diagnostics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    public bool TryApplyHeadlessPendingUpdate(out string error)
    {
        error = string.Empty;
        if (!EnsureDeviceReady())
        {
            error = string.IsNullOrWhiteSpace(LastError) ? "D3D11 device was not ready." : LastError;
            return false;
        }
        _context?.Flush();
        return true;
    }

    public bool TryRunHeadlessFrame(out double frameMs, out double presentMs, out string error)
    {
        frameMs = 0.0;
        presentMs = 0.0;
        error = string.Empty;
        if (!EnsureDeviceReady())
        {
            error = string.IsNullOrWhiteSpace(LastError) ? "D3D11 device was not ready." : LastError;
            return false;
        }
        try
        {
            var captureActive = PreviewPerformanceCapture.IsActive;
            var allocatedBytesBefore = captureActive ? GC.GetAllocatedBytesForCurrentThread() : 0L;
            var started = Stopwatch.GetTimestamp();
            presentMs = RenderFrame();
            _context?.Flush();
            var finished = Stopwatch.GetTimestamp();
            frameMs = (finished - started) * 1000.0 / Stopwatch.Frequency;
            if (captureActive)
            {
                PreviewPerformanceCapture.RecordFrame(
                    started,
                    _lastPresentStartedTimestamp,
                    finished,
                    ResolvedGpuTimeForFrameMs,
                    allocatedBytesBefore);
                PreviewPerformanceCapture.RecordPhase(
                    PreviewPerformancePhase.Paint,
                    started,
                    finished,
                    allocatedBytesBefore);
            }
            PublishTextureRegionCompletion();
            return true;
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
            error = ex.Message;
            return false;
        }
    }
}

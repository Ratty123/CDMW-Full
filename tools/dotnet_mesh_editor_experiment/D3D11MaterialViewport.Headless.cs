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
            var started = Stopwatch.GetTimestamp();
            presentMs = RenderFrame();
            _context?.Flush();
            frameMs = (Stopwatch.GetTimestamp() - started) * 1000.0 / Stopwatch.Frequency;
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

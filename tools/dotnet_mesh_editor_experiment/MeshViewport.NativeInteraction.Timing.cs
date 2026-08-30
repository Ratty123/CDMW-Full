using System.Diagnostics;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class MeshViewport
{
    private const int ResidentNativeTimingSampleCapacity = 256;

    private readonly double[] _residentNativeInputHandlerTimingMs =
        new double[ResidentNativeTimingSampleCapacity];
    private readonly double[] _residentNativeProvisionalFeedbackTimingMs =
        new double[ResidentNativeTimingSampleCapacity];
    private int _residentNativeInputHandlerTimingCount;
    private int _residentNativeInputHandlerTimingNext;
    private int _residentNativeProvisionalFeedbackTimingCount;
    private int _residentNativeProvisionalFeedbackTimingNext;

    private static long ResidentNativeTimingTimestamp() => Stopwatch.GetTimestamp();

    private NativeMeshInteractionResult TimeResidentNativeUpdate(
        ResidentNativeGesture gesture,
        Point point)
    {
        var request = ResidentNativeGestureRequest(gesture, point, gesture.Previous);
        var session = RequireResidentNativeSession();
        var startedTimestamp = Stopwatch.GetTimestamp();
        var result = session.Update(request);
        RecordResidentNativeTiming(
            _residentNativeInputHandlerTimingMs,
            ref _residentNativeInputHandlerTimingCount,
            ref _residentNativeInputHandlerTimingNext,
            startedTimestamp);
        return result;
    }

    private void ApplyTimedResidentNativeResult(
        NativeMeshInteractionResult result,
        long startedTimestamp)
    {
        ApplyResidentNativeResult(result);
        RecordResidentNativeTiming(
            _residentNativeProvisionalFeedbackTimingMs,
            ref _residentNativeProvisionalFeedbackTimingCount,
            ref _residentNativeProvisionalFeedbackTimingNext,
            startedTimestamp);
    }

    private static void RecordResidentNativeTiming(
        double[] samples,
        ref int sampleCount,
        ref int nextSampleIndex,
        long startedTimestamp)
    {
        samples[nextSampleIndex] = Math.Max(
            0.0,
            (Stopwatch.GetTimestamp() - startedTimestamp) * 1000.0 / Stopwatch.Frequency);
        nextSampleIndex = (nextSampleIndex + 1) % ResidentNativeTimingSampleCapacity;
        sampleCount = Math.Min(sampleCount + 1, ResidentNativeTimingSampleCapacity);
    }

    private Dictionary<string, object?> ResidentNativeInputHandlerTimingDiagnostics() =>
        ResidentNativeTimingDiagnostics(
            _residentNativeInputHandlerTimingMs,
            _residentNativeInputHandlerTimingCount);

    private Dictionary<string, object?> ResidentNativeProvisionalFeedbackTimingDiagnostics() =>
        ResidentNativeTimingDiagnostics(
            _residentNativeProvisionalFeedbackTimingMs,
            _residentNativeProvisionalFeedbackTimingCount);

    private static Dictionary<string, object?> ResidentNativeTimingDiagnostics(
        double[] samples,
        int sampleCount)
    {
        if (sampleCount == 0)
        {
            return new Dictionary<string, object?>
            {
                ["count"] = 0,
                ["average_ms"] = 0.0,
                ["p95_ms"] = 0.0,
                ["max_ms"] = 0.0,
            };
        }
        var ordered = new double[sampleCount];
        Array.Copy(samples, ordered, sampleCount);
        Array.Sort(ordered);
        var p95Index = Math.Clamp(
            (int)Math.Ceiling(ordered.Length * 0.95) - 1,
            0,
            ordered.Length - 1);
        return new Dictionary<string, object?>
        {
            ["count"] = ordered.Length,
            ["average_ms"] = ordered.Average(),
            ["p95_ms"] = ordered[p95Index],
            ["max_ms"] = ordered[^1],
        };
    }
}

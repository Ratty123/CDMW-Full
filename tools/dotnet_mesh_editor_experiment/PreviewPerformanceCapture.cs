using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;

namespace Cdmw.MeshEditorExperiment;

internal enum PreviewPerformancePhase : byte
{
    ProtocolReceive = 1,
    ProtocolParse = 2,
    ProtocolApply = 3,
    Invalidation = 4,
    Paint = 5,
    OpaquePass = 6,
    TransparentPass = 7,
    OverlayPass = 8,
    Present = 9,
    Acknowledgement = 10,
    TextureUpload = 11,
    TopologyPrepare = 12,
    TopologyCommit = 13,
    VertexPrepare = 14,
    VertexCommit = 15,
    SyntheticDriver = 16,
}

internal enum PreviewPerformanceInputKind : byte
{
    Physical = 1,
    Protocol = 2,
    Synthetic = 3,
}

internal enum PreviewPerformanceHeartbeatKind : byte
{
    WinForms = 1,
    QtHost = 2,
}

internal readonly record struct PreviewPerformanceFrameSample(
    long Ordinal,
    double TimestampMs,
    double IntervalMs,
    double RenderMs,
    double PresentMs,
    double GpuMs,
    double InputToPresentMs,
    long ManagedAllocatedBytes,
    int ProtocolQueueDepth,
    long InputSequence,
    long InputCorrelation);

internal readonly record struct PreviewPerformancePhaseSample(
    PreviewPerformancePhase Phase,
    long Correlation,
    int ManagedThreadId,
    double TimestampMs,
    double DurationMs,
    long ManagedAllocatedBytes);

internal readonly record struct PreviewPerformanceHeartbeatSample(
    PreviewPerformanceHeartbeatKind Kind,
    double TimestampMs,
    double GapMs);

internal sealed record PreviewPerformanceCaptureOptions(
    string CaptureId,
    string Source,
    string ReportPath,
    double DurationSeconds,
    double TargetHz,
    int WarmupFrames,
    int Width,
    int Height,
    IReadOnlyDictionary<string, object?> AssetProvenance);

internal sealed record PreviewPerformanceCaptureSnapshot(
    PreviewPerformanceCaptureOptions Options,
    DateTime StartedAtUtc,
    DateTime StoppedAtUtc,
    double ElapsedSeconds,
    PreviewPerformanceFrameSample[] Frames,
    PreviewPerformancePhaseSample[] Phases,
    PreviewPerformanceHeartbeatSample[] Heartbeats,
    long DroppedFrameSamples,
    long DroppedPhaseSamples,
    long DroppedHeartbeatSamples,
    long InputsReceived,
    long InputsPresented,
    long InputsCoalesced,
    int MaximumProtocolQueueDepth,
    int MaximumOrderedProtocolQueueDepth,
    int MaximumProtocolOutputQueueDepth,
    long ProtocolInputUpdatesCoalesced,
    long ProtocolTelemetryCoalesced,
    long ProtocolCriticalWritten,
    long ProtocolTelemetryWritten,
    long ProtocolWriteFailures,
    long TotalAllocatedBytesStart,
    long TotalAllocatedBytesStop,
    int[] GcCountsStart,
    int[] GcCountsStop,
    double GcPauseMsStart,
    double GcPauseMsStop,
    long WorkingSetBytesStart,
    long WorkingSetBytesStop,
    long PeakWorkingSetBytes,
    long PreallocatedStorageBytes);

internal static class PreviewPerformanceCapture
{
    private static PreviewPerformanceCaptureSession? _active;

    public static bool IsActive => Volatile.Read(ref _active) is not null;

    public static bool TryStart(
        PreviewPerformanceCaptureOptions options,
        out PreviewPerformanceCaptureSession? session,
        out string error)
    {
        var candidate = new PreviewPerformanceCaptureSession(options);
        if (Interlocked.CompareExchange(ref _active, candidate, null) is not null)
        {
            candidate.DisposeWithoutSnapshot();
            session = null;
            error = "A performance capture is already active.";
            return false;
        }
        session = candidate;
        error = string.Empty;
        return true;
    }

    public static PreviewPerformanceCaptureSnapshot? Stop(string captureId, out string error)
    {
        var session = Volatile.Read(ref _active);
        if (session is null)
        {
            error = "No performance capture is active.";
            return null;
        }
        if (!string.IsNullOrWhiteSpace(captureId)
            && !string.Equals(captureId, session.Options.CaptureId, StringComparison.Ordinal))
        {
            error = "Performance capture id does not match the active capture.";
            return null;
        }
        if (Interlocked.CompareExchange(ref _active, null, session) != session)
        {
            error = "Performance capture changed while it was being stopped.";
            return null;
        }
        error = string.Empty;
        return session.StopAndSnapshot();
    }

    public static PreviewPerformanceCaptureSnapshot? StopActive()
    {
        var session = Interlocked.Exchange(ref _active, null);
        return session?.StopAndSnapshot();
    }

    public static void RecordInput(PreviewPerformanceInputKind kind, long correlation = 0)
    {
        Volatile.Read(ref _active)?.RecordInput(kind, correlation, Stopwatch.GetTimestamp());
    }

    public static void RecordInputAtTimestamp(
        PreviewPerformanceInputKind kind,
        long correlation,
        long receivedTimestamp)
    {
        Volatile.Read(ref _active)?.RecordInput(kind, correlation, receivedTimestamp);
    }

    public static void RecordPhase(
        PreviewPerformancePhase phase,
        long startedTimestamp,
        long finishedTimestamp,
        long allocatedBytesBefore,
        long correlation = 0)
    {
        Volatile.Read(ref _active)?.RecordPhase(
            phase,
            startedTimestamp,
            finishedTimestamp,
            allocatedBytesBefore,
            correlation);
    }

    public static void RecordFrame(
        long frameStartedTimestamp,
        long presentStartedTimestamp,
        long frameFinishedTimestamp,
        double gpuMs,
        long allocatedBytesBefore)
    {
        Volatile.Read(ref _active)?.RecordFrame(
            frameStartedTimestamp,
            presentStartedTimestamp,
            frameFinishedTimestamp,
            gpuMs,
            allocatedBytesBefore);
    }

    public static long NextFrameOrdinal => Volatile.Read(ref _active)?.NextFrameOrdinal ?? 0L;

    public static void RecordGpuTime(long frameOrdinal, double gpuMs)
    {
        Volatile.Read(ref _active)?.RecordGpuTime(frameOrdinal, gpuMs);
    }

    public static void RecordHeartbeat(PreviewPerformanceHeartbeatKind kind)
    {
        Volatile.Read(ref _active)?.RecordHeartbeat(kind);
    }

    public static void UpdateProtocolWriterCounters(
        int queueDepth,
        long telemetryCoalesced,
        long criticalWritten,
        long telemetryWritten,
        long writeFailures)
    {
        Volatile.Read(ref _active)?.UpdateProtocolWriterCounters(
            queueDepth,
            telemetryCoalesced,
            criticalWritten,
            telemetryWritten,
            writeFailures);
    }

    public static void RecordProtocolInputQueueDepth(int queueDepth)
    {
        Volatile.Read(ref _active)?.RecordProtocolInputQueueDepth(queueDepth);
    }

    public static void RecordOrderedProtocolInputQueueDepth(int queueDepth)
    {
        Volatile.Read(ref _active)?.RecordOrderedProtocolInputQueueDepth(queueDepth);
    }

    public static void RecordProtocolInputCoalesced()
    {
        Volatile.Read(ref _active)?.RecordProtocolInputCoalesced();
    }

    public static void SampleWorkingSet()
    {
        Volatile.Read(ref _active)?.SampleWorkingSet();
    }
}

internal sealed class PreviewPerformanceCaptureSession
{
    private readonly PreviewPerformanceFrameSample[] _frames;
    private readonly PreviewPerformancePhaseSample[] _phases;
    private readonly PreviewPerformanceHeartbeatSample[] _heartbeats;
    private readonly long _startedTimestamp;
    private readonly long _totalAllocatedBytesStart;
    private readonly int[] _gcCountsStart;
    private readonly double _gcPauseMsStart;
    private readonly long _workingSetBytesStart;
    private readonly long _preallocatedStorageBytes;
    private readonly object _inputSync = new();
    private int _active = 1;
    private int _frameWriteIndex = -1;
    private int _phaseWriteIndex = -1;
    private int _heartbeatWriteIndex = -1;
    private long _lastFrameTimestamp;
    private long _lastWinFormsHeartbeatTimestamp;
    private long _lastQtHeartbeatTimestamp;
    private long _latestInputTimestamp;
    private long _latestInputSequence;
    private long _latestInputCorrelation;
    private long _consumedInputSequence;
    private long _inputsPresented;
    private long _inputsCoalesced;
    private long _droppedFrameSamples;
    private long _droppedPhaseSamples;
    private long _droppedHeartbeatSamples;
    private int _maximumProtocolQueueDepth;
    private int _maximumOrderedProtocolQueueDepth;
    private int _maximumProtocolOutputQueueDepth;
    private long _protocolInputUpdatesCoalesced;
    private long _protocolTelemetryCoalesced;
    private long _protocolCriticalWritten;
    private long _protocolTelemetryWritten;
    private long _protocolWriteFailures;
    private long _peakWorkingSetBytes;

    public PreviewPerformanceCaptureSession(PreviewPerformanceCaptureOptions options)
    {
        if (string.IsNullOrWhiteSpace(options.CaptureId))
        {
            throw new ArgumentException("Performance capture id is required.", nameof(options));
        }
        if (options.DurationSeconds <= 0.0 || options.DurationSeconds > 600.0)
        {
            throw new ArgumentOutOfRangeException(nameof(options), "Performance capture duration must be greater than zero and at most 600 seconds.");
        }
        if (options.TargetHz < 30.0 || options.TargetHz > 360.0)
        {
            throw new ArgumentOutOfRangeException(nameof(options), "Performance capture target must be from 30 through 360 Hz.");
        }
        Options = options;
        var expectedFrames = checked((int)Math.Ceiling(options.DurationSeconds * options.TargetHz));
        var frameCapacity = Math.Clamp(expectedFrames + options.WarmupFrames + Math.Max(256, expectedFrames / 2), 512, 500_000);
        _frames = new PreviewPerformanceFrameSample[frameCapacity];
        _phases = new PreviewPerformancePhaseSample[Math.Clamp(frameCapacity * 10, 4_096, 2_000_000)];
        _heartbeats = new PreviewPerformanceHeartbeatSample[Math.Clamp(frameCapacity * 2, 1_024, 1_000_000)];
        _preallocatedStorageBytes = checked(
            (long)MemoryMarshal.AsBytes(_frames.AsSpan()).Length
            + MemoryMarshal.AsBytes(_phases.AsSpan()).Length
            + MemoryMarshal.AsBytes(_heartbeats.AsSpan()).Length);
        CommitArrayPages(_frames);
        CommitArrayPages(_phases);
        CommitArrayPages(_heartbeats);
        StartedAtUtc = DateTime.UtcNow;
        _startedTimestamp = Stopwatch.GetTimestamp();
        _totalAllocatedBytesStart = GC.GetTotalAllocatedBytes(precise: false);
        _gcCountsStart = new[] { GC.CollectionCount(0), GC.CollectionCount(1), GC.CollectionCount(2) };
        _gcPauseMsStart = GC.GetTotalPauseDuration().TotalMilliseconds;
        _workingSetBytesStart = CurrentWorkingSet();
        _peakWorkingSetBytes = _workingSetBytesStart;
    }

    public PreviewPerformanceCaptureOptions Options { get; }
    public DateTime StartedAtUtc { get; }
    public long NextFrameOrdinal => Volatile.Read(ref _frameWriteIndex) + 2L;

    public void RecordInput(PreviewPerformanceInputKind kind, long correlation, long receivedTimestamp)
    {
        if (Volatile.Read(ref _active) == 0)
        {
            return;
        }
        lock (_inputSync)
        {
            if (_latestInputSequence > _consumedInputSequence)
            {
                _inputsCoalesced++;
            }
            var sequence = ++_latestInputSequence;
            _latestInputTimestamp = receivedTimestamp;
            _latestInputCorrelation = correlation != 0
                ? correlation
                : ((long)kind << 56) | (sequence & 0x00FFFFFFFFFFFFFF);
        }
    }

    public void RecordPhase(
        PreviewPerformancePhase phase,
        long startedTimestamp,
        long finishedTimestamp,
        long allocatedBytesBefore,
        long correlation)
    {
        if (Volatile.Read(ref _active) == 0)
        {
            return;
        }
        var index = Interlocked.Increment(ref _phaseWriteIndex);
        if ((uint)index >= (uint)_phases.Length)
        {
            Interlocked.Increment(ref _droppedPhaseSamples);
            return;
        }
        var allocatedAfter = GC.GetAllocatedBytesForCurrentThread();
        _phases[index] = new PreviewPerformancePhaseSample(
            phase,
            correlation,
            Environment.CurrentManagedThreadId,
            ToElapsedMilliseconds(startedTimestamp),
            ToMilliseconds(Math.Max(0, finishedTimestamp - startedTimestamp)),
            Math.Max(0, allocatedAfter - allocatedBytesBefore));
    }

    public void RecordFrame(
        long frameStartedTimestamp,
        long presentStartedTimestamp,
        long frameFinishedTimestamp,
        double gpuMs,
        long allocatedBytesBefore)
    {
        if (Volatile.Read(ref _active) == 0)
        {
            return;
        }
        var index = Interlocked.Increment(ref _frameWriteIndex);
        if ((uint)index >= (uint)_frames.Length)
        {
            Interlocked.Increment(ref _droppedFrameSamples);
            return;
        }
        var previousFrame = Interlocked.Exchange(ref _lastFrameTimestamp, frameFinishedTimestamp);
        long inputSequence;
        long inputTimestamp;
        long inputCorrelation;
        var inputToPresentMs = double.NaN;
        lock (_inputSync)
        {
            inputSequence = _latestInputSequence;
            inputTimestamp = _latestInputTimestamp;
            inputCorrelation = _latestInputCorrelation;
            if (inputSequence > 0 && inputSequence != _consumedInputSequence)
            {
                _consumedInputSequence = inputSequence;
                _inputsPresented++;
                inputToPresentMs = ToMilliseconds(Math.Max(0, frameFinishedTimestamp - inputTimestamp));
            }
        }
        _frames[index] = new PreviewPerformanceFrameSample(
            index + 1L,
            ToElapsedMilliseconds(frameFinishedTimestamp),
            previousFrame > 0 ? ToMilliseconds(Math.Max(0, frameFinishedTimestamp - previousFrame)) : double.NaN,
            ToMilliseconds(Math.Max(0, presentStartedTimestamp - frameStartedTimestamp)),
            ToMilliseconds(Math.Max(0, frameFinishedTimestamp - presentStartedTimestamp)),
            gpuMs,
            inputToPresentMs,
            Math.Max(0, GC.GetAllocatedBytesForCurrentThread() - allocatedBytesBefore),
            Volatile.Read(ref _maximumProtocolQueueDepth),
            inputSequence,
            inputCorrelation);
    }

    public void RecordHeartbeat(PreviewPerformanceHeartbeatKind kind)
    {
        if (Volatile.Read(ref _active) == 0)
        {
            return;
        }
        var now = Stopwatch.GetTimestamp();
        ref var previous = ref kind == PreviewPerformanceHeartbeatKind.WinForms
            ? ref _lastWinFormsHeartbeatTimestamp
            : ref _lastQtHeartbeatTimestamp;
        var prior = Interlocked.Exchange(ref previous, now);
        if (prior <= 0)
        {
            return;
        }
        var index = Interlocked.Increment(ref _heartbeatWriteIndex);
        if ((uint)index >= (uint)_heartbeats.Length)
        {
            Interlocked.Increment(ref _droppedHeartbeatSamples);
            return;
        }
        _heartbeats[index] = new PreviewPerformanceHeartbeatSample(
            kind,
            ToElapsedMilliseconds(now),
            ToMilliseconds(Math.Max(0, now - prior)));
    }

    public void RecordGpuTime(long frameOrdinal, double gpuMs)
    {
        if (Volatile.Read(ref _active) == 0 || frameOrdinal <= 0 || !double.IsFinite(gpuMs))
        {
            return;
        }
        var index = checked((int)(frameOrdinal - 1));
        if ((uint)index > (uint)Volatile.Read(ref _frameWriteIndex)
            || (uint)index >= (uint)_frames.Length)
        {
            return;
        }
        _frames[index] = _frames[index] with { GpuMs = gpuMs };
    }

    public void UpdateProtocolWriterCounters(
        int queueDepth,
        long telemetryCoalesced,
        long criticalWritten,
        long telemetryWritten,
        long writeFailures)
    {
        InterlockedMax(ref _maximumProtocolOutputQueueDepth, queueDepth);
        Volatile.Write(ref _protocolTelemetryCoalesced, telemetryCoalesced);
        Volatile.Write(ref _protocolCriticalWritten, criticalWritten);
        Volatile.Write(ref _protocolTelemetryWritten, telemetryWritten);
        Volatile.Write(ref _protocolWriteFailures, writeFailures);
    }

    public void RecordProtocolInputQueueDepth(int queueDepth)
    {
        InterlockedMax(ref _maximumProtocolQueueDepth, queueDepth);
    }

    public void RecordOrderedProtocolInputQueueDepth(int queueDepth)
    {
        InterlockedMax(ref _maximumOrderedProtocolQueueDepth, queueDepth);
    }

    public void RecordProtocolInputCoalesced()
    {
        Interlocked.Increment(ref _protocolInputUpdatesCoalesced);
    }

    public void SampleWorkingSet()
    {
        InterlockedMax(ref _peakWorkingSetBytes, CurrentWorkingSet());
    }

    public PreviewPerformanceCaptureSnapshot StopAndSnapshot()
    {
        Interlocked.Exchange(ref _active, 0);
        var stoppedTimestamp = Stopwatch.GetTimestamp();
        var stoppedAtUtc = DateTime.UtcNow;
        var workingSetStop = CurrentWorkingSet();
        InterlockedMax(ref _peakWorkingSetBytes, workingSetStop);
        var frameCount = Math.Clamp(Volatile.Read(ref _frameWriteIndex) + 1, 0, _frames.Length);
        var phaseCount = Math.Clamp(Volatile.Read(ref _phaseWriteIndex) + 1, 0, _phases.Length);
        var heartbeatCount = Math.Clamp(Volatile.Read(ref _heartbeatWriteIndex) + 1, 0, _heartbeats.Length);
        long inputsReceived;
        long inputsPresented;
        long inputsCoalesced;
        lock (_inputSync)
        {
            inputsReceived = _latestInputSequence;
            inputsPresented = _inputsPresented;
            inputsCoalesced = _inputsCoalesced;
        }
        var frames = new PreviewPerformanceFrameSample[frameCount];
        var phases = new PreviewPerformancePhaseSample[phaseCount];
        var heartbeats = new PreviewPerformanceHeartbeatSample[heartbeatCount];
        Array.Copy(_frames, frames, frameCount);
        Array.Copy(_phases, phases, phaseCount);
        Array.Copy(_heartbeats, heartbeats, heartbeatCount);
        return new PreviewPerformanceCaptureSnapshot(
            Options,
            StartedAtUtc,
            stoppedAtUtc,
            ToMilliseconds(stoppedTimestamp - _startedTimestamp) / 1000.0,
            frames,
            phases,
            heartbeats,
            Volatile.Read(ref _droppedFrameSamples),
            Volatile.Read(ref _droppedPhaseSamples),
            Volatile.Read(ref _droppedHeartbeatSamples),
            inputsReceived,
            inputsPresented,
            inputsCoalesced,
            Volatile.Read(ref _maximumProtocolQueueDepth),
            Volatile.Read(ref _maximumOrderedProtocolQueueDepth),
            Volatile.Read(ref _maximumProtocolOutputQueueDepth),
            Volatile.Read(ref _protocolInputUpdatesCoalesced),
            Volatile.Read(ref _protocolTelemetryCoalesced),
            Volatile.Read(ref _protocolCriticalWritten),
            Volatile.Read(ref _protocolTelemetryWritten),
            Volatile.Read(ref _protocolWriteFailures),
            _totalAllocatedBytesStart,
            GC.GetTotalAllocatedBytes(precise: false),
            _gcCountsStart,
            new[] { GC.CollectionCount(0), GC.CollectionCount(1), GC.CollectionCount(2) },
            _gcPauseMsStart,
            GC.GetTotalPauseDuration().TotalMilliseconds,
            _workingSetBytesStart,
            workingSetStop,
            Volatile.Read(ref _peakWorkingSetBytes),
            _preallocatedStorageBytes);
    }

    public void DisposeWithoutSnapshot()
    {
        Interlocked.Exchange(ref _active, 0);
    }

    private double ToElapsedMilliseconds(long timestamp) => ToMilliseconds(timestamp - _startedTimestamp);

    private static double ToMilliseconds(long ticks) => ticks * 1000.0 / Stopwatch.Frequency;

    private static long CurrentWorkingSet() => Environment.WorkingSet;

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void CommitArrayPages<T>(T[] values) where T : struct
    {
        var bytes = MemoryMarshal.AsBytes(values.AsSpan());
        var pageSize = Math.Max(1, Environment.SystemPageSize);
        for (var offset = 0; offset < bytes.Length; offset += pageSize)
        {
            Volatile.Write(ref bytes[offset], (byte)0);
        }
        if (bytes.Length > 0)
        {
            Volatile.Write(ref bytes[^1], (byte)0);
        }
    }

    private static void InterlockedMax(ref int target, int candidate)
    {
        var current = Volatile.Read(ref target);
        while (candidate > current)
        {
            var observed = Interlocked.CompareExchange(ref target, candidate, current);
            if (observed == current)
            {
                return;
            }
            current = observed;
        }
    }

    private static void InterlockedMax(ref long target, long candidate)
    {
        var current = Volatile.Read(ref target);
        while (candidate > current)
        {
            var observed = Interlocked.CompareExchange(ref target, candidate, current);
            if (observed == current)
            {
                return;
            }
            current = observed;
        }
    }
}

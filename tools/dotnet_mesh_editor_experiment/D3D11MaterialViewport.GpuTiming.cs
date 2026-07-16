using Vortice.Direct3D11;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class D3D11MaterialViewport
{
    private const int GpuTimingQuerySlotCount = 8;
    private readonly D3D11GpuTimingQuerySet[] _gpuTimingQuerySets = new D3D11GpuTimingQuerySet[GpuTimingQuerySlotCount];
    private int _gpuTimingWriteIndex;
    private int _gpuTimingReadIndex;
    private int _activeGpuTimingQueryIndex = -1;
    private double _resolvedGpuTimeForFrameMs = double.NaN;
    private long _gpuTimingQueryIssuedCount;
    private long _gpuTimingQueryResolvedCount;
    private long _gpuTimingQueryDisjointCount;
    private long _gpuTimingQueryDroppedCount;

    private double ResolvedGpuTimeForFrameMs => _resolvedGpuTimeForFrameMs;

    public void PreparePerformanceCapture() => CreateGpuTimingQueries();

    private void CreateGpuTimingQueries()
    {
        DisposeGpuTimingQueries();
        if (_device is null)
        {
            return;
        }
        try
        {
            for (var index = 0; index < _gpuTimingQuerySets.Length; index++)
            {
                _gpuTimingQuerySets[index] = new D3D11GpuTimingQuerySet(
                    _device.CreateQuery(QueryType.TimestampDisjoint),
                    _device.CreateQuery(QueryType.Timestamp),
                    _device.CreateQuery(QueryType.Timestamp));
            }
        }
        catch
        {
            DisposeGpuTimingQueries();
        }
    }

    private void BeginGpuTimingFrame(bool enabled)
    {
        _resolvedGpuTimeForFrameMs = double.NaN;
        _activeGpuTimingQueryIndex = -1;
        if (!enabled || _context is null || _gpuTimingQuerySets[0].Disjoint is null)
        {
            return;
        }
        TryResolveGpuTimingQuery();
        ref var querySet = ref _gpuTimingQuerySets[_gpuTimingWriteIndex];
        if (querySet.Pending)
        {
            _gpuTimingQueryDroppedCount++;
            return;
        }
        _context.Begin(querySet.Disjoint);
        _context.End(querySet.Start);
        querySet.PerformanceFrameOrdinal = PreviewPerformanceCapture.NextFrameOrdinal;
        _activeGpuTimingQueryIndex = _gpuTimingWriteIndex;
    }

    private void EndGpuTimingFrame()
    {
        if (_activeGpuTimingQueryIndex < 0 || _context is null)
        {
            return;
        }
        ref var querySet = ref _gpuTimingQuerySets[_activeGpuTimingQueryIndex];
        _context.End(querySet.End);
        _context.End(querySet.Disjoint);
        querySet.Pending = true;
        _gpuTimingQueryIssuedCount++;
        _gpuTimingWriteIndex = (_activeGpuTimingQueryIndex + 1) % _gpuTimingQuerySets.Length;
        _activeGpuTimingQueryIndex = -1;
    }

    private void TryResolveGpuTimingQuery()
    {
        if (_context is null)
        {
            return;
        }
        ref var querySet = ref _gpuTimingQuerySets[_gpuTimingReadIndex];
        var disjointQuery = querySet.Disjoint;
        var startQuery = querySet.Start;
        var endQuery = querySet.End;
        if (!querySet.Pending
            || disjointQuery is null
            || startQuery is null
            || endQuery is null
            || !_context.GetData(disjointQuery, AsyncGetDataFlags.DoNotFlush, out QueryDataTimestampDisjoint disjoint)
            || !_context.GetData(startQuery, AsyncGetDataFlags.DoNotFlush, out ulong start)
            || !_context.GetData(endQuery, AsyncGetDataFlags.DoNotFlush, out ulong end))
        {
            return;
        }
        querySet.Pending = false;
        _gpuTimingReadIndex = (_gpuTimingReadIndex + 1) % _gpuTimingQuerySets.Length;
        _gpuTimingQueryResolvedCount++;
        if (disjoint.Disjoint || disjoint.Frequency == 0 || end < start)
        {
            _gpuTimingQueryDisjointCount++;
            return;
        }
        var gpuMs = (end - start) * 1000.0 / disjoint.Frequency;
        PreviewPerformanceCapture.RecordGpuTime(querySet.PerformanceFrameOrdinal, gpuMs);
        _resolvedGpuTimeForFrameMs = double.NaN;
    }

    private void DisposeGpuTimingQueries()
    {
        for (var index = 0; index < _gpuTimingQuerySets.Length; index++)
        {
            ref var querySet = ref _gpuTimingQuerySets[index];
            querySet.End?.Dispose();
            querySet.Start?.Dispose();
            querySet.Disjoint?.Dispose();
            querySet = default;
        }
        _gpuTimingWriteIndex = 0;
        _gpuTimingReadIndex = 0;
        _activeGpuTimingQueryIndex = -1;
        _resolvedGpuTimeForFrameMs = double.NaN;
    }
}

internal struct D3D11GpuTimingQuerySet
{
    public D3D11GpuTimingQuerySet(ID3D11Query disjoint, ID3D11Query start, ID3D11Query end)
    {
        Disjoint = disjoint;
        Start = start;
        End = end;
        Pending = false;
        PerformanceFrameOrdinal = 0L;
    }

    public ID3D11Query? Disjoint;
    public ID3D11Query? Start;
    public ID3D11Query? End;
    public bool Pending;
    public long PerformanceFrameOrdinal;
}

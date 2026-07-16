using System.Collections.Concurrent;
using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed class ProtocolOutputWriter
{
    private const int MaximumCriticalBacklog = 4096;
    private readonly ConcurrentQueue<IReadOnlyDictionary<string, object?>> _critical = new();
    private readonly SemaphoreSlim _available = new(0);
    private readonly object _stateLock = new();
    private readonly Task _writerTask;
    private IReadOnlyDictionary<string, object?>? _latestTelemetry;
    private int _criticalCount;
    private int _stopping;
    private long _telemetryCoalesced;
    private long _criticalWritten;
    private long _telemetryWritten;
    private long _writeFailures;

    public ProtocolOutputWriter()
    {
        _writerTask = Task.Run(WriterLoopAsync);
    }

    public void EnqueueCritical(IReadOnlyDictionary<string, object?> message)
    {
        lock (_stateLock)
        {
            if (_stopping != 0)
            {
                throw new InvalidOperationException("Protocol output is stopping; a critical event cannot be accepted.");
            }
            if (_criticalCount >= MaximumCriticalBacklog)
            {
                Interlocked.Increment(ref _writeFailures);
                throw new InvalidOperationException($"Critical protocol output exceeded its bounded {MaximumCriticalBacklog}-message backlog.");
            }
            _critical.Enqueue(message);
            _criticalCount++;
        }
        _available.Release();
        PublishCounters();
    }

    public void EnqueueLatestTelemetry(IReadOnlyDictionary<string, object?> message)
    {
        lock (_stateLock)
        {
            if (_stopping != 0)
            {
                return;
            }
            if (_latestTelemetry is not null)
            {
                Interlocked.Increment(ref _telemetryCoalesced);
            }
            _latestTelemetry = message;
        }
        _available.Release();
        PublishCounters();
    }

    public void RequestStop()
    {
        var release = false;
        lock (_stateLock)
        {
            if (_stopping == 0)
            {
                _stopping = 1;
                release = true;
            }
        }
        if (release)
        {
            _available.Release();
        }
    }

    public bool WaitForDrain(TimeSpan grace)
    {
        RequestStop();
        try
        {
            return _writerTask.Wait(grace);
        }
        catch (AggregateException)
        {
            return false;
        }
    }

    private async Task WriterLoopAsync()
    {
        while (true)
        {
            await _available.WaitAsync().ConfigureAwait(false);
            var wrote = false;
            while (_critical.TryDequeue(out var critical))
            {
                lock (_stateLock)
                {
                    _criticalCount--;
                }
                wrote |= await TryWriteAsync(critical, telemetry: false).ConfigureAwait(false);
            }
            IReadOnlyDictionary<string, object?>? telemetry;
            lock (_stateLock)
            {
                telemetry = _latestTelemetry;
                _latestTelemetry = null;
            }
            if (telemetry is not null)
            {
                wrote |= await TryWriteAsync(telemetry, telemetry: true).ConfigureAwait(false);
            }
            if (wrote)
            {
                try
                {
                    await Console.Out.FlushAsync().ConfigureAwait(false);
                }
                catch (IOException)
                {
                    Interlocked.Increment(ref _writeFailures);
                }
            }
            PublishCounters();
            lock (_stateLock)
            {
                if (_stopping != 0
                    && _criticalCount == 0
                    && _latestTelemetry is null)
                {
                    return;
                }
            }
        }
    }

    private async Task<bool> TryWriteAsync(IReadOnlyDictionary<string, object?> message, bool telemetry)
    {
        try
        {
            var json = JsonSerializer.Serialize(message);
            await Console.Out.WriteLineAsync(json).ConfigureAwait(false);
            if (telemetry)
            {
                Interlocked.Increment(ref _telemetryWritten);
            }
            else
            {
                Interlocked.Increment(ref _criticalWritten);
            }
            return true;
        }
        catch (Exception ex) when (ex is IOException or ObjectDisposedException or NotSupportedException)
        {
            Interlocked.Increment(ref _writeFailures);
            return false;
        }
    }

    private bool HasTelemetry()
    {
        lock (_stateLock)
        {
            return _latestTelemetry is not null;
        }
    }

    private void PublishCounters()
    {
        var telemetryDepth = HasTelemetry() ? 1 : 0;
        PreviewPerformanceCapture.UpdateProtocolWriterCounters(
            Volatile.Read(ref _criticalCount) + telemetryDepth,
            Volatile.Read(ref _telemetryCoalesced),
            Volatile.Read(ref _criticalWritten),
            Volatile.Read(ref _telemetryWritten),
            Volatile.Read(ref _writeFailures));
    }
}

using System.Collections.Concurrent;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveSessionManager : IDisposable
{
    private readonly NativeArchiveCore _native;
    private readonly ArchiveCacheStore _cache;
    private readonly ConcurrentDictionary<string, ArchiveSession> _sessions = new(StringComparer.Ordinal);
    private int _disposed;

    public ArchiveSessionManager(NativeArchiveCore native, ArchiveCacheStore cache)
    {
        _native = native;
        _cache = cache;
    }

    public Task<ArchiveSessionHandle> OpenAsync(
        OpenArchiveRequest request,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null) =>
        OpenCoreAsync(request, forceRefresh: request.ForceRefresh, cancellationToken, progress);

    public Task<ArchiveSessionHandle> RefreshAsync(
        OpenArchiveRequest request,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null) =>
        OpenCoreAsync(request, forceRefresh: true, cancellationToken, progress);

    private async Task<ArchiveSessionHandle> OpenCoreAsync(
        OpenArchiveRequest request,
        bool forceRefresh,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
        ArgumentNullException.ThrowIfNull(request);
        var generation = await _cache.OpenAsync(
            request.PackageRoot,
            forceRefresh,
            _native,
            cancellationToken,
            progress).ConfigureAwait(false);
        var sessionId = Guid.NewGuid().ToString("N");
        var session = new ArchiveSession(sessionId, generation);
        if (!_sessions.TryAdd(sessionId, session))
        {
            session.Dispose();
            throw new InvalidOperationException("Could not register the archive session.");
        }
        return session.Handle;
    }

    public ArchiveSession GetRequired(string sessionId)
    {
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
        if (string.IsNullOrWhiteSpace(sessionId) || !_sessions.TryGetValue(sessionId, out var session))
        {
            throw new KeyNotFoundException("Archive session is not open or has expired.");
        }
        return session;
    }

    public bool Close(string sessionId)
    {
        if (!_sessions.TryRemove(sessionId, out var session))
        {
            return false;
        }
        session.Dispose();
        return true;
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }
        foreach (var session in _sessions.Values)
        {
            session.Dispose();
        }
        _sessions.Clear();
    }
}

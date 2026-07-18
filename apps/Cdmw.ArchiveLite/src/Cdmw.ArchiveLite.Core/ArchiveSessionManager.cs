using System.Collections.Concurrent;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveSessionManager : IDisposable
{
    private readonly NativeArchiveCore _native;
    private readonly ConcurrentDictionary<string, ArchiveSession> _sessions = new(StringComparer.Ordinal);
    private int _disposed;

    public ArchiveSessionManager(NativeArchiveCore native)
    {
        _native = native;
    }

    public async Task<OpenArchiveResult> OpenAsync(OpenArchiveRequest request, CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
        ArgumentNullException.ThrowIfNull(request);
        var root = Path.GetFullPath(request.PackageRoot);
        var fingerprint = await ArchiveFingerprint.ComputeAsync(root, cancellationToken).ConfigureAwait(false);
        ArchiveLiteDataPaths.EnsureCreated();
        var indexPath = Path.Combine(ArchiveLiteDataPaths.IndexCache, $"{fingerprint.Value}.ali");
        var usedCache = !request.ForceRefresh && File.Exists(indexPath);
        ArchiveIndex? index = null;
        if (usedCache)
        {
            try
            {
                index = ArchiveIndex.Open(indexPath);
            }
            catch (InvalidDataException)
            {
                usedCache = false;
            }
            catch (IOException)
            {
                usedCache = false;
            }
        }

        if (index is null)
        {
            cancellationToken.ThrowIfCancellationRequested();
            await Task.Run(() => _native.BuildIndex(root, indexPath), cancellationToken).ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();
            index = ArchiveIndex.Open(indexPath);
        }

        var sessionId = Guid.NewGuid().ToString("N");
        var session = new ArchiveSession(sessionId, root, fingerprint.Value, index, fingerprint.SourceFiles);
        if (!_sessions.TryAdd(sessionId, session))
        {
            session.Dispose();
            throw new InvalidOperationException("Could not register the archive session.");
        }

        var warnings = new List<string>();
        var missingPaz = 0;
        for (long entryId = 0; entryId < index.EntryCount && missingPaz < 20; entryId++)
        {
            if (!File.Exists(index.ReadEntry(entryId).PazFile)) missingPaz++;
        }
        if (missingPaz > 0) warnings.Add($"At least {missingPaz} indexed entries reference missing PAZ files.");
        return new OpenArchiveResult(sessionId, root, fingerprint.Value, index.EntryCount, ArchiveIndex.Version, usedCache, warnings);
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

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
        foreach (var session in _sessions.Values) session.Dispose();
        _sessions.Clear();
    }
}

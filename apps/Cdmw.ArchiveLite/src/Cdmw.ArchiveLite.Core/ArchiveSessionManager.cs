using System.Collections.Concurrent;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveSessionManager : IDisposable
{
    private readonly NativeArchiveCore _native;
    private readonly ConcurrentDictionary<string, ArchiveSession> _sessions = new(StringComparer.Ordinal);
    private readonly SemaphoreSlim _openGate = new(1, 1);
    private int _disposed;

    public ArchiveSessionManager(NativeArchiveCore native)
    {
        _native = native;
    }

    public async Task<OpenArchiveResult> OpenAsync(
        OpenArchiveRequest request,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
        ArgumentNullException.ThrowIfNull(request);
        if (!Enum.IsDefined(request.CacheMode))
        {
            throw new ArgumentOutOfRangeException(nameof(request), "The archive cache mode is not supported.");
        }

        await _openGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            return await OpenCoreAsync(request, cancellationToken, progress).ConfigureAwait(false);
        }
        finally
        {
            _openGate.Release();
        }
    }

    private async Task<OpenArchiveResult> OpenCoreAsync(
        OpenArchiveRequest request,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        var root = Path.GetFullPath(request.PackageRoot);
        await PublishProgressAsync(progress, new ProgressUpdate(0, 0, "discover", root)).ConfigureAwait(false);
        var fingerprint = await ArchiveFingerprint.ComputeAsync(root, cancellationToken, progress).ConfigureAwait(false);
        var persistent = request.CacheMode == ArchiveCacheMode.Persistent;
        var indexPath = persistent
            ? ResolvePersistentIndexPath(fingerprint.Value)
            : ArchiveLiteDataPaths.CreateSessionIndexPath();
        var usedCache = persistent && !request.ForceRefresh && File.Exists(indexPath);
        var ownedIndexPath = persistent ? null : indexPath;
        string? stagingPath = null;
        ArchiveIndex? index = null;
        try
        {
            await PublishProgressAsync(
                progress,
                new ProgressUpdate(0, 0, usedCache ? "index_cache" : "index_build", Path.GetFileName(indexPath))).ConfigureAwait(false);
            if (usedCache)
            {
                try
                {
                    index = ArchiveIndex.Open(indexPath);
                }
                catch (Exception exception) when (exception is InvalidDataException or IOException)
                {
                    usedCache = false;
                }
            }

            if (index is null)
            {
                if (persistent && !request.ForceRefresh && !request.AllowCacheBuild)
                {
                    throw new ArchiveCacheRefreshRequiredException(
                        "The saved archive cache no longer matches the current game files. Refresh is required before opening it.");
                }
                cancellationToken.ThrowIfCancellationRequested();
                await PublishProgressAsync(progress, new ProgressUpdate(0, 0, "index_build", root)).ConfigureAwait(false);
                var buildPath = persistent
                    ? stagingPath = Path.Combine(
                        ArchiveLiteDataPaths.IndexCache,
                        $".{fingerprint.Value}.{Guid.NewGuid():N}.tmp")
                    : indexPath;
                await Task.Run(() => _native.BuildIndex(root, buildPath), cancellationToken).ConfigureAwait(false);
                cancellationToken.ThrowIfCancellationRequested();

                if (persistent)
                {
                    using (ArchiveIndex.Open(buildPath))
                    {
                        // Validate the complete native index before replacing a reusable cache.
                    }
                    cancellationToken.ThrowIfCancellationRequested();
                    File.Move(buildPath, indexPath, overwrite: true);
                    stagingPath = null;
                }
                index = ArchiveIndex.Open(indexPath);
            }

            var warnings = await ValidatePazReferencesAsync(index, progress, cancellationToken).ConfigureAwait(false);
            if (persistent)
            {
                try
                {
                    await ArchiveCacheHealthService.PublishCurrentAsync(
                        root,
                        fingerprint,
                        index.EntryCount,
                        cancellationToken).ConfigureAwait(false);
                }
                catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
                {
                    warnings.Add($"Archive cache freshness metadata could not be updated: {exception.Message}");
                }
            }
            await PublishProgressAsync(progress, new ProgressUpdate(1, 1, "complete", root)).ConfigureAwait(false);

            var sessionId = Guid.NewGuid().ToString("N");
            var session = new ArchiveSession(
                sessionId,
                root,
                fingerprint.Value,
                index,
                fingerprint.SourceFiles,
                ownedIndexPath);
            index = null;
            ownedIndexPath = null;
            if (!_sessions.TryAdd(sessionId, session))
            {
                session.Dispose();
                throw new InvalidOperationException("Could not register the archive session.");
            }
            return new OpenArchiveResult(
                sessionId,
                root,
                fingerprint.Value,
                session.Index.EntryCount,
                ArchiveIndex.Version,
                usedCache,
                warnings,
                request.CacheMode);
        }
        finally
        {
            index?.Dispose();
            TryDeleteFile(stagingPath);
            TryDeleteFile(ownedIndexPath);
        }
    }

    private static string ResolvePersistentIndexPath(string fingerprint)
    {
        ArchiveLiteDataPaths.EnsureCreated();
        return Path.Combine(ArchiveLiteDataPaths.IndexCache, $"{fingerprint}.ali");
    }

    private static void TryDeleteFile(string? path)
    {
        if (path is null)
        {
            return;
        }
        try
        {
            File.Delete(path);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // A later cache prune or OS temp cleanup can remove an abandoned build file.
        }
    }

    private static async Task<List<string>> ValidatePazReferencesAsync(
        ArchiveIndex index,
        Func<ProgressUpdate, Task>? progress,
        CancellationToken cancellationToken)
    {
        const int maximumSamples = 4_096;
        var sampleCount = (int)Math.Min(maximumSamples, index.EntryCount);
        var missingPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        await PublishProgressAsync(progress, new ProgressUpdate(0, sampleCount, "validate", null)).ConfigureAwait(false);
        for (var sample = 0; sample < sampleCount; sample++)
        {
            if ((sample & 0x1FF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                await PublishProgressAsync(progress, new ProgressUpdate(sample, sampleCount, "validate", null)).ConfigureAwait(false);
            }

            var entryId = EvenlySpacedEntryId(sample, sampleCount, index.EntryCount);
            var pazFile = index.ReadEntry(entryId).PazFile;
            if (!File.Exists(pazFile) && missingPaths.Count < 20)
            {
                missingPaths.Add(pazFile);
            }
        }

        await PublishProgressAsync(progress, new ProgressUpdate(sampleCount, sampleCount, "validate", null)).ConfigureAwait(false);
        return missingPaths.Count == 0
            ? []
            : [$"The bounded archive check found {missingPaths.Count} missing PAZ file(s)."];
    }

    private static long EvenlySpacedEntryId(int sample, int sampleCount, long entryCount)
    {
        if (sampleCount <= 1 || entryCount <= 1)
        {
            return 0;
        }

        var span = entryCount - 1;
        var divisor = sampleCount - 1L;
        return (span / divisor * sample) + (span % divisor * sample / divisor);
    }

    private static Task PublishProgressAsync(
        Func<ProgressUpdate, Task>? progress,
        ProgressUpdate update) => progress is null ? Task.CompletedTask : progress(update);

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
        _openGate.Dispose();
    }
}

public sealed class ArchiveCacheRefreshRequiredException(string message) : InvalidOperationException(message);

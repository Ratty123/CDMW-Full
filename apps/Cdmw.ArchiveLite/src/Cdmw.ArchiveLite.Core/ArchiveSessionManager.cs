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

    public async Task<OpenArchiveResult> OpenAsync(
        OpenArchiveRequest request,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
        ArgumentNullException.ThrowIfNull(request);
        var root = Path.GetFullPath(request.PackageRoot);
        await PublishProgressAsync(progress, new ProgressUpdate(0, 0, "discover", root)).ConfigureAwait(false);
        var fingerprint = await ArchiveFingerprint.ComputeAsync(root, cancellationToken, progress).ConfigureAwait(false);
        ArchiveLiteDataPaths.EnsureCreated();
        var indexPath = Path.Combine(ArchiveLiteDataPaths.IndexCache, $"{fingerprint.Value}.ali");
        var usedCache = !request.ForceRefresh && File.Exists(indexPath);
        ArchiveIndex? index = null;
        await PublishProgressAsync(
            progress,
            new ProgressUpdate(0, 0, usedCache ? "index_cache" : "index_build", Path.GetFileName(indexPath))).ConfigureAwait(false);
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
            await PublishProgressAsync(progress, new ProgressUpdate(0, 0, "index_build", root)).ConfigureAwait(false);
            await Task.Run(() => _native.BuildIndex(root, indexPath), cancellationToken).ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();
            index = ArchiveIndex.Open(indexPath);
        }

        List<string> warnings;
        try
        {
            warnings = await ValidatePazReferencesAsync(index, progress, cancellationToken).ConfigureAwait(false);
            await PublishProgressAsync(progress, new ProgressUpdate(1, 1, "complete", root)).ConfigureAwait(false);
        }
        catch
        {
            index.Dispose();
            throw;
        }

        var sessionId = Guid.NewGuid().ToString("N");
        var session = new ArchiveSession(sessionId, root, fingerprint.Value, index, fingerprint.SourceFiles);
        if (!_sessions.TryAdd(sessionId, session))
        {
            session.Dispose();
            throw new InvalidOperationException("Could not register the archive session.");
        }
        return new OpenArchiveResult(sessionId, root, fingerprint.Value, index.EntryCount, ArchiveIndex.Version, usedCache, warnings);
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
    }
}

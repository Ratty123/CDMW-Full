using System.Collections.Concurrent;

namespace Cdmw.FullArchive.Core;

/// <summary>
/// Owns one generation's derived dependency index.
///
/// An already published index is opened inline, so warm opens behave exactly as
/// before. When the index has to be built, the build runs in the background and
/// the archive open returns without it: the index backs facets and basename
/// lookups, and nothing on the path to the first page of results reads it.
/// Consumers that do need it wait here, and a build that failed is retried on the
/// next access so a transient file lock cannot poison the whole session.
/// </summary>
internal sealed class ArchiveDependencyIndexHandle : IDisposable
{
    private readonly ArchiveIndex _source;
    private readonly string _path;
    private readonly CancellationTokenSource _cancellation = new();
    private readonly object _gate = new();
    private Task<ArchiveDependencyIndex> _build;
    private int _disposed;

    private ArchiveDependencyIndexHandle(ArchiveIndex source, string path, Task<ArchiveDependencyIndex> build)
    {
        _source = source;
        _path = path;
        _build = build;
    }

    public static ArchiveDependencyIndexHandle Create(ArchiveIndex source, string path)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        var published = ArchiveDependencyIndex.TryOpen(source, path);
        if (published is not null)
        {
            return new ArchiveDependencyIndexHandle(source, path, Task.FromResult(published));
        }
        var handle = new ArchiveDependencyIndexHandle(source, path, Task.FromCanceled<ArchiveDependencyIndex>(
            new CancellationToken(canceled: true)));
        lock (handle._gate)
        {
            handle.StartBuildLocked();
        }
        return handle;
    }

    /// <summary>True when the index is open, so no consumer will block on it.</summary>
    public bool IsReady
    {
        get
        {
            lock (_gate)
            {
                return _build.IsCompletedSuccessfully;
            }
        }
    }

    /// <summary>
    /// The index, waiting for a background build to finish and surfacing that
    /// build's failure to the caller that actually needed it.
    /// </summary>
    public ArchiveDependencyIndex Value => WaitAsync(CancellationToken.None).GetAwaiter().GetResult();

    public Task<ArchiveDependencyIndex> WaitAsync(CancellationToken cancellationToken)
    {
        Task<ArchiveDependencyIndex> pending;
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
            // A previous attempt that failed is discarded rather than replayed: the
            // lock or damaged file behind it may well be gone by now.
            if (_build.IsCompletedSuccessfully)
            {
                return _build;
            }
            pending = _build.IsCompleted ? StartBuildLocked() : _build;
        }
        return pending.WaitAsync(cancellationToken);
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }
        _cancellation.Cancel();
        Task<ArchiveDependencyIndex> pending;
        lock (_gate)
        {
            pending = _build;
        }
        try
        {
            // The build reads through the source index mapping, so it has to stop
            // before the generation lease closes that mapping underneath it.
            pending.GetAwaiter().GetResult();
        }
        catch
        {
            // A cancelled or failed build holds nothing that needs releasing.
        }
        if (pending.IsCompletedSuccessfully)
        {
            pending.Result.Dispose();
        }
        _cancellation.Dispose();
    }

    private Task<ArchiveDependencyIndex> StartBuildLocked()
    {
        var token = _cancellation.Token;
        _build = Task.Run(() => BuildGuardedAsync(token), CancellationToken.None);
        return _build;
    }

    /// <summary>
    /// Serialises builds of one generation's index across every session in this
    /// process. Overlapping sessions each hold their own mapping of the published
    /// file, and a second build cannot replace a file the first one has mapped.
    /// </summary>
    private async Task<ArchiveDependencyIndex> BuildGuardedAsync(CancellationToken cancellationToken)
    {
        var gate = BuildGates.GetOrAdd(_path, static _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            // Another session may have published this index while we queued.
            var published = ArchiveDependencyIndex.TryOpen(_source, _path);
            if (published is not null)
            {
                return published;
            }
            // No progress sink: the request that triggered the open has already been
            // answered, and progress written against a finished request is noise the
            // client cannot attribute to anything.
            return await ArchiveDependencyIndex
                .BuildAsync(_source, _path, null, cancellationToken)
                .ConfigureAwait(false);
        }
        finally
        {
            gate.Release();
        }
    }

    private static readonly ConcurrentDictionary<string, SemaphoreSlim> BuildGates =
        new(StringComparer.OrdinalIgnoreCase);
}

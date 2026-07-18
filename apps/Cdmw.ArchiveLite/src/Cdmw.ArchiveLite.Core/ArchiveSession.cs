using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveSession : IDisposable
{
    private readonly object _queryStateGate = new();
    private ArchiveQuerySpec? _lastQuery;
    private long _lastQueryGeneration = long.MinValue;
    private long _lastQueryTotal;
    private int _disposed;

    internal ArchiveSession(
        string id,
        string packageRoot,
        string fingerprint,
        ArchiveIndex index,
        IReadOnlyList<string> sourceFiles)
    {
        Id = id;
        PackageRoot = packageRoot;
        Fingerprint = fingerprint;
        Index = index;
        SourceFiles = sourceFiles;
    }

    public string Id { get; }
    public string PackageRoot { get; }
    public string Fingerprint { get; }
    public ArchiveIndex Index { get; }
    public IReadOnlyList<string> SourceFiles { get; }
    internal void StoreQuery(ArchiveQuerySpec query, long generation, long total)
    {
        lock (_queryStateGate)
        {
            if (generation < _lastQueryGeneration) return;
            _lastQuery = query;
            _lastQueryGeneration = generation;
            _lastQueryTotal = total;
        }
    }

    internal (ArchiveQuerySpec Query, long Total) GetLastQuery()
    {
        lock (_queryStateGate)
        {
            return (_lastQuery ?? throw new InvalidOperationException("No filtered archive query is active."), _lastQueryTotal);
        }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) == 0)
        {
            Index.Dispose();
        }
    }
}

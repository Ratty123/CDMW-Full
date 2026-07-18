using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveSession : IDisposable
{
    private readonly object _queryStateGate = new();
    private readonly object _catalogueGate = new();
    private ArchiveQuerySpec? _lastQuery;
    private long _lastQueryGeneration = long.MinValue;
    private long _lastQueryTotal;
    private ArchiveItemNameIndex? _nameIndex;
    private IReadOnlyList<ArchiveExtensionFacet>? _extensionFacets;
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
    internal SemaphoreSlim NameIndexBuildGate { get; } = new(1, 1);

    internal ArchiveEntryDto EnrichEntry(ArchiveEntryDto entry)
    {
        ArchiveItemNameIndex? index;
        lock (_catalogueGate)
        {
            index = _nameIndex;
        }
        return index?.Enrich(entry) ?? entry;
    }

    internal bool TryGetNameIndex(out ArchiveItemNameIndex? index)
    {
        lock (_catalogueGate)
        {
            index = _nameIndex;
            return index is not null;
        }
    }

    internal void SetNameIndex(ArchiveItemNameIndex index)
    {
        ArgumentNullException.ThrowIfNull(index);
        lock (_catalogueGate)
        {
            _nameIndex = index;
        }
    }

    internal bool TryGetExtensionFacets(out IReadOnlyList<ArchiveExtensionFacet>? facets)
    {
        lock (_catalogueGate)
        {
            facets = _extensionFacets;
            return facets is not null;
        }
    }

    internal void SetExtensionFacets(IReadOnlyList<ArchiveExtensionFacet> facets)
    {
        ArgumentNullException.ThrowIfNull(facets);
        lock (_catalogueGate)
        {
            _extensionFacets = facets;
        }
    }
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
            NameIndexBuildGate.Dispose();
            Index.Dispose();
        }
    }
}

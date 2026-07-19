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
    private readonly string? _ownedIndexPath;
    private readonly string? _ownedBasenameIndexPath;
    private int _disposed;

    internal ArchiveSession(
        string id,
        string packageRoot,
        string fingerprint,
        ArchiveIndex index,
        ArchiveBasenameIndex basenameIndex,
        IReadOnlyList<string> sourceFiles,
        string? ownedIndexPath = null,
        string? ownedBasenameIndexPath = null)
    {
        Id = id;
        PackageRoot = packageRoot;
        Fingerprint = fingerprint;
        Index = index;
        BasenameIndex = basenameIndex;
        SourceFiles = sourceFiles;
        _ownedIndexPath = ownedIndexPath;
        _ownedBasenameIndexPath = ownedBasenameIndexPath;
    }

    public string Id { get; }
    public string PackageRoot { get; }
    public string Fingerprint { get; }
    public ArchiveIndex Index { get; }
    internal ArchiveBasenameIndex BasenameIndex { get; }
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
            try
            {
                BasenameIndex.Dispose();
            }
            finally
            {
                try
                {
                    Index.Dispose();
                }
                finally
                {
                    DeleteOwnedIndex(_ownedBasenameIndexPath);
                    DeleteOwnedIndex(_ownedIndexPath);
                }
            }
        }
    }

    private static void DeleteOwnedIndex(string? path)
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
            // Session-only indexes are best-effort cleanup during process teardown.
        }
    }
}

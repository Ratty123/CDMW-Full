using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveSession : IDisposable
{
    private const int MaximumCompiledQueries = 4;
    private readonly object _queryGate = new();
    private readonly Dictionary<string, LinkedListNode<CompiledArchiveQuery>> _queries = new(StringComparer.Ordinal);
    private readonly LinkedList<CompiledArchiveQuery> _queryLru = new();
    private readonly ArchiveGenerationLease _generation;
    private ArchiveNameIndex? _nameIndex;
    private ArchiveItemCatalog? _itemCatalog;
    private int _disposed;

    internal ArchiveSession(string id, ArchiveGenerationLease generation)
    {
        Id = id;
        _generation = generation;
        PackageRoot = generation.Manifest.PackageRoot;
        Fingerprint = generation.Manifest.Fingerprint;
    }

    public string Id { get; }
    public string PackageRoot { get; }
    public string Fingerprint { get; }
    public string GenerationPath => _generation.GenerationPath;
    public ArchiveIndex Index => _generation.Index;
    /// <summary>
    /// Blocks until the derived dependency index is available. It is built in the
    /// background when an archive is opened cold, so the first caller that needs
    /// facets or a basename lookup may wait here; prefer
    /// <see cref="DependencyIndexAsync"/> from an async path.
    /// </summary>
    internal ArchiveDependencyIndex DependencyIndex => _generation.DependencyIndex;

    internal Task<ArchiveDependencyIndex> DependencyIndexAsync(CancellationToken cancellationToken) =>
        _generation.DependencyIndexHandle.WaitAsync(cancellationToken);
    public bool CacheHit => _generation.CacheHit;

    public ArchiveSessionHandle Handle => new(
        Id,
        PackageRoot,
        Fingerprint,
        Index.EntryCount,
        ArchiveIndex.Version,
        CacheHit,
        ArchiveDiscoveryWarnings.FromManifest(_generation.Manifest));

    public ArchiveEntryDto ReadEntry(long entryId)
    {
        var entry = Index.ReadEntry(entryId, Id);
        return Volatile.Read(ref _nameIndex)?.Enrich(entry) ?? entry;
    }

    internal void SetNameIndex(ArchiveNameIndex index) => Volatile.Write(ref _nameIndex, index);

    internal bool TryGetNameIndex(out ArchiveNameIndex? index)
    {
        index = Volatile.Read(ref _nameIndex);
        return index is not null;
    }

    internal void SetCatalogue(ArchiveNameIndex index, ArchiveItemCatalog catalog)
    {
        Volatile.Write(ref _nameIndex, index);
        Volatile.Write(ref _itemCatalog, catalog);
    }

    internal bool TryGetItemCatalog(out ArchiveItemCatalog? catalog)
    {
        catalog = Volatile.Read(ref _itemCatalog);
        return catalog is not null;
    }

    internal void StoreQuery(CompiledArchiveQuery query)
    {
        lock (_queryGate)
        {
            if (_queries.Remove(query.QueryId, out var existing))
            {
                _queryLru.Remove(existing);
            }
            var node = _queryLru.AddFirst(query);
            _queries[query.QueryId] = node;
            while (_queries.Count > MaximumCompiledQueries && _queryLru.Last is { } last)
            {
                _queryLru.RemoveLast();
                _queries.Remove(last.Value.QueryId);
            }
        }
    }

    internal CompiledArchiveQuery GetRequiredQuery(string queryId)
    {
        lock (_queryGate)
        {
            if (!_queries.TryGetValue(queryId, out var node))
            {
                throw new KeyNotFoundException("Archive query is not available or has expired from the bounded query cache.");
            }
            _queryLru.Remove(node);
            _queryLru.AddFirst(node);
            return node.Value;
        }
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) == 0)
        {
            lock (_queryGate)
            {
                _queries.Clear();
                _queryLru.Clear();
            }
            _generation.Dispose();
        }
    }
}

internal static class ArchiveDiscoveryWarnings
{
    public static IReadOnlyList<string> FromManifest(ArchiveGenerationManifest manifest)
    {
        if (File.Exists(manifest.PackageRoot))
        {
            return [];
        }
        var suspicious = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var source in manifest.SourceFiles)
        {
            if (!source.RelativePath.EndsWith(".pamt", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            var parts = source.RelativePath.Replace('\\', '/').Split('/', StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 1 || parts.Length == 2 && IsPackageGroup(parts[0]))
            {
                continue;
            }
            string relativeRoot;
            if (parts[0].Equals("game_files", StringComparison.OrdinalIgnoreCase))
            {
                if (parts.Length == 2 || parts.Length == 3 && IsPackageGroup(parts[1]))
                {
                    continue;
                }
                relativeRoot = string.Join(Path.DirectorySeparatorChar, parts[..^1]);
            }
            else
            {
                relativeRoot = IsPackageGroup(parts[0])
                    ? string.Join(Path.DirectorySeparatorChar, parts[..^1])
                    : parts[0];
            }
            suspicious.Add(Path.GetFullPath(Path.Combine(manifest.PackageRoot, relativeRoot)));
        }
        return suspicious
            .Order(StringComparer.OrdinalIgnoreCase)
            .Select(static path => $"Possible duplicate archive tree: {path}")
            .ToArray();
    }

    private static bool IsPackageGroup(string value) =>
        value.Length == 4 && value.All(static character => character is >= '0' and <= '9');
}

internal sealed class CompiledArchiveQuery
{
    private readonly long[]? _entryIds;

    private CompiledArchiveQuery(
        string queryId,
        long generation,
        ArchiveQuery query,
        long[]? entryIds,
        long identityEntryCount)
    {
        QueryId = queryId;
        Generation = generation;
        Query = query;
        _entryIds = entryIds;
        EntryCount = entryIds?.LongLength ?? identityEntryCount;
    }

    public string QueryId { get; }
    public long Generation { get; }
    public ArchiveQuery Query { get; }
    public long EntryCount { get; }
    public bool UsesIdentityOrder => _entryIds is null;

    public static CompiledArchiveQuery Identity(
        string queryId,
        long generation,
        ArchiveQuery query,
        long entryCount) =>
        new(queryId, generation, query, null, entryCount);

    public static CompiledArchiveQuery Materialized(
        string queryId,
        long generation,
        ArchiveQuery query,
        long[] entryIds) =>
        new(queryId, generation, query, entryIds, 0);

    public long EntryIdAt(long row)
    {
        if (row < 0 || row >= EntryCount)
        {
            throw new ArgumentOutOfRangeException(nameof(row));
        }
        return _entryIds is null ? row : _entryIds[row];
    }

    public long[] MaterializeEntryIds()
    {
        if (_entryIds is not null)
        {
            return _entryIds;
        }
        if (EntryCount > Array.MaxLength)
        {
            throw new InvalidDataException("The archive query is too large to materialize.");
        }
        var entryIds = new long[checked((int)EntryCount)];
        for (var index = 0; index < entryIds.Length; index++)
        {
            entryIds[index] = index;
        }
        return entryIds;
    }
}

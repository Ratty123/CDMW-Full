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
    public bool CacheHit => _generation.CacheHit;

    public ArchiveSessionHandle Handle => new(
        Id,
        PackageRoot,
        Fingerprint,
        Index.EntryCount,
        ArchiveIndex.Version,
        CacheHit);

    public ArchiveEntryDto ReadEntry(long entryId)
    {
        var entry = Index.ReadEntry(entryId, Id);
        return Volatile.Read(ref _nameIndex)?.Enrich(entry) ?? entry;
    }

    internal void SetNameIndex(ArchiveNameIndex index) => Volatile.Write(ref _nameIndex, index);

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

internal sealed record CompiledArchiveQuery(
    string QueryId,
    long Generation,
    ArchiveQuery Query,
    long[] EntryIds);

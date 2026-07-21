using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveItemCatalogService(
    ArchiveSessionManager sessions,
    ArchiveItemCatalogBuildService builder)
{
    public async Task<ItemCatalogSearchResult> SearchAsync(
        ItemCatalogSearchRequest request,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var pageSize = Math.Clamp(request.PageSize, 1, 256);
        var session = sessions.GetRequired(request.SessionId);
        if (!session.TryGetItemCatalog(out var catalog) || catalog is null)
        {
            var built = await builder.BuildAsync(
                new BuildNameIndexRequest(request.SessionId),
                publishProgress,
                cancellationToken).ConfigureAwait(false);
            if (!built.Available || !session.TryGetItemCatalog(out catalog) || catalog is null)
            {
                return new ItemCatalogSearchResult(
                    request.SessionId,
                    0,
                    0,
                    pageSize,
                    [],
                    [],
                    [],
                    HasMaterialEvidence: false,
                    built.Warning ?? "The item catalogue is unavailable for this archive.");
            }
        }
        var page = catalog.Search(
            request.Query,
            request.Category,
            request.Group,
            request.MaterialTag,
            Math.Max(0, request.PageStart),
            pageSize);
        return new ItemCatalogSearchResult(
            request.SessionId,
            page.TotalMatches,
            Math.Max(0, request.PageStart),
            pageSize,
            page.Items.Select(ToContract).ToArray(),
            catalog.CategoryFacets,
            catalog.MaterialFacets,
            catalog.HasMaterialEvidence);
    }

    internal static ItemCatalogRow ToContract(ArchiveItemCatalogRecord item) => new(
        item.ItemId,
        Bounded(item.InternalName),
        Bounded(item.DisplayName),
        Bounded(item.Category),
        Bounded(item.Group),
        Bounded(item.CategoryEvidence),
        BoundedValues(item.PacFiles, 4),
        BoundedValues(item.ModelStems, 4),
        BoundedValues(item.IconPaths, 2),
        BoundedValues(item.LocalizedNames, 3),
        BoundedValues(item.MaterialTags, 6),
        item.VariantCount,
        Bounded(item.Evidence, 4096));

    private static string[] BoundedValues(IReadOnlyList<string> values, int maximum) => values
        .Take(maximum)
        .Select(static value => Bounded(value, 160))
        .ToArray();

    private static string Bounded(string value, int maximum = 1024) =>
        value.Length <= maximum ? value : value[..maximum];
}

public sealed class ArchiveItemIconService(
    ArchiveSessionManager sessions,
    ArchiveItemCatalogBuildService builder,
    ArchiveEntryPreparationService preparation)
{
    private const int MaximumVisibleBatch = 64;

    public async Task<ItemIconBatchResult> LoadAsync(ItemIconBatchRequest request, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var ids = request.ItemIds.Distinct().Take(MaximumVisibleBatch + 1).ToArray();
        if (ids.Length > MaximumVisibleBatch)
        {
            throw new InvalidDataException($"A visible icon batch may contain at most {MaximumVisibleBatch} items.");
        }
        if (request.ThumbnailSize is < 32 or > 512)
        {
            throw new InvalidDataException("Item icon size must be between 32 and 512 pixels.");
        }
        var session = sessions.GetRequired(request.SessionId);
        if (!session.TryGetItemCatalog(out var catalog) || catalog is null)
        {
            var built = await builder.BuildAsync(new BuildNameIndexRequest(request.SessionId), null, cancellationToken).ConfigureAwait(false);
            if (!built.Available || !session.TryGetItemCatalog(out catalog) || catalog is null)
            {
                throw new InvalidOperationException(built.Warning ?? "The item catalogue is unavailable for this archive.");
            }
        }
        var results = new List<ItemIconResult>(ids.Length);
        foreach (var itemId in ids)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!catalog.TryGet(itemId, out var item) || item is null)
            {
                results.Add(new ItemIconResult(itemId, null, null, "The item is not present in the active catalogue."));
                continue;
            }
            var entryId = ResolveFirstPath(session, item.IconPaths, cancellationToken);
            if (entryId is null)
            {
                results.Add(new ItemIconResult(itemId, null, null, "No archive DDS inventory icon was recovered for this item."));
                continue;
            }
            try
            {
                var prepared = await preparation.PrepareAsync(
                    new PrepareEntryRequest(session.Id, entryId.Value),
                    cancellationToken).ConfigureAwait(false);
                results.Add(new ItemIconResult(itemId, null, prepared.PreparedPath, null));
            }
            catch (Exception exception) when (exception is IOException or InvalidDataException or NativeArchiveException)
            {
                results.Add(new ItemIconResult(itemId, null, null, Bounded(exception.Message)));
            }
        }
        return new ItemIconBatchResult(session.Id, results);
    }

    private static long? ResolveFirstPath(ArchiveSession session, IReadOnlyList<string> paths, CancellationToken cancellationToken)
    {
        foreach (var candidate in paths.Take(8))
        {
            cancellationToken.ThrowIfCancellationRequested();
            var normalized = candidate.Replace('\\', '/').Trim('/');
            var exact = session.Index.FindEntriesByPath(normalized, 1);
            if (exact.Count > 0) return exact[0].EntryId;
            var basename = Path.GetFileName(normalized);
            if (basename.Length == 0) continue;
            var lookup = session.DependencyIndex.FindEntryIdsByBasename(session.Index, basename, 1, cancellationToken);
            if (lookup.EntryIds.Count > 0) return lookup.EntryIds[0];
        }
        return null;
    }

    private static string Bounded(string value) => value.Length <= 4096 ? value : value[..4096];
}

public sealed class ArchiveItemCatalogScopeService(
    ArchiveSessionManager sessions,
    ArchiveItemCatalogBuildService builder,
    ArchiveLookupService lookups)
{
    private static readonly string[] ModelExtensions = [".pac", ".pam", ".pamlod", ".pat", ".prefab", ".pact"];

    public async Task<ItemCatalogScopeResult> ResolveAsync(
        ItemCatalogScopeRequest request,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var maximum = Math.Clamp(request.MaximumResults, 1, 4096);
        var session = sessions.GetRequired(request.SessionId);
        if (!session.TryGetItemCatalog(out var catalog) || catalog is null)
        {
            var built = await builder.BuildAsync(new BuildNameIndexRequest(request.SessionId), publishProgress, cancellationToken).ConfigureAwait(false);
            if (!built.Available || !session.TryGetItemCatalog(out catalog) || catalog is null)
            {
                throw new InvalidOperationException(built.Warning ?? "The item catalogue is unavailable for this archive.");
            }
        }

        var selected = new List<ArchiveItemCatalogRecord>();
        if (request.ItemIds is { Count: > 0 })
        {
            foreach (var itemId in request.ItemIds.Distinct().Take(4096))
            {
                if (catalog.TryGet(itemId, out var item) && item is not null) selected.Add(item);
            }
        }
        else
        {
            var start = 0;
            while (selected.Count < 4096)
            {
                var page = catalog.Search(request.Query, request.Category, request.Group, request.MaterialTag, start, 256);
                selected.AddRange(page.Items);
                start += page.Items.Count;
                if (page.Items.Count == 0 || start >= page.TotalMatches) break;
            }
        }

        var resolved = new HashSet<long>();
        var truncated = selected.Count >= 4096;
        foreach (var item in selected)
        {
            cancellationToken.ThrowIfCancellationRequested();
            foreach (var path in item.PacFiles.Concat(item.IconPaths))
            {
                truncated |= AddPath(session, path, resolved, maximum, cancellationToken);
                if (resolved.Count >= maximum) break;
            }
            foreach (var stem in item.ModelStems)
            {
                var name = Path.GetFileNameWithoutExtension(stem.Replace('\\', '/'));
                foreach (var extension in ModelExtensions)
                {
                    truncated |= AddPath(session, name + extension, resolved, maximum, cancellationToken);
                    if (resolved.Count >= maximum) break;
                }
                if (resolved.Count >= maximum) break;
            }
            if (resolved.Count >= maximum) break;
        }
        var directCount = resolved.Count;
        if (request.IncludeRelated && resolved.Count < maximum)
        {
            foreach (var sourceId in resolved.Take(12).ToArray())
            {
                cancellationToken.ThrowIfCancellationRequested();
                var related = await lookups.ResolveAssociationEntryIdsAsync(session.Id, sourceId, cancellationToken, publishProgress).ConfigureAwait(false);
                foreach (var entryId in related)
                {
                    if (resolved.Count >= maximum)
                    {
                        truncated = true;
                        break;
                    }
                    resolved.Add(entryId);
                }
                if (resolved.Count >= maximum) break;
            }
        }
        if (publishProgress is not null)
        {
            await publishProgress(new ProgressUpdate(resolved.Count, resolved.Count, "item_scope_ready")).ConfigureAwait(false);
        }
        return new ItemCatalogScopeResult(
            session.Id,
            resolved.Order().ToArray(),
            directCount,
            selected.Count,
            truncated);
    }

    private static bool AddPath(
        ArchiveSession session,
        string candidate,
        ISet<long> resolved,
        int maximum,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(candidate) || resolved.Count >= maximum) return false;
        var normalized = candidate.Replace('\\', '/').Trim('/');
        var exact = session.Index.FindEntriesByPath(normalized, 33);
        foreach (var entry in exact.Take(32))
        {
            resolved.Add(entry.EntryId);
            if (resolved.Count >= maximum) return exact.Count > 32;
        }
        var basename = Path.GetFileName(normalized);
        if (basename.Length == 0) return exact.Count > 32;
        var matches = session.DependencyIndex.FindEntryIdsByBasename(session.Index, basename, 33, cancellationToken);
        foreach (var entryId in matches.EntryIds.Take(32))
        {
            resolved.Add(entryId);
            if (resolved.Count >= maximum) break;
        }
        return exact.Count > 32 || matches.Truncated || resolved.Count >= maximum;
    }
}

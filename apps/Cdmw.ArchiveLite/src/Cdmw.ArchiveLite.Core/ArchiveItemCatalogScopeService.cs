using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveItemCatalogScopeService(
    ArchiveSessionManager sessions,
    ArchiveItemNameIndexService catalogueBuilder,
    ArchiveAssociationService associations)
{
    private static readonly string[] ModelExtensions = [".pac", ".pam", ".pamlod", ".pat", ".prefab", ".pact"];

    public async Task<ItemCatalogScopeResult> ResolveAsync(
        ItemCatalogScopeRequest request,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var maximumResults = Math.Clamp(request.MaximumResults, 1, 1024);
        var session = sessions.GetRequired(request.SessionId);
        if (!session.TryGetItemCatalog(out var catalog) || catalog is null)
        {
            var built = await catalogueBuilder.BuildAsync(
                new BuildNameIndexRequest(request.SessionId),
                publishProgress,
                cancellationToken).ConfigureAwait(false);
            if (!built.Available || !session.TryGetItemCatalog(out catalog) || catalog is null)
            {
                throw new InvalidOperationException(built.Warning ?? "The Item Finder catalog is unavailable for this archive.");
            }
        }
        if (!catalog.TryGet(request.ItemId, out var item) || item is null)
        {
            throw new KeyNotFoundException($"Item {request.ItemId} is not present in the active catalog.");
        }

        var resolved = new Dictionary<long, ArchiveEntryDto>();
        foreach (var path in item.PacFiles.Concat(item.IconPaths))
        {
            cancellationToken.ThrowIfCancellationRequested();
            AddResolvedPath(session, path, resolved, maximumResults);
            if (resolved.Count >= maximumResults) break;
        }
        foreach (var stem in item.ModelStems)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var normalized = Path.GetFileNameWithoutExtension(stem.Replace('\\', '/'));
            foreach (var extension in ModelExtensions)
            {
                AddResolvedPath(session, normalized + extension, resolved, maximumResults);
                if (resolved.Count >= maximumResults) break;
            }
            if (resolved.Count >= maximumResults) break;
        }

        var directCount = resolved.Count;
        var truncated = directCount >= maximumResults;
        if (request.IncludeRelated && resolved.Count < maximumResults)
        {
            var directSources = resolved.Values
                .Where(static entry => entry.Role is ArchiveEntryRole.Model or ArchiveEntryRole.Material or ArchiveEntryRole.Metadata)
                .Take(12)
                .ToArray();
            for (var index = 0; index < directSources.Length && resolved.Count < maximumResults; index++)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (publishProgress is not null)
                {
                    await publishProgress(new ProgressUpdate(index, directSources.Length, "item_scope_related", directSources[index].Path)).ConfigureAwait(false);
                }
                var related = await associations.FindAsync(
                    new FindAssociatedAssetsRequest(request.SessionId, directSources[index].EntryId, maximumResults),
                    publishProgress: null,
                    cancellationToken).ConfigureAwait(false);
                truncated |= related.Truncated;
                foreach (var asset in related.Assets)
                {
                    resolved.TryAdd(asset.Entry.EntryId, asset.Entry);
                    if (resolved.Count >= maximumResults)
                    {
                        truncated = true;
                        break;
                    }
                }
            }
        }
        if (publishProgress is not null)
        {
            await publishProgress(new ProgressUpdate(resolved.Count, resolved.Count, "item_scope_ready")).ConfigureAwait(false);
        }
        return new ItemCatalogScopeResult(
            request.SessionId,
            request.ItemId,
            request.IncludeRelated,
            resolved.Keys.Order().ToArray(),
            directCount,
            truncated);
    }

    private static void AddResolvedPath(
        ArchiveSession session,
        string candidatePath,
        IDictionary<long, ArchiveEntryDto> resolved,
        int maximumResults)
    {
        if (string.IsNullOrWhiteSpace(candidatePath) || resolved.Count >= maximumResults)
        {
            return;
        }
        var normalized = candidatePath.Replace('\\', '/').Trim('/');
        var exact = session.Index.FindEntriesByPath(normalized, 32);
        foreach (var entry in exact)
        {
            resolved.TryAdd(entry.EntryId, entry);
            if (resolved.Count >= maximumResults) return;
        }
        var basename = Path.GetFileName(normalized);
        if (string.IsNullOrWhiteSpace(basename))
        {
            return;
        }
        foreach (var entry in session.BasenameIndex.FindEntriesByBasename(session.Index, basename, 32)
                     .OrderByDescending(entry => entry.Path.EndsWith(normalized, StringComparison.OrdinalIgnoreCase))
                     .ThenBy(static entry => entry.Path.Length))
        {
            resolved.TryAdd(entry.EntryId, entry);
            if (resolved.Count >= maximumResults) return;
        }
    }
}

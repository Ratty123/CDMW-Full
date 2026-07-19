using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveItemCatalogService(
    ArchiveSessionManager sessions,
    ArchiveItemNameIndexService catalogueBuilder)
{
    public async Task<ItemCatalogSearchResult> SearchAsync(
        ItemCatalogSearchRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(request.SessionId);
        if (!session.TryGetItemCatalog(out var catalog) || catalog is null)
        {
            var built = await catalogueBuilder.BuildAsync(
                new BuildNameIndexRequest(request.SessionId),
                publishProgress: null,
                cancellationToken).ConfigureAwait(false);
            if (!built.Available || !session.TryGetItemCatalog(out catalog) || catalog is null)
            {
                return new ItemCatalogSearchResult(
                    request.SessionId,
                    0,
                    0,
                    Math.Clamp(request.PageSize, 1, 200),
                    [],
                    [],
                    [],
                    built.Warning ?? "The Item Finder catalog is unavailable for this archive.");
            }
        }

        var page = catalog.Search(
            request.Query,
            request.Category,
            request.Group,
            request.MaterialTag,
            request.PageStart,
            request.PageSize);
        return new ItemCatalogSearchResult(
            request.SessionId,
            page.TotalMatches,
            request.PageStart,
            request.PageSize,
            page.Items.Select(ToContract).ToArray(),
            catalog.CategoryFacets,
            catalog.MaterialFacets);
    }

    internal static ItemCatalogRow ToContract(ArchiveItemCatalogRecord item) => new(
        item.ItemId,
        item.InternalName,
        item.DisplayName,
        item.Category,
        item.Group,
        item.CategoryEvidence,
        item.PacFiles,
        item.ModelStems,
        item.IconPaths,
        item.LocalizedNames,
        item.MaterialTags,
        item.VariantCount,
        item.Evidence);
}

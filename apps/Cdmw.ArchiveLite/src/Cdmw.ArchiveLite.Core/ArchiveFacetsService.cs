using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveFacetsService(ArchiveSessionManager sessions)
{
    public async Task<ArchiveFacetsResult> LoadAsync(
        ArchiveFacetsRequest request,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(request.SessionId);
        if (session.TryGetExtensionFacets(out var cached) && cached is not null)
        {
            return new ArchiveFacetsResult(session.Id, cached);
        }

        var counts = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        var total = session.Index.EntryCount;
        if (publishProgress is not null)
        {
            await publishProgress(new ProgressUpdate(0, total, "extension_scan")).ConfigureAwait(false);
        }
        for (long entryId = 0; entryId < total; entryId++)
        {
            if ((entryId & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (publishProgress is not null)
                {
                    await publishProgress(new ProgressUpdate(entryId, total, "extension_scan")).ConfigureAwait(false);
                }
            }
            var extension = session.Index.ReadEntry(entryId).Extension;
            if (!string.IsNullOrWhiteSpace(extension))
            {
                counts[extension] = counts.GetValueOrDefault(extension) + 1;
            }
        }
        cancellationToken.ThrowIfCancellationRequested();
        var facets = counts
            .Select(pair => new ArchiveExtensionFacet(
                pair.Key,
                pair.Value,
                ArchiveEntryClassifier.ClassifyExtensionCategory(pair.Key)))
            .OrderBy(static item => item.Category)
            .ThenByDescending(static item => item.Count)
            .ThenBy(static item => item.Extension, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        session.SetExtensionFacets(facets);
        if (publishProgress is not null)
        {
            await publishProgress(new ProgressUpdate(total, total, "extension_scan")).ConfigureAwait(false);
        }
        return new ArchiveFacetsResult(session.Id, facets);
    }
}

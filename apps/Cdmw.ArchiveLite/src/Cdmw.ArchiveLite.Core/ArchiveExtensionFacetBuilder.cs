using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public static class ArchiveExtensionFacetBuilder
{
    public static IReadOnlyList<ArchiveExtensionFacet> Build(IEnumerable<ArchiveEntryDto> entries)
    {
        ArgumentNullException.ThrowIfNull(entries);
        return entries
            .Where(static entry => !string.IsNullOrWhiteSpace(entry.Extension))
            .GroupBy(static entry => entry.Extension, StringComparer.OrdinalIgnoreCase)
            .Select(group => new ArchiveExtensionFacet(
                group.Key.ToLowerInvariant(),
                group.LongCount(),
                ArchiveEntryClassifier.ClassifyExtensionCategory(group.Key)))
            .OrderBy(static facet => facet.Category)
            .ThenByDescending(static facet => facet.Count)
            .ThenBy(static facet => facet.Extension, StringComparer.Ordinal)
            .ToArray();
    }
}

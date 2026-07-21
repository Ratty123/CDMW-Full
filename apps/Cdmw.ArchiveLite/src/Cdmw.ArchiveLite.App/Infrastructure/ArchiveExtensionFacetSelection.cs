using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.App.Infrastructure;

public static class ArchiveExtensionFacetSelection
{
    public static IReadOnlyList<ArchiveExtensionFacet> MostCommon(
        IEnumerable<ArchiveExtensionFacet> facets,
        int maximum = 10)
    {
        ArgumentNullException.ThrowIfNull(facets);
        if (maximum < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maximum));
        }
        return facets
            .OrderByDescending(static facet => facet.Count)
            .ThenBy(static facet => facet.Extension, StringComparer.Ordinal)
            .Take(maximum)
            .ToArray();
    }
}

using System.Collections.ObjectModel;
using System.Text;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveItemCatalog
{
    private readonly IReadOnlyList<ArchiveItemCatalogRecord> _items;
    private readonly IReadOnlyDictionary<int, ArchiveItemCatalogRecord> _byItemId;

    private ArchiveItemCatalog(IReadOnlyList<ArchiveItemCatalogRecord> items)
    {
        _items = items;
        _byItemId = new ReadOnlyDictionary<int, ArchiveItemCatalogRecord>(
            items.GroupBy(static item => item.ItemId)
                .ToDictionary(static group => group.Key, static group => group.First()));
        CategoryFacets = items
            .GroupBy(static item => (item.Category, item.Group), CategoryGroupComparer.Instance)
            .Select(static group => new ItemCatalogCategoryFacet(group.Key.Category, group.Key.Group, group.LongCount()))
            .OrderBy(static facet => facet.Category, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static facet => facet.Group, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        MaterialFacets = items
            .SelectMany(static item => item.MaterialTags)
            .Where(static value => !string.IsNullOrWhiteSpace(value))
            .GroupBy(static value => value, StringComparer.OrdinalIgnoreCase)
            .Select(static group => new ItemCatalogValueFacet(group.Key, group.LongCount()))
            .OrderByDescending(static facet => facet.Count)
            .ThenBy(static facet => facet.Value, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public long Count => _items.Count;
    public IReadOnlyList<ArchiveItemCatalogRecord> Items => _items;
    public IReadOnlyList<ItemCatalogCategoryFacet> CategoryFacets { get; }
    public IReadOnlyList<ItemCatalogValueFacet> MaterialFacets { get; }
    public bool HasMaterialEvidence => MaterialFacets.Count > 0;

    public static ArchiveItemCatalog FromRecords(IEnumerable<ArchiveItemCatalogRecord> records)
    {
        ArgumentNullException.ThrowIfNull(records);
        var items = records
            .Where(static item => item.ItemId > 0 && !string.IsNullOrWhiteSpace(item.InternalName))
            .Select(Normalize)
            .GroupBy(static item => item.ItemId)
            .Select(static group => group.First())
            .OrderBy(static item => item.Category, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static item => item.Group, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static item => item.DisplayName, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static item => item.ItemId)
            .ToArray();
        return new ArchiveItemCatalog(items);
    }

    public bool TryGet(int itemId, out ArchiveItemCatalogRecord? item) => _byItemId.TryGetValue(itemId, out item);

    public ArchiveItemCatalogPage Search(
        string? query,
        string? category,
        string? group,
        string? materialTag,
        int pageStart,
        int pageSize)
    {
        if (pageStart < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(pageStart));
        }
        if (pageSize is < 1 or > 256)
        {
            throw new ArgumentOutOfRangeException(nameof(pageSize), "Finder page size must be between 1 and 256.");
        }

        IEnumerable<ArchiveItemCatalogRecord> matches = _items;
        if (!string.IsNullOrWhiteSpace(category))
        {
            matches = matches.Where(item => item.Category.Equals(category.Trim(), StringComparison.OrdinalIgnoreCase));
        }
        if (!string.IsNullOrWhiteSpace(group))
        {
            matches = matches.Where(item => item.Group.Equals(group.Trim(), StringComparison.OrdinalIgnoreCase));
        }
        if (!string.IsNullOrWhiteSpace(materialTag))
        {
            matches = matches.Where(item => item.MaterialTags.Contains(materialTag.Trim(), StringComparer.OrdinalIgnoreCase));
        }
        var tokens = NormalizeSearch(query).Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (tokens.Length > 0)
        {
            matches = matches.Where(item => tokens.All(token => item.SearchText.Contains(token, StringComparison.Ordinal)));
        }
        var materialized = matches as IReadOnlyCollection<ArchiveItemCatalogRecord> ?? matches.ToArray();
        return new ArchiveItemCatalogPage(
            materialized.Count,
            materialized.Skip(pageStart).Take(pageSize).ToArray());
    }

    private static ArchiveItemCatalogRecord Normalize(ArchiveItemCatalogRecord source)
    {
        var internalName = source.InternalName.Trim();
        var displayName = string.IsNullOrWhiteSpace(source.DisplayName)
            ? FriendlyName(internalName)
            : source.DisplayName.Trim();
        var localizedNames = Values(source.LocalizedNames);
        var modelStems = Values(source.ModelStems);
        var pacFiles = Values(source.PacFiles);
        var iconPaths = Values(source.IconPaths);
        var materialTags = Values(source.MaterialTags);
        var (category, group, categoryEvidence) = Classify(
            internalName,
            displayName,
            pacFiles,
            modelStems,
            iconPaths);
        var evidence = string.Join(
            "; ",
            new[]
            {
                source.PrefabHashes.Count > 0 ? "prefab link" : "",
                modelStems.Length > 0 ? "model link" : "",
                iconPaths.Length > 0 ? "inventory icon" : "",
                materialTags.Length > 0 ? "material evidence" : "",
            }.Where(static value => value.Length > 0));
        return source with
        {
            InternalName = internalName,
            DisplayName = displayName,
            LocalizedNames = localizedNames,
            PrefabHashes = source.PrefabHashes.Distinct().ToArray(),
            ModelStems = modelStems,
            PacFiles = pacFiles,
            IconPaths = iconPaths,
            MaterialTags = materialTags,
            Category = category,
            Group = group,
            CategoryEvidence = categoryEvidence,
            VariantCount = Math.Max(1, source.VariantCount),
            Evidence = evidence,
            SearchText = NormalizeSearch(string.Join(
                ' ',
                new[] { source.ItemId.ToString(), internalName, displayName, category, group }
                    .Concat(localizedNames)
                    .Concat(pacFiles)
                    .Concat(modelStems)
                    .Concat(iconPaths)
                    .Concat(materialTags))),
        };
    }

    private static (string Category, string Group, string Evidence) Classify(
        string internalName,
        string displayName,
        IReadOnlyList<string> pacFiles,
        IReadOnlyList<string> modelStems,
        IReadOnlyList<string> iconPaths)
    {
        var text = NormalizeSearch(string.Join(' ', new[] { internalName, displayName }.Concat(pacFiles).Concat(modelStems).Concat(iconPaths)));
        static bool Has(string textValue, params string[] values) => values.Any(value => textValue.Contains(value, StringComparison.Ordinal));
        const string evidence = "item and archive path classification";
        if (Has(text, "subweapon", "shield")) return ("Equipment", "Subweapon / Shield", evidence);
        if (Has(text, "greatsword", "longsword", "sword", "dagger", "bow", "staff", "axe", "spear", "weapon")) return ("Equipment", "Weapon", evidence);
        if (Has(text, "upperbody", "upper body", "chest", "armor")) return ("Equipment", "Upper Armor", evidence);
        if (Has(text, "lowerbody", "lower body", "pants", "leg armor")) return ("Equipment", "Lower Armor", evidence);
        if (Has(text, "glove", "hand")) return ("Equipment", "Hands", evidence);
        if (Has(text, "boot", "shoe", "foot")) return ("Equipment", "Feet", evidence);
        if (Has(text, "helmet", "headgear", "head armor")) return ("Equipment", "Head", evidence);
        if (Has(text, "earring", "necklace", "ring", "belt", "accessory")) return ("Equipment", "Accessory", evidence);
        if (Has(text, "potion", "food", "drink", "elixir", "consumable")) return ("Consumable", "Consumable", evidence);
        if (Has(text, "ore", "ingot", "metal", "cloth", "leather", "fabric", "wood", "stone", "crystal", "gem", "material")) return ("Material", "Crafting Material", evidence);
        if (Has(text, "quest")) return ("Quest", "Quest Item", evidence);
        return ("Other", "Other", evidence);
    }

    private static string FriendlyName(string value)
    {
        var builder = new StringBuilder(value.Length);
        var previousWasSeparator = true;
        foreach (var character in value)
        {
            if (character is '_' or '-' or '.')
            {
                if (!previousWasSeparator) builder.Append(' ');
                previousWasSeparator = true;
                continue;
            }
            builder.Append(previousWasSeparator ? char.ToUpperInvariant(character) : character);
            previousWasSeparator = false;
        }
        return builder.ToString().Trim();
    }

    private static string[] Values(IEnumerable<string>? values) => (values ?? [])
        .Where(static value => !string.IsNullOrWhiteSpace(value))
        .Select(static value => value.Trim())
        .Distinct(StringComparer.OrdinalIgnoreCase)
        .ToArray();

    private static string NormalizeSearch(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return string.Empty;
        var builder = new StringBuilder(value.Length);
        var separator = false;
        foreach (var character in value.Normalize().ToLowerInvariant())
        {
            if (char.IsLetterOrDigit(character))
            {
                if (separator && builder.Length > 0) builder.Append(' ');
                builder.Append(character);
                separator = false;
            }
            else
            {
                separator = true;
            }
        }
        return builder.ToString();
    }

    private sealed class CategoryGroupComparer : IEqualityComparer<(string Category, string Group)>
    {
        public static CategoryGroupComparer Instance { get; } = new();

        public bool Equals((string Category, string Group) left, (string Category, string Group) right) =>
            left.Category.Equals(right.Category, StringComparison.OrdinalIgnoreCase)
            && left.Group.Equals(right.Group, StringComparison.OrdinalIgnoreCase);

        public int GetHashCode((string Category, string Group) value) => HashCode.Combine(
            StringComparer.OrdinalIgnoreCase.GetHashCode(value.Category),
            StringComparer.OrdinalIgnoreCase.GetHashCode(value.Group));
    }
}

public sealed record ArchiveItemCatalogRecord(
    int ItemId,
    string InternalName,
    string DisplayName,
    IReadOnlyList<string> LocalizedNames,
    IReadOnlyList<uint> PrefabHashes,
    IReadOnlyList<string> ModelStems,
    IReadOnlyList<string> PacFiles,
    IReadOnlyList<string> IconPaths,
    IReadOnlyList<string> MaterialTags,
    string Category = "",
    string Group = "",
    string CategoryEvidence = "",
    int VariantCount = 1,
    string Evidence = "",
    string SearchText = "");

public sealed record ArchiveItemCatalogPage(long TotalMatches, IReadOnlyList<ArchiveItemCatalogRecord> Items);

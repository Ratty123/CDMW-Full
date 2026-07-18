using System.Text.RegularExpressions;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveItemNameIndex
{
    private static readonly string[] VariantSuffixes =
    [
        "_index01_l", "_index01_r", "_index02_l", "_index02_r", "_index03_l", "_index03_r",
        "_index01", "_index02", "_index03", "_sub01", "_sub02", "_sub03",
        "_in", "_l", "_r", "_u", "_s", "_t", "_c", "_d",
    ];

    private static readonly Regex NumberedVariant = new(
        "_(?:index|sub)\\d{2}$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private static readonly Regex CharacterEquipmentComponent = new(
        "^(?<root>cd_[a-z]\\d{4}_\\d{2}_.+?)_(?:ub|lb|hel|sho|hand|foot|belt|vest|mask|cloak|cape|hair|head|face|acc|body|arm|leg)(?:_[a-z0-9]+)*_\\d{4}(?:_\\d+)?$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private static readonly Regex PlateHelmModel = new(
        "^(?<prefix>cd_)ptm_\\d{2}_hel_(?<rest>.+)$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private readonly IReadOnlyDictionary<string, string> _exactNames;
    private readonly IReadOnlyDictionary<string, string> _relatedNames;

    private ArchiveItemNameIndex(
        IReadOnlyDictionary<string, string> exactNames,
        IReadOnlyDictionary<string, string> relatedNames)
    {
        _exactNames = Normalize(exactNames);
        _relatedNames = Normalize(relatedNames);
    }

    public long ExactNameCount => _exactNames.Count;
    public long RelatedNameCount => _relatedNames.Count;

    public static ArchiveItemNameIndex FromMappings(
        IReadOnlyDictionary<string, string> exactNames,
        IReadOnlyDictionary<string, string> relatedNames) => new(exactNames, relatedNames);

    public ArchiveEntryDto Enrich(ArchiveEntryDto entry)
    {
        ArgumentNullException.ThrowIfNull(entry);
        var stem = Path.GetFileNameWithoutExtension(entry.Name).Trim().ToLowerInvariant();
        if (string.IsNullOrWhiteSpace(stem))
        {
            return entry;
        }

        if (_exactNames.TryGetValue(stem, out var exactName))
        {
            return entry with
            {
                KnownName = exactName,
                NameEvidence = "Exact localization",
            };
        }

        foreach (var candidate in RelatedCandidates(stem))
        {
            if (_relatedNames.TryGetValue(candidate, out var relatedName)
                || _exactNames.TryGetValue(candidate, out relatedName))
            {
                return entry with
                {
                    KnownName = string.Empty,
                    NameEvidence = $"Name hint: {relatedName}",
                };
            }
        }
        return entry;
    }

    internal IReadOnlyDictionary<string, string> ExactNames => _exactNames;
    internal IReadOnlyDictionary<string, string> RelatedNames => _relatedNames;

    private static IReadOnlyDictionary<string, string> Normalize(IReadOnlyDictionary<string, string> source)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var (rawKey, rawValue) in source)
        {
            var key = rawKey.Trim().ToLowerInvariant();
            var value = rawValue.Trim();
            if (!string.IsNullOrWhiteSpace(key) && !string.IsNullOrWhiteSpace(value))
            {
                result[key] = value;
            }
        }
        return result;
    }

    private static IEnumerable<string> RelatedCandidates(string stem)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var candidates = new List<string>();
        void Add(string value)
        {
            var normalized = value.Trim().ToLowerInvariant();
            if (!string.IsNullOrWhiteSpace(normalized) && seen.Add(normalized))
            {
                candidates.Add(normalized);
            }
        }

        Add(stem);
        var family = StripVariantSuffix(stem);
        Add(family);
        foreach (var value in candidates.ToArray())
        {
            var equipment = CharacterEquipmentComponent.Match(value);
            if (equipment.Success)
            {
                Add(equipment.Groups["root"].Value);
            }
            var helm = PlateHelmModel.Match(value);
            if (helm.Success)
            {
                var descriptor = $"{helm.Groups["prefix"].Value}phm_00_hel_{helm.Groups["rest"].Value}";
                Add(descriptor);
                Add(descriptor + "_c");
            }
        }
        return candidates;
    }

    private static string StripVariantSuffix(string stem)
    {
        var normalized = stem.Trim().ToLowerInvariant();
        while (!string.IsNullOrWhiteSpace(normalized))
        {
            var before = normalized;
            foreach (var suffix in VariantSuffixes)
            {
                if (normalized.Length > suffix.Length && normalized.EndsWith(suffix, StringComparison.Ordinal))
                {
                    normalized = normalized[..^suffix.Length];
                    break;
                }
            }
            if (!normalized.Equals(before, StringComparison.Ordinal))
            {
                continue;
            }
            var stripped = NumberedVariant.Replace(normalized, string.Empty);
            if (!string.IsNullOrWhiteSpace(stripped) && !stripped.Equals(normalized, StringComparison.Ordinal))
            {
                normalized = stripped;
                continue;
            }
            if (normalized.Length >= 2 && char.IsDigit(normalized[^2]) && char.IsLetter(normalized[^1]))
            {
                normalized = normalized[..^1];
                continue;
            }
            return normalized;
        }
        return stem;
    }
}

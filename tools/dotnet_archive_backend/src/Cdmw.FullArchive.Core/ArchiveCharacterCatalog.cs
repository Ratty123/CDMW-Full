using System.Text;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

// Cache records contain generation-local IDs, never session IDs or prepared files.
public sealed record CharacterCatalogRecord(
    CharacterCatalogRow Row, string[] SearchNames, long[] DirectIds, long[] RelatedIds,
    string[] RelatedKeys, CharacterCatalogComponent[] Components,
    CharacterCatalogOwner[] Characters, string[] Evidence, string AppearancePath = "",
    string ContextKey = "");

public sealed record CharacterCatalogSnapshot(
    int Version, string Signature, CharacterCatalogRecord[] Records,
    CharacterCatalogRow[] Coverage, string[] Warnings);

public sealed class ArchiveCharacterCatalog(CharacterCatalogSnapshot snapshot)
{
    public CharacterCatalogSnapshot Snapshot { get; } = snapshot;
    private readonly Dictionary<string, CharacterCatalogRecord> _records = snapshot.Records
        .ToDictionary(static record => record.Row.Key, StringComparer.Ordinal);
    private readonly Dictionary<string, string> _search = snapshot.Records.ToDictionary(
        static record => record.Row.Key,
        static record => SearchText(record.Row, record.SearchNames), StringComparer.Ordinal);

    public CharacterCatalogRecord GetRequired(string key) => _records.TryGetValue(key, out var record)
        ? record : throw new KeyNotFoundException("Character catalogue result is unavailable. Refresh the finder.");

    public CharacterCatalogSearchResult Search(CharacterCatalogSearchRequest request)
    {
        if (request.View is not ("assets" or "appearances" or "coverage"))
            throw new ArgumentException("Character catalogue view must be assets, appearances or coverage.");
        if (request.Tab is not ("bodies" or "faces" or "all"))
            throw new ArgumentException("Character catalogue tab must be bodies, faces or all.");
        if (request.SelectionPurpose is not (null or "" or "hair_head" or "hair_body"))
            throw new ArgumentException("Unsupported character reference selector.");
        var tokens = Tokens(request.Query);
        HashSet<string>? related = null;
        if (!string.IsNullOrWhiteSpace(request.RelatedKey))
            related = GetRequired(request.RelatedKey).RelatedKeys.ToHashSet(StringComparer.Ordinal);
        var candidates = request.View == "coverage" ? Snapshot.Coverage : Snapshot.Records
            .Where(record => record.Row.View == request.View).Select(static record => record.Row);
        var matching = candidates.Where(row => EligibleReference(row, request.SelectionPurpose) && InTab(row, request.Tab)
            && (related is null || related.Contains(row.Key))
            && tokens.All(token => (_search.GetValueOrDefault(row.Key) ?? SearchText(row, [])).Contains(token, StringComparison.Ordinal)))
            .ToArray();
        var role = request.Tab == "faces" && string.IsNullOrEmpty(request.Role) ? "head" : request.Role;
        var rows = matching.Where(row => Matches(row.Role, role)
            && (row.Role != "unclassified" || request.Tab == "all" || request.Role == "unclassified")
            && (request.SourceGroup == "humanoid" ? IsHumanoid(row) : Matches(row.SourceGroup, request.SourceGroup))
            && Matches(row.BodyFamily, request.BodyFamily)
            && Matches(row.Resolution, request.Resolution))
            .OrderBy(static row => row.Label, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static row => row.Key, StringComparer.Ordinal).ToArray();
        var facets = new List<CharacterCatalogFacet>();
        facets.Add(new("source_group", "humanoid", matching.Count(IsHumanoid)));
        foreach (var (field, values) in new (string, IEnumerable<string>)[] {
            ("role", matching.Select(static row => row.Role)),
            ("source_group", matching.Select(static row => row.SourceGroup)),
            ("body_family", matching.Select(static row => row.BodyFamily)),
            ("resolution", matching.Select(static row => row.Resolution)) })
            facets.AddRange(values.GroupBy(static value => value, StringComparer.Ordinal)
                .OrderBy(static group => group.Key, StringComparer.Ordinal)
                .Select(group => new CharacterCatalogFacet(field, group.Key, group.Count())));
        var start = Math.Max(0, request.PageStart);
        var size = Math.Clamp(request.PageSize, 1, 72);
        return new(request.SessionId, rows.Length, start, size, rows.Skip(start).Take(size).ToArray(), facets, Snapshot.Warnings);
    }

    private static bool InTab(CharacterCatalogRow row, string tab) => tab == "all"
        || row.Role == "unclassified"
        || tab == "bodies" && row.Role is "body" or "whole_character"
        || tab == "faces" && !row.EmbeddedFace && row.Role is "head" or "facial_detail" or "hair" or "beard";
    private static bool IsHumanoid(CharacterCatalogRow row) => row.SourceGroup is "1_pc" or "3_npc";
    // Apply eligibility to the resident result set, before facets and pagination.
    // The asset view is already deduplicated against mounted archive precedence.
    private static bool EligibleReference(CharacterCatalogRow row, string? purpose)
    {
        if (string.IsNullOrEmpty(purpose)) return true;
        if (row.View != "assets" || row.BodyFamily != "2_phw" || row.ModelCount != 1
            || row.Resolution is not ("resolved" or "inferred")) return false;
        var path = row.Path.Replace('\\', '/').ToLowerInvariant();
        if (!path.StartsWith("character/model/1_pc/2_phw/", StringComparison.Ordinal)
            || !path.EndsWith(".pac", StringComparison.Ordinal)) return false;
        return purpose == "hair_head"
            ? row.Role == "head" && path.Contains("/head/head/", StringComparison.Ordinal)
            : (row.Role is "body" or "whole_character") && path.Contains("/nude/", StringComparison.Ordinal)
                && Path.GetFileName(path).StartsWith("cd_phw_00_nude_", StringComparison.Ordinal);
    }
    private static bool Matches(string value, string? filter) => string.IsNullOrEmpty(filter) || value == filter;
    private static string SearchText(CharacterCatalogRow row, IEnumerable<string> names) =>
        string.Join(' ', new[] { row.Label, row.InternalName, row.Path, row.Role, row.SourceGroup, row.BodyFamily }
            .Concat(names)).Normalize().ToLowerInvariant();
    private static string[] Tokens(string query)
    {
        var normalized = new StringBuilder();
        foreach (var character in query.Normalize().ToLowerInvariant())
            normalized.Append(char.IsLetterOrDigit(character) ? character : ' ');
        return normalized.ToString().Split(' ', StringSplitOptions.RemoveEmptyEntries);
    }
}

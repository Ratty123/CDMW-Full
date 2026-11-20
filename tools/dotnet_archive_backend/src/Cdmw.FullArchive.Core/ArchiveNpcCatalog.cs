using System.Globalization;
using System.Text;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

// Cache records hold generation-local entry IDs only, never session IDs.
public sealed record NpcCatalogRecord(NpcCatalogRow Row, string[] SearchNames, string[] DisplayNames, NpcOutfit[] Outfits);

public sealed record NpcCatalogSnapshot(
    int Version, string Signature, NpcCatalogRecord[] Records, NpcCatalogStatistics Statistics, string[] Warnings);

public sealed class ArchiveNpcCatalog
{
    public const int MaximumPageSize = 200;
    private readonly Dictionary<string, NpcCatalogRecord> _records;
    private readonly Dictionary<string, string> _search;
    private readonly Dictionary<string, List<(string Key, string AppearancePath, NpcPiece Piece)>> _wearers;

    public ArchiveNpcCatalog(NpcCatalogSnapshot snapshot)
    {
        Snapshot = snapshot;
        _records = snapshot.Records.ToDictionary(static record => record.Row.Key, StringComparer.Ordinal);
        _search = snapshot.Records.ToDictionary(static record => record.Row.Key,
            static record => SearchText(record), StringComparer.Ordinal);
        _wearers = new(StringComparer.Ordinal);
        foreach (var record in snapshot.Records)
        foreach (var outfit in record.Outfits)
        foreach (var piece in outfit.Pieces)
        {
            foreach (var key in PieceKeys(piece))
            {
                if (!_wearers.TryGetValue(key, out var list)) _wearers[key] = list = [];
                list.Add((record.Row.Key, outfit.AppearancePath, piece));
            }
        }
    }

    public NpcCatalogSnapshot Snapshot { get; }

    public NpcCatalogRecord GetRequired(string key) => _records.TryGetValue(key, out var record)
        ? record : throw new KeyNotFoundException("NPC Finder result is unavailable. Search again.");

    public NpcCatalogSearchResult Search(NpcCatalogSearchRequest request)
    {
        if (request.Kind is not (null or "" or "all" or "npc" or "creature" or "mount" or "player" or "other"))
            throw new ArgumentException("NPC kind must be all, npc, creature, mount, player or other.");
        var query = (request.Query ?? "").Trim();
        var tokens = Tokens(query);
        var lowered = query.Normalize().ToLowerInvariant();
        var numeric = query.Length > 0 && query.All(char.IsAsciiDigit);
        var rows = new List<(int Rank, NpcCatalogRecord Record)>();
        foreach (var record in Snapshot.Records)
        {
            var row = record.Row;
            if (!string.IsNullOrEmpty(request.Kind) && request.Kind != "all" && row.Kind != request.Kind) continue;
            if (request.HasArmor && !row.HasArmor) continue;
            int rank;
            if (numeric && row.CharacterId.ToString(CultureInfo.InvariantCulture) == query) rank = 0;
            else
            {
                var text = _search[row.Key];
                if (!tokens.All(token => text.Contains(token, StringComparison.Ordinal))) continue;
                rank = Rank(record, lowered);
            }
            rows.Add((rank, record));
        }
        if (numeric && rows.Any(static row => row.Rank == 0)) rows.RemoveAll(static row => row.Rank != 0);
        var ordered = rows.OrderBy(static row => row.Rank)
            .ThenBy(static row => row.Record.Row.DisplayName.Length == 0 ? 1 : 0)
            .ThenBy(static row => row.Record.Row.DisplayName, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static row => row.Record.Row.Key, StringComparer.Ordinal)
            .Select(static row => row.Record.Row).ToArray();
        var start = Math.Max(0, request.PageStart);
        var size = Math.Clamp(request.PageSize, 1, MaximumPageSize);
        return new(request.SessionId, ordered.Length, start, size, ordered.Skip(start).Take(size).ToArray(), Snapshot.Warnings);
    }

    public NpcWearersResult Wearers(string sessionId, string piece, int maximum)
    {
        var key = PieceKey(piece);
        var found = _wearers.GetValueOrDefault(key) ?? [];
        var wearers = found
            .Select(match => new NpcWearer(_records[match.Key].Row, match.AppearancePath, match.Piece.Section,
                match.Piece.Slot, match.Piece.PrefabName, match.Piece.ModelPath))
            .DistinctBy(static wearer => (wearer.Row.Key, wearer.AppearancePath, wearer.PrefabName, wearer.ModelPath))
            .OrderBy(static wearer => wearer.Row.DisplayName.Length == 0 ? 1 : 0)
            .ThenBy(static wearer => wearer.Row.DisplayName, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static wearer => wearer.Row.Key, StringComparer.Ordinal)
            .ThenBy(static wearer => wearer.AppearancePath, StringComparer.Ordinal).ToArray();
        var limit = Math.Clamp(maximum, 1, 1000);
        return new(sessionId, piece, wearers.Take(limit).ToArray(), wearers.Length, wearers.Length > limit);
    }

    // A piece is found by its model path, its model file name or its prefab name.
    internal static IEnumerable<string> PieceKeys(NpcPiece piece)
    {
        if (piece.ModelPath.Length > 0)
        {
            yield return "model:" + ArchiveCharacterReferences.Normalize(piece.ModelPath);
            yield return "file:" + Path.GetFileName(ArchiveCharacterReferences.Normalize(piece.ModelPath));
        }
        if (piece.PrefabName.Length > 0)
            yield return "prefab:" + Path.GetFileNameWithoutExtension(ArchiveCharacterReferences.Normalize(piece.PrefabName));
    }

    internal static string PieceKey(string value)
    {
        var normalized = ArchiveCharacterReferences.Normalize(value ?? "");
        if (normalized.Length == 0) throw new ArgumentException("Give a model path, a model file name or a prefab name.");
        var extension = Path.GetExtension(normalized);
        if (extension is ".pac" or ".pam" or ".pamlod")
            return normalized.Contains('/') ? "model:" + normalized : "file:" + normalized;
        return "prefab:" + Path.GetFileNameWithoutExtension(normalized);
    }

    // 1 exact English name, 2 English name starts with the query, 3 English name
    // contains it, 4 other languages, internal names, appearance files and pieces.
    private static int Rank(NpcCatalogRecord record, string query)
    {
        if (query.Length == 0) return 1;
        var name = record.Row.DisplayName.Normalize().ToLowerInvariant();
        if (name == query) return 1;
        if (name.StartsWith(query, StringComparison.Ordinal)) return 2;
        if (name.Contains(query, StringComparison.Ordinal)) return 3;
        if (record.Row.InternalName.Equals(query, StringComparison.OrdinalIgnoreCase)) return 3;
        return 4;
    }

    private static string SearchText(NpcCatalogRecord record)
    {
        var row = record.Row;
        var parts = new List<string> { row.DisplayName, row.InternalName, row.Key, row.AppearancePath };
        if (row.CharacterId != 0) parts.Add(row.CharacterId.ToString(CultureInfo.InvariantCulture));
        parts.AddRange(record.SearchNames);
        parts.AddRange(record.DisplayNames);
        foreach (var outfit in record.Outfits)
        {
            parts.Add(outfit.AppearancePath);
            foreach (var piece in outfit.Pieces)
            {
                parts.Add(piece.PrefabName);
                if (piece.ModelPath.Length > 0) parts.Add(Path.GetFileName(piece.ModelPath));
            }
        }
        return string.Join(' ', parts.Where(static part => !string.IsNullOrEmpty(part))).Normalize().ToLowerInvariant();
    }

    private static string[] Tokens(string query)
    {
        var normalized = new StringBuilder();
        foreach (var character in query.Normalize().ToLowerInvariant())
            normalized.Append(char.IsLetterOrDigit(character) ? character : ' ');
        return normalized.ToString().Split(' ', StringSplitOptions.RemoveEmptyEntries);
    }
}

namespace Cdmw.FullArchive.Contracts;

// NPC Finder: character name or ID -> appearance file -> worn pieces.
// Keys are "npc:<character id>" or "appearance:<normalized appearance path>".

public sealed record BuildNpcCatalogRequest(string SessionId);

public sealed record NpcCatalogStatistics(
    int AppearanceCount, int UnparsedAppearanceCount, int ArmorAppearanceCount, int ArmorEntryCount,
    int DistinctPrefabCount, int ResolvedPrefabCount, int MissingPrefabCount, int EmptyPrefabCount,
    int ModelPathCount, int UnresolvedLinkCount);

public sealed record BuildNpcCatalogResult(
    string SessionId, bool UsedCache, int NpcCount, int AppearanceRowCount,
    NpcCatalogStatistics Statistics, IReadOnlyList<string> Warnings);

public sealed record NpcCatalogSearchRequest(
    string SessionId, string Query = "", string? Kind = null, bool HasArmor = false,
    int PageStart = 0, int PageSize = 100);

public sealed record NpcCatalogRow(
    string Key, uint CharacterId, string DisplayName, string InternalName, string Kind,
    string SourceGroup, int VariantCount, int PieceCount, string Resolution, string AppearancePath,
    bool HasArmor);

public sealed record NpcCatalogSearchResult(
    string SessionId, int TotalMatches, int PageStart, int PageSize,
    IReadOnlyList<NpcCatalogRow> Rows, IReadOnlyList<string> Warnings);

public sealed record NpcPiece(
    string Section, string Slot, string PrefabName, long PrefabEntryId, string PrefabPath,
    long ModelEntryId, string ModelPath, string Preview, string Resolution, IReadOnlyList<int> ItemIds);

public sealed record NpcOutfit(
    int Variant, string AppearancePath, long AppearanceEntryId, string Resolution,
    IReadOnlyList<NpcPiece> Pieces, IReadOnlyList<string> Evidence);

public sealed record NpcOutfitRequest(string SessionId, string Key, string? AppearancePath = null);

public sealed record NpcOutfitResult(
    string SessionId, NpcCatalogRow Row, IReadOnlyList<NpcOutfit> Outfits,
    IReadOnlyList<string> OtherDisplayNames, bool ItemLinksAvailable);

public sealed record NpcWearersRequest(string SessionId, string Piece, int MaximumResults = 200);

public sealed record NpcWearer(
    NpcCatalogRow Row, string AppearancePath, string Section, string Slot, string PrefabName, string ModelPath);

public sealed record NpcWearersResult(
    string SessionId, string Piece, IReadOnlyList<NpcWearer> Wearers, int TotalCount, bool Truncated);

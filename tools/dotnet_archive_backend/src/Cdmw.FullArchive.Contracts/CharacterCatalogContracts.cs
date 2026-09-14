namespace Cdmw.FullArchive.Contracts;

public sealed record BuildCharacterCatalogRequest(string SessionId);

public sealed record BuildCharacterCatalogResult(
    string SessionId, bool UsedCache, int AssetCount, int AppearanceCount,
    int CandidateCount, int ResolvedCount, int UnresolvedCount, int ExcludedCount,
    IReadOnlyList<string> Warnings);

public sealed record CharacterCatalogSearchRequest(
    string SessionId, string Query = "", string View = "assets", string Tab = "bodies",
    string? Role = null, string? SourceGroup = null, string? BodyFamily = null,
    string? Resolution = null, string? RelatedKey = null, int PageStart = 0, int PageSize = 72,
    string? SelectionPurpose = null);

public sealed record CharacterCatalogRow(
    string Key, string View, string Role, string Label, string InternalName, string Path,
    string SourceGroup, string BodyFamily, string Resolution, string PreviewStatus,
    int ModelCount, int UsageCount, string Evidence, bool EmbeddedFace = false);

public sealed record CharacterCatalogFacet(string Field, string Value, int Count);

public sealed record CharacterCatalogSearchResult(
    string SessionId, int TotalMatches, int PageStart, int PageSize,
    IReadOnlyList<CharacterCatalogRow> Rows, IReadOnlyList<CharacterCatalogFacet> Facets,
    IReadOnlyList<string> Warnings);

public sealed record CharacterCatalogDetailRequest(string SessionId, string Key);

public sealed record CharacterCatalogFile(
    long EntryId, string Path, string Extension, string Relation, string SourcePamt);

public sealed record CharacterCatalogComponent(
    string Role, string Name, IReadOnlyList<long> ModelEntryIds,
    IReadOnlyList<long> ContextEntryIds, double Scale,
    IReadOnlyDictionary<string, string> Attributes, string Resolution);

public sealed record CharacterCatalogOwner(
    uint CharacterId, string InternalName, string DisplayName, string Evidence);

public sealed record CharacterCatalogDetailResult(
    string SessionId, CharacterCatalogRow Row, IReadOnlyList<ArchiveEntryDto> Models,
    IReadOnlyList<CharacterCatalogComponent> Components, IReadOnlyList<CharacterCatalogFile> Files,
    IReadOnlyList<CharacterCatalogOwner> Characters, IReadOnlyList<CharacterCatalogRow> Related,
    IReadOnlyList<string> Evidence, int TotalFileCount, int TotalRelatedCount,
    int TotalCharacterCount, bool Truncated, string AppearancePath, string ContextKey);

public sealed record CharacterCatalogScopeRequest(
    string SessionId, string Key, bool IncludeRelated = false, int MaximumResults = 4096);

public sealed record CharacterCatalogScopeResult(
    string SessionId, IReadOnlyList<long> EntryIds, int DirectCount, int TotalCount, bool Truncated);

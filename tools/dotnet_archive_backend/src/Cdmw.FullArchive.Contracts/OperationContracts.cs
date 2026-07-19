namespace Cdmw.FullArchive.Contracts;

public sealed record CacheHealthRequest(string PackageRoot);

public sealed record CacheHealthResult(
    string PackageRoot,
    string RootId,
    string State,
    string Reason,
    string? Fingerprint = null,
    string? GenerationId = null,
    long EntryCount = 0);

public sealed record OpenArchiveRequest(string PackageRoot, bool ForceRefresh = false);

public sealed record CreateQueryRequest(ArchiveQuery Query);

public sealed record FetchPageRequest(string QueryId, int PageStart = 0, int PageSize = 256);

public sealed record PrepareEntryRequest(
    string SessionId,
    long EntryId,
    bool IncludeContentAnalysis = false);

public sealed record PrepareEntriesRequest(
    string SessionId,
    IReadOnlyList<long> EntryIds,
    long? ContentAnalysisEntryId = null);

public sealed record PrepareEntryResult(
    ArchiveEntryRef Entry,
    string PreparedPath,
    long Size,
    string Sha256,
    string? Note = null,
    string? ContentAnalysisJsonPath = null,
    string? ContentAnalysisTextPath = null,
    string? ContentAnalysisVersion = null);

public sealed record PrepareEntriesResult(
    string SessionId,
    IReadOnlyList<PrepareEntryResult> Items,
    int Requested,
    int Prepared,
    long TotalBytes);

public sealed record ArchiveTextSearchRequest(
    string SessionId,
    string Query,
    bool UseRegularExpression = false,
    bool CaseSensitive = false,
    string? PathFilter = null,
    IReadOnlyList<string>? Extensions = null,
    int MaximumMatches = 2_000,
    int ContextCharacters = 160,
    int RegexTimeoutMilliseconds = 1_000,
    int BatchSize = 128);

public sealed record ArchiveTextMatch(
    long EntryId,
    string Path,
    int Line,
    int Column,
    int Length,
    string Context,
    string Package = "");

public sealed record ArchiveTextSearchBatch(
    string SessionId,
    long FilesScanned,
    long FilesMatched,
    long BytesRead,
    IReadOnlyList<ArchiveTextMatch> Matches,
    bool IsFinal,
    bool LimitReached,
    IReadOnlyList<string> Warnings);

public enum ArchiveExportSelectionKind
{
    EntryIds,
    Query,
    Folder,
    Family,
}

public enum ArchiveExportCollisionPolicy
{
    Skip,
    Overwrite,
    Rename,
    Cancel,
}

public sealed record ArchiveExportRequest(
    string SessionId,
    ArchiveExportSelectionKind SelectionKind,
    string Destination,
    IReadOnlyList<long>? EntryIds = null,
    string? QueryId = null,
    string? FolderPath = null,
    long? FamilyEntryId = null,
    ArchiveExportCollisionPolicy CollisionPolicy = ArchiveExportCollisionPolicy.Skip,
    bool WriteManifest = true,
    bool IncludePackageRoot = false,
    bool ReplaceDestination = false,
    IReadOnlyList<string>? Extensions = null);

public sealed record ArchiveExportItem(
    string SourcePath,
    string? OutputPath,
    string Status,
    string? Message = null);

public sealed record ArchiveExportResult(
    string SessionId,
    long Requested,
    long Exported,
    long Skipped,
    long Failed,
    bool Cancelled,
    string? ManifestPath,
    IReadOnlyList<ArchiveExportItem> Items,
    bool ItemsTruncated);

public sealed record ProgressUpdate(long Completed, long Total, string Phase, string? CurrentItem = null);

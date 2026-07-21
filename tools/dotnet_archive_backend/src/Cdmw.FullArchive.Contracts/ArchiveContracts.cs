namespace Cdmw.FullArchive.Contracts;

public sealed record ArchiveDurableIdentity(
    string NormalizedPath,
    string SourcePamt,
    int PazIndex,
    long ArchiveOffset);

public sealed record ArchiveSessionHandle(
    string SessionId,
    string PackageRoot,
    string Fingerprint,
    long EntryCount,
    int IndexVersion,
    bool CacheHit,
    IReadOnlyList<string>? DiscoveryWarnings = null);

public sealed record ArchiveEntryRef(
    string SessionId,
    long EntryId,
    ArchiveDurableIdentity Identity,
    string DisplayPath);

public sealed record ArchiveEntryDto(
    string SessionId,
    long EntryId,
    ArchiveDurableIdentity Identity,
    string Path,
    string SourcePamt,
    string PazFile,
    int PazIndex,
    long Offset,
    long StoredSize,
    long OriginalSize,
    int Flags,
    string Extension,
    string Package,
    ArchiveEntryRole Role,
    string Category,
    bool IsPreviewable,
    string KnownName = "",
    string ExactName = "",
    string NameEvidence = "",
    bool IsActiveOverride = false,
    string OverrideState = "",
    string TypeDisplay = "")
{
    public bool IsCompressed => StoredSize != OriginalSize;
    public int CompressionType => Flags & 0x0F;
    public bool IsEncrypted => ((Flags >> 4) & 0x0F) != 0;
    public int EncryptionType => (Flags >> 4) & 0x0F;
    public string Name => System.IO.Path.GetFileName(Path.Replace('/', System.IO.Path.DirectorySeparatorChar));
}

public enum ArchiveEntryRole
{
    Other,
    Model,
    Animation,
    Physics,
    Metadata,
    Video,
    Audio,
    UserInterface,
    Impostor,
    Normal,
    Material,
    Image,
    Text,
}

public enum ArchiveExtensionCategory
{
    ModelMeshPhysics,
    TextureImage,
    MaterialMetadata,
    AnimationScene,
    AudioVideo,
    UserInterfaceText,
    Other,
}

public enum ArchiveViewMode
{
    Folders,
    Categories,
    CategoriesAndFolders,
    Flat,
}

public enum ArchiveSortField
{
    Path,
    Name,
    KnownName,
    ExactName,
    NameEvidence,
    Extension,
    Package,
    OriginalSize,
    StoredSize,
    Compression,
    Role,
    Category,
    ActiveOverride,
}

public sealed record ArchiveQuery(
    string SessionId,
    string? IncludeText = null,
    string? ExcludeText = null,
    IReadOnlyList<string>? Extensions = null,
    IReadOnlyList<string>? Packages = null,
    string? Folder = null,
    IReadOnlyList<ArchiveEntryRole>? Roles = null,
    IReadOnlyList<string>? TechnicalSuffixes = null,
    long? MinimumSize = null,
    bool PreviewableOnly = false,
    bool ActiveOverridesOnly = false,
    ArchiveViewMode ViewMode = ArchiveViewMode.Flat,
    ArchiveSortField SortField = ArchiveSortField.Path,
    bool SortActive = false,
    bool SortDescending = false,
    IReadOnlyList<long>? EntryIds = null);

public sealed record ArchiveQueryHandle(
    string SessionId,
    string QueryId,
    long Generation,
    long TotalMatches);

public sealed record ArchivePage(
    string SessionId,
    string QueryId,
    long Generation,
    long TotalMatches,
    int PageStart,
    IReadOnlyList<ArchiveEntryDto> Rows);

public sealed record ArchiveChildrenRequest(
    string QueryId,
    string? ParentPath,
    string? Category,
    int Limit = 512,
    int Offset = 0,
    bool IncludePackageRoot = false);

public sealed record ArchiveChildNode(
    string Key,
    string Label,
    bool IsFolder,
    long MatchCount,
    ArchiveEntryDto? Entry = null);

public sealed record ArchiveChildrenResult(
    string SessionId,
    string QueryId,
    IReadOnlyList<ArchiveChildNode> Children,
    bool Truncated,
    int Offset = 0,
    long TotalChildren = 0,
    int? NextOffset = null);

public sealed record ArchiveFacet(string Key, string Label, long Count);

public sealed record ArchiveFacetsResult(
    string SessionId,
    IReadOnlyList<ArchiveFacet> Extensions,
    IReadOnlyList<ArchiveFacet> Packages,
    IReadOnlyList<ArchiveFacet> Roles,
    IReadOnlyList<ArchiveFacet> Categories);

public enum ArchiveLookupKind
{
    EntryIds,
    Identities,
    ExactPaths,
    Basenames,
    Extensions,
    Roles,
}

public sealed record ArchiveLookupRequest(
    string SessionId,
    ArchiveLookupKind Kind,
    IReadOnlyList<long>? EntryIds = null,
    IReadOnlyList<ArchiveDurableIdentity>? Identities = null,
    IReadOnlyList<string>? Values = null,
    IReadOnlyList<ArchiveEntryRole>? Roles = null,
    int Limit = 512,
    string? QueryId = null);

public sealed record ArchiveLookupResult(
    string SessionId,
    IReadOnlyList<ArchiveEntryDto> Entries,
    long TotalMatches,
    bool Truncated,
    IReadOnlyList<long>? QueryRows = null);

public enum ArchiveAssociationPurpose
{
    Family,
    Preview,
}

public sealed record ArchiveAssociationRequest(
    string SessionId,
    long EntryId,
    int Limit = 256,
    ArchiveAssociationPurpose Purpose = ArchiveAssociationPurpose.Family);

public sealed record ArchiveAssociationResult(
    string SessionId,
    long EntryId,
    IReadOnlyList<ArchiveEntryDto> Candidates,
    long TotalCandidates,
    bool Truncated);

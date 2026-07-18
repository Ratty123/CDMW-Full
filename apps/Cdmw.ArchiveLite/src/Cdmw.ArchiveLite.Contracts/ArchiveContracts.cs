namespace Cdmw.ArchiveLite.Contracts;

public sealed record ArchiveEntryDto(
    long EntryId,
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
    bool IsPreviewable,
    string KnownName = "",
    string NameEvidence = "")
{
    public bool IsCompressed => StoredSize != OriginalSize;
    public int CompressionType => Flags & 0x0F;
    public bool IsEncrypted => (Flags >> 4) != 0;
    public int EncryptionType => (Flags >> 4) & 0x0F;
    public string Name => System.IO.Path.GetFileName(Path.Replace('/', System.IO.Path.DirectorySeparatorChar));
    public string CompressionLabel => IsCompressed ? $"Type {CompressionType}" : "None";
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
    NameEvidence,
    Extension,
    Package,
    OriginalSize,
    StoredSize,
    Compression,
    Role,
}

public sealed record OpenArchiveRequest(string PackageRoot, bool ForceRefresh = false);

public sealed record OpenArchiveResult(
    string SessionId,
    string PackageRoot,
    string Fingerprint,
    long EntryCount,
    int IndexVersion,
    bool UsedCachedIndex,
    IReadOnlyList<string> Warnings);

public sealed record ArchiveQuerySpec(
    string SessionId,
    string? PathText = null,
    IReadOnlyList<string>? Extensions = null,
    string? Package = null,
    string? Folder = null,
    IReadOnlyList<ArchiveEntryRole>? Roles = null,
    long? MinimumSize = null,
    bool PreviewableOnly = false,
    ArchiveViewMode ViewMode = ArchiveViewMode.Flat,
    ArchiveSortField SortField = ArchiveSortField.Path,
    bool SortDescending = false,
    int PageStart = 0,
    int PageSize = 256);

public sealed record ArchivePageResult(
    string SessionId,
    long Generation,
    long TotalMatches,
    int PageStart,
    IReadOnlyList<ArchiveEntryDto> Entries,
    IReadOnlyList<string> Folders,
    IReadOnlyDictionary<string, long> Categories);

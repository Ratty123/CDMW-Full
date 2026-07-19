namespace Cdmw.ArchiveLite.Contracts;

public enum ExportCollisionPolicy
{
    Skip,
    Overwrite,
    Cancel,
}

public enum ExportManifestFormat
{
    None,
    Json,
    Csv,
    Text,
}

public enum ExportKind
{
    RawEntries,
    FolderTree,
    FilteredEntries,
    ManifestOnly,
    Wav,
    Obj,
    Fbx,
    Glb,
    HkxJson,
    HkxXml,
    StructuredJson,
    DependencySet,
}

public enum ExportPathLayout
{
    PreserveStructure,
    FilesOnly,
}

public sealed record ExportPlanRequest(
    string? SessionId,
    ExportKind Kind,
    string Destination,
    IReadOnlyList<long> EntryIds,
    IReadOnlyList<string>? LoosePaths,
    string? LooseSourceRoot = null,
    ExportCollisionPolicy CollisionPolicy = ExportCollisionPolicy.Skip,
    ExportManifestFormat ManifestFormat = ExportManifestFormat.Json,
    string? SingleOutputPath = null,
    string? FolderPath = null,
    ExportPathLayout PathLayout = ExportPathLayout.PreserveStructure);

public sealed record ExportItemResult(string SourcePath, string? OutputPath, string Status, string? Message);

public sealed record ExportPlanResult(
    long Requested,
    long Exported,
    long Skipped,
    long Failed,
    bool Cancelled,
    string? ManifestPath,
    IReadOnlyList<ExportItemResult> Items,
    bool ItemsTruncated);

public sealed record ArchiveLiteManifest(
    string Schema,
    string ProductVersion,
    DateTimeOffset CreatedUtc,
    string? ArchiveFingerprint,
    IReadOnlyList<ArchiveLiteManifestEntry> Entries,
    IReadOnlyList<ArchiveLiteLooseManifestEntry> LooseFiles);

public sealed record ArchiveLiteManifestEntry(
    string Path,
    string Package,
    string SourcePamt,
    string PazFile,
    int PazIndex,
    long Offset,
    long StoredSize,
    long OriginalSize,
    int Flags,
    int CompressionType,
    int EncryptionType,
    ArchiveEntryRole Role,
    string? OutputPath);

public sealed record ArchiveLiteLooseManifestEntry(
    string SourcePath,
    long Size,
    string OutputPath);

namespace Cdmw.ArchiveLite.Contracts;

public sealed record FindAssociatedAssetsRequest(
    string SessionId,
    long EntryId,
    int MaximumResults = 128);

public sealed record FindAssociatedAssetsResult(
    string SessionId,
    long EntryId,
    IReadOnlyList<AssociatedAssetDto> Assets,
    long ScannedEntries,
    bool Truncated);

public sealed record AssociatedAssetDto(
    ArchiveEntryDto Entry,
    AssociatedAssetCategory Category,
    AssociationEvidence Evidence,
    string EvidenceSource);

public enum AssociatedAssetCategory
{
    Model,
    Material,
    Texture,
    Physics,
    MeshMetadata,
    PrefabMetadata,
    SkeletonRig,
    AnimationMotion,
    AudioVideo,
    UserInterface,
    Other,
}

public enum AssociationEvidence
{
    ExplicitReference,
    ExactCompanion,
    SameStem,
    CachedFamily,
}

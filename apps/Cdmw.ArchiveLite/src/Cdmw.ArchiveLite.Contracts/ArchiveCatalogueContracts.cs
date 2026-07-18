namespace Cdmw.ArchiveLite.Contracts;

public sealed record ArchiveFacetsRequest(string SessionId);

public sealed record ArchiveFacetsResult(
    string SessionId,
    IReadOnlyList<ArchiveExtensionFacet> Extensions);

public sealed record ArchiveExtensionFacet(
    string Extension,
    long Count,
    ArchiveExtensionCategory Category);

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

public sealed record BuildNameIndexRequest(string SessionId);

public sealed record BuildNameIndexResult(
    string SessionId,
    bool Available,
    bool UsedCache,
    long ExactNameCount,
    long RelatedNameCount,
    string? Warning = null);

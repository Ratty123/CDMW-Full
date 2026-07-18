namespace Cdmw.ArchiveLite.Contracts;

public enum PreviewKind
{
    Metadata,
    Text,
    Image,
    Audio,
    Video,
    Model,
    Hkx,
    StructuredData,
    Hex,
}

public sealed record PreviewRequest(
    string SessionId,
    long EntryId,
    int TextCharacterLimit = 120_000,
    int BinaryByteLimit = 256);

public sealed record PreviewResult(
    string SessionId,
    long EntryId,
    PreviewKind Kind,
    string Title,
    string Metadata,
    string? Text = null,
    string? ArtifactPath = null,
    string? MediaKind = null,
    IReadOnlyList<string>? Warnings = null);

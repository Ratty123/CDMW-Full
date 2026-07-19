using System.Text.Json;
using System.Text.Json.Serialization;

namespace Cdmw.Archive.Content;

public sealed record ArchiveContentManifest(
    int SchemaVersion,
    IReadOnlyList<ArchiveContentCapability> Extensions);

public sealed record ArchiveContentCapability(
    string Extension,
    string Role,
    string Group,
    string Container,
    string Analyzer,
    string Maturity,
    bool Readable,
    bool Structured,
    bool References,
    bool Visual,
    bool Playback,
    IReadOnlyList<string> Exports,
    string? UnsupportedReason = null);

public sealed record ArchiveContentDocument(
    int SchemaVersion,
    string AnalyzerVersion,
    string Extension,
    string ContentKind,
    string Title,
    string Summary,
    string Maturity,
    long SourceLength,
    IReadOnlyList<ArchiveContentSection> Sections,
    IReadOnlyList<ArchiveContentReference> References,
    IReadOnlyList<string> Warnings,
    bool Truncated,
    string? RawText = null,
    string? UnsupportedReason = null,
    ArchiveContentModel? Model = null)
{
    public string ToReadableText()
    {
        var lines = new List<string>
        {
            Title,
            Summary,
            $"Format: {Extension} | Analyzer: {AnalyzerVersion} | Maturity: {Maturity}",
            $"Source bytes: {SourceLength:N0}" + (Truncated ? " | bounded analysis" : string.Empty),
        };
        foreach (var section in Sections)
        {
            lines.Add(string.Empty);
            lines.Add(section.Title);
            foreach (var field in section.Fields)
            {
                var offset = field.Offset is null ? string.Empty : $" @ 0x{field.Offset.Value:X}";
                var confidence = string.IsNullOrWhiteSpace(field.Confidence) ? string.Empty : $" [{field.Confidence}]";
                lines.Add($"{field.Name}: {field.Value}{offset}{confidence}");
            }
            lines.AddRange(section.Lines);
        }
        if (References.Count > 0)
        {
            lines.Add(string.Empty);
            lines.Add("References");
            lines.AddRange(References.Select(reference =>
                $"{reference.Value} | {reference.Kind} | {reference.Confidence}" +
                (reference.Offset is null ? string.Empty : $" @ 0x{reference.Offset.Value:X}")));
        }
        if (Warnings.Count > 0)
        {
            lines.Add(string.Empty);
            lines.Add("Warnings");
            lines.AddRange(Warnings);
        }
        if (!string.IsNullOrWhiteSpace(RawText))
        {
            lines.Add(string.Empty);
            lines.Add("Raw text");
            lines.Add(RawText);
        }
        return string.Join(Environment.NewLine, lines);
    }
}

public sealed record ArchiveContentSection(
    string Title,
    IReadOnlyList<ArchiveContentField> Fields,
    IReadOnlyList<string> Lines);

public sealed record ArchiveContentField(
    string Name,
    string Value,
    string ValueType = "string",
    long? Offset = null,
    int? Size = null,
    string Confidence = "proven",
    string? Evidence = null);

public sealed record ArchiveContentReference(
    string Value,
    string Kind,
    string Confidence,
    long? Offset = null,
    string? Evidence = null);

public sealed record ArchiveContentModel(
    string Format,
    int LodCount,
    int VertexCount,
    int IndexCount,
    int DrawCount,
    int MaterialCount,
    IReadOnlyList<int> LodVertexCounts,
    IReadOnlyList<int> LodIndexCounts,
    IReadOnlyList<int> LodDrawCounts,
    IReadOnlyList<float> BoundsMinimum,
    IReadOnlyList<float> BoundsMaximum);

public static class ArchiveContentJson
{
    public static JsonSerializerOptions Options { get; } = CreateOptions();

    public static string Serialize(ArchiveContentDocument document, bool indented = true)
    {
        ArgumentNullException.ThrowIfNull(document);
        var options = new JsonSerializerOptions(Options) { WriteIndented = indented };
        return JsonSerializer.Serialize(document, options);
    }

    private static JsonSerializerOptions CreateOptions()
    {
        var options = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            PropertyNameCaseInsensitive = true,
            WriteIndented = false,
        };
        options.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower));
        return options;
    }
}

using System.Text;
using System.Text.Json;
using System.Xml.Linq;

namespace Cdmw.Archive.Content;

internal static class ArchiveStructuredAnalyzers
{
    public static ArchiveContentDocument AnalyzeText(
        ArchiveContentCapability capability,
        string path,
        ReadOnlyMemory<byte> payload,
        long sourceLength,
        bool truncated)
    {
        var rawText = ArchiveContentBinary.DecodeText(payload.Span, out var encoding).TrimEnd('\0');
        var warnings = new List<string>();
        var fields = new List<ArchiveContentField>
        {
            new("Encoding", encoding),
            new("Line count", CountLines(rawText).ToString("N0"), "integer"),
            new("Character count", rawText.Length.ToString("N0"), "integer"),
        };
        ValidateStructuredText(capability.Analyzer, rawText, fields, warnings);
        var strings = ArchiveContentBinary.ExtractStrings(payload.Span);
        var references = ArchiveContentBinary.ExtractReferences(strings);
        var displayText = rawText.Length <= 240_000 ? rawText : rawText[..240_000];
        if (displayText.Length != rawText.Length)
        {
            warnings.Add("Readable text was capped at 240,000 characters for responsive preview.");
            truncated = true;
        }
        return Document(
            capability,
            path,
            sourceLength,
            truncated,
            $"Readable {capability.Extension} text",
            $"Decoded {encoding} text with {CountLines(rawText):N0} line(s).",
            [new ArchiveContentSection("Text metadata", fields, Array.Empty<string>())],
            references,
            warnings,
            rawText: displayText);
    }

    public static ArchiveContentDocument AnalyzeDds(
        ArchiveContentCapability capability,
        string path,
        ReadOnlyMemory<byte> payload,
        long sourceLength,
        bool truncated)
    {
        var data = payload.Span;
        var fields = HeaderFields(data);
        var warnings = new List<string>();
        if (data.Length >= 128 && data[..4].SequenceEqual("DDS "u8))
        {
            fields.Add(new("Header size", ArchiveContentBinary.ReadUInt32(data, 4).ToString(), "uint32", 4, 4));
            fields.Add(new("Height", ArchiveContentBinary.ReadUInt32(data, 12).ToString("N0"), "uint32", 12, 4));
            fields.Add(new("Width", ArchiveContentBinary.ReadUInt32(data, 16).ToString("N0"), "uint32", 16, 4));
            fields.Add(new("Mip count", ArchiveContentBinary.ReadUInt32(data, 28).ToString("N0"), "uint32", 28, 4));
            var fourCc = Encoding.ASCII.GetString(data.Slice(84, 4)).TrimEnd('\0');
            fields.Add(new("Pixel format", string.IsNullOrWhiteSpace(fourCc) ? "uncompressed/legacy" : fourCc, "fourcc", 84, 4));
            if (fourCc == "DX10" && data.Length >= 148)
            {
                fields.Add(new("DXGI format", ArchiveContentBinary.ReadUInt32(data, 128).ToString(), "uint32", 128, 4));
                fields.Add(new("Resource dimension", ArchiveContentBinary.ReadUInt32(data, 132).ToString(), "uint32", 132, 4));
                fields.Add(new("Array size", ArchiveContentBinary.ReadUInt32(data, 140).ToString("N0"), "uint32", 140, 4));
            }
        }
        else
        {
            warnings.Add("The DDS magic/header is missing or truncated; fields beyond the bounded header were not decoded.");
        }
        var strings = ArchiveContentBinary.ExtractStrings(data);
        return Document(
            capability, path, sourceLength, truncated,
            "DirectDraw Surface metadata",
            "Decoded the stable DDS header. Pixel conversion remains owned by the native texture pipeline.",
            [new ArchiveContentSection("DDS header", fields, Array.Empty<string>())],
            ArchiveContentBinary.ExtractReferences(strings), warnings);
    }

    public static ArchiveContentDocument AnalyzeBnk(
        ArchiveContentCapability capability,
        string path,
        ReadOnlyMemory<byte> payload,
        long sourceLength,
        bool truncated)
    {
        var data = payload.Span;
        var fields = HeaderFields(data);
        var lines = new List<string>();
        var warnings = new List<string>();
        var offset = 0;
        while (offset <= data.Length - 8 && lines.Count < 128)
        {
            var id = Encoding.ASCII.GetString(data.Slice(offset, 4));
            var size = ArchiveContentBinary.ReadUInt32(data, offset + 4);
            var end = (long)offset + 8 + size;
            lines.Add($"0x{offset:X8} {id} | {size:N0} byte(s)");
            if (!id.All(character => character is >= 'A' and <= 'Z') || end > data.Length)
            {
                warnings.Add($"Chunk at 0x{offset:X} is not fully available or has an unexpected identifier.");
                break;
            }
            offset = checked((int)end);
        }
        fields.Add(new("Parsed chunk count", lines.Count.ToString("N0"), "integer", Confidence: "proven"));
        var strings = ArchiveContentBinary.ExtractStrings(data);
        return Document(
            capability, path, sourceLength, truncated,
            "Wwise sound bank metadata",
            "Decoded the BNK chunk envelope and exposed bounded names/references; HIRC object semantics remain heuristic.",
            [new ArchiveContentSection("BNK chunks", fields, lines), ArchiveContentBinary.BuildStringSection(strings)],
            ArchiveContentBinary.ExtractReferences(strings), warnings);
    }

    public static ArchiveContentDocument AnalyzeMeshInfo(
        ArchiveContentCapability capability,
        string path,
        ReadOnlyMemory<byte> payload,
        long sourceLength,
        bool truncated)
    {
        var data = payload.Span;
        var strings = ArchiveContentBinary.ExtractStrings(data);
        var fields = HeaderFields(data);
        fields.Add(new("Printable string count", strings.Count.ToString("N0"), "integer", Confidence: "proven"));
        var sections = new List<ArchiveContentSection>
        {
            new("Container", fields, Array.Empty<string>()),
            BuildKeywordGroups(strings),
            BuildCandidateIntegers(data),
            BuildCandidateVectors(data),
            ArchiveContentBinary.BuildStringSection(strings),
        };
        return Document(
            capability, path, sourceLength, truncated,
            "MeshInfo readable analysis",
            "Extracted field/type names, asset references, and bounded numeric layout candidates. Unknown offsets remain explicitly heuristic.",
            sections,
            ArchiveContentBinary.ExtractReferences(strings),
            ["MeshInfo does not yet have a proven public schema; candidate numbers and vectors require comparison with the paired model." ]);
    }

    public static ArchiveContentDocument AnalyzeMedia(
        ArchiveContentCapability capability,
        string path,
        ReadOnlyMemory<byte> payload,
        long sourceLength,
        bool truncated)
    {
        var data = payload.Span;
        var fields = HeaderFields(data);
        var warnings = new List<string>();
        if (data.Length >= 12 && data[..4].SequenceEqual("RIFF"u8))
        {
            fields.Add(new("RIFF size", ArchiveContentBinary.ReadUInt32(data, 4).ToString("N0"), "uint32", 4, 4));
            fields.Add(new("RIFF kind", Encoding.ASCII.GetString(data.Slice(8, 4)), "fourcc", 8, 4));
            DecodeWaveFormat(data, fields, warnings);
        }
        else if (data.Length >= 4 && data[..4].SequenceEqual("OggS"u8))
        {
            fields.Add(new("Container", "Ogg", Offset: 0, Size: 4));
        }
        else if (data.Length >= 12 && data.Slice(4, 4).SequenceEqual("ftyp"u8))
        {
            fields.Add(new("Container", "ISO base media", Offset: 4, Size: 4));
            fields.Add(new("Brand", Encoding.ASCII.GetString(data.Slice(8, 4)), "fourcc", 8, 4));
        }
        else
        {
            warnings.Add("Only bounded header metadata is available for this media payload.");
        }
        var strings = ArchiveContentBinary.ExtractStrings(data);
        return Document(
            capability, path, sourceLength, truncated,
            $"{capability.Extension} media metadata",
            "Decoded stable container/header fields where present. Playback and conversion remain codec-dependent.",
            [new ArchiveContentSection("Media header", fields, Array.Empty<string>())],
            ArchiveContentBinary.ExtractReferences(strings), warnings);
    }

    public static ArchiveContentDocument AnalyzeHkx(
        ArchiveContentCapability capability,
        string path,
        ReadOnlyMemory<byte> payload,
        long sourceLength,
        bool truncated)
    {
        var strings = ArchiveContentBinary.ExtractStrings(payload.Span);
        var fields = HeaderFields(payload.Span);
        var typeLines = strings
            .Where(item => item.Value.Contains("hk", StringComparison.OrdinalIgnoreCase) ||
                           item.Value.Contains("Havok", StringComparison.OrdinalIgnoreCase))
            .Take(160)
            .Select(item => $"0x{item.Offset:X8} {item.Value}")
            .ToArray();
        fields.Add(new("Havok/type string count", typeLines.Length.ToString("N0"), "integer", Confidence: "heuristic"));
        return Document(
            capability, path, sourceLength, truncated,
            "Havok container analysis",
            "Exposed Havok SDK/type names and referenced assets without claiming a complete object-graph decode.",
            [new ArchiveContentSection("Container", fields, typeLines), ArchiveContentBinary.BuildStringSection(strings)],
            ArchiveContentBinary.ExtractReferences(strings),
            ["Geometry, skeleton, and animation object graphs are not reconstructed from HKX/HKT yet."]);
    }

    public static ArchiveContentDocument AnalyzePab(
        ArchiveContentCapability capability,
        string path,
        ReadOnlyMemory<byte> payload,
        long sourceLength,
        bool truncated)
    {
        var strings = ArchiveContentBinary.ExtractStrings(payload.Span);
        var boneLines = strings
            .Where(item => LooksLikeBone(item.Value))
            .Take(200)
            .Select(item => $"0x{item.Offset:X8} {item.Value}")
            .ToArray();
        var fields = HeaderFields(payload.Span);
        fields.Add(new("Candidate bone/name count", boneLines.Length.ToString("N0"), "integer", Confidence: "heuristic"));
        return Document(
            capability, path, sourceLength, truncated,
            "PAB skeleton/name analysis",
            "Extracted skeleton/name candidates and referenced assets; transforms and hierarchy are not yet proven.",
            [new ArchiveContentSection("PAB candidates", fields, boneLines), ArchiveContentBinary.BuildStringSection(strings)],
            ArchiveContentBinary.ExtractReferences(strings),
            ["Bone names are heuristic string classifications, not a verified skeleton hierarchy."]);
    }

    public static ArchiveContentDocument AnalyzePathc(
        ArchiveContentCapability capability,
        string path,
        ReadOnlyMemory<byte> payload,
        long sourceLength,
        bool truncated)
    {
        var generic = AnalyzeStructured(capability, path, payload, sourceLength, truncated);
        return generic with
        {
            Title = "PATHC path-container analysis",
            Summary = "Exposed bounded path names, references, header integers, and vector candidates without assuming an undocumented route schema.",
            Warnings = [.. generic.Warnings, "Path nodes and connectivity remain candidate data until validated against known PATHC samples."],
        };
    }

    public static ArchiveContentDocument AnalyzeStructured(
        ArchiveContentCapability capability,
        string path,
        ReadOnlyMemory<byte> payload,
        long sourceLength,
        bool truncated)
    {
        var data = payload.Span;
        var strings = ArchiveContentBinary.ExtractStrings(data);
        return Document(
            capability, path, sourceLength, truncated,
            $"{capability.Extension} structured analysis",
            $"Decoded bounded header, string, reference, and numeric candidates using the shared {capability.Analyzer} analyzer.",
            [
                new ArchiveContentSection("Container", HeaderFields(data), Array.Empty<string>()),
                BuildCandidateIntegers(data),
                ArchiveContentBinary.BuildStringSection(strings),
            ],
            ArchiveContentBinary.ExtractReferences(strings),
            ["Undocumented fields are labeled candidate/heuristic and may require paired-file interpretation." ]);
    }

    public static ArchiveContentDocument AnalyzeGeneric(
        ArchiveContentCapability capability,
        string path,
        ReadOnlyMemory<byte> payload,
        long sourceLength,
        bool truncated)
    {
        var strings = ArchiveContentBinary.ExtractStrings(payload.Span);
        var warnings = new List<string>();
        if (!string.IsNullOrWhiteSpace(capability.UnsupportedReason)) warnings.Add(capability.UnsupportedReason);
        warnings.Add("No format-specific structural decoder is registered; this view is bounded binary evidence only.");
        return Document(
            capability, path, sourceLength, truncated,
            $"{capability.Extension} binary analysis",
            "Shows header bytes, printable strings, and likely asset references without claiming a schema decode.",
            [
                new ArchiveContentSection("Header", HeaderFields(payload.Span), Array.Empty<string>()),
                ArchiveContentBinary.BuildStringSection(strings),
            ],
            ArchiveContentBinary.ExtractReferences(strings), warnings);
    }

    private static ArchiveContentDocument Document(
        ArchiveContentCapability capability,
        string path,
        long sourceLength,
        bool truncated,
        string title,
        string summary,
        IReadOnlyList<ArchiveContentSection> sections,
        IReadOnlyList<ArchiveContentReference> references,
        IReadOnlyList<string> warnings,
        string? rawText = null) =>
        new(
            1,
            ArchiveContentAnalyzer.AnalyzerVersion,
            capability.Extension,
            capability.Analyzer,
            title,
            $"{Path.GetFileName(path)}: {summary}",
            capability.Maturity,
            sourceLength,
            sections,
            references,
            warnings,
            truncated,
            rawText,
            capability.UnsupportedReason);

    private static List<ArchiveContentField> HeaderFields(ReadOnlySpan<byte> data) =>
    [
        new("Header ASCII", ArchiveContentBinary.HeaderAscii(data), "ascii", 0, Math.Min(data.Length, 16)),
        new("Header hex", ArchiveContentBinary.HeaderHex(data), "hex", 0, Math.Min(data.Length, 64)),
        new("Analyzed bytes", data.Length.ToString("N0"), "integer"),
    ];

    private static ArchiveContentSection BuildKeywordGroups(IReadOnlyList<ExtractedString> strings)
    {
        string Category(string value)
        {
            var lower = value.ToLowerInvariant();
            if (lower.Contains("bound")) return "Bounds";
            if (lower.Contains("socket") || lower.Contains("attach")) return "Sockets/attachments";
            if (lower.Contains("break") || lower.Contains("destroy")) return "Breakable";
            if (lower.Contains("collision") || lower.Contains("physics")) return "Collision/physics";
            if (lower.Contains("tree") || lower.Contains("branch") || lower.Contains("leaf")) return "Tree/vegetation";
            if (lower.Contains("mesh") || lower.Contains("model") || lower.Contains("lod")) return "Model/LOD";
            return "Other";
        }
        var lines = strings
            .GroupBy(item => Category(item.Value))
            .OrderBy(group => group.Key, StringComparer.Ordinal)
            .SelectMany(group => new[] { $"[{group.Key}]" }.Concat(
                group.Take(64).Select(item => $"0x{item.Offset:X8} {item.Value}")))
            .Take(240)
            .ToArray();
        return new ArchiveContentSection("Named fields/types by likely purpose", Array.Empty<ArchiveContentField>(), lines);
    }

    private static ArchiveContentSection BuildCandidateIntegers(ReadOnlySpan<byte> data)
    {
        var fields = new List<ArchiveContentField>();
        var limit = Math.Min(data.Length - data.Length % 4, 512);
        for (var offset = 0; offset < limit && fields.Count < 32; offset += 4)
        {
            var value = ArchiveContentBinary.ReadUInt32(data, offset);
            if (value is 0 or > 10_000_000) continue;
            fields.Add(new("Candidate u32", value.ToString("N0"), "uint32", offset, 4, "candidate"));
        }
        return new ArchiveContentSection("Candidate header integers", fields, Array.Empty<string>());
    }

    private static ArchiveContentSection BuildCandidateVectors(ReadOnlySpan<byte> data)
    {
        var fields = new List<ArchiveContentField>();
        var limit = Math.Min(data.Length - data.Length % 4, 1024);
        for (var offset = 0; offset <= limit - 12 && fields.Count < 16; offset += 4)
        {
            var x = ArchiveContentBinary.ReadSingle(data, offset);
            var y = ArchiveContentBinary.ReadSingle(data, offset + 4);
            var z = ArchiveContentBinary.ReadSingle(data, offset + 8);
            if (!float.IsFinite(x) || !float.IsFinite(y) || !float.IsFinite(z)) continue;
            if (Math.Abs(x) > 1e7 || Math.Abs(y) > 1e7 || Math.Abs(z) > 1e7) continue;
            if (Math.Abs(x) < 1e-5 && Math.Abs(y) < 1e-5 && Math.Abs(z) < 1e-5) continue;
            fields.Add(new(
                "Candidate float3",
                $"({ArchiveContentBinary.FormatSingle(x)}, {ArchiveContentBinary.FormatSingle(y)}, {ArchiveContentBinary.FormatSingle(z)})",
                "float3", offset, 12, "candidate"));
        }
        return new ArchiveContentSection("Candidate vectors", fields, Array.Empty<string>());
    }

    private static void DecodeWaveFormat(
        ReadOnlySpan<byte> data,
        ICollection<ArchiveContentField> fields,
        ICollection<string> warnings)
    {
        var offset = 12;
        while (offset <= data.Length - 8)
        {
            var id = Encoding.ASCII.GetString(data.Slice(offset, 4));
            var size = ArchiveContentBinary.ReadUInt32(data, offset + 4);
            var content = offset + 8;
            if ((long)content + size > data.Length) break;
            if (id == "fmt " && size >= 16)
            {
                fields.Add(new("Codec tag", $"0x{ArchiveContentBinary.ReadUInt16(data, content):X4}", "uint16", content, 2));
                fields.Add(new("Channels", ArchiveContentBinary.ReadUInt16(data, content + 2).ToString(), "uint16", content + 2, 2));
                fields.Add(new("Sample rate", ArchiveContentBinary.ReadUInt32(data, content + 4).ToString("N0"), "uint32", content + 4, 4));
                fields.Add(new("Bits per sample", ArchiveContentBinary.ReadUInt16(data, content + 14).ToString(), "uint16", content + 14, 2));
                return;
            }
            offset = checked(content + (int)size + ((int)size & 1));
        }
        warnings.Add("RIFF/WAVE format chunk was not available in the analyzed prefix.");
    }

    private static void ValidateStructuredText(
        string analyzer,
        string text,
        ICollection<ArchiveContentField> fields,
        ICollection<string> warnings)
    {
        try
        {
            if (analyzer == "json")
            {
                using var document = JsonDocument.Parse(text);
                fields.Add(new("JSON root", document.RootElement.ValueKind.ToString(), Confidence: "proven"));
            }
            else if (analyzer is "xml" or "material_text" && text.TrimStart().StartsWith('<'))
            {
                var document = XDocument.Parse(text, LoadOptions.None);
                fields.Add(new("XML root", document.Root?.Name.LocalName ?? "(empty)", Confidence: "proven"));
            }
        }
        catch (JsonException exception)
        {
            warnings.Add($"JSON parse failed at byte/line {exception.BytePositionInLine}: {exception.Message}");
        }
        catch (System.Xml.XmlException exception)
        {
            warnings.Add($"XML parse failed at line {exception.LineNumber}: {exception.Message}");
        }
    }

    private static int CountLines(string text) =>
        text.Length == 0 ? 0 : 1 + text.Count(character => character == '\n');

    private static bool LooksLikeBone(string value)
    {
        var lower = value.ToLowerInvariant();
        return lower.Contains("bone") || lower.Contains("joint") || lower.Contains("bip") ||
               lower.Contains("root") || lower.Contains("spine") || lower.Contains("finger") ||
               lower.Contains("hand") || lower.Contains("foot") || lower.Contains("head");
    }
}

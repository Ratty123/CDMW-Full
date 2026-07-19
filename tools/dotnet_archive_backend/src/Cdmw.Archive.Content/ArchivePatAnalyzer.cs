namespace Cdmw.Archive.Content;

internal static class ArchivePatAnalyzer
{
    private const int VertexStride = 32;
    private const int DrawStride = 16;

    public static ArchiveContentDocument Analyze(
        ArchiveContentCapability capability,
        string path,
        ReadOnlyMemory<byte> payload,
        long sourceLength,
        bool truncated)
    {
        var data = payload.Span;
        var fields = new List<ArchiveContentField>
        {
            new("Header ASCII", ArchiveContentBinary.HeaderAscii(data), "ascii", 0, Math.Min(data.Length, 16)),
            new("Header hex", ArchiveContentBinary.HeaderHex(data), "hex", 0, Math.Min(data.Length, 64)),
        };
        var warnings = new List<string>();
        var sections = new List<ArchiveContentSection>();
        var strings = ArchiveContentBinary.ExtractStrings(data);
        ArchiveContentModel? model = null;
        try
        {
            model = DecodeStructure(data, sourceLength, fields, sections, strings, warnings);
        }
        catch (InvalidDataException exception)
        {
            warnings.Add(exception.Message);
        }
        if (truncated)
        {
            warnings.Add("The PAT payload exceeded the analysis bound; tail materials/references may be incomplete.");
        }
        sections.Insert(0, new ArchiveContentSection("PAT header", fields, Array.Empty<string>()));
        sections.Add(ArchiveContentBinary.BuildStringSection(strings));
        var summary = model is null
            ? "PAT header evidence is readable, but the bounded payload did not validate as a complete mesh layout."
            : $"Validated {model.LodCount:N0} LOD(s), {model.VertexCount:N0} vertices, {model.IndexCount:N0} indices, and {model.DrawCount:N0} draw records.";
        return new ArchiveContentDocument(
            1,
            ArchiveContentAnalyzer.AnalyzerVersion,
            capability.Extension,
            capability.Analyzer,
            "PAT plant-mesh analysis",
            $"{Path.GetFileName(path)}: {summary}",
            capability.Maturity,
            sourceLength,
            sections,
            ArchiveContentBinary.ExtractReferences(strings),
            warnings,
            truncated,
            UnsupportedReason: capability.UnsupportedReason,
            Model: model);
    }

    private static ArchiveContentModel DecodeStructure(
        ReadOnlySpan<byte> data,
        long sourceLength,
        ICollection<ArchiveContentField> fields,
        ICollection<ArchiveContentSection> sections,
        IReadOnlyList<ExtractedString> strings,
        ICollection<string> warnings)
    {
        if (data.Length < 48) throw new InvalidDataException("PAT payload is shorter than the 48-byte header.");
        if (!data[..4].SequenceEqual("PAR "u8))
        {
            throw new InvalidDataException($"Unsupported PAT magic {ArchiveContentBinary.HeaderAscii(data, 4)}; expected 'PAR '.");
        }
        var minimum = ReadFloat3(data, 16);
        var maximum = ReadFloat3(data, 28);
        var lodCount = checked((int)ArchiveContentBinary.ReadUInt32(data, 40));
        if (lodCount is < 1 or > 16) throw new InvalidDataException($"Invalid PAT LOD count {lodCount}.");

        fields.Add(new("Magic", "PAR ", "fourcc", 0, 4));
        fields.Add(new("Bounds minimum", FormatVector(minimum), "float3", 16, 12));
        fields.Add(new("Bounds maximum", FormatVector(maximum), "float3", 28, 12));
        fields.Add(new("LOD count", lodCount.ToString(), "uint32", 40, 4));

        var vertexCounts = ReadUInt32Table(data, 48, lodCount, "vertex LOD counts");
        RequireMonotonic(vertexCounts, "vertex LOD counts", startsAtZero: false);
        var vertexCount = vertexCounts[^1];
        var vertexStart = 48L + lodCount * 4L;
        var vertexEnd = checked(vertexStart + vertexCount * VertexStride);
        RequireAvailable(vertexEnd, data.Length, sourceLength, "vertex buffer");

        var indexTableOffset = checked((int)vertexEnd);
        var indexOffsets = ReadUInt32Table(data, indexTableOffset, lodCount + 1, "index LOD offsets");
        RequireMonotonic(indexOffsets, "index LOD offsets", startsAtZero: true);
        var indexCount = indexOffsets[^1];
        var indexStart = checked((long)indexTableOffset + (lodCount + 1L) * 4L);
        var indexEnd = checked(indexStart + indexCount * 2L);
        RequireAvailable(indexEnd, data.Length, sourceLength, "index buffer");

        var drawTableOffset = checked((int)indexEnd);
        var drawOffsets = ReadUInt32Table(data, drawTableOffset, lodCount + 1, "draw LOD offsets");
        RequireMonotonic(drawOffsets, "draw LOD offsets", startsAtZero: true);
        var drawCount = drawOffsets[^1];
        var drawStart = checked((long)drawTableOffset + (lodCount + 1L) * 4L);
        var drawEnd = checked(drawStart + drawCount * DrawStride);
        RequireAvailable(drawEnd, data.Length, sourceLength, "draw buffer");

        var indexCounts = Differences(indexOffsets);
        var drawCounts = Differences(drawOffsets);
        sections.Add(new ArchiveContentSection(
            "PAT LOD layout",
            [
                new("Vertex buffer", $"0x{vertexStart:X}-0x{vertexEnd:X}", "range", vertexStart, checked((int)(vertexEnd - vertexStart))),
                new("Index buffer", $"0x{indexStart:X}-0x{indexEnd:X}", "range", indexStart, checked((int)(indexEnd - indexStart))),
                new("Draw buffer", $"0x{drawStart:X}-0x{drawEnd:X}", "range", drawStart, checked((int)(drawEnd - drawStart))),
                new("Tail bytes", (sourceLength - drawEnd).ToString("N0"), "integer", drawEnd),
            ],
            Enumerable.Range(0, lodCount)
                .Select(index => $"LOD {index}: cumulative vertices {vertexCounts[index]:N0} | indices {indexCounts[index]:N0} | draws {drawCounts[index]:N0}")
                .ToArray()));

        var materialNames = strings
            .Select(item => item.Value)
            .Where(value => value.Contains("_mat", StringComparison.OrdinalIgnoreCase))
            .Select(value => TrimAt(value, "_mat"))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(256)
            .ToArray();
        var textureNames = strings
            .Select(item => item.Value)
            .Where(value => value.Contains(".dds", StringComparison.OrdinalIgnoreCase) ||
                            value.Contains(".tga", StringComparison.OrdinalIgnoreCase))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(256)
            .ToArray();
        sections.Add(new ArchiveContentSection(
            "PAT materials and textures",
            [
                new("Material name count", materialNames.Length.ToString("N0"), "integer", Confidence: "heuristic"),
                new("Texture name count", textureNames.Length.ToString("N0"), "integer", Confidence: "heuristic"),
            ],
            materialNames.Select(value => $"Material: {value}")
                .Concat(textureNames.Select(value => $"Texture: {value}"))
                .ToArray()));
        if (materialNames.Length == 0)
        {
            warnings.Add("No '_mat' material strings were found in the available PAT tail.");
        }
        return new ArchiveContentModel(
            "pat",
            lodCount,
            checked((int)vertexCount),
            checked((int)indexCount),
            checked((int)drawCount),
            materialNames.Length,
            vertexCounts.Select(value => checked((int)value)).ToArray(),
            indexCounts,
            drawCounts,
            minimum,
            maximum);
    }

    private static float[] ReadFloat3(ReadOnlySpan<byte> data, int offset) =>
    [
        ArchiveContentBinary.ReadSingle(data, offset),
        ArchiveContentBinary.ReadSingle(data, offset + 4),
        ArchiveContentBinary.ReadSingle(data, offset + 8),
    ];

    private static uint[] ReadUInt32Table(ReadOnlySpan<byte> data, int offset, int count, string label)
    {
        if (offset < 0 || count < 0 || (long)offset + count * 4L > data.Length)
        {
            throw new InvalidDataException($"PAT {label} are outside the analyzed payload.");
        }
        var values = new uint[count];
        for (var index = 0; index < count; index++)
        {
            values[index] = ArchiveContentBinary.ReadUInt32(data, offset + index * 4);
        }
        return values;
    }

    private static void RequireMonotonic(IReadOnlyList<uint> values, string label, bool startsAtZero)
    {
        if (startsAtZero && values.Count > 0 && values[0] != 0)
        {
            throw new InvalidDataException($"PAT {label} must start at zero.");
        }
        for (var index = 0; index + 1 < values.Count; index++)
        {
            if (values[index] > values[index + 1])
            {
                throw new InvalidDataException($"PAT {label} must be monotonic.");
            }
        }
    }

    private static void RequireAvailable(long end, int analyzedLength, long sourceLength, string label)
    {
        if (end > sourceLength) throw new InvalidDataException($"PAT {label} exceeds the source length.");
        if (end > analyzedLength)
        {
            throw new InvalidDataException($"PAT {label} is valid by size but lies beyond the bounded analysis prefix.");
        }
    }

    private static int[] Differences(IReadOnlyList<uint> offsets) =>
        Enumerable.Range(0, offsets.Count - 1)
            .Select(index => checked((int)(offsets[index + 1] - offsets[index])))
            .ToArray();

    private static string FormatVector(IEnumerable<float> values) =>
        $"({string.Join(", ", values.Select(ArchiveContentBinary.FormatSingle))})";

    private static string TrimAt(string value, string marker)
    {
        var index = value.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
        return index < 0 ? value : value[..(index + marker.Length)];
    }
}

using System.Text.Json;

namespace Cdmw.ArchiveLite.Core;

internal sealed record NativePreviewMeshPackage(IReadOnlyList<NativePreviewMeshBatch> Batches, int TotalVertices)
{
    private const int MaximumVertices = 8_000_000;

    public static async Task<NativePreviewMeshPackage> ReadAsync(
        string packageRoot,
        CancellationToken cancellationToken)
    {
        var root = Path.GetFullPath(packageRoot);
        var manifestPath = Path.Combine(root, "manifest.json");
        using var manifest = JsonDocument.Parse(
            await File.ReadAllTextAsync(manifestPath, cancellationToken).ConfigureAwait(false));
        if (!manifest.RootElement.TryGetProperty("schema_version", out var schema)
            || !schema.TryGetInt32(out var schemaVersion)
            || schemaVersion != 8)
        {
            throw new InvalidDataException("Mesh export requires native preview manifest schema 8.");
        }
        if (!manifest.RootElement.TryGetProperty("batches", out var batchesElement)
            || batchesElement.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidDataException("Native preview manifest has no batches array.");
        }

        var batches = new List<NativePreviewMeshBatch>();
        var totalVertices = 0;
        foreach (var element in batchesElement.EnumerateArray())
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (element.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var index = ReadInt(element, "index", batches.Count);
            var vertexCount = ReadInt(element, "vertex_count", 0);
            if (vertexCount <= 0 || vertexCount % 3 != 0)
            {
                throw new InvalidDataException($"Native preview batch {index} has an invalid vertex count.");
            }
            totalVertices = checked(totalVertices + vertexCount);
            if (totalVertices > MaximumVertices)
            {
                throw new InvalidDataException($"Mesh export exceeds the {MaximumVertices:N0}-vertex safety limit.");
            }
            var geometry = ResolveContainedFile(root, ReadString(element, "vertex_file"));
            if (new FileInfo(geometry).Length
                != checked((long)vertexCount * NativePreviewGeometryIO.BytesPerPreviewVertex))
            {
                throw new InvalidDataException($"Native preview batch {index} has an invalid geometry length.");
            }
            batches.Add(new NativePreviewMeshBatch(
                index,
                vertexCount,
                geometry,
                ReadString(element, "material_name"),
                ReadColor(element),
                ReadUnitFloat(element, "metalness", 0.0f),
                ReadUnitFloat(element, "roughness", 0.62f)));
        }
        if (batches.Count == 0)
        {
            throw new InvalidDataException("Native preview package did not contain renderable batches.");
        }
        return new NativePreviewMeshPackage(batches, totalVertices);
    }

    private static string ResolveContainedFile(string packageRoot, string relativePath)
    {
        if (string.IsNullOrWhiteSpace(relativePath) || Path.IsPathRooted(relativePath))
        {
            throw new InvalidDataException("Native preview package path must be relative.");
        }
        var root = Path.GetFullPath(packageRoot).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var candidate = Path.GetFullPath(Path.Combine(root, relativePath.Replace('/', Path.DirectorySeparatorChar)));
        if (!candidate.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
            || !File.Exists(candidate))
        {
            throw new InvalidDataException($"Native preview package path is missing or escapes its root: {relativePath}");
        }
        return candidate;
    }

    private static int ReadInt(JsonElement element, string name, int fallback)
    {
        return element.TryGetProperty(name, out var value) && value.TryGetInt32(out var result)
            ? result
            : fallback;
    }

    private static float[] ReadColor(JsonElement element)
    {
        if (!element.TryGetProperty("base_color", out var color) || color.ValueKind != JsonValueKind.Array)
        {
            return [0.65f, 0.65f, 0.65f];
        }
        var values = color.EnumerateArray().Take(3).Select(static item =>
            item.TryGetSingle(out var value) && float.IsFinite(value)
                ? Math.Clamp(value, 0.0f, 1.0f)
                : 0.65f).ToArray();
        return values.Length == 3 ? values : [0.65f, 0.65f, 0.65f];
    }

    private static float ReadUnitFloat(JsonElement element, string name, float fallback)
    {
        return element.TryGetProperty(name, out var value)
            && value.TryGetSingle(out var result)
            && float.IsFinite(result)
                ? Math.Clamp(result, 0.0f, 1.0f)
                : fallback;
    }

    private static string ReadString(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? string.Empty
            : string.Empty;
    }
}

internal sealed record NativePreviewMeshBatch(
    int Index,
    int VertexCount,
    string GeometryPath,
    string MaterialName,
    float[] BaseColor,
    float Metalness,
    float Roughness);

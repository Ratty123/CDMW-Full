using System.Buffers.Binary;
using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static class NativePreviewPackageDocument
{
    private const int SupportedSchemaVersion = 8;
    private const int FloatsPerVertex = 23;
    private const int BytesPerVertex = FloatsPerVertex * sizeof(float);
    private const int MaximumVertices = 8_000_000;

    public static ObjDocument Load(string manifestPath)
    {
        var resolvedManifest = Path.GetFullPath(manifestPath);
        var packageRoot = Path.GetDirectoryName(resolvedManifest)
            ?? throw new InvalidDataException("Native preview manifest has no package directory.");
        using var manifest = JsonDocument.Parse(File.ReadAllText(resolvedManifest));
        var root = manifest.RootElement;
        if (root.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException("Native preview manifest root must be an object.");
        }
        var schemaVersion = ReadInt(root, "schema_version", -1);
        if (schemaVersion != SupportedSchemaVersion)
        {
            throw new InvalidDataException(
                $"Native preview manifest schema {schemaVersion} is unsupported; expected {SupportedSchemaVersion}.");
        }
        if (!root.TryGetProperty("batches", out var batches)
            || batches.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidDataException("Native preview manifest does not contain a batches array.");
        }

        var document = new ObjDocument();
        document.HeaderComments.Add($"# source_native_preview_package {resolvedManifest}");
        var totalVertices = 0;
        foreach (var batch in batches.EnumerateArray())
        {
            if (batch.ValueKind != JsonValueKind.Object)
            {
                continue;
            }

            var batchIndex = ReadInt(batch, "index", document.Submeshes.Count);
            var vertexCount = ReadInt(batch, "vertex_count", 0);
            if (vertexCount <= 0 || vertexCount % 3 != 0)
            {
                throw new InvalidDataException($"Native preview batch {batchIndex} has an invalid triangle vertex count.");
            }
            totalVertices = checked(totalVertices + vertexCount);
            if (totalVertices > MaximumVertices)
            {
                throw new InvalidDataException($"Native preview package exceeds the {MaximumVertices:N0}-vertex safety limit.");
            }

            var vertexFile = ReadString(batch, "vertex_file");
            var geometryPath = ResolveContainedFile(packageRoot, vertexFile);
            var expectedBytes = checked((long)vertexCount * BytesPerVertex);
            var fileLength = new FileInfo(geometryPath).Length;
            if (fileLength != expectedBytes)
            {
                throw new InvalidDataException(
                    $"Native preview batch {batchIndex} geometry length is {fileLength:N0} bytes; expected {expectedBytes:N0}.");
            }

            var submesh = new ObjSubmesh($"batch_{batchIndex:000}", 0, 0, 0)
            {
                Material = ReadString(batch, "material_name", $"material_{batchIndex:000}"),
                NormalsVertexAligned = true,
                UvsVertexAligned = true,
            };
            submesh.Vertices.EnsureCapacity(vertexCount);
            submesh.Uvs.EnsureCapacity(vertexCount);
            submesh.Normals.EnsureCapacity(vertexCount);
            submesh.Faces.EnsureCapacity(vertexCount / 3);
            ReadGeometry(geometryPath, vertexCount, submesh, batchIndex);
            document.Submeshes.Add(submesh);
        }

        if (document.Submeshes.Count == 0)
        {
            throw new InvalidDataException("Native preview package did not contain renderable batches.");
        }
        return document;
    }

    private static void ReadGeometry(string path, int vertexCount, ObjSubmesh submesh, int batchIndex)
    {
        using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            bufferSize: 128 * 1024,
            FileOptions.SequentialScan);
        var vertex = new byte[BytesPerVertex];
        for (var index = 0; index < vertexCount; index++)
        {
            stream.ReadExactly(vertex);
            var position = new Vec3(ReadFinite(vertex, 0, batchIndex), ReadFinite(vertex, 1, batchIndex), ReadFinite(vertex, 2, batchIndex));
            var normal = new Vec3(ReadFinite(vertex, 3, batchIndex), ReadFinite(vertex, 4, batchIndex), ReadFinite(vertex, 5, batchIndex));
            var nativeU = ReadFinite(vertex, 9, batchIndex);
            var nativeV = ReadFinite(vertex, 10, batchIndex);
            // The shared upload path flips Wavefront-style V into renderer coordinates.
            // Native UVs are already renderer-ready, so enter the intermediate convention here;
            // the upload conversion then restores the original native V.
            var uv = new Vec2(nativeU, 1.0f - nativeV);
            submesh.Vertices.Add(position);
            submesh.Normals.Add(normal);
            submesh.Uvs.Add(uv);
            if (index % 3 == 2)
            {
                submesh.Faces.Add(new ObjFace(
                [
                    new ObjCorner(index - 2, index - 2, index - 2),
                    new ObjCorner(index - 1, index - 1, index - 1),
                    new ObjCorner(index, index, index),
                ]));
            }
        }
    }

    private static float ReadFinite(byte[] bytes, int floatIndex, int batchIndex)
    {
        var value = BinaryPrimitives.ReadSingleLittleEndian(bytes.AsSpan(floatIndex * sizeof(float), sizeof(float)));
        if (!float.IsFinite(value))
        {
            throw new InvalidDataException($"Native preview batch {batchIndex} contains a non-finite vertex value.");
        }
        return value;
    }

    private static string ResolveContainedFile(string packageRoot, string relativePath)
    {
        if (string.IsNullOrWhiteSpace(relativePath) || Path.IsPathRooted(relativePath))
        {
            throw new InvalidDataException("Native preview geometry path must be package-relative.");
        }
        var root = Path.GetFullPath(packageRoot).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var candidate = Path.GetFullPath(Path.Combine(root, relativePath.Replace('/', Path.DirectorySeparatorChar)));
        var prefix = root + Path.DirectorySeparatorChar;
        if (!candidate.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) || !File.Exists(candidate))
        {
            throw new InvalidDataException($"Native preview geometry path is missing or escapes its package: {relativePath}");
        }
        return candidate;
    }

    private static int ReadInt(JsonElement element, string name, int fallback)
    {
        return element.TryGetProperty(name, out var value)
            && value.ValueKind == JsonValueKind.Number
            && value.TryGetInt32(out var result)
                ? result
                : fallback;
    }

    private static string ReadString(JsonElement element, string name, string fallback = "")
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? fallback
            : fallback;
    }
}

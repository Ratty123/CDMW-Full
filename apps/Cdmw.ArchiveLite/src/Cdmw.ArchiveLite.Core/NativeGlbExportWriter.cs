using System.Buffers.Binary;
using System.Text;
using System.Text.Json;
using Cdmw.ArchiveLite.Contracts;
using static Cdmw.ArchiveLite.Core.NativePreviewGeometryIO;

namespace Cdmw.ArchiveLite.Core;

internal static class NativeGlbExportWriter
{
    private static readonly JsonSerializerOptions CompactJson = new() { WriteIndented = false };

    public static async Task WriteAsync(
        NativePreviewMeshPackage package,
        string sourcePath,
        string destination,
        bool overwrite,
        Func<ProgressUpdate, Task>? progress,
        string? currentItem,
        CancellationToken cancellationToken)
    {
        var totalWork = checked(package.TotalVertices * 4L);
        long completed = 0;
        await ReportAsync(progress, completed, totalWork, "mesh_export_prepare", currentItem).ConfigureAwait(false);
        var bounds = new List<MeshBounds>(package.Batches.Count);
        foreach (var batch in package.Batches)
        {
            var result = await ReadBoundsAsync(
                batch,
                completed,
                totalWork,
                progress,
                currentItem,
                cancellationToken).ConfigureAwait(false);
            bounds.Add(result.Bounds);
            completed = result.Completed;
        }

        var bufferViews = new List<Dictionary<string, object?>>();
        var accessors = new List<Dictionary<string, object?>>();
        var primitives = new List<Dictionary<string, object?>>();
        var materials = new List<Dictionary<string, object?>>();
        long binaryLength = 0;
        for (var index = 0; index < package.Batches.Count; index++)
        {
            var batch = package.Batches[index];
            var positionAccessor = AddFloatAccessor(
                bufferViews,
                accessors,
                ref binaryLength,
                batch.VertexCount,
                3,
                bounds[index].Minimum,
                bounds[index].Maximum);
            var normalAccessor = AddFloatAccessor(bufferViews, accessors, ref binaryLength, batch.VertexCount, 3, null, null);
            var uvAccessor = AddFloatAccessor(bufferViews, accessors, ref binaryLength, batch.VertexCount, 2, null, null);
            primitives.Add(new Dictionary<string, object?>
            {
                ["attributes"] = new Dictionary<string, object?>
                {
                    ["POSITION"] = positionAccessor,
                    ["NORMAL"] = normalAccessor,
                    ["TEXCOORD_0"] = uvAccessor,
                },
                ["material"] = index,
                ["mode"] = 4,
            });
            materials.Add(new Dictionary<string, object?>
            {
                ["name"] = CleanName(batch.MaterialName, $"material_{batch.Index:000}"),
                ["pbrMetallicRoughness"] = new Dictionary<string, object?>
                {
                    ["baseColorFactor"] = new[] { batch.BaseColor[0], batch.BaseColor[1], batch.BaseColor[2], 1.0f },
                    ["metallicFactor"] = batch.Metalness,
                    ["roughnessFactor"] = batch.Roughness,
                },
                ["doubleSided"] = false,
            });
        }

        var baseName = CleanName(Path.GetFileNameWithoutExtension(sourcePath), "mesh");
        var document = new Dictionary<string, object?>
        {
            ["asset"] = new Dictionary<string, object?>
            {
                ["version"] = "2.0",
                ["generator"] = "CDMW Archive Lite",
                ["extras"] = new Dictionary<string, object?>
                {
                    ["source_path"] = sourcePath,
                    ["source_format"] = Path.GetExtension(sourcePath).TrimStart('.').ToLowerInvariant(),
                    ["mesh_only"] = true,
                },
            },
            ["scene"] = 0,
            ["scenes"] = new[] { new Dictionary<string, object?> { ["nodes"] = new[] { 0 } } },
            ["nodes"] = new[] { new Dictionary<string, object?> { ["name"] = baseName, ["mesh"] = 0 } },
            ["meshes"] = new[] { new Dictionary<string, object?> { ["name"] = baseName, ["primitives"] = primitives } },
            ["materials"] = materials,
            ["buffers"] = new[] { new Dictionary<string, object?> { ["byteLength"] = binaryLength } },
            ["bufferViews"] = bufferViews,
            ["accessors"] = accessors,
        };
        var jsonChunk = Pad4(JsonSerializer.SerializeToUtf8Bytes(document, CompactJson), (byte)' ');
        var binaryPaddedLength = Align4(binaryLength);
        var totalLength = checked(12L + 8L + jsonChunk.LongLength + 8L + binaryPaddedLength);
        if (totalLength > uint.MaxValue)
        {
            throw new InvalidDataException("GLB output exceeds the 4 GiB format limit.");
        }

        await AtomicFile.WriteAsync(
            destination,
            async (output, token) =>
            {
                var header = new byte[20];
                "glTF"u8.CopyTo(header);
                BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(4, 4), 2);
                BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(8, 4), checked((uint)totalLength));
                BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(12, 4), checked((uint)jsonChunk.Length));
                BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(16, 4), 0x4E4F534A);
                await output.WriteAsync(header, token).ConfigureAwait(false);
                await output.WriteAsync(jsonChunk, token).ConfigureAwait(false);
                var binaryHeader = new byte[8];
                BinaryPrimitives.WriteUInt32LittleEndian(binaryHeader.AsSpan(0, 4), checked((uint)binaryPaddedLength));
                BinaryPrimitives.WriteUInt32LittleEndian(binaryHeader.AsSpan(4, 4), 0x004E4942);
                await output.WriteAsync(binaryHeader, token).ConfigureAwait(false);

                foreach (var batch in package.Batches)
                {
                    completed = await CopyFloatAttributeAsync(
                        batch,
                        output,
                        0,
                        3,
                        flipSecondComponent: false,
                        completed,
                        totalWork,
                        progress,
                        currentItem,
                        token).ConfigureAwait(false);
                    completed = await CopyFloatAttributeAsync(
                        batch,
                        output,
                        3,
                        3,
                        flipSecondComponent: false,
                        completed,
                        totalWork,
                        progress,
                        currentItem,
                        token).ConfigureAwait(false);
                    completed = await CopyFloatAttributeAsync(
                        batch,
                        output,
                        9,
                        2,
                        flipSecondComponent: true,
                        completed,
                        totalWork,
                        progress,
                        currentItem,
                        token).ConfigureAwait(false);
                }
                for (long padding = binaryLength; padding < binaryPaddedLength; padding++)
                {
                    output.WriteByte(0);
                }
            },
            cancellationToken,
            overwrite).ConfigureAwait(false);
        await ReportAsync(progress, totalWork, totalWork, "mesh_export_write", currentItem).ConfigureAwait(false);
    }

    private static int AddFloatAccessor(
        List<Dictionary<string, object?>> views,
        List<Dictionary<string, object?>> accessors,
        ref long binaryLength,
        int count,
        int components,
        float[]? minimum,
        float[]? maximum)
    {
        var byteLength = checked((long)count * components * sizeof(float));
        var viewIndex = views.Count;
        views.Add(new Dictionary<string, object?>
        {
            ["buffer"] = 0,
            ["byteOffset"] = binaryLength,
            ["byteLength"] = byteLength,
            ["target"] = 34962,
        });
        binaryLength = checked(binaryLength + byteLength);
        var accessor = new Dictionary<string, object?>
        {
            ["bufferView"] = viewIndex,
            ["componentType"] = 5126,
            ["count"] = count,
            ["type"] = components == 3 ? "VEC3" : "VEC2",
        };
        if (minimum is not null && maximum is not null)
        {
            accessor["min"] = minimum;
            accessor["max"] = maximum;
        }
        accessors.Add(accessor);
        return accessors.Count - 1;
    }

    private static async Task<BoundsProgress> ReadBoundsAsync(
        NativePreviewMeshBatch batch,
        long completed,
        long totalWork,
        Func<ProgressUpdate, Task>? progress,
        string? currentItem,
        CancellationToken cancellationToken)
    {
        var minimum = new[] { float.PositiveInfinity, float.PositiveInfinity, float.PositiveInfinity };
        var maximum = new[] { float.NegativeInfinity, float.NegativeInfinity, float.NegativeInfinity };
        await using var input = OpenRead(batch.GeometryPath);
        var buffer = new byte[RecordsPerChunk * BytesPerPreviewVertex];
        var batchCompleted = 0;
        while (batchCompleted < batch.VertexCount)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var count = Math.Min(RecordsPerChunk, batch.VertexCount - batchCompleted);
            var bytes = checked(count * BytesPerPreviewVertex);
            await input.ReadExactlyAsync(buffer.AsMemory(0, bytes), cancellationToken).ConfigureAwait(false);
            for (var localIndex = 0; localIndex < count; localIndex++)
            {
                var offset = localIndex * BytesPerPreviewVertex;
                for (var component = 0; component < 3; component++)
                {
                    var value = ReadFiniteSingle(buffer, offset + (component * sizeof(float)), "position");
                    minimum[component] = Math.Min(minimum[component], value);
                    maximum[component] = Math.Max(maximum[component], value);
                }
            }
            batchCompleted += count;
            completed += count;
            await ReportAsync(progress, completed, totalWork, "mesh_export_prepare", currentItem).ConfigureAwait(false);
        }
        return new BoundsProgress(new MeshBounds(minimum, maximum), completed);
    }

    private static async Task<long> CopyFloatAttributeAsync(
        NativePreviewMeshBatch batch,
        Stream output,
        int sourceFloatOffset,
        int components,
        bool flipSecondComponent,
        long completed,
        long totalWork,
        Func<ProgressUpdate, Task>? progress,
        string? currentItem,
        CancellationToken cancellationToken)
    {
        await ReportAsync(progress, completed, totalWork, "mesh_export_write", currentItem).ConfigureAwait(false);
        await using var input = OpenRead(batch.GeometryPath);
        var inputBuffer = new byte[RecordsPerChunk * BytesPerPreviewVertex];
        var outputBuffer = new byte[RecordsPerChunk * components * sizeof(float)];
        var batchCompleted = 0;
        while (batchCompleted < batch.VertexCount)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var count = Math.Min(RecordsPerChunk, batch.VertexCount - batchCompleted);
            var inputBytes = checked(count * BytesPerPreviewVertex);
            await input.ReadExactlyAsync(inputBuffer.AsMemory(0, inputBytes), cancellationToken).ConfigureAwait(false);
            var outputOffset = 0;
            for (var localIndex = 0; localIndex < count; localIndex++)
            {
                var sourceOffset = (localIndex * BytesPerPreviewVertex) + (sourceFloatOffset * sizeof(float));
                for (var component = 0; component < components; component++)
                {
                    var value = ReadFiniteSingle(inputBuffer, sourceOffset + (component * sizeof(float)), "mesh attribute");
                    if (flipSecondComponent && component == 1)
                    {
                        value = 1.0f - value;
                    }
                    BinaryPrimitives.WriteSingleLittleEndian(outputBuffer.AsSpan(outputOffset, 4), value);
                    outputOffset += 4;
                }
            }
            await output.WriteAsync(outputBuffer.AsMemory(0, outputOffset), cancellationToken).ConfigureAwait(false);
            batchCompleted += count;
            completed += count;
            await ReportAsync(progress, completed, totalWork, "mesh_export_write", currentItem).ConfigureAwait(false);
        }
        return completed;
    }

    private static async Task ReportAsync(
        Func<ProgressUpdate, Task>? progress,
        long completed,
        long total,
        string phase,
        string? currentItem)
    {
        if (progress is not null)
        {
            await progress(new ProgressUpdate(completed, total, phase, currentItem)).ConfigureAwait(false);
        }
    }

    private static byte[] Pad4(byte[] source, byte padding)
    {
        var length = checked((int)Align4(source.LongLength));
        if (length == source.Length)
        {
            return source;
        }
        var result = new byte[length];
        source.CopyTo(result, 0);
        result.AsSpan(source.Length).Fill(padding);
        return result;
    }

    private static long Align4(long value) => checked((value + 3L) & ~3L);

    private static string CleanName(string? value, string fallback)
    {
        var source = string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
        var builder = new StringBuilder(Math.Min(source.Length, 96));
        foreach (var character in source)
        {
            if (builder.Length >= 96)
            {
                break;
            }
            builder.Append(char.IsControl(character) || character is '/' or '\\' ? '_' : character);
        }
        return builder.Length == 0 ? fallback : builder.ToString();
    }

    private sealed record MeshBounds(float[] Minimum, float[] Maximum);
    private sealed record BoundsProgress(MeshBounds Bounds, long Completed);
}

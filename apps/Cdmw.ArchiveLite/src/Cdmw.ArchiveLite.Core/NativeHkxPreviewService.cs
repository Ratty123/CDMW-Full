using System.Collections.Concurrent;
using System.Diagnostics;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class NativeHkxPreviewService
{
    private const string ArtifactVersion = "hkx_native_preview_v1";
    private const int MaximumHelperOutputCharacters = 1_048_576;
    private static readonly TimeSpan DecodeTimeout = TimeSpan.FromSeconds(30);
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _buildGates = new(StringComparer.Ordinal);

    public static bool Supports(string extension) =>
        extension.Equals(".hkx", StringComparison.OrdinalIgnoreCase)
        || extension.Equals(".hkt", StringComparison.OrdinalIgnoreCase);

    public async Task<HkxPreviewArtifact> BuildAsync(
        ArchiveSession session,
        ArchiveEntryDto entry,
        byte[] bytes,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(session);
        ArgumentNullException.ThrowIfNull(entry);
        ArgumentNullException.ThrowIfNull(bytes);
        if (!Supports(entry.Extension))
        {
            throw new NotSupportedException($"Native HKX preview does not support {entry.Extension}.");
        }

        ArchiveLiteDataPaths.EnsureCreated();
        var identity = Encoding.UTF8.GetBytes(string.Join(
            '|', ArtifactVersion, session.Fingerprint, entry.EntryId, entry.Path, entry.Offset, entry.StoredSize, entry.OriginalSize));
        var key = Convert.ToHexString(SHA256.HashData(identity)).ToLowerInvariant();
        var previewRoot = Path.Combine(ArchiveLiteDataPaths.PreviewCache, "hkx");
        var destination = Path.Combine(previewRoot, key);
        Directory.CreateDirectory(previewRoot);
        if (TryReadArtifact(destination, out var cached))
        {
            return cached;
        }

        var gate = _buildGates.GetOrAdd(key, static _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (TryReadArtifact(destination, out cached))
            {
                return cached;
            }

            if (publishProgress is not null)
            {
                await publishProgress(new ProgressUpdate(0, 2, "hkx_preview_native", entry.Name)).ConfigureAwait(false);
            }
            var document = await InspectAsync(bytes, cancellationToken).ConfigureAwait(false);
            if (!string.Equals(document.Status, "ok", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(document.Warnings.FirstOrDefault()
                    ?? "The native HKX parser did not recover previewable structure.");
            }

            var staging = Path.Combine(previewRoot, $".{key}.{Guid.NewGuid():N}.staging");
            Directory.CreateDirectory(staging);
            try
            {
                var summary = document.PreviewKind.Equals("skeleton", StringComparison.OrdinalIgnoreCase)
                    ? BuildSkeletonGeometry(document)
                    : BuildStructureGeometry(document);
                await WriteNativePackageAsync(staging, summary, cancellationToken).ConfigureAwait(false);
                if (publishProgress is not null)
                {
                    await publishProgress(new ProgressUpdate(1, 2, "hkx_preview_adapt", entry.Name)).ConfigureAwait(false);
                }
                await NativePreviewPackageAdapter.PrepareAsync(
                    staging,
                    $"archive-hkx:{session.Fingerprint}:{entry.EntryId}:{entry.Path}",
                    cancellationToken).ConfigureAwait(false);
                var artifact = new HkxPreviewArtifact(
                    destination,
                    document.PreviewKind,
                    document.Bones.Count,
                    document.Nodes.Count,
                    document.SdkVersion,
                    document.Warnings);
                await WriteArtifactAsync(staging, artifact with { PackagePath = destination }, cancellationToken).ConfigureAwait(false);
                cancellationToken.ThrowIfCancellationRequested();
                ReplaceOwnedDirectory(previewRoot, staging, destination);
                if (publishProgress is not null)
                {
                    await publishProgress(new ProgressUpdate(2, 2, "hkx_preview_adapt", entry.Name)).ConfigureAwait(false);
                }
                return artifact;
            }
            finally
            {
                TryDeleteOwnedDirectory(previewRoot, staging);
            }
        }
        finally
        {
            gate.Release();
        }
    }

    private static async Task<HkxPreviewDocument> InspectAsync(byte[] bytes, CancellationToken cancellationToken)
    {
        var executable = ResolveHelperPath();
        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = false,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(executable) ?? AppContext.BaseDirectory,
        };
        startInfo.ArgumentList.Add("preview-json");
        startInfo.ArgumentList.Add("-");
        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("cd-hkx could not be started.");
        var stdout = ReadBoundedAsync(process.StandardOutput, MaximumHelperOutputCharacters, cancellationToken);
        var stderr = ReadBoundedAsync(process.StandardError, 64 * 1024, cancellationToken);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(DecodeTimeout);
        try
        {
            await process.StandardInput.BaseStream.WriteAsync(bytes, timeout.Token).ConfigureAwait(false);
            process.StandardInput.Close();
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            StopProcess(process);
            await ObserveAsync(stdout, stderr).ConfigureAwait(false);
            throw new TimeoutException($"cd-hkx did not finish within {DecodeTimeout.TotalSeconds:N0} seconds.");
        }
        catch (OperationCanceledException)
        {
            StopProcess(process);
            await ObserveAsync(stdout, stderr).ConfigureAwait(false);
            throw;
        }

        var stdoutText = await stdout.ConfigureAwait(false);
        var stderrText = await stderr.ConfigureAwait(false);
        if (process.ExitCode != 0)
        {
            var detail = string.IsNullOrWhiteSpace(stderrText) ? stdoutText : stderrText;
            throw new InvalidDataException($"cd-hkx exited with code {process.ExitCode}: {detail.Trim()}");
        }
        var document = JsonSerializer.Deserialize<HkxPreviewDocument>(stdoutText, WorkerProtocol.JsonOptions)
            ?? throw new InvalidDataException("cd-hkx returned an empty preview report.");
        ValidateDocument(document);
        return document;
    }

    private static void ValidateDocument(HkxPreviewDocument document)
    {
        if (!string.Equals(document.Format, "cd_hkx_preview_v1", StringComparison.Ordinal))
        {
            throw new InvalidDataException($"cd-hkx returned unsupported preview format '{document.Format}'.");
        }
        if (document.Bones is null || document.Nodes is null || document.Edges is null || document.Warnings is null)
        {
            throw new InvalidDataException("cd-hkx returned an incomplete preview report.");
        }
        if (document.Bones.Count > 4096 || document.Nodes.Count > 128 || document.Edges.Count > 256)
        {
            throw new InvalidDataException("cd-hkx preview report exceeds its bounded geometry limits.");
        }
        if (document.Bones.Any(bone => bone.Position is null || bone.Position.Length != 3 || bone.Position.Any(value => !float.IsFinite(value))))
        {
            throw new InvalidDataException("cd-hkx returned an invalid skeleton position.");
        }
        if (document.Bones.Select(static bone => bone.Index).Distinct().Count() != document.Bones.Count)
        {
            throw new InvalidDataException("cd-hkx returned duplicate skeleton indices.");
        }
    }

    private static GeometrySummary BuildSkeletonGeometry(HkxPreviewDocument document)
    {
        var orderedBones = document.Bones.OrderBy(static bone => bone.Index).ToArray();
        var normalized = Normalize(orderedBones.Select(static bone => ToVector(bone.Position)));
        var positions = orderedBones.Select((bone, index) => (bone.Index, Position: normalized[index]))
            .ToDictionary(static pair => pair.Index, static pair => pair.Position);
        var links = new List<Triangle>();
        var joints = new List<Triangle>();
        foreach (var bone in document.Bones)
        {
            var position = positions[bone.Index];
            AddOctahedron(joints, position, 0.035f);
            if (bone.ParentIndex >= 0 && positions.TryGetValue(bone.ParentIndex, out var parent))
            {
                AddCylinder(links, parent, position, 0.014f, 7);
            }
        }
        if (links.Count == 0 && joints.Count == 0)
        {
            throw new InvalidDataException("HKX skeleton preview did not produce renderable geometry.");
        }
        return new GeometrySummary(
            "skeleton",
            document.Bones.Count,
            document.Nodes.Count,
            [
                new GeometryBatch("Skeleton bones", [0.50f, 0.72f, 0.92f], links),
                new GeometryBatch("Skeleton joints", [0.95f, 0.65f, 0.28f], joints),
            ]);
    }

    private static GeometrySummary BuildStructureGeometry(HkxPreviewDocument document)
    {
        if (document.Nodes.Count == 0)
        {
            throw new InvalidDataException("HKX object graph contains no previewable nodes.");
        }
        var positions = new Dictionary<int, Vector3>();
        for (var index = 0; index < document.Nodes.Count; index++)
        {
            var angle = index * 2.3999632f;
            var radius = 0.25f + 0.065f * MathF.Sqrt(index + 1);
            var y = ((index % 9) - 4) * 0.12f;
            positions[document.Nodes[index].RecordIndex] = new Vector3(MathF.Cos(angle) * radius, y, MathF.Sin(angle) * radius);
        }
        var links = new List<Triangle>();
        foreach (var edge in document.Edges)
        {
            if (positions.TryGetValue(edge.SourceRecordIndex, out var source)
                && positions.TryGetValue(edge.TargetRecordIndex, out var target))
            {
                AddCylinder(links, source, target, 0.008f, 6);
            }
        }
        var nodes = new List<Triangle>();
        foreach (var position in positions.Values)
        {
            AddOctahedron(nodes, position, 0.035f);
        }
        return new GeometrySummary(
            "structure",
            document.Bones.Count,
            document.Nodes.Count,
            [
                new GeometryBatch("HKX relationships", [0.36f, 0.65f, 0.78f], links),
                new GeometryBatch("HKX objects", [0.91f, 0.58f, 0.25f], nodes),
            ]);
    }

    private static IReadOnlyList<Vector3> Normalize(IEnumerable<Vector3> source)
    {
        var points = source.ToArray();
        if (points.Length == 0)
        {
            return [];
        }
        var min = points.Aggregate(Vector3.Min);
        var max = points.Aggregate(Vector3.Max);
        var center = (min + max) * 0.5f;
        var extent = Math.Max(Math.Max(max.X - min.X, max.Y - min.Y), max.Z - min.Z);
        var scale = extent > 1e-6f ? 1.8f / extent : 1.0f;
        return points.Select(point => (point - center) * scale).ToArray();
    }

    private static void AddCylinder(List<Triangle> output, Vector3 start, Vector3 end, float radius, int sides)
    {
        var axis = end - start;
        if (axis.LengthSquared() <= 1e-10f)
        {
            AddOctahedron(output, start, radius * 2.5f);
            return;
        }
        var direction = Vector3.Normalize(axis);
        var helper = Math.Abs(Vector3.Dot(direction, Vector3.UnitY)) < 0.9f ? Vector3.UnitY : Vector3.UnitX;
        var tangent = Vector3.Normalize(Vector3.Cross(direction, helper));
        var bitangent = Vector3.Normalize(Vector3.Cross(direction, tangent));
        for (var side = 0; side < sides; side++)
        {
            var next = (side + 1) % sides;
            var a = RingPoint(start, tangent, bitangent, radius, side, sides);
            var b = RingPoint(start, tangent, bitangent, radius, next, sides);
            var c = RingPoint(end, tangent, bitangent, radius, next, sides);
            var d = RingPoint(end, tangent, bitangent, radius, side, sides);
            output.Add(new(a, b, c));
            output.Add(new(a, c, d));
            output.Add(new(start, b, a));
            output.Add(new(end, d, c));
        }
    }

    private static Vector3 RingPoint(Vector3 center, Vector3 tangent, Vector3 bitangent, float radius, int side, int sides)
    {
        var angle = MathF.Tau * side / sides;
        return center + tangent * (MathF.Cos(angle) * radius) + bitangent * (MathF.Sin(angle) * radius);
    }

    private static void AddOctahedron(List<Triangle> output, Vector3 center, float radius)
    {
        var px = center + Vector3.UnitX * radius;
        var nx = center - Vector3.UnitX * radius;
        var py = center + Vector3.UnitY * radius;
        var ny = center - Vector3.UnitY * radius;
        var pz = center + Vector3.UnitZ * radius;
        var nz = center - Vector3.UnitZ * radius;
        output.AddRange([
            new(py, px, pz), new(py, pz, nx), new(py, nx, nz), new(py, nz, px),
            new(ny, pz, px), new(ny, nx, pz), new(ny, nz, nx), new(ny, px, nz),
        ]);
    }

    private static async Task WriteNativePackageAsync(string root, GeometrySummary summary, CancellationToken cancellationToken)
    {
        var geometryRoot = Path.Combine(root, "geometry");
        Directory.CreateDirectory(geometryRoot);
        var manifests = new List<object>();
        var batchIndex = 0;
        foreach (var batch in summary.Batches.Where(static batch => batch.Triangles.Count > 0))
        {
            var relative = $"geometry/batch_{batchIndex:000}.bin";
            await WriteGeometryAsync(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)), batch.Triangles, cancellationToken).ConfigureAwait(false);
            manifests.Add(new
            {
                index = batchIndex,
                material_name = batch.Name,
                vertex_file = relative,
                vertex_count = batch.Triangles.Count * 3,
                base_color = batch.Color,
                roughness = 0.68f,
                metalness = 0.0f,
                specular = 0.22f,
                material_category = "hkx_preview",
                material_category_confidence = 1.0f,
                material_category_reason = "Native read-only HKX preview geometry.",
                material_response_promoted = false,
                dds_textures = new Dictionary<string, object>(),
            });
            batchIndex++;
        }
        if (manifests.Count == 0)
        {
            throw new InvalidDataException("HKX preview package has no triangles.");
        }
        await WriteJsonAsync(
            Path.Combine(root, "manifest.json"),
            new
            {
                schema_version = 8,
                backend = "d3d11",
                source_kind = summary.Kind,
                bone_count = summary.BoneCount,
                node_count = summary.NodeCount,
                batches = manifests,
            },
            cancellationToken).ConfigureAwait(false);
    }

    private static async Task WriteGeometryAsync(string path, IReadOnlyList<Triangle> triangles, CancellationToken cancellationToken)
    {
        using var memory = new MemoryStream(checked(triangles.Count * 3 * 23 * sizeof(float)));
        using (var writer = new BinaryWriter(memory, Encoding.UTF8, leaveOpen: true))
        {
            foreach (var triangle in triangles)
            {
                var normal = Vector3.Cross(triangle.B - triangle.A, triangle.C - triangle.A);
                normal = normal.LengthSquared() > 1e-12f ? Vector3.Normalize(normal) : Vector3.UnitY;
                WriteVertex(writer, triangle.A, normal);
                WriteVertex(writer, triangle.B, normal);
                WriteVertex(writer, triangle.C, normal);
            }
        }
        var payload = memory.ToArray();
        await AtomicFile.WriteAsync(
            path,
            async (stream, token) => await stream.WriteAsync(payload, token).ConfigureAwait(false),
            cancellationToken).ConfigureAwait(false);
    }

    private static void WriteVertex(BinaryWriter writer, Vector3 position, Vector3 normal)
    {
        var vertex = new float[23];
        vertex[0] = position.X;
        vertex[1] = position.Y;
        vertex[2] = position.Z;
        vertex[3] = normal.X;
        vertex[4] = normal.Y;
        vertex[5] = normal.Z;
        vertex[6] = 1.0f;
        for (var index = 0; index < vertex.Length; index++) writer.Write(vertex[index]);
    }

    private static async Task WriteArtifactAsync(string root, HkxPreviewArtifact artifact, CancellationToken cancellationToken) =>
        await WriteJsonAsync(Path.Combine(root, "archive_lite_hkx_preview.json"), artifact, cancellationToken).ConfigureAwait(false);

    private static async Task WriteJsonAsync(string path, object value, CancellationToken cancellationToken) =>
        await AtomicFile.WriteAsync(
            path,
            async (stream, token) => await JsonSerializer.SerializeAsync(stream, value, WorkerProtocol.JsonOptions, token).ConfigureAwait(false),
            cancellationToken).ConfigureAwait(false);

    private static bool TryReadArtifact(string destination, out HkxPreviewArtifact artifact)
    {
        artifact = default!;
        var manifest = Path.Combine(destination, "manifest.json");
        var report = Path.Combine(destination, "archive_lite_hkx_preview.json");
        if (!File.Exists(manifest) || !File.Exists(Path.Combine(destination, "dotnet_scene.json")) || !File.Exists(report))
        {
            return false;
        }
        try
        {
            artifact = JsonSerializer.Deserialize<HkxPreviewArtifact>(File.ReadAllText(report), WorkerProtocol.JsonOptions)!;
            var expected = Path.GetFullPath(destination).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var actual = artifact is null
                ? string.Empty
                : Path.GetFullPath(artifact.PackagePath).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            return artifact is not null
                && artifact.Warnings is not null
                && actual.Equals(expected, StringComparison.OrdinalIgnoreCase)
                && Directory.Exists(actual);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or JsonException or ArgumentException or NotSupportedException)
        {
            artifact = default!;
            return false;
        }
    }

    private static void ReplaceOwnedDirectory(string root, string staging, string destination)
    {
        RequireContained(root, staging);
        RequireContained(root, destination);
        if (Directory.Exists(destination)) Directory.Delete(destination, recursive: true);
        Directory.Move(staging, destination);
    }

    private static void TryDeleteOwnedDirectory(string root, string path)
    {
        try
        {
            RequireContained(root, path);
            if (Directory.Exists(path)) Directory.Delete(path, recursive: true);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // A later cache rebuild can remove a locked staging directory.
        }
    }

    private static void RequireContained(string root, string path)
    {
        var resolvedRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var resolvedPath = Path.GetFullPath(path);
        if (!resolvedPath.StartsWith(resolvedRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException($"HKX preview path escapes its owned cache root: {resolvedPath}");
        }
    }

    private static string ResolveHelperPath()
    {
        var overridePath = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_HKX_HELPER_PATH");
        if (!string.IsNullOrWhiteSpace(overridePath) && File.Exists(overridePath)) return Path.GetFullPath(overridePath);
        var packaged = Path.Combine(AppContext.BaseDirectory, "hkx", "cd-hkx.exe");
        if (File.Exists(packaged)) return packaged;
        for (var current = new DirectoryInfo(AppContext.BaseDirectory); current is not null; current = current.Parent)
        {
            foreach (var configuration in new[] { "release", "debug" })
            {
                var candidate = Path.Combine(current.FullName, "native", "cd_hkx", "target", configuration, "cd-hkx.exe");
                if (File.Exists(candidate)) return candidate;
            }
        }
        throw new FileNotFoundException("cd-hkx.exe was not found. Rebuild Archive Lite or set CDMW_ARCHIVE_LITE_HKX_HELPER_PATH.");
    }

    private static async Task<string> ReadBoundedAsync(TextReader reader, int limit, CancellationToken cancellationToken)
    {
        var output = new StringBuilder(Math.Min(limit, 4096));
        var buffer = new char[4096];
        while (true)
        {
            var count = await reader.ReadAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false);
            if (count == 0) break;
            if (output.Length + count > limit) throw new InvalidDataException($"cd-hkx output exceeded {limit:N0} characters.");
            output.Append(buffer, 0, count);
        }
        return output.ToString();
    }

    private static void StopProcess(Process process)
    {
        try
        {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
        }
        catch (InvalidOperationException)
        {
            // The process exited between the check and kill.
        }
    }

    private static async Task ObserveAsync(params Task<string>[] tasks)
    {
        try { await Task.WhenAll(tasks).ConfigureAwait(false); }
        catch (Exception) { }
    }

    private static Vector3 ToVector(float[] values) => new(values[0], values[1], values[2]);

    private sealed record GeometrySummary(string Kind, int BoneCount, int NodeCount, IReadOnlyList<GeometryBatch> Batches);
    private sealed record GeometryBatch(string Name, float[] Color, IReadOnlyList<Triangle> Triangles);
    private sealed record Triangle(Vector3 A, Vector3 B, Vector3 C);
}

public sealed record HkxPreviewArtifact(
    string PackagePath,
    string PreviewKind,
    int BoneCount,
    int NodeCount,
    string SdkVersion,
    IReadOnlyList<string> Warnings);

public sealed record HkxPreviewDocument(
    [property: JsonPropertyName("format")] string Format,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("preview_kind")] string PreviewKind,
    [property: JsonPropertyName("sdk_version")] string SdkVersion,
    [property: JsonPropertyName("bone_count")] int BoneCount,
    [property: JsonPropertyName("bones")] IReadOnlyList<HkxPreviewBone> Bones,
    [property: JsonPropertyName("nodes")] IReadOnlyList<HkxPreviewNode> Nodes,
    [property: JsonPropertyName("edges")] IReadOnlyList<HkxPreviewEdge> Edges,
    [property: JsonPropertyName("warnings")] IReadOnlyList<string> Warnings);

public sealed record HkxPreviewBone(
    [property: JsonPropertyName("index")] int Index,
    [property: JsonPropertyName("parent_index")] int ParentIndex,
    [property: JsonPropertyName("position")] float[] Position);

public sealed record HkxPreviewNode(
    [property: JsonPropertyName("record_index")] int RecordIndex,
    [property: JsonPropertyName("type_name")] string TypeName,
    [property: JsonPropertyName("count")] int Count);

public sealed record HkxPreviewEdge(
    [property: JsonPropertyName("source_record_index")] int SourceRecordIndex,
    [property: JsonPropertyName("target_record_index")] int TargetRecordIndex);

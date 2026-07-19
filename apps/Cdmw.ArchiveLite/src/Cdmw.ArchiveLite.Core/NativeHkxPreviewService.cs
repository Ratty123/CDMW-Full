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
    private const string ArtifactVersion = "hkx_native_preview_v2";
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
                    ?? "The native HKX parser did not recover previewable skeleton or collision geometry.");
            }

            var staging = Path.Combine(previewRoot, $".{key}.{Guid.NewGuid():N}.staging");
            Directory.CreateDirectory(staging);
            try
            {
                var summary = document.PreviewKind.Equals("skeleton", StringComparison.OrdinalIgnoreCase)
                    ? BuildSkeletonGeometry(document)
                    : BuildCollisionGeometry(document);
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
                    document.Shapes.Count,
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
        if (!string.Equals(document.Format, "cd_hkx_preview_v2", StringComparison.Ordinal))
        {
            throw new InvalidDataException($"cd-hkx returned unsupported preview format '{document.Format}'.");
        }
        if (document.Bones is null || document.Shapes is null || document.Warnings is null)
        {
            throw new InvalidDataException("cd-hkx returned an incomplete preview report.");
        }
        if (document.BoneCount != document.Bones.Count || document.ShapeCount != document.Shapes.Count)
        {
            throw new InvalidDataException("cd-hkx returned inconsistent preview geometry counts.");
        }
        if (document.Bones.Count > 4096
            || document.Shapes.Count > 96
            || document.Shapes.Sum(static shape => shape.Vertices?.Count ?? 0) > 4096
            || document.Shapes.Sum(static shape => shape.Triangles?.Count ?? 0) > 8192)
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
        foreach (var shape in document.Shapes)
        {
            if (string.IsNullOrWhiteSpace(shape.ShapeType)
                || shape.Endpoints is null || shape.Vertices is null || shape.Triangles is null
                || !IsVector(shape.Center, optional: true)
                || !IsVector(shape.HalfExtents, optional: true)
                || shape.Endpoints.Any(static vector => !IsVector(vector, optional: false))
                || shape.Vertices.Any(static vector => !IsVector(vector, optional: false))
                || shape.Triangles.Any(triangle => triangle is null || triangle.Length != 3 || triangle.Any(index => index < 0 || index >= shape.Vertices.Count))
                || shape.Radius is { } radius && (!float.IsFinite(radius) || radius <= 0))
            {
                throw new InvalidDataException("cd-hkx returned invalid collision preview geometry.");
            }
        }
    }

    private static bool IsVector(float[]? vector, bool optional) =>
        vector is null
            ? optional
            : vector.Length == 3 && vector.All(float.IsFinite);

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
            document.Shapes.Count,
            [
                new GeometryBatch("Skeleton bones", [0.50f, 0.72f, 0.92f], links),
                new GeometryBatch("Skeleton joints", [0.95f, 0.65f, 0.28f], joints),
            ]);
    }

    private static GeometrySummary BuildCollisionGeometry(HkxPreviewDocument document)
    {
        if (document.Shapes.Count == 0)
        {
            throw new InvalidDataException("HKX contains no decoded collision shapes.");
        }
        var boxes = new List<Triangle>();
        var spheres = new List<Triangle>();
        var capsules = new List<Triangle>();
        var hulls = new List<Triangle>();
        foreach (var shape in document.Shapes)
        {
            switch (shape.ShapeType.ToLowerInvariant())
            {
                case "box" when shape.Center is not null && shape.HalfExtents is not null:
                    AddBox(boxes, ToVector(shape.Center), ToVector(shape.HalfExtents));
                    break;
                case "sphere" when shape.Center is not null && shape.Radius is { } sphereRadius:
                    AddSphere(spheres, ToVector(shape.Center), sphereRadius, 16, 10);
                    break;
                case "capsule" when shape.Endpoints.Count >= 2 && shape.Radius is { } capsuleRadius:
                    var start = ToVector(shape.Endpoints[0]);
                    var end = ToVector(shape.Endpoints[1]);
                    AddCylinder(capsules, start, end, capsuleRadius, 14);
                    AddSphere(capsules, start, capsuleRadius, 14, 8);
                    AddSphere(capsules, end, capsuleRadius, 14, 8);
                    break;
                case "convex":
                    foreach (var triangle in shape.Triangles)
                    {
                        hulls.Add(new Triangle(
                            ToVector(shape.Vertices[triangle[0]]),
                            ToVector(shape.Vertices[triangle[1]]),
                            ToVector(shape.Vertices[triangle[2]])));
                    }
                    break;
            }
        }
        var batches = NormalizeGeometryBatches([
            new GeometryBatch("Collision boxes", [0.56f, 0.68f, 0.82f], boxes),
            new GeometryBatch("Collision spheres", [0.48f, 0.72f, 0.86f], spheres),
            new GeometryBatch("Collision capsules", [0.64f, 0.76f, 0.88f], capsules),
            new GeometryBatch("Collision hulls", [0.58f, 0.70f, 0.84f], hulls),
        ]);
        if (batches.All(static batch => batch.Triangles.Count == 0))
        {
            throw new InvalidDataException("Decoded HKX collision shapes did not produce renderable geometry.");
        }
        return new GeometrySummary("collision", document.Bones.Count, document.Shapes.Count, batches);
    }

    private static IReadOnlyList<GeometryBatch> NormalizeGeometryBatches(IReadOnlyList<GeometryBatch> batches)
    {
        var points = batches
            .SelectMany(static batch => batch.Triangles)
            .SelectMany(static triangle => new[] { triangle.A, triangle.B, triangle.C })
            .ToArray();
        if (points.Length == 0)
        {
            return batches;
        }
        var min = points.Aggregate(Vector3.Min);
        var max = points.Aggregate(Vector3.Max);
        var center = (min + max) * 0.5f;
        var extent = Math.Max(Math.Max(max.X - min.X, max.Y - min.Y), max.Z - min.Z);
        var scale = extent > 1e-6f ? 1.8f / extent : 1.0f;
        Vector3 Transform(Vector3 point) => (point - center) * scale;
        return batches
            .Select(batch => batch with
            {
                Triangles = batch.Triangles
                    .Select(triangle => new Triangle(Transform(triangle.A), Transform(triangle.B), Transform(triangle.C)))
                    .ToArray(),
            })
            .ToArray();
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

    private static void AddBox(List<Triangle> output, Vector3 center, Vector3 halfExtents)
    {
        var min = center - halfExtents;
        var max = center + halfExtents;
        var vertices = new[]
        {
            new Vector3(min.X, min.Y, min.Z), new Vector3(max.X, min.Y, min.Z),
            new Vector3(max.X, max.Y, min.Z), new Vector3(min.X, max.Y, min.Z),
            new Vector3(min.X, min.Y, max.Z), new Vector3(max.X, min.Y, max.Z),
            new Vector3(max.X, max.Y, max.Z), new Vector3(min.X, max.Y, max.Z),
        };
        foreach (var (a, b, c, d) in new[]
        {
            (0, 2, 1, 3), (4, 5, 6, 7), (0, 1, 5, 4),
            (3, 7, 6, 2), (0, 4, 7, 3), (1, 2, 6, 5),
        })
        {
            output.Add(new(vertices[a], vertices[b], vertices[c]));
            output.Add(new(vertices[a], vertices[d], vertices[b]));
        }
    }

    private static void AddSphere(List<Triangle> output, Vector3 center, float radius, int segments, int rings)
    {
        segments = Math.Max(6, segments);
        rings = Math.Max(3, rings);
        var ringPoints = new Vector3[rings - 1][];
        for (var ring = 1; ring < rings; ring++)
        {
            var latitude = MathF.PI * 0.5f - MathF.PI * ring / rings;
            var y = MathF.Sin(latitude);
            var radial = MathF.Cos(latitude);
            ringPoints[ring - 1] = Enumerable.Range(0, segments)
                .Select(segment =>
                {
                    var longitude = MathF.Tau * segment / segments;
                    return center + new Vector3(
                        radial * MathF.Cos(longitude),
                        y,
                        radial * MathF.Sin(longitude)) * radius;
                })
                .ToArray();
        }
        var top = center + Vector3.UnitY * radius;
        var bottom = center - Vector3.UnitY * radius;
        for (var segment = 0; segment < segments; segment++)
        {
            var next = (segment + 1) % segments;
            output.Add(new(top, ringPoints[0][segment], ringPoints[0][next]));
            for (var ring = 0; ring < ringPoints.Length - 1; ring++)
            {
                var a = ringPoints[ring][segment];
                var b = ringPoints[ring][next];
                var c = ringPoints[ring + 1][next];
                var d = ringPoints[ring + 1][segment];
                output.Add(new(a, d, c));
                output.Add(new(a, c, b));
            }
            var last = ringPoints[^1];
            output.Add(new(bottom, last[next], last[segment]));
        }
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
                shape_count = summary.ShapeCount,
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

    private sealed record GeometrySummary(string Kind, int BoneCount, int ShapeCount, IReadOnlyList<GeometryBatch> Batches);
    private sealed record GeometryBatch(string Name, float[] Color, IReadOnlyList<Triangle> Triangles);
    private sealed record Triangle(Vector3 A, Vector3 B, Vector3 C);
}

public sealed record HkxPreviewArtifact(
    string PackagePath,
    string PreviewKind,
    int BoneCount,
    int ShapeCount,
    string SdkVersion,
    IReadOnlyList<string> Warnings);

public sealed record HkxPreviewDocument(
    [property: JsonPropertyName("format")] string Format,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("preview_kind")] string PreviewKind,
    [property: JsonPropertyName("sdk_version")] string SdkVersion,
    [property: JsonPropertyName("bone_count")] int BoneCount,
    [property: JsonPropertyName("bones")] IReadOnlyList<HkxPreviewBone> Bones,
    [property: JsonPropertyName("shape_count")] int ShapeCount,
    [property: JsonPropertyName("shapes")] IReadOnlyList<HkxPreviewShape> Shapes,
    [property: JsonPropertyName("warnings")] IReadOnlyList<string> Warnings);

public sealed record HkxPreviewBone(
    [property: JsonPropertyName("index")] int Index,
    [property: JsonPropertyName("parent_index")] int ParentIndex,
    [property: JsonPropertyName("position")] float[] Position);

public sealed record HkxPreviewShape(
    [property: JsonPropertyName("record_index")] int RecordIndex,
    [property: JsonPropertyName("shape_type")] string ShapeType,
    [property: JsonPropertyName("center")] float[]? Center,
    [property: JsonPropertyName("half_extents")] float[]? HalfExtents,
    [property: JsonPropertyName("radius")] float? Radius,
    [property: JsonPropertyName("endpoints")] IReadOnlyList<float[]> Endpoints,
    [property: JsonPropertyName("vertices")] IReadOnlyList<float[]> Vertices,
    [property: JsonPropertyName("triangles")] IReadOnlyList<int[]> Triangles);

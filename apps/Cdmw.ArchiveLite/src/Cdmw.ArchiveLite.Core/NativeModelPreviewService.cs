using System.Collections.Concurrent;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class NativeModelPreviewService
{
    private const string PackageVersion = "archive_lite_native_model_v2";
    private static readonly TimeSpan PreviewTimeout = TimeSpan.FromSeconds(90);
    private static readonly TimeSpan ColdBuildCoalesceDelay = TimeSpan.FromMilliseconds(35);
    private readonly ConcurrentDictionary<string, SemaphoreSlim> _buildGates = new(StringComparer.Ordinal);

    public static bool Supports(string extension) => extension.ToLowerInvariant() is ".pac" or ".pam" or ".pamlod";

    public async Task<string> BuildAsync(
        ArchiveSession session,
        ArchiveEntryDto entry,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(session);
        ArgumentNullException.ThrowIfNull(entry);
        if (!Supports(entry.Extension))
        {
            throw new NotSupportedException($"Native model preview does not support {entry.Extension}.");
        }

        var companion = FindCompanion(session.Index, entry);
        ArchiveLiteDataPaths.EnsureCreated();
        var key = NativeModelPreviewCache.ComputeKey(PackageVersion, session, entry, companion);
        var modelRoot = Path.Combine(ArchiveLiteDataPaths.PreviewCache, "models");
        var nativeCacheRoot = Path.Combine(ArchiveLiteDataPaths.PreviewCache, "native");
        Directory.CreateDirectory(modelRoot);
        Directory.CreateDirectory(nativeCacheRoot);
        var destination = Path.Combine(modelRoot, key);
        if (await NativeModelPreviewCache.IsReusableAsync(
                destination,
                PackageVersion,
                key,
                session,
                entry,
                cancellationToken).ConfigureAwait(false))
        {
            return destination;
        }
        await Task.Delay(ColdBuildCoalesceDelay, cancellationToken).ConfigureAwait(false);
        if (await NativeModelPreviewCache.IsReusableAsync(
                destination,
                PackageVersion,
                key,
                session,
                entry,
                cancellationToken).ConfigureAwait(false))
        {
            return destination;
        }

        var gate = _buildGates.GetOrAdd(key, static _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (await NativeModelPreviewCache.IsReusableAsync(
                    destination,
                    PackageVersion,
                    key,
                    session,
                    entry,
                    cancellationToken).ConfigureAwait(false))
            {
                return destination;
            }
            if (Directory.Exists(destination))
            {
                DeleteOwnedDirectory(modelRoot, destination);
            }

            var staging = Path.Combine(modelRoot, $"_staging_{Guid.NewGuid():N}");
            Directory.CreateDirectory(staging);
            try
            {
                var packageRoot = Path.Combine(staging, "package");
                var protocolRoot = Path.Combine(staging, "protocol");
                Directory.CreateDirectory(protocolRoot);
                var jobPath = Path.Combine(protocolRoot, "job.json");
                var reportPath = Path.Combine(protocolRoot, "report.json");
                await PublishAsync(publishProgress, "model_preview_native", cancellationToken).ConfigureAwait(false);
                await WriteJobAsync(jobPath, packageRoot, nativeCacheRoot, session, entry, companion, cancellationToken).ConfigureAwait(false);
                await RunPreviewCoreAsync(jobPath, reportPath, cancellationToken).ConfigureAwait(false);
                var dependencyTrace = ValidateReport(reportPath, staging, packageRoot);

                await PublishAsync(publishProgress, "model_preview_adapt", cancellationToken).ConfigureAwait(false);
                var cacheManifest = await NativeModelPreviewCache.CaptureAsync(
                    PackageVersion,
                    key,
                    session,
                    entry,
                    dependencyTrace,
                    cancellationToken).ConfigureAwait(false);
                await NativePreviewPackageAdapter.PrepareAsync(
                    packageRoot,
                    cacheManifest.SourceIdentity,
                    cancellationToken).ConfigureAwait(false);
                await AtomicFile.WriteAsync(
                    Path.Combine(packageRoot, "archive_lite_preview.json"),
                    async (stream, token) => await JsonSerializer.SerializeAsync(
                        stream,
                        cacheManifest,
                        NativePreviewPackageAdapter.JsonOptions,
                        token).ConfigureAwait(false),
                    cancellationToken,
                    flushToDisk: false).ConfigureAwait(false);

                try
                {
                    Directory.Move(packageRoot, destination);
                }
                catch (IOException)
                {
                    if (!await NativeModelPreviewCache.IsReusableAsync(
                            destination,
                            PackageVersion,
                            key,
                            session,
                            entry,
                            cancellationToken).ConfigureAwait(false))
                    {
                        throw;
                    }
                    // Another worker published the same reusable package first.
                }
                return destination;
            }
            finally
            {
                if (Directory.Exists(staging))
                {
                    DeleteOwnedDirectory(modelRoot, staging);
                }
            }
        }
        finally
        {
            gate.Release();
        }
    }

    private static async Task PublishAsync(
        Func<ProgressUpdate, Task>? publishProgress,
        string phase,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (publishProgress is not null)
        {
            await publishProgress(new ProgressUpdate(0, 0, phase)).ConfigureAwait(false);
        }
    }

    private static async Task WriteJobAsync(
        string path,
        string outputRoot,
        string cacheRoot,
        ArchiveSession session,
        ArchiveEntryDto entry,
        ArchiveEntryDto? companion,
        CancellationToken cancellationToken)
    {
        var payload = new Dictionary<string, object?>
        {
            ["version"] = 1,
            ["backend"] = "cdmw_preview_core_0.1",
            ["renderer_backend"] = "d3d11",
            ["schema_version"] = 8,
            ["created_at"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0,
            ["package_root"] = session.PackageRoot,
            ["archive_index_path"] = session.Index.Path,
            ["archive_basename_index_path"] = session.BasenameIndex.Path,
            ["cache_root"] = cacheRoot,
            ["output_root"] = outputRoot,
            ["entry"] = EntryPayload(entry),
            ["companion_entry"] = companion is null ? new Dictionary<string, object?>() : EntryPayload(companion),
            ["render_settings"] = new Dictionary<string, object?>
            {
                ["visible_texture_mode"] = "mesh_base_first",
                ["d3d11_view_mode"] = "lit",
                ["use_textures_by_default"] = false,
                ["high_quality_by_default"] = true,
            },
            ["capabilities"] = new Dictionary<string, object?>
            {
                ["direct_dds"] = true,
                ["d3d11_package"] = true,
                ["material_index"] = false,
                ["material_graph"] = false,
                ["material_graph_version"] = 3,
                ["python_fallback_allowed"] = false,
                ["native_material_runtime"] = false,
            },
        };
        await AtomicFile.WriteAsync(
            path,
            async (stream, token) => await JsonSerializer.SerializeAsync(
                stream,
                payload,
                NativePreviewPackageAdapter.JsonOptions,
                token).ConfigureAwait(false),
            cancellationToken,
            flushToDisk: false).ConfigureAwait(false);
    }

    private static ArchiveEntryDto? FindCompanion(ArchiveIndex index, ArchiveEntryDto entry)
    {
        var normalizedPath = entry.Path.Replace('\\', '/').Trim('/');
        var candidates = new List<string>(2);
        if (entry.Extension.Equals(".pam", StringComparison.OrdinalIgnoreCase)
            && normalizedPath.EndsWith(".pam", StringComparison.OrdinalIgnoreCase))
        {
            var stem = normalizedPath[..^4];
            candidates.Add(stem + ".pamlod");
            if (stem.EndsWith("_breakable", StringComparison.OrdinalIgnoreCase))
            {
                candidates.Add(stem[..^10] + ".pamlod");
            }
        }
        else if (entry.Extension.Equals(".pamlod", StringComparison.OrdinalIgnoreCase)
            && normalizedPath.EndsWith(".pamlod", StringComparison.OrdinalIgnoreCase))
        {
            candidates.Add(normalizedPath[..^7] + ".pam");
        }

        foreach (var path in candidates)
        {
            var matches = index.FindEntriesByPath(path);
            if (matches.Count == 0)
            {
                continue;
            }
            return matches.FirstOrDefault(candidate => candidate.SourcePamt.Equals(entry.SourcePamt, StringComparison.OrdinalIgnoreCase))
                ?? matches[0];
        }
        return null;
    }

    private static Dictionary<string, object?> EntryPayload(ArchiveEntryDto entry) => new()
    {
        ["path"] = entry.Path,
        ["basename"] = entry.Name,
        ["extension"] = entry.Extension,
        ["pamt_path"] = entry.SourcePamt,
        ["paz_file"] = entry.PazFile,
        ["offset"] = entry.Offset,
        ["comp_size"] = entry.StoredSize,
        ["orig_size"] = entry.OriginalSize,
        ["flags"] = entry.Flags,
        ["paz_index"] = entry.PazIndex,
        ["compression_type"] = entry.CompressionType,
    };

    private static async Task RunPreviewCoreAsync(
        string jobPath,
        string reportPath,
        CancellationToken cancellationToken)
    {
        var executable = ResolvePreviewCorePath();
        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(executable) ?? AppContext.BaseDirectory,
        };
        startInfo.ArgumentList.Add("preview-job");
        startInfo.ArgumentList.Add(jobPath);
        startInfo.ArgumentList.Add(reportPath);
        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("cdmw-preview-core could not be started.");
        var stdout = ReadBoundedAsync(process.StandardOutput, cancellationToken);
        var stderr = ReadBoundedAsync(process.StandardError, cancellationToken);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(PreviewTimeout);
        try
        {
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            StopProcess(process);
            await ObserveCaptureAsync(stdout, stderr).ConfigureAwait(false);
            throw new TimeoutException($"cdmw-preview-core did not finish within {PreviewTimeout.TotalSeconds:N0} seconds.");
        }
        catch (OperationCanceledException)
        {
            StopProcess(process);
            await ObserveCaptureAsync(stdout, stderr).ConfigureAwait(false);
            throw;
        }

        var stdoutText = await stdout.ConfigureAwait(false);
        var stderrText = await stderr.ConfigureAwait(false);
        if (process.ExitCode != 0)
        {
            var detail = string.IsNullOrWhiteSpace(stderrText) ? stdoutText : stderrText;
            throw new InvalidDataException($"cdmw-preview-core exited with code {process.ExitCode}: {detail.Trim()}");
        }
    }

    private static NativePreviewDependencyTrace ValidateReport(
        string reportPath,
        string stagingRoot,
        string expectedPackageRoot)
    {
        if (!File.Exists(reportPath))
        {
            throw new InvalidDataException("cdmw-preview-core did not produce a report.");
        }
        using var report = JsonDocument.Parse(File.ReadAllText(reportPath));
        var root = report.RootElement;
        var status = ReadString(root, "status").Trim().ToLowerInvariant();
        var message = ReadString(root, "fallback_reason", ReadString(root, "message"));
        if (status != "ok")
        {
            throw new InvalidDataException(string.IsNullOrWhiteSpace(message)
                ? $"cdmw-preview-core reported '{status}'."
                : message);
        }
        var packagePath = Path.GetFullPath(ReadString(root, "package_path"));
        RequireContained(stagingRoot, packagePath);
        if (!packagePath.Equals(Path.GetFullPath(expectedPackageRoot), StringComparison.OrdinalIgnoreCase)
            || !File.Exists(Path.Combine(packagePath, "manifest.json")))
        {
            throw new InvalidDataException("cdmw-preview-core reported an unexpected or incomplete package path.");
        }
        return NativeModelPreviewCache.ReadTrace(root);
    }

    private static string ResolvePreviewCorePath()
    {
        var overridePath = Environment.GetEnvironmentVariable("CDMW_ARCHIVE_LITE_PREVIEW_CORE_PATH");
        if (!string.IsNullOrWhiteSpace(overridePath) && File.Exists(overridePath))
        {
            return Path.GetFullPath(overridePath);
        }
        var packaged = Path.Combine(AppContext.BaseDirectory, "preview", "cdmw-preview-core.exe");
        if (File.Exists(packaged))
        {
            return packaged;
        }
        for (var current = new DirectoryInfo(AppContext.BaseDirectory); current is not null; current = current.Parent)
        {
            foreach (var configuration in new[] { "Release", "Debug" })
            {
                var candidate = Path.Combine(
                    current.FullName,
                    "native",
                    "cdmw_preview_core",
                    "build",
                    configuration,
                    "cdmw-preview-core.exe");
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
        }
        throw new FileNotFoundException(
            "cdmw-preview-core.exe was not found. Rebuild the Archive Lite portable package or set CDMW_ARCHIVE_LITE_PREVIEW_CORE_PATH.");
    }

    private static async Task<string> ReadBoundedAsync(StreamReader reader, CancellationToken cancellationToken)
    {
        const int maximumCharacters = 64 * 1024;
        var output = new StringBuilder();
        var buffer = new char[4096];
        while (true)
        {
            var count = await reader.ReadAsync(buffer.AsMemory(), cancellationToken).ConfigureAwait(false);
            if (count == 0)
            {
                break;
            }
            if (output.Length < maximumCharacters)
            {
                output.Append(buffer, 0, Math.Min(count, maximumCharacters - output.Length));
            }
        }
        return output.ToString();
    }

    private static async Task ObserveCaptureAsync(params Task<string>[] captures)
    {
        foreach (var capture in captures)
        {
            try
            {
                _ = await capture.ConfigureAwait(false);
            }
            catch
            {
                // The process is already being torn down; only observe the reader task.
            }
        }
    }

    private static void StopProcess(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }
        }
        catch
        {
            // Preserve the cancellation or timeout that owns this teardown.
        }
    }

    private static void DeleteOwnedDirectory(string root, string path)
    {
        RequireContained(root, path);
        Directory.Delete(path, recursive: true);
    }

    private static void RequireContained(string root, string path)
    {
        var resolvedRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var resolvedPath = Path.GetFullPath(path);
        if (!resolvedPath.StartsWith(resolvedRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException($"Preview cache path escapes its owned root: {resolvedPath}");
        }
    }

    private static string ReadString(JsonElement element, string name, string fallback = "")
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? fallback
            : fallback;
    }
}

public static class NativePreviewPackageAdapter
{
    private const int SupportedSchemaVersion = 8;
    private const int BytesPerVertex = 23 * sizeof(float);
    private const int MaximumVertices = 8_000_000;
    internal static JsonSerializerOptions JsonOptions { get; } = new() { WriteIndented = true };

    public static async Task<NativePreviewPackageInfo> PrepareAsync(
        string packageRoot,
        string sourceIdentity,
        CancellationToken cancellationToken)
    {
        var root = Path.GetFullPath(packageRoot);
        var manifestPath = Path.Combine(root, "manifest.json");
        using var manifest = JsonDocument.Parse(await File.ReadAllTextAsync(manifestPath, cancellationToken).ConfigureAwait(false));
        if (manifest.RootElement.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException("Native preview manifest root must be an object.");
        }
        var schemaVersion = ReadInt(manifest.RootElement, "schema_version", -1);
        if (schemaVersion != SupportedSchemaVersion)
        {
            throw new InvalidDataException(
                $"Native preview manifest schema {schemaVersion} is unsupported; expected {SupportedSchemaVersion}.");
        }
        if (!manifest.RootElement.TryGetProperty("batches", out var batches) || batches.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidDataException("Native preview manifest has no batches array.");
        }

        var slots = new List<Dictionary<string, object?>>();
        var submeshes = new List<Dictionary<string, object?>>();
        long totalVertices = 0;
        foreach (var batch in batches.EnumerateArray())
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (batch.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var index = ReadInt(batch, "index", submeshes.Count);
            var vertexCount = ReadInt(batch, "vertex_count", 0);
            if (vertexCount <= 0 || vertexCount % 3 != 0)
            {
                throw new InvalidDataException($"Native preview batch {index} has an invalid vertex count.");
            }
            totalVertices = checked(totalVertices + vertexCount);
            if (totalVertices > MaximumVertices)
            {
                throw new InvalidDataException($"Native preview package exceeds the {MaximumVertices:N0}-vertex safety limit.");
            }
            var geometry = ResolveContainedFile(root, ReadString(batch, "vertex_file"));
            if (new FileInfo(geometry).Length != checked((long)vertexCount * BytesPerVertex))
            {
                throw new InvalidDataException($"Native preview batch {index} has an invalid geometry length.");
            }

            var material = ReadString(batch, "material_name", $"material_{index:000}");
            var channels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var components = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            slots.Add(new Dictionary<string, object?>
            {
                ["index"] = index,
                ["name"] = material,
                ["texture"] = channels.GetValueOrDefault("base", ""),
                ["channels"] = channels,
            });

            var color = ReadFloatArray(batch, "base_color", [0.65f, 0.65f, 0.65f]);
            var category = ReadString(batch, "material_category", "unknown");
            submeshes.Add(new Dictionary<string, object?>
            {
                ["submesh_index"] = index,
                ["material_slot_index"] = index,
                ["material"] = material,
                ["texture"] = channels.GetValueOrDefault("base", ""),
                ["resolved_channels"] = channels,
                ["packaged_channels"] = new Dictionary<string, string>(),
                ["resource_channels"] = new Dictionary<string, string>(),
                ["channel_components"] = components,
                ["channel_color_spaces"] = channels.Keys.ToDictionary(
                    static channel => channel,
                    static channel => channel == "base" ? "srgb" : "linear",
                    StringComparer.OrdinalIgnoreCase),
                ["channel_authorities"] = channels.Keys.ToDictionary(
                    static channel => channel,
                    static _ => "native_preview_core",
                    StringComparer.OrdinalIgnoreCase),
                ["normal_y_policy"] = "shader_invert_legacy_compat",
                ["texture_flip_vertical"] = false,
                ["shader_family"] = ReadString(batch, "shader_family", "generic"),
                ["shader_technique"] = ReadString(batch, "shader_rule", "generic"),
                ["shader_authority"] = "native_preview_core",
                ["shader_family_source"] = "native_preview_core",
                ["shader_family_reason"] = "Native material graph preview package.",
                ["material_category"] = category,
                ["material_category_confidence"] = ReadFloat(batch, "material_category_confidence", 0.35f),
                ["material_category_reason"] = ReadString(batch, "material_category_reason"),
                ["material_response_promoted"] = ReadBool(batch, "material_response_promoted"),
                ["alpha_mode"] = "opaque",
                ["alpha_cutoff"] = 0.5f,
                ["opacity_factor"] = 1.0f,
                ["double_sided"] = false,
                ["unsupported_features"] = Array.Empty<string>(),
                ["parameters"] = new Dictionary<string, object?>
                {
                    ["base_color"] = color,
                    ["base_tint_strength"] = 1.0f,
                    ["roughness"] = ReadFloat(batch, "roughness", 0.62f),
                    ["metalness"] = ReadFloat(batch, "metalness", 0.0f),
                    ["specular"] = ReadFloat(batch, "specular", 0.25f),
                    ["height_scale"] = ReadFloat(batch, "height_scale", 0.0f),
                    ["material_role"] = category,
                },
            });
        }
        if (submeshes.Count == 0)
        {
            throw new InvalidDataException("Native preview package did not contain renderable batches.");
        }

        var manifestBytes = await File.ReadAllBytesAsync(manifestPath, cancellationToken).ConfigureAwait(false);
        var signature = Convert.ToHexString(SHA256.HashData(manifestBytes)).ToLowerInvariant();
        await WriteJsonAsync(
            Path.Combine(root, "net_materials.json"),
            new Dictionary<string, object?>
            {
                ["schema"] = "cdmw_archive_lite_native_materials_v1",
                ["material_signature"] = signature,
                ["material_slots"] = slots,
                ["submeshes"] = submeshes,
            },
            cancellationToken).ConfigureAwait(false);
        await WriteJsonAsync(
            Path.Combine(root, "dotnet_scene.json"),
            new Dictionary<string, object?>
            {
                ["session_id"] = "archive_lite",
                ["source_identity"] = sourceIdentity,
                ["scene_generation"] = 1,
                ["editable_submesh_count"] = submeshes.Count,
                ["reference_submesh_count"] = 0,
                ["interaction_mode"] = "placement",
                ["comparison_mode"] = "replacement_only",
                ["grid"] = new Dictionary<string, object?> { ["visible"] = false, ["origin"] = new[] { 0.0f, -1.0f, 0.0f }, ["spacing"] = 0.25f },
                ["gizmo"] = new Dictionary<string, object?> { ["visible"] = false, ["tool"] = "move" },
            },
            cancellationToken).ConfigureAwait(false);
        await WriteJsonAsync(
            Path.Combine(root, "mesh.cdmeta.json"),
            new Dictionary<string, object?>
            {
                ["schema"] = "cdmw_archive_lite_preview_metadata_v1",
                ["source_identity"] = sourceIdentity,
                ["native_manifest"] = "manifest.json",
                ["read_only"] = true,
            },
            cancellationToken).ConfigureAwait(false);
        return new NativePreviewPackageInfo(submeshes.Count, totalVertices, manifestPath);
    }

    private static Dictionary<string, string> ResolveChannels(
        string packageRoot,
        JsonElement batch,
        out Dictionary<string, string> components)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        components = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (!batch.TryGetProperty("dds_textures", out var textures) || textures.ValueKind != JsonValueKind.Object)
        {
            return result;
        }
        foreach (var texture in textures.EnumerateObject())
        {
            if (texture.Value.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var path = ReadString(texture.Value, "source_path");
            if (string.IsNullOrWhiteSpace(path))
            {
                continue;
            }
            path = Path.IsPathRooted(path)
                ? Path.GetFullPath(path)
                : ResolveContainedFile(packageRoot, path);
            if (!File.Exists(path))
            {
                continue;
            }
            var slot = texture.Name.ToLowerInvariant();
            result[slot] = path;
            if (slot == "material")
            {
                result["specular"] = path;
                result["roughness"] = path;
                result["metallic"] = path;
                var packed = ReadString(texture.Value, "packed_channels");
                components["specular"] = FindComponent(packed, "specular", "r");
                components["roughness"] = FindComponent(packed, "roughness", "g");
                components["metallic"] = FindComponent(packed, "metalness", "b");
            }
        }
        return result;
    }

    private static string FindComponent(string packed, string semantic, string fallback)
    {
        var normalized = packed.ToLowerInvariant().Replace("metallic", "metalness", StringComparison.Ordinal);
        foreach (var channel in new[] { "r", "g", "b", "a" })
        {
            if (normalized.Contains($"{semantic}={channel}", StringComparison.Ordinal)
                || normalized.Contains($"{semantic}:{channel}", StringComparison.Ordinal)
                || normalized.Contains($"{channel}={semantic}", StringComparison.Ordinal)
                || normalized.Contains($"{channel}:{semantic}", StringComparison.Ordinal))
            {
                return channel;
            }
        }
        return fallback;
    }

    private static async Task WriteJsonAsync(string path, object payload, CancellationToken cancellationToken)
    {
        await AtomicFile.WriteAsync(
            path,
            async (stream, token) => await JsonSerializer.SerializeAsync(stream, payload, JsonOptions, token).ConfigureAwait(false),
            cancellationToken,
            flushToDisk: false).ConfigureAwait(false);
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
        return element.TryGetProperty(name, out var value) && value.TryGetInt32(out var result) ? result : fallback;
    }

    private static float ReadFloat(JsonElement element, string name, float fallback)
    {
        return element.TryGetProperty(name, out var value)
            && value.TryGetSingle(out var result)
            && float.IsFinite(result)
                ? result
                : fallback;
    }

    private static bool ReadBool(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;
    }

    private static float[] ReadFloatArray(JsonElement element, string name, float[] fallback)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return fallback;
        }
        var result = value.EnumerateArray()
            .Take(3)
            .Select(item => item.TryGetSingle(out var number) && float.IsFinite(number) ? number : 0.0f)
            .ToArray();
        return result.Length == 3 ? result : fallback;
    }

    private static string ReadString(JsonElement element, string name, string fallback = "")
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? fallback
            : fallback;
    }
}

public sealed record NativePreviewPackageInfo(int BatchCount, long VertexCount, string ManifestPath);

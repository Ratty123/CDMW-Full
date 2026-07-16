using System.Reflection;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal static class HelperBuildProvenance
{
    public const string ManifestFileName = "cdmw-mesh-dotnet-editor.manifest.json";
    private static readonly Lazy<IReadOnlyDictionary<string, object?>> CachedIdentity = new(
        BuildIdentityPayload,
        LazyThreadSafetyMode.ExecutionAndPublication);
    public static readonly string[] RequiredProtocolCapabilities =
    {
        "mesh_edit_revision_ack_v1",
        "resident_mutation_envelope_v2",
        "host_tool_state_v1",
        "resident_material_updates_v2",
        "resident_material_parameter_updates_v1",
        "resident_texture_region_updates_v1",
        "viewport_display_modes_v1",
        "resident_scene_state_v1",
        "authoritative_resident_scene_frame_v2",
        "helper_build_provenance_v1",
        "deterministic_offscreen_capture_v1",
        "performance_capture_v1",
    };

    public static Dictionary<string, object?> Payload(IEnumerable<string> capabilities)
    {
        var payload = new Dictionary<string, object?>(CachedIdentity.Value, StringComparer.Ordinal)
        {
            ["capabilities"] = capabilities.Order(StringComparer.Ordinal).ToArray(),
        };
        return payload;
    }

    private static IReadOnlyDictionary<string, object?> BuildIdentityPayload()
    {
        var processPath = Environment.ProcessPath ?? string.Empty;
        var assembly = Assembly.GetExecutingAssembly();
        var assemblyPath = assembly.Location;
        var manifestPath = CandidateManifestPaths(processPath, assemblyPath)
            .FirstOrDefault(File.Exists) ?? string.Empty;
        var manifest = ReadManifest(manifestPath);
        var processSha = HashFile(processPath);
        var assemblySha = HashFile(assemblyPath);
        var shaderSha = ShaderSha256();
        var manifestId = Text(manifest, "manifest_id");
        var mode = string.IsNullOrWhiteSpace(manifestPath) ? "development" : "release_manifest";
        if (string.IsNullOrWhiteSpace(manifestId))
        {
            manifestId = $"development:{Prefix(processSha)}:{Prefix(shaderSha)}";
        }
        return new Dictionary<string, object?>
        {
            ["semantic_version"] = assembly.GetName().Version?.ToString(3) ?? "0.0.0",
            ["informational_version"] = assembly
                .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? string.Empty,
            ["protocol_version"] = 2,
            ["manifest_mode"] = mode,
            ["manifest_id"] = manifestId,
            ["source_revision"] = Text(manifest, "source_revision"),
            ["process_path"] = processPath,
            ["process_sha256"] = processSha,
            ["assembly_path"] = assemblyPath,
            ["assembly_sha256"] = assemblySha,
            ["shader_sha256"] = shaderSha,
            ["renderer_backend"] = "d3d11_vortice_shader",
            ["edit_backend"] = "cdmw_mesh_core_0.1",
        };
    }

    private static IEnumerable<string> CandidateManifestPaths(string processPath, string assemblyPath)
    {
        if (!string.IsNullOrWhiteSpace(processPath))
        {
            yield return Path.Combine(Path.GetDirectoryName(processPath) ?? string.Empty, ManifestFileName);
        }
        if (!string.IsNullOrWhiteSpace(assemblyPath))
        {
            yield return Path.Combine(Path.GetDirectoryName(assemblyPath) ?? string.Empty, ManifestFileName);
        }
        yield return Path.Combine(AppContext.BaseDirectory, ManifestFileName);
    }

    private static Dictionary<string, string> ReadManifest(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return new Dictionary<string, string>(StringComparer.Ordinal);
        }
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            return document.RootElement.EnumerateObject().ToDictionary(
                property => property.Name,
                property => property.Value.ValueKind == JsonValueKind.String
                    ? property.Value.GetString() ?? string.Empty
                    : property.Value.GetRawText(),
                StringComparer.Ordinal);
        }
        catch
        {
            return new Dictionary<string, string>(StringComparer.Ordinal);
        }
    }

    private static string Text(IReadOnlyDictionary<string, string> values, string key) =>
        values.TryGetValue(key, out var value) ? value : string.Empty;

    private static string HashFile(string path)
    {
        try
        {
            return !string.IsNullOrWhiteSpace(path) && File.Exists(path)
                ? Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant()
                : string.Empty;
        }
        catch
        {
            return string.Empty;
        }
    }

    private static string ShaderSha256()
    {
        var adjacent = Path.Combine(AppContext.BaseDirectory, "D3D11MaterialShaders.hlsl");
        if (File.Exists(adjacent))
        {
            return HashFile(adjacent);
        }
        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("D3D11MaterialShaders.hlsl");
        if (stream is null)
        {
            return string.Empty;
        }
        using var memory = new MemoryStream();
        stream.CopyTo(memory);
        return Convert.ToHexString(SHA256.HashData(memory.ToArray())).ToLowerInvariant();
    }

    private static string Prefix(string value) => value.Length >= 16 ? value[..16] : value;
}

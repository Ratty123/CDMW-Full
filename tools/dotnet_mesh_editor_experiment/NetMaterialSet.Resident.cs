using System.Globalization;
using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class NetMaterialSet
{
    private static readonly string[] TextureSemantics =
    {
        "base", "albedo", "diffuse", "normal", "specular", "material",
        "roughness", "metallic", "height", "emissive", "opacity", "occlusion",
        "layer_mask", "mask"
    };

    public NetMaterialStateSnapshot CaptureState()
    {
        return new NetMaterialStateSnapshot(Slots, Submeshes, Resources, ManifestDirectory, Signature, Generation);
    }

    public NetMaterialStateUpdate NormalizeStateUpdate(NetMaterialStateUpdate update)
    {
        return update with
        {
            Resources = update.Resources.Select(resource =>
            {
                var path = Path.IsPathRooted(resource.Path) || string.IsNullOrWhiteSpace(ManifestDirectory)
                    ? resource.Path
                    : Path.GetFullPath(Path.Combine(ManifestDirectory, resource.Path));
                return resource with { Path = path };
            }).ToArray()
        };
    }

    public NetMaterialStateSnapshot BuildState(NetMaterialStateUpdate update)
    {
        var resources = new Dictionary<string, NetMaterialResource>(Resources, StringComparer.Ordinal);
        var affectedResourceIds = update.ResourceIdsForAffectedSubmeshes();
        foreach (var resource in update.Resources.Where(resource => affectedResourceIds.Contains(resource.ResourceId)))
        {
            resources[resource.ResourceId] = resource;
        }

        var affected = update.AffectedSubmeshes.ToHashSet();
        var submeshes = Submeshes.ToDictionary(binding => binding.SubmeshIndex);
        foreach (var binding in update.Submeshes.Where(binding => affected.Contains(binding.SubmeshIndex)))
        {
            submeshes[binding.SubmeshIndex] = binding;
        }
        var activeResourceIds = submeshes.Values
            .SelectMany(binding => binding.ResourceChannels.Values)
            .ToHashSet(StringComparer.Ordinal);
        resources = resources
            .Where(pair => activeResourceIds.Contains(pair.Key))
            .ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal);
        return new NetMaterialStateSnapshot(
            Slots,
            submeshes.Values.OrderBy(binding => binding.SubmeshIndex).ToArray(),
            resources,
            ManifestDirectory,
            update.MaterialSignature,
            update.Generation);
    }

    public void ReplaceState(NetMaterialStateSnapshot state)
    {
        Slots = state.Slots;
        Submeshes = state.Submeshes;
        Resources = state.Resources;
        ManifestDirectory = state.ManifestDirectory;
        Signature = state.Signature;
        Generation = state.Generation;
    }

    public IReadOnlySet<int> RemapTopologyState(
        IReadOnlyDictionary<int, int> materialSources,
        int submeshCount)
    {
        var count = Math.Max(0, submeshCount);
        var previousBindings = Submeshes.ToDictionary(binding => binding.SubmeshIndex);
        var previousParameters = ParameterStates;
        var nextBindings = previousBindings
            .Where(pair => pair.Key >= 0 && pair.Key < count)
            .ToDictionary(pair => pair.Key, pair => pair.Value);
        var nextParameters = previousParameters
            .Where(pair => pair.Key >= 0 && pair.Key < count)
            .ToDictionary(pair => pair.Key, pair => pair.Value);
        var reboundTargets = new HashSet<int>();

        foreach (var (targetIndex, sourceIndex) in materialSources)
        {
            if (targetIndex < 0 || targetIndex >= count || sourceIndex < 0)
            {
                continue;
            }
            if (previousBindings.TryGetValue(sourceIndex, out var binding))
            {
                nextBindings[targetIndex] = binding with { SubmeshIndex = targetIndex };
                reboundTargets.Add(targetIndex);
            }
            else
            {
                nextBindings.Remove(targetIndex);
            }
            if (previousParameters.TryGetValue(sourceIndex, out var parameters))
            {
                nextParameters[targetIndex] = parameters;
            }
            else
            {
                nextParameters.Remove(targetIndex);
            }
        }

        Submeshes = nextBindings.Values.OrderBy(binding => binding.SubmeshIndex).ToArray();
        ParameterStates = nextParameters;
        return reboundTargets;
    }

    public NetMaterialTextureReference TextureReferenceForSubmesh(int submeshIndex, params string[] keys)
    {
        var binding = Submeshes.FirstOrDefault(item => item.SubmeshIndex == submeshIndex);
        if (binding is null)
        {
            return NetMaterialTextureReference.Empty;
        }
        foreach (var key in keys)
        {
            if (binding.ResourceChannels.TryGetValue(key, out var resourceId)
                && Resources.TryGetValue(resourceId, out var resource))
            {
                binding.ChannelColorSpaces.TryGetValue(key, out var colorSpace);
                binding.ChannelAuthorities.TryGetValue(key, out var authority);
                return resource.ReferenceForSemantic(key, colorSpace, authority);
            }
            if (binding.PackageChannels.TryGetValue(key, out var packaged) && !string.IsNullOrWhiteSpace(packaged))
            {
                var packagedPath = ResolveManifestPath(packaged);
                if (File.Exists(packagedPath))
                {
                    return NetMaterialTextureReference.FromPath(packagedPath, key);
                }
            }
            if (binding.ResolvedChannels.TryGetValue(key, out var resolved) && !string.IsNullOrWhiteSpace(resolved))
            {
                return NetMaterialTextureReference.FromPath(resolved, key);
            }
        }
        return NetMaterialTextureReference.Empty;
    }

    public int ChannelComponentIndexForSubmesh(int submeshIndex, string channel)
    {
        var binding = Submeshes.FirstOrDefault(item => item.SubmeshIndex == submeshIndex);
        if (binding is null || !binding.ChannelComponents.TryGetValue(channel, out var component))
        {
            return 0;
        }
        return component.Trim().ToLowerInvariant() switch
        {
            "g" => 1,
            "b" => 2,
            "a" => 3,
            _ => 0,
        };
    }

    public string ShaderFamilyForSubmesh(int submeshIndex)
    {
        var family = Submeshes.FirstOrDefault(item => item.SubmeshIndex == submeshIndex)?.ShaderFamily;
        return string.IsNullOrWhiteSpace(family) ? "generic" : family.Trim().ToLowerInvariant();
    }

    public bool NormalYInvertedForSubmesh(int submeshIndex)
    {
        var binding = Submeshes.FirstOrDefault(item => item.SubmeshIndex == submeshIndex);
        return string.Equals(
            binding?.NormalYPolicy,
            "invert_green_for_directx",
            StringComparison.OrdinalIgnoreCase);
    }

    public bool TextureFlipVerticalForSubmesh(int submeshIndex)
    {
        return Submeshes.FirstOrDefault(item => item.SubmeshIndex == submeshIndex)
            ?.TextureFlipVertical == true;
    }

    public string AlphaModeForSubmesh(int submeshIndex)
    {
        return Submeshes.FirstOrDefault(item => item.SubmeshIndex == submeshIndex)?.AlphaMode ?? "opaque";
    }

    public float AlphaCutoffForSubmesh(int submeshIndex)
    {
        return Math.Clamp(
            Submeshes.FirstOrDefault(item => item.SubmeshIndex == submeshIndex)?.AlphaCutoff ?? 0.5f,
            0.0f,
            1.0f);
    }

    public float OpacityFactorForSubmesh(int submeshIndex)
    {
        return Math.Clamp(
            Submeshes.FirstOrDefault(item => item.SubmeshIndex == submeshIndex)?.OpacityFactor ?? 1.0f,
            0.0f,
            1.0f);
    }

    public bool DoubleSidedForSubmesh(int submeshIndex)
    {
        return Submeshes.FirstOrDefault(item => item.SubmeshIndex == submeshIndex)?.DoubleSided == true;
    }

    public IReadOnlyList<Dictionary<string, object?>> MaterialSemanticDiagnostics()
    {
        return Submeshes
            .OrderBy(binding => binding.SubmeshIndex)
            .Select(binding => new Dictionary<string, object?>
            {
                ["submesh_index"] = binding.SubmeshIndex,
                ["material"] = binding.Material,
                ["shader_family"] = string.IsNullOrWhiteSpace(binding.ShaderFamily) ? "generic" : binding.ShaderFamily,
                ["shader_technique"] = binding.ShaderTechnique,
                ["shader_authority"] = binding.ShaderAuthority,
                ["shader_family_source"] = binding.ShaderFamilySource,
                ["shader_family_reason"] = binding.ShaderFamilyReason,
                ["channel_color_spaces"] = binding.ChannelColorSpaces,
                ["channel_authorities"] = binding.ChannelAuthorities,
                ["channel_components"] = binding.ChannelComponents,
                ["normal_y_policy"] = binding.NormalYPolicy,
                ["alpha_mode"] = string.IsNullOrWhiteSpace(binding.AlphaMode) ? "opaque" : binding.AlphaMode,
                ["alpha_cutoff"] = binding.AlphaCutoff,
                ["opacity_factor"] = binding.OpacityFactor,
                ["alpha_authority"] = binding.AlphaAuthority,
                ["alpha_reason"] = binding.AlphaReason,
                ["double_sided"] = binding.DoubleSided,
                ["double_sided_authority"] = binding.DoubleSidedAuthority,
                ["double_sided_reason"] = binding.DoubleSidedReason,
                ["layer_binding_count"] = binding.LayerBindingCount,
                ["unsupported_features"] = binding.UnsupportedFeatures,
            })
            .ToArray();
    }

    public IEnumerable<NetMaterialTextureReference> TextureReferencesForSubmesh(int submeshIndex)
    {
        return TextureSemantics
            .Select(semantic => TextureReferenceForSubmesh(submeshIndex, semantic))
            .Where(reference => !reference.IsEmpty)
            .DistinctBy(reference => reference.CacheKey);
    }

    public IEnumerable<NetMaterialResource> TextureLoadResources()
    {
        var activeResourceIds = Submeshes
            .SelectMany(binding => binding.ResourceChannels.Values)
            .ToHashSet(StringComparer.Ordinal);
        return Resources.Values
            .Where(resource => activeResourceIds.Contains(resource.ResourceId))
            .OrderBy(resource => resource.ResourceId);
    }

    public IReadOnlyList<NetMaterialResource> FailedRequiredResources(IEnumerable<string> failedPaths)
    {
        var failed = failedPaths.ToHashSet(StringComparer.OrdinalIgnoreCase);
        return TextureLoadResources()
            .Where(resource => resource.Required && failed.Contains(resource.Path))
            .ToArray();
    }

    public IReadOnlyList<NetMaterialResource> FailedOptionalResources(IEnumerable<string> failedPaths)
    {
        var failed = failedPaths.ToHashSet(StringComparer.OrdinalIgnoreCase);
        return TextureLoadResources()
            .Where(resource => !resource.Required && failed.Contains(resource.Path))
            .ToArray();
    }

    public static NetMaterialStateUpdate ParseStateUpdate(JsonElement root)
    {
        var format = JsonText(root, "schema");
        if (string.IsNullOrWhiteSpace(format))
        {
            format = JsonText(root, "format");
        }
        var version = JsonLong(root, "version", 0);
        if (!string.IsNullOrWhiteSpace(format) && !string.Equals(format, "cdmw_mesh_material_state_v2", StringComparison.Ordinal))
        {
            throw new InvalidDataException($"Unsupported material state format: {format}");
        }
        if (version is not 0 and not 2)
        {
            throw new InvalidDataException($"Unsupported material state version: {version}");
        }

        var resources = ParseResources(root);
        var submeshes = ParseResidentSubmeshes(root);
        var affected = JsonIntArray(root, "affected_submeshes");
        if (!root.TryGetProperty("affected_submeshes", out var affectedValue) || affectedValue.ValueKind != JsonValueKind.Array)
        {
            affected = submeshes.Select(binding => binding.SubmeshIndex).Distinct().Order().ToArray();
        }
        return new NetMaterialStateUpdate(
            JsonText(root, "session_id"),
            JsonLong(root, "edit_revision", JsonLong(root, "revision", 0)),
            JsonLong(root, "generation", 0),
            JsonText(root, "material_signature"),
            affected,
            resources,
            submeshes);
    }

    private static IReadOnlyList<NetMaterialResource> ParseResources(JsonElement root)
    {
        if (!root.TryGetProperty("resources", out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<NetMaterialResource>();
        }
        var resources = new List<NetMaterialResource>();
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var resourceId = JsonText(item, "resource_id");
            var path = JsonText(item, "path");
            if (string.IsNullOrWhiteSpace(resourceId) || string.IsNullOrWhiteSpace(path))
            {
                throw new InvalidDataException("Material resources require resource_id and path.");
            }
            resources.Add(new NetMaterialResource(
                resourceId,
                path,
                JsonText(item, "fingerprint"),
                JsonText(item, "role"),
                (int)JsonLong(item, "submesh_index", -1),
                JsonText(item, "material_channel"),
                JsonText(item, "semantic"),
                JsonText(item, "color_space"),
                JsonText(item, "semantic_authority"),
                JsonText(item, "source_reference"),
                JsonText(item, "profile"),
                JsonBoolean(item, "required"),
                JsonText(item, "fallback_policy")));
        }
        return resources;
    }

    private static IReadOnlyList<NetSubmeshMaterialBinding> ParseResidentSubmeshes(JsonElement root)
    {
        JsonElement value = default;
        foreach (var name in new[] { "submeshes", "submesh_bindings", "bindings" })
        {
            if (root.TryGetProperty(name, out value) && value.ValueKind == JsonValueKind.Array)
            {
                break;
            }
        }
        if (value.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<NetSubmeshMaterialBinding>();
        }
        var result = new List<NetSubmeshMaterialBinding>();
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            var submeshIndex = (int)JsonLong(item, "submesh_index", -1);
            if (submeshIndex < 0)
            {
                throw new InvalidDataException("Material submesh binding requires a non-negative submesh_index.");
            }
            var channels = JsonMap(item, "channels");
            if (channels.Count == 0)
            {
                channels = JsonMap(item, "channel_resource_ids");
            }
            result.Add(new NetSubmeshMaterialBinding(
                submeshIndex,
                (int)JsonLong(item, "material_slot_index", submeshIndex),
                JsonText(item, "material"),
                JsonText(item, "texture"),
                new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase),
                new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase),
                channels,
                JsonMap(item, "channel_components"),
                JsonText(item, "normal_y_policy"),
                JsonBoolean(item, "texture_flip_vertical"),
                JsonText(item, "shader_family"),
                JsonText(item, "shader_technique"),
                JsonText(item, "shader_authority"),
                JsonText(item, "shader_family_source"),
                JsonText(item, "shader_family_reason"),
                JsonMap(item, "channel_color_spaces"),
                JsonMap(item, "channel_authorities"),
                JsonText(item, "alpha_mode"),
                JsonFloat(item, "alpha_cutoff", 0.5f),
                JsonFloat(item, "opacity_factor", 1.0f),
                JsonText(item, "alpha_authority"),
                JsonText(item, "alpha_reason"),
                JsonBoolean(item, "double_sided"),
                JsonText(item, "double_sided_authority"),
                JsonText(item, "double_sided_reason"),
                JsonStringArray(item, "unsupported_features"),
                JsonArrayLength(item, "layer_bindings")));
        }
        return result;
    }

    private static Dictionary<string, string> JsonMap(JsonElement root, string name)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (!root.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Object)
        {
            return result;
        }
        foreach (var property in value.EnumerateObject())
        {
            if (property.Value.ValueKind == JsonValueKind.String)
            {
                result[property.Name] = property.Value.GetString() ?? string.Empty;
            }
        }
        return result;
    }

    private static IReadOnlyList<int> JsonIntArray(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<int>();
        }
        return value.EnumerateArray()
            .Select(item => item.ValueKind == JsonValueKind.Number && item.TryGetInt32(out var number) ? number : -1)
            .Where(number => number >= 0)
            .Distinct()
            .Order()
            .ToArray();
    }

    private static string JsonText(JsonElement root, string name)
    {
        return root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? string.Empty
            : string.Empty;
    }

    private static long JsonLong(JsonElement root, string name, long fallback)
    {
        if (!root.TryGetProperty(name, out var value))
        {
            return fallback;
        }
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number))
        {
            return number;
        }
        return value.ValueKind == JsonValueKind.String && long.TryParse(value.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out number)
            ? number
            : fallback;
    }

    private static bool JsonBoolean(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var value))
        {
            return false;
        }
        return value.ValueKind == JsonValueKind.True
            || (value.ValueKind == JsonValueKind.String && bool.TryParse(value.GetString(), out var parsed) && parsed);
    }
}

internal sealed record NetMaterialStateSnapshot(
    IReadOnlyList<NetMaterialSlot> Slots,
    IReadOnlyList<NetSubmeshMaterialBinding> Submeshes,
    IReadOnlyDictionary<string, NetMaterialResource> Resources,
    string ManifestDirectory,
    string Signature,
    long Generation);

internal sealed record NetMaterialStateUpdate(
    string SessionId,
    long EditRevision,
    long Generation,
    string MaterialSignature,
    IReadOnlyList<int> AffectedSubmeshes,
    IReadOnlyList<NetMaterialResource> Resources,
    IReadOnlyList<NetSubmeshMaterialBinding> Submeshes)
{
    public IReadOnlySet<string> ResourceIdsForAffectedSubmeshes()
    {
        var affected = AffectedSubmeshes.ToHashSet();
        return Submeshes
            .Where(binding => affected.Contains(binding.SubmeshIndex))
            .SelectMany(binding => binding.ResourceChannels.Values)
            .ToHashSet(StringComparer.Ordinal);
    }
}

internal sealed record NetMaterialResource(
    string ResourceId,
    string Path,
    string Fingerprint,
    string Role,
    int SubmeshIndex,
    string MaterialChannel,
    string Semantic,
    string ColorSpace,
    string SemanticAuthority,
    string SourceReference,
    string Profile,
    bool Required,
    string FallbackPolicy)
{
    public NetMaterialTextureReference Reference => ReferenceForSemantic(Semantic, ColorSpace, SemanticAuthority);

    public NetMaterialTextureReference ReferenceForSemantic(
        string semantic,
        string? colorSpace = null,
        string? semanticAuthority = null)
    {
        var normalizedSemantic = string.IsNullOrWhiteSpace(semantic) ? MaterialChannel : semantic.Trim().ToLowerInvariant();
        var normalizedColorSpace = NormalizeColorSpace(
            colorSpace,
            normalizedSemantic,
            string.IsNullOrWhiteSpace(ColorSpace) ? null : ColorSpace);
        return new NetMaterialTextureReference(
            ResourceId,
            Path,
            Fingerprint,
            normalizedSemantic,
            normalizedColorSpace,
            SourceReference,
            string.IsNullOrWhiteSpace(semanticAuthority) ? SemanticAuthority : semanticAuthority);
    }

    private static string NormalizeColorSpace(string? value, string semantic, string? fallback)
    {
        var normalized = (value ?? fallback ?? string.Empty).Trim().ToLowerInvariant();
        if (normalized is "srgb" or "linear")
        {
            return normalized;
        }
        return semantic is "base" or "albedo" or "diffuse" or "emissive" ? "srgb" : "linear";
    }
}

internal readonly record struct NetMaterialTextureReference(
    string ResourceId,
    string Path,
    string Fingerprint,
    string Semantic,
    string ColorSpace,
    string SourceReference,
    string SemanticAuthority)
{
    public static NetMaterialTextureReference Empty { get; } = new(
        string.Empty, string.Empty, string.Empty, string.Empty, string.Empty, string.Empty, string.Empty);
    public bool IsEmpty => string.IsNullOrWhiteSpace(Path);
    public string SourceCacheKey => NetTextureSet.TextureCacheKey(Path, Fingerprint);
    public string CacheKey => string.IsNullOrWhiteSpace(SourceCacheKey)
        ? string.Empty
        : $"{SourceCacheKey}|view:{ColorSpace}";

    public static NetMaterialTextureReference FromPath(string path, string semantic = "")
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return Empty;
        }
        var normalized = semantic.Trim().ToLowerInvariant();
        var colorSpace = normalized is "base" or "albedo" or "diffuse" or "emissive" ? "srgb" : "linear";
        return new NetMaterialTextureReference(path, path, string.Empty, normalized, colorSpace, path, "legacy_fallback");
    }
}

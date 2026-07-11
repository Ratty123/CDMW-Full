using System.Globalization;
using System.IO;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class NetMaterialSet
{
    private static readonly string[] TextureSemantics =
    {
        "base", "albedo", "diffuse", "normal", "specular", "material",
        "roughness", "metallic", "height", "emissive"
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
                return resource.Reference;
            }
            if (binding.PackageChannels.TryGetValue(key, out var packaged) && !string.IsNullOrWhiteSpace(packaged))
            {
                var packagedPath = ResolveManifestPath(packaged);
                if (File.Exists(packagedPath))
                {
                    return NetMaterialTextureReference.FromPath(packagedPath);
                }
            }
            if (binding.ResolvedChannels.TryGetValue(key, out var resolved) && !string.IsNullOrWhiteSpace(resolved))
            {
                return NetMaterialTextureReference.FromPath(resolved);
            }
        }
        return NetMaterialTextureReference.Empty;
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
        return Submeshes
            .SelectMany(binding => TextureReferencesForSubmesh(binding.SubmeshIndex))
            .DistinctBy(reference => reference.CacheKey)
            .Select(reference => new NetMaterialResource(reference.ResourceId, reference.Path, reference.Fingerprint));
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
            resources.Add(new NetMaterialResource(resourceId, path, JsonText(item, "fingerprint")));
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
                channels));
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

internal sealed record NetMaterialResource(string ResourceId, string Path, string Fingerprint)
{
    public NetMaterialTextureReference Reference => new(ResourceId, Path, Fingerprint);
}

internal readonly record struct NetMaterialTextureReference(string ResourceId, string Path, string Fingerprint)
{
    public static NetMaterialTextureReference Empty { get; } = new(string.Empty, string.Empty, string.Empty);
    public bool IsEmpty => string.IsNullOrWhiteSpace(Path);
    public string CacheKey => NetTextureSet.TextureCacheKey(Path, Fingerprint);

    public static NetMaterialTextureReference FromPath(string path)
    {
        return string.IsNullOrWhiteSpace(path) ? Empty : new NetMaterialTextureReference(path, path, string.Empty);
    }
}

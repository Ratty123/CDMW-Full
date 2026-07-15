using System.IO;
using System.Text;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed partial class NetMaterialSet
{
    public static NetMaterialSet Empty => new(Array.Empty<NetMaterialSlot>(), Array.Empty<NetSubmeshMaterialBinding>(), string.Empty, string.Empty);

    private NetMaterialSet(IReadOnlyList<NetMaterialSlot> slots, IReadOnlyList<NetSubmeshMaterialBinding> submeshes, string manifestDirectory, string signature)
    {
        Slots = slots;
        Submeshes = submeshes;
        ManifestDirectory = manifestDirectory;
        Signature = signature;
    }

    public IReadOnlyList<NetMaterialSlot> Slots { get; private set; }
    public IReadOnlyList<NetSubmeshMaterialBinding> Submeshes { get; private set; }
    public string ManifestDirectory { get; private set; }
    public string Signature { get; private set; }
    public long Generation { get; private set; }
    private IReadOnlyDictionary<string, NetMaterialResource> Resources { get; set; }
        = new Dictionary<string, NetMaterialResource>(StringComparer.Ordinal);
    public int SlotCount => Slots.Count;
    public int TextureReferenceCount => Slots.Sum(slot => slot.Channels.Values.Count(value => !string.IsNullOrWhiteSpace(value)))
        + SubmeshTexturePaths().Count(value => !string.IsNullOrWhiteSpace(value));
    public int ResolvedTextureReferenceCount => SubmeshTexturePaths().Count(value => !string.IsNullOrWhiteSpace(value));
    public int ExistingTextureFileCount => SubmeshTexturePaths().Count(value => !string.IsNullOrWhiteSpace(value) && File.Exists(value));
    public int DecodableTextureFileCount => SubmeshTexturePaths().Count(IsDecodableImagePath);

    public IEnumerable<string> SubmeshTexturePaths()
    {
        foreach (var submesh in Submeshes)
        {
            foreach (var reference in TextureReferencesForSubmesh(submesh.SubmeshIndex))
            {
                yield return reference.Path;
            }
        }
    }

    public IEnumerable<string> TextureLoadPaths()
    {
        foreach (var resource in TextureLoadResources())
        {
            yield return resource.Path;
        }
    }

    private string ResolveManifestPath(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }
        return Path.IsPathRooted(value) || string.IsNullOrWhiteSpace(ManifestDirectory)
            ? value
            : Path.GetFullPath(Path.Combine(ManifestDirectory, value));
    }

    public string TexturePathForSubmesh(int submeshIndex, params string[] keys)
    {
        return TextureReferenceForSubmesh(submeshIndex, keys).Path;
    }

    public string BaseTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "base", "albedo", "diffuse");
    }

    public string EmissiveTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "emissive");
    }

    public string NormalTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "normal");
    }

    public string SpecularTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "specular");
    }

    public string RoughnessTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "roughness");
    }

    public string MetallicTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "metallic");
    }

    public string HeightTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "height");
    }

    public static NetMaterialSet Load(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            return Empty;
        }
        using var document = JsonDocument.Parse(File.ReadAllText(path, Encoding.UTF8));
        var root = document.RootElement;
        var manifestDirectory = Path.GetDirectoryName(path) ?? string.Empty;
        var result = new NetMaterialSet(
            ParseSlots(root, "material_slots"),
            ParseSubmeshes(root, "submeshes"),
            manifestDirectory,
            JsonString(root, "material_signature"));
        result.Resources = ParseResources(root)
            .Select(resource => Path.IsPathRooted(resource.Path) || string.IsNullOrWhiteSpace(manifestDirectory)
                ? resource
                : resource with { Path = Path.GetFullPath(Path.Combine(manifestDirectory, resource.Path)) })
            .ToDictionary(resource => resource.ResourceId, StringComparer.Ordinal);
        result.LoadInitialParameterStates(root);
        return result;
    }

    private static IReadOnlyList<NetMaterialSlot> ParseSlots(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var array) || array.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<NetMaterialSlot>();
        }
        var result = new List<NetMaterialSlot>();
        foreach (var item in array.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            result.Add(new NetMaterialSlot(
                JsonInt(item, "index", result.Count),
                JsonString(item, "name"),
                JsonString(item, "texture"),
                JsonStringMap(item, "channels")));
        }
        return result;
    }

    private static IReadOnlyList<NetSubmeshMaterialBinding> ParseSubmeshes(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var array) || array.ValueKind != JsonValueKind.Array)
        {
            return Array.Empty<NetSubmeshMaterialBinding>();
        }
        var result = new List<NetSubmeshMaterialBinding>();
        foreach (var item in array.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }
            result.Add(new NetSubmeshMaterialBinding(
                JsonInt(item, "submesh_index", result.Count),
                JsonInt(item, "material_slot_index", result.Count),
                JsonString(item, "material"),
                JsonString(item, "texture"),
                JsonStringMap(item, "resolved_channels"),
                JsonStringMap(item, "packaged_channels"),
                JsonStringMap(item, "resource_channels"),
                JsonStringMap(item, "channel_components"),
                JsonString(item, "normal_y_policy"),
                JsonBoolean(item, "texture_flip_vertical"),
                JsonString(item, "shader_family"),
                JsonString(item, "shader_technique"),
                JsonString(item, "shader_authority"),
                JsonString(item, "shader_family_source"),
                JsonString(item, "shader_family_reason"),
                JsonString(item, "material_category"),
                JsonFloat(item, "material_category_confidence", 0.35f),
                JsonString(item, "material_category_reason"),
                JsonBoolean(item, "material_response_promoted"),
                JsonStringMap(item, "channel_color_spaces"),
                JsonStringMap(item, "channel_authorities"),
                JsonString(item, "alpha_mode"),
                JsonFloat(item, "alpha_cutoff", 0.5f),
                JsonFloat(item, "opacity_factor", 1.0f),
                JsonString(item, "alpha_authority"),
                JsonString(item, "alpha_reason"),
                JsonBoolean(item, "double_sided"),
                JsonString(item, "double_sided_authority"),
                JsonString(item, "double_sided_reason"),
                JsonStringArray(item, "unsupported_features"),
                JsonArrayLength(item, "layer_bindings")));
        }
        return result;
    }

    private static Dictionary<string, string> JsonStringMap(JsonElement element, string name)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Object)
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

    private static bool IsDecodableImagePath(string value)
    {
        if (string.IsNullOrWhiteSpace(value) || !File.Exists(value))
        {
            return false;
        }
        var extension = Path.GetExtension(value).ToLowerInvariant();
        return extension is ".png" or ".jpg" or ".jpeg" or ".bmp" or ".gif" or ".tif" or ".tiff";
    }

    private static string JsonString(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? string.Empty
            : string.Empty;
    }

    private static int JsonInt(JsonElement element, string name, int fallback)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var number)
            ? number
            : fallback;
    }

    private static float JsonFloat(JsonElement element, string name, float fallback)
    {
        return element.TryGetProperty(name, out var value)
            && value.ValueKind == JsonValueKind.Number
            && value.TryGetDouble(out var number)
            && double.IsFinite(number)
                ? (float)number
                : fallback;
    }

    private static IReadOnlyList<string> JsonStringArray(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Array
            ? value.EnumerateArray()
                .Where(item => item.ValueKind == JsonValueKind.String)
                .Select(item => item.GetString() ?? string.Empty)
                .Where(item => !string.IsNullOrWhiteSpace(item))
                .ToArray()
            : Array.Empty<string>();
    }

    private static int JsonArrayLength(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Array
            ? value.GetArrayLength()
            : 0;
    }
}

internal sealed record NetMaterialSlot(int Index, string Name, string Texture, Dictionary<string, string> Channels);

internal sealed record NetSubmeshMaterialBinding(
    int SubmeshIndex,
    int MaterialSlotIndex,
    string Material,
    string Texture,
    Dictionary<string, string> ResolvedChannels,
    Dictionary<string, string> PackageChannels,
    Dictionary<string, string> ResourceChannels,
    Dictionary<string, string> ChannelComponents,
    string NormalYPolicy,
    bool TextureFlipVertical,
    string ShaderFamily,
    string ShaderTechnique,
    string ShaderAuthority,
    string ShaderFamilySource,
    string ShaderFamilyReason,
    string MaterialCategory,
    float MaterialCategoryConfidence,
    string MaterialCategoryReason,
    bool MaterialResponsePromoted,
    Dictionary<string, string> ChannelColorSpaces,
    Dictionary<string, string> ChannelAuthorities,
    string AlphaMode,
    float AlphaCutoff,
    float OpacityFactor,
    string AlphaAuthority,
    string AlphaReason,
    bool DoubleSided,
    string DoubleSidedAuthority,
    string DoubleSidedReason,
    IReadOnlyList<string> UnsupportedFeatures,
    int LayerBindingCount);

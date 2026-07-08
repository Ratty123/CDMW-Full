using System.IO;
using System.Text;
using System.Text.Json;

namespace Cdmw.MeshEditorExperiment;

internal sealed class NetMaterialSet
{
    public static NetMaterialSet Empty { get; } = new(Array.Empty<NetMaterialSlot>(), Array.Empty<NetSubmeshMaterialBinding>(), string.Empty);

    private NetMaterialSet(IReadOnlyList<NetMaterialSlot> slots, IReadOnlyList<NetSubmeshMaterialBinding> submeshes, string manifestDirectory)
    {
        Slots = slots;
        Submeshes = submeshes;
        ManifestDirectory = manifestDirectory;
    }

    public IReadOnlyList<NetMaterialSlot> Slots { get; }
    public IReadOnlyList<NetSubmeshMaterialBinding> Submeshes { get; }
    public string ManifestDirectory { get; }
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
            foreach (var value in submesh.PackageChannels.Values)
            {
                yield return ResolveManifestPath(value);
            }
            foreach (var value in submesh.ResolvedChannels.Values)
            {
                yield return value;
            }
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
        var binding = Submeshes.FirstOrDefault(item => item.SubmeshIndex == submeshIndex);
        if (binding is null)
        {
            return string.Empty;
        }
        foreach (var key in keys)
        {
            if (binding.PackageChannels.TryGetValue(key, out var packaged) && !string.IsNullOrWhiteSpace(packaged))
            {
                return ResolveManifestPath(packaged);
            }
            if (binding.ResolvedChannels.TryGetValue(key, out var value) && !string.IsNullOrWhiteSpace(value))
            {
                return value;
            }
        }
        return string.Empty;
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
        return TexturePathForSubmesh(submeshIndex, "specular", "material");
    }

    public string RoughnessTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "roughness", "material");
    }

    public string MetallicTexturePathForSubmesh(int submeshIndex)
    {
        return TexturePathForSubmesh(submeshIndex, "metallic", "material");
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
        return new NetMaterialSet(
            ParseSlots(root, "material_slots"),
            ParseSubmeshes(root, "submeshes"),
            Path.GetDirectoryName(path) ?? string.Empty);
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
                JsonStringMap(item, "packaged_channels")));
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
}

internal sealed record NetMaterialSlot(int Index, string Name, string Texture, Dictionary<string, string> Channels);

internal sealed record NetSubmeshMaterialBinding(
    int SubmeshIndex,
    int MaterialSlotIndex,
    string Material,
    string Texture,
    Dictionary<string, string> ResolvedChannels,
    Dictionary<string, string> PackageChannels);

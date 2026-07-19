using System.Reflection;
using System.Text.Json;

namespace Cdmw.Archive.Content;

public static class ArchiveContentRegistry
{
    private const string ResourceName = "Cdmw.Archive.Content.archive_content_capabilities.v1.json";
    private static readonly Lazy<ArchiveContentManifest> ManifestOwner = new(LoadManifest, true);
    private static readonly Lazy<IReadOnlyDictionary<string, ArchiveContentCapability>> CapabilitiesOwner =
        new(BuildCapabilities, true);

    public static ArchiveContentManifest Manifest => ManifestOwner.Value;

    public static IReadOnlyCollection<ArchiveContentCapability> All =>
        CapabilitiesOwner.Value.Values.ToArray();

    public static ArchiveContentCapability? Find(string? extension)
    {
        var normalized = NormalizeExtension(extension);
        return CapabilitiesOwner.Value.TryGetValue(normalized, out var capability) ? capability : null;
    }

    public static ArchiveContentCapability Describe(string? extension) =>
        Find(extension) ?? new ArchiveContentCapability(
            NormalizeExtension(extension),
            "other",
            "other",
            "binary",
            "generic_binary",
            "raw_only",
            Readable: true,
            Structured: false,
            References: true,
            Visual: false,
            Playback: false,
            Exports: ["raw"],
            UnsupportedReason: "No format-specific decoder is registered; bounded binary analysis is available.");

    public static string NormalizeExtension(string? extension)
    {
        var value = (extension ?? string.Empty).Trim().ToLowerInvariant();
        if (value.Length == 0) return string.Empty;
        return value[0] == '.' ? value : "." + value;
    }

    private static IReadOnlyDictionary<string, ArchiveContentCapability> BuildCapabilities()
    {
        var result = new Dictionary<string, ArchiveContentCapability>(StringComparer.OrdinalIgnoreCase);
        foreach (var capability in Manifest.Extensions)
        {
            var extension = NormalizeExtension(capability.Extension);
            if (extension.Length < 2)
            {
                throw new InvalidDataException("Archive content capability has an empty extension.");
            }
            if (!result.TryAdd(extension, capability with { Extension = extension }))
            {
                throw new InvalidDataException($"Duplicate archive content capability: {extension}");
            }
        }
        return result;
    }

    private static ArchiveContentManifest LoadManifest()
    {
        var assembly = Assembly.GetExecutingAssembly();
        using var stream = assembly.GetManifestResourceStream(ResourceName)
            ?? throw new InvalidOperationException($"Embedded capability manifest is missing: {ResourceName}");
        var manifest = JsonSerializer.Deserialize<ArchiveContentManifest>(stream, ArchiveContentJson.Options)
            ?? throw new InvalidDataException("Archive content capability manifest is empty.");
        if (manifest.SchemaVersion != 1 || manifest.Extensions.Count == 0)
        {
            throw new InvalidDataException("Unsupported or empty archive content capability manifest.");
        }
        return manifest;
    }
}

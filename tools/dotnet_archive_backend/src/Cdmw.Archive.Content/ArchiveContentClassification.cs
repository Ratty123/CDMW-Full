namespace Cdmw.Archive.Content;

public static class ArchiveContentClassification
{
    private static readonly string[] ColorTextureSuffixes =
    [
        "_d",
        "_diffuse",
        "_albedo",
        "_basecolor",
        "_base_color",
        "_color",
    ];

    private static readonly string[] NormalTextureSuffixes =
    [
        "_n",
        "_normal",
        "_nrm",
    ];

    private static readonly string[] MaterialTextureSuffixes =
    [
        "_m",
        "_ma",
        "_mg",
        "_mask",
        "_orm",
        "_mra",
        "_ao",
        "_rough",
        "_roughness",
        "_metal",
        "_metallic",
        "_spec",
        "_specular",
    ];

    public static string ClassifyRole(string path, string extension)
    {
        var normalizedPath = (path ?? string.Empty).Replace('\\', '/').ToLowerInvariant();
        var normalizedExtension = ArchiveContentRegistry.NormalizeExtension(extension);
        if (normalizedExtension is ".hkx" or ".hkt")
        {
            return normalizedPath.Contains("physics", StringComparison.Ordinal) ||
                   normalizedPath.Contains("ragdoll", StringComparison.Ordinal)
                ? "physics"
                : "animation";
        }

        var capability = ArchiveContentRegistry.Find(normalizedExtension);
        if (capability?.Container == "text") return "text";
        if (capability is not null && capability.Role is not "image" and not "other")
        {
            return capability.Role;
        }
        if (normalizedPath.Contains("/ui/", StringComparison.Ordinal) ||
            Path.GetFileName(normalizedPath).StartsWith("ui_", StringComparison.Ordinal))
        {
            return "user_interface";
        }
        if (normalizedPath.Contains("impostor", StringComparison.Ordinal)) return "impostor";
        if (capability?.Role == "image" || normalizedPath.Contains("/texture/", StringComparison.Ordinal))
        {
            return ClassifyTextureUsage(normalizedPath) switch
            {
                ArchiveTextureUsageKind.NormalMap => "normal",
                ArchiveTextureUsageKind.MaterialMap => "material",
                _ => "image",
            };
        }
        return capability?.Role ?? "other";
    }

    public static ArchiveTextureUsageKind ClassifyTextureUsage(string path)
    {
        var filename = Path.GetFileNameWithoutExtension((path ?? string.Empty).Replace('\\', '/')).ToLowerInvariant();
        if (HasTerminalSuffix(filename, ColorTextureSuffixes))
        {
            return ArchiveTextureUsageKind.Color;
        }
        if (HasTerminalSuffix(filename, NormalTextureSuffixes))
        {
            return ArchiveTextureUsageKind.NormalMap;
        }
        if (HasTerminalSuffix(filename, MaterialTextureSuffixes))
        {
            return ArchiveTextureUsageKind.MaterialMap;
        }
        return ArchiveTextureUsageKind.Unknown;
    }

    public static string ClassifyGroup(string extension) =>
        ArchiveContentRegistry.Find(extension)?.Group ?? "other";

    public static bool IsPreviewable(string extension) =>
        ArchiveContentRegistry.Find(extension) is { } capability &&
        (capability.Readable || capability.Visual || capability.Playback);

    private static bool HasTerminalSuffix(string filename, IReadOnlyList<string> suffixes) =>
        suffixes.Any(suffix => filename.EndsWith(suffix, StringComparison.Ordinal));
}

public enum ArchiveTextureUsageKind
{
    Unknown,
    Color,
    NormalMap,
    MaterialMap,
}

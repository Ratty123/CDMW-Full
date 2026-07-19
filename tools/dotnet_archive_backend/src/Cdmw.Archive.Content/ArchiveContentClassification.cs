namespace Cdmw.Archive.Content;

public static class ArchiveContentClassification
{
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
            var filename = Path.GetFileNameWithoutExtension(normalizedPath);
            if (filename.EndsWith("_n", StringComparison.Ordinal) ||
                filename.EndsWith("_normal", StringComparison.Ordinal)) return "normal";
            if (filename.EndsWith("_m", StringComparison.Ordinal) ||
                filename.Contains("rough", StringComparison.Ordinal) ||
                filename.Contains("mask", StringComparison.Ordinal) ||
                filename.Contains("metal", StringComparison.Ordinal)) return "material";
            return "image";
        }
        return capability?.Role ?? "other";
    }

    public static string ClassifyGroup(string extension) =>
        ArchiveContentRegistry.Find(extension)?.Group ?? "other";

    public static bool IsPreviewable(string extension) =>
        ArchiveContentRegistry.Find(extension) is { } capability &&
        (capability.Readable || capability.Visual || capability.Playback);
}

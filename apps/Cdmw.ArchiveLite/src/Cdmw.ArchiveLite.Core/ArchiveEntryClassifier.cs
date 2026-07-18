using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public static class ArchiveEntryClassifier
{
    private static readonly HashSet<string> ModelExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".3ds", ".dae", ".fbx", ".glb", ".gltf", ".mesh", ".mdl", ".model",
        ".obj", ".pac", ".pab", ".pam", ".pamlod", ".pat", ".patx",
    };
    private static readonly HashSet<string> AnimationExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".paa", ".paa_metabin", ".pae", ".paem", ".motionblending", ".papr",
        ".paseq", ".paseqc", ".paschedule", ".paschedulepath", ".pastage",
    };
    private static readonly HashSet<string> MetadataExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".meshinfo", ".prefab", ".pamhc", ".pappt", ".paccd", ".pabgb", ".pabgh",
        ".pabc", ".pabv", ".levelinfo", ".palevel", ".roadsector", ".road", ".nav",
        ".seqmt", ".uianiminit", ".pathc",
    };
    private static readonly HashSet<string> ImageExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".bmp", ".dds", ".gif", ".hdr", ".jpeg", ".jpg", ".png", ".tga",
        ".tif", ".tiff", ".webp",
    };
    private static readonly HashSet<string> AudioExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".mp3", ".ogg", ".wem", ".wav", ".bnk",
    };
    private static readonly HashSet<string> VideoExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".bk2", ".mp4",
    };
    private static readonly HashSet<string> TextExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".cfg", ".css", ".csv", ".dae", ".html", ".gltf", ".h", ".hpp", ".ini",
        ".json", ".log", ".lua", ".material", ".mtl", ".obj", ".paloc", ".app_xml",
        ".prefab_xml", ".shader", ".txt", ".xml", ".yaml", ".yml",
    };

    public static ArchiveEntryRole Classify(string path, string extension)
    {
        var normalized = path.Replace('\\', '/').ToLowerInvariant();
        if (extension is ".hkx" or ".hkt")
        {
            return normalized.Contains("physics", StringComparison.Ordinal) || normalized.Contains("ragdoll", StringComparison.Ordinal)
                ? ArchiveEntryRole.Physics
                : ArchiveEntryRole.Animation;
        }
        if (ModelExtensions.Contains(extension)) return ArchiveEntryRole.Model;
        if (AnimationExtensions.Contains(extension)) return ArchiveEntryRole.Animation;
        if (MetadataExtensions.Contains(extension)) return ArchiveEntryRole.Metadata;
        if (VideoExtensions.Contains(extension)) return ArchiveEntryRole.Video;
        if (AudioExtensions.Contains(extension)) return ArchiveEntryRole.Audio;
        if (TextExtensions.Contains(extension)) return ArchiveEntryRole.Text;
        if (normalized.Contains("/ui/", StringComparison.Ordinal) || System.IO.Path.GetFileName(normalized).StartsWith("ui_", StringComparison.Ordinal)) return ArchiveEntryRole.UserInterface;
        if (normalized.Contains("impostor", StringComparison.Ordinal)) return ArchiveEntryRole.Impostor;
        if (ImageExtensions.Contains(extension) || normalized.Contains("/texture/", StringComparison.Ordinal))
        {
            var filename = System.IO.Path.GetFileNameWithoutExtension(normalized);
            if (filename.EndsWith("_n", StringComparison.Ordinal) || filename.EndsWith("_normal", StringComparison.Ordinal)) return ArchiveEntryRole.Normal;
            if (filename.EndsWith("_m", StringComparison.Ordinal) || filename.Contains("rough", StringComparison.Ordinal) || filename.Contains("mask", StringComparison.Ordinal) || filename.Contains("metal", StringComparison.Ordinal)) return ArchiveEntryRole.Material;
            return ArchiveEntryRole.Image;
        }
        return ArchiveEntryRole.Other;
    }

    public static bool IsPreviewable(string extension, ArchiveEntryRole role) =>
        role != ArchiveEntryRole.Other || extension is ".meshinfo" or ".pab" or ".pathc";

    public static string PackageLabel(string pamtPath)
    {
        var file = System.IO.Path.GetFileName(pamtPath);
        var parent = System.IO.Path.GetFileName(System.IO.Path.GetDirectoryName(pamtPath));
        return string.IsNullOrEmpty(parent) ? file : $"{parent}/{file}";
    }
}

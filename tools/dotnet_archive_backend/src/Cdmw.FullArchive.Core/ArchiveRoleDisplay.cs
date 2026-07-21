using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

internal static class ArchiveRoleDisplay
{
    private static readonly HashSet<string> ImageExtensions = new(StringComparer.Ordinal)
    {
        ".bmp", ".dds", ".gif", ".jpeg", ".jpg", ".png", ".tga", ".tif", ".tiff", ".webp",
    };

    private static readonly HashSet<string> AudioExtensions = new(StringComparer.Ordinal)
    {
        ".akb", ".bnk", ".flac", ".mp3", ".ogg", ".opus", ".wav", ".wem",
    };

    private static readonly HashSet<string> VideoExtensions = new(StringComparer.Ordinal)
    {
        ".avi", ".bk2", ".bik", ".mp4", ".usm", ".webm", ".wmv",
    };

    private static readonly HashSet<string> TextExtensions = new(StringComparer.Ordinal)
    {
        ".bnk", ".cfg", ".css", ".csv", ".dae", ".html", ".gltf", ".h", ".hpp", ".ini", ".json",
        ".log", ".lua", ".material", ".mtl", ".obj", ".paloc", ".app_xml", ".pami", ".pac_xml",
        ".pam_xml", ".pamlod_xml", ".prefabdata_xml", ".shader", ".thtml", ".txt", ".xml", ".yaml", ".yml",
    };

    private static readonly HashSet<string> AnimationExtensions = new(StringComparer.Ordinal)
    {
        ".paa", ".motionblending", ".pae", ".paem", ".papr", ".paseq", ".paseqc", ".paschedule",
        ".paschedulepath", ".pastage",
    };

    private static readonly HashSet<string> ModelExtensions = new(StringComparer.Ordinal)
    {
        ".pac", ".pam", ".pamlod", ".obj", ".fbx", ".dae", ".gltf", ".glb", ".mesh", ".mdl", ".model",
        ".pat", ".patx",
    };

    public static string For(ArchiveEntryDto entry)
    {
        var extension = entry.Extension.ToLowerInvariant();
        var path = entry.Path.Replace('\\', '/').ToLowerInvariant();
        var basename = path[(path.LastIndexOf('/') + 1)..];
        string role;
        if (ImageExtensions.Contains(extension))
        {
            role = "Texture";
        }
        else if (extension is ".pami" or ".pac_xml" or ".pam_xml" or ".pamlod_xml" ||
                 extension == ".xml" &&
                 (basename.EndsWith(".pac.xml", StringComparison.Ordinal) ||
                  basename.EndsWith(".pam.xml", StringComparison.Ordinal) ||
                  basename.EndsWith(".pamlod.xml", StringComparison.Ordinal)))
        {
            role = "Material";
        }
        else if (extension is ".hkx" or ".hkt")
        {
            role = path.Contains("meshphysics", StringComparison.Ordinal) ||
                path.Contains("havokphysics", StringComparison.Ordinal) ||
                path.Contains("ragdoll", StringComparison.Ordinal) ||
                path.Contains("physics", StringComparison.Ordinal) ? "Physics" : "HKX";
        }
        else if (extension == ".paa_metabin")
        {
            role = "Animation Metadata";
        }
        else if (AnimationExtensions.Contains(extension))
        {
            role = "Animation";
        }
        else if (extension == ".pab")
        {
            role = "Skeleton / Rig";
        }
        else if (extension is ".prefab" or ".prefabdata_xml" or ".prefabdata.xml" or ".pappt")
        {
            role = "Prefab";
        }
        else if (extension == ".pamhc")
        {
            role = "Model Property Metadata";
        }
        else if (extension == ".paccd")
        {
            role = "Character Customization";
        }
        else if (extension == ".seqmt")
        {
            role = "Sequence Texture Metadata";
        }
        else if (AudioExtensions.Contains(extension))
        {
            role = "Audio";
        }
        else if (VideoExtensions.Contains(extension))
        {
            role = "Video";
        }
        else if (TextExtensions.Contains(extension) ||
                 extension is ".meshinfo" or ".motionblending" or ".paa_metabin" or ".prefab" or ".pappt" or ".pamhc" or ".paccd" or ".seqmt")
        {
            role = IsUiPath(path) ? "UI" : "Metadata";
        }
        else if (ModelExtensions.Contains(extension))
        {
            role = "Mesh";
        }
        else
        {
            role = IsUiPath(path) ? "UI" : "Unknown";
        }
        return $"{role} {extension}".Trim();
    }

    private static bool IsUiPath(string normalizedPath) =>
        normalizedPath.Contains("/ui", StringComparison.Ordinal) || normalizedPath.StartsWith("ui/", StringComparison.Ordinal);
}

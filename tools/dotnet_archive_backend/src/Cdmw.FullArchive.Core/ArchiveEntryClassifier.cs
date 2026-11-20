using Cdmw.Archive.Content;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public static class ArchiveEntryClassifier
{
    public static ArchiveEntryRole Classify(string path, string extension) =>
        ArchiveContentClassification.ClassifyRole(path, extension) switch
        {
            "model" => ArchiveEntryRole.Model,
            "animation" => ArchiveEntryRole.Animation,
            "physics" => ArchiveEntryRole.Physics,
            "metadata" => ArchiveEntryRole.Metadata,
            "video" => ArchiveEntryRole.Video,
            "audio" => ArchiveEntryRole.Audio,
            "user_interface" => ArchiveEntryRole.UserInterface,
            "impostor" => ArchiveEntryRole.Impostor,
            "normal" => ArchiveEntryRole.Normal,
            "material" => ArchiveEntryRole.Material,
            "image" => ArchiveEntryRole.Image,
            "text" => ArchiveEntryRole.Text,
            _ => ArchiveEntryRole.Other,
        };

    public static bool IsPreviewable(string extension, ArchiveEntryRole role) =>
        role != ArchiveEntryRole.Other || ArchiveContentClassification.IsPreviewable(extension);

    public static ArchiveExtensionCategory ClassifyExtensionCategory(string extension)
    {
        return ArchiveContentClassification.ClassifyGroup(extension) switch
        {
            "model_mesh_physics" => ArchiveExtensionCategory.ModelMeshPhysics,
            "texture_image" => ArchiveExtensionCategory.TextureImage,
            "material_metadata" => ArchiveExtensionCategory.MaterialMetadata,
            "animation_scene" => ArchiveExtensionCategory.AnimationScene,
            "audio_video" => ArchiveExtensionCategory.AudioVideo,
            "user_interface_text" => ArchiveExtensionCategory.UserInterfaceText,
            _ => ArchiveExtensionCategory.Other,
        };
    }

    public static string PackageLabel(string pamtPath)
    {
        var file = System.IO.Path.GetFileName(pamtPath.Replace('\\', '/'));
        var folder = PackageFolder(pamtPath, fallback: string.Empty);
        return string.IsNullOrEmpty(folder) ? file : $"{folder}/{file}";
    }

    /// <summary>
    /// The package folder of a .pamt path. A DLC package keeps its dlc/&lt;name&gt;/ folders in
    /// front, because the base game and a DLC both have a folder named, for example, 0015.
    /// </summary>
    public static string PackageFolder(string pamtPath, string fallback = "package")
    {
        var parts = pamtPath.Replace('\\', '/').Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length < 2)
        {
            return fallback;
        }
        var folders = parts[..^1];
        if (folders.Length >= 3 && folders[^3].Equals("dlc", StringComparison.OrdinalIgnoreCase))
        {
            return string.Join('/', folders[^3..]);
        }
        var last = folders[^1].Trim();
        return last.Length == 0 ? fallback : last;
    }
}

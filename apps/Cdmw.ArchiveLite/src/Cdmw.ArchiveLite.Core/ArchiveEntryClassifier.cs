using Cdmw.Archive.Content;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

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
        var file = System.IO.Path.GetFileName(pamtPath);
        var parent = System.IO.Path.GetFileName(System.IO.Path.GetDirectoryName(pamtPath));
        return string.IsNullOrEmpty(parent) ? file : $"{parent}/{file}";
    }
}

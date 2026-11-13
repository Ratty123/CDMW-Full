namespace Cdmw.FullArchive.Core;

// CDMW never writes into a game installation: it only creates mods. These are
// the checks the worker makes before it moves, replaces or writes a folder that
// a request or a cache file named.
internal static class GameFolderPolicy
{
    // A game installation's root: CrimsonDesert.exe (at the root or in bin64)
    // or the package group table meta\0.papgt.
    public static bool IsGameRoot(string folder) =>
        File.Exists(Path.Combine(folder, "CrimsonDesert.exe"))
        || File.Exists(Path.Combine(folder, "bin64", "CrimsonDesert.exe"))
        || File.Exists(Path.Combine(folder, "meta", "0.papgt"));

    // The folder, or one above it, is a game installation's root.
    public static bool IsInsideGameInstallation(string path)
    {
        for (var folder = new DirectoryInfo(Path.GetFullPath(path)); folder is not null; folder = folder.Parent)
        {
            if (IsGameRoot(folder.FullName))
            {
                return true;
            }
        }
        return false;
    }

    // Game archives (.pamt, .paz, .papgt) directly in the folder.
    public static bool HoldsArchiveFiles(string folder) =>
        Directory.Exists(folder)
        && (Directory.EnumerateFiles(folder, "*.pamt").Any()
            || Directory.EnumerateFiles(folder, "*.paz").Any()
            || Directory.EnumerateFiles(folder, "*.papgt").Any());

    // A folder that holds game archives, lies inside a game installation, or
    // could not be checked. Never moved or deleted, whatever led to it.
    public static bool IsProtected(string path)
    {
        try
        {
            return HoldsArchiveFiles(path) || IsInsideGameInstallation(path);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return true;
        }
    }

    // A cache folder the worker is about to write into must not be a link: a
    // planted junction would carry the write out of the cache.
    public static void RejectLinks(params string[] folders)
    {
        foreach (var folder in folders)
        {
            var info = new DirectoryInfo(folder);
            if (info.Exists && (info.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new InvalidDataException($"Archive cache folder is a link: {folder}");
            }
        }
    }

    public static bool Overlaps(string left, string right) =>
        ExportPathPolicy.IsWithinOrEqual(left, right) || ExportPathPolicy.IsWithinOrEqual(right, left);
}

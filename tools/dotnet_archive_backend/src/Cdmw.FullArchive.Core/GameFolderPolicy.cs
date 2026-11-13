using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace Cdmw.FullArchive.Core;

// CDMW never writes into a game installation: it only creates mods. These are
// the checks the worker makes before it moves, replaces or writes a folder that
// a request or a cache file named.
internal static class GameFolderPolicy
{
    // A game installation's root, the same marks as cdmw.core.protected_roots
    // (INSTALLATION_MARKS): the package group table meta\0.papgt together with
    // one of bin64\CrimsonDesert.exe, CrimsonDesert.exe or the shipped group
    // 0000\0.pamt. meta\0.papgt alone is not enough: the archive-style mods CDMW
    // writes for DMM hold their own. Keep this description and the Python one
    // the same.
    public static bool IsGameRoot(string folder) =>
        File.Exists(Path.Combine(folder, "meta", "0.papgt"))
        && (File.Exists(Path.Combine(folder, "bin64", "CrimsonDesert.exe"))
            || File.Exists(Path.Combine(folder, "CrimsonDesert.exe"))
            || File.Exists(Path.Combine(folder, "0000", "0.pamt")));

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

    // A link (junction or symbolic link) on any existing folder of the path,
    // the path itself included, below its volume root.
    public static bool HasLinkOnPath(string path)
    {
        for (var entry = new DirectoryInfo(Path.GetFullPath(path)); entry?.Parent is not null; entry = entry.Parent)
        {
            if (entry.Exists && (entry.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                return true;
            }
        }
        return false;
    }

    // Where the path really leads: its nearest existing folder resolved through
    // every link to its final path (GetFinalPathNameByHandle), then the parts
    // that do not exist yet. String checks on the path as written are blind to
    // a junction on the way.
    public static string FinalPath(string path)
    {
        var full = Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
        var existing = full;
        var missing = new Stack<string>();
        while (!Directory.Exists(existing) && !File.Exists(existing))
        {
            var parent = Path.GetDirectoryName(existing);
            if (parent is null)
            {
                return full;
            }
            missing.Push(Path.GetFileName(existing));
            existing = parent;
        }
        var resolved = FinalPathOfExisting(existing);
        while (missing.Count > 0)
        {
            resolved = Path.Combine(resolved, missing.Pop());
        }
        return resolved;
    }

    public static bool Overlaps(string left, string right) =>
        ExportPathPolicy.IsWithinOrEqual(left, right) || ExportPathPolicy.IsWithinOrEqual(right, left);

    private static string FinalPathOfExisting(string path)
    {
        using var handle = CreateFileW(path, 0, FileShare.ReadWrite | FileShare.Delete, IntPtr.Zero, FileMode.Open,
            BackupSemantics, IntPtr.Zero);
        if (handle.IsInvalid)
        {
            throw new IOException($"The path could not be resolved: {path}", Marshal.GetHRForLastWin32Error());
        }
        var buffer = new char[1024];
        while (true)
        {
            var length = GetFinalPathNameByHandleW(handle, buffer, (uint)buffer.Length, 0);
            if (length == 0)
            {
                throw new IOException($"The path could not be resolved: {path}", Marshal.GetHRForLastWin32Error());
            }
            if (length < buffer.Length)
            {
                var text = new string(buffer, 0, (int)length);
                if (text.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase)) return @"\\" + text[8..];
                if (text.StartsWith(@"\\?\", StringComparison.Ordinal)) return text[4..];
                return text;
            }
            buffer = new char[length + 1];
        }
    }

    private const uint BackupSemantics = 0x02000000;  // FILE_FLAG_BACKUP_SEMANTICS: opens a folder

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(string fileName, uint desiredAccess, FileShare shareMode,
        IntPtr securityAttributes, FileMode creationDisposition, uint flagsAndAttributes, IntPtr templateFile);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandleW(SafeFileHandle file, [Out] char[] path, uint length, uint flags);
}

// An export destination refused because it is, holds or leads into the game, the
// archive cache or a link. The worker reports it as export_destination_protected
// (WorkerServer.ClassifyFailure), with a message that says what to choose instead.
public sealed class ExportDestinationRefusedException(string message) : InvalidDataException(message);

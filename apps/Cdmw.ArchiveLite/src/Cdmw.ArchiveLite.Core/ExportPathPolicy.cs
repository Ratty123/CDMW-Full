namespace Cdmw.ArchiveLite.Core;

public static class ExportPathPolicy
{
    private static readonly HashSet<string> ReservedWindowsNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
        "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³",
    };

    public static string NormalizeVirtualPath(string virtualPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(virtualPath);
        if (virtualPath.IndexOf('\0') >= 0)
        {
            throw new InvalidDataException("Archive path contains a NUL character.");
        }

        var normalized = virtualPath.Replace('\\', '/').Trim();
        if (normalized.StartsWith('/') || normalized.StartsWith("//", StringComparison.Ordinal) || Path.IsPathRooted(normalized))
        {
            throw new InvalidDataException("Archive path must be relative.");
        }

        var parts = normalized.Split('/', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length == 0 || parts.Any(static part => part is "." or ".."))
        {
            throw new InvalidDataException("Archive path contains an unsafe segment.");
        }

        foreach (var part in parts)
        {
            if (part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || part.EndsWith(' ') || part.EndsWith('.'))
            {
                throw new InvalidDataException($"Archive path segment '{part}' is not a safe Windows filename.");
            }
            var deviceStem = part.Split('.', 2)[0];
            if (ReservedWindowsNames.Contains(deviceStem))
            {
                throw new InvalidDataException($"Archive path segment '{part}' is a reserved Windows device name.");
            }
        }

        return string.Join('/', parts);
    }

    public static string ResolveContainedPath(string outputRoot, string virtualPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(outputRoot);
        var root = Path.GetFullPath(outputRoot);
        var normalized = NormalizeVirtualPath(virtualPath);
        var target = Path.GetFullPath(Path.Combine(root, normalized.Replace('/', Path.DirectorySeparatorChar)));
        var rootWithSeparator = root.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!target.StartsWith(rootWithSeparator, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Resolved archive path escapes the selected output root.");
        }

        return target;
    }

    public static bool IsWithinOrEqual(string rootPath, string candidatePath)
    {
        var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(rootPath));
        var candidate = Path.TrimEndingDirectorySeparator(Path.GetFullPath(candidatePath));
        if (candidate.Equals(root, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }
        var prefix = Path.EndsInDirectorySeparator(root) ? root : root + Path.DirectorySeparatorChar;
        return candidate.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
    }

    public static void PrepareContainedOutputPath(string outputRoot, string targetPath)
    {
        var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(outputRoot));
        var target = Path.GetFullPath(targetPath);
        if (!IsWithinOrEqual(root, target) || target.Equals(root, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Output target is outside the selected export directory.");
        }
        if (!Directory.Exists(root))
        {
            throw new DirectoryNotFoundException($"Export directory does not exist: {root}");
        }

        RejectReparsePoint(root);
        var parent = Path.GetDirectoryName(target)
            ?? throw new InvalidDataException("Output target has no parent directory.");
        var relativeParent = Path.GetRelativePath(root, parent);
        var current = root;
        if (relativeParent != ".")
        {
            foreach (var segment in relativeParent.Split(
                [Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar],
                StringSplitOptions.RemoveEmptyEntries))
            {
                current = Path.Combine(current, segment);
                if (File.Exists(current) && !Directory.Exists(current))
                {
                    throw new InvalidDataException($"Output path component is not a directory: {current}");
                }
                Directory.CreateDirectory(current);
                RejectReparsePoint(current);
            }
        }

        if (File.Exists(target) || Directory.Exists(target))
        {
            RejectReparsePoint(target);
            if (Directory.Exists(target))
            {
                throw new InvalidDataException("Output file resolves to an existing directory.");
            }
        }
    }

    private static void RejectReparsePoint(string path)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidDataException($"Output path crosses a reparse point: {path}");
        }
    }
}

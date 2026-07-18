using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;

namespace Cdmw.ArchiveLite.Core;

public static class ArchiveFingerprint
{
    public static async Task<ArchiveFingerprintResult> ComputeAsync(
        string packageRoot,
        CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(packageRoot);
        var root = Path.GetFullPath(packageRoot);
        if (!File.Exists(root) && !Directory.Exists(root))
        {
            throw new DirectoryNotFoundException($"Archive root does not exist: {root}");
        }

        var files = DiscoverArchiveFiles(root);
        if (!files.Any(static path => path.EndsWith(".pamt", StringComparison.OrdinalIgnoreCase)))
        {
            throw new InvalidDataException("No PAMT files were found under the selected archive root.");
        }

        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = new byte[128 * 1024];
        var metadata = new byte[16];
        foreach (var file in files)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var info = new FileInfo(file);
            AppendText(hash, RelativeIdentity(root, file));
            BinaryPrimitives.WriteInt64LittleEndian(metadata, info.Length);
            BinaryPrimitives.WriteInt64LittleEndian(metadata.AsSpan(8), info.LastWriteTimeUtc.Ticks);
            hash.AppendData(metadata);
            if (file.EndsWith(".pamt", StringComparison.OrdinalIgnoreCase) ||
                file.EndsWith(".pathc", StringComparison.OrdinalIgnoreCase))
            {
                await using var stream = new FileStream(
                    file,
                    FileMode.Open,
                    FileAccess.Read,
                    FileShare.ReadWrite | FileShare.Delete,
                    buffer.Length,
                    FileOptions.Asynchronous | FileOptions.SequentialScan);
                while (true)
                {
                    var read = await stream.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
                    if (read == 0) break;
                    hash.AppendData(buffer.AsSpan(0, read));
                }
            }
        }
        return new ArchiveFingerprintResult(Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant(), files);
    }

    private static IReadOnlyList<string> DiscoverArchiveFiles(string root)
    {
        if (File.Exists(root))
        {
            if (!root.EndsWith(".pamt", StringComparison.OrdinalIgnoreCase))
            {
                return [root];
            }
            var packageDirectory = Path.GetDirectoryName(root)
                ?? throw new InvalidDataException("PAMT file has no package directory.");
            var related = Directory.EnumerateFiles(packageDirectory, "*", SearchOption.TopDirectoryOnly)
                .Where(static path =>
                    path.EndsWith(".paz", StringComparison.OrdinalIgnoreCase) ||
                    path.EndsWith(".pathc", StringComparison.OrdinalIgnoreCase))
                .Append(root)
                .ToList();
            var metadataDirectory = Path.Combine(Path.GetDirectoryName(packageDirectory) ?? packageDirectory, "meta");
            if (Directory.Exists(metadataDirectory))
            {
                related.AddRange(Directory.EnumerateFiles(metadataDirectory, "*.pathc", SearchOption.TopDirectoryOnly));
            }
            return related.Distinct(StringComparer.OrdinalIgnoreCase).Order(StringComparer.OrdinalIgnoreCase).ToArray();
        }
        var options = new EnumerationOptions
        {
            RecurseSubdirectories = true,
            IgnoreInaccessible = true,
            AttributesToSkip = FileAttributes.ReparsePoint,
            MatchCasing = MatchCasing.CaseInsensitive,
        };
        return Directory.EnumerateFiles(root, "*", options)
            .Where(static path =>
                path.EndsWith(".pamt", StringComparison.OrdinalIgnoreCase) ||
                path.EndsWith(".paz", StringComparison.OrdinalIgnoreCase) ||
                path.EndsWith(".pathc", StringComparison.OrdinalIgnoreCase))
            .Where(path => !IsCdmodsPath(root, path))
            .Order(StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    private static bool IsCdmodsPath(string root, string path)
    {
        var relative = Path.GetRelativePath(root, path);
        var firstSeparator = relative.IndexOfAny([Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar]);
        var first = firstSeparator < 0 ? relative : relative[..firstSeparator];
        return first.Equals("cdmods", StringComparison.OrdinalIgnoreCase);
    }

    private static string RelativeIdentity(string root, string file) =>
        File.Exists(root)
            ? Path.GetRelativePath(Path.GetDirectoryName(root)!, file).Replace('\\', '/').ToLowerInvariant()
            : Path.GetRelativePath(root, file).Replace('\\', '/').ToLowerInvariant();

    private static void AppendText(IncrementalHash hash, string value) => hash.AppendData(Encoding.UTF8.GetBytes(value));
}

public sealed record ArchiveFingerprintResult(string Value, IReadOnlyList<string> SourceFiles);

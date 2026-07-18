using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public static class ArchiveFingerprint
{
    public static async Task<ArchiveFingerprintResult> ComputeAsync(
        string packageRoot,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
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

        var contentBytes = files
            .Where(RequiresContentHash)
            .Select(static path => new FileInfo(path).Length)
            .Aggregate(0L, static (total, length) =>
                total > long.MaxValue - length ? long.MaxValue : total + length);
        await PublishProgressAsync(
            progress,
            new ProgressUpdate(0, contentBytes, "fingerprint", RelativeIdentity(root, files[0]))).ConfigureAwait(false);

        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = new byte[128 * 1024];
        var metadata = new byte[16];
        long completedBytes = 0;
        long lastPublishedBytes = 0;
        foreach (var file in files)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var info = new FileInfo(file);
            var relativeIdentity = RelativeIdentity(root, file);
            AppendText(hash, relativeIdentity);
            BinaryPrimitives.WriteInt64LittleEndian(metadata, info.Length);
            BinaryPrimitives.WriteInt64LittleEndian(metadata.AsSpan(8), info.LastWriteTimeUtc.Ticks);
            hash.AppendData(metadata);
            if (RequiresContentHash(file))
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
                    completedBytes += read;
                    if (completedBytes - lastPublishedBytes >= 8L * 1024L * 1024L)
                    {
                        lastPublishedBytes = completedBytes;
                        await PublishProgressAsync(
                            progress,
                            new ProgressUpdate(completedBytes, contentBytes, "fingerprint", relativeIdentity)).ConfigureAwait(false);
                    }
                }
            }
        }
        await PublishProgressAsync(
            progress,
            new ProgressUpdate(contentBytes, contentBytes, "fingerprint", "complete")).ConfigureAwait(false);
        return new ArchiveFingerprintResult(Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant(), files);
    }

    private static bool RequiresContentHash(string path) =>
        path.EndsWith(".pamt", StringComparison.OrdinalIgnoreCase) ||
        path.EndsWith(".pathc", StringComparison.OrdinalIgnoreCase);

    private static Task PublishProgressAsync(
        Func<ProgressUpdate, Task>? progress,
        ProgressUpdate update) => progress is null ? Task.CompletedTask : progress(update);

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

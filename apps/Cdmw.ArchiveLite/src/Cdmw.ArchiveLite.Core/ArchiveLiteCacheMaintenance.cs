namespace Cdmw.ArchiveLite.Core;

public static class ArchiveLiteCacheMaintenance
{
    public static CachePruneResult Prune(string cacheRoot, long maximumBytes)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(cacheRoot);
        if (maximumBytes < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(maximumBytes));
        }
        if (!Directory.Exists(cacheRoot))
        {
            return new CachePruneResult(0, 0, 0);
        }

        var options = new EnumerationOptions
        {
            RecurseSubdirectories = true,
            IgnoreInaccessible = true,
            AttributesToSkip = FileAttributes.ReparsePoint,
        };
        var files = new List<FileInfo>();
        long totalBytes = 0;
        try
        {
            foreach (var path in Directory.EnumerateFiles(cacheRoot, "*", options))
            {
                try
                {
                    var info = new FileInfo(path);
                    if ((info.Attributes & FileAttributes.ReparsePoint) != 0)
                    {
                        continue;
                    }
                    if (info.Extension.Equals(".tmp", StringComparison.OrdinalIgnoreCase) &&
                        info.LastWriteTimeUtc < DateTime.UtcNow.AddDays(-1))
                    {
                        info.Delete();
                        continue;
                    }
                    totalBytes = totalBytes > long.MaxValue - info.Length ? long.MaxValue : totalBytes + info.Length;
                    files.Add(info);
                }
                catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
                {
                    // Cache maintenance is best-effort and never blocks startup.
                }
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // The cache may change while it is enumerated; prune the rows found so far.
        }

        var before = totalBytes;
        var removed = 0;
        var targetBytes = maximumBytes - maximumBytes / 10;
        if (totalBytes > maximumBytes)
        {
            foreach (var file in files.OrderBy(static info => info.LastWriteTimeUtc).ThenBy(static info => info.FullName, StringComparer.OrdinalIgnoreCase))
            {
                if (totalBytes <= targetBytes)
                {
                    break;
                }
                try
                {
                    var length = file.Length;
                    file.Delete();
                    totalBytes = Math.Max(0, totalBytes - length);
                    removed++;
                }
                catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
                {
                    // A live cache entry remains authoritative until a later startup.
                }
            }
        }
        return new CachePruneResult(before, totalBytes, removed);
    }
}

public sealed record CachePruneResult(long BytesBefore, long BytesAfter, int FilesRemoved);

using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveCacheHealthService
{
    private const int ManifestSchemaVersion = 1;
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        WriteIndented = true,
    };

    public async Task<ArchiveCacheHealthResult> InspectAsync(
        ArchiveCacheHealthRequest request,
        Func<ProgressUpdate, Task>? publishProgress,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var root = NormalizeRoot(request.PackageRoot);
        if (publishProgress is not null)
        {
            await publishProgress(new ProgressUpdate(0, 0, "cache_health", root)).ConfigureAwait(false);
        }
        var result = await Task.Run(
            () => InspectCore(root, cancellationToken),
            cancellationToken).ConfigureAwait(false);
        if (publishProgress is not null)
        {
            await publishProgress(new ProgressUpdate(result.SourceCount, result.SourceCount, "cache_health", root)).ConfigureAwait(false);
        }
        return result;
    }

    public static async Task PublishCurrentAsync(
        string packageRoot,
        ArchiveFingerprintResult fingerprint,
        long entryCount,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(fingerprint);
        ArchiveLiteDataPaths.EnsureCreated();
        var root = NormalizeRoot(packageRoot);
        var sources = BuildSourceStamps(root, fingerprint.SourceFiles, cancellationToken);
        var payload = new CacheRootManifest(
            ManifestSchemaVersion,
            root,
            fingerprint.Value,
            ArchiveIndex.Version,
            entryCount,
            DateTimeOffset.UtcNow,
            sources);
        await AtomicFile.WriteAsync(
            ManifestPath(root),
            (stream, token) => JsonSerializer.SerializeAsync(stream, payload, JsonOptions, token),
            cancellationToken).ConfigureAwait(false);
    }

    private static ArchiveCacheHealthResult InspectCore(string root, CancellationToken cancellationToken)
    {
        if (!File.Exists(root) && !Directory.Exists(root))
        {
            return new ArchiveCacheHealthResult(
                root,
                ArchiveCacheHealthState.Invalid,
                $"The selected Crimson Desert folder does not exist: {root}");
        }

        IReadOnlyList<string> sourceFiles;
        try
        {
            sourceFiles = ArchiveFingerprint.DiscoverSourceFiles(root);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return new ArchiveCacheHealthResult(
                root,
                ArchiveCacheHealthState.Invalid,
                $"Archive sources could not be inspected: {exception.Message}");
        }
        cancellationToken.ThrowIfCancellationRequested();
        if (!sourceFiles.Any(static path => path.EndsWith(".pamt", StringComparison.OrdinalIgnoreCase)))
        {
            return new ArchiveCacheHealthResult(
                root,
                ArchiveCacheHealthState.Invalid,
                "No PAMT files were found under the selected Crimson Desert folder.",
                sourceFiles.Count);
        }

        ArchiveLiteDataPaths.EnsureCreated();
        var manifestPath = ManifestPath(root);
        if (!File.Exists(manifestPath))
        {
            return new ArchiveCacheHealthResult(
                root,
                ArchiveCacheHealthState.Missing,
                "No verified Archive Lite cache exists for this folder yet.",
                sourceFiles.Count);
        }

        CacheRootManifest? manifest;
        try
        {
            using var stream = new FileStream(
                manifestPath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete,
                64 * 1024,
                FileOptions.SequentialScan);
            manifest = JsonSerializer.Deserialize<CacheRootManifest>(stream, JsonOptions);
        }
        catch (Exception exception) when (exception is IOException or JsonException or UnauthorizedAccessException)
        {
            return new ArchiveCacheHealthResult(
                root,
                ArchiveCacheHealthState.Stale,
                $"Archive cache metadata is unreadable and will be rebuilt: {exception.Message}",
                sourceFiles.Count);
        }

        if (manifest is null || !ManifestIsCompatible(manifest, root))
        {
            return new ArchiveCacheHealthResult(
                root,
                ArchiveCacheHealthState.Stale,
                "Archive cache metadata is from an older or different cache format and will be rebuilt.",
                sourceFiles.Count,
                CachedFingerprint: manifest?.Fingerprint);
        }

        IReadOnlyList<ArchiveCacheSourceStamp> currentSources;
        try
        {
            currentSources = BuildSourceStamps(root, sourceFiles, cancellationToken);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return new ArchiveCacheHealthResult(
                root,
                ArchiveCacheHealthState.Invalid,
                $"Archive source metadata changed while cache health was checked: {exception.Message}",
                sourceFiles.Count,
                CachedFingerprint: manifest.Fingerprint);
        }
        var cachedSources = manifest.Sources.ToDictionary(static item => item.Identity, StringComparer.OrdinalIgnoreCase);
        var currentSourceMap = currentSources.ToDictionary(static item => item.Identity, StringComparer.OrdinalIgnoreCase);
        var changed = 0;
        foreach (var source in currentSources)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!cachedSources.TryGetValue(source.Identity, out var cached)
                || cached.Length != source.Length
                || cached.LastWriteTimeUtcTicks != source.LastWriteTimeUtcTicks)
            {
                changed++;
            }
        }
        changed += cachedSources.Keys.Count(identity => !currentSourceMap.ContainsKey(identity));
        if (changed > 0)
        {
            return new ArchiveCacheHealthResult(
                root,
                ArchiveCacheHealthState.Stale,
                $"Archive cache is stale: {changed:N0} archive source file(s) were added, removed, or changed.",
                sourceFiles.Count,
                changed,
                manifest.Fingerprint);
        }

        var indexPath = Path.Combine(ArchiveLiteDataPaths.IndexCache, $"{manifest.Fingerprint}.ali");
        if (!File.Exists(indexPath))
        {
            return new ArchiveCacheHealthResult(
                root,
                ArchiveCacheHealthState.Missing,
                "Archive cache metadata exists, but its index file is missing.",
                sourceFiles.Count,
                CachedFingerprint: manifest.Fingerprint);
        }

        try
        {
            using var index = ArchiveIndex.Open(indexPath);
            if (index.EntryCount != manifest.EntryCount)
            {
                throw new InvalidDataException("entry count does not match cache metadata");
            }
        }
        catch (Exception exception) when (exception is IOException or InvalidDataException or UnauthorizedAccessException)
        {
            return new ArchiveCacheHealthResult(
                root,
                ArchiveCacheHealthState.Stale,
                $"Archive cache index is invalid and will be rebuilt: {exception.Message}",
                sourceFiles.Count,
                CachedFingerprint: manifest.Fingerprint);
        }

        return new ArchiveCacheHealthResult(
            root,
            ArchiveCacheHealthState.Current,
            $"Archive cache is current for {sourceFiles.Count:N0} source file(s).",
            sourceFiles.Count,
            CachedFingerprint: manifest.Fingerprint);
    }

    private static IReadOnlyList<ArchiveCacheSourceStamp> BuildSourceStamps(
        string root,
        IReadOnlyList<string> sourceFiles,
        CancellationToken cancellationToken)
    {
        var result = new List<ArchiveCacheSourceStamp>(sourceFiles.Count);
        foreach (var sourcePath in sourceFiles)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var fullPath = Path.GetFullPath(sourcePath);
            var info = new FileInfo(fullPath);
            result.Add(new ArchiveCacheSourceStamp(
                SourceIdentity(root, fullPath),
                info.Length,
                info.LastWriteTimeUtc.Ticks));
        }
        return result
            .OrderBy(static item => item.Identity, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    private static string SourceIdentity(string root, string sourcePath)
    {
        var basePath = File.Exists(root)
            ? Path.GetDirectoryName(root) ?? root
            : root;
        return Path.GetRelativePath(basePath, sourcePath)
            .Replace('\\', '/')
            .Trim()
            .ToLowerInvariant();
    }

    private static string ManifestPath(string packageRoot)
    {
        var key = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(packageRoot.ToLowerInvariant())))
            .ToLowerInvariant();
        return Path.Combine(ArchiveLiteDataPaths.IndexRootManifests, $"{key}.json");
    }

    private static bool ManifestIsCompatible(CacheRootManifest manifest, string root)
    {
        try
        {
            return manifest.SchemaVersion == ManifestSchemaVersion
                && manifest.IndexVersion == ArchiveIndex.Version
                && !string.IsNullOrWhiteSpace(manifest.PackageRoot)
                && IsSha256Fingerprint(manifest.Fingerprint)
                && manifest.EntryCount >= 0
                && manifest.Sources is { } sources
                && sources.All(static source =>
                    !string.IsNullOrWhiteSpace(source.Identity)
                    && source.Length >= 0
                    && source.LastWriteTimeUtcTicks >= 0)
                && sources.Select(static source => source.Identity).Distinct(StringComparer.OrdinalIgnoreCase).Count() == sources.Count
                && string.Equals(NormalizeRoot(manifest.PackageRoot), root, StringComparison.OrdinalIgnoreCase);
        }
        catch (Exception exception) when (exception is ArgumentException or NotSupportedException)
        {
            return false;
        }
    }

    private static bool IsSha256Fingerprint(string? value) =>
        value is { Length: 64 }
        && value.All(static character =>
            character is >= '0' and <= '9'
            || character is >= 'a' and <= 'f'
            || character is >= 'A' and <= 'F');

    private static string NormalizeRoot(string packageRoot)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(packageRoot);
        var root = Path.GetFullPath(packageRoot.Trim());
        var driveRoot = Path.GetPathRoot(root);
        return string.Equals(root, driveRoot, StringComparison.OrdinalIgnoreCase)
            ? root
            : root.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }

    private sealed record CacheRootManifest(
        int SchemaVersion,
        string PackageRoot,
        string Fingerprint,
        int IndexVersion,
        long EntryCount,
        DateTimeOffset UpdatedUtc,
        IReadOnlyList<ArchiveCacheSourceStamp> Sources);

    private sealed record ArchiveCacheSourceStamp(
        string Identity,
        long Length,
        long LastWriteTimeUtcTicks);
}

using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveCacheStore
{
    public const long MaximumCacheBytes = 5L * 1024L * 1024L * 1024L;

    private readonly ConcurrentDictionary<string, SemaphoreSlim> _rootGates = new(StringComparer.Ordinal);
    private readonly object _activeGate = new();
    private readonly Dictionary<string, int> _activeGenerations = new(StringComparer.OrdinalIgnoreCase);

    public ArchiveCacheStore(string archiveCacheRoot)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(archiveCacheRoot);
        ArchiveCacheRoot = Path.GetFullPath(archiveCacheRoot);
        CatalogueRoot = ResolveCatalogueRoot(ArchiveCacheRoot);
        Directory.CreateDirectory(CatalogueRoot);
    }

    public string ArchiveCacheRoot { get; }
    public string CatalogueRoot { get; }

    private static string ResolveCatalogueRoot(string archiveCacheRoot)
    {
        var indexRoot = Path.Combine(archiveCacheRoot, "index");
        var preferredRoot = Path.Combine(indexRoot, "catalogue_v2");
        var legacyRoot = Path.Combine(archiveCacheRoot, "catalogue_v2");
        Directory.CreateDirectory(indexRoot);
        if (!Directory.Exists(preferredRoot) && Directory.Exists(legacyRoot))
        {
            try
            {
                Directory.Move(legacyRoot, preferredRoot);
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
            {
                return legacyRoot;
            }
        }
        return preferredRoot;
    }

    public static string DeriveRootId(string packageRoot)
    {
        var canonical = CanonicalRoot(packageRoot).ToLowerInvariant();
        var digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();
        return digest[..24];
    }

    public async Task UpdateSecondaryStateAsync(
        string generationPath,
        bool? lookupsReady,
        bool? namesReady,
        CancellationToken cancellationToken)
    {
        var fullGenerationPath = Path.GetFullPath(generationPath);
        var cataloguePrefix = CatalogueRoot.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!fullGenerationPath.StartsWith(cataloguePrefix, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("Archive generation is outside the v2 cache family.");
        }
        var manifestPath = Path.Combine(fullGenerationPath, "manifest.json");
        var manifest = await ReadJsonAsync<ArchiveGenerationManifest>(manifestPath, cancellationToken).ConfigureAwait(false);
        var updated = manifest with
        {
            LookupsReady = lookupsReady ?? manifest.LookupsReady,
            NamesReady = namesReady ?? manifest.NamesReady,
        };
        await AtomicJson.WriteAsync(manifestPath, updated, cancellationToken).ConfigureAwait(false);
    }

    public async Task<CacheHealthResult> InspectAsync(
        string packageRoot,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        var canonicalRoot = CanonicalRoot(packageRoot);
        var rootId = DeriveRootId(canonicalRoot);
        var rootDirectory = RootDirectory(rootId);
        var currentPath = Path.Combine(rootDirectory, "current.json");
        if (!File.Exists(currentPath))
        {
            return new CacheHealthResult(canonicalRoot, rootId, "missing", "No v2 generation has been published.");
        }

        ArchiveFingerprintResult fingerprint;
        try
        {
            fingerprint = await ArchiveFingerprint.ComputeAsync(canonicalRoot, cancellationToken, progress).ConfigureAwait(false);
        }
        catch (Exception exception) when (exception is IOException or InvalidDataException or UnauthorizedAccessException)
        {
            return new CacheHealthResult(canonicalRoot, rootId, "invalid_source", exception.Message);
        }

        try
        {
            var pointer = await ReadJsonAsync<ArchiveCurrentPointer>(currentPath, cancellationToken).ConfigureAwait(false);
            if (!StringComparer.Ordinal.Equals(pointer.RootId, rootId))
            {
                return new CacheHealthResult(canonicalRoot, rootId, "invalid", "The current pointer belongs to another archive root.");
            }
            if (!StringComparer.Ordinal.Equals(pointer.Fingerprint, fingerprint.Value))
            {
                return new CacheHealthResult(
                    canonicalRoot,
                    rootId,
                    "stale",
                    "Archive source fingerprints changed.",
                    pointer.Fingerprint,
                    pointer.GenerationId);
            }

            var generationPath = GenerationDirectory(rootId, pointer.GenerationId);
            using var index = ValidateGeneration(
                generationPath,
                pointer,
                canonicalRoot,
                fingerprint.Value,
                out _);
            return new CacheHealthResult(
                canonicalRoot,
                rootId,
                "current",
                "The published v2 generation matches the archive sources.",
                pointer.Fingerprint,
                pointer.GenerationId,
                index.EntryCount);
        }
        catch (Exception exception) when (exception is IOException or JsonException or InvalidDataException or UnauthorizedAccessException)
        {
            return new CacheHealthResult(canonicalRoot, rootId, "invalid", exception.Message, fingerprint.Value);
        }
    }

    public async Task<ArchiveGenerationLease> OpenAsync(
        string packageRoot,
        bool forceRefresh,
        NativeArchiveCore native,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        ArgumentNullException.ThrowIfNull(native);
        var canonicalRoot = CanonicalRoot(packageRoot);
        var rootId = DeriveRootId(canonicalRoot);
        var rootGate = _rootGates.GetOrAdd(rootId, static _ => new SemaphoreSlim(1, 1));
        await rootGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var fingerprint = await ArchiveFingerprint.ComputeAsync(canonicalRoot, cancellationToken, progress).ConfigureAwait(false);
            if (!forceRefresh)
            {
                var cached = await TryOpenCurrentAsync(
                    rootId,
                    canonicalRoot,
                    fingerprint,
                    cancellationToken,
                    progress).ConfigureAwait(false);
                if (cached is not null)
                {
                    return cached;
                }
            }

            var generationId = $"{DateTimeOffset.UtcNow:yyyyMMddHHmmssfff}-{Guid.NewGuid():N}"[..30];
            var generationsRoot = Path.Combine(RootDirectory(rootId), "generations");
            Directory.CreateDirectory(generationsRoot);
            var stagingPath = Path.Combine(generationsRoot, $".{generationId}.staging");
            var generationPath = Path.Combine(generationsRoot, generationId);
            Directory.CreateDirectory(stagingPath);
            try
            {
                var indexPath = Path.Combine(stagingPath, "archive.ali");
                var entryCount = await Task.Run(
                    () => native.BuildIndex(
                        canonicalRoot,
                        indexPath,
                        update => progress?.Invoke(update).GetAwaiter().GetResult(),
                        cancellationToken),
                    CancellationToken.None).ConfigureAwait(false);
                cancellationToken.ThrowIfCancellationRequested();

                var manifest = await BuildManifestAsync(
                    rootId,
                    generationId,
                    canonicalRoot,
                    fingerprint,
                    entryCount,
                    cancellationToken).ConfigureAwait(false);
                await AtomicJson.WriteAsync(Path.Combine(stagingPath, "manifest.json"), manifest, cancellationToken).ConfigureAwait(false);
                using (var validation = ValidateGeneration(
                    stagingPath,
                    new ArchiveCurrentPointer(rootId, generationId, fingerprint.Value, DateTimeOffset.UtcNow),
                    canonicalRoot,
                    fingerprint.Value,
                    out _))
                {
                    if (validation.EntryCount != entryCount)
                    {
                        throw new InvalidDataException("The native index entry count does not match its generation manifest.");
                    }
                }

                Directory.Move(stagingPath, generationPath);
                var pointer = new ArchiveCurrentPointer(rootId, generationId, fingerprint.Value, DateTimeOffset.UtcNow);
                await AtomicJson.WriteAsync(Path.Combine(RootDirectory(rootId), "current.json"), pointer, cancellationToken).ConfigureAwait(false);
                var lease = await AcquireGenerationAsync(
                    generationPath,
                    manifest,
                    cacheHit: false,
                    validatedIndex: null,
                    cancellationToken,
                    progress).ConfigureAwait(false);
                PruneSupersededGenerations(rootId, generationId);
                PruneCacheFamily();
                return lease;
            }
            catch
            {
                TryDeleteDirectory(stagingPath);
                throw;
            }
        }
        finally
        {
            rootGate.Release();
        }
    }

    private async Task<ArchiveGenerationLease?> TryOpenCurrentAsync(
        string rootId,
        string packageRoot,
        ArchiveFingerprintResult fingerprint,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        var currentPath = Path.Combine(RootDirectory(rootId), "current.json");
        if (!File.Exists(currentPath))
        {
            return null;
        }

        ArchiveCurrentPointer? pointer = null;
        ArchiveIndex? validatedIndex = null;
        string? generationPath = null;
        ArchiveGenerationManifest? manifest = null;
        try
        {
            pointer = await ReadJsonAsync<ArchiveCurrentPointer>(currentPath, cancellationToken).ConfigureAwait(false);
            if (!StringComparer.Ordinal.Equals(pointer.RootId, rootId) ||
                !StringComparer.Ordinal.Equals(pointer.Fingerprint, fingerprint.Value))
            {
                return null;
            }
            generationPath = GenerationDirectory(rootId, pointer.GenerationId);
            validatedIndex = ValidateGeneration(
                generationPath,
                pointer,
                packageRoot,
                fingerprint.Value,
                out var validatedManifest);
            manifest = validatedManifest;
        }
        catch (Exception exception) when (exception is IOException or JsonException or InvalidDataException or UnauthorizedAccessException)
        {
            validatedIndex?.Dispose();
            if (pointer is not null)
            {
                QuarantineCorruptGeneration(rootId, pointer.GenerationId, exception.Message);
            }
            return null;
        }
        catch
        {
            validatedIndex?.Dispose();
            throw;
        }

        return await AcquireGenerationAsync(
            generationPath!,
            manifest!,
            cacheHit: true,
            validatedIndex,
            cancellationToken,
            progress).ConfigureAwait(false);
    }

    private async Task<ArchiveGenerationLease> AcquireGenerationAsync(
        string generationPath,
        ArchiveGenerationManifest manifest,
        bool cacheHit,
        ArchiveIndex? validatedIndex,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        ArchiveIndex? index = validatedIndex;
        ArchiveDependencyIndex? dependencyIndex = null;
        try
        {
            index ??= ArchiveIndex.Open(Path.Combine(generationPath, "archive.ali"));
            dependencyIndex = await ArchiveDependencyIndex.OpenOrBuildAsync(
                index,
                Path.Combine(generationPath, "archive.adi"),
                progress,
                cancellationToken).ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();
            if (!manifest.LookupsReady)
            {
                await UpdateSecondaryStateAsync(
                    generationPath,
                    lookupsReady: true,
                    namesReady: null,
                    cancellationToken).ConfigureAwait(false);
                manifest = manifest with { LookupsReady = true };
            }
            lock (_activeGate)
            {
                _activeGenerations[generationPath] = _activeGenerations.GetValueOrDefault(generationPath) + 1;
            }
            return new ArchiveGenerationLease(this, generationPath, manifest, index, dependencyIndex, cacheHit);
        }
        catch
        {
            dependencyIndex?.Dispose();
            index?.Dispose();
            throw;
        }
    }

    internal void ReleaseGeneration(string generationPath)
    {
        lock (_activeGate)
        {
            if (!_activeGenerations.TryGetValue(generationPath, out var count))
            {
                return;
            }
            if (count <= 1)
            {
                _activeGenerations.Remove(generationPath);
            }
            else
            {
                _activeGenerations[generationPath] = count - 1;
            }
        }
    }

    private ArchiveIndex ValidateGeneration(
        string generationPath,
        ArchiveCurrentPointer pointer,
        string packageRoot,
        string fingerprint,
        out ArchiveGenerationManifest manifest)
    {
        var manifestPath = Path.Combine(generationPath, "manifest.json");
        var indexPath = Path.Combine(generationPath, "archive.ali");
        if (!File.Exists(manifestPath) || !File.Exists(indexPath))
        {
            throw new InvalidDataException("The archive generation is incomplete.");
        }
        manifest = JsonSerializer.Deserialize<ArchiveGenerationManifest>(
            File.ReadAllText(manifestPath),
            WorkerProtocol.JsonOptions) ?? throw new InvalidDataException("The archive generation manifest is empty.");
        if (!StringComparer.Ordinal.Equals(manifest.RootId, pointer.RootId) ||
            !StringComparer.Ordinal.Equals(manifest.GenerationId, pointer.GenerationId) ||
            !StringComparer.Ordinal.Equals(manifest.Fingerprint, fingerprint) ||
            !StringComparer.OrdinalIgnoreCase.Equals(CanonicalRoot(manifest.PackageRoot), CanonicalRoot(packageRoot)) ||
            manifest.IndexVersion != ArchiveIndex.Version ||
            manifest.SourceFiles.Count == 0)
        {
            throw new InvalidDataException("The archive generation manifest does not match its source or pointer.");
        }

        var index = ArchiveIndex.Open(indexPath);
        if (index.EntryCount != manifest.EntryCount)
        {
            index.Dispose();
            throw new InvalidDataException("The archive generation entry count is inconsistent.");
        }
        return index;
    }

    private static async Task<ArchiveGenerationManifest> BuildManifestAsync(
        string rootId,
        string generationId,
        string packageRoot,
        ArchiveFingerprintResult fingerprint,
        long entryCount,
        CancellationToken cancellationToken)
    {
        var rows = new List<ArchiveSourceReference>(fingerprint.SourceFiles.Count);
        var identityRoot = File.Exists(packageRoot)
            ? Path.GetDirectoryName(packageRoot) ?? packageRoot
            : packageRoot;
        foreach (var source in fingerprint.SourceFiles)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var info = new FileInfo(source);
            rows.Add(new ArchiveSourceReference(
                Path.GetRelativePath(identityRoot, source).Replace('\\', '/'),
                info.Length,
                info.LastWriteTimeUtc.Ticks));
        }
        await Task.CompletedTask.ConfigureAwait(false);
        return new ArchiveGenerationManifest(
            rootId,
            generationId,
            packageRoot,
            fingerprint.Value,
            entryCount,
            ArchiveIndex.Version,
            DateTimeOffset.UtcNow,
            rows,
            LookupsReady: false,
            NamesReady: false);
    }

    private void QuarantineCorruptGeneration(string rootId, string generationId, string reason)
    {
        var source = GenerationDirectory(rootId, generationId);
        if (!Directory.Exists(source) || IsActive(source))
        {
            return;
        }
        try
        {
            var quarantine = Path.Combine(RootDirectory(rootId), "quarantine");
            Directory.CreateDirectory(quarantine);
            var destination = Path.Combine(quarantine, $"{generationId}-{DateTimeOffset.UtcNow:yyyyMMddHHmmssfff}");
            Directory.Move(source, destination);
            File.WriteAllText(Path.Combine(destination, "quarantine-reason.txt"), reason);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // A mapped or externally inspected generation remains in place and will be ignored on rebuild.
        }
    }

    private void PruneSupersededGenerations(string rootId, string currentGenerationId)
    {
        var root = Path.Combine(RootDirectory(rootId), "generations");
        if (!Directory.Exists(root))
        {
            return;
        }
        foreach (var directory in new DirectoryInfo(root).EnumerateDirectories()
                     .Where(static item => !item.Name.StartsWith(".", StringComparison.Ordinal))
                     .OrderByDescending(static item => item.CreationTimeUtc)
                     .Skip(2))
        {
            if (directory.Name.Equals(currentGenerationId, StringComparison.Ordinal) || IsActive(directory.FullName))
            {
                continue;
            }
            TryDeleteDirectory(directory.FullName);
        }
    }

    private void PruneCacheFamily()
    {
        var root = new DirectoryInfo(CatalogueRoot);
        var directories = root.EnumerateDirectories()
            .SelectMany(static rootDirectory => new[] { "generations", "quarantine" }
                .Select(name => new DirectoryInfo(Path.Combine(rootDirectory.FullName, name)))
                .Where(static family => family.Exists)
                .SelectMany(static family => family.EnumerateDirectories()))
            .Where(static item => !item.Name.StartsWith(".", StringComparison.Ordinal))
            .Select(item => new CacheDirectory(item.FullName, DirectorySize(item.FullName), item.LastWriteTimeUtc))
            .OrderBy(static item => item.LastWriteUtc)
            .ToArray();
        var total = DirectorySize(CatalogueRoot);
        if (total <= MaximumCacheBytes)
        {
            return;
        }
        foreach (var item in directories)
        {
            if (IsActive(item.Path) || IsCurrentGeneration(item.Path))
            {
                continue;
            }
            TryDeleteDirectory(item.Path);
            total -= item.Size;
            if (total <= MaximumCacheBytes)
            {
                break;
            }
        }
    }

    private bool IsCurrentGeneration(string path)
    {
        var generation = new DirectoryInfo(path);
        if (generation.Parent?.Name != "generations")
        {
            return false;
        }
        var rootDirectory = generation.Parent.Parent;
        if (rootDirectory is null)
        {
            return false;
        }
        try
        {
            var pointer = JsonSerializer.Deserialize<ArchiveCurrentPointer>(
                File.ReadAllText(Path.Combine(rootDirectory.FullName, "current.json")),
                WorkerProtocol.JsonOptions);
            return pointer?.GenerationId.Equals(generation.Name, StringComparison.Ordinal) == true;
        }
        catch (Exception exception) when (exception is IOException or JsonException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    private bool IsActive(string path)
    {
        lock (_activeGate)
        {
            return _activeGenerations.Keys.Any(active =>
                active.Equals(path, StringComparison.OrdinalIgnoreCase) ||
                active.StartsWith(path.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) ||
                path.StartsWith(active.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase));
        }
    }

    private string RootDirectory(string rootId) => Path.Combine(CatalogueRoot, rootId);

    private string GenerationDirectory(string rootId, string generationId) =>
        Path.Combine(RootDirectory(rootId), "generations", generationId);

    private static string CanonicalRoot(string packageRoot)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(packageRoot);
        return Path.GetFullPath(packageRoot).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
    }

    private static async Task<T> ReadJsonAsync<T>(string path, CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete,
            16 * 1024,
            FileOptions.Asynchronous | FileOptions.SequentialScan);
        return await JsonSerializer.DeserializeAsync<T>(stream, WorkerProtocol.JsonOptions, cancellationToken).ConfigureAwait(false)
            ?? throw new InvalidDataException($"JSON file is empty: {path}");
    }

    private static long DirectorySize(string path)
    {
        try
        {
            return Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories)
                .Sum(static file => new FileInfo(file).Length);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return 0;
        }
    }

    private static void TryDeleteDirectory(string path)
    {
        try
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, recursive: true);
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // Cache pruning is best effort; active or externally inspected files remain recoverable.
        }
    }

    private sealed record CacheDirectory(string Path, long Size, DateTime LastWriteUtc);
}

public sealed class ArchiveGenerationLease : IDisposable
{
    private readonly ArchiveCacheStore _owner;
    private int _disposed;

    internal ArchiveGenerationLease(
        ArchiveCacheStore owner,
        string generationPath,
        ArchiveGenerationManifest manifest,
        ArchiveIndex index,
        ArchiveDependencyIndex dependencyIndex,
        bool cacheHit)
    {
        _owner = owner;
        GenerationPath = generationPath;
        Manifest = manifest;
        Index = index;
        DependencyIndex = dependencyIndex;
        CacheHit = cacheHit;
    }

    public string GenerationPath { get; }
    public ArchiveGenerationManifest Manifest { get; }
    public ArchiveIndex Index { get; }
    internal ArchiveDependencyIndex DependencyIndex { get; }
    public bool CacheHit { get; }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }
        try
        {
            DependencyIndex.Dispose();
        }
        finally
        {
            try
            {
                Index.Dispose();
            }
            finally
            {
                _owner.ReleaseGeneration(GenerationPath);
            }
        }
    }
}

public sealed record ArchiveCurrentPointer(
    string RootId,
    string GenerationId,
    string Fingerprint,
    DateTimeOffset PublishedUtc);

public sealed record ArchiveSourceReference(string RelativePath, long Size, long ModifiedUtcTicks);

public sealed record ArchiveGenerationManifest(
    string RootId,
    string GenerationId,
    string PackageRoot,
    string Fingerprint,
    long EntryCount,
    int IndexVersion,
    DateTimeOffset CreatedUtc,
    IReadOnlyList<ArchiveSourceReference> SourceFiles,
    bool LookupsReady,
    bool NamesReady);

internal static class AtomicJson
{
    public static async Task WriteAsync<T>(string destination, T value, CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(destination)
            ?? throw new InvalidDataException("Atomic JSON destination has no parent directory."));
        var staging = Path.Combine(
            Path.GetDirectoryName(destination)!,
            $".{Path.GetFileName(destination)}.{Guid.NewGuid():N}.tmp");
        try
        {
            await using (var stream = new FileStream(
                staging,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                16 * 1024,
                FileOptions.Asynchronous | FileOptions.WriteThrough))
            {
                await JsonSerializer.SerializeAsync(stream, value, WorkerProtocol.JsonOptions, cancellationToken).ConfigureAwait(false);
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
                stream.Flush(flushToDisk: true);
            }
            cancellationToken.ThrowIfCancellationRequested();
            File.Move(staging, destination, overwrite: true);
        }
        finally
        {
            try
            {
                File.Delete(staging);
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
            {
                // A later cache prune can remove an abandoned staging file.
            }
        }
    }
}

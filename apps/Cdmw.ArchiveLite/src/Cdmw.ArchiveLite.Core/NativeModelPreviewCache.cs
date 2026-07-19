using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

internal static class NativeModelPreviewCache
{
    private const int ManifestSchema = 1;
    private const int DependencySchema = 1;
    private const int MaximumDependencies = 256;
    private const int MaximumQueries = 256;
    private const int MaximumQueryResults = 256;
    private const int MaximumMemoizedValidations = 4096;
    private const string DependencyValidation = "dependency_v1";
    private const string SessionValidation = "session_fallback";
    private static readonly ConcurrentDictionary<string, string> ValidatedFingerprints = new(StringComparer.OrdinalIgnoreCase);

    public static string ComputeKey(
        string packageVersion,
        ArchiveSession session,
        ArchiveEntryDto entry,
        ArchiveEntryDto? companion)
    {
        var fields = new List<string>
        {
            packageVersion,
            NormalizeFilePath(session.PackageRoot),
        };
        AppendEntryIdentity(fields, entry);
        if (companion is null)
        {
            fields.Add("no-companion");
        }
        else
        {
            fields.Add("companion");
            AppendEntryIdentity(fields, companion);
        }
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(string.Join('\0', fields))))
            .ToLowerInvariant();
    }

    public static bool HasCompletePackage(string directory) =>
        Directory.Exists(directory)
        && File.Exists(Path.Combine(directory, "manifest.json"))
        && File.Exists(Path.Combine(directory, "net_materials.json"))
        && File.Exists(Path.Combine(directory, "dotnet_scene.json"))
        && File.Exists(Path.Combine(directory, "archive_lite_preview.json"));

    public static async Task<bool> IsReusableAsync(
        string directory,
        string packageVersion,
        string cacheKey,
        ArchiveSession session,
        ArchiveEntryDto entry,
        CancellationToken cancellationToken)
    {
        if (!HasCompletePackage(directory))
        {
            return false;
        }

        NativeModelPreviewCacheManifest? manifest;
        try
        {
            await using var stream = new FileStream(
                Path.Combine(directory, "archive_lite_preview.json"),
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete,
                16 * 1024,
                FileOptions.Asynchronous | FileOptions.SequentialScan);
            manifest = await JsonSerializer.DeserializeAsync<NativeModelPreviewCacheManifest>(
                stream,
                NativePreviewPackageAdapter.JsonOptions,
                cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or JsonException)
        {
            return false;
        }

        if (!IsStructurallyValid(manifest, packageVersion, cacheKey, entry))
        {
            ValidatedFingerprints.TryRemove(directory, out _);
            return false;
        }
        var cacheManifest = manifest!;
        if (ValidatedFingerprints.TryGetValue(directory, out var validated))
        {
            if (string.Equals(validated, session.Fingerprint, StringComparison.Ordinal))
            {
                return true;
            }
            ValidatedFingerprints.TryRemove(directory, out _);
        }
        if (!string.Equals(cacheManifest.ValidationMode, DependencyValidation, StringComparison.Ordinal))
        {
            return string.Equals(cacheManifest.SourceSessionFingerprint, session.Fingerprint, StringComparison.Ordinal);
        }

        try
        {
            var primaryHash = await HashFileAsync(entry.SourcePamt, cancellationToken).ConfigureAwait(false);
            if (!string.Equals(primaryHash, cacheManifest.PrimaryPamtSha256, StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            foreach (var dependency in cacheManifest.Dependencies)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var current = FindCurrentEntry(session, dependency);
                if (current is null || dependency.RawSha256.Length != 64)
                {
                    return false;
                }
                var currentHash = await HashEntryRawAsync(current, cancellationToken).ConfigureAwait(false);
                if (!string.Equals(currentHash, dependency.RawSha256, StringComparison.OrdinalIgnoreCase))
                {
                    return false;
                }
            }

            foreach (var query in cacheManifest.BasenameQueries)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (query.MaximumResults is < 1 or > MaximumQueryResults)
                {
                    return false;
                }
                var current = session.BasenameIndex
                    .FindEntriesByBasename(session.Index, query.Basename, query.MaximumResults)
                    .Select(CacheEntrySnapshot.FromEntry)
                    .OrderBy(static candidate => candidate.CanonicalIdentity, StringComparer.Ordinal)
                    .ToArray();
                var expected = query.Candidates
                    .OrderBy(static candidate => candidate.CanonicalIdentity, StringComparer.Ordinal)
                    .ToArray();
                if (current.Length != expected.Length
                    || current.Where((candidate, index) =>
                        !string.Equals(candidate.CanonicalIdentity, expected[index].CanonicalIdentity, StringComparison.Ordinal)).Any())
                {
                    return false;
                }
            }

            if (ValidatedFingerprints.Count >= MaximumMemoizedValidations)
            {
                ValidatedFingerprints.Clear();
            }
            ValidatedFingerprints[directory] = session.Fingerprint;
            return true;
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or InvalidDataException or ArgumentException)
        {
            return false;
        }
    }

    public static async Task<NativeModelPreviewCacheManifest> CaptureAsync(
        string packageVersion,
        string cacheKey,
        ArchiveSession session,
        ArchiveEntryDto entry,
        NativePreviewDependencyTrace trace,
        CancellationToken cancellationToken)
    {
        var dependencies = new Dictionary<string, ArchiveEntryDto>(StringComparer.Ordinal);
        AddDependency(dependencies, entry);
        var dependencySafe = trace.Schema == DependencySchema
            && trace.Entries.Count is > 0 and <= MaximumDependencies
            && trace.Queries.Count <= MaximumQueries;
        foreach (var descriptor in trace.Entries.Take(MaximumDependencies))
        {
            cancellationToken.ThrowIfCancellationRequested();
            var current = FindCurrentEntry(session, descriptor);
            if (current is null)
            {
                dependencySafe = false;
                continue;
            }
            AddDependency(dependencies, current);
        }

        var queries = new Dictionary<string, BasenameQuerySnapshot>(StringComparer.Ordinal);
        foreach (var query in trace.Queries.Take(MaximumQueries))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (query.MaximumResults is < 1 or > MaximumQueryResults
                || string.IsNullOrWhiteSpace(query.Basename))
            {
                dependencySafe = false;
                continue;
            }
            if (string.Equals(query.Scope, "package_scan_fallback", StringComparison.Ordinal))
            {
                dependencySafe = false;
                continue;
            }
            if (string.Equals(query.Scope, "primary_pamt", StringComparison.Ordinal))
            {
                continue;
            }
            if (!string.Equals(query.Scope, "global_index", StringComparison.Ordinal))
            {
                dependencySafe = false;
                continue;
            }
            var normalizedBasename = Path.GetFileName(query.Basename.Replace('\\', '/')).ToLowerInvariant();
            var candidates = session.BasenameIndex
                .FindEntriesByBasename(session.Index, normalizedBasename, query.MaximumResults)
                .Select(CacheEntrySnapshot.FromEntry)
                .OrderBy(static candidate => candidate.CanonicalIdentity, StringComparer.Ordinal)
                .ToList();
            var snapshot = new BasenameQuerySnapshot
            {
                Basename = normalizedBasename,
                MaximumResults = query.MaximumResults,
                Candidates = candidates,
            };
            queries[$"{normalizedBasename}|{query.MaximumResults}"] = snapshot;
        }

        var dependencyEntries = new List<CacheEntrySnapshot>(dependencies.Count);
        foreach (var dependency in dependencies.Values)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var snapshot = CacheEntrySnapshot.FromEntry(dependency);
            try
            {
                snapshot.RawSha256 = await HashEntryRawAsync(dependency, cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or InvalidDataException)
            {
                dependencySafe = false;
            }
            dependencyEntries.Add(snapshot);
        }
        dependencyEntries.Sort(static (left, right) =>
            StringComparer.Ordinal.Compare(left.CanonicalIdentity, right.CanonicalIdentity));
        var primaryHash = await HashFileAsync(entry.SourcePamt, cancellationToken).ConfigureAwait(false);
        return new NativeModelPreviewCacheManifest
        {
            Schema = ManifestSchema,
            Version = packageVersion,
            CacheKey = cacheKey,
            SourceSessionFingerprint = session.Fingerprint,
            SourceIdentity = $"{packageVersion}:{cacheKey}:{entry.Path}",
            EntryPath = entry.Path,
            ValidationMode = dependencySafe ? DependencyValidation : SessionValidation,
            PrimaryPamtSha256 = primaryHash,
            Dependencies = dependencyEntries,
            BasenameQueries = queries.Values
                .OrderBy(static query => query.Basename, StringComparer.Ordinal)
                .ThenBy(static query => query.MaximumResults)
                .ToList(),
        };
    }

    public static NativePreviewDependencyTrace ReadTrace(JsonElement report)
    {
        var schema = ReadInt32(report, "cache_dependency_schema");
        var queries = new List<NativePreviewDependencyQuery>();
        if (report.TryGetProperty("cache_dependency_queries", out var queryArray)
            && queryArray.ValueKind == JsonValueKind.Array)
        {
            foreach (var query in queryArray.EnumerateArray().Take(MaximumQueries + 1))
            {
                queries.Add(new NativePreviewDependencyQuery(
                    ReadString(query, "basename"),
                    ReadInt32(query, "maximum_results"),
                    ReadString(query, "scope")));
            }
        }

        var entries = new List<CacheEntrySnapshot>();
        if (report.TryGetProperty("cache_dependency_entries", out var entryArray)
            && entryArray.ValueKind == JsonValueKind.Array)
        {
            foreach (var dependency in entryArray.EnumerateArray().Take(MaximumDependencies + 1))
            {
                entries.Add(new CacheEntrySnapshot
                {
                    Path = ReadString(dependency, "path"),
                    SourcePamt = ReadString(dependency, "pamt_path"),
                    PazFile = ReadString(dependency, "paz_file"),
                    Offset = ReadInt64(dependency, "offset"),
                    StoredSize = ReadInt64(dependency, "comp_size"),
                    OriginalSize = ReadInt64(dependency, "orig_size"),
                    Flags = ReadInt32(dependency, "flags"),
                    PazIndex = ReadInt32(dependency, "paz_index"),
                });
            }
        }
        return new NativePreviewDependencyTrace(schema, queries, entries);
    }

    private static bool IsStructurallyValid(
        NativeModelPreviewCacheManifest? manifest,
        string packageVersion,
        string cacheKey,
        ArchiveEntryDto entry)
    {
        try
        {
            var dependencyValidation = string.Equals(
                manifest?.ValidationMode,
                DependencyValidation,
                StringComparison.Ordinal);
            var sessionValidation = string.Equals(
                manifest?.ValidationMode,
                SessionValidation,
                StringComparison.Ordinal);
            return manifest is not null
                && manifest.Schema == ManifestSchema
                && string.Equals(manifest.Version, packageVersion, StringComparison.Ordinal)
                && string.Equals(manifest.CacheKey, cacheKey, StringComparison.Ordinal)
                && string.Equals(manifest.EntryPath, entry.Path, StringComparison.OrdinalIgnoreCase)
                && !string.IsNullOrWhiteSpace(manifest.SourceSessionFingerprint)
                && manifest.PrimaryPamtSha256?.Length == 64
                && manifest.Dependencies is { Count: > 0 and <= MaximumDependencies }
                && manifest.BasenameQueries is { Count: <= MaximumQueries }
                && (dependencyValidation || sessionValidation)
                && manifest.Dependencies.All(dependency =>
                    IsSnapshotStructurallyValid(dependency, dependencyValidation))
                && manifest.BasenameQueries.All(IsQueryStructurallyValid)
                && manifest.Dependencies.Any(dependency => dependency is not null && EntryMatches(dependency, entry));
        }
        catch (Exception exception) when (exception is IOException or ArgumentException or InvalidDataException)
        {
            return false;
        }
    }

    private static bool IsSnapshotStructurallyValid(CacheEntrySnapshot? snapshot, bool requireHash) =>
        snapshot is not null
        && !string.IsNullOrWhiteSpace(snapshot.Path)
        && !string.IsNullOrWhiteSpace(snapshot.SourcePamt)
        && !string.IsNullOrWhiteSpace(snapshot.PazFile)
        && snapshot.Offset >= 0
        && snapshot.StoredSize >= 0
        && snapshot.OriginalSize >= 0
        && (!requireHash || snapshot.RawSha256.Length == 64);

    private static bool IsQueryStructurallyValid(BasenameQuerySnapshot? query) =>
        query is not null
        && !string.IsNullOrWhiteSpace(query.Basename)
        && query.MaximumResults is >= 1 and <= MaximumQueryResults
        && query.Candidates is { Count: <= MaximumQueryResults }
        && query.Candidates.All(candidate => IsSnapshotStructurallyValid(candidate, requireHash: false));

    private static ArchiveEntryDto? FindCurrentEntry(ArchiveSession session, CacheEntrySnapshot expected)
    {
        if (string.IsNullOrWhiteSpace(expected.Path)
            || expected.Offset < 0
            || expected.StoredSize < 0
            || expected.OriginalSize < 0)
        {
            return null;
        }
        return session.Index.FindEntriesByPath(expected.Path, 128)
            .FirstOrDefault(candidate => EntryMatches(expected, candidate));
    }

    private static bool EntryMatches(CacheEntrySnapshot expected, ArchiveEntryDto current) =>
        string.Equals(expected.Path, current.Path, StringComparison.OrdinalIgnoreCase)
        && string.Equals(NormalizeFilePath(expected.SourcePamt), NormalizeFilePath(current.SourcePamt), StringComparison.Ordinal)
        && string.Equals(NormalizePazPath(expected.SourcePamt, expected.PazFile), ResolvePazPath(current), StringComparison.Ordinal)
        && expected.Offset == current.Offset
        && expected.StoredSize == current.StoredSize
        && expected.OriginalSize == current.OriginalSize
        && expected.Flags == current.Flags
        && expected.PazIndex == current.PazIndex;

    private static void AddDependency(Dictionary<string, ArchiveEntryDto> dependencies, ArchiveEntryDto entry) =>
        dependencies[CacheEntrySnapshot.FromEntry(entry).CanonicalIdentity] = entry;

    private static async Task<string> HashFileAsync(string path, CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete,
            128 * 1024,
            FileOptions.Asynchronous | FileOptions.SequentialScan);
        return Convert.ToHexString(await SHA256.HashDataAsync(stream, cancellationToken).ConfigureAwait(false))
            .ToLowerInvariant();
    }

    private static async Task<string> HashEntryRawAsync(
        ArchiveEntryDto entry,
        CancellationToken cancellationToken)
    {
        var pazPath = ResolvePazPath(entry);
        await using var stream = new FileStream(
            pazPath,
            FileMode.Open,
            FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete,
            128 * 1024,
            FileOptions.Asynchronous | FileOptions.RandomAccess);
        if (entry.Offset < 0
            || entry.StoredSize < 0
            || entry.Offset > stream.Length
            || entry.StoredSize > stream.Length - entry.Offset)
        {
            throw new InvalidDataException("A model-preview dependency range is outside its PAZ file.");
        }
        stream.Position = entry.Offset;
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = new byte[128 * 1024];
        var remaining = entry.StoredSize;
        while (remaining > 0)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var read = await stream.ReadAsync(
                buffer.AsMemory(0, checked((int)Math.Min(buffer.Length, remaining))),
                cancellationToken).ConfigureAwait(false);
            if (read == 0)
            {
                throw new EndOfStreamException("A model-preview dependency PAZ range was truncated.");
            }
            hash.AppendData(buffer.AsSpan(0, read));
            remaining -= read;
        }
        return Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
    }

    private static void AppendEntryIdentity(ICollection<string> fields, ArchiveEntryDto entry)
    {
        fields.Add(entry.Path.Replace('\\', '/').Trim('/').ToLowerInvariant());
        fields.Add(NormalizeFilePath(entry.SourcePamt));
        fields.Add(ResolvePazPath(entry));
        fields.Add(entry.Offset.ToString(System.Globalization.CultureInfo.InvariantCulture));
        fields.Add(entry.StoredSize.ToString(System.Globalization.CultureInfo.InvariantCulture));
        fields.Add(entry.OriginalSize.ToString(System.Globalization.CultureInfo.InvariantCulture));
        fields.Add(entry.Flags.ToString(System.Globalization.CultureInfo.InvariantCulture));
        fields.Add(entry.PazIndex.ToString(System.Globalization.CultureInfo.InvariantCulture));
    }

    private static string ResolvePazPath(ArchiveEntryDto entry) =>
        NormalizePazPath(entry.SourcePamt, entry.PazFile);

    private static string NormalizePazPath(string pamtPath, string pazPath)
    {
        if (Path.IsPathFullyQualified(pazPath))
        {
            return NormalizeFilePath(pazPath);
        }
        var pamtDirectory = Path.GetDirectoryName(Path.GetFullPath(pamtPath))
            ?? throw new InvalidDataException("Archive PAMT path has no containing directory.");
        return NormalizeFilePath(Path.Combine(pamtDirectory, pazPath));
    }

    private static string NormalizeFilePath(string path) =>
        Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar).ToLowerInvariant();

    private static int ReadInt32(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.TryGetInt32(out var result) ? result : -1;

    private static long ReadInt64(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.TryGetInt64(out var result) ? result : -1;

    private static string ReadString(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? string.Empty
            : string.Empty;
}

internal sealed record NativePreviewDependencyTrace(
    int Schema,
    IReadOnlyList<NativePreviewDependencyQuery> Queries,
    IReadOnlyList<CacheEntrySnapshot> Entries);

internal sealed record NativePreviewDependencyQuery(string Basename, int MaximumResults, string Scope);

internal sealed class NativeModelPreviewCacheManifest
{
    [JsonPropertyName("schema")]
    public int Schema { get; set; }

    [JsonPropertyName("version")]
    public string Version { get; set; } = string.Empty;

    [JsonPropertyName("cache_key")]
    public string CacheKey { get; set; } = string.Empty;

    [JsonPropertyName("source_session_fingerprint")]
    public string SourceSessionFingerprint { get; set; } = string.Empty;

    [JsonPropertyName("source_identity")]
    public string SourceIdentity { get; set; } = string.Empty;

    [JsonPropertyName("entry_path")]
    public string EntryPath { get; set; } = string.Empty;

    [JsonPropertyName("validation_mode")]
    public string ValidationMode { get; set; } = string.Empty;

    [JsonPropertyName("primary_pamt_sha256")]
    public string PrimaryPamtSha256 { get; set; } = string.Empty;

    [JsonPropertyName("dependencies")]
    public List<CacheEntrySnapshot> Dependencies { get; set; } = [];

    [JsonPropertyName("basename_queries")]
    public List<BasenameQuerySnapshot> BasenameQueries { get; set; } = [];
}

internal sealed class CacheEntrySnapshot
{
    [JsonPropertyName("path")]
    public string Path { get; set; } = string.Empty;

    [JsonPropertyName("source_pamt")]
    public string SourcePamt { get; set; } = string.Empty;

    [JsonPropertyName("paz_file")]
    public string PazFile { get; set; } = string.Empty;

    [JsonPropertyName("offset")]
    public long Offset { get; set; }

    [JsonPropertyName("stored_size")]
    public long StoredSize { get; set; }

    [JsonPropertyName("original_size")]
    public long OriginalSize { get; set; }

    [JsonPropertyName("flags")]
    public int Flags { get; set; }

    [JsonPropertyName("paz_index")]
    public int PazIndex { get; set; }

    [JsonPropertyName("raw_sha256")]
    public string RawSha256 { get; set; } = string.Empty;

    [JsonIgnore]
    public string CanonicalIdentity => string.Join(
        '|',
        Path.Replace('\\', '/').Trim('/').ToLowerInvariant(),
        System.IO.Path.GetFullPath(SourcePamt).ToLowerInvariant(),
        System.IO.Path.IsPathFullyQualified(PazFile)
            ? System.IO.Path.GetFullPath(PazFile).ToLowerInvariant()
            : System.IO.Path.GetFullPath(System.IO.Path.Combine(System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(SourcePamt))!, PazFile)).ToLowerInvariant(),
        Offset,
        StoredSize,
        OriginalSize,
        Flags,
        PazIndex);

    public static CacheEntrySnapshot FromEntry(ArchiveEntryDto entry) => new()
    {
        Path = entry.Path,
        SourcePamt = System.IO.Path.GetFullPath(entry.SourcePamt).ToLowerInvariant(),
        PazFile = System.IO.Path.IsPathFullyQualified(entry.PazFile)
            ? System.IO.Path.GetFullPath(entry.PazFile).ToLowerInvariant()
            : System.IO.Path.GetFullPath(System.IO.Path.Combine(System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(entry.SourcePamt))!, entry.PazFile)).ToLowerInvariant(),
        Offset = entry.Offset,
        StoredSize = entry.StoredSize,
        OriginalSize = entry.OriginalSize,
        Flags = entry.Flags,
        PazIndex = entry.PazIndex,
    };
}

internal sealed class BasenameQuerySnapshot
{
    [JsonPropertyName("basename")]
    public string Basename { get; set; } = string.Empty;

    [JsonPropertyName("maximum_results")]
    public int MaximumResults { get; set; }

    [JsonPropertyName("candidates")]
    public List<CacheEntrySnapshot> Candidates { get; set; } = [];
}

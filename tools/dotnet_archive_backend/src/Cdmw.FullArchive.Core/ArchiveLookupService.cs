using System.Collections.Concurrent;
using System.Text;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveLookupService(
    ArchiveSessionManager sessions,
    ArchiveCacheStore cache,
    NativeArchiveCore native)
{
    private const int FileVersion = 2;
    private const int MaximumPreviewCandidates = 4096;
    private const int MaximumPreviewLookupResults = MaximumPreviewCandidates + 1;
    private static readonly byte[] Magic = "CDMWLKP2"u8.ToArray();
    private readonly ConcurrentDictionary<string, Lazy<Task<ArchiveLookupIndex>>> _indexes =
        new(StringComparer.OrdinalIgnoreCase);

    public Task WarmAsync(
        string sessionId,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        var session = sessions.GetRequired(sessionId);
        cancellationToken.ThrowIfCancellationRequested();
        _ = session.DependencyIndex.RecordCount;
        return progress is null
            ? Task.CompletedTask
            : progress(new ProgressUpdate(
                session.DependencyIndex.RecordCount,
                session.DependencyIndex.RecordCount,
                "dependency_index_ready",
                "memory_mapped"));
    }

    public async Task<ArchiveLookupResult> ResolveAsync(
        ArchiveLookupRequest request,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(request.SessionId);
        var limit = Math.Clamp(request.Limit, 1, 4096);
        var ids = new HashSet<long>();
        var incomplete = false;
        switch (request.Kind)
        {
            case ArchiveLookupKind.EntryIds:
                foreach (var id in request.EntryIds ?? [])
                {
                    if (id >= 0 && id < session.Index.EntryCount)
                    {
                        ids.Add(id);
                    }
                }
                break;
            case ArchiveLookupKind.Identities:
                foreach (var identity in request.Identities ?? [])
                {
                    incomplete |= AddIdentityMatches(session.Index, identity, ids, cancellationToken);
                }
                break;
            case ArchiveLookupKind.ExactPaths:
                foreach (var value in request.Values ?? [])
                {
                    if (!string.IsNullOrWhiteSpace(value))
                    {
                        incomplete |= AddExactPathMatches(session.Index, value, ids, cancellationToken);
                    }
                }
                break;
            case ArchiveLookupKind.Basenames:
                foreach (var value in request.Values ?? [])
                {
                    if (!string.IsNullOrWhiteSpace(value))
                    {
                        incomplete |= AddDependencyMatches(
                            session.DependencyIndex.FindEntryIdsByBasename(
                                session.Index,
                                value,
                                MaximumPreviewLookupResults,
                                cancellationToken),
                            ids,
                            cancellationToken);
                    }
                }
                break;
            case ArchiveLookupKind.Extensions:
                var extensionIndex = await GetIndexAsync(session, cancellationToken, progress).ConfigureAwait(false);
                foreach (var value in request.Values ?? [])
                {
                    Add(extensionIndex.Extensions, NormalizeExtension(value), ids);
                }
                break;
            case ArchiveLookupKind.Roles:
                var roleIndex = await GetIndexAsync(session, cancellationToken, progress).ConfigureAwait(false);
                foreach (var role in request.Roles ?? [])
                {
                    Add(roleIndex.Roles, role.ToString(), ids);
                }
                break;
            default:
                throw new InvalidDataException("The archive lookup kind is not supported.");
        }

        if (!string.IsNullOrWhiteSpace(request.QueryId))
        {
            var compiled = session.GetRequiredQuery(request.QueryId);
            if (compiled.UsesIdentityOrder)
            {
                var directMatches = ids
                    .Where(entryId => entryId >= 0 && entryId < compiled.EntryCount)
                    .Order()
                    .ToArray();
                var directSelected = directMatches.Take(limit).ToArray();
                return new ArchiveLookupResult(
                    session.Id,
                    directSelected.Select(session.ReadEntry).ToArray(),
                    directMatches.LongLength,
                    incomplete || directMatches.LongLength > limit,
                    directSelected);
            }
            var matches = new List<(long Row, long EntryId)>();
            for (var row = 0L; row < compiled.EntryCount; row++)
            {
                if ((row & 0x1FFF) == 0)
                {
                    cancellationToken.ThrowIfCancellationRequested();
                }
                var entryId = compiled.EntryIdAt(row);
                if (ids.Contains(entryId))
                {
                    matches.Add((row, entryId));
                }
            }
            var selected = matches.Take(limit).ToArray();
            return new ArchiveLookupResult(
                session.Id,
                selected.Select(item => session.ReadEntry(item.EntryId)).ToArray(),
                matches.Count,
                incomplete || matches.Count > limit,
                selected.Select(static item => item.Row).ToArray());
        }

        var ordered = ids.Order().Take(limit + 1).ToArray();
        return new ArchiveLookupResult(
            session.Id,
            ordered.Take(limit).Select(session.ReadEntry).ToArray(),
            ids.Count,
            incomplete || ids.Count > limit,
            []);
    }

    public async Task<ArchiveAssociationResult> FindAssociationCandidatesAsync(
        ArchiveAssociationRequest request,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(request.SessionId);
        var selected = session.ReadEntry(request.EntryId);
        var previewResolution = request.Purpose == ArchiveAssociationPurpose.Preview
            ? await ResolvePreviewAssociationEntryIdsAsync(
                request.SessionId,
                request.EntryId,
                cancellationToken,
                progress).ConfigureAwait(false)
            : null;
        var ids = previewResolution?.EntryIds ?? await ResolveAssociationEntryIdsAsync(
                request.SessionId,
                request.EntryId,
                cancellationToken,
                progress).ConfigureAwait(false);
        var limit = Math.Clamp(request.Limit, 1, 4096);
        var ranked = ids
            .Select(session.ReadEntry)
            .OrderByDescending(entry => AssociationScore(selected, entry))
            .ThenBy(static entry => entry.Path, StringComparer.OrdinalIgnoreCase)
            .Take(limit + 1)
            .ToArray();
        return new ArchiveAssociationResult(
            session.Id,
            selected.EntryId,
            ranked.Take(limit).ToArray(),
            ids.Count,
            previewResolution?.Incomplete == true || ids.Count > limit);
    }

    internal async Task<IReadOnlyList<long>> ResolveAssociationEntryIdsAsync(
        string sessionId,
        long entryId,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        var session = sessions.GetRequired(sessionId);
        var selected = session.ReadEntry(entryId);
        var index = await GetIndexAsync(session, cancellationToken, progress).ConfigureAwait(false);
        var ids = new HashSet<long>();
        AddCancellable(index.Stems, Path.GetFileNameWithoutExtension(selected.Path), ids, cancellationToken);
        var folder = NormalizePath(Path.GetDirectoryName(selected.Path.Replace('/', Path.DirectorySeparatorChar)) ?? string.Empty);
        AddCancellable(index.Folders, folder, ids, cancellationToken);
        ids.Remove(selected.EntryId);
        cancellationToken.ThrowIfCancellationRequested();
        return ids.Order().ToArray();
    }

    private async Task<PreviewAssociationResolution> ResolvePreviewAssociationEntryIdsAsync(
        string sessionId,
        long entryId,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        var session = sessions.GetRequired(sessionId);
        var selected = session.ReadEntry(entryId);
        var ids = new HashSet<long>();
        var incomplete = AddDependencyMatches(
            session.DependencyIndex.FindEntryIdsByStem(
                session.Index,
                Path.GetFileNameWithoutExtension(selected.Path),
                MaximumPreviewLookupResults,
                cancellationToken),
            ids,
            cancellationToken);
        incomplete |= AddPreviewCompanionPaths(selected, session.Index, ids, cancellationToken);

        var allScanIds = ids
            .Append(selected.EntryId)
            .Distinct()
            .Order()
            .ToArray();
        incomplete |= allScanIds.Length > 512;
        var scanIds = allScanIds.Take(512).ToArray();
        for (var scanIndex = 0; scanIndex < scanIds.Length; scanIndex++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (ids.Count >= MaximumPreviewLookupResults)
            {
                incomplete = true;
                break;
            }
            var entry = session.ReadEntry(scanIds[scanIndex]);
            var shouldScan = ShouldScanPreviewReferences(entry, selected.EntryId);
            if (!shouldScan)
            {
                continue;
            }
            var maximumBytes = entry.EntryId == selected.EntryId
                ? 512L * 1024 * 1024
                : 64L * 1024 * 1024;
            if (entry.OriginalSize is <= 0 || entry.OriginalSize > maximumBytes)
            {
                incomplete = true;
                continue;
            }
            if (progress is not null)
            {
                await progress(new ProgressUpdate(
                    scanIndex,
                    scanIds.Length,
                    "preview_association_scan",
                    entry.Path)).ConfigureAwait(false);
            }
            var decoded = await Task.Run(() => native.Decode(entry), cancellationToken).ConfigureAwait(false);
            var extracted = ArchivePreviewReferenceScanner.Extract(decoded.Bytes, cancellationToken);
            incomplete |= extracted.Truncated;
            foreach (var token in extracted.Tokens)
            {
                if (ids.Count >= MaximumPreviewLookupResults)
                {
                    incomplete = true;
                    break;
                }
                incomplete |= AddPreviewReference(session, token, ids, cancellationToken);
            }
        }
        ids.Remove(selected.EntryId);
        cancellationToken.ThrowIfCancellationRequested();
        return new PreviewAssociationResolution(ids.Order().ToArray(), incomplete);
    }

    public Task<ArchiveFacetsResult> FacetsAsync(
        string sessionId,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        var session = sessions.GetRequired(sessionId);
        cancellationToken.ThrowIfCancellationRequested();
        return Task.FromResult(session.DependencyIndex.CreateFacets(session.Id));
    }

    private Task<ArchiveLookupIndex> GetIndexAsync(
        ArchiveSession session,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        var lazy = _indexes.GetOrAdd(
            session.GenerationPath,
            _ => new Lazy<Task<ArchiveLookupIndex>>(
                () => LoadOrBuildAsync(session, cancellationToken, progress),
                LazyThreadSafetyMode.ExecutionAndPublication));
        return AwaitIndexAsync(session.GenerationPath, lazy, cancellationToken);
    }

    private async Task<ArchiveLookupIndex> LoadOrBuildAsync(
        ArchiveSession session,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        var path = Path.Combine(session.GenerationPath, "lookups.bin");
        if (File.Exists(path))
        {
            try
            {
                return await Task.Run(() => Load(path, session.Index.EntryCount), cancellationToken).ConfigureAwait(false);
            }
            catch (Exception exception) when (exception is IOException or InvalidDataException or UnauthorizedAccessException)
            {
                TryDelete(path);
            }
        }

        var built = await Task.Run(
            () => Build(session, cancellationToken, progress),
            CancellationToken.None).ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();
        await WriteAsync(path, session.Index.EntryCount, built, cancellationToken).ConfigureAwait(false);
        await cache.UpdateSecondaryStateAsync(session.GenerationPath, lookupsReady: true, namesReady: null, cancellationToken).ConfigureAwait(false);
        return built;
    }

    private static ArchiveLookupIndex Build(
        ArchiveSession session,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        var index = new ArchiveLookupIndex();
        var total = session.Index.EntryCount;
        Publish(progress, new ProgressUpdate(0, total, "lookups_build"));
        for (long entryId = 0; entryId < total; entryId++)
        {
            if ((entryId & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                Publish(progress, new ProgressUpdate(entryId, total, "lookups_build"));
            }
            var entry = session.ReadEntry(entryId);
            Add(index.Paths, NormalizePath(entry.Path), entryId);
            Add(index.Basenames, entry.Name, entryId);
            Add(index.Stems, Path.GetFileNameWithoutExtension(entry.Path), entryId);
            Add(index.Extensions, entry.Extension, entryId);
            Add(index.Roles, entry.Role.ToString(), entryId);
            Add(index.Packages, entry.Package, entryId);
            Add(index.Categories, entry.Category, entryId);
            var folder = NormalizePath(Path.GetDirectoryName(entry.Path.Replace('/', Path.DirectorySeparatorChar)) ?? string.Empty);
            Add(index.Folders, folder, entryId);
            Add(index.Identities, IdentityKey(entry.Identity), entryId);
        }
        Publish(progress, new ProgressUpdate(total, total, "lookups_complete"));
        return index;
    }

    private static async Task WriteAsync(
        string destination,
        long entryCount,
        ArchiveLookupIndex index,
        CancellationToken cancellationToken)
    {
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
                128 * 1024,
                FileOptions.Asynchronous | FileOptions.WriteThrough))
            using (var writer = new BinaryWriter(stream, Encoding.UTF8, leaveOpen: true))
            {
                writer.Write(Magic);
                writer.Write(FileVersion);
                writer.Write(entryCount);
                foreach (var map in index.AllMaps)
                {
                    WriteMap(writer, map);
                }
                writer.Flush();
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
                stream.Flush(flushToDisk: true);
            }
            cancellationToken.ThrowIfCancellationRequested();
            File.Move(staging, destination, overwrite: true);
        }
        finally
        {
            TryDelete(staging);
        }
    }

    private static ArchiveLookupIndex Load(string path, long expectedEntryCount)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        using var reader = new BinaryReader(stream, Encoding.UTF8, leaveOpen: false);
        if (!reader.ReadBytes(Magic.Length).AsSpan().SequenceEqual(Magic) ||
            reader.ReadInt32() != FileVersion ||
            reader.ReadInt64() != expectedEntryCount)
        {
            throw new InvalidDataException("Archive lookup index header is invalid.");
        }
        var index = new ArchiveLookupIndex();
        foreach (var map in index.AllMaps)
        {
            ReadMap(reader, map, expectedEntryCount);
        }
        if (stream.Position != stream.Length)
        {
            throw new InvalidDataException("Archive lookup index has trailing data.");
        }
        return index;
    }

    private static void WriteMap(BinaryWriter writer, Dictionary<string, List<long>> map)
    {
        writer.Write(map.Count);
        foreach (var pair in map.OrderBy(static pair => pair.Key, StringComparer.OrdinalIgnoreCase))
        {
            writer.Write(pair.Key);
            writer.Write(pair.Value.Count);
            foreach (var entryId in pair.Value)
            {
                writer.Write(entryId);
            }
        }
    }

    private static void ReadMap(BinaryReader reader, Dictionary<string, List<long>> map, long entryCount)
    {
        var keyCount = reader.ReadInt32();
        if (keyCount < 0 || keyCount > entryCount + 1)
        {
            throw new InvalidDataException("Archive lookup key count is invalid.");
        }
        for (var keyIndex = 0; keyIndex < keyCount; keyIndex++)
        {
            var key = reader.ReadString();
            var count = reader.ReadInt32();
            if (count < 0 || count > entryCount)
            {
                throw new InvalidDataException("Archive lookup posting count is invalid.");
            }
            var postings = new List<long>(count);
            for (var index = 0; index < count; index++)
            {
                var entryId = reader.ReadInt64();
                if (entryId < 0 || entryId >= entryCount)
                {
                    throw new InvalidDataException("Archive lookup posting is outside the index.");
                }
                postings.Add(entryId);
            }
            map.Add(key, postings);
        }
    }

    private static bool AddPreviewCompanionPaths(
        ArchiveEntryDto selected,
        ArchiveIndex index,
        HashSet<long> ids,
        CancellationToken cancellationToken)
    {
        var incomplete = false;
        var path = NormalizePath(selected.Path);
        var candidates = new List<string>();
        if (path.EndsWith(".pam", StringComparison.OrdinalIgnoreCase))
        {
            var stem = path[..^4];
            candidates.Add(stem + ".pamlod");
            if (stem.EndsWith("_breakable", StringComparison.OrdinalIgnoreCase))
            {
                candidates.Add(stem[..^10] + ".pamlod");
            }
        }
        else if (path.EndsWith(".pamlod", StringComparison.OrdinalIgnoreCase))
        {
            candidates.Add(path[..^7] + ".pam");
        }
        foreach (var candidate in candidates)
        {
            incomplete |= AddExactPathMatches(index, candidate, ids, cancellationToken);
        }
        return incomplete;
    }

    private static bool ShouldScanPreviewReferences(ArchiveEntryDto entry, long selectedEntryId)
    {
        if (entry.EntryId == selectedEntryId)
        {
            return true;
        }
        return entry.Extension is
            ".xml" or ".pac_xml" or ".pam_xml" or ".pamlod_xml" or
            ".material" or ".meshinfo" or ".prefab" or ".prefabdata_xml" or
            ".pappt" or ".pamhc" or ".seqmt";
    }

    private static bool AddPreviewReference(
        ArchiveSession session,
        string token,
        HashSet<long> ids,
        CancellationToken cancellationToken)
    {
        var incomplete = false;
        var normalized = NormalizePath(token);
        incomplete |= AddExactPathMatches(session.Index, normalized, ids, cancellationToken);
        var separatorPath = normalized.Replace('/', Path.DirectorySeparatorChar);
        incomplete |= AddDependencyMatches(
            session.DependencyIndex.FindEntryIdsByBasename(
                session.Index,
                Path.GetFileName(separatorPath),
                MaximumPreviewLookupResults,
                cancellationToken),
            ids,
            cancellationToken);

        var slash = normalized.IndexOf('/');
        if (slash <= 0)
        {
            return incomplete;
        }
        var firstSegment = normalized[..slash];
        if (firstSegment.All(char.IsDigit) || firstSegment.StartsWith("dmm", StringComparison.OrdinalIgnoreCase))
        {
            incomplete |= AddExactPathMatches(
                session.Index,
                normalized[(slash + 1)..],
                ids,
                cancellationToken);
        }
        return incomplete;
    }

    private static bool AddExactPathMatches(
        ArchiveIndex index,
        string path,
        HashSet<long> destination,
        CancellationToken cancellationToken)
    {
        var matches = index.FindEntriesByPath(path, MaximumPreviewLookupResults + 1);
        var incomplete = matches.Count > MaximumPreviewLookupResults;
        foreach (var entry in matches.Take(MaximumPreviewLookupResults))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!destination.Contains(entry.EntryId) && destination.Count >= MaximumPreviewLookupResults)
            {
                incomplete = true;
                break;
            }
            destination.Add(entry.EntryId);
        }
        return incomplete;
    }

    private static bool AddIdentityMatches(
        ArchiveIndex index,
        ArchiveDurableIdentity identity,
        HashSet<long> destination,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(identity.NormalizedPath))
        {
            return false;
        }
        var matches = index.FindEntriesByPath(identity.NormalizedPath, MaximumPreviewLookupResults + 1);
        var incomplete = matches.Count > MaximumPreviewLookupResults;
        var identityKey = IdentityKey(identity);
        foreach (var entry in matches.Take(MaximumPreviewLookupResults))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!StringComparer.OrdinalIgnoreCase.Equals(IdentityKey(entry.Identity), identityKey))
            {
                continue;
            }
            if (!destination.Contains(entry.EntryId) && destination.Count >= MaximumPreviewLookupResults)
            {
                return true;
            }
            destination.Add(entry.EntryId);
        }
        return incomplete;
    }

    private static bool AddDependencyMatches(
        ArchiveDependencyLookupResult matches,
        HashSet<long> destination,
        CancellationToken cancellationToken)
    {
        var incomplete = matches.Truncated;
        for (var index = 0; index < matches.EntryIds.Count; index++)
        {
            if ((index & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
            }
            var entryId = matches.EntryIds[index];
            if (!destination.Contains(entryId) && destination.Count >= MaximumPreviewLookupResults)
            {
                incomplete = true;
                break;
            }
            destination.Add(entryId);
        }
        return incomplete;
    }

    private static int AssociationScore(ArchiveEntryDto selected, ArchiveEntryDto candidate)
    {
        var score = 0;
        if (Path.GetFileNameWithoutExtension(selected.Path)
            .Equals(Path.GetFileNameWithoutExtension(candidate.Path), StringComparison.OrdinalIgnoreCase))
        {
            score += 100;
        }
        if (Path.GetDirectoryName(selected.Path.Replace('/', Path.DirectorySeparatorChar))
            ?.Equals(
                Path.GetDirectoryName(candidate.Path.Replace('/', Path.DirectorySeparatorChar)),
                StringComparison.OrdinalIgnoreCase) == true)
        {
            score += 25;
        }
        if (selected.Package.Equals(candidate.Package, StringComparison.OrdinalIgnoreCase))
        {
            score += 10;
        }
        return score;
    }

    private static string IdentityKey(ArchiveDurableIdentity identity) =>
        $"{NormalizePath(identity.NormalizedPath)}\u001f{NormalizePath(identity.SourcePamt)}\u001f{identity.PazIndex}\u001f{identity.ArchiveOffset}";

    private static string NormalizePath(string value) => value.Replace('\\', '/').Trim('/').ToLowerInvariant();

    private static string NormalizeExtension(string value)
    {
        var normalized = value.Trim().ToLowerInvariant();
        return normalized.StartsWith('.') ? normalized : "." + normalized;
    }

    private static void Add(Dictionary<string, List<long>> map, string key, long entryId)
    {
        if (!map.TryGetValue(key, out var postings))
        {
            postings = [];
            map[key] = postings;
        }
        postings.Add(entryId);
    }

    private static void Add(Dictionary<string, List<long>> map, string key, HashSet<long> destination)
    {
        if (map.TryGetValue(key, out var postings))
        {
            destination.UnionWith(postings);
        }
    }

    private static void AddCancellable(
        Dictionary<string, List<long>> map,
        string key,
        HashSet<long> destination,
        CancellationToken cancellationToken)
    {
        if (!map.TryGetValue(key, out var postings))
        {
            return;
        }
        for (var index = 0; index < postings.Count; index++)
        {
            if ((index & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
            }
            destination.Add(postings[index]);
        }
    }

    private async Task<ArchiveLookupIndex> AwaitIndexAsync(
        string generationPath,
        Lazy<Task<ArchiveLookupIndex>> lazy,
        CancellationToken cancellationToken)
    {
        try
        {
            return await lazy.Value.WaitAsync(cancellationToken).ConfigureAwait(false);
        }
        catch
        {
            if (lazy.IsValueCreated && (lazy.Value.IsCanceled || lazy.Value.IsFaulted))
            {
                if (_indexes.TryGetValue(generationPath, out var current) && ReferenceEquals(current, lazy))
                {
                    _indexes.TryRemove(generationPath, out _);
                }
            }
            throw;
        }
    }

    private static void Publish(Func<ProgressUpdate, Task>? progress, ProgressUpdate update) =>
        progress?.Invoke(update).GetAwaiter().GetResult();

    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // A later cache prune can remove a stale secondary index.
        }
    }

    private sealed record PreviewAssociationResolution(
        IReadOnlyList<long> EntryIds,
        bool Incomplete);

    private sealed class ArchiveLookupIndex
    {
        public Dictionary<string, List<long>> Paths { get; } = new(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, List<long>> Basenames { get; } = new(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, List<long>> Stems { get; } = new(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, List<long>> Extensions { get; } = new(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, List<long>> Roles { get; } = new(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, List<long>> Packages { get; } = new(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, List<long>> Folders { get; } = new(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, List<long>> Categories { get; } = new(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, List<long>> Identities { get; } = new(StringComparer.OrdinalIgnoreCase);

        public IEnumerable<Dictionary<string, List<long>>> AllMaps
        {
            get
            {
                yield return Paths;
                yield return Basenames;
                yield return Stems;
                yield return Extensions;
                yield return Roles;
                yield return Packages;
                yield return Folders;
                yield return Categories;
                yield return Identities;
            }
        }
    }
}

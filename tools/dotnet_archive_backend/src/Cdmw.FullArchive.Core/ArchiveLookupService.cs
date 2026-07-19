using System.Collections.Concurrent;
using System.Text;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveLookupService(
    ArchiveSessionManager sessions,
    ArchiveCacheStore cache)
{
    private const int FileVersion = 2;
    private static readonly byte[] Magic = "CDMWLKP2"u8.ToArray();
    private readonly ConcurrentDictionary<string, Lazy<Task<ArchiveLookupIndex>>> _indexes =
        new(StringComparer.OrdinalIgnoreCase);

    public async Task WarmAsync(
        string sessionId,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        _ = await GetIndexAsync(sessions.GetRequired(sessionId), cancellationToken, progress).ConfigureAwait(false);
    }

    public async Task<ArchiveLookupResult> ResolveAsync(
        ArchiveLookupRequest request,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(request.SessionId);
        var limit = Math.Clamp(request.Limit, 1, 4096);
        var index = await GetIndexAsync(session, cancellationToken, progress).ConfigureAwait(false);
        var ids = new HashSet<long>();
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
                    Add(index.Identities, IdentityKey(identity), ids);
                }
                break;
            case ArchiveLookupKind.ExactPaths:
                foreach (var value in request.Values ?? [])
                {
                    Add(index.Paths, NormalizePath(value), ids);
                }
                break;
            case ArchiveLookupKind.Basenames:
                foreach (var value in request.Values ?? [])
                {
                    Add(index.Basenames, Path.GetFileName(value), ids);
                }
                break;
            case ArchiveLookupKind.Extensions:
                foreach (var value in request.Values ?? [])
                {
                    Add(index.Extensions, NormalizeExtension(value), ids);
                }
                break;
            case ArchiveLookupKind.Roles:
                foreach (var role in request.Roles ?? [])
                {
                    Add(index.Roles, role.ToString(), ids);
                }
                break;
            default:
                throw new InvalidDataException("The archive lookup kind is not supported.");
        }

        if (!string.IsNullOrWhiteSpace(request.QueryId))
        {
            var compiled = session.GetRequiredQuery(request.QueryId);
            var matches = new List<(long Row, long EntryId)>();
            for (var row = 0; row < compiled.EntryIds.LongLength; row++)
            {
                if ((row & 0x1FFF) == 0)
                {
                    cancellationToken.ThrowIfCancellationRequested();
                }
                var entryId = compiled.EntryIds[row];
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
                matches.Count > limit,
                selected.Select(static item => item.Row).ToArray());
        }

        var ordered = ids.Order().Take(limit + 1).ToArray();
        return new ArchiveLookupResult(
            session.Id,
            ordered.Take(limit).Select(session.ReadEntry).ToArray(),
            ids.Count,
            ids.Count > limit,
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
        var index = await GetIndexAsync(session, cancellationToken, progress).ConfigureAwait(false);
        var ids = new HashSet<long>();
        Add(index.Stems, Path.GetFileNameWithoutExtension(selected.Path), ids);
        var folder = NormalizePath(Path.GetDirectoryName(selected.Path.Replace('/', Path.DirectorySeparatorChar)) ?? string.Empty);
        Add(index.Folders, folder, ids);
        ids.Remove(selected.EntryId);
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
            ids.Count > limit);
    }

    public async Task<ArchiveFacetsResult> FacetsAsync(
        string sessionId,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        var session = sessions.GetRequired(sessionId);
        var index = await GetIndexAsync(session, cancellationToken, progress).ConfigureAwait(false);
        return new ArchiveFacetsResult(
            session.Id,
            ToFacets(index.Extensions),
            ToFacets(index.Packages),
            ToFacets(index.Roles),
            ToFacets(index.Categories));
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

    private static IReadOnlyList<ArchiveFacet> ToFacets(Dictionary<string, List<long>> map) =>
        map.Select(static pair => new ArchiveFacet(pair.Key, pair.Key, pair.Value.Count))
            .OrderByDescending(static facet => facet.Count)
            .ThenBy(static facet => facet.Key, StringComparer.OrdinalIgnoreCase)
            .ToArray();

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

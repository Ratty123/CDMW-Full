using System.Text.RegularExpressions;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class ArchiveQueryService(ArchiveSessionManager sessions)
{
    private const int MaximumScopedEntryIds = 1024;

    public Task<ArchivePageResult> QueryAsync(
        ArchiveQuerySpec query,
        long generation,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);
        ValidateScopedEntryIds(query.EntryIds);
        var session = sessions.GetRequired(query.SessionId);
        var normalized = query with
        {
            PageStart = Math.Max(0, query.PageStart),
            PageSize = Math.Clamp(query.PageSize, 1, 512),
        };
        return Task.Run(() => Query(session, normalized, generation, cancellationToken), cancellationToken);
    }

    public IEnumerable<ArchiveEntryDto> EnumerateMatchingEntries(
        ArchiveSession session,
        ArchiveQuerySpec query,
        CancellationToken cancellationToken)
    {
        ValidateScopedEntryIds(query.EntryIds);
        if (query.EntryIds is not null)
        {
            foreach (var entryId in query.EntryIds.Distinct().Order())
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (entryId < 0 || entryId >= session.Index.EntryCount)
                {
                    continue;
                }
                var entry = session.Index.ReadEntry(entryId);
                if (Matches(entry, query, entryIds: null)) yield return entry;
            }
            yield break;
        }
        for (long entryId = 0; entryId < session.Index.EntryCount; entryId++)
        {
            if ((entryId & 0xFF) == 0) cancellationToken.ThrowIfCancellationRequested();
            var entry = session.Index.ReadEntry(entryId);
            if (Matches(entry, query, entryIds: null)) yield return entry;
        }
    }

    private ArchivePageResult Query(
        ArchiveSession session,
        ArchiveQuerySpec query,
        long generation,
        CancellationToken cancellationToken)
    {
        if (IsDirectPathPage(query))
        {
            return ReadDirectPathPage(session, query, generation, cancellationToken);
        }
        if (query.EntryIds is not null)
        {
            return ReadEntryIdScopePage(session, query, generation, cancellationToken);
        }

        var page = new List<ArchiveEntryDto>(query.PageSize);
        var candidateComparer = query.SortField == ArchiveSortField.Path
            ? null
            : CreateComparer(query.SortField, query.SortDescending);
        var candidateLimit = checked(query.PageStart + query.PageSize);
        var candidates = candidateComparer is null
            ? null
            : new SortedSet<ArchiveEntryDto>(candidateComparer);
        var needsNameDataDuringScan = query.SortField is ArchiveSortField.KnownName or ArchiveSortField.NameEvidence
            || !string.IsNullOrWhiteSpace(query.PathText);
        var folders = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var categories = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        long total = 0;
        var descendingPath = query.SortField == ArchiveSortField.Path && query.SortDescending;
        for (long position = 0; position < session.Index.EntryCount; position++)
        {
            if ((position & 0xFF) == 0) cancellationToken.ThrowIfCancellationRequested();
            var entryId = descendingPath ? session.Index.EntryCount - position - 1 : position;
            var entry = session.Index.ReadEntry(entryId);
            if (needsNameDataDuringScan)
            {
                entry = session.EnrichEntry(entry);
            }
            if (!Matches(entry, query, entryIds: null)) continue;
            total++;
            var folder = Path.GetDirectoryName(entry.Path.Replace('/', Path.DirectorySeparatorChar))?.Replace('\\', '/');
            if (!string.IsNullOrEmpty(folder) && folders.Count < 10_000) folders.Add(folder);
            var category = entry.Role.ToString();
            categories[category] = categories.GetValueOrDefault(category) + 1;
            if (candidates is not null)
            {
                if (candidates.Count < candidateLimit)
                {
                    candidates.Add(entry);
                }
                else if (candidates.Max is { } worst && candidateComparer!.Compare(entry, worst) < 0)
                {
                    candidates.Remove(worst);
                    candidates.Add(entry);
                }
            }
            else if (total > query.PageStart && page.Count < query.PageSize)
            {
                page.Add(entry);
            }
        }

        if (candidates is not null)
        {
            page.AddRange(candidates.Skip(query.PageStart).Take(query.PageSize));
        }
        for (var index = 0; index < page.Count; index++)
        {
            page[index] = session.EnrichEntry(page[index]);
        }
        session.StoreQuery(query, generation, total);
        return new ArchivePageResult(
            session.Id,
            generation,
            total,
            query.PageStart,
            page,
            folders.Order(StringComparer.OrdinalIgnoreCase).ToArray(),
            categories);
    }

    private static ArchivePageResult ReadEntryIdScopePage(
        ArchiveSession session,
        ArchiveQuerySpec query,
        long generation,
        CancellationToken cancellationToken)
    {
        var matches = new List<ArchiveEntryDto>(query.EntryIds!.Count);
        var folders = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var categories = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        foreach (var entryId in query.EntryIds.Distinct())
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (entryId < 0 || entryId >= session.Index.EntryCount)
            {
                continue;
            }
            var entry = session.EnrichEntry(session.Index.ReadEntry(entryId));
            if (!Matches(entry, query, entryIds: null))
            {
                continue;
            }
            matches.Add(entry);
            var folder = Path.GetDirectoryName(entry.Path.Replace('/', Path.DirectorySeparatorChar))?.Replace('\\', '/');
            if (!string.IsNullOrEmpty(folder) && folders.Count < 10_000) folders.Add(folder);
            var category = entry.Role.ToString();
            categories[category] = categories.GetValueOrDefault(category) + 1;
        }

        matches.Sort(CreateComparer(query.SortField, query.SortDescending));
        var page = matches.Skip(query.PageStart).Take(query.PageSize).ToArray();
        session.StoreQuery(query, generation, matches.Count);
        return new ArchivePageResult(
            session.Id,
            generation,
            matches.Count,
            query.PageStart,
            page,
            folders.Order(StringComparer.OrdinalIgnoreCase).ToArray(),
            categories);
    }

    private static ArchivePageResult ReadDirectPathPage(
        ArchiveSession session,
        ArchiveQuerySpec query,
        long generation,
        CancellationToken cancellationToken)
    {
        var page = new List<ArchiveEntryDto>(query.PageSize);
        var total = session.Index.EntryCount;
        var available = Math.Max(0L, total - query.PageStart);
        var count = (int)Math.Min(query.PageSize, available);
        for (var offset = 0; offset < count; offset++)
        {
            if ((offset & 0xFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
            }

            var ascendingId = (long)query.PageStart + offset;
            var entryId = query.SortDescending ? total - ascendingId - 1 : ascendingId;
            page.Add(session.EnrichEntry(session.Index.ReadEntry(entryId)));
        }

        session.StoreQuery(query, generation, total);
        return new ArchivePageResult(
            session.Id,
            generation,
            total,
            query.PageStart,
            page,
            [],
            new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase));
    }

    private static bool IsDirectPathPage(ArchiveQuerySpec query) =>
        query.ViewMode == ArchiveViewMode.Flat &&
        query.SortField == ArchiveSortField.Path &&
        string.IsNullOrWhiteSpace(query.PathText) &&
        query.Extensions is not { Count: > 0 } &&
        string.IsNullOrWhiteSpace(query.Package) &&
        string.IsNullOrWhiteSpace(query.Folder) &&
        query.Roles is not { Count: > 0 } &&
        query.MinimumSize is null &&
        !query.PreviewableOnly &&
        query.EntryIds is null;

    private static bool Matches(ArchiveEntryDto entry, ArchiveQuerySpec query, IReadOnlySet<long>? entryIds)
    {
        if (entryIds is not null && !entryIds.Contains(entry.EntryId)) return false;
        if (!MatchesPath(entry, query.PathText)) return false;
        if (query.Extensions is { Count: > 0 } && !query.Extensions.Any(value => MatchesExtension(entry.Extension, value))) return false;
        if (!string.IsNullOrWhiteSpace(query.Package) && !entry.Package.Contains(query.Package, StringComparison.OrdinalIgnoreCase)) return false;
        if (!string.IsNullOrWhiteSpace(query.Folder) && !entry.Path.StartsWith(query.Folder.Trim().Replace('\\', '/').Trim('/') + "/", StringComparison.OrdinalIgnoreCase)) return false;
        if (query.Roles is { Count: > 0 } && !query.Roles.Contains(entry.Role)) return false;
        if (query.MinimumSize is { } minimum && entry.OriginalSize < minimum) return false;
        return !query.PreviewableOnly || entry.IsPreviewable;
    }

    private static void ValidateScopedEntryIds(IReadOnlyList<long>? entryIds)
    {
        if (entryIds is { Count: > MaximumScopedEntryIds })
        {
            throw new InvalidDataException($"An archive query scope may contain at most {MaximumScopedEntryIds} entry IDs.");
        }
    }

    private static bool MatchesPath(ArchiveEntryDto entry, string? filter)
    {
        if (string.IsNullOrWhiteSpace(filter)) return true;
        var text = filter.Trim();
        if (!text.ContainsAny(['*', '?', '[']))
        {
            return entry.Path.Contains(text, StringComparison.OrdinalIgnoreCase)
                || entry.Name.Contains(text, StringComparison.OrdinalIgnoreCase)
                || entry.KnownName.Contains(text, StringComparison.OrdinalIgnoreCase)
                || entry.NameEvidence.Contains(text, StringComparison.OrdinalIgnoreCase);
        }
        var pattern = "^" + Regex.Escape(text).Replace("\\*", ".*").Replace("\\?", ".") + "$";
        return Regex.IsMatch(entry.Path, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250))
            || Regex.IsMatch(entry.Name, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250))
            || Regex.IsMatch(entry.KnownName, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250))
            || Regex.IsMatch(entry.NameEvidence, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250));
    }

    private static bool MatchesExtension(string extension, string candidate)
    {
        var normalized = candidate.Trim().ToLowerInvariant();
        if (normalized is "*" or ".*" or "all") return true;
        if (!normalized.StartsWith('.')) normalized = "." + normalized;
        return extension.Equals(normalized, StringComparison.OrdinalIgnoreCase);
    }

    private static IComparer<ArchiveEntryDto> CreateComparer(ArchiveSortField field, bool descending)
    {
        var comparer = Comparer<ArchiveEntryDto>.Create((left, right) =>
        {
            var result = field switch
            {
                ArchiveSortField.Name => StringComparer.OrdinalIgnoreCase.Compare(left.Name, right.Name),
                ArchiveSortField.KnownName => StringComparer.OrdinalIgnoreCase.Compare(left.KnownName, right.KnownName),
                ArchiveSortField.NameEvidence => StringComparer.OrdinalIgnoreCase.Compare(left.NameEvidence, right.NameEvidence),
                ArchiveSortField.Extension => StringComparer.OrdinalIgnoreCase.Compare(left.Extension, right.Extension),
                ArchiveSortField.Package => StringComparer.OrdinalIgnoreCase.Compare(left.Package, right.Package),
                ArchiveSortField.OriginalSize => left.OriginalSize.CompareTo(right.OriginalSize),
                ArchiveSortField.StoredSize => left.StoredSize.CompareTo(right.StoredSize),
                ArchiveSortField.Compression => left.CompressionType != right.CompressionType
                    ? left.CompressionType.CompareTo(right.CompressionType)
                    : left.StoredSize.CompareTo(right.StoredSize),
                ArchiveSortField.Role => left.Role.CompareTo(right.Role),
                ArchiveSortField.FileType => left.FileType.CompareTo(right.FileType),
                ArchiveSortField.TextureUsage => left.TextureUsage.CompareTo(right.TextureUsage),
                _ => StringComparer.OrdinalIgnoreCase.Compare(left.Path, right.Path),
            };
            return result != 0 ? result : left.EntryId.CompareTo(right.EntryId);
        });
        return descending ? Comparer<ArchiveEntryDto>.Create((left, right) => comparer.Compare(right, left)) : comparer;
    }
}

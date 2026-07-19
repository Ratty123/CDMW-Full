using System.Text.RegularExpressions;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveQueryService(ArchiveSessionManager sessions)
{
    public Task<ArchiveQueryHandle> CreateAsync(
        ArchiveQuery query,
        long generation,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        ArgumentNullException.ThrowIfNull(query);
        var session = sessions.GetRequired(query.SessionId);
        return Task.Run(
            () => Compile(session, query, generation, cancellationToken, progress),
            CancellationToken.None);
    }

    public ArchivePage FetchPage(string sessionId, FetchPageRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(sessionId);
        var compiled = session.GetRequiredQuery(request.QueryId);
        var pageStart = Math.Max(0, request.PageStart);
        var pageSize = Math.Clamp(request.PageSize, 1, WorkerProtocol.MaximumPageSize);
        var available = Math.Max(0L, compiled.EntryIds.LongLength - pageStart);
        var count = (int)Math.Min(pageSize, available);
        var rows = new ArchiveEntryDto[count];
        for (var index = 0; index < count; index++)
        {
            rows[index] = session.ReadEntry(compiled.EntryIds[pageStart + index]);
        }
        return new ArchivePage(
            session.Id,
            compiled.QueryId,
            compiled.Generation,
            compiled.EntryIds.LongLength,
            pageStart,
            rows);
    }

    public ArchiveChildrenResult FetchChildren(string sessionId, ArchiveChildrenRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        var session = sessions.GetRequired(sessionId);
        var compiled = session.GetRequiredQuery(request.QueryId);
        var limit = Math.Clamp(request.Limit, 1, WorkerProtocol.MaximumPageSize);
        var offset = Math.Max(0, request.Offset);
        var parent = NormalizeFolder(request.ParentPath);
        var folders = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        var entries = new List<(string Path, long EntryId)>();
        foreach (var entryId in compiled.EntryIds)
        {
            var entry = session.ReadEntry(entryId);
            if (!string.IsNullOrWhiteSpace(request.Category) &&
                !entry.Category.Equals(request.Category, StringComparison.OrdinalIgnoreCase) &&
                !entry.Role.ToString().Equals(request.Category, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            if (!entry.Path.StartsWith(parent, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            var relative = entry.Path[parent.Length..].TrimStart('/');
            if (relative.Length == 0)
            {
                continue;
            }
            var separator = relative.IndexOf('/');
            if (separator >= 0)
            {
                var name = relative[..separator];
                var full = string.IsNullOrEmpty(parent) ? name : $"{parent.TrimEnd('/')}/{name}";
                folders[full] = folders.GetValueOrDefault(full) + 1;
            }
            else
            {
                entries.Add((entry.Path, entry.EntryId));
            }
        }

        var folderNodes = folders
            .OrderBy(static pair => pair.Key, StringComparer.OrdinalIgnoreCase)
            .Select(static pair => new ArchiveChildNode(pair.Key, Path.GetFileName(pair.Key), true, pair.Value))
            .ToArray();
        entries.Sort(static (left, right) =>
        {
            var compared = StringComparer.OrdinalIgnoreCase.Compare(left.Path, right.Path);
            return compared != 0 ? compared : left.EntryId.CompareTo(right.EntryId);
        });
        var totalChildren = (long)folderNodes.Length + entries.Count;
        var pageNodes = new List<ArchiveChildNode>(limit);
        for (long childIndex = offset; childIndex < totalChildren && pageNodes.Count < limit; childIndex++)
        {
            if (childIndex < folderNodes.Length)
            {
                pageNodes.Add(folderNodes[childIndex]);
                continue;
            }
            var direct = entries[checked((int)(childIndex - folderNodes.Length))];
            var entry = session.ReadEntry(direct.EntryId);
            pageNodes.Add(new ArchiveChildNode(
                $"entry:{entry.EntryId}",
                entry.Name,
                false,
                1,
                entry));
        }
        var consumed = (long)offset + pageNodes.Count;
        var nextOffset = consumed < totalChildren ? checked((int)consumed) : (int?)null;
        return new ArchiveChildrenResult(
            session.Id,
            request.QueryId,
            pageNodes,
            nextOffset is not null,
            offset,
            totalChildren,
            nextOffset);
    }

    public IReadOnlyList<long> GetEntryIds(string sessionId, string queryId)
    {
        var session = sessions.GetRequired(sessionId);
        return session.GetRequiredQuery(queryId).EntryIds;
    }

    private static ArchiveQueryHandle Compile(
        ArchiveSession session,
        ArchiveQuery query,
        long generation,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        var candidates = new List<QueryCandidate>();
        var total = session.Index.EntryCount;
        Publish(progress, new ProgressUpdate(0, total, "query_scan"));
        for (long entryId = 0; entryId < total; entryId++)
        {
            if ((entryId & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                Publish(progress, new ProgressUpdate(entryId, total, "query_scan"));
            }
            var entry = session.ReadEntry(entryId);
            if (!Matches(entry, query))
            {
                continue;
            }
            candidates.Add(QueryCandidate.Create(entry, query.SortField));
        }

        cancellationToken.ThrowIfCancellationRequested();
        if (query.SortField != ArchiveSortField.Path)
        {
            candidates.Sort((left, right) => CompareCandidates(left, right, query.SortField));
        }
        if (query.SortDescending)
        {
            candidates.Reverse();
        }
        var ids = candidates.Select(static item => item.EntryId).ToArray();
        var queryId = Guid.NewGuid().ToString("N");
        session.StoreQuery(new CompiledArchiveQuery(queryId, generation, query, ids));
        Publish(progress, new ProgressUpdate(total, total, "query_complete"));
        return new ArchiveQueryHandle(session.Id, queryId, generation, ids.LongLength);
    }

    private static bool Matches(ArchiveEntryDto entry, ArchiveQuery query)
    {
        if (!MatchesAnyTextPattern(entry, query.IncludeText))
        {
            return false;
        }
        if (!string.IsNullOrWhiteSpace(query.ExcludeText) && MatchesAnyTextPattern(entry, query.ExcludeText))
        {
            return false;
        }
        if (query.Extensions is { Count: > 0 } &&
            !query.Extensions.Any(value => MatchesExtension(entry.Extension, value)))
        {
            return false;
        }
        if (query.Packages is { Count: > 0 } &&
            !query.Packages.Any(value => MatchesPackage(entry, value)))
        {
            return false;
        }
        if (!string.IsNullOrWhiteSpace(query.Folder))
        {
            var folder = NormalizeFolder(query.Folder);
            if (!entry.Path.StartsWith(folder, StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }
        }
        if (query.Roles is { Count: > 0 } && !query.Roles.Contains(entry.Role))
        {
            return false;
        }
        if (query.TechnicalSuffixes is { Count: > 0 } &&
            query.TechnicalSuffixes.Any(pattern => MatchesTextPattern(entry, pattern)))
        {
            return false;
        }
        if (query.MinimumSize is { } minimum && entry.OriginalSize < minimum)
        {
            return false;
        }
        if (query.PreviewableOnly && !entry.IsPreviewable)
        {
            return false;
        }
        return !query.ActiveOverridesOnly || entry.IsActiveOverride;
    }

    private static bool MatchesAnyTextPattern(ArchiveEntryDto entry, string? filter)
    {
        if (string.IsNullOrWhiteSpace(filter))
        {
            return true;
        }
        return filter
            .Split([';', ',', '\r', '\n'], StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
            .Any(pattern => MatchesTextPattern(entry, pattern));
    }

    private static bool MatchesTextPattern(ArchiveEntryDto entry, string filter)
    {
        var text = filter.Trim();
        if (!text.ContainsAny(['*', '?', '[']))
        {
            return entry.Path.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                entry.Name.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                entry.KnownName.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                entry.ExactName.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                entry.NameEvidence.Contains(text, StringComparison.OrdinalIgnoreCase);
        }
        var pattern = "^" + Regex.Escape(text).Replace("\\*", ".*").Replace("\\?", ".") + "$";
        return Regex.IsMatch(entry.Path, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250)) ||
            Regex.IsMatch(entry.Name, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250)) ||
            Regex.IsMatch(entry.KnownName, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250));
    }

    private static bool MatchesPackage(ArchiveEntryDto entry, string candidate)
    {
        var text = candidate.Trim();
        if (text.Length == 0)
        {
            return true;
        }
        if (!text.ContainsAny(['*', '?', '[']))
        {
            return entry.Package.Contains(text, StringComparison.OrdinalIgnoreCase) ||
                entry.SourcePamt.Contains(text, StringComparison.OrdinalIgnoreCase);
        }
        var pattern = "^" + Regex.Escape(text).Replace("\\*", ".*").Replace("\\?", ".") + "$";
        return Regex.IsMatch(entry.Package, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250)) ||
            Regex.IsMatch(entry.SourcePamt, pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(250));
    }

    private static bool MatchesExtension(string extension, string candidate)
    {
        var normalized = candidate.Trim().ToLowerInvariant();
        if (normalized is "*" or ".*" or "all")
        {
            return true;
        }
        if (!normalized.StartsWith('.'))
        {
            normalized = "." + normalized;
        }
        return extension.Equals(normalized, StringComparison.OrdinalIgnoreCase);
    }

    private static int CompareCandidates(QueryCandidate left, QueryCandidate right, ArchiveSortField field)
    {
        var result = field switch
        {
            ArchiveSortField.OriginalSize or ArchiveSortField.StoredSize => left.Number.CompareTo(right.Number),
            ArchiveSortField.Compression or ArchiveSortField.Role or ArchiveSortField.ActiveOverride => left.Number.CompareTo(right.Number),
            _ => StringComparer.OrdinalIgnoreCase.Compare(left.Text, right.Text),
        };
        return result != 0 ? result : left.EntryId.CompareTo(right.EntryId);
    }

    private static string NormalizeFolder(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }
        return value.Replace('\\', '/').Trim('/') + "/";
    }

    private static void Publish(Func<ProgressUpdate, Task>? progress, ProgressUpdate update) =>
        progress?.Invoke(update).GetAwaiter().GetResult();

    private sealed record QueryCandidate(long EntryId, string Text, long Number)
    {
        public static QueryCandidate Create(ArchiveEntryDto entry, ArchiveSortField field) => field switch
        {
            ArchiveSortField.Name => new(entry.EntryId, entry.Name, 0),
            ArchiveSortField.KnownName => new(entry.EntryId, entry.KnownName, 0),
            ArchiveSortField.ExactName => new(entry.EntryId, entry.ExactName, 0),
            ArchiveSortField.NameEvidence => new(entry.EntryId, entry.NameEvidence, 0),
            ArchiveSortField.Extension => new(entry.EntryId, entry.Extension, 0),
            ArchiveSortField.Package => new(entry.EntryId, entry.Package, 0),
            ArchiveSortField.OriginalSize => new(entry.EntryId, string.Empty, entry.OriginalSize),
            ArchiveSortField.StoredSize => new(entry.EntryId, string.Empty, entry.StoredSize),
            ArchiveSortField.Compression => new(entry.EntryId, string.Empty, entry.CompressionType),
            ArchiveSortField.Role => new(entry.EntryId, string.Empty, (long)entry.Role),
            ArchiveSortField.Category => new(entry.EntryId, entry.Category, 0),
            ArchiveSortField.ActiveOverride => new(entry.EntryId, string.Empty, entry.IsActiveOverride ? 1 : 0),
            _ => new(entry.EntryId, entry.Path, 0),
        };
    }
}

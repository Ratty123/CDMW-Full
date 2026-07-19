using System.Text.RegularExpressions;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveTextSearchService(
    ArchiveSessionManager sessions,
    NativeArchiveCore native)
{
    private const long MaximumSearchEntryBytes = 256L * 1024L * 1024L;

    public async Task<ArchiveTextSearchBatch> SearchAsync(
        ArchiveTextSearchRequest request,
        Func<ArchiveTextSearchBatch, Task>? publishBatch,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (string.IsNullOrEmpty(request.Query))
        {
            throw new ArgumentException("Text search query must not be empty.", nameof(request));
        }
        var session = sessions.GetRequired(request.SessionId);
        var maximumMatches = Math.Clamp(request.MaximumMatches, 1, 100_000);
        var contextCharacters = Math.Clamp(request.ContextCharacters, 0, 4_096);
        var batchSize = Math.Clamp(request.BatchSize, 1, 256);
        var regexTimeout = TimeSpan.FromMilliseconds(Math.Clamp(request.RegexTimeoutMilliseconds, 50, 30_000));
        var regex = request.UseRegularExpression
            ? new Regex(
                request.Query,
                (request.CaseSensitive ? RegexOptions.None : RegexOptions.IgnoreCase) |
                RegexOptions.CultureInvariant,
                regexTimeout)
            : null;
        var comparison = request.CaseSensitive ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
        var extensions = NormalizeExtensions(request.Extensions);
        var warnings = new List<string>();
        var pending = new List<ArchiveTextMatch>(batchSize);
        long filesScanned = 0;
        long filesMatched = 0;
        long bytesRead = 0;
        var matchCount = 0;
        var limitReached = false;
        var total = session.Index.EntryCount;

        if (progress is not null)
        {
            await progress(new ProgressUpdate(0, total, "text_search")).ConfigureAwait(false);
        }
        for (long entryId = 0; entryId < total && !limitReached; entryId++)
        {
            if ((entryId & 0xFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (progress is not null)
                {
                    await progress(new ProgressUpdate(entryId, total, "text_search")).ConfigureAwait(false);
                }
            }
            var entry = session.ReadEntry(entryId);
            if (!ShouldSearch(entry, request.PathFilter, extensions))
            {
                continue;
            }
            filesScanned++;
            if (entry.OriginalSize > MaximumSearchEntryBytes)
            {
                if (warnings.Count < 64)
                {
                    warnings.Add($"Skipped oversized text candidate: {entry.Path}");
                }
                continue;
            }

            DecodedArchiveEntry decoded;
            try
            {
                decoded = await Task.Run(() => native.Decode(entry), cancellationToken).ConfigureAwait(false);
            }
            catch (Exception exception) when (exception is InvalidDataException or NativeArchiveException or IOException)
            {
                if (warnings.Count < 64)
                {
                    warnings.Add($"Could not decode {entry.Path}: {exception.Message}");
                }
                continue;
            }
            bytesRead += decoded.Bytes.LongLength;
            if (!TextDecoding.LooksTextual(decoded.Bytes))
            {
                continue;
            }
            var text = TextDecoding.Decode(decoded.Bytes);
            var entryMatched = false;
            try
            {
                foreach (var span in FindMatches(text, request.Query, regex, comparison))
                {
                    entryMatched = true;
                    var (line, column) = LineAndColumn(text, span.Index);
                    pending.Add(new ArchiveTextMatch(
                        entry.EntryId,
                        entry.Path,
                        line,
                        column,
                        span.Length,
                        Context(text, span.Index, span.Length, contextCharacters)));
                    matchCount++;
                    if (pending.Count >= batchSize)
                    {
                        await PublishAsync(
                            session.Id,
                            filesScanned,
                            filesMatched + 1,
                            bytesRead,
                            pending,
                            isFinal: false,
                            limitReached: false,
                            warnings: [],
                            publishBatch).ConfigureAwait(false);
                        pending.Clear();
                    }
                    if (matchCount >= maximumMatches)
                    {
                        limitReached = true;
                        break;
                    }
                }
            }
            catch (RegexMatchTimeoutException)
            {
                if (warnings.Count < 64)
                {
                    warnings.Add($"Regular expression timed out for {entry.Path}.");
                }
            }
            if (entryMatched)
            {
                filesMatched++;
            }
        }

        var final = new ArchiveTextSearchBatch(
            session.Id,
            filesScanned,
            filesMatched,
            bytesRead,
            pending.ToArray(),
            IsFinal: true,
            limitReached,
            warnings);
        if (publishBatch is not null)
        {
            await publishBatch(final).ConfigureAwait(false);
        }
        if (progress is not null)
        {
            await progress(new ProgressUpdate(total, total, "text_search_complete")).ConfigureAwait(false);
        }
        return final;
    }

    private static bool ShouldSearch(
        ArchiveEntryDto entry,
        string? pathFilter,
        HashSet<string>? extensions)
    {
        if (!string.IsNullOrWhiteSpace(pathFilter) &&
            !entry.Path.Contains(pathFilter.Trim(), StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }
        if (extensions is { Count: > 0 })
        {
            return extensions.Contains(entry.Extension);
        }
        return entry.Role == ArchiveEntryRole.Text;
    }

    private static HashSet<string>? NormalizeExtensions(IReadOnlyList<string>? values)
    {
        if (values is not { Count: > 0 })
        {
            return null;
        }
        return values.Select(static value =>
            {
                var normalized = value.Trim().ToLowerInvariant();
                return normalized.StartsWith('.') ? normalized : "." + normalized;
            })
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
    }

    private static IEnumerable<(int Index, int Length)> FindMatches(
        string text,
        string query,
        Regex? regex,
        StringComparison comparison)
    {
        if (regex is not null)
        {
            foreach (Match match in regex.Matches(text))
            {
                if (match.Success)
                {
                    yield return (match.Index, match.Length);
                }
            }
            yield break;
        }

        var start = 0;
        while (start <= text.Length - query.Length)
        {
            var index = text.IndexOf(query, start, comparison);
            if (index < 0)
            {
                yield break;
            }
            yield return (index, query.Length);
            start = index + Math.Max(1, query.Length);
        }
    }

    private static (int Line, int Column) LineAndColumn(string text, int index)
    {
        var line = 1;
        var lineStart = 0;
        for (var cursor = 0; cursor < index; cursor++)
        {
            if (text[cursor] == '\n')
            {
                line++;
                lineStart = cursor + 1;
            }
        }
        return (line, index - lineStart + 1);
    }

    private static string Context(string text, int index, int length, int contextCharacters)
    {
        var start = Math.Max(0, index - contextCharacters);
        var end = Math.Min(text.Length, index + length + contextCharacters);
        return text[start..end].Replace('\r', ' ').Replace('\n', ' ');
    }

    private static Task PublishAsync(
        string sessionId,
        long filesScanned,
        long filesMatched,
        long bytesRead,
        IReadOnlyList<ArchiveTextMatch> matches,
        bool isFinal,
        bool limitReached,
        IReadOnlyList<string> warnings,
        Func<ArchiveTextSearchBatch, Task>? publishBatch) =>
        publishBatch is null
            ? Task.CompletedTask
            : publishBatch(new ArchiveTextSearchBatch(
                sessionId,
                filesScanned,
                filesMatched,
                bytesRead,
                matches.ToArray(),
                isFinal,
                limitReached,
                warnings));
}

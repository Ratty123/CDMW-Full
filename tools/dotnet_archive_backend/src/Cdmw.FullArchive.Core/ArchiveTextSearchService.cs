using System.Collections.Concurrent;
using System.Text.RegularExpressions;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveTextSearchService(
    ArchiveSessionManager sessions,
    NativeArchiveCore native)
{
    private const long MaximumSearchEntryBytes = 256L * 1024L * 1024L;
    // Matches the Python reference reader's per-file limit.
    private const long MaximumByteSearchEntryBytes = 32L * 1024L * 1024L;

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
            ? CreateQueryRegex(request.Query, request.CaseSensitive, regexTimeout)
            : null;
        var comparison = request.CaseSensitive ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
        if (request.MatchBytes && regex is not null)
        {
            throw new ArgumentException("Byte search does not take a regular expression.", nameof(request));
        }
        var extensions = NormalizeExtensions(request.Extensions);
        if (request.MatchBytes)
        {
            return await SearchBytesAsync(
                session, request, maximumMatches, batchSize, comparison, extensions, publishBatch, cancellationToken, progress)
                .ConfigureAwait(false);
        }
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
            var text = NormalizeLineEndings(TextDecoding.Decode(decoded.Bytes));
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
                        Context(text, span.Index, span.Length, contextCharacters),
                        entry.Package));
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

    /// <summary>
    /// Finds the files whose stored bytes contain the query: one match per file,
    /// for callers that confirm each file themselves (Find references). Decoding
    /// dominates, so files are decoded on half the cores, at most six, which
    /// leaves room for previews; preparation already decodes in parallel.
    /// </summary>
    private async Task<ArchiveTextSearchBatch> SearchBytesAsync(
        ArchiveSession session,
        ArchiveTextSearchRequest request,
        int maximumMatches,
        int batchSize,
        StringComparison comparison,
        HashSet<string>? extensions,
        Func<ArchiveTextSearchBatch, Task>? publishBatch,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        var needles = ByteNeedles(request.Query, request.CaseSensitive);
        var warnings = new List<string>();
        var candidates = new List<ArchiveEntryDto>();
        long oversized = 0;
        var total = session.Index.EntryCount;
        for (long entryId = 0; entryId < total; entryId++)
        {
            if ((entryId & 0xFFFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
            }
            var entry = session.ReadEntry(entryId);
            if (!ShouldSearch(entry, request.PathFilter, extensions))
            {
                continue;
            }
            if (entry.OriginalSize > MaximumByteSearchEntryBytes)
            {
                oversized++;
                if (warnings.Count < 64)
                {
                    warnings.Add($"Skipped oversized byte-search candidate: {entry.Path}");
                }
                continue;
            }
            candidates.Add(entry);
        }

        var gate = new SemaphoreSlim(1, 1);
        var pending = new List<ArchiveTextMatch>(batchSize);
        long processed = 0;
        long filesMatched = 0;
        long bytesRead = 0;
        var limitReached = false;
        if (progress is not null)
        {
            await progress(new ProgressUpdate(0, candidates.Count, "byte_search")).ConfigureAwait(false);
        }
        using var stop = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        try
        {
            await Parallel.ForEachAsync(
                candidates,
                new ParallelOptions
                {
                    MaxDegreeOfParallelism = Math.Clamp(Environment.ProcessorCount / 2, 1, 6),
                    CancellationToken = stop.Token,
                },
                async (entry, token) =>
                {
                    (int Index, int Length) hit = (-1, 0);
                    string? warning = null;
                    try
                    {
                        var decoded = native.Decode(entry);
                        Interlocked.Add(ref bytesRead, decoded.Bytes.LongLength);
                        hit = FindByteMatch(decoded.Bytes, needles, request.CaseSensitive);
                    }
                    catch (Exception exception) when (exception is InvalidDataException or NativeArchiveException or IOException)
                    {
                        warning = $"Could not decode {entry.Path}: {exception.Message}";
                    }
                    var done = Interlocked.Increment(ref processed);
                    await gate.WaitAsync(token).ConfigureAwait(false);
                    try
                    {
                        if (warning is not null && warnings.Count < 64)
                        {
                            warnings.Add(warning);
                        }
                        if (hit.Index >= 0 && !limitReached)
                        {
                            filesMatched++;
                            pending.Add(new ArchiveTextMatch(
                                entry.EntryId, entry.Path, 1, hit.Index + 1, hit.Length, string.Empty, entry.Package));
                            if (filesMatched >= maximumMatches)
                            {
                                limitReached = true;
                                stop.Cancel();
                            }
                        }
                        if (pending.Count >= batchSize)
                        {
                            await PublishAsync(
                                session.Id, done + oversized, filesMatched, Interlocked.Read(ref bytesRead), pending,
                                isFinal: false, limitReached: false, warnings: [], publishBatch).ConfigureAwait(false);
                            pending.Clear();
                        }
                        if (progress is not null && (done & 0xFF) == 0)
                        {
                            await progress(new ProgressUpdate(done, candidates.Count, "byte_search")).ConfigureAwait(false);
                        }
                    }
                    finally
                    {
                        gate.Release();
                    }
                }).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (limitReached && !cancellationToken.IsCancellationRequested)
        {
        }

        var final = new ArchiveTextSearchBatch(
            session.Id,
            Interlocked.Read(ref processed) + oversized,
            filesMatched,
            Interlocked.Read(ref bytesRead),
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
            await progress(new ProgressUpdate(candidates.Count, candidates.Count, "byte_search_complete")).ConfigureAwait(false);
        }
        return final;
    }

    /// <summary>
    /// Byte search compares stored bytes, the query taken one character per byte
    /// (Latin-1), so binary containers are searched as stored. A printable ASCII
    /// query is also looked for as UTF-16LE and UTF-16BE; any other query (an ID's
    /// raw bytes) only as given. Ignoring case folds ASCII letters only.
    /// </summary>
    private static byte[][] ByteNeedles(string query, bool caseSensitive)
    {
        var raw = System.Text.Encoding.Latin1.GetBytes(query);
        if (!caseSensitive)
        {
            FoldAsciiCase(raw);
        }
        if (!query.All(static character => character is >= ' ' and <= '~'))
        {
            return [raw];
        }
        var littleEndian = new byte[raw.Length * 2];
        var bigEndian = new byte[raw.Length * 2];
        for (var index = 0; index < raw.Length; index++)
        {
            littleEndian[index * 2] = raw[index];
            bigEndian[index * 2 + 1] = raw[index];
        }
        return [raw, littleEndian, bigEndian];
    }

    private static void FoldAsciiCase(Span<byte> bytes)
    {
        for (var index = 0; index < bytes.Length; index++)
        {
            var value = bytes[index];
            if ((uint)(value - 'A') <= 'Z' - 'A')
            {
                bytes[index] = (byte)(value | 0x20);
            }
        }
    }

    /// <summary>Folds <paramref name="bytes"/> in place when ignoring case: it is a freshly decoded copy.</summary>
    private static (int Index, int Length) FindByteMatch(byte[] bytes, byte[][] needles, bool caseSensitive)
    {
        if (!caseSensitive)
        {
            FoldAsciiCase(bytes);
        }
        ReadOnlySpan<byte> span = bytes;
        foreach (var needle in needles)
        {
            var index = span.IndexOf(needle);
            if (index >= 0)
            {
                return (index, needle.Length);
            }
        }
        return (-1, 0);
    }

    private static bool ShouldSearch(
        ArchiveEntryDto entry,
        string? pathFilter,
        HashSet<string>? extensions)
    {
        if (!PathMatchesFilter(entry.Path, pathFilter))
        {
            return false;
        }
        if (extensions is { Count: > 0 })
        {
            return extensions.Contains(entry.Extension);
        }
        return entry.Role == ArchiveEntryRole.Text;
    }

    /// <summary>
    /// Plain filters match anywhere in the path, ignoring case. A filter with
    /// <c>*</c> or <c>?</c> matches the file name, or with a slash the path from
    /// any folder; a leading slash anchors it at the archive root. Text Search's
    /// Python search applies the same rules.
    /// </summary>
    internal static bool PathMatchesFilter(string path, string? pathFilter)
    {
        if (string.IsNullOrWhiteSpace(pathFilter))
        {
            return true;
        }
        var wildcard = PathWildcard(pathFilter);
        return wildcard is null
            ? path.Contains(pathFilter.Trim(), StringComparison.OrdinalIgnoreCase)
            : wildcard.IsMatch(path.Replace('\\', '/'));
    }

    private static readonly ConcurrentDictionary<string, Regex?> PathWildcards = new(StringComparer.Ordinal);

    private static Regex? PathWildcard(string pathFilter)
    {
        if (PathWildcards.TryGetValue(pathFilter, out var cached))
        {
            return cached;
        }
        var pattern = pathFilter.Trim().Replace('\\', '/');
        Regex? compiled = null;
        if (pattern.Contains('*') || pattern.Contains('?'))
        {
            var nameOnly = !pattern.Contains('/');
            var body = Regex.Escape(pattern.TrimStart('/'))
                .Replace(@"\*", nameOnly ? "[^/]*" : ".*", StringComparison.Ordinal)
                .Replace(@"\?", nameOnly ? "[^/]" : ".", StringComparison.Ordinal);
            var prefix = pattern.StartsWith('/') ? "" : "(?:.*/)?";
            compiled = new Regex(
                $"^{prefix}{body}$",
                RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Singleline);
        }
        if (PathWildcards.Count >= 64)
        {
            PathWildcards.Clear();
        }
        PathWildcards[pathFilter] = compiled;
        return compiled;
    }

    /// <summary>Matches Python's preview text, so ^ and $ see every line end.</summary>
    internal static string NormalizeLineEndings(string text) =>
        text.Contains('\r') ? text.Replace("\r\n", "\n", StringComparison.Ordinal).Replace('\r', '\n') : text;

    // Multiline matches Python's re.MULTILINE, so ^ and $ work per line in both searches.
    private static Regex CreateQueryRegex(string query, bool caseSensitive, TimeSpan timeout) =>
        new(
            query,
            (caseSensitive ? RegexOptions.None : RegexOptions.IgnoreCase) |
            RegexOptions.CultureInvariant | RegexOptions.Multiline,
            timeout);

    /// <summary>The per-file matching SearchAsync applies after decoding.</summary>
    internal static IEnumerable<(int Index, int Length)> FindTextMatches(
        string text,
        string query,
        bool useRegularExpression,
        bool caseSensitive) =>
        FindMatches(
            NormalizeLineEndings(text),
            query,
            useRegularExpression ? CreateQueryRegex(query, caseSensitive, TimeSpan.FromSeconds(1)) : null,
            caseSensitive ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase);

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
                // Empty matches (a bare ^ or lookahead) are skipped, as the Python search does.
                if (match.Success && match.Length > 0)
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

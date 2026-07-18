using System.Collections.Concurrent;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Cdmw.ArchiveLite.Contracts;

namespace Cdmw.ArchiveLite.Core;

public sealed class TextSearchService(ArchiveSessionManager sessions, NativeArchiveCore native)
{
    private const long MaximumDecodedTextBytes = 64L * 1024L * 1024L;
    private const int MaximumMatchPayloadBytes = 700 * 1024;

    public async Task<TextSearchResultBatch> SearchAsync(TextSearchRequest request, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (string.IsNullOrEmpty(request.Query)) throw new ArgumentException("Search query must not be empty.", nameof(request));
        var maximumMatches = Math.Clamp(request.MaximumMatches, 1, 2_000);
        var matcher = BuildMatcher(request);
        IEnumerable<SearchInput> inputs = request.SourceKind == TextSearchSourceKind.Archive
            ? BuildArchiveInputs(sessions.GetRequired(request.Source), request)
            : BuildLooseInputs(request);
        var matches = new ConcurrentBag<RawMatch>();
        var timedOut = new ConcurrentBag<string>();
        var warnings = new ConcurrentBag<string>();
        var matchedFiles = new ConcurrentDictionary<string, byte>(StringComparer.OrdinalIgnoreCase);
        long filesScanned = 0;
        long bytesRead = 0;
        var matchCount = 0;
        var parallelism = Math.Max(1, Math.Min(4, Environment.ProcessorCount - 1));
        await Parallel.ForEachAsync(
            inputs,
            new ParallelOptions { CancellationToken = cancellationToken, MaxDegreeOfParallelism = parallelism },
            async (input, token) =>
            {
                if (Volatile.Read(ref matchCount) >= maximumMatches) return;
                try
                {
                    if (input.DeclaredSize > MaximumDecodedTextBytes)
                    {
                        warnings.Add(BoundedDiagnostic($"Skipped {input.DisplayPath}: decoded text exceeds 64 MiB."));
                        return;
                    }
                    var bytes = await input.ReadAsync(token).ConfigureAwait(false);
                    Interlocked.Increment(ref filesScanned);
                    Interlocked.Add(ref bytesRead, bytes.LongLength);
                    if (bytes.LongLength > MaximumDecodedTextBytes)
                    {
                        warnings.Add(BoundedDiagnostic($"Skipped {input.DisplayPath}: decoded text exceeds 64 MiB."));
                        return;
                    }
                    var text = TextDecoding.Decode(bytes).Replace("\r\n", "\n", StringComparison.Ordinal);
                    var fileMatches = FindMatches(text, request, matcher, input.DisplayPath, input.EntryId, token);
                    var any = false;
                    foreach (var match in fileMatches)
                    {
                        if (Interlocked.Increment(ref matchCount) > maximumMatches) break;
                        matches.Add(match);
                        any = true;
                    }
                    if (any) matchedFiles.TryAdd(input.DisplayPath, 0);
                }
                catch (RegexMatchTimeoutException)
                {
                    timedOut.Add(BoundedDiagnostic(input.DisplayPath));
                }
                catch (NativeArchiveException exception)
                {
                    warnings.Add(BoundedDiagnostic($"Skipped {input.DisplayPath}: {exception.Message}"));
                }
                catch (IOException exception)
                {
                    warnings.Add(BoundedDiagnostic($"Skipped {input.DisplayPath}: {exception.Message}"));
                }
            }).ConfigureAwait(false);

        var orderedMatches = matches
            .OrderBy(static match => match.Path, StringComparer.OrdinalIgnoreCase)
            .ThenBy(static match => match.Offset)
            .Take(maximumMatches);
        var ordered = new List<TextSearchMatchDto>();
        var matchPayloadBytes = 0;
        var responseLimited = false;
        foreach (var match in orderedMatches)
        {
            var dto = new TextSearchMatchDto(
                ordered.Count + 1,
                match.EntryId,
                match.Path,
                match.Line,
                match.Column,
                match.Length,
                match.Context);
            var dtoBytes = JsonSerializer.SerializeToUtf8Bytes(dto, WorkerProtocol.JsonOptions).Length;
            if (matchPayloadBytes + dtoBytes > MaximumMatchPayloadBytes)
            {
                responseLimited = true;
                break;
            }
            matchPayloadBytes += dtoBytes;
            ordered.Add(dto);
        }
        var returnedWarnings = warnings
            .Order(StringComparer.OrdinalIgnoreCase)
            .Take(50)
            .ToList();
        if (responseLimited)
        {
            returnedWarnings.Add("Additional matches were omitted to stay within the worker protocol limit.");
        }
        return new TextSearchResultBatch(
            filesScanned,
            matchedFiles.Count,
            bytesRead,
            ordered,
            Volatile.Read(ref matchCount) >= maximumMatches || responseLimited,
            timedOut.Order(StringComparer.OrdinalIgnoreCase).Take(50).ToArray(),
            returnedWarnings);
    }

    private IEnumerable<SearchInput> BuildArchiveInputs(ArchiveSession session, TextSearchRequest request)
    {
        for (long entryId = 0; entryId < session.Index.EntryCount; entryId++)
        {
            var entry = session.Index.ReadEntry(entryId);
            if (!MatchesPathAndExtension(entry.Path, entry.Extension, request)) continue;
            yield return new SearchInput(entry.Path, entry.EntryId, entry.OriginalSize, token =>
            {
                token.ThrowIfCancellationRequested();
                return Task.FromResult(native.Decode(entry).Bytes);
            });
        }
    }

    private static IEnumerable<SearchInput> BuildLooseInputs(TextSearchRequest request)
    {
        var root = Path.GetFullPath(request.Source);
        if (!Directory.Exists(root)) throw new DirectoryNotFoundException($"Text-search folder does not exist: {root}");
        var options = new EnumerationOptions
        {
            RecurseSubdirectories = true,
            IgnoreInaccessible = true,
            AttributesToSkip = FileAttributes.ReparsePoint,
        };
        foreach (var path in Directory.EnumerateFiles(root, "*", options))
        {
            var relative = Path.GetRelativePath(root, path).Replace('\\', '/');
            if (!MatchesPathAndExtension(relative, Path.GetExtension(path), request)) continue;
            long declaredSize;
            try
            {
                declaredSize = new FileInfo(path).Length;
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
            {
                continue;
            }
            yield return new SearchInput(relative, null, declaredSize, token => ReadLooseFileAsync(path, token));
        }
    }

    private static Regex? BuildMatcher(TextSearchRequest request)
    {
        if (!request.UseRegularExpression) return null;
        var options = RegexOptions.CultureInvariant;
        if (!request.CaseSensitive) options |= RegexOptions.IgnoreCase;
        return new Regex(
            request.Query,
            options,
            TimeSpan.FromMilliseconds(Math.Clamp(request.RegexTimeoutMilliseconds, 50, 10_000)));
    }

    private static IEnumerable<RawMatch> FindMatches(
        string text,
        TextSearchRequest request,
        Regex? regex,
        string path,
        long? entryId,
        CancellationToken cancellationToken)
    {
        var lines = new LineTracker(text);
        if (regex is not null)
        {
            foreach (Match match in regex.Matches(text))
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (!match.Success) continue;
                yield return BuildMatch(text, path, entryId, match.Index, match.Length, request.ContextCharacters, lines);
            }
            yield break;
        }
        var comparison = request.CaseSensitive ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
        var offset = 0;
        while (offset <= text.Length - request.Query.Length)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var found = text.IndexOf(request.Query, offset, comparison);
            if (found < 0) yield break;
            yield return BuildMatch(text, path, entryId, found, request.Query.Length, request.ContextCharacters, lines);
            offset = found + Math.Max(1, request.Query.Length);
        }
    }

    private static RawMatch BuildMatch(
        string text,
        string path,
        long? entryId,
        int offset,
        int length,
        int contextCharacters,
        LineTracker lines)
    {
        var (line, column) = lines.GetPosition(offset);
        var radius = Math.Clamp(contextCharacters, 40, 1000);
        var contextStart = Math.Max(0, offset - radius);
        var contextEnd = Math.Min(text.Length, offset + Math.Max(length, 1) + radius);
        var context = text[contextStart..contextEnd].Replace('\n', ' ').Replace('\t', ' ');
        return new RawMatch(path, entryId, offset, line, column, length, context);
    }

    private static bool MatchesPathAndExtension(string path, string extension, TextSearchRequest request)
    {
        if (!string.IsNullOrWhiteSpace(request.PathFilter) && !path.Contains(request.PathFilter, StringComparison.OrdinalIgnoreCase)) return false;
        if (request.Extensions.Count == 0) return true;
        return request.Extensions.Any(candidate =>
        {
            var normalized = candidate.Trim();
            if (normalized is "*" or ".*") return true;
            if (!normalized.StartsWith('.')) normalized = "." + normalized;
            return extension.Equals(normalized, StringComparison.OrdinalIgnoreCase);
        });
    }

    private sealed record SearchInput(
        string DisplayPath,
        long? EntryId,
        long DeclaredSize,
        Func<CancellationToken, Task<byte[]>> ReadAsync);

    private static async Task<byte[]> ReadLooseFileAsync(string path, CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete,
            128 * 1024,
            FileOptions.Asynchronous | FileOptions.SequentialScan);
        if (stream.Length > MaximumDecodedTextBytes)
        {
            throw new IOException("File exceeds the 64 MiB text-search limit.");
        }
        var bytes = new byte[checked((int)stream.Length)];
        var offset = 0;
        while (offset < bytes.Length)
        {
            var read = await stream.ReadAsync(bytes.AsMemory(offset), cancellationToken).ConfigureAwait(false);
            if (read == 0) break;
            offset += read;
        }
        if (offset != bytes.Length) Array.Resize(ref bytes, offset);
        return bytes;
    }

    private sealed class LineTracker(string text)
    {
        private int _scanOffset;
        private int _line = 1;
        private int _lineStart;

        public (int Line, int Column) GetPosition(int offset)
        {
            if (offset < _scanOffset)
            {
                _scanOffset = 0;
                _line = 1;
                _lineStart = 0;
            }
            while (_scanOffset < offset)
            {
                if (text[_scanOffset] == '\n')
                {
                    _line++;
                    _lineStart = _scanOffset + 1;
                }
                _scanOffset++;
            }
            return (_line, offset - _lineStart + 1);
        }
    }

    private sealed record RawMatch(
        string Path,
        long? EntryId,
        int Offset,
        int Line,
        int Column,
        int Length,
        string Context);

    private static string BoundedDiagnostic(string value) => value.Length <= 1_024 ? value : value[..1_024] + "...";
}

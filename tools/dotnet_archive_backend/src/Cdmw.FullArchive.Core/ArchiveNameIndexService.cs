using System.Collections.Concurrent;
using System.Text;
using System.Text.RegularExpressions;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

public sealed class ArchiveNameIndexService(
    ArchiveSessionManager sessions,
    ArchiveCacheStore cache,
    NativeArchiveCore native)
{
    private const int FileVersion = 3;
    private static readonly byte[] Magic = "CDMWNAM3"u8.ToArray();
    private readonly ConcurrentDictionary<string, Lazy<Task<ArchiveNameIndex>>> _indexes =
        new(StringComparer.OrdinalIgnoreCase);

    public async Task<ArchiveNameIndex> WarmAsync(
        string sessionId,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress = null)
    {
        var session = sessions.GetRequired(sessionId);
        var index = await GetIndexAsync(session, cancellationToken, progress).ConfigureAwait(false);
        session.SetNameIndex(index);
        return index;
    }

    private Task<ArchiveNameIndex> GetIndexAsync(
        ArchiveSession session,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        var lazy = _indexes.GetOrAdd(
            session.GenerationPath,
            _ => new Lazy<Task<ArchiveNameIndex>>(
                () => LoadOrBuildAsync(session, cancellationToken, progress),
                LazyThreadSafetyMode.ExecutionAndPublication));
        return AwaitIndexAsync(session.GenerationPath, lazy, cancellationToken);
    }

    private async Task<ArchiveNameIndex> LoadOrBuildAsync(
        ArchiveSession session,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        var path = Path.Combine(session.GenerationPath, "names.bin");
        if (File.Exists(path))
        {
            try
            {
                return await Task.Run(() => Load(path, session.Fingerprint), cancellationToken).ConfigureAwait(false);
            }
            catch (Exception exception) when (exception is IOException or InvalidDataException or UnauthorizedAccessException)
            {
                TryDelete(path);
            }
        }

        var index = await Task.Run(
            () => ArchiveNameIndexBuilder.Build(session, native, cancellationToken, progress),
            CancellationToken.None).ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();
        await WriteAsync(path, session.Fingerprint, index, cancellationToken).ConfigureAwait(false);
        await cache.UpdateSecondaryStateAsync(session.GenerationPath, lookupsReady: null, namesReady: true, cancellationToken).ConfigureAwait(false);
        return index;
    }

    private static async Task WriteAsync(
        string destination,
        string fingerprint,
        ArchiveNameIndex index,
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
                64 * 1024,
                FileOptions.Asynchronous | FileOptions.WriteThrough))
            using (var writer = new BinaryWriter(stream, Encoding.UTF8, leaveOpen: true))
            {
                writer.Write(Magic);
                writer.Write(FileVersion);
                writer.Write(fingerprint);
                writer.Write(index.IsAvailable);
                writer.Write(index.UnavailableReason);
                WriteMap(writer, index.ExactNames);
                WriteMap(writer, index.RelatedNames);
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

    private static ArchiveNameIndex Load(string path, string fingerprint)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        using var reader = new BinaryReader(stream, Encoding.UTF8, leaveOpen: false);
        if (!reader.ReadBytes(Magic.Length).AsSpan().SequenceEqual(Magic) ||
            reader.ReadInt32() != FileVersion ||
            !reader.ReadString().Equals(fingerprint, StringComparison.Ordinal))
        {
            throw new InvalidDataException("Archive name index header is invalid.");
        }
        var isAvailable = reader.ReadBoolean();
        var unavailableReason = reader.ReadString();
        var exact = ReadMap(reader);
        var related = ReadMap(reader);
        if (stream.Position != stream.Length)
        {
            throw new InvalidDataException("Archive name index has trailing data.");
        }
        return isAvailable
            ? ArchiveNameIndex.FromMappings(exact, related)
            : ArchiveNameIndex.Unavailable(unavailableReason);
    }

    private static void WriteMap(BinaryWriter writer, IReadOnlyDictionary<string, string> map)
    {
        writer.Write(map.Count);
        foreach (var pair in map.OrderBy(static pair => pair.Key, StringComparer.OrdinalIgnoreCase))
        {
            writer.Write(pair.Key);
            writer.Write(pair.Value);
        }
    }

    private static Dictionary<string, string> ReadMap(BinaryReader reader)
    {
        var count = reader.ReadInt32();
        if (count < 0 || count > 10_000_000)
        {
            throw new InvalidDataException("Archive name index mapping count is invalid.");
        }
        var result = new Dictionary<string, string>(count, StringComparer.OrdinalIgnoreCase);
        for (var index = 0; index < count; index++)
        {
            result.Add(reader.ReadString(), reader.ReadString());
        }
        return result;
    }

    private async Task<ArchiveNameIndex> AwaitIndexAsync(
        string generationPath,
        Lazy<Task<ArchiveNameIndex>> lazy,
        CancellationToken cancellationToken)
    {
        try
        {
            return await lazy.Value.WaitAsync(cancellationToken).ConfigureAwait(false);
        }
        catch
        {
            if (lazy.IsValueCreated && (lazy.Value.IsCanceled || lazy.Value.IsFaulted) &&
                _indexes.TryGetValue(generationPath, out var current) && ReferenceEquals(current, lazy))
            {
                _indexes.TryRemove(generationPath, out _);
            }
            throw;
        }
    }

    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // A later cache prune can remove a stale name index.
        }
    }
}

public sealed class ArchiveNameIndex
{
    private static readonly string[] VariantSuffixes =
    [
        "_index01_l", "_index01_r", "_index02_l", "_index02_r", "_index03_l", "_index03_r",
        "_index01", "_index02", "_index03", "_sub01", "_sub02", "_sub03",
        "_in", "_l", "_r", "_u", "_s", "_t", "_c", "_d",
    ];

    private static readonly Regex NumberedVariant = new(
        "_(?:index|sub)\\d{2}$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private readonly IReadOnlyDictionary<string, string> _exactNames;
    private readonly IReadOnlyDictionary<string, string> _relatedNames;

    private ArchiveNameIndex(
        IReadOnlyDictionary<string, string> exactNames,
        IReadOnlyDictionary<string, string> relatedNames,
        bool isAvailable,
        string unavailableReason)
    {
        _exactNames = Normalize(exactNames);
        _relatedNames = Normalize(relatedNames);
        IsAvailable = isAvailable;
        UnavailableReason = unavailableReason.Trim();
    }

    public static ArchiveNameIndex Empty { get; } = new(
        new Dictionary<string, string>(),
        new Dictionary<string, string>(),
        true,
        string.Empty);

    public IReadOnlyDictionary<string, string> ExactNames => _exactNames;
    public IReadOnlyDictionary<string, string> RelatedNames => _relatedNames;
    public bool IsAvailable { get; }
    public string UnavailableReason { get; }
    public bool HasNames => _exactNames.Count > 0 || _relatedNames.Count > 0;

    public static ArchiveNameIndex FromMappings(
        IReadOnlyDictionary<string, string> exactNames,
        IReadOnlyDictionary<string, string> relatedNames) => new(
            exactNames,
            relatedNames,
            true,
            string.Empty);

    public static ArchiveNameIndex Unavailable(string reason) => new(
        new Dictionary<string, string>(),
        new Dictionary<string, string>(),
        false,
        string.IsNullOrWhiteSpace(reason) ? "Archive name sources are unavailable." : reason);

    public ArchiveEntryDto Enrich(ArchiveEntryDto entry)
    {
        var stem = Path.GetFileNameWithoutExtension(entry.Name).Trim().ToLowerInvariant();
        if (_exactNames.TryGetValue(stem, out var exactName))
        {
            return entry with
            {
                KnownName = exactName,
                ExactName = exactName,
                NameEvidence = "Exact localization",
            };
        }
        foreach (var candidate in RelatedCandidates(stem))
        {
            if (_relatedNames.TryGetValue(candidate, out var relatedName) ||
                _exactNames.TryGetValue(candidate, out relatedName))
            {
                return entry with { NameEvidence = $"Name hint: {relatedName}" };
            }
        }
        return entry;
    }

    private static IReadOnlyDictionary<string, string> Normalize(IReadOnlyDictionary<string, string> source)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var (rawKey, rawValue) in source)
        {
            var key = rawKey.Trim().ToLowerInvariant();
            var value = rawValue.Trim();
            if (key.Length > 0 && value.Length > 0)
            {
                result[key] = value;
            }
        }
        return result;
    }

    private static IEnumerable<string> RelatedCandidates(string stem)
    {
        yield return stem;
        var stripped = stem;
        while (stripped.Length > 0)
        {
            var previous = stripped;
            foreach (var suffix in VariantSuffixes)
            {
                if (stripped.Length > suffix.Length && stripped.EndsWith(suffix, StringComparison.Ordinal))
                {
                    stripped = stripped[..^suffix.Length];
                    break;
                }
            }
            stripped = NumberedVariant.Replace(stripped, string.Empty);
            if (stripped.Equals(previous, StringComparison.Ordinal))
            {
                break;
            }
            yield return stripped;
        }
    }
}

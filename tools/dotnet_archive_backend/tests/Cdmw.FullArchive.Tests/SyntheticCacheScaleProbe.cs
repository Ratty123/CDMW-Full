using System.Diagnostics;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

internal static class SyntheticCacheScaleProbe
{
    private const int Cycles = 3;
    private const int EntryCount = 200_000;
    private const int FirstPageSize = 64;

    public static async Task<int> RunAsync(string reportPath)
    {
        var rows = new List<SyntheticCacheScaleTiming>(Cycles);
        for (var cycle = 1; cycle <= Cycles; cycle++)
        {
            await using var fixture = await SyntheticCacheScaleFixture.CreateAsync(EntryCount).ConfigureAwait(false);
            var cacheRoot = Path.Combine(Path.GetTempPath(), $"cdmw-full-archive-cache-scale-report-{Guid.NewGuid():N}");
            Directory.CreateDirectory(cacheRoot);
            try
            {
                var native = new NativeArchiveCore();
                var cache = new ArchiveCacheStore(cacheRoot);
                using var sessions = new ArchiveSessionManager(native, cache);
                var queries = new ArchiveQueryService(sessions);

                var coldReady = Stopwatch.StartNew();
                var cold = Stopwatch.StartNew();
                var coldHandle = await sessions.OpenAsync(
                    new OpenArchiveRequest(fixture.Root),
                    CancellationToken.None).ConfigureAwait(false);
                cold.Stop();
                if (coldHandle.CacheHit || coldHandle.EntryCount != EntryCount)
                {
                    throw new InvalidDataException("Scaled cold cache build did not produce the expected generation.");
                }
                await ValidateFirstPageAsync(queries, coldHandle, cycle * 10 + 1).ConfigureAwait(false);
                coldReady.Stop();

                var warmReady = Stopwatch.StartNew();
                var warm = Stopwatch.StartNew();
                var warmHandle = await sessions.OpenAsync(
                    new OpenArchiveRequest(fixture.Root),
                    CancellationToken.None).ConfigureAwait(false);
                warm.Stop();
                if (!warmHandle.CacheHit || warmHandle.EntryCount != EntryCount)
                {
                    throw new InvalidDataException("Scaled warm cache open did not reuse the expected generation.");
                }
                await ValidateFirstPageAsync(queries, warmHandle, cycle * 10 + 2).ConfigureAwait(false);
                warmReady.Stop();

                var refreshReady = Stopwatch.StartNew();
                var refresh = Stopwatch.StartNew();
                var refreshHandle = await sessions.RefreshAsync(
                    new OpenArchiveRequest(fixture.Root),
                    CancellationToken.None).ConfigureAwait(false);
                refresh.Stop();
                if (refreshHandle.CacheHit || refreshHandle.EntryCount != EntryCount)
                {
                    throw new InvalidDataException("Scaled forced refresh did not replace the expected generation.");
                }
                await ValidateFirstPageAsync(queries, refreshHandle, cycle * 10 + 3).ConfigureAwait(false);
                refreshReady.Stop();

                rows.Add(new SyntheticCacheScaleTiming(
                    cycle,
                    cold.Elapsed.TotalMilliseconds,
                    coldReady.Elapsed.TotalMilliseconds,
                    warm.Elapsed.TotalMilliseconds,
                    warmReady.Elapsed.TotalMilliseconds,
                    refresh.Elapsed.TotalMilliseconds,
                    refreshReady.Elapsed.TotalMilliseconds,
                    DirectorySize(cacheRoot)));
            }
            finally
            {
                TryDelete(cacheRoot);
            }
        }

        var report = new SyntheticCacheScaleReport(
            "cdmw_full_archive_cache_scale_v2",
            DateTimeOffset.UtcNow,
            EntryCount,
            rows,
            new SyntheticCacheScaleSummary(
                Median(rows.Select(static row => row.ColdBuildMilliseconds)),
                Median(rows.Select(static row => row.ColdReadyMilliseconds)),
                Median(rows.Select(static row => row.WarmOpenMilliseconds)),
                Median(rows.Select(static row => row.WarmReadyMilliseconds)),
                Median(rows.Select(static row => row.ForcedRefreshMilliseconds)),
                Median(rows.Select(static row => row.RefreshReadyMilliseconds)),
                (long)Median(rows.Select(static row => (double)row.CacheBytes))));
        var fullPath = Path.GetFullPath(reportPath);
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath)!);
        await File.WriteAllTextAsync(
            fullPath,
            JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true })).ConfigureAwait(false);
        Console.WriteLine(fullPath);
        return 0;
    }

    private static async Task ValidateFirstPageAsync(
        ArchiveQueryService queries,
        ArchiveSessionHandle session,
        long generation)
    {
        var query = await queries.CreateAsync(
            new ArchiveQuery(session.SessionId),
            generation,
            CancellationToken.None).ConfigureAwait(false);
        var page = queries.FetchPage(
            session.SessionId,
            new FetchPageRequest(query.QueryId, 0, FirstPageSize));
        if (query.TotalMatches != EntryCount || page.Rows.Count != FirstPageSize)
        {
            throw new InvalidDataException("Scaled cache open did not produce the expected first usable page.");
        }
    }

    private static double Median(IEnumerable<double> values)
    {
        var ordered = values.Order().ToArray();
        return ordered.Length % 2 == 1
            ? ordered[ordered.Length / 2]
            : (ordered[ordered.Length / 2 - 1] + ordered[ordered.Length / 2]) / 2.0;
    }

    private static long DirectorySize(string path) =>
        Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories)
            .Sum(static file => new FileInfo(file).Length);

    private static void TryDelete(string path)
    {
        try
        {
            Directory.Delete(path, recursive: true);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // System temp cleanup is best effort after mapped-file timing cycles.
        }
    }
}

internal sealed record SyntheticCacheScaleReport(
    string Schema,
    DateTimeOffset CreatedUtc,
    int EntryCount,
    IReadOnlyList<SyntheticCacheScaleTiming> Cycles,
    SyntheticCacheScaleSummary Median);

internal sealed record SyntheticCacheScaleTiming(
    int Cycle,
    double ColdBuildMilliseconds,
    double ColdReadyMilliseconds,
    double WarmOpenMilliseconds,
    double WarmReadyMilliseconds,
    double ForcedRefreshMilliseconds,
    double RefreshReadyMilliseconds,
    long CacheBytes);

internal sealed record SyntheticCacheScaleSummary(
    double ColdBuildMilliseconds,
    double ColdReadyMilliseconds,
    double WarmOpenMilliseconds,
    double WarmReadyMilliseconds,
    double ForcedRefreshMilliseconds,
    double RefreshReadyMilliseconds,
    long CacheBytes);

internal sealed class SyntheticCacheScaleFixture : IAsyncDisposable
{
    private SyntheticCacheScaleFixture(string root)
    {
        Root = root;
        Pamt = Path.Combine(root, "base", "0.pamt");
        Paz = Path.Combine(root, "base", "0.paz");
    }

    public string Root { get; }
    private string Pamt { get; }
    private string Paz { get; }

    public static async Task<SyntheticCacheScaleFixture> CreateAsync(int entryCount)
    {
        if (entryCount < 1)
        {
            throw new ArgumentOutOfRangeException(nameof(entryCount));
        }

        var root = Path.Combine(Path.GetTempPath(), $"cdmw-full-archive-cache-scale-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        var fixture = new SyntheticCacheScaleFixture(root);
        Directory.CreateDirectory(Path.GetDirectoryName(fixture.Pamt)!);
        await File.WriteAllBytesAsync(fixture.Paz, [0x00]).ConfigureAwait(false);

        string[] pathTemplates =
        [
            "character/model/cache_{0:D7}.pac",
            "character/modelproperty/cache_{0:D7}.pac_xml",
            "character/texture/cache_{0:D7}_d.dds",
            "character/texture/cache_{0:D7}_n.dds",
            "character/physics/cache_{0:D7}.hkx",
            "gamecommon/item/cache_{0:D7}.pabgb",
            "sound/cache_{0:D7}.wem",
            "world/cache_{0:D7}.prefab",
        ];
        var entries = new CacheScaleEntry[entryCount];
        for (var index = 0; index < entries.Length; index++)
        {
            entries[index] = new CacheScaleEntry(
                string.Format(pathTemplates[index % pathTemplates.Length], index),
                0,
                1,
                1,
                0);
        }
        await File.WriteAllBytesAsync(fixture.Pamt, BuildPamt(entries)).ConfigureAwait(false);
        return fixture;
    }

    public ValueTask DisposeAsync()
    {
        try
        {
            Directory.Delete(Root, recursive: true);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // System temp cleanup is best effort after mapped-file timing cycles.
        }
        return ValueTask.CompletedTask;
    }

    private static byte[] BuildPamt(IReadOnlyList<CacheScaleEntry> entries)
    {
        using var output = new MemoryStream();
        WriteUInt32(output, 0);
        WriteUInt32(output, 1);
        WriteUInt32(output, 0);
        WriteUInt32(output, 0);
        WriteUInt32(output, 0);
        WriteUInt32(output, 0);
        WriteUInt32(output, 0);

        using var names = new MemoryStream();
        var nameOffsets = new uint[entries.Count];
        for (var index = 0; index < entries.Count; index++)
        {
            nameOffsets[index] = checked((uint)names.Position);
            WriteUInt32(names, uint.MaxValue);
            var path = System.Text.Encoding.UTF8.GetBytes(entries[index].Path);
            if (path.Length > byte.MaxValue)
            {
                throw new InvalidOperationException("Synthetic path is too long.");
            }
            names.WriteByte((byte)path.Length);
            names.Write(path);
        }
        WriteUInt32(output, checked((uint)names.Length));
        names.Position = 0;
        names.CopyTo(output);
        WriteUInt32(output, 0);
        WriteUInt32(output, checked((uint)entries.Count));
        for (var index = 0; index < entries.Count; index++)
        {
            var entry = entries[index];
            WriteUInt32(output, nameOffsets[index]);
            WriteUInt32(output, entry.Offset);
            WriteUInt32(output, entry.StoredSize);
            WriteUInt32(output, entry.OriginalSize);
            WriteUInt16(output, 0);
            WriteUInt16(output, entry.Flags);
        }
        return output.ToArray();
    }

    private static void WriteUInt16(Stream stream, ushort value)
    {
        Span<byte> bytes = stackalloc byte[2];
        System.Buffers.Binary.BinaryPrimitives.WriteUInt16LittleEndian(bytes, value);
        stream.Write(bytes);
    }

    private static void WriteUInt32(Stream stream, uint value)
    {
        Span<byte> bytes = stackalloc byte[4];
        System.Buffers.Binary.BinaryPrimitives.WriteUInt32LittleEndian(bytes, value);
        stream.Write(bytes);
    }

    private sealed record CacheScaleEntry(
        string Path,
        uint Offset,
        uint StoredSize,
        uint OriginalSize,
        ushort Flags);
}

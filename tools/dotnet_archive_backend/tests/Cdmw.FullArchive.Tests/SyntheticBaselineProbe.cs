using System.Diagnostics;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

internal static class SyntheticBaselineProbe
{
    private const int Cycles = 3;

    public static async Task<int> RunAsync(string reportPath)
    {
        var rows = new List<SyntheticTimingRow>(Cycles);
        IReadOnlyList<SyntheticIdentity>? identities = null;
        for (var cycle = 1; cycle <= Cycles; cycle++)
        {
            await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
            var cacheRoot = Path.Combine(Path.GetTempPath(), $"cdmw-full-archive-baseline-{Guid.NewGuid():N}");
            Directory.CreateDirectory(cacheRoot);
            try
            {
                var native = new NativeArchiveCore();
                var cache = new ArchiveCacheStore(cacheRoot);
                using var sessions = new ArchiveSessionManager(native, cache);
                var cold = Stopwatch.StartNew();
                var coldHandle = await sessions.OpenAsync(
                    new OpenArchiveRequest(fixture.Root),
                    CancellationToken.None).ConfigureAwait(false);
                cold.Stop();
                var session = sessions.GetRequired(coldHandle.SessionId);
                var cycleIdentities = Enumerable.Range(0, checked((int)session.Index.EntryCount))
                    .Select(index => session.ReadEntry(index))
                    .Select(static entry => new SyntheticIdentity(
                        entry.EntryId,
                        entry.Path,
                        Path.GetFileName(entry.SourcePamt),
                        entry.PazIndex,
                        entry.Offset,
                        entry.StoredSize,
                        entry.OriginalSize,
                        entry.Flags))
                    .ToArray();
                identities ??= cycleIdentities;
                if (!identities.SequenceEqual(cycleIdentities))
                {
                    throw new InvalidDataException("Synthetic identity baseline changed between isolated cycles.");
                }

                var warm = Stopwatch.StartNew();
                var warmHandle = await sessions.OpenAsync(
                    new OpenArchiveRequest(fixture.Root),
                    CancellationToken.None).ConfigureAwait(false);
                warm.Stop();
                if (!warmHandle.CacheHit)
                {
                    throw new InvalidDataException("Synthetic warm baseline did not hit the cache.");
                }

                var refresh = Stopwatch.StartNew();
                _ = await sessions.RefreshAsync(
                    new OpenArchiveRequest(fixture.Root),
                    CancellationToken.None).ConfigureAwait(false);
                refresh.Stop();
                rows.Add(new SyntheticTimingRow(
                    cycle,
                    cold.Elapsed.TotalMilliseconds,
                    warm.Elapsed.TotalMilliseconds,
                    refresh.Elapsed.TotalMilliseconds,
                    DirectorySize(cacheRoot)));
            }
            finally
            {
                TryDelete(cacheRoot);
            }
        }

        var report = new SyntheticBaselineReport(
            "cdmw_full_archive_synthetic_baseline_v2",
            DateTimeOffset.UtcNow,
            Environment.MachineName,
            Environment.OSVersion.ToString(),
            Environment.Version.ToString(),
            identities ?? [],
            rows,
            new SyntheticTimingSummary(
                Median(rows.Select(static row => row.ColdBuildMilliseconds)),
                Median(rows.Select(static row => row.WarmOpenMilliseconds)),
                Median(rows.Select(static row => row.ForcedRefreshMilliseconds)),
                (long)Median(rows.Select(static row => (double)row.CacheBytes))));
        var fullPath = Path.GetFullPath(reportPath);
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath)!);
        await File.WriteAllTextAsync(
            fullPath,
            JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true })).ConfigureAwait(false);
        Console.WriteLine(fullPath);
        return 0;
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

internal sealed record SyntheticBaselineReport(
    string Schema,
    DateTimeOffset CreatedUtc,
    string Machine,
    string OperatingSystem,
    string DotNetRuntime,
    IReadOnlyList<SyntheticIdentity> Identities,
    IReadOnlyList<SyntheticTimingRow> Cycles,
    SyntheticTimingSummary Median);

internal sealed record SyntheticIdentity(
    long EntryId,
    string Path,
    string SourcePamt,
    int PazIndex,
    long Offset,
    long StoredSize,
    long OriginalSize,
    int Flags);

internal sealed record SyntheticTimingRow(
    int Cycle,
    double ColdBuildMilliseconds,
    double WarmOpenMilliseconds,
    double ForcedRefreshMilliseconds,
    long CacheBytes);

internal sealed record SyntheticTimingSummary(
    double ColdBuildMilliseconds,
    double WarmOpenMilliseconds,
    double ForcedRefreshMilliseconds,
    long CacheBytes);

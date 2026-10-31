using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

/// <summary>
/// Read-only timing probe against a real package root. It opens the archive into its
/// own cache root, then compiles a fixed query set several times, with and without the
/// name index, and records each result's entry count and a SHA-256 of its entry-id
/// order so a faster implementation can be checked for identical results.
/// </summary>
internal static class RealArchiveQueryProbe
{
    private const int Runs = 3;

    public static async Task<int> RunAsync(string packageRoot, string cacheRoot, string reportPath, bool skipCold)
    {
        Directory.CreateDirectory(cacheRoot);
        var report = new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_real_archive_query_probe_v1",
            ["package_root"] = packageRoot,
            ["processor_count"] = Environment.ProcessorCount,
        };
        var native = new NativeArchiveCore();
        var cache = new ArchiveCacheStore(cacheRoot);

        if (!skipCold)
        {
            // Process-warm, OS-cache-warm cold builds: RefreshAsync rebuilds the index.
            var coldRuns = new List<double>();
            for (var run = 0; run < Runs; run++)
            {
                using var coldSessions = new ArchiveSessionManager(native, cache);
                var watch = Stopwatch.StartNew();
                var handle = await coldSessions.RefreshAsync(new OpenArchiveRequest(packageRoot), CancellationToken.None).ConfigureAwait(false);
                watch.Stop();
                if (handle.CacheHit)
                {
                    throw new InvalidDataException("Refresh reused the cache.");
                }
                coldRuns.Add(watch.Elapsed.TotalMilliseconds);
                Console.WriteLine($"cold build {run + 1}: {watch.Elapsed.TotalMilliseconds:F0} ms, {handle.EntryCount:N0} entries");
            }
            report["cold_build_ms"] = Summary(coldRuns);
        }

        var warmRuns = new List<double>();
        for (var run = 0; run < Runs; run++)
        {
            using var warmSessions = new ArchiveSessionManager(native, cache);
            var watch = Stopwatch.StartNew();
            var handle = await warmSessions.OpenAsync(new OpenArchiveRequest(packageRoot), CancellationToken.None).ConfigureAwait(false);
            watch.Stop();
            if (!handle.CacheHit)
            {
                throw new InvalidDataException("Warm open rebuilt the cache.");
            }
            warmRuns.Add(watch.Elapsed.TotalMilliseconds);
            Console.WriteLine($"warm open {run + 1}: {watch.Elapsed.TotalMilliseconds:F0} ms");
        }
        report["warm_open_ms"] = Summary(warmRuns);

        using var sessions = new ArchiveSessionManager(native, cache);
        var queries = new ArchiveQueryService(sessions);
        var session = await sessions.OpenAsync(new OpenArchiveRequest(packageRoot), CancellationToken.None).ConfigureAwait(false);
        report["entry_count"] = session.EntryCount;

        report["queries_without_names"] = await RunQueriesAsync(queries, session.SessionId).ConfigureAwait(false);

        var names = new ArchiveNameIndexService(sessions, cache, native);
        var namesWatch = Stopwatch.StartNew();
        var nameIndex = await names.WarmAsync(session.SessionId, CancellationToken.None).ConfigureAwait(false);
        namesWatch.Stop();
        report["name_index_ms"] = namesWatch.Elapsed.TotalMilliseconds;
        report["name_index_entries"] = nameIndex.ExactNames.Count + nameIndex.RelatedNames.Count;
        Console.WriteLine($"name index: {namesWatch.Elapsed.TotalMilliseconds:F0} ms, {nameIndex.ExactNames.Count:N0} exact, {nameIndex.RelatedNames.Count:N0} related");

        report["queries_with_names"] = await RunQueriesAsync(queries, session.SessionId).ConfigureAwait(false);

        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(reportPath))!);
        await File.WriteAllTextAsync(reportPath, JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true })).ConfigureAwait(false);
        Console.WriteLine($"Report: {reportPath}");
        return 0;
    }

    private static async Task<List<Dictionary<string, object?>>> RunQueriesAsync(ArchiveQueryService queries, string sessionId)
    {
        var rows = new List<Dictionary<string, object?>>();
        foreach (var (name, query) in QuerySet(sessionId))
        {
            var times = new List<double>();
            long count = 0;
            var hash = string.Empty;
            for (var run = 0; run < Runs; run++)
            {
                var watch = Stopwatch.StartNew();
                var handle = await queries.CreateAsync(query, run + 1, CancellationToken.None).ConfigureAwait(false);
                watch.Stop();
                times.Add(watch.Elapsed.TotalMilliseconds);
                var ids = queries.GetEntryIds(sessionId, handle.QueryId);
                var runHash = HashIds(ids);
                if (run > 0 && (runHash != hash || ids.Count != count))
                {
                    throw new InvalidDataException($"Query {name} is not deterministic.");
                }
                hash = runHash;
                count = ids.Count;
            }
            Console.WriteLine($"{name,-28} {Median(times),9:F1} ms  {count,9:N0} rows  {hash[..16]}");
            rows.Add(new Dictionary<string, object?>
            {
                ["name"] = name,
                ["count"] = count,
                ["sha256"] = hash,
                ["ms"] = Summary(times),
            });
        }
        return rows;
    }

    private static IEnumerable<(string Name, ArchiveQuery Query)> QuerySet(string session)
    {
        yield return ("text_sword", new ArchiveQuery(session, IncludeText: "sword"));
        yield return ("text_kliff", new ArchiveQuery(session, IncludeText: "kliff"));
        yield return ("text_two_terms", new ArchiveQuery(session, IncludeText: "helm; boots"));
        yield return ("text_no_match", new ArchiveQuery(session, IncludeText: "zzqqxxnomatch"));
        yield return ("wildcard_pac_0001", new ArchiveQuery(session, IncludeText: "*_0001.pac"));
        yield return ("exclude_dds", new ArchiveQuery(session, IncludeText: "armor", ExcludeText: ".dds"));
        yield return ("folder_character", new ArchiveQuery(session, Folder: "0009/character"));
        yield return ("package_0012", new ArchiveQuery(session, Packages: ["0012"]));
        yield return ("package_wildcard", new ArchiveQuery(session, Packages: ["00*1"]));
        yield return ("role_model", new ArchiveQuery(session, Roles: [ArchiveEntryRole.Model]));
        yield return ("active_overrides", new ArchiveQuery(session, ActiveOverridesOnly: true));
        yield return ("min_size_8mb", new ArchiveQuery(session, MinimumSize: 8L << 20));
        yield return ("previewable", new ArchiveQuery(session, PreviewableOnly: true));
        yield return ("technical_suffix", new ArchiveQuery(session, TechnicalSuffixes: ["*_n.dds", "*_sp.dds"]));
        yield return ("ext_pac", new ArchiveQuery(session, Extensions: [".pac"]));
        yield return ("ext_pac_sort_name", new ArchiveQuery(session, Extensions: [".pac"], SortField: ArchiveSortField.Name, SortActive: true));
        yield return ("text_sort_size_desc", new ArchiveQuery(session, IncludeText: "cd_", SortField: ArchiveSortField.OriginalSize, SortActive: true, SortDescending: true));
        yield return ("sort_path_all", new ArchiveQuery(session, SortField: ArchiveSortField.Path, SortActive: true));
        yield return ("sort_known_name_all", new ArchiveQuery(session, SortField: ArchiveSortField.KnownName, SortActive: true));
        yield return ("text_sort_role", new ArchiveQuery(session, IncludeText: "phw", SortField: ArchiveSortField.Role, SortActive: true));
    }

    private static string HashIds(IReadOnlyList<long> ids)
    {
        using var sha = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        Span<byte> buffer = stackalloc byte[8];
        foreach (var id in ids)
        {
            BitConverter.TryWriteBytes(buffer, id);
            sha.AppendData(buffer);
        }
        return Convert.ToHexString(sha.GetHashAndReset()).ToLowerInvariant();
    }

    private static Dictionary<string, object> Summary(List<double> values) => new()
    {
        ["runs"] = values.Select(static value => Math.Round(value, 1)).ToArray(),
        ["median"] = Math.Round(Median(values), 1),
    };

    private static double Median(List<double> values)
    {
        var sorted = values.Order().ToArray();
        return sorted.Length % 2 == 1 ? sorted[sorted.Length / 2] : (sorted[sorted.Length / 2 - 1] + sorted[sorted.Length / 2]) / 2;
    }
}

using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

/// <summary>
/// Read-only decode and export timing probe against a real package root. Single-entry
/// decodes record a SHA-256 of the decoded bytes; the bulk export records one hash
/// over the exported tree (relative paths and file contents, manifest excluded), so a
/// faster implementation can be checked for byte-identical output.
/// </summary>
internal static class RealArchiveExportProbe
{
    private const int Runs = 3;
    private const int DecodeRuns = 5;

    public static async Task<int> RunAsync(string packageRoot, string cacheRoot, string outputRoot, string reportPath, string exportText, bool noFlush = false)
    {
        Directory.CreateDirectory(outputRoot);
        var native = new NativeArchiveCore();
        var cache = new ArchiveCacheStore(cacheRoot);
        using var sessions = new ArchiveSessionManager(native, cache);
        var queries = new ArchiveQueryService(sessions);
        var lookups = new ArchiveLookupService(sessions, cache, native);
        var exports = new ArchiveExportService(sessions, queries, lookups, native);
        var session = await sessions.OpenAsync(new OpenArchiveRequest(packageRoot), CancellationToken.None).ConfigureAwait(false);
        var live = sessions.GetRequired(session.SessionId);
        var report = new Dictionary<string, object?>
        {
            ["schema"] = "cdmw_real_archive_export_probe_v1",
            ["package_root"] = packageRoot,
            ["processor_count"] = Environment.ProcessorCount,
        };

        var decodes = new List<Dictionary<string, object?>>();
        foreach (var extension in new[] { ".dds", ".pac", ".pam" })
        {
            var handle = await queries.CreateAsync(
                new ArchiveQuery(session.SessionId, Extensions: [extension], SortField: ArchiveSortField.OriginalSize, SortActive: true, SortDescending: true),
                1,
                CancellationToken.None).ConfigureAwait(false);
            foreach (var entryId in queries.GetEntryIds(session.SessionId, handle.QueryId).Take(2))
            {
                var entry = live.ReadEntry(entryId);
                var times = new List<double>();
                var hash = string.Empty;
                var note = string.Empty;
                for (var run = 0; run < DecodeRuns; run++)
                {
                    var watch = Stopwatch.StartNew();
                    var decoded = native.Decode(entry);
                    watch.Stop();
                    times.Add(watch.Elapsed.TotalMilliseconds);
                    hash = Convert.ToHexString(SHA256.HashData(decoded.Bytes)).ToLowerInvariant();
                    note = decoded.Note;
                }
                Console.WriteLine($"decode {entry.Path} ({entry.StoredSize / 1048576.0:F1} -> {entry.OriginalSize / 1048576.0:F1} MiB, {note}): {Median(times):F1} ms {hash[..16]}");
                decodes.Add(new Dictionary<string, object?>
                {
                    ["path"] = entry.Path,
                    ["stored_size"] = entry.StoredSize,
                    ["original_size"] = entry.OriginalSize,
                    ["note"] = note,
                    ["sha256"] = hash,
                    ["ms"] = Summary(times),
                });
            }
        }
        report["decodes"] = decodes;

        var exportQuery = await queries.CreateAsync(new ArchiveQuery(session.SessionId, IncludeText: exportText), 1, CancellationToken.None).ConfigureAwait(false);
        var exportIds = queries.GetEntryIds(session.SessionId, exportQuery.QueryId);
        var exportBytes = exportIds.Sum(id => live.ReadEntry(id).OriginalSize);
        report["export_selection"] = new Dictionary<string, object?> { ["text"] = exportText, ["entries"] = exportIds.Count, ["original_bytes"] = exportBytes };
        Console.WriteLine($"export selection '{exportText}': {exportIds.Count:N0} entries, {exportBytes / 1048576.0:F0} MiB");
        var exportTimes = new List<double>();
        var treeHash = string.Empty;
        for (var run = 0; run < Runs; run++)
        {
            var destination = Path.Combine(outputRoot, $"export-{run}");
            if (Directory.Exists(destination))
            {
                Directory.Delete(destination, recursive: true);
            }
            var watch = Stopwatch.StartNew();
            var result = await exports.ExportAsync(
                new ArchiveExportRequest(session.SessionId, ArchiveExportSelectionKind.Query, destination, QueryId: exportQuery.QueryId, FlushToDisk: !noFlush),
                CancellationToken.None).ConfigureAwait(false);
            watch.Stop();
            exportTimes.Add(watch.Elapsed.TotalMilliseconds);
            var runHash = HashTree(destination);
            if (run > 0 && runHash != treeHash)
            {
                throw new InvalidDataException("Export output is not deterministic.");
            }
            treeHash = runHash;
            Console.WriteLine($"export run {run + 1}: {watch.Elapsed.TotalMilliseconds:F0} ms, {result.Exported:N0} files, tree {treeHash[..16]}");
            Directory.Delete(destination, recursive: true);
        }
        report["export_ms"] = Summary(exportTimes);
        report["export_tree_sha256"] = treeHash;

        await File.WriteAllTextAsync(reportPath, JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true })).ConfigureAwait(false);
        Console.WriteLine($"Report: {reportPath}");
        return 0;
    }

    private static string HashTree(string root)
    {
        using var sha = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        foreach (var file in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories)
                     .Select(path => (Full: path, Relative: Path.GetRelativePath(root, path).Replace('\\', '/')))
                     .Where(static item => !item.Relative.Equals("cdmw-export-manifest.json", StringComparison.OrdinalIgnoreCase))
                     .OrderBy(static item => item.Relative, StringComparer.Ordinal))
        {
            sha.AppendData(System.Text.Encoding.UTF8.GetBytes(file.Relative + "\n"));
            sha.AppendData(SHA256.HashData(File.ReadAllBytes(file.Full)));
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

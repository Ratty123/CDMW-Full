using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;
using Cdmw.FullArchive.Worker;

namespace Cdmw.FullArchive.Tests;

internal static class FullArchiveTestRunner
{
    public static async Task<int> RunAsync()
    {
        var tests = new (string Name, Func<Task> Run)[]
        {
            ("native_and_generation_cache", NativeAndGenerationCacheAsync),
            ("query_lookup_search_prepare_export", QueryLookupSearchPrepareExportAsync),
            ("bounded_protocol_reader", BoundedProtocolReaderAsync),
            ("source_independence_and_baseline", SourceIndependenceAndBaselineAsync),
            ("stdio_worker_ping_shutdown", StdioWorkerPingShutdownAsync),
        };
        var failures = new List<string>();
        foreach (var test in tests)
        {
            try
            {
                await test.Run().ConfigureAwait(false);
                Console.WriteLine($"PASS {test.Name}");
            }
            catch (Exception exception)
            {
                failures.Add($"{test.Name}: {exception}");
                Console.Error.WriteLine($"FAIL {test.Name}: {exception.Message}");
            }
        }
        if (failures.Count == 0)
        {
            Console.WriteLine($"CDMW full archive tests: PASS ({tests.Length})");
            return 0;
        }
        Console.Error.WriteLine(string.Join(Environment.NewLine + Environment.NewLine, failures));
        return 1;
    }

    private static async Task NativeAndGenerationCacheAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var cacheRoot = TempDirectory("cache");
        try
        {
            var native = new NativeArchiveCore();
            native.EnsureCompatible();
            var cache = new ArchiveCacheStore(cacheRoot);
            using var sessions = new ArchiveSessionManager(native, cache);
            var coldStarted = Stopwatch.StartNew();
            var first = await sessions.OpenAsync(
                new OpenArchiveRequest(fixture.Root),
                CancellationToken.None).ConfigureAwait(false);
            coldStarted.Stop();
            Require(first.EntryCount == 4, "synthetic entry count changed");
            Require(first.IndexVersion == 2, "full archive index version changed");
            Require(!first.CacheHit, "first generation unexpectedly reported a cache hit");
            var firstSession = sessions.GetRequired(first.SessionId);
            Require(
                firstSession.ReadEntry(0).Path == "binary/blob.bin" &&
                firstSession.ReadEntry(1).Path == "materials/sample.material" &&
                firstSession.ReadEntry(2).Path == "text/hello.txt" &&
                firstSession.ReadEntry(3).Path == "texture/test.dds",
                "deterministic path and identity ordering changed");

            var rootId = ArchiveCacheStore.DeriveRootId(fixture.Root);
            var family = Path.Combine(cacheRoot, "catalogue_v2", rootId);
            Require(File.Exists(Path.Combine(family, "current.json")), "current pointer was not published");
            var firstGeneration = Directory.GetDirectories(Path.Combine(family, "generations"))
                .Single(path => !Path.GetFileName(path).StartsWith(".", StringComparison.Ordinal));
            Require(File.Exists(Path.Combine(firstGeneration, "archive.ali")), "base index is missing");
            Require(File.Exists(Path.Combine(firstGeneration, "manifest.json")), "generation manifest is missing");

            var warmStarted = Stopwatch.StartNew();
            var second = await sessions.OpenAsync(
                new OpenArchiveRequest(fixture.Root),
                CancellationToken.None).ConfigureAwait(false);
            warmStarted.Stop();
            Require(second.CacheHit, "warm open did not reuse the current generation");
            Require(second.Fingerprint == first.Fingerprint, "warm fingerprint changed");

            File.SetLastWriteTimeUtc(fixture.Pamt, DateTime.UtcNow.AddSeconds(5));
            var refreshed = await sessions.RefreshAsync(
                new OpenArchiveRequest(fixture.Root),
                CancellationToken.None).ConfigureAwait(false);
            Require(refreshed.Fingerprint != first.Fingerprint, "refresh did not observe changed source metadata");
            Require(firstSession.ReadEntry(2).Path == "text/hello.txt", "old mapped generation stopped serving its active session");
            Require(Directory.GetDirectories(Path.Combine(family, "generations")).Length >= 2, "active prior generation was pruned");

            var health = await cache.InspectAsync(fixture.Root, CancellationToken.None).ConfigureAwait(false);
            Require(health.State == "current", $"cache health is not current: {health.State} {health.Reason}");
            Require(coldStarted.Elapsed >= TimeSpan.Zero && warmStarted.Elapsed >= TimeSpan.Zero, "timing capture failed");
        }
        finally
        {
            DeleteDirectory(cacheRoot);
        }
    }

    private static async Task QueryLookupSearchPrepareExportAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var cacheRoot = TempDirectory("operations-cache");
        var exportRoot = fixture.OutputRoot;
        try
        {
            var native = new NativeArchiveCore();
            var cache = new ArchiveCacheStore(cacheRoot);
            using var sessions = new ArchiveSessionManager(native, cache);
            var sessionHandle = await sessions.OpenAsync(
                new OpenArchiveRequest(fixture.Root),
                CancellationToken.None).ConfigureAwait(false);
            var queries = new ArchiveQueryService(sessions);
            var lookup = new ArchiveLookupService(sessions, cache);
            var names = new ArchiveNameIndexService(sessions, cache);
            var query = await queries.CreateAsync(
                new ArchiveQuery(sessionHandle.SessionId),
                generation: 7,
                CancellationToken.None).ConfigureAwait(false);
            Require(query.TotalMatches == 4, "unfiltered query count changed");
            var page = queries.FetchPage(sessionHandle.SessionId, new FetchPageRequest(query.QueryId, 0, 2));
            Require(page.Rows.Count == 2 && page.Generation == 7, "paged query result is invalid");
            Require(page.Rows[0].Path == "binary/blob.bin", "path ordering changed");

            var materialQuery = await queries.CreateAsync(
                new ArchiveQuery(sessionHandle.SessionId, Extensions: [".material"]),
                generation: 8,
                CancellationToken.None).ConfigureAwait(false);
            var materialPage = queries.FetchPage(sessionHandle.SessionId, new FetchPageRequest(materialQuery.QueryId));
            Require(materialPage.TotalMatches == 1 && materialPage.Rows[0].Path == "materials/sample.material", "extension filter changed");

            await lookup.WarmAsync(sessionHandle.SessionId, CancellationToken.None).ConfigureAwait(false);
            var exact = await lookup.ResolveAsync(
                new ArchiveLookupRequest(
                    sessionHandle.SessionId,
                    ArchiveLookupKind.ExactPaths,
                    Values: ["text/hello.txt"]),
                CancellationToken.None).ConfigureAwait(false);
            Require(exact.TotalMatches == 1 && exact.Entries[0].EntryId == 2, "exact-path lookup changed");
            var facets = await lookup.FacetsAsync(sessionHandle.SessionId, CancellationToken.None).ConfigureAwait(false);
            Require(facets.Extensions.Any(static facet => facet.Key == ".txt" && facet.Count == 1), "extension facets changed");
            var generationPath = sessions.GetRequired(sessionHandle.SessionId).GenerationPath;
            Require(File.Exists(Path.Combine(generationPath, "lookups.bin")), "lookup index was not published");

            await names.WarmAsync(sessionHandle.SessionId, CancellationToken.None).ConfigureAwait(false);
            Require(File.Exists(Path.Combine(generationPath, "names.bin")), "name index was not published");

            var searchBatches = new List<ArchiveTextSearchBatch>();
            var search = new ArchiveTextSearchService(sessions, native);
            var finalSearch = await search.SearchAsync(
                new ArchiveTextSearchRequest(sessionHandle.SessionId, "Crimson", BatchSize: 1),
                batch =>
                {
                    searchBatches.Add(batch);
                    return Task.CompletedTask;
                },
                CancellationToken.None).ConfigureAwait(false);
            var searchMatches = searchBatches.SelectMany(static batch => batch.Matches).ToArray();
            Require(finalSearch.IsFinal && searchMatches.Length == 1, "archive text search result changed");
            Require(searchMatches[0].Path == "text/hello.txt" && searchMatches[0].Line == 1, "text match location changed");

            var preparation = new ArchiveEntryPreparationService(sessions, native);
            var prepared = await preparation.PrepareAsync(
                new PrepareEntryRequest(sessionHandle.SessionId, 2),
                CancellationToken.None).ConfigureAwait(false);
            Require(await File.ReadAllTextAsync(prepared.PreparedPath).ConfigureAwait(false) == "Hello Crimson\nline 2", "prepared bytes changed");

            var exports = new ArchiveExportService(sessions, queries, lookup, native);
            var exported = await exports.ExportAsync(
                new ArchiveExportRequest(
                    sessionHandle.SessionId,
                    ArchiveExportSelectionKind.Query,
                    exportRoot,
                    QueryId: materialQuery.QueryId,
                    CollisionPolicy: ArchiveExportCollisionPolicy.Overwrite),
                CancellationToken.None).ConfigureAwait(false);
            Require(exported.Exported == 1 && !exported.Cancelled, "query-token export failed");
            var materialPath = Path.Combine(exportRoot, "materials", "sample.material");
            Require(await File.ReadAllTextAsync(materialPath).ConfigureAwait(false) == "material alpha", "exported decoded bytes changed");
            await File.WriteAllTextAsync(materialPath, "preserve me").ConfigureAwait(false);
            var cancelled = await exports.ExportAsync(
                new ArchiveExportRequest(
                    sessionHandle.SessionId,
                    ArchiveExportSelectionKind.EntryIds,
                    exportRoot,
                    EntryIds: [1],
                    CollisionPolicy: ArchiveExportCollisionPolicy.Cancel),
                CancellationToken.None).ConfigureAwait(false);
            Require(cancelled.Cancelled, "collision cancellation was not reported");
            Require(await File.ReadAllTextAsync(materialPath).ConfigureAwait(false) == "preserve me", "cancelled export changed its destination");

            for (var generation = 10; generation < 15; generation++)
            {
                _ = await queries.CreateAsync(
                    new ArchiveQuery(sessionHandle.SessionId, MinimumSize: generation),
                    generation,
                    CancellationToken.None).ConfigureAwait(false);
            }
            Expect<KeyNotFoundException>(() => queries.FetchPage(sessionHandle.SessionId, new FetchPageRequest(query.QueryId)));
        }
        finally
        {
            DeleteDirectory(cacheRoot);
            DeleteDirectory(exportRoot);
        }
    }

    private static async Task BoundedProtocolReaderAsync()
    {
        var oversized = new byte[WorkerProtocol.MaximumMessageBytes + 2];
        Array.Fill(oversized, (byte)'x');
        oversized[^1] = (byte)'\n';
        var valid = Encoding.UTF8.GetBytes("{}\n");
        await using var stream = new MemoryStream(oversized.Concat(valid).ToArray());
        var reader = new BoundedLineReader(stream, WorkerProtocol.MaximumMessageBytes);
        await ExpectAsync<InvalidDataException>(() => reader.ReadLineAsync(CancellationToken.None)).ConfigureAwait(false);
        Require(await reader.ReadLineAsync(CancellationToken.None).ConfigureAwait(false) == "{}", "bounded reader did not recover at the next message");
    }

    private static async Task SourceIndependenceAndBaselineAsync()
    {
        var root = RepositoryRoot();
        var backendRoot = Path.Combine(root, "tools", "dotnet_archive_backend");
        var sourceFiles = Directory.EnumerateFiles(backendRoot, "*", SearchOption.AllDirectories)
            .Where(static path => path.EndsWith(".cs", StringComparison.OrdinalIgnoreCase) ||
                path.EndsWith(".csproj", StringComparison.OrdinalIgnoreCase) ||
                path.EndsWith(".slnx", StringComparison.OrdinalIgnoreCase))
            .Where(static path => !path.Contains($"{Path.DirectorySeparatorChar}bin{Path.DirectorySeparatorChar}", StringComparison.OrdinalIgnoreCase) &&
                !path.Contains($"{Path.DirectorySeparatorChar}obj{Path.DirectorySeparatorChar}", StringComparison.OrdinalIgnoreCase))
            .ToArray();
        var liteNamespace = "Cdmw." + "ArchiveLite";
        var liteBinary = "cdmw-" + "archive-core";
        var liteAbi = "cdmw_" + "archive_";
        foreach (var path in sourceFiles)
        {
            var text = await File.ReadAllTextAsync(path).ConfigureAwait(false);
            Require(!text.Contains(liteNamespace, StringComparison.Ordinal), $"Archive Lite namespace leaked into {path}");
            Require(!text.Contains(liteBinary, StringComparison.Ordinal), $"Archive Lite native binary leaked into {path}");
            Require(!text.Contains(liteAbi, StringComparison.Ordinal), $"Archive Lite native ABI leaked into {path}");
        }

        var baselinePath = Path.Combine(backendRoot, "baselines", "synthetic-v2.json");
        using var baseline = JsonDocument.Parse(await File.ReadAllTextAsync(baselinePath).ConfigureAwait(false));
        var rootElement = baseline.RootElement;
        Require(rootElement.GetProperty("entry_count").GetInt32() == 4, "synthetic baseline entry count changed");
        var paths = rootElement.GetProperty("identities").EnumerateArray()
            .Select(static row => row.GetProperty("path").GetString())
            .ToArray();
        Require(
            paths.SequenceEqual(["binary/blob.bin", "materials/sample.material", "text/hello.txt", "texture/test.dds"]),
            "synthetic baseline path order changed");
    }

    private static async Task StdioWorkerPingShutdownAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var cacheRoot = TempDirectory("worker-cache");
        try
        {
            var executable = WorkerExecutable();
            Require(File.Exists(executable), $"worker executable is missing: {executable}");
            using var process = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = executable,
                    UseShellExecute = false,
                    RedirectStandardInput = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true,
                },
                EnableRaisingEvents = true,
            };
            process.StartInfo.ArgumentList.Add("--cache-root");
            process.StartInfo.ArgumentList.Add(cacheRoot);
            Require(process.Start(), "worker process did not start");
            try
            {
                var ping = WorkerProtocol.Request(
                    Guid.NewGuid(),
                    11,
                    WorkerProtocol.Ping,
                    new PingRequest("tests"));
                await SendAsync(process, ping).ConfigureAwait(false);
                var started = await ReadMessageAsync(process).ConfigureAwait(false);
                var result = await ReadMessageAsync(process).ConfigureAwait(false);
                Require(started.Status == WorkerMessageStatus.Started, "worker did not acknowledge ping");
                Require(result.Status == WorkerMessageStatus.Result, "worker ping did not complete");
                var pingResult = WorkerProtocol.ReadPayload<PingResult>(result);
                Require(pingResult is { ProtocolVersion: 2, NativeAbiVersion: 1, IndexVersion: 2 }, "worker ping compatibility data changed");

                var openId = Guid.NewGuid();
                await SendAsync(process, WorkerProtocol.Request(
                    openId,
                    20,
                    WorkerProtocol.OpenArchive,
                    new OpenArchiveRequest(fixture.Root))).ConfigureAwait(false);
                var openResult = await ReadTerminalAsync(process, openId).ConfigureAwait(false);
                Require(openResult.Status == WorkerMessageStatus.Result, "worker archive open failed");
                var session = WorkerProtocol.ReadPayload<ArchiveSessionHandle>(openResult)
                    ?? throw new InvalidDataException("worker open result has no session handle");
                Require(session.EntryCount == 4 && openResult.SessionId == session.SessionId, "worker open session envelope changed");

                var queryId = Guid.NewGuid();
                await SendAsync(process, WorkerProtocol.Request(
                    queryId,
                    21,
                    WorkerProtocol.CreateQuery,
                    new CreateQueryRequest(new ArchiveQuery(session.SessionId, Extensions: [".txt"])),
                    session.SessionId)).ConfigureAwait(false);
                var queryResult = await ReadTerminalAsync(process, queryId).ConfigureAwait(false);
                var query = WorkerProtocol.ReadPayload<ArchiveQueryHandle>(queryResult)
                    ?? throw new InvalidDataException("worker query result is empty");
                Require(query.TotalMatches == 1 && query.Generation == 21, "worker query generation or count changed");

                var pageId = Guid.NewGuid();
                await SendAsync(process, WorkerProtocol.Request(
                    pageId,
                    21,
                    WorkerProtocol.FetchPage,
                    new FetchPageRequest(query.QueryId),
                    session.SessionId)).ConfigureAwait(false);
                var pageResult = await ReadTerminalAsync(process, pageId).ConfigureAwait(false);
                var page = WorkerProtocol.ReadPayload<ArchivePage>(pageResult)
                    ?? throw new InvalidDataException("worker page result is empty");
                Require(page.Rows.Count == 1 && page.Rows[0].Path == "text/hello.txt", "worker page result changed");

                var concurrentA = Guid.NewGuid();
                var concurrentB = Guid.NewGuid();
                await SendAsync(process, WorkerProtocol.Request(
                    concurrentA,
                    30,
                    WorkerProtocol.Ping,
                    new PingRequest("concurrent-a"))).ConfigureAwait(false);
                await SendAsync(process, WorkerProtocol.Request(
                    concurrentB,
                    31,
                    WorkerProtocol.Ping,
                    new PingRequest("concurrent-b"))).ConfigureAwait(false);
                var concurrentResults = new Dictionary<Guid, WorkerMessage>();
                while (concurrentResults.Count < 2)
                {
                    var message = await ReadMessageAsync(process).ConfigureAwait(false);
                    if (message.Status == WorkerMessageStatus.Result &&
                        (message.RequestId == concurrentA || message.RequestId == concurrentB))
                    {
                        concurrentResults[message.RequestId] = message;
                    }
                }
                Require(concurrentResults.Count == 2, "worker did not complete concurrent requests");

                var refreshId = Guid.NewGuid();
                var cancelId = Guid.NewGuid();
                await SendAsync(process, WorkerProtocol.Request(
                    refreshId,
                    40,
                    WorkerProtocol.RefreshArchive,
                    new OpenArchiveRequest(fixture.Root, ForceRefresh: true))).ConfigureAwait(false);
                await SendAsync(process, WorkerProtocol.Request(
                    cancelId,
                    41,
                    WorkerProtocol.Cancel,
                    new CancelRequest(refreshId))).ConfigureAwait(false);
                WorkerMessage? refreshTerminal = null;
                WorkerMessage? cancelTerminal = null;
                while (refreshTerminal is null || cancelTerminal is null)
                {
                    var message = await ReadMessageAsync(process).ConfigureAwait(false);
                    if (message.RequestId == refreshId && message.Status is WorkerMessageStatus.Result or WorkerMessageStatus.Cancelled or WorkerMessageStatus.Error)
                    {
                        refreshTerminal = message;
                    }
                    if (message.RequestId == cancelId && message.Status == WorkerMessageStatus.Result)
                    {
                        cancelTerminal = message;
                    }
                }
                Require(cancelTerminal.Payload?.GetProperty("accepted").GetBoolean() == true, "worker did not accept cooperative cancellation");
                Require(refreshTerminal.Status == WorkerMessageStatus.Cancelled, "cancelled refresh published a terminal result");

                var shutdown = WorkerProtocol.Request(
                    Guid.NewGuid(),
                    12,
                    WorkerProtocol.Shutdown,
                    new { });
                await SendAsync(process, shutdown).ConfigureAwait(false);
                var shutdownResult = await ReadMessageAsync(process).ConfigureAwait(false);
                Require(shutdownResult.Status == WorkerMessageStatus.Result, "worker shutdown was not acknowledged");
                await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(10)).ConfigureAwait(false);
                Require(process.ExitCode == 0, await process.StandardError.ReadToEndAsync().ConfigureAwait(false));
            }
            finally
            {
                if (!process.HasExited)
                {
                    process.Kill(entireProcessTree: true);
                    await process.WaitForExitAsync().ConfigureAwait(false);
                }
            }
        }
        finally
        {
            DeleteDirectory(cacheRoot);
        }
    }

    private static Task SendAsync(Process process, WorkerMessage message)
    {
        var json = JsonSerializer.Serialize(message, WorkerProtocol.JsonOptions);
        Require(Encoding.UTF8.GetByteCount(json) <= WorkerProtocol.MaximumMessageBytes, "test request exceeds protocol limit");
        return SendLineAsync(process, json);
    }

    private static async Task SendLineAsync(Process process, string line)
    {
        await process.StandardInput.WriteLineAsync(line).ConfigureAwait(false);
        await process.StandardInput.FlushAsync().ConfigureAwait(false);
    }

    private static async Task<WorkerMessage> ReadMessageAsync(Process process)
    {
        var line = await process.StandardOutput.ReadLineAsync()
            .WaitAsync(TimeSpan.FromSeconds(10)).ConfigureAwait(false);
        return JsonSerializer.Deserialize<WorkerMessage>(
            line ?? throw new EndOfStreamException("Worker stdout closed before a protocol response."),
            WorkerProtocol.JsonOptions) ?? throw new InvalidDataException("Worker returned an empty protocol response.");
    }

    private static async Task<WorkerMessage> ReadTerminalAsync(Process process, Guid requestId)
    {
        while (true)
        {
            var message = await ReadMessageAsync(process).ConfigureAwait(false);
            if (message.RequestId == requestId &&
                message.Status is WorkerMessageStatus.Result or WorkerMessageStatus.Cancelled or WorkerMessageStatus.Error)
            {
                return message;
            }
        }
    }

    private static string WorkerExecutable()
    {
        return Path.Combine(AppContext.BaseDirectory, "cdmw-full-archive-worker.exe");
    }

    private static string RepositoryRoot()
    {
        var current = new DirectoryInfo(Environment.CurrentDirectory);
        while (current is not null)
        {
            if (File.Exists(Path.Combine(current.FullName, "AGENTS.md")) && Directory.Exists(Path.Combine(current.FullName, "native")))
            {
                return current.FullName;
            }
            current = current.Parent;
        }
        throw new DirectoryNotFoundException("Could not locate the CDMW repository root.");
    }

    private static string TempDirectory(string label)
    {
        var path = Path.Combine(Path.GetTempPath(), $"cdmw-full-archive-{label}-{Guid.NewGuid():N}");
        Directory.CreateDirectory(path);
        return path;
    }

    private static void DeleteDirectory(string path)
    {
        try
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, recursive: true);
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            // System temp cleanup is best effort after mapped-file tests.
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }

    private static void Expect<TException>(Action action)
        where TException : Exception
    {
        try
        {
            action();
        }
        catch (TException)
        {
            return;
        }
        throw new InvalidOperationException($"Expected {typeof(TException).Name} was not raised.");
    }

    private static async Task ExpectAsync<TException>(Func<Task> action)
        where TException : Exception
    {
        try
        {
            await action().ConfigureAwait(false);
        }
        catch (TException)
        {
            return;
        }
        throw new InvalidOperationException($"Expected {typeof(TException).Name} was not raised.");
    }
}

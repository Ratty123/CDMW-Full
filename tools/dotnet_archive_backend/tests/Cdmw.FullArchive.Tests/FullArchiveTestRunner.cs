using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Cdmw.Archive.Content;
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
            ("compact_dependency_index", CompactDependencyIndexAsync),
            ("query_lookup_search_prepare_export", QueryLookupSearchPrepareExportAsync),
            ("preview_association_and_prepare_batch", PreviewAssociationAndPrepareBatchAsync),
            ("query_sort_parity", QuerySortParityAsync),
            ("duplicate_override_state", DuplicateOverrideStateAsync),
            ("archive_name_index", ArchiveNameIndexAsync),
            ("item_catalogue_paging_and_bounded_scope", ItemCataloguePagingAndBoundedScopeAsync),
            ("texture_usage_classification", TextureUsageClassificationAsync),
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

    private static Task TextureUsageClassificationAsync()
    {
        Require(
            ArchiveContentClassification.ClassifyTextureUsage("equipment/metal_sword_d.dds") == ArchiveTextureUsageKind.Color
            && ArchiveEntryClassifier.Classify("equipment/metal_sword_d.dds", ".dds") == ArchiveEntryRole.Image,
            "a terminal color suffix lost to an earlier material-like word");
        Require(
            ArchiveContentClassification.ClassifyTextureUsage("equipment/sword_nrm.dds") == ArchiveTextureUsageKind.NormalMap
            && ArchiveEntryClassifier.Classify("equipment/sword_nrm.dds", ".dds") == ArchiveEntryRole.Normal,
            "normal-map suffix classification drifted");
        Require(
            new[] { "_m", "_ma", "_mg", "_mask", "_orm", "_mra", "_ao", "_roughness", "_metallic", "_specular" }
                .All(suffix => ArchiveContentClassification.ClassifyTextureUsage($"equipment/sword{suffix}.dds") == ArchiveTextureUsageKind.MaterialMap),
            "a material-map suffix family is missing");
        Require(
            ArchiveContentClassification.ClassifyTextureUsage("equipment/metal_sword_detail.dds") == ArchiveTextureUsageKind.Unknown
            && ArchiveEntryClassifier.Classify("equipment/metal_sword_detail.dds", ".dds") == ArchiveEntryRole.Image,
            "unknown DDS semantics are still inferred from a word elsewhere in the name");
        return Task.CompletedTask;
    }

    private static async Task ItemCataloguePagingAndBoundedScopeAsync()
    {
        var catalog = ArchiveItemCatalog.FromRecords(
        [
            new ArchiveItemCatalogRecord(
                10,
                "steel_sword",
                "Steel Sword",
                ["Steel Sword"],
                [123u],
                ["steel_sword"],
                ["equipment/weapon/steel_sword.pac"],
                ["ui/icon/steel_sword.dds"],
                ["metal"]),
            new ArchiveItemCatalogRecord(
                11,
                "leather_glove",
                "Leather Glove",
                ["Leather Glove"],
                [],
                ["leather_glove"],
                ["equipment/hand/leather_glove.pac"],
                [],
                ["leather"]),
        ]);
        var metal = catalog.Search("steel", null, null, "metal", 0, 72);
        Require(
            catalog.Count == 2
            && metal.TotalMatches == 1
            && metal.Items[0].ItemId == 10
            && catalog.MaterialFacets.Count == 2,
            "item catalogue search, classification, or material facets changed");

        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var cacheRoot = TempDirectory("bounded-entry-query");
        try
        {
            var native = new NativeArchiveCore();
            native.EnsureCompatible();
            var cache = new ArchiveCacheStore(cacheRoot);
            using var sessions = new ArchiveSessionManager(native, cache);
            var session = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None).ConfigureAwait(false);
            var queries = new ArchiveQueryService(sessions);
            var query = await queries.CreateAsync(
                new ArchiveQuery(session.SessionId, EntryIds: [3, 1, 3]),
                17,
                CancellationToken.None).ConfigureAwait(false);
            var page = queries.FetchPage(session.SessionId, new FetchPageRequest(query.QueryId));
            Require(
                page.TotalMatches == 2
                && page.Rows.Select(static row => row.EntryId).SequenceEqual([3L, 1L]),
                "bounded entry-id query did not preserve a unique server-owned scope");
            var unboundedQuery = await queries.CreateAsync(
                new ArchiveQuery(session.SessionId, EntryIds: []),
                18,
                CancellationToken.None).ConfigureAwait(false);
            Require(
                unboundedQuery.TotalMatches == session.EntryCount,
                "an empty wire entry-id list must retain unbounded query semantics");
        }
        finally
        {
            DeleteDirectory(cacheRoot);
        }
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
            Require(first.IndexVersion == 3, "full archive index version changed");
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
            Require(File.Exists(Path.Combine(firstGeneration, "archive.adi")), "compact dependency index is missing");
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

    private static async Task CompactDependencyIndexAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync().ConfigureAwait(false);
        var cacheRoot = TempDirectory("dependency-index-cache");
        try
        {
            var native = new NativeArchiveCore();
            var cache = new ArchiveCacheStore(cacheRoot);
            string dependencyIndexPath;
            using (var sessions = new ArchiveSessionManager(native, cache))
            {
                var handle = await sessions.OpenAsync(
                    new OpenArchiveRequest(fixture.Root),
                    CancellationToken.None).ConfigureAwait(false);
                var session = sessions.GetRequired(handle.SessionId);
                dependencyIndexPath = Path.Combine(session.GenerationPath, "archive.adi");
                Require(File.Exists(dependencyIndexPath), "compact dependency index was not published on cold open");
                Require(!File.Exists(Path.Combine(session.GenerationPath, "lookups.bin")), "cold open eagerly published the general lookup maps");
                var lookup = new ArchiveLookupService(sessions, cache, native);
                await lookup.WarmAsync(handle.SessionId, CancellationToken.None).ConfigureAwait(false);
                var facets = await lookup.FacetsAsync(handle.SessionId, CancellationToken.None).ConfigureAwait(false);
                Require(facets.Extensions.Any(static facet => facet.Key == ".dds" && facet.Count == 1), "mapped dependency facets changed");
                Require(!File.Exists(Path.Combine(session.GenerationPath, "lookups.bin")), "dependency warmup reconstructed the general lookup maps");
            }

            var generationPath = Path.GetDirectoryName(dependencyIndexPath)!;
            var rootCachePath = Directory.GetParent(generationPath)!.Parent!.FullName;
            var currentPath = Path.Combine(rootCachePath, "current.json");
            var currentPointer = await File.ReadAllTextAsync(currentPath).ConfigureAwait(false);
            using (var lockedIndex = new FileStream(dependencyIndexPath, FileMode.Open, FileAccess.Read, FileShare.None))
            using (var sessions = new ArchiveSessionManager(native, cache))
            {
                await ExpectAsync<UnauthorizedAccessException>(() => sessions.OpenAsync(
                    new OpenArchiveRequest(fixture.Root),
                    CancellationToken.None)).ConfigureAwait(false);
                Require(File.Exists(dependencyIndexPath), "secondary index access failure quarantined the base generation");
                Require(
                    await File.ReadAllTextAsync(currentPath).ConfigureAwait(false) == currentPointer,
                    "secondary index access failure replaced the current base generation");
            }

            await File.WriteAllTextAsync(dependencyIndexPath, "damaged").ConfigureAwait(false);
            using (var sessions = new ArchiveSessionManager(native, cache))
            {
                var reopened = await sessions.OpenAsync(
                    new OpenArchiveRequest(fixture.Root),
                    CancellationToken.None).ConfigureAwait(false);
                Require(reopened.CacheHit, "damaged derived dependency index prevented base generation reuse");
                Require(new FileInfo(dependencyIndexPath).Length > 80, "damaged dependency index was not rebuilt");
            }

            File.Delete(dependencyIndexPath);
            using (var sessions = new ArchiveSessionManager(native, cache))
            using (var cancelled = new CancellationTokenSource())
            {
                await ExpectAsync<OperationCanceledException>(() => sessions.OpenAsync(
                    new OpenArchiveRequest(fixture.Root),
                    cancelled.Token,
                    update =>
                    {
                        if (update.Phase == "dependency_index_build")
                        {
                            cancelled.Cancel();
                        }
                        return Task.CompletedTask;
                    })).ConfigureAwait(false);
                Require(!File.Exists(dependencyIndexPath), "cancelled dependency-index build published a partial index");
            }

            using (var sessions = new ArchiveSessionManager(native, cache))
            {
                var recovered = await sessions.OpenAsync(
                    new OpenArchiveRequest(fixture.Root),
                    CancellationToken.None).ConfigureAwait(false);
                Require(recovered.CacheHit && File.Exists(dependencyIndexPath), "dependency index did not recover after cancellation");
            }
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
            var lookup = new ArchiveLookupService(sessions, cache, native);
            var names = new ArchiveNameIndexService(sessions, cache, native);
            var query = await queries.CreateAsync(
                new ArchiveQuery(sessionHandle.SessionId),
                generation: 7,
                CancellationToken.None).ConfigureAwait(false);
            Require(query.TotalMatches == 4, "unfiltered query count changed");
            var page = queries.FetchPage(sessionHandle.SessionId, new FetchPageRequest(query.QueryId, 0, 2));
            Require(page.Rows.Count == 2 && page.Generation == 7, "paged query result is invalid");
            Require(page.Rows[0].Path == "binary/blob.bin", "path ordering changed");
            var nameSortedQuery = await queries.CreateAsync(
                new ArchiveQuery(
                    sessionHandle.SessionId,
                    SortField: ArchiveSortField.Name,
                    SortActive: true),
                generation: 8,
                CancellationToken.None).ConfigureAwait(false);
            var nameSortedPage = queries.FetchPage(
                sessionHandle.SessionId,
                new FetchPageRequest(nameSortedQuery.QueryId, PageSize: 16));
            Require(
                nameSortedPage.Rows.Select(static row => row.Name).SequenceEqual(
                    ["blob.bin", "hello.txt", "sample.material", "test.dds"]),
                "active natural-name sort changed");
            var firstChildren = queries.FetchChildren(
                sessionHandle.SessionId,
                new ArchiveChildrenRequest(query.QueryId, null, null, Limit: 2));
            Require(
                firstChildren.Children.Count == 2 &&
                firstChildren.TotalChildren == 4 &&
                firstChildren.NextOffset == 2 &&
                firstChildren.Truncated,
                "first folder-child page is invalid");
            var secondChildren = queries.FetchChildren(
                sessionHandle.SessionId,
                new ArchiveChildrenRequest(query.QueryId, null, null, Limit: 2, Offset: 2));
            Require(
                secondChildren.Children.Count == 2 &&
                secondChildren.Offset == 2 &&
                secondChildren.NextOffset is null &&
                !secondChildren.Truncated,
                "folder-child continuation page is invalid");

            var structureRoot = queries.FetchChildren(
                sessionHandle.SessionId,
                new ArchiveChildrenRequest(
                    string.Empty,
                    null,
                    null,
                    IncludePackageRoot: true));
            Require(
                structureRoot.Children is [{ Key: "base", IsFolder: true, MatchCount: 4 }],
                "package-root structure children changed");
            var structurePackage = queries.FetchChildren(
                sessionHandle.SessionId,
                new ArchiveChildrenRequest(
                    string.Empty,
                    "base",
                    null,
                    IncludePackageRoot: true));
            Require(
                structurePackage.Children.Count == 4 &&
                structurePackage.Children.All(static child => child.IsFolder) &&
                structurePackage.Children.Select(static child => child.Key).SequenceEqual(
                    ["base/binary", "base/materials", "base/text", "base/texture"]),
                "package-folder structure children changed");
            using (var cancelledChildren = new CancellationTokenSource())
            {
                cancelledChildren.Cancel();
                Expect<OperationCanceledException>(
                    () => queries.FetchChildren(
                        sessionHandle.SessionId,
                        new ArchiveChildrenRequest(string.Empty, null, null, IncludePackageRoot: true),
                        cancelledChildren.Token));
            }

            var materialQuery = await queries.CreateAsync(
                new ArchiveQuery(sessionHandle.SessionId, Extensions: [".material"]),
                generation: 9,
                CancellationToken.None).ConfigureAwait(false);
            var materialPage = queries.FetchPage(sessionHandle.SessionId, new FetchPageRequest(materialQuery.QueryId));
            Require(materialPage.TotalMatches == 1 && materialPage.Rows[0].Path == "materials/sample.material", "extension filter changed");

            var excludeQuery = await queries.CreateAsync(
                new ArchiveQuery(sessionHandle.SessionId, ExcludeText: "blob;hello"),
                generation: 10,
                CancellationToken.None).ConfigureAwait(false);
            Require(excludeQuery.TotalMatches == 2, "semicolon exclude patterns changed");
            var packageQuery = await queries.CreateAsync(
                new ArchiveQuery(sessionHandle.SessionId, Packages: [page.Rows[0].Package[..4]]),
                generation: 11,
                CancellationToken.None).ConfigureAwait(false);
            Require(packageQuery.TotalMatches == 4, "package substring filter changed");
            var technicalQuery = await queries.CreateAsync(
                new ArchiveQuery(sessionHandle.SessionId, TechnicalSuffixes: ["*test.dds"]),
                generation: 12,
                CancellationToken.None).ConfigureAwait(false);
            Require(technicalQuery.TotalMatches == 3, "technical-suffix exclusion changed");

            await lookup.WarmAsync(sessionHandle.SessionId, CancellationToken.None).ConfigureAwait(false);
            var generationPath = sessions.GetRequired(sessionHandle.SessionId).GenerationPath;
            var exact = await lookup.ResolveAsync(
                new ArchiveLookupRequest(
                    sessionHandle.SessionId,
                    ArchiveLookupKind.ExactPaths,
                    Values: ["text/hello.txt"]),
                CancellationToken.None).ConfigureAwait(false);
            Require(exact.TotalMatches == 1 && exact.Entries[0].EntryId == 2, "exact-path lookup changed");
            var selectionPosition = await lookup.ResolveAsync(
                new ArchiveLookupRequest(
                    sessionHandle.SessionId,
                    ArchiveLookupKind.Identities,
                    Identities: [page.Rows[1].Identity],
                    QueryId: technicalQuery.QueryId),
                CancellationToken.None).ConfigureAwait(false);
            Require(
                selectionPosition.Entries.Count == 1 &&
                selectionPosition.QueryRows is [1],
                "durable selection query position changed");
            var facets = await lookup.FacetsAsync(sessionHandle.SessionId, CancellationToken.None).ConfigureAwait(false);
            Require(facets.Extensions.Any(static facet => facet.Key == ".txt" && facet.Count == 1), "extension facets changed");
            var basename = await lookup.ResolveAsync(
                new ArchiveLookupRequest(
                    sessionHandle.SessionId,
                    ArchiveLookupKind.Basenames,
                    Values: ["test.dds"]),
                CancellationToken.None).ConfigureAwait(false);
            Require(basename.TotalMatches == 1 && basename.Entries[0].EntryId == 3, "compact basename lookup changed");
            Require(
                !File.Exists(Path.Combine(generationPath, "lookups.bin")),
                "targeted path or selection lookup reconstructed the general lookup maps");
            var byExtension = await lookup.ResolveAsync(
                new ArchiveLookupRequest(
                    sessionHandle.SessionId,
                    ArchiveLookupKind.Extensions,
                    Values: [".txt"]),
                CancellationToken.None).ConfigureAwait(false);
            Require(byExtension.TotalMatches == 1, "general extension lookup changed");
            Require(File.Exists(Path.Combine(generationPath, "lookups.bin")), "lazy general lookup index was not published");

            var unavailableNames = await names.WarmAsync(
                sessionHandle.SessionId,
                CancellationToken.None).ConfigureAwait(false);
            Require(!unavailableNames.IsAvailable, "name index fabricated availability without archive item tables");
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
            Require(searchMatches[0].Package == "base/0.pamt", "text match package label changed");

            var preparation = new ArchiveEntryPreparationService(sessions, native);
            var prepared = await preparation.PrepareAsync(
                new PrepareEntryRequest(sessionHandle.SessionId, 2),
                CancellationToken.None).ConfigureAwait(false);
            Require(await File.ReadAllTextAsync(prepared.PreparedPath).ConfigureAwait(false) == "Hello Crimson\nline 2", "prepared bytes changed");
            var preparedSource = sessions.GetRequired(sessionHandle.SessionId).ReadEntry(2);
            var sourceTimestamp = File.GetLastWriteTimeUtc(preparedSource.PazFile);
            var originalRaw = new byte[checked((int)preparedSource.StoredSize)];
            await using (var source = new FileStream(
                preparedSource.PazFile,
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete))
            {
                source.Seek(preparedSource.Offset, SeekOrigin.Begin);
                await source.ReadExactlyAsync(originalRaw).ConfigureAwait(false);
            }
            try
            {
                var mutatedRaw = (byte[])originalRaw.Clone();
                mutatedRaw[0] = (byte)'J';
                await using (var source = new FileStream(
                    preparedSource.PazFile,
                    FileMode.Open,
                    FileAccess.Write,
                    FileShare.Read))
                {
                    source.Seek(preparedSource.Offset, SeekOrigin.Begin);
                    await source.WriteAsync(mutatedRaw).ConfigureAwait(false);
                    await source.FlushAsync().ConfigureAwait(false);
                    source.Flush(flushToDisk: true);
                }
                File.SetLastWriteTimeUtc(preparedSource.PazFile, sourceTimestamp);
                var mutatedPrepared = await preparation.PrepareAsync(
                    new PrepareEntryRequest(sessionHandle.SessionId, 2),
                    CancellationToken.None).ConfigureAwait(false);
                Require(
                    mutatedPrepared.PreparedPath != prepared.PreparedPath &&
                    mutatedPrepared.Sha256 != prepared.Sha256 &&
                    await File.ReadAllTextAsync(mutatedPrepared.PreparedPath).ConfigureAwait(false) == "Jello Crimson\nline 2",
                    "same-size same-timestamp source mutation reused stale prepared bytes");
            }
            finally
            {
                await using (var source = new FileStream(
                    preparedSource.PazFile,
                    FileMode.Open,
                    FileAccess.Write,
                    FileShare.Read))
                {
                    source.Seek(preparedSource.Offset, SeekOrigin.Begin);
                    await source.WriteAsync(originalRaw).ConfigureAwait(false);
                    await source.FlushAsync().ConfigureAwait(false);
                    source.Flush(flushToDisk: true);
                }
                File.SetLastWriteTimeUtc(preparedSource.PazFile, sourceTimestamp);
            }
            var preparedBatch = await preparation.PrepareManyAsync(
                new PrepareEntriesRequest(sessionHandle.SessionId, [1, 2]),
                CancellationToken.None).ConfigureAwait(false);
            Require(
                preparedBatch.Requested == 2 && preparedBatch.Prepared == 2 &&
                preparedBatch.Items.Select(static item => item.Entry.EntryId).SequenceEqual([1L, 2L]),
                "bounded prepare batch changed");
            Require(
                preparedBatch.TotalBytes == preparedBatch.Items.Sum(static item => item.Size),
                "bounded prepare batch byte total changed");

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
            var structureQuery = await queries.CreateAsync(
                new ArchiveQuery(sessionHandle.SessionId, Folder: "base/text"),
                generation: 13,
                CancellationToken.None).ConfigureAwait(false);
            Require(structureQuery.TotalMatches == 1, "package-aware structure filter changed");
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

            var renameRoot = Path.Combine(exportRoot, "rename-export");
            var existingPackageMaterial = Path.Combine(renameRoot, "base", "materials", "sample.material");
            Directory.CreateDirectory(Path.GetDirectoryName(existingPackageMaterial)!);
            await File.WriteAllTextAsync(existingPackageMaterial, "keep existing").ConfigureAwait(false);
            var existingManifest = Path.Combine(renameRoot, "cdmw-export-manifest.json");
            await File.WriteAllTextAsync(existingManifest, "keep manifest").ConfigureAwait(false);
            var renamed = await exports.ExportAsync(
                new ArchiveExportRequest(
                    sessionHandle.SessionId,
                    ArchiveExportSelectionKind.EntryIds,
                    renameRoot,
                    EntryIds: [materialPage.Rows[0].EntryId],
                    CollisionPolicy: ArchiveExportCollisionPolicy.Rename,
                    IncludePackageRoot: true),
                CancellationToken.None).ConfigureAwait(false);
            Require(renamed.Exported == 1 && renamed.Items.Single().Status == "renamed", "rename collision policy changed");
            Require(
                await File.ReadAllTextAsync(Path.Combine(renameRoot, "base", "materials", "sample_2.material")).ConfigureAwait(false) == "material alpha",
                "renamed package-root export bytes changed");
            Require(
                await File.ReadAllTextAsync(existingPackageMaterial).ConfigureAwait(false) == "keep existing",
                "rename export overwrote its collision target");
            Require(
                renamed.ManifestPath == Path.Combine(renameRoot, "cdmw-export-manifest_2.json") &&
                File.Exists(renamed.ManifestPath) &&
                await File.ReadAllTextAsync(existingManifest).ConfigureAwait(false) == "keep manifest",
                "rename export manifest collision handling changed");

            var folderRoot = Path.Combine(exportRoot, "folder-export");
            var folderExport = await exports.ExportAsync(
                new ArchiveExportRequest(
                    sessionHandle.SessionId,
                    ArchiveExportSelectionKind.Folder,
                    folderRoot,
                    QueryId: structureQuery.QueryId,
                    FolderPath: "base",
                    CollisionPolicy: ArchiveExportCollisionPolicy.Overwrite,
                    IncludePackageRoot: true),
                CancellationToken.None).ConfigureAwait(false);
            Require(folderExport.Exported == 1, "folder export selection changed");
            Require(
                await File.ReadAllTextAsync(Path.Combine(folderRoot, "base", "text", "hello.txt")).ConfigureAwait(false) == "Hello Crimson\nline 2",
                "folder export package layout changed");

            var familyRoot = Path.Combine(exportRoot, "family-export");
            var familyExport = await exports.ExportAsync(
                new ArchiveExportRequest(
                    sessionHandle.SessionId,
                    ArchiveExportSelectionKind.Family,
                    familyRoot,
                    FamilyEntryId: materialPage.Rows[0].EntryId,
                    CollisionPolicy: ArchiveExportCollisionPolicy.Overwrite),
                CancellationToken.None).ConfigureAwait(false);
            Require(familyExport.Exported >= 1, "family export selection changed");
            Require(File.Exists(Path.Combine(familyRoot, "materials", "sample.material")), "family export omitted its seed");

            var replaceRoot = Path.Combine(exportRoot, "replace-export");
            Directory.CreateDirectory(replaceRoot);
            await File.WriteAllTextAsync(Path.Combine(replaceRoot, "stale.txt"), "stale").ConfigureAwait(false);
            var replaced = await exports.ExportAsync(
                new ArchiveExportRequest(
                    sessionHandle.SessionId,
                    ArchiveExportSelectionKind.EntryIds,
                    replaceRoot,
                    EntryIds: [prepared.Entry.EntryId],
                    CollisionPolicy: ArchiveExportCollisionPolicy.Overwrite,
                    IncludePackageRoot: true,
                    ReplaceDestination: true),
                CancellationToken.None).ConfigureAwait(false);
            Require(replaced.Exported == 1 && !File.Exists(Path.Combine(replaceRoot, "stale.txt")), "replace-destination export changed");
            Require(
                await File.ReadAllTextAsync(Path.Combine(replaceRoot, "base", "text", "hello.txt")).ConfigureAwait(false) == "Hello Crimson\nline 2",
                "replace-destination export bytes changed");

            var cancellationRoot = Path.Combine(exportRoot, "cancelled-export");
            Directory.CreateDirectory(cancellationRoot);
            var cancellationMarker = Path.Combine(cancellationRoot, "keep.txt");
            await File.WriteAllTextAsync(cancellationMarker, "keep destination").ConfigureAwait(false);
            var cancellationQuery = await queries.CreateAsync(
                new ArchiveQuery(sessionHandle.SessionId),
                generation: 19,
                CancellationToken.None).ConfigureAwait(false);
            using var exportCancellation = new CancellationTokenSource();
            var cancellationObserved = false;
            try
            {
                _ = await exports.ExportAsync(
                    new ArchiveExportRequest(
                        sessionHandle.SessionId,
                        ArchiveExportSelectionKind.Query,
                        cancellationRoot,
                        QueryId: cancellationQuery.QueryId,
                        CollisionPolicy: ArchiveExportCollisionPolicy.Overwrite,
                        IncludePackageRoot: true,
                        ReplaceDestination: true),
                    exportCancellation.Token,
                    update =>
                    {
                        if (update.Phase == "export_publish")
                        {
                            exportCancellation.Cancel();
                        }
                        return Task.CompletedTask;
                    }).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                cancellationObserved = true;
            }
            Require(cancellationObserved, "export cancellation was not observed");
            Require(
                Directory.GetFiles(cancellationRoot, "*", SearchOption.AllDirectories) is [var onlyFile] &&
                onlyFile.Equals(cancellationMarker, StringComparison.OrdinalIgnoreCase) &&
                await File.ReadAllTextAsync(cancellationMarker).ConfigureAwait(false) == "keep destination",
                "cancelled export changed its previous destination");
            Require(
                !Directory.EnumerateFileSystemEntries(exportRoot, ".cancelled-export.cdmw-*").Any(),
                "cancelled export left a staging directory");

            for (var generation = 20; generation < 25; generation++)
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

    private static async Task PreviewAssociationAndPrepareBatchAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAssociatedAssetsAsync().ConfigureAwait(false);
        var cacheRoot = TempDirectory("preview-association-cache");
        try
        {
            var native = new NativeArchiveCore();
            var cache = new ArchiveCacheStore(cacheRoot);
            using var sessions = new ArchiveSessionManager(native, cache);
            var handle = await sessions.OpenAsync(
                new OpenArchiveRequest(fixture.Root),
                CancellationToken.None).ConfigureAwait(false);
            var session = sessions.GetRequired(handle.SessionId);
            var selected = Enumerable.Range(0, checked((int)handle.EntryCount))
                .Select(index => session.ReadEntry(index))
                .Single(static entry => entry.Path == "character/model/hero.pac");
            var lookup = new ArchiveLookupService(sessions, cache, native);
            var association = await lookup.FindAssociationCandidatesAsync(
                new ArchiveAssociationRequest(
                    handle.SessionId,
                    selected.EntryId,
                    128,
                    ArchiveAssociationPurpose.Preview),
                CancellationToken.None).ConfigureAwait(false);
            var paths = association.Candidates.Select(static entry => entry.Path).ToHashSet(StringComparer.OrdinalIgnoreCase);
            Require(
                paths.SetEquals(
                [
                    "character/modelproperty/hero.pac_xml",
                    "character/texture/hero_body_d.dds",
                    "character/texture/hero_body_n.dds",
                    "character/physics/hero.hkx",
                    "character/model/hero.meshinfo",
                    "character/model/hero.prefab",
                ]),
                "preview association did not preserve the bounded semantic dependency set");
            Require(!paths.Contains("unrelated/other.dds") && !association.Truncated, "preview association included unrelated rows");
            Require(
                File.Exists(Path.Combine(session.GenerationPath, "archive.adi")) &&
                !File.Exists(Path.Combine(session.GenerationPath, "lookups.bin")),
                "preview association reconstructed the eager general lookup maps");

            var preparation = new ArchiveEntryPreparationService(sessions, native);
            var entryIds = association.Candidates
                .Select(static entry => entry.EntryId)
                .Prepend(selected.EntryId)
                .ToArray();
            var prepared = await preparation.PrepareManyAsync(
                new PrepareEntriesRequest(handle.SessionId, entryIds),
                CancellationToken.None).ConfigureAwait(false);
            Require(
                prepared.Prepared == 7 && prepared.Items.Count == 7 && prepared.TotalBytes > 0,
                "preview dependency preparation batch changed");
            Require(
                prepared.Items.All(static item => File.Exists(item.PreparedPath)),
                "preview dependency preparation did not publish every bounded source");
        }
        finally
        {
            DeleteDirectory(cacheRoot);
        }
    }

    private static async Task DuplicateOverrideStateAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateDuplicateOverridesAsync().ConfigureAwait(false);
        var cacheRoot = TempDirectory("override-cache");
        try
        {
            var native = new NativeArchiveCore();
            var cache = new ArchiveCacheStore(cacheRoot);
            using var sessions = new ArchiveSessionManager(native, cache);
            var session = await sessions.OpenAsync(
                new OpenArchiveRequest(fixture.Root),
                CancellationToken.None).ConfigureAwait(false);
            var queries = new ArchiveQueryService(sessions);
            var all = await queries.CreateAsync(
                new ArchiveQuery(session.SessionId),
                generation: 1,
                CancellationToken.None).ConfigureAwait(false);
            var rows = queries.FetchPage(session.SessionId, new FetchPageRequest(all.QueryId, PageSize: 8)).Rows;
            Require(rows.Count == 2, "duplicate fixture count changed");
            var original = rows.Single(static row => row.SourcePamt.Contains("0009", StringComparison.OrdinalIgnoreCase));
            var mod = rows.Single(static row => row.SourcePamt.Contains("dmm1", StringComparison.OrdinalIgnoreCase));
            Require(!original.IsActiveOverride && original.OverrideState == "Shadowed original", "original override state changed");
            Require(mod.IsActiveOverride && mod.OverrideState == "Active mod", "mod override state changed");

            var active = await queries.CreateAsync(
                new ArchiveQuery(session.SessionId, ActiveOverridesOnly: true),
                generation: 2,
                CancellationToken.None).ConfigureAwait(false);
            var activeRows = queries.FetchPage(session.SessionId, new FetchPageRequest(active.QueryId)).Rows;
            Require(activeRows is [{ OverrideState: "Active mod" }], "active-override filter changed");

            var lookup = new ArchiveLookupService(sessions, cache, native);
            var exports = new ArchiveExportService(sessions, queries, lookup, native);
            var overwriteRoot = Path.Combine(fixture.OutputRoot, "duplicate-overwrite");
            var overwritten = await exports.ExportAsync(
                new ArchiveExportRequest(
                    session.SessionId,
                    ArchiveExportSelectionKind.Query,
                    overwriteRoot,
                    QueryId: all.QueryId,
                    CollisionPolicy: ArchiveExportCollisionPolicy.Overwrite),
                CancellationToken.None).ConfigureAwait(false);
            Require(
                overwritten.Requested == 2 && overwritten.Exported == 1 &&
                await File.ReadAllBytesAsync(Path.Combine(overwriteRoot, "character", "model", "duplicate.pac"))
                    .ConfigureAwait(false) is [0x02],
                "duplicate overwrite export did not preserve the active mod bytes");

            var renameRoot = Path.Combine(fixture.OutputRoot, "duplicate-rename");
            var renamed = await exports.ExportAsync(
                new ArchiveExportRequest(
                    session.SessionId,
                    ArchiveExportSelectionKind.Query,
                    renameRoot,
                    QueryId: all.QueryId,
                    CollisionPolicy: ArchiveExportCollisionPolicy.Rename),
                CancellationToken.None).ConfigureAwait(false);
            Require(
                renamed.Exported == 2 &&
                renamed.Items.Count(static item => item.Status == "renamed") == 1 &&
                await File.ReadAllBytesAsync(Path.Combine(renameRoot, "character", "model", "duplicate.pac"))
                    .ConfigureAwait(false) is [0x01] &&
                await File.ReadAllBytesAsync(Path.Combine(renameRoot, "character", "model", "duplicate_2.pac"))
                    .ConfigureAwait(false) is [0x02],
                "duplicate rename export did not preserve both ordered payloads");
        }
        finally
        {
            DeleteDirectory(cacheRoot);
        }
    }

    private static async Task QuerySortParityAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateSortParityAsync().ConfigureAwait(false);
        var cacheRoot = TempDirectory("sort-cache");
        try
        {
            var native = new NativeArchiveCore();
            var cache = new ArchiveCacheStore(cacheRoot);
            using var sessions = new ArchiveSessionManager(native, cache);
            var session = await sessions.OpenAsync(
                new OpenArchiveRequest(fixture.Root),
                CancellationToken.None).ConfigureAwait(false);
            var queries = new ArchiveQueryService(sessions);

            var naturalNames = await queries.CreateAsync(
                new ArchiveQuery(
                    session.SessionId,
                    Extensions: [".bin"],
                    SortField: ArchiveSortField.Name,
                    SortActive: true),
                generation: 1,
                CancellationToken.None).ConfigureAwait(false);
            var naturalRows = queries.FetchPage(
                session.SessionId,
                new FetchPageRequest(naturalNames.QueryId, PageSize: 16)).Rows;
            Require(
                naturalRows.Select(static row => row.Name).SequenceEqual(["item2.bin", "item10.bin"]),
                "natural numeric name ordering changed");

            var roleAscending = await queries.CreateAsync(
                new ArchiveQuery(session.SessionId, SortField: ArchiveSortField.Role, SortActive: true),
                generation: 2,
                CancellationToken.None).ConfigureAwait(false);
            var ascendingPaths = queries.FetchPage(
                session.SessionId,
                new FetchPageRequest(roleAscending.QueryId, PageSize: 16)).Rows.Select(static row => row.Path);
            Require(
                ascendingPaths.SequenceEqual(
                    [
                        "roles/sidecar.pac_xml",
                        "roles/model.pac",
                        "roles/property.pamhc",
                        "names/item2.bin",
                        "names/item10.bin",
                    ]),
                "legacy role-display ordering changed");

            var roleDescending = await queries.CreateAsync(
                new ArchiveQuery(
                    session.SessionId,
                    SortField: ArchiveSortField.Role,
                    SortActive: true,
                    SortDescending: true),
                generation: 3,
                CancellationToken.None).ConfigureAwait(false);
            var descendingPaths = queries.FetchPage(
                session.SessionId,
                new FetchPageRequest(roleDescending.QueryId, PageSize: 16)).Rows.Select(static row => row.Path);
            Require(
                descendingPaths.SequenceEqual(
                    [
                        "names/item10.bin",
                        "names/item2.bin",
                        "roles/property.pamhc",
                        "roles/model.pac",
                        "roles/sidecar.pac_xml",
                    ]),
                "descending role-display ordering changed");
        }
        finally
        {
            DeleteDirectory(cacheRoot);
        }
    }

    private static async Task ArchiveNameIndexAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateNameIndexAsync().ConfigureAwait(false);
        var cacheRoot = TempDirectory("names-cache");
        try
        {
            var native = new NativeArchiveCore();
            var cache = new ArchiveCacheStore(cacheRoot);
            using var sessions = new ArchiveSessionManager(native, cache);
            var handle = await sessions.OpenAsync(
                new OpenArchiveRequest(fixture.Root),
                CancellationToken.None).ConfigureAwait(false);
            var service = new ArchiveNameIndexService(sessions, cache, native);
            var index = await service.WarmAsync(handle.SessionId, CancellationToken.None).ConfigureAwait(false);
            Require(index.IsAvailable && index.HasNames, $"synthetic archive name index is unavailable: {index.UnavailableReason}");
            Require(
                index.ExactNames.TryGetValue("cd_test_01_sword", out var exactName) && exactName == "Synthetic Blade",
                "exact prefab-hash localization mapping changed");
            Require(
                index.RelatedNames.TryGetValue("cd_related_01_sword", out var relatedName) && relatedName == "Synthetic Blade",
                "StringInfo related-name mapping changed");

            var session = sessions.GetRequired(handle.SessionId);
            var exactEntry = session.Index.FindEntriesByPath("character/model/cd_test_01_sword.pac").Single();
            var enrichedExact = session.ReadEntry(exactEntry.EntryId);
            Require(
                enrichedExact.KnownName == "Synthetic Blade" &&
                enrichedExact.ExactName == "Synthetic Blade" &&
                enrichedExact.NameEvidence == "Exact localization",
                "exact archive name evidence changed");
            var relatedEntry = session.Index.FindEntriesByPath("character/model/cd_related_01_sword_index01.pac").Single();
            var enrichedRelated = session.ReadEntry(relatedEntry.EntryId);
            Require(
                enrichedRelated.KnownName.Length == 0 &&
                enrichedRelated.NameEvidence == "Name hint: Synthetic Blade",
                "related archive name evidence changed");

            var persistedPath = Path.Combine(session.GenerationPath, "names.bin");
            Require(File.Exists(persistedPath), "available archive name index was not persisted");
            var reloadedService = new ArchiveNameIndexService(sessions, cache, native);
            var reloaded = await reloadedService.WarmAsync(handle.SessionId, CancellationToken.None).ConfigureAwait(false);
            Require(
                reloaded.IsAvailable && reloaded.ExactNames.SequenceEqual(index.ExactNames),
                "persisted archive name index did not round-trip");
        }
        finally
        {
            DeleteDirectory(cacheRoot);
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
            var withoutSharedAccelerator = text.Replace("cdmw_archive_accelerator", string.Empty, StringComparison.Ordinal);
            Require(!withoutSharedAccelerator.Contains(liteAbi, StringComparison.Ordinal), $"Archive Lite native ABI leaked into {path}");
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
                Require(pingResult is { ProtocolVersion: 3, NativeAbiVersion: 1, IndexVersion: 3 }, "worker ping compatibility data changed");

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

                var unavailableNameQueryId = Guid.NewGuid();
                await SendAsync(process, WorkerProtocol.Request(
                    unavailableNameQueryId,
                    22,
                    WorkerProtocol.CreateQuery,
                    new CreateQueryRequest(new ArchiveQuery(session.SessionId, IncludeText: "name:Crimson")),
                    session.SessionId)).ConfigureAwait(false);
                var unavailableNameQuery = await ReadTerminalAsync(process, unavailableNameQueryId).ConfigureAwait(false);
                Require(
                    unavailableNameQuery.Status == WorkerMessageStatus.Error &&
                    unavailableNameQuery.Error?.Message.Contains("iteminfo.pabgb", StringComparison.OrdinalIgnoreCase) == true,
                    "explicit name query silently degraded without archive name sources");

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

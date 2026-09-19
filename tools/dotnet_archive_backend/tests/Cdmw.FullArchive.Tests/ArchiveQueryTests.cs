using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

internal static class ArchiveQueryTests
{
    public static async Task ExtensionSearchAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateExtensionSearchAsync();
        var native = new NativeArchiveCore();
        using var sessions = new ArchiveSessionManager(native, new ArchiveCacheStore(fixture.OutputRoot));
        var session = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None);
        var queries = new ArchiveQueryService(sessions);
        var query = new ArchiveQuery(session.SessionId, IncludeText: "nude", Extensions: [" PAC ", ".pac"]);
        var first = await SearchAsync(queries, query);
        Require(first.Page.Rows.Select(row => row.Path).SequenceEqual([
            "character/model/nude_body10.pac", "character/model/nude_body2.pac", "other/nude_body.pac",
        ]), "PAC text search changed its results or native order");
        RequireScanned(first.Progress, 4);
        Require(first.Progress.Any(update => update.Phase == "query_extension_index"),
            "the first extension query did not prepare the compact index");

        var filtered = await SearchAsync(queries, query with
        {
            ExcludeText = "body10", Folder = "0009/character/model", MinimumSize = 2,
            Roles = [ArchiveEntryRole.Model], PreviewableOnly = true,
        });
        Require(filtered.Page.Rows is [{ Path: "character/model/nude_body2.pac" }],
            "extension candidates bypassed the remaining browser filters");
        RequireScanned(filtered.Progress, 4);
        Require(!filtered.Progress.Any(update => update.Phase == "query_extension_index"),
            "a repeated extension query rebuilt the index");

        var sorted = await SearchAsync(queries, query with
        {
            SortField = ArchiveSortField.OriginalSize, SortActive = true, SortDescending = true,
        });
        Require(sorted.Page.Rows.Select(row => row.OriginalSize).SequenceEqual([3L, 2L, 1L]),
            "indexed extension search changed explicit sorting");

        var multiple = await SearchAsync(queries, query with { Extensions = [".PAC", "pam", ".pac"] });
        Require(multiple.Page.TotalMatches == 4 && multiple.Page.Rows.Select(row => row.EntryId)
            .SequenceEqual(multiple.Page.Rows.Select(row => row.EntryId).Distinct().Order()),
            "multiple extension lists were duplicated or lost native order");
        RequireScanned(multiple.Progress, 5);
        Require(!multiple.Progress.Any(update => update.Phase == "query_extension_index"),
            "changing the extension rebuilt the catalogue index");

        foreach (var wildcard in new[] { "*", ".*", " ALL " })
        {
            var all = await SearchAsync(queries, query with { Extensions = [".pac", wildcard] });
            Require(all.Page.TotalMatches == 9005, "an all-extension alias narrowed the search");
            RequireScanned(all.Progress, session.EntryCount);
        }
        foreach (var missing in new[] { ".unknown", "" })
        {
            var empty = await SearchAsync(queries, query with { Extensions = [missing] });
            Require(empty.Page.TotalMatches == 0, "an unknown extension returned unrelated entries");
            RequireScanned(empty.Progress, 0);
        }

        var scoped = await SearchAsync(queries, query with
        {
            EntryIds = [first.Page.Rows[2].EntryId, first.Page.Rows[0].EntryId, first.Page.Rows[2].EntryId, -1],
        });
        Require(scoped.Page.Rows.Select(row => row.EntryId)
            .SequenceEqual([first.Page.Rows[2].EntryId, first.Page.Rows[0].EntryId]),
            "extension filtering changed the explicit entry scope or its order");

        await using var otherFixture = await SyntheticArchiveFixture.CreateAsync();
        var otherSession = await sessions.OpenAsync(new OpenArchiveRequest(otherFixture.Root), CancellationToken.None);
        var other = await SearchAsync(queries, new ArchiveQuery(otherSession.SessionId, Extensions: [".pac"]));
        Require(other.Page.TotalMatches == 0, "extension candidates leaked between catalogues");
    }

    public static async Task CancellationAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateExtensionSearchAsync();
        using var sessions = new ArchiveSessionManager(new NativeArchiveCore(), new ArchiveCacheStore(fixture.OutputRoot));
        var session = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None);
        var queries = new ArchiveQueryService(sessions);
        var query = new ArchiveQuery(session.SessionId, IncludeText: "nude", Extensions: [".pac"]);
        using var cancelled = new CancellationTokenSource();
        try
        {
            await queries.CreateAsync(query, 1, cancelled.Token, update =>
            {
                if (update.Phase == "query_extension_index" && update.Completed >= 4096)
                    cancelled.Cancel();
                return Task.CompletedTask;
            });
            throw new InvalidDataException("cancelling the extension-index build did not stop the query");
        }
        catch (OperationCanceledException) when (cancelled.IsCancellationRequested) { }

        var results = await Task.WhenAll(
            SearchAsync(queries, query),
            SearchAsync(queries, query with { Extensions = [".pam"] }));
        Require(results[0].Page.TotalMatches == 3 && results[1].Page.TotalMatches == 1,
            "a cancelled or concurrent build published incomplete extension candidates");
        Require(results.SelectMany(result => result.Progress)
            .Count(update => update.Phase == "query_extension_index" && update.Completed == 0) == 1,
            "concurrent queries did not share one complete retry of the cancelled index build");
        RequireScanned(results[0].Progress, 4);
        RequireScanned(results[1].Progress, 1);
        try
        {
            await queries.CreateAsync(query, 2, cancelled.Token);
            throw new InvalidDataException("a cached extension index ignored query cancellation");
        }
        catch (OperationCanceledException) when (cancelled.IsCancellationRequested) { }
    }

    public static async Task ItemNamesAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateNameIndexAsync();
        var native = new NativeArchiveCore();
        var cache = new ArchiveCacheStore(fixture.OutputRoot);
        using var sessions = new ArchiveSessionManager(native, cache);
        var session = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None);
        await new ArchiveNameIndexService(sessions, cache, native).WarmAsync(session.SessionId, CancellationToken.None);
        var queries = new ArchiveQueryService(sessions);
        var query = new ArchiveQuery(session.SessionId, IncludeText: "Synthetic Blade");
        var all = await SearchAsync(queries, query);
        var expected = all.Page.Rows.Where(row => row.Extension == ".pac").ToArray();
        Require(expected.Length > 0 && expected.All(row => !row.Path.Contains("Synthetic Blade")),
            "the fixture must exercise item names that are absent from PAC paths");
        var indexed = await SearchAsync(queries, query with { Extensions = [".pac"] });
        Require(indexed.Page.Rows.SequenceEqual(expected), "extension search lost localized item-name matches");
    }

    private static async Task<(ArchivePage Page, List<ProgressUpdate> Progress)> SearchAsync(
        ArchiveQueryService queries, ArchiveQuery query)
    {
        var progress = new List<ProgressUpdate>();
        var handle = await queries.CreateAsync(query, 1, CancellationToken.None, update =>
        {
            progress.Add(update);
            return Task.CompletedTask;
        });
        return (queries.FetchPage(query.SessionId, new FetchPageRequest(handle.QueryId, PageSize: 512)), progress);
    }

    private static void RequireScanned(IReadOnlyList<ProgressUpdate> progress, long candidates)
    {
        Require(progress.Any(update => update.Phase == "query_scan") &&
            progress.Where(update => update.Phase == "query_scan").All(update => update.Total == candidates),
            $"expected only {candidates} query candidates, rather than a full catalogue scan");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}

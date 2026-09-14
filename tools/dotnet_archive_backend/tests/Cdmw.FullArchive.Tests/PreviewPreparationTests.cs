using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

internal static class PreviewPreparationTests
{
    public static async Task ConcurrentAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync();
        for (var round = 0; round < 8; round++)
        {
            var native = new NativeArchiveCore();
            var cache = new ArchiveCacheStore(Path.Combine(fixture.OutputRoot, $"cache-{round}"));
            using var sessions = new ArchiveSessionManager(native, cache);
            var session = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None);
            var preparation = new ArchiveEntryPreparationService(sessions, native);
            var start = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var jobs = Enumerable.Range(0, 48).Select(async _ =>
            {
                await start.Task;
                // Finder lanes can share the selected model, textures and analysis.
                return await preparation.PrepareManyAsync(
                    new PrepareEntriesRequest(session.SessionId, [1L, 2L, 3L], ContentAnalysisEntryId: 2L),
                    CancellationToken.None);
            }).ToArray();
            start.SetResult();
            var results = await Task.WhenAll(jobs);
            foreach (var result in results)
            {
                if (result.Prepared != 3 || !result.Items.Select(item => item.Sha256)
                        .SequenceEqual(results[0].Items.Select(item => item.Sha256)))
                    throw new InvalidDataException("Concurrent previews did not retain identical prepared inputs.");
                var text = result.Items.Single(item => item.Entry.EntryId == 2);
                if (await File.ReadAllTextAsync(text.PreparedPath) != "Hello Crimson\nline 2")
                    throw new InvalidDataException("Concurrent preview preparation changed the source bytes.");
            }
            if (Directory.EnumerateFiles(fixture.OutputRoot, "*.tmp", SearchOption.AllDirectories).Any())
                throw new InvalidDataException("Concurrent preview preparation left unpublished files.");
        }
        Console.WriteLine("PASS concurrent_preview_preparation");
    }

    public static async Task CancellationAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync();
        var native = new NativeArchiveCore();
        var cache = new ArchiveCacheStore(fixture.OutputRoot);
        using var sessions = new ArchiveSessionManager(native, cache);
        var session = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None);
        var preparation = new ArchiveEntryPreparationService(sessions, native);
        var otherPreparation = new ArchiveEntryPreparationService(sessions, native);
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var request = new PrepareEntryRequest(session.SessionId, 2);
        var first = preparation.PrepareAsync(request, CancellationToken.None, async progress =>
        {
            if (progress.Phase == "prepare_decode")
            {
                entered.TrySetResult();
                await release.Task;
            }
        });
        try
        {
            await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            using var cancellation = new CancellationTokenSource();
            var waiting = otherPreparation.PrepareAsync(request, cancellation.Token);
            cancellation.Cancel();
            try
            {
                await waiting.WaitAsync(TimeSpan.FromSeconds(5));
                throw new InvalidOperationException("A waiting preview ignored cancellation.");
            }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
        }
        finally
        {
            release.TrySetResult();
            await first;
        }
        var cached = await otherPreparation.PrepareAsync(request, CancellationToken.None);
        if (cached.PreparedPath != first.Result.PreparedPath || cached.Note != "prepared cache hit")
            throw new InvalidDataException("Cancelling a waiting preview disrupted cache publication.");
        Console.WriteLine("PASS preview_preparation_wait_cancellation");
    }
}

using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

internal static class CacheMaintenanceTests
{
    public static async Task GrowthAndReleaseAsync()
    {
        await using var fixture = await Fixture.CreateAsync();
        var cache = fixture.CreateCache();
        using var sessions = new ArchiveSessionManager(fixture.Native, cache);
        var first = await fixture.OpenAsync(sessions, cache);
        var generation = sessions.GetRequired(first.SessionId).GenerationPath;
        var preparation = new ArchiveEntryPreparationService(sessions, fixture.Native);
        var hot = await preparation.PrepareAsync(new(first.SessionId, 2), CancellationToken.None);
        var large = await AddUnitAsync(generation, 'a', extensionless: true);
        var unknownCompanion = large[0] + ".user-note.keep";
        await File.WriteAllTextAsync(unknownCompanion, "unrecognized companion");
        // This publication is the runtime trigger for growth after cache creation.
        await preparation.PrepareAsync(new(first.SessionId, 3), CancellationToken.None);
        await cache.WaitForMaintenanceAsync(CancellationToken.None);
        Require(large.All(File.Exists), "maintenance removed an active prepared file");
        var second = await sessions.OpenAsync(new(fixture.Archive.Root), CancellationToken.None);
        Require(second.CacheHit, "warm open rebuilt a valid catalogue");
        sessions.Close(first.SessionId);
        await cache.WaitForMaintenanceAsync(CancellationToken.None);
        Require(large.All(File.Exists), "maintenance ignored another session's lease");
        var reused = await preparation.PrepareAsync(new(second.SessionId, 2), CancellationToken.None);
        Require(reused.PreparedPath == hot.PreparedPath && reused.Note == "prepared cache hit", "active cache reuse changed");
        await File.WriteAllTextAsync(Path.Combine(generation, "item-catalog-keep.json"), "durable catalogue");
        sessions.Close(second.SessionId);
        await cache.WaitForMaintenanceAsync(CancellationToken.None);
        Require(large.All(path => !File.Exists(path)), "released derived payloads exceeded the budget");
        Require(File.Exists(unknownCompanion), "maintenance removed an unrecognized companion");
        Require(File.Exists(hot.PreparedPath), "maintenance discarded a newer cached payload unnecessarily");
        Require(File.Exists(Path.Combine(generation, "archive.ali")) && File.Exists(Path.Combine(generation, "archive.adi"))
            && File.Exists(Path.Combine(generation, "item-catalog-keep.json")), "maintenance removed reusable indexes/catalogues");
        Require(Size(cache.CatalogueRoot) <= Fixture.TargetBytes, "cleanup did not reach its target");
        var reopened = await sessions.OpenAsync(new(fixture.Archive.Root), CancellationToken.None);
        Require(reopened.CacheHit, "trimming derived files forced a catalogue rebuild");
    }

    public static async Task WarmOpenAndCoalescingAsync()
    {
        await using var fixture = await Fixture.CreateAsync();
        var seed = fixture.CreateCache(long.MaxValue);
        string oldGeneration;
        using (var sessions = new ArchiveSessionManager(fixture.Native, seed))
        {
            var first = await fixture.OpenAsync(sessions, seed);
            oldGeneration = sessions.GetRequired(first.SessionId).GenerationPath;
            await AddUnitAsync(oldGeneration, 'a');
            await sessions.RefreshAsync(new(fixture.Archive.Root), CancellationToken.None);
        }
        await seed.WaitForMaintenanceAsync(CancellationToken.None);
        Require(Directory.Exists(oldGeneration), "seed did not retain its previous generation");
        var cache = fixture.CreateCache(interval: TimeSpan.FromMinutes(5));
        using var reopenedSessions = new ArchiveSessionManager(fixture.Native, cache);
        // A busy sweep lock must not hold up cache reuse or enqueueing requests.
        using (var lockFile = new FileStream(Path.Combine(cache.CatalogueRoot, ".maintenance.lock"),
            FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None))
        {
            var started = Stopwatch.StartNew();
            var warm = await reopenedSessions.OpenAsync(new(fixture.Archive.Root), CancellationToken.None);
            Require(warm.CacheHit, "warm maintenance forced a rebuild");
            for (var index = 0; index < 2000; index++) cache.RequestMaintenance();
            await cache.WaitForMaintenanceAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(3));
            Require(started.Elapsed < TimeSpan.FromSeconds(3), "maintenance blocked foreground work");
        }
        // Urgent release/drain wakes a throttled pass instead of waiting five minutes.
        await cache.WaitForMaintenanceAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(3));
        Require(!Directory.Exists(oldGeneration), "warm cache reuse did not reclaim the old generation");
    }

    public static async Task SeparateOwnersAsync()
    {
        await using var fixture = await Fixture.CreateAsync();
        var cache = fixture.CreateCache();
        var otherCache = fixture.CreateCache();
        using var sessions = new ArchiveSessionManager(fixture.Native, cache);
        using var otherSessions = new ArchiveSessionManager(fixture.Native, otherCache);
        var first = await fixture.OpenAsync(sessions, cache);
        var generation = sessions.GetRequired(first.SessionId).GenerationPath;
        var prepared = await AddUnitAsync(generation, 'a');
        var other = await otherSessions.OpenAsync(new(fixture.Archive.Root), CancellationToken.None);
        Require(other.CacheHit, "second cache owner did not reuse the current generation");
        await otherCache.WaitForMaintenanceAsync(CancellationToken.None);
        var publicationGuardObserved = false;
        await sessions.RefreshAsync(new(fixture.Archive.Root), CancellationToken.None, _ =>
        {
            var staging = Directory.EnumerateDirectories(Directory.GetParent(generation)!.FullName, ".*.staging")
                .SingleOrDefault();
            if (staging is null) return Task.CompletedTask;
            var publishing = Path.Combine(Directory.GetParent(staging)!.FullName,
                Path.GetFileName(staging)[1..^".staging".Length]);
            try
            {
                // Another cache owner must not acquire its maintenance lock before
                // the new directory becomes visible and current.json is replaced.
                using var maintenance = new FileStream(ArchiveCacheStore.GenerationUsePath(publishing),
                    FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.Delete);
                throw new InvalidOperationException("a publishing generation was unprotected from another owner's maintenance");
            }
            catch (IOException exception) when ((exception.HResult & 0xFFFF) is 32 or 33)
            {
                publicationGuardObserved = true;
            }
            return Task.CompletedTask;
        });
        Require(publicationGuardObserved, "refresh never exercised cross-owner publication protection");
        sessions.Close(first.SessionId);
        await cache.WaitForMaintenanceAsync(CancellationToken.None);
        Require(Directory.Exists(generation) && prepared.All(File.Exists), "another cache owner's generation was deleted");
        Require(otherSessions.GetRequired(other.SessionId).ReadEntry(2).Path == "text/hello.txt", "another owner's mapped index failed");
        otherSessions.Close(other.SessionId);
        await otherCache.WaitForMaintenanceAsync(CancellationToken.None);
        await cache.WaitForMaintenanceAsync(CancellationToken.None);
        Require(!Directory.Exists(generation), "an externally released old generation was not reclaimed");

        string? cancelledMarker = null;
        using var cancellation = new CancellationTokenSource();
        try
        {
            await sessions.RefreshAsync(new(fixture.Archive.Root), cancellation.Token, _ =>
            {
                var staging = Directory.EnumerateDirectories(Directory.GetParent(generation)!.FullName, ".*.staging")
                    .SingleOrDefault();
                if (staging is not null)
                {
                    var publishing = Path.Combine(Directory.GetParent(staging)!.FullName,
                        Path.GetFileName(staging)[1..^".staging".Length]);
                    cancelledMarker = ArchiveCacheStore.GenerationUsePath(publishing);
                    cancellation.Cancel();
                }
                return Task.CompletedTask;
            });
            throw new InvalidOperationException("a cancelled refresh published a generation");
        }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
        Require(cancelledMarker is not null, "refresh never exercised publication cancellation");
        // The cancelled generation was never published, so nothing will ever retire it:
        // its lease file must go with its staging folder, not stay behind for good.
        Require(!File.Exists(cancelledMarker!), "a cancelled publication left its lease file behind");
        var reopened = await sessions.OpenAsync(new(fixture.Archive.Root), CancellationToken.None);
        Require(reopened.CacheHit, "a cancelled publication broke the previous current generation");
    }

    public static async Task MidSweepReleaseRetiresGenerationAsync()
    {
        await using var fixture = await Fixture.CreateAsync();
        var cache = fixture.CreateCache();
        var otherCache = fixture.CreateCache();
        using var sessions = new ArchiveSessionManager(fixture.Native, cache);
        using var otherSessions = new ArchiveSessionManager(fixture.Native, otherCache);
        var first = await fixture.OpenAsync(sessions, cache);
        var generation = sessions.GetRequired(first.SessionId).GenerationPath;
        await AddUnitAsync(generation, 'a');
        var other = await otherSessions.OpenAsync(new(fixture.Archive.Root), CancellationToken.None);
        Require(other.CacheHit, "second cache owner did not reuse the current generation");
        await sessions.RefreshAsync(new(fixture.Archive.Root), CancellationToken.None);
        sessions.Close(first.SessionId);
        await otherCache.WaitForMaintenanceAsync(CancellationToken.None);
        await cache.WaitForMaintenanceAsync(CancellationToken.None);
        Require(Directory.Exists(generation), "active external generation was deleted early");

        var closed = 0;
        cache.OnBeforePreparedEviction = () =>
        {
            if (Interlocked.Exchange(ref closed, 1) == 0)
            {
                otherSessions.Close(other.SessionId);
            }
        };
        try
        {
            await cache.WaitForMaintenanceAsync(CancellationToken.None);
        }
        finally
        {
            cache.OnBeforePreparedEviction = null;
        }
        Require(Interlocked.CompareExchange(ref closed, 0, 0) == 1, "mid-sweep eviction hook did not run");
        Require(!Directory.Exists(generation), "generation released mid-sweep was trimmed instead of retired");
    }

    public static async Task PublishedManifestRemainsImmutableAsync()
    {
        await using var fixture = await Fixture.CreateAsync();
        var cache = fixture.CreateCache(long.MaxValue);
        string generation;
        string manifestPath;
        byte[] initialManifestBytes;
        DateTime initialManifestWriteUtc;
        using (var sessions = new ArchiveSessionManager(fixture.Native, cache))
        {
            var handle = await sessions.OpenAsync(new(fixture.Archive.Root), CancellationToken.None);
            generation = sessions.GetRequired(handle.SessionId).GenerationPath;
            manifestPath = Path.Combine(generation, "manifest.json");
            initialManifestBytes = await File.ReadAllBytesAsync(manifestPath);
            initialManifestWriteUtc = File.GetLastWriteTimeUtc(manifestPath);

            var lookups = new ArchiveLookupService(sessions, cache, fixture.Native);
            await lookups.WarmAsync(handle.SessionId, CancellationToken.None);
            await lookups.ResolveAsync(
                new ArchiveLookupRequest(handle.SessionId, ArchiveLookupKind.Extensions, Values: [".dds"]),
                CancellationToken.None);
            var names = new ArchiveNameIndexService(sessions, cache, fixture.Native);
            await names.WarmAsync(handle.SessionId, CancellationToken.None);
        }
        await cache.WaitForMaintenanceAsync(CancellationToken.None);
        Require(File.Exists(Path.Combine(generation, "archive.adi")), "dependency index was not published");
        Require(File.Exists(Path.Combine(generation, "lookups.bin")), "lookup index was not published");
        Require(File.Exists(Path.Combine(generation, "names.bin")), "name index was not published");
        Require(
            (await File.ReadAllBytesAsync(manifestPath)).SequenceEqual(initialManifestBytes)
            && File.GetLastWriteTimeUtc(manifestPath) == initialManifestWriteUtc,
            "published generation manifest changed after secondary index builds");

        using (var sessions = new ArchiveSessionManager(fixture.Native, cache))
        {
            ArchiveSessionHandle fallback;
            using (new FileStream(manifestPath, FileMode.Open, FileAccess.Read, FileShare.None))
            {
                fallback = await sessions.OpenAsync(new(fixture.Archive.Root), CancellationToken.None);
                Require(!fallback.CacheHit, "a locked manifest still reported a cache hit");
                Require(
                    Directory.Exists(generation)
                    && !Directory.Exists(Path.Combine(Directory.GetParent(generation)!.Parent!.FullName, "quarantine")),
                    "a sharing violation on manifest.json quarantined a valid generation");
            }
            sessions.Close(fallback.SessionId);
        }
        await cache.WaitForMaintenanceAsync(CancellationToken.None);
        var family = Directory.GetParent(generation)!.Parent!.FullName;
        Directory.Move(Path.Combine(family, "g"), Path.Combine(family, "generations"));
    }

    public static async Task AbandonedStagingAsync()
    {
        await using var fixture = await Fixture.CreateAsync();
        var cache = fixture.CreateCache();
        using var sessions = new ArchiveSessionManager(fixture.Native, cache);
        var handle = await fixture.OpenAsync(sessions, cache);
        var generations = Directory.GetParent(sessions.GetRequired(handle.SessionId).GenerationPath)!.FullName;
        string Staging(string id)
        {
            var path = Path.Combine(generations, $".{id}.staging");
            Directory.CreateDirectory(path);
            File.WriteAllText(Path.Combine(path, "archive.ali"), "half-written index");
            return path;
        }
        // A worker killed mid-build leaves its staging folder and an unheld lease file.
        var abandoned = Staging("20260101000000000-0123456789ab");
        var abandonedLease = ArchiveCacheStore.GenerationUsePath(Path.Combine(generations, "20260101000000000-0123456789ab"));
        Directory.CreateDirectory(Path.GetDirectoryName(abandonedLease)!);
        File.WriteAllText(abandonedLease, "");
        Directory.SetLastWriteTimeUtc(abandoned, DateTime.UtcNow.AddHours(-1));
        // Another process still building holds its lease: its folder must stay, however old.
        var building = Staging("20260101000000001-0123456789ac");
        var buildingLease = ArchiveCacheStore.GenerationUsePath(Path.Combine(generations, "20260101000000001-0123456789ac"));
        Directory.SetLastWriteTimeUtc(building, DateTime.UtcNow.AddHours(-1));
        // A fresh folder whose builder has not taken its lease yet must stay too.
        var fresh = Staging("20260101000000002-0123456789ad");
        using (new FileStream(buildingLease, FileMode.OpenOrCreate, FileAccess.Read, FileShare.ReadWrite))
        {
            // A just-written file can be held briefly by the system (a virus scan); the
            // sweep then leaves it for the next pass, so allow a few passes.
            for (var pass = 0; pass < 20 && Directory.Exists(abandoned); pass++)
            {
                await cache.WaitForMaintenanceAsync(CancellationToken.None);
                if (Directory.Exists(abandoned)) await Task.Delay(100);
            }
        }
        Require(!Directory.Exists(abandoned), "an abandoned staging folder was never swept");
        Require(!File.Exists(abandonedLease), "an abandoned staging folder's lease file was left behind");
        Require(Directory.Exists(building), "maintenance deleted a staging folder another process is building");
        Require(Directory.Exists(fresh), "maintenance deleted a fresh staging folder");
        Require(sessions.GetRequired(handle.SessionId).ReadEntry(2).Path == "text/hello.txt", "sweeping staging broke the active index");
    }

    public static async Task UrgentNotificationsAsync()
    {
        await using var fixture = await Fixture.CreateAsync();
        var cache = fixture.CreateCache(interval: TimeSpan.FromMinutes(5));
        using var sessions = new ArchiveSessionManager(fixture.Native, cache);
        var handle = await fixture.OpenAsync(sessions, cache);
        await cache.WaitForMaintenanceAsync(CancellationToken.None);
        cache.RequestMaintenance();
        var notifications = Task.Run(async () =>
        {
            for (var index = 0; index < 64; index++)
            {
                cache.RequestMaintenance();
                await Task.Delay(1);
            }
        });
        // Notifications arriving during an urgent drain must not insert the
        // ordinary five-minute delay before that drain can complete.
        await Task.WhenAll(notifications, cache.WaitForMaintenanceAsync(CancellationToken.None))
            .WaitAsync(TimeSpan.FromSeconds(3));
        Require(sessions.GetRequired(handle.SessionId).ReadEntry(2).Path == "text/hello.txt", "draining maintenance broke an active index");
    }

    public static async Task LockedFilesAsync()
    {
        await using var fixture = await Fixture.CreateAsync();
        var cache = fixture.CreateCache();
        using var sessions = new ArchiveSessionManager(fixture.Native, cache);
        var handle = await fixture.OpenAsync(sessions, cache);
        var generation = sessions.GetRequired(handle.SessionId).GenerationPath;
        var prepared = await AddUnitAsync(generation, 'a');
        // A legacy helper's mapped index is protective even without a marker lease.
        using (var mapped = ArchiveIndex.Open(Path.Combine(generation, "archive.ali")))
        {
            sessions.Close(handle.SessionId);
            await cache.WaitForMaintenanceAsync(CancellationToken.None);
            Require(prepared.All(File.Exists), "maintenance deleted a legacy reader's prepared files");
        }
        using (var reader = new FileStream(prepared[0], FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
        {
            await cache.WaitForMaintenanceAsync(CancellationToken.None);
            Require(prepared.All(File.Exists), "locked payload eviction removed its companions");
            // Once superseded, the complete generation must also respect an
            // external prepared-file reader, even if it permits file deletion.
            await sessions.RefreshAsync(new(fixture.Archive.Root), CancellationToken.None);
            await cache.WaitForMaintenanceAsync(CancellationToken.None);
            Require(Directory.Exists(generation) && prepared.All(File.Exists), "retirement ignored an open prepared file");
            var removable = await AddUnitAsync(generation, 'b');
            await cache.WaitForMaintenanceAsync(CancellationToken.None);
            Require(removable.All(path => !File.Exists(path)), "locked files prevented other safe eviction");
            Require(prepared.All(File.Exists) && Size(cache.CatalogueRoot) > Fixture.MaximumBytes,
                "cleanup falsely counted locked bytes as removed");
        }
        await cache.WaitForMaintenanceAsync(CancellationToken.None);
        Require(prepared.All(path => !File.Exists(path)) && Size(cache.CatalogueRoot) <= Fixture.TargetBytes,
            "maintenance did not retry a released file lock");
    }

    public static async Task BusyOpenCancellationAsync()
    {
        await using var fixture = await Fixture.CreateAsync();
        var cache = fixture.CreateCache();
        using var sessions = new ArchiveSessionManager(fixture.Native, cache);
        var first = await fixture.OpenAsync(sessions, cache);
        var generation = sessions.GetRequired(first.SessionId).GenerationPath;
        sessions.Close(first.SessionId);
        await cache.WaitForMaintenanceAsync(CancellationToken.None);
        using (var busy = new FileStream(ArchiveCacheStore.GenerationUsePath(generation), FileMode.Open, FileAccess.ReadWrite, FileShare.None))
        {
            using var cancellation = new CancellationTokenSource(TimeSpan.FromMilliseconds(100));
            try
            {
                await sessions.OpenAsync(new(fixture.Archive.Root), cancellation.Token);
                throw new InvalidOperationException("a busy open ignored cancellation");
            }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
            Require(Directory.Exists(generation) && !Directory.Exists(Path.Combine(Directory.GetParent(generation)!.Parent!.FullName, "quarantine")),
                "a maintenance sharing violation quarantined a valid generation");
        }
        var reopened = await sessions.OpenAsync(new(fixture.Archive.Root), CancellationToken.None);
        Require(reopened.CacheHit, "a cancelled busy open broke cache reuse");
    }

    public static async Task ScopeAndInterruptedRetirementAsync()
    {
        await using var fixture = await Fixture.CreateAsync();
        var cache = fixture.CreateCache();
        using var sessions = new ArchiveSessionManager(fixture.Native, cache);
        var handle = await fixture.OpenAsync(sessions, cache);
        var generation = sessions.GetRequired(handle.SessionId).GenerationPath;
        var retired = Path.Combine(Directory.GetParent(generation)!.FullName, $".retired-{Guid.NewGuid():N}");
        Directory.CreateDirectory(retired);
        await File.WriteAllBytesAsync(Path.Combine(retired, "leftover.dds"), new byte[96 * 1024]);
        // Interrupted retirement may already have deleted its manifest.
        var staging = Path.Combine(Directory.GetParent(generation)!.FullName, ".fixture.staging");
        Directory.CreateDirectory(staging);
        var staged = Path.Combine(staging, "manifest.json");
        await File.WriteAllTextAsync(staged, "unfinished publication");
        var foreign = Path.Combine(cache.CatalogueRoot, "user-files");
        Directory.CreateDirectory(foreign);
        var keep = Path.Combine(foreign, "project.keep");
        await File.WriteAllTextAsync(keep, "not a catalogue generation");
        await cache.WaitForMaintenanceAsync(CancellationToken.None);
        Require(!Directory.Exists(retired), "interrupted retirement was not resumed");
        Require(File.Exists(staged) && File.Exists(keep) && File.Exists(Path.Combine(generation, "archive.ali")),
            "maintenance crossed an ownership/publication boundary");
    }

    private static async Task<string[]> AddUnitAsync(string generation, char identity, bool extensionless = false)
    {
        var hash = new string(identity, 64);
        var shard = Path.Combine(generation, "p", hash[..2]);
        Directory.CreateDirectory(shard);
        var payload = Path.Combine(shard, hash + (extensionless ? "" : ".dds"));
        var paths = new[] { payload, payload + ".meta.json", payload + ".content-v1.json", payload + ".content-v1.txt" };
        await File.WriteAllBytesAsync(payload, new byte[96 * 1024]);
        foreach (var path in paths.Skip(1)) await File.WriteAllTextAsync(path, "derived companion");
        foreach (var path in paths) File.SetLastWriteTimeUtc(path, DateTime.UtcNow.AddDays(-2));
        return paths;
    }

    private static long Size(string path) => Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories).Sum(file => new FileInfo(file).Length);

    // current.json's generation_id is a file value: a crafted or corrupt one that
    // names a folder outside the cache (an absolute path, "..", a separator)
    // must not make the worker lease, quarantine or write beside that folder.
    // The open rebuilds instead.
    public static async Task PointerOutsideCacheAsync()
    {
        await using var fixture = await Fixture.CreateAsync();
        var victimRoot = Path.Combine(fixture.Archive.OutputRoot, "victim");
        var victim = Path.Combine(victimRoot, "0036");
        Directory.CreateDirectory(victim);
        var victimPamt = Path.Combine(victim, "0.pamt");
        File.Copy(fixture.Archive.Pamt, victimPamt);
        await File.WriteAllTextAsync(Path.Combine(victimRoot, "CrimsonDesert.exe"), "owned synthetic executable");
        var victimHash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(victimPamt)));
        var seed = fixture.CreateCache(long.MaxValue);
        using (var sessions = new ArchiveSessionManager(fixture.Native, seed))
        {
            await fixture.OpenAsync(sessions, seed);
        }
        var pointerPath = Path.Combine(seed.CatalogueRoot, ArchiveCacheStore.DeriveRootId(fixture.Archive.Root), "current.json");
        var original = JsonSerializer.Deserialize<ArchiveCurrentPointer>(
            await File.ReadAllTextAsync(pointerPath), WorkerProtocol.JsonOptions)!;
        Require(ArchiveCacheStore.IsGenerationId(original.GenerationId), "the cache wrote a generation id it would refuse");
        var crafted = new[]
        {
            victim,
            @"..\..\..\..\..\victim\0036",
            "../../../../../victim/0036",
            original.GenerationId + @"\..\..\..\..\..\..\victim\0036",
            original.GenerationId.ToUpperInvariant(),
            original.GenerationId[..29],
            "",
        };
        foreach (var generationId in crafted)
        {
            await File.WriteAllTextAsync(pointerPath,
                JsonSerializer.Serialize(original with { GenerationId = generationId }, WorkerProtocol.JsonOptions));
            var cache = fixture.CreateCache(long.MaxValue);
            var health = await cache.InspectAsync(fixture.Archive.Root, CancellationToken.None);
            Require(health.State == "invalid", $"a pointer naming '{generationId}' was not reported invalid");
            using (var sessions = new ArchiveSessionManager(fixture.Native, cache))
            {
                var reopened = await sessions.OpenAsync(new(fixture.Archive.Root), CancellationToken.None);
                Require(!reopened.CacheHit, $"a pointer naming '{generationId}' was reused");
            }
            await cache.WaitForMaintenanceAsync(CancellationToken.None);
            Require(File.Exists(victimPamt)
                && Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(victimPamt))) == victimHash,
                $"a pointer naming '{generationId}' moved or changed a folder outside the cache");
            Require(Directory.GetFileSystemEntries(victim).Length == 1
                && Directory.GetFileSystemEntries(victimRoot).Length == 2
                && !Directory.Exists(Path.Combine(fixture.Archive.OutputRoot, ".leases")),
                $"a pointer naming '{generationId}' made the worker write beside a folder outside the cache");
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private sealed class Fixture(SyntheticArchiveFixture archive) : IAsyncDisposable
    {
        public const long MaximumBytes = 64 * 1024;
        public const long TargetBytes = 48 * 1024;
        private readonly List<ArchiveCacheStore> _caches = [];
        private readonly string[] _sourceHashes = new[] { archive.Pamt, archive.Paz, archive.Pathc }
            .Select(path => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)))).ToArray();
        public SyntheticArchiveFixture Archive => archive;
        public NativeArchiveCore Native { get; } = new();
        public static async Task<Fixture> CreateAsync() => new(await SyntheticArchiveFixture.CreateAsync());

        public ArchiveCacheStore CreateCache(long maximum = MaximumBytes, TimeSpan? interval = null)
        {
            var cache = new ArchiveCacheStore(Path.Combine(archive.OutputRoot, "cache"), maximum, Math.Min(maximum, TargetBytes), interval ?? TimeSpan.Zero);
            _caches.Add(cache);
            return cache;
        }

        public async Task<ArchiveSessionHandle> OpenAsync(ArchiveSessionManager sessions, ArchiveCacheStore cache)
        {
            var handle = await sessions.OpenAsync(new(archive.Root), CancellationToken.None);
            await new ArchiveLookupService(sessions, cache, Native).WarmAsync(handle.SessionId, CancellationToken.None);
            return handle;
        }

        public async ValueTask DisposeAsync()
        {
            try
            {
                foreach (var cache in _caches)
                    await cache.WaitForMaintenanceAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(5));
                var hashes = new[] { archive.Pamt, archive.Paz, archive.Pathc }
                    .Select(path => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))));
                Require(hashes.SequenceEqual(_sourceHashes), "cache maintenance changed source archives");
            }
            finally
            {
                await archive.DisposeAsync();
            }
        }
    }
}

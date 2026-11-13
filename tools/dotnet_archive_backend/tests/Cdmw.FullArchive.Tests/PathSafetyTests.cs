using System.Security.Cryptography;
using System.Text;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;
using Cdmw.FullArchive.Worker;

namespace Cdmw.FullArchive.Tests;

// Paths the worker builds from a request or from an archive's own entry paths
// never reach a game installation or the archive cache.
internal static class PathSafetyTests
{
    public static async Task ExportDestinationAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync();
        var cacheRoot = Path.Combine(fixture.OutputRoot, "cache");
        var game = Path.Combine(fixture.OutputRoot, "game");
        Directory.CreateDirectory(Path.Combine(game, "bin64"));
        Directory.CreateDirectory(Path.Combine(game, "meta"));
        Directory.CreateDirectory(Path.Combine(game, "0036"));
        await File.WriteAllTextAsync(Path.Combine(game, "bin64", "CrimsonDesert.exe"), "owned synthetic executable");
        await File.WriteAllTextAsync(Path.Combine(game, "meta", "0.papgt"), "owned synthetic group table");
        // A junction outside the game into one of its folders: the path as written
        // overlaps nothing, where it leads is inside the game.
        var link = Path.Combine(fixture.OutputRoot, "link");
        using (var mklink = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(
                   "cmd.exe", $"/c mklink /J \"{link}\" \"{Path.Combine(game, "0036")}\"")
               { CreateNoWindow = true, UseShellExecute = false }))
        {
            mklink!.WaitForExit();
        }
        Require(Directory.Exists(link), "the test junction was not created");
        var gameWithArchives = Path.Combine(fixture.OutputRoot, "packages");
        Directory.CreateDirectory(gameWithArchives);
        File.Copy(fixture.Pamt, Path.Combine(gameWithArchives, "0.pamt"));
        var before = Hashes(fixture.Root);
        var native = new NativeArchiveCore();
        var cache = new ArchiveCacheStore(cacheRoot);
        using var sessions = new ArchiveSessionManager(native, cache);
        var handle = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None);
        var exports = new ArchiveExportService(
            sessions, new ArchiveQueryService(sessions), new ArchiveLookupService(sessions, cache, native), native);
        ArchiveExportRequest Request(string destination, bool replace) => new(
            handle.SessionId, ArchiveExportSelectionKind.EntryIds, destination, EntryIds: [0],
            CollisionPolicy: ArchiveExportCollisionPolicy.Overwrite, IncludePackageRoot: true, ReplaceDestination: replace);

        try
        {
            foreach (var (destination, replace) in new[]
            {
                (fixture.Root, true),
                (fixture.Root, false),
                (Path.Combine(fixture.Root, "base"), false),
                (Path.Combine(fixture.Root, "base", "new-folder"), false),
                (cacheRoot, true),
                (Path.Combine(cacheRoot, "index"), false),
                (fixture.OutputRoot, true),
                (game, true),
                (Path.Combine(game, "mods"), false),
                (gameWithArchives, false),
                (Path.Combine(link, "out"), false),
                (Path.Combine(link, "out"), true),
                (link, false),
            })
            {
                var refused = false;
                try
                {
                    await exports.ExportAsync(Request(destination, replace), CancellationToken.None);
                }
                catch (ExportDestinationRefusedException)
                {
                    refused = true;
                }
                Require(refused, $"an export to '{destination}' (replace: {replace}) was not refused");
                Require(Hashes(fixture.Root).SequenceEqual(before), $"an export to '{destination}' changed the archive source");
                Require(File.Exists(Path.Combine(game, "bin64", "CrimsonDesert.exe")) && !Directory.Exists(Path.Combine(game, "mods"))
                    && Directory.GetFileSystemEntries(Path.Combine(game, "0036")).Length == 0
                    && File.Exists(Path.Combine(gameWithArchives, "0.pamt")) && Directory.GetFileSystemEntries(gameWithArchives).Length == 1,
                    $"an export to '{destination}' wrote into a game folder");
                Require(Directory.Exists(cacheRoot), $"an export to '{destination}' moved the cache");
            }
            var allowed = Path.Combine(fixture.OutputRoot, "export");
            var exported = await exports.ExportAsync(Request(allowed, true), CancellationToken.None);
            Require(exported.Exported == 1, "an export to an ordinary folder was refused");
            // CDMW's archive-style mods hold their own meta\0.papgt; that alone is not a game.
            var mod = Path.Combine(fixture.OutputRoot, "mods", "My Archive Mod");
            Directory.CreateDirectory(Path.Combine(mod, "meta"));
            await File.WriteAllTextAsync(Path.Combine(mod, "meta", "0.papgt"), "the mod's own group table");
            var intoMod = await exports.ExportAsync(Request(Path.Combine(mod, "extracted"), false), CancellationToken.None);
            Require(intoMod.Exported == 1, "an export into a CDMW archive mod folder was refused");
        }
        finally
        {
            if (Directory.Exists(link)) Directory.Delete(link);  // the junction only, never its target
        }
    }

    // archive.ali names every entry's PAMT and PAZ. An index whose names lead
    // outside the package root (another folder, or another host by UNC) is
    // invalid: cache_health says so, the open rebuilds it, and nothing opens
    // the path it named.
    public static async Task TamperedIndexAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAsync();
        var cacheRoot = Path.Combine(fixture.OutputRoot, "cache");
        var native = new NativeArchiveCore();
        string generation;
        {
            var seed = new ArchiveCacheStore(cacheRoot);
            using var sessions = new ArchiveSessionManager(native, seed);
            var handle = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None);
            generation = sessions.GetRequired(handle.SessionId).GenerationPath;
        }
        // Short enough to fit in place of entry 0's PAMT path, and outside the package root.
        var outsideFolder = Path.Combine(Path.GetDirectoryName(Path.GetDirectoryName(fixture.Root)!)!, "o");
        var outside = outsideFolder + Path.DirectorySeparatorChar;
        foreach (var prefix in new[] { outside, @"\\127.0.0.1\share\" })
        {
            var indexPath = Path.Combine(generation, "archive.ali");
            var original = await File.ReadAllBytesAsync(indexPath);
            // The header's records and strings offsets, then entry 0's PAMT string range.
            var records = (int)BitConverter.ToUInt64(original, 24);
            var strings = (int)BitConverter.ToUInt64(original, 32);
            var pamtOffset = (int)BitConverter.ToUInt64(original, records + 8);
            var pamtLength = (int)BitConverter.ToUInt32(original, records + 52);
            Require(prefix.Length + 5 < pamtLength, "the test's replacement path does not fit");
            var replacement = prefix + new string('x', pamtLength - prefix.Length - 5) + ".pamt";
            System.Text.Encoding.ASCII.GetBytes(replacement).CopyTo(original, strings + pamtOffset);
            await File.WriteAllBytesAsync(indexPath, original);
            var cache = new ArchiveCacheStore(cacheRoot);
            var health = await cache.InspectAsync(fixture.Root, CancellationToken.None);
            Require(health.State == "invalid", $"an index naming '{prefix}' was not reported invalid");
            using var sessions = new ArchiveSessionManager(native, cache);
            var reopened = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None);
            Require(!reopened.CacheHit, $"an index naming '{prefix}' was reused");
            var session = sessions.GetRequired(reopened.SessionId);
            Require(session.ReadEntry(0).SourcePamt.StartsWith(fixture.Root, StringComparison.OrdinalIgnoreCase),
                "the rebuilt index does not name the package's own files");
            generation = session.GenerationPath;
        }
        Require(!Directory.Exists(outsideFolder), "a source outside the root was created");
    }

    public static Task LanguageNamesAsync()
    {
        foreach (var name in new[] { "eng", "kor", "zh-TW", "pt_BR", "a" })
        {
            Require(ArchiveItemSources.IsLanguageName(name), $"'{name}' was refused as a language");
        }
        foreach (var name in new[] { "", "../x", "a/b", @"a\b", "..", "x:y", "eng.", " eng", new string('a', 33) })
        {
            Require(!ArchiveItemSources.IsLanguageName(name), $"'{name}' was accepted as a language");
        }
        return Task.CompletedTask;
    }

    // The review of rr/parity-deps-p20: only junctions and symbolic links are links.
    // OneDrive placeholders and redirected folders carry the reparse attribute too
    // and must not be refused; no test can make such a folder without the cloud
    // filter driver, so the tag decision is tested on the tags themselves, and the
    // folder check on a real junction.
    public static Task LinkTagsAsync()
    {
        Require(GameFolderPolicy.IsLinkTag(0xA0000003), "a junction's tag is a link");
        Require(GameFolderPolicy.IsLinkTag(0xA000000C), "a symbolic link's tag is a link");
        foreach (var tag in new uint[] { 0, 0x9000001A, 0x9000601A, 0x9000101A, 0x80000013, 0x8000001B, 0x80000017 })
        {
            Require(!GameFolderPolicy.IsLinkTag(tag), $"tag 0x{tag:X8} (not a junction or symbolic link) was a link");
        }
        var root = Path.Combine(Path.GetTempPath(), "cdmw-link-tags-" + Guid.NewGuid().ToString("N"));
        var target = Path.Combine(root, "target");
        var junction = Path.Combine(root, "junction");
        Directory.CreateDirectory(target);
        File.WriteAllText(Path.Combine(root, "file.txt"), "x");
        try
        {
            using (var mklink = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(
                       "cmd.exe", $"/c mklink /J \"{junction}\" \"{target}\"")
                   { CreateNoWindow = true, UseShellExecute = false }))
            {
                mklink!.WaitForExit();
            }
            Require(Directory.Exists(junction), "the test junction was not created");
            Require(GameFolderPolicy.IsLink(junction), "a junction was not a link");
            Require(GameFolderPolicy.HasLinkOnPath(Path.Combine(junction, "below")), "a path through a junction had no link");
            Require(!GameFolderPolicy.IsLink(target), "an ordinary folder was a link");
            Require(!GameFolderPolicy.IsLink(Path.Combine(root, "file.txt")), "an ordinary file was a link");
            Require(!GameFolderPolicy.IsLink(Path.Combine(root, "missing")), "a missing path was a link");
            Require(!GameFolderPolicy.HasLinkOnPath(Path.Combine(target, "below")), "a plain path had a link");
            var refused = false;
            try
            {
                GameFolderPolicy.RejectLinks(junction);
            }
            catch (InvalidDataException)
            {
                refused = true;
            }
            Require(refused, "RejectLinks let a junction through");
            GameFolderPolicy.RejectLinks(target);
        }
        finally
        {
            if (Directory.Exists(junction)) Directory.Delete(junction);
            Directory.Delete(root, recursive: true);
        }
        // The refusal is an IOException now (InvalidDataException is sealed), and keeps its code.
        var exception = new ExportDestinationRefusedException("refused");
        Require(exception is IOException, "the refusal is not an IOException");
        Require(WorkerServer.ClassifyFailure(exception).Code == "export_destination_protected",
            "the refusal lost its export_destination_protected code");
        return Task.CompletedTask;
    }

    // F1: the linear engine finds what the backtracking one found, and a hostile
    // prefab takes milliseconds, not hours.
    public static Task PrefabPathsLinearAsync()
    {
        string[] pieces = ["object", "Character", "vehicle", "environment", "effect", "/", "\\", ".", "pac", "PAM",
            "pamlod", "pami", "prefab", "x", "_9", "-", " ", "\u017F", "\u212A", "\n", "objec", "/a.pac"];
        var random = new Random(12345);
        for (var round = 0; round < 4000; round++)
        {
            var text = new StringBuilder();
            var count = 1 + random.Next(40);
            for (var i = 0; i < count; i++) text.Append(pieces[random.Next(pieces.Length)]);
            var bytes = Encoding.UTF8.GetBytes(text.ToString());
            var linear = ArchiveNameIndexBuilder.ExtractPrefabModelPaths(bytes);
            var reference = ArchiveNameIndexBuilder.ExtractPrefabModelPaths(bytes, ArchiveNameIndexBuilder.PrefabModelPathPatternBacktracking);
            Require(linear.SequenceEqual(reference), $"the engines differ on: {text}");
        }
        var hostile = new StringBuilder();
        while (hostile.Length < 16 << 20) hostile.Append("object/");
        hostile.Append(".pac");
        var watch = System.Diagnostics.Stopwatch.StartNew();
        var found = ArchiveNameIndexBuilder.ExtractPrefabModelPaths(Encoding.UTF8.GetBytes(hostile.ToString()));
        Require(found.Length == 1 && found[0].Length == hostile.Length, "the hostile prefab's one path was not found");
        Require(watch.Elapsed < TimeSpan.FromSeconds(10), $"the hostile prefab took {watch.Elapsed}");
        return Task.CompletedTask;
    }

    // F6: a key's joined display names stop at MaximumJoinedDisplayNames.
    public static Task JoinedDisplayNamesAsync()
    {
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var i = 0; i < 5000; i++) ArchiveNameIndexBuilder.AddDisplayName(map, "cd_key", $"Name {i}");
        ArchiveNameIndexBuilder.AddDisplayName(map, "cd_key", "name 3");
        var names = map["cd_key"].Split(" / ");
        Require(names.Length == ArchiveNameIndexBuilder.MaximumJoinedDisplayNames, $"{names.Length} names were joined");
        Require(names[0] == "Name 0" && names[^1] == $"Name {ArchiveNameIndexBuilder.MaximumJoinedDisplayNames - 1}", "the first names were not the ones kept");
        // The game's own largest key joins 428 names; all of them stay.
        var real = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var i = 0; i < 428; i++) ArchiveNameIndexBuilder.AddDisplayName(real, "cd_t0000_hyperspace_remotecontrol_0001", $"Name {i}");
        Require(real["cd_t0000_hyperspace_remotecontrol_0001"].Split(" / ").Length == 428, "the game's 428 joined names were cut");
        return Task.CompletedTask;
    }

    private static string[] Hashes(string root) =>
        Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories).Order(StringComparer.Ordinal)
            .Select(path => path + ":" + Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)))).ToArray();

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}

using System.Security.Cryptography;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

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
        await File.WriteAllTextAsync(Path.Combine(game, "bin64", "CrimsonDesert.exe"), "owned synthetic executable");
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
        })
        {
            var refused = false;
            try
            {
                await exports.ExportAsync(Request(destination, replace), CancellationToken.None);
            }
            catch (InvalidDataException)
            {
                refused = true;
            }
            Require(refused, $"an export to '{destination}' (replace: {replace}) was not refused");
            Require(Hashes(fixture.Root).SequenceEqual(before), $"an export to '{destination}' changed the archive source");
            Require(File.Exists(Path.Combine(game, "bin64", "CrimsonDesert.exe")) && !Directory.Exists(Path.Combine(game, "mods"))
                && File.Exists(Path.Combine(gameWithArchives, "0.pamt")) && Directory.GetFileSystemEntries(gameWithArchives).Length == 1,
                $"an export to '{destination}' wrote into a game folder");
            Require(Directory.Exists(cacheRoot), $"an export to '{destination}' moved the cache");
        }
        var allowed = Path.Combine(fixture.OutputRoot, "export");
        var exported = await exports.ExportAsync(Request(allowed, true), CancellationToken.None);
        Require(exported.Exported == 1, "an export to an ordinary folder was refused");
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

    private static string[] Hashes(string root) =>
        Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories).Order(StringComparer.Ordinal)
            .Select(path => path + ":" + Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)))).ToArray();

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}

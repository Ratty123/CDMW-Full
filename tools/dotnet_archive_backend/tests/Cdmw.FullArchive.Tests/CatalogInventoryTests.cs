using System.Text.Json;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

// The catalogue builders read the per-extension entry lists instead of every entry.
// What they keep, and what they build from it, must not change.
internal static class CatalogInventoryTests
{
    private static void Check(bool condition, string message)
    { if (!condition) throw new InvalidOperationException(message); }

    private static IEnumerable<ArchiveEntryDto> Everything(ArchiveSession session)
    {
        for (long entryId = 0; entryId < session.Index.EntryCount; entryId++)
            yield return session.Index.ReadEntry(entryId, session.Id);
    }

    // A texture, sound or film names no other file. Its bytes are not read for
    // references, so they can neither overflow the lookup nor slow it down.
    public static async Task OpaquePayloadsAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateOpaquePayloadsAsync();
        var native = new NativeArchiveCore();
        var cache = new ArchiveCacheStore(fixture.OutputRoot);
        using var sessions = new ArchiveSessionManager(native, cache);
        var opened = await sessions.OpenAsync(new(fixture.Root), CancellationToken.None);
        var session = sessions.GetRequired(opened.SessionId);
        var byPath = Everything(session).ToDictionary(static entry => entry.Path, StringComparer.OrdinalIgnoreCase);
        var lookup = new ArchiveLookupService(sessions, cache, native);

        async Task<(ArchiveAssociationResult Result, List<string> Scanned)> PreviewAsync(string path)
        {
            var scanned = new List<string>();
            var result = await lookup.FindAssociationCandidatesAsync(
                new ArchiveAssociationRequest(opened.SessionId, byPath[path].EntryId, 4095, ArchiveAssociationPurpose.Preview),
                CancellationToken.None,
                update =>
                {
                    if (update.Phase == "preview_association_scan" && update.CurrentItem is { } item) scanned.Add(item);
                    return Task.CompletedTask;
                });
            return (result, scanned);
        }

        var texture = await PreviewAsync("ui/texture/fog.dds");
        Check(!texture.Result.Truncated, "a texture's pixels made its preview lookup incomplete");
        Check(!texture.Scanned.Contains("ui/texture/fog.dds"), "a texture's pixels were read for file references");
        Check(texture.Result.Candidates.Select(static entry => entry.Path).SequenceEqual(["ui/texture/fog.xml"]),
            "a texture's same-name files are no longer its related files");
        var sound = await PreviewAsync("sound/windows/voice.wem");
        Check(!sound.Result.Truncated && sound.Scanned.Count == 0, "a sound's samples were read for file references");
        var unnamed = await PreviewAsync("sound/windows/.vce_meta");
        Check(!unnamed.Result.Truncated, "a file named by its extension alone has no related-files answer");
    }

    public static async Task RunAsync()
    {
        foreach (var path in new[] {
            "gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody", "GameData\\BinaryStaticInfo__\\bin\\iteminfo.dlc_01.staticinfoheader",
            "/gamedata/binary__/client/bin/stringinfo.pabgb", "gamedata/binary__/client/bin/stringinfo.pabgh",
            "gamedata/stringtable/binary__/eng/item.paloc" })
            Check(ArchiveItemSources.IsCandidatePath(path), $"'{path}' is a table the item sources read");
        foreach (var path in new[] {
            "character/model/hero.pac", "gamedata/binarystaticinfo__/bin/iteminfo.xml", "gamedata/binarystaticinfo__/bin/notes.txt",
            "ui/gamedata/binary__/client/bin/stringinfo.pabgb", "gamedata/stringtable/binary__/eng/item.paloc.bak" })
            Check(!ArchiveItemSources.IsCandidatePath(path), $"'{path}' is not a table the item sources read");

        await using var fixture = await SyntheticArchiveFixture.CreateAssociatedAssetsAsync();
        var native = new NativeArchiveCore();
        using var sessions = new ArchiveSessionManager(native, new ArchiveCacheStore(fixture.OutputRoot));
        var opened = await sessions.OpenAsync(new(fixture.Root), CancellationToken.None);
        var session = sessions.GetRequired(opened.SessionId);
        var all = Everything(session).ToArray();
        Check(all.Length > 0, "the fixture archive is empty");

        foreach (var extensions in new[] { ArchiveCharacterCatalogBuilder.InventoryExtensions, ArchiveNpcCatalogBuilder.InventoryExtensions })
        {
            var wanted = new HashSet<string>(extensions, StringComparer.OrdinalIgnoreCase);
            var expected = all.Where(entry => ArchiveItemSources.IsCandidatePath(entry.Path)
                || (entry.Path.StartsWith("character/", StringComparison.OrdinalIgnoreCase) && wanted.Contains(entry.Extension)))
                .Select(static entry => entry.EntryId).ToArray();
            var listed = ArchiveCatalogInventory.CharacterEntries(session, extensions, CancellationToken.None).ToArray();
            Check(expected.Length > 0 && expected.Length < all.Length, "the fixture does not exercise the inventory filter");
            Check(listed.Select(static entry => entry.EntryId).SequenceEqual(expected), "the catalogue inventory differs from a full walk");
            Check(listed.All(entry => entry == session.Index.ReadEntry(entry.EntryId, session.Id)), "an inventory entry differs from the index entry");
        }

        byte[] Read(ArchiveEntryDto entry) => native.Decode(entry).Bytes;
        var characters = JsonSerializer.Serialize(ArchiveCharacterCatalogBuilder.Build(fixture.Root, "fixture", all, Read, CancellationToken.None));
        var listedCharacters = JsonSerializer.Serialize(ArchiveCharacterCatalogBuilder.Build(fixture.Root, "fixture",
            ArchiveCatalogInventory.CharacterEntries(session, ArchiveCharacterCatalogBuilder.InventoryExtensions, CancellationToken.None), Read, CancellationToken.None));
        Check(characters == listedCharacters, "the character catalogue changed with the listed inventory");
        var npcs = JsonSerializer.Serialize(ArchiveNpcCatalogBuilder.Build(fixture.Root, "fixture", all, Read, CancellationToken.None));
        var listedNpcs = JsonSerializer.Serialize(ArchiveNpcCatalogBuilder.Build(fixture.Root, "fixture",
            ArchiveCatalogInventory.CharacterEntries(session, ArchiveNpcCatalogBuilder.InventoryExtensions, CancellationToken.None), Read, CancellationToken.None));
        Check(npcs == listedNpcs, "the NPC catalogue changed with the listed inventory");

        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();
        try
        {
            _ = ArchiveCatalogInventory.CharacterEntries(session, ArchiveNpcCatalogBuilder.InventoryExtensions, cancelled.Token).ToArray();
            throw new InvalidOperationException("a cancelled inventory read went on");
        }
        catch (OperationCanceledException) { }
    }
}

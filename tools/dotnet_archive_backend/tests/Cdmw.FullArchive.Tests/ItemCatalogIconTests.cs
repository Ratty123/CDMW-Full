using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

internal static class ItemCatalogIconTests
{
    public static async Task RunAsync()
    {
        CheckBoundedModelList();
        foreach (var compact in new[] { false, true })
        {
            await using var fixture = await SyntheticArchiveFixture.CreateCurrentItemNamesAsync(compactDlc: compact, explicitIcons: true);
            var native = new NativeArchiveCore();
            using var sessions = new ArchiveSessionManager(native, new ArchiveCacheStore(Path.Combine(fixture.Root, "cache")));
            var handle = await sessions.OpenAsync(new OpenArchiveRequest(fixture.Root), CancellationToken.None);
            var builder = new ArchiveItemCatalogBuildService(sessions, native);
            var service = new ArchiveItemCatalogService(sessions, builder);
            var result = await service.SearchAsync(new ItemCatalogSearchRequest(handle.SessionId, "1236"), null, CancellationToken.None);
            var item = result.Items.Single();
            Require(item.IconPaths.SequenceEqual(new[] { "ui/texture/icon/itemicon_prefab_gimmick_test_sail.dds" }), "Explicit icon was lost or replaced by a placeholder");
            Require(item.ModelStems.Contains("gimmick_test_sail") && item.PacFiles.Contains("test_sail_mesh.pac"), "Icon-linked prefab dependencies were not recovered");
            Require(item.ModelStems[0] == "gimmick_test_sail", "The bounded Item Finder row lost its source prefab context");
            Require(item.ModelStems.Contains("test_sail_lod") && !item.ModelStems.Contains("test_sail_instance"), "Nested prefab/PAMI resolution truncated a static-mesh extension");
            Require(!item.ModelStems.Contains("cd_t9999_empty"), "Empty prefab was advertised as usable geometry");
            var icons = new ArchiveItemIconService(sessions, builder, new ArchiveEntryPreparationService(sessions, native));
            var loaded = await icons.LoadAsync(new ItemIconBatchRequest(handle.SessionId, [1236]), CancellationToken.None);
            Require(loaded.Items.Single().SourcePath is { } source && File.ReadAllText(source) == "DDS owned sail icon", "The icon loader prepared the wrong archive asset");
            var session = sessions.GetRequired(handle.SessionId);
            var mesh = session.Index.FindEntriesByPath("object/test_sail_mesh.pac").First();
            Require(string.IsNullOrEmpty(session.ReadEntry(mesh.EntryId).ExactName), "Icon-derived model evidence was promoted to an exact item prefab reference");
        }
    }

    private static void CheckBoundedModelList()
    {
        var files = Enumerable.Range(0, 40).Select(index => $"piece_{index}.pac").ToArray();
        var stems = Enumerable.Range(0, 40).Select(index => $"piece_{index}").ToArray();
        var record = new ArchiveItemCatalogRecord(1, "armor", "Armor", [], [], stems, files, []);
        var row = ArchiveItemCatalogService.ToContract(record);
        Require(row.PacFiles.SequenceEqual(files.Take(32)), "The detail pane lost worn pieces or exceeded its model bound");
        Require(row.ModelStems.SequenceEqual(stems.Take(32)), "The detail pane lost prefab context or exceeded its stem bound");
        row = ArchiveItemCatalogService.ToContract(record with { PacFiles = files.Take(5).ToArray() });
        Require(row.PacFiles.Count == 5, "A five-piece set must show its full PAC list");
        row = ArchiveItemCatalogService.ToContract(record with { PacFiles = [new string('p', 200)] });
        Require(row.PacFiles[0].Length == 160, "Model path display strings must remain bounded");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}

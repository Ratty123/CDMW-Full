using System.Text.Json;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

internal static class ItemCatalogueDefinitionTests
{
    internal static Task RunAsync()
    {
        using var cases = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "ItemCatalogueDefinitions.json")));
        var id = 1;
        foreach (var row in cases.RootElement.EnumerateArray())
        {
            var name = row[0].GetString()!;
            var catalog = ArchiveItemCatalog.FromRecords([
                new ArchiveItemCatalogRecord(id++, name, "Bow Helmet Crate", ["boots necklace sword"], [],
                    ["horse_armor"], ["necklace.pac"], [], EquipType: row[1].GetString()!)
            ]);
            var actual = catalog.Items.Single();
            if (actual.Category != row[2].GetString() || actual.Group != row[3].GetString())
                throw new InvalidOperationException($"{name}: {actual.Category}/{actual.Group} did not follow its definition");
        }
        var paging = ArchiveItemCatalog.FromRecords([
            new ArchiveItemCatalogRecord(1, "base_sail", "A", [], [], [], [], [], EquipType: "ShipSail"),
            new ArchiveItemCatalogRecord(2, "dlc_sail", "B", [], [], [], [], [], EquipType: "ShipSail", IsDlc: true),
            new ArchiveItemCatalogRecord(3, "dlc_sail_2", "C", [], [], [], [], [], EquipType: "ShipSail", IsDlc: true),
            new ArchiveItemCatalogRecord(4, "dlc_helm", "D", [], [], [], [], [], EquipType: "Helm", IsDlc: true),
        ]);
        var page = paging.Search("", "Ships", "Sails", 1, 1, onlyDlc: true);
        if (page.TotalMatches != 2 || page.Items.Single().ItemId != 3
            || paging.Search("base", "Ships", null, 0, 72, onlyDlc: true).TotalMatches != 0
            || paging.Search("", "Ships", "Cannons", 0, 72, onlyDlc: true).TotalMatches != 0)
            throw new InvalidOperationException("DLC filtering must precede category/group search and pagination");
        return Task.CompletedTask;
    }
}

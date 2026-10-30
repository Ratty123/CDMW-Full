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
        // Cache loads also pass saved records through FromRecords: stale armor
        // categories must not survive, and facets/search must use the new result.
        var socketGear = ArchiveItemCatalog.FromRecords([
            new ArchiveItemCatalogRecord(1006117, "Item_Skill_AbyssGear_CircusMachine", "Trial by Fire", [], [], [], [], [],
                Category: "Armor", Group: "Hands", EquipType: "Hand", IsDlc: true),
            new ArchiveItemCatalogRecord(1006123, "Item_Skill_AbyssGear_Incarnation", "Ascended Incarnate", [], [], [], [], [],
                Category: "Armor", Group: "Feet", EquipType: "Foot", IsDlc: true),
            new ArchiveItemCatalogRecord(5, "Test_Leather_Gloves", "Gloves", [], [], [], [], [], EquipType: "Hand"),
            new ArchiveItemCatalogRecord(6, "Test_Leather_Boots", "Boots", [], [], [], [], [], EquipType: "Foot"),
        ]);
        if (socketGear.Search("", "Armor", "Hands", 0, 72).Items.Single().ItemId != 5
            || socketGear.Search("", "Armor", "Feet", 0, 72).Items.Single().ItemId != 6
            || socketGear.Search("Trial by Fire", "Progression / Reward", "Skill", 0, 72, onlyDlc: true).Items.Single().ItemId != 1006117
            || socketGear.Search("", "Progression / Reward", "Skill", 1, 1, onlyDlc: true).Items.Single().ItemId != 1006117
            || socketGear.CategoryFacets.Single(facet => facet.Group == "Skill").Count != 2
            || socketGear.Items.Single(item => item.ItemId == 1006117).EquipType != "Hand")
            throw new InvalidOperationException("Socket gear must leave armor filters and keep its source slot as metadata");
        return Task.CompletedTask;
    }
}

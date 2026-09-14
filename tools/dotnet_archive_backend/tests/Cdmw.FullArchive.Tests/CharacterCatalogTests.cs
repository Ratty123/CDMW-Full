using System.Buffers.Binary;
using System.Text;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

internal static class CharacterCatalogTests
{
    private static void Check(bool condition, string message)
    { if (!condition) throw new InvalidOperationException(message); }

    public static async Task CatalogueAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateCurrentItemNamesAsync();
        var inventory = new List<ArchiveEntryDto>();
        var bytes = new Dictionary<long, byte[]>();
        ArchiveEntryDto Add(string path, byte[] payload, string package = "0009")
        {
            var id = inventory.Count;
            var pamt = Path.Combine(fixture.Root, package, "0.pamt");
            var entry = new ArchiveEntryDto("fixture", id, new(path.ToLowerInvariant(), pamt, 0, id), path,
                pamt, Path.ChangeExtension(pamt, ".paz"), 0, id, payload.Length, payload.Length, 0,
                Path.GetExtension(path).ToLowerInvariant(), package, ArchiveEntryRole.Model, "Model", true);
            inventory.Add(entry); bytes[id] = payload;
            return entry;
        }
        ArchiveEntryDto Xml(string path, string text, string package = "0009") => Add(path, Encoding.UTF8.GetBytes(text), package);
        const string body = "character/model/1_pc/1_phm/nude/hero_body_0001.pac";
        const string appearance = "character/appearance/1_pc/1_phm/hero.app_xml";
        var shadowed = Add(body, [1], "0038");
        var active = Add(body.ToUpperInvariant(), [2], "0036");
        var head = Add("character/model/1_pc/1_phm/head/hero_head_0001.pac", [3]);
        var tears = Add("character/model/1_pc/1_phm/head/hero_head_0001_tear.pac", [3]);
        var eyes = Add("character/model/1_pc/1_phm/head/hero_head_0001_eye.pac", [3]);
        Xml("character/appearance/3_npc/tears.app_xml", "<Appearance><Head Name=\"hero_head_0001_tear\"/></Appearance>");
        Xml("character/modelproperty/1_pc/1_phm/head/hero_head_0001.pac_xml", "<Mesh _subMeshName=\"hero_body_neck_01\"/>");
        var orphan = Add("character/model/3_npc/nude/orphan_body_0001.pac", [4]);
        Add("character/model/1_pc/1_phm/armor/hero_ub_0001.pac", [5]);
        Add("character/model/3_npc/a/head/duplicate_head_0001.pac", [6]);
        Add("character/model/3_npc/b/head/duplicate_head_0001.pac", [7]);
        Add("character/model/2_mon/mystery.pac", [8]);
        Xml(appearance, "<Appearance><Nude CharacterScale=\"1.1\"><Prefab Name=\"hero_body_0001\"Preview=\"true\"/></Nude><Head Name=\"hero_head_0001\"/><Customization File=\"hero_custom\"/></Appearance>");
        Xml("character/appearance/3_npc/shared.app_xml", "<Appearance><Nude Name=\"hero_body_0001\"/><Head Name=\"hero_head_0001\"/></Appearance>");
        Xml("character/appearance/3_npc/unresolved.app_xml", "<Appearance><Nude Name=\"missing_body\"/></Appearance>");
        Xml("character/appearance/3_npc/ambiguous.app_xml", "<Appearance><Head Name=\"duplicate_head_0001\"/></Appearance>");
        Xml("character/appearance/2_mon/combined.app_xml", "<Appearance><Nude Name=\"orphan_body_0001\"/><Head Name=\"orphan_body_0001\"/></Appearance>");
        Xml("character/prefab/3_npc/cycle_a.prefabdata_xml", "<Prefab FileName=\"character/prefab/3_npc/cycle_b.prefabdata_xml\"/>");
        Xml("character/prefab/3_npc/cycle_b.prefabdata_xml", "<Prefab FileName=\"character/prefab/3_npc/cycle_a.prefabdata_xml\"/>");
        Add("character/customization/hero_custom.paccd", [9]);
        Xml("character/modelproperty/1_pc/1_phm/nude/hero_body_0001.pac_xml", "<Header/>\n<Material FileName=\"character/texture/hero.dds\"/><Mesh _subMeshName=\"hero_head_01\"/><Mesh _subMeshName=\"hero_nude_01\"/>");
        Add("character/texture/hero.dds", [10]);
        const string creatureRoot = "character/model/2_mon/test_creature/";
        var creature = Add(creatureRoot + "creature_0001.pac", [11]);
        var boots = Add(creatureRoot + "creature_foot_0040.pac", [12]);
        var bag = Add(creatureRoot + "creature_bag_0040.pac", [13]);
        var fur = Add(creatureRoot + "creature_0001_00_spline.pac", [14]);
        Xml("character/modelproperty/2_mon/test_creature/creature_0001.pac_xml",
            "<Mesh _subMeshName=\"creature_body_01\"/>");
        Xml("character/modelproperty/2_mon/test_creature/creature_0001_00_spline.pac_xml",
            "<Mesh _subMeshName=\"creature_hair_01_spline\"/>");
        Xml("character/prefab/2_mon/test_creature/creature_nude_0001.prefabdata_xml",
            "<Prefab>" + string.Join("", new[] { creature, boots, bag, fur }.Select(entry => $"<Mesh FileName=\"{entry.Path}\"/>")) + "</Prefab>");
        const string creatureAppearance = "character/appearance/2_mon/test_creature/creature.app_xml";
        Xml(creatureAppearance, "<Appearance><Nude Name=\"creature_nude_0001\"/></Appearance>");
        Xml("character/bin__/sequenceprefab/01_tool/cd_ani_cd_alchemy_bottle_03.prefab",
            "<Prefab FileName=\"object/products/alchemy/cd_alchemy_bottle_03.pami\"/>");
        var wagon = Add("character/model/4_riding/vehicle/test_wagon_0002_nohorse.pac", [15]);
        var boat = Add("character/model/4_riding/vehicle/test_boat_0001.pac", [16]);
        Xml("character/modelproperty/4_riding/vehicle/test_wagon_0002_nohorse.pac_xml", "<Mesh _subMeshName=\"vehicle_body_01\"/>");
        const string wagonAppearance = "character/appearance/4_riding/vehicle/test_wagon_0002.app_xml";
        Xml(wagonAppearance, "<Appearance><Nude Name=\"test_wagon_0002_nohorse\"/></Appearance>");
        for (var i = 0; i < 80; i++) Add($"character/model/4_riding/nude/mount_body_{i:0000}.pac", [1]);

        const string table = "gamedata/binarystaticinfo__/bin/";
        static byte[] U32(uint n) => BitConverter.GetBytes(n);
        var nameKey = ((1UL << 32) | 0x30).ToString();
        var internalName = Encoding.ASCII.GetBytes("Hero_Internal");
        var name = U32(1).Concat(U32((uint)internalName.Length)).Concat(internalName)
            .Concat(new byte[] { 0, 3, 0x30, 0, 0, 0 }).Concat(U32(1))
            .Concat(U32((uint)nameKey.Length)).Concat(Encoding.ASCII.GetBytes(nameKey)).ToArray();
        Add(table + "characterinfo.staticinfobody", name, "0036");
        Add(table + "characterinfo.staticinfoheader", new byte[] { 1, 0 }.Concat(U32(1)).Concat(U32(0)).ToArray(), "0036");
        var link = new byte[29];
        BinaryPrimitives.WriteUInt32LittleEndian(link, 1);
        // Independent hashlittle vector for the full appearance path, seed 0xC5EDE.
        BinaryPrimitives.WriteUInt32LittleEndian(link.AsSpan(17), 0x85CC7485);
        BinaryPrimitives.WriteUInt32LittleEndian(link.AsSpan(25), 1);
        Add(table + "characterappearanceindexinfo.staticinfobody", link, "0036");
        Add(table + "characterappearanceindexinfo.staticinfoheader", new byte[] { 1, 0 }.Concat(U32(1)).Concat(U32(0)).Concat(U32(0)).ToArray(), "0036");
        byte[] Loc(string value) => U32((uint)nameKey.Length).Concat(Encoding.ASCII.GetBytes(nameKey))
            .Concat(U32((uint)Encoding.UTF8.GetByteCount(value))).Concat(Encoding.UTF8.GetBytes(value)).ToArray();
        Add("gamedata/stringtable/binary__/eng/character.paloc", Loc("Test Hero"), "0036");
        Add("gamedata/stringtable/binary__/ara/character.paloc", Loc("البطل"), "0036");

        CharacterCatalogSnapshot Build(CancellationToken token = default) => ArchiveCharacterCatalogBuilder.Build(
            fixture.Root, "fixture-generation", inventory, entry => bytes[entry.EntryId], token);
        for (var i = 0; i < 80; i++)
        {
            Add($"character/model/1_pc/2_phw/head/head/cd_phw_00_head_00_{i:0000}.pac", [1]);
            Add($"character/model/1_pc/2_phw/armor/cd_phw_00_ub_{i:0000}.pac", [1]);
        }
        Add("character/model/1_pc/2_phw/nude/cd_phw_00_nude_00_0001_damian.pac", [1]);
        Add("character/model/1_pc/2_phw/nude/cd_phw_00_fuzz_00_0001_damian.pac", [1]);
        Xml("character/modelproperty/1_pc/2_phw/nude/cd_phw_00_nude_00_0001_damian.pac_xml", "<Mesh _subMeshName=\"cd_phw_nude\"/><Mesh _subMeshName=\"cd_phw_head\"/>");
        var snapshot = Build();
        var catalogue = new ArchiveCharacterCatalog(snapshot);
        var hairHeads = catalogue.Search(new("fixture", Tab: "all", SelectionPurpose: "hair_head", PageStart: 72));
        Check(hairHeads.TotalMatches == 80 && hairHeads.Rows.Count == 8 && hairHeads.Rows.All(row => row.Role == "head" && row.BodyFamily == "2_phw"),
            "hair reference filtering did not precede pagination");
        var hairBodies = catalogue.Search(new("fixture", Tab: "all", SelectionPurpose: "hair_body"));
        Check(hairBodies.TotalMatches == 1 && hairBodies.Rows.Single().Path.EndsWith("cd_phw_00_nude_00_0001_damian.pac"),
            "body reference selector admitted armor, fuzz or another skeleton family");
        var hero = catalogue.Search(new("fixture", Query: "البطل", View: "appearances", Tab: "all"));
        Check(hero.Rows.Count == 2 && hero.Rows.All(row => row.Label == "Test Hero"), "validated multilingual character name join failed");
        var details = catalogue.GetRequired(hero.Rows.Single(row => row.Role == "body").Key);
        Check(details.Evidence.Any(line => line.Contains("Recovered missing whitespace")), "XML recovery was not reported");
        Check(details.Components.Single(c => c.Role == "body").Scale == 1.1, "authored scale lost");
        Check(details.Row.Resolution == "resolved", "multi-root model-property fragment was rejected");
        Check(details.RelatedIds.Any(id => inventory[(int)id].Extension == ".paccd"), "customization context lost");
        Check(details.Components.SelectMany(c => c.ModelEntryIds).Contains(active.EntryId)
            && !details.Components.SelectMany(c => c.ModelEntryIds).Contains(shadowed.EntryId), "mount precedence/case identity failed");
        var physical = catalogue.GetRequired("asset:" + body);
        Check(physical.Row.UsageCount >= 2 && physical.Characters.Single().CharacterId == 1, "shared model ownership failed");
        Check(physical.Row.EmbeddedFace && details.Row.EmbeddedFace, "declared embedded head submesh was lost");
        Check(!catalogue.GetRequired(hero.Rows.Single(row => row.Role == "head").Key).Row.EmbeddedFace, "separate head was mislabeled as embedded");
        Check(catalogue.GetRequired("asset:" + head.Path).Row.Role == "head", "a neck submesh relabeled an explicit head as a body");
        Check(physical.RelatedIds.Any(id => inventory[(int)id].Path == appearance), "asset related-file scope lost appearance");
        Check(catalogue.Search(new("fixture", Query: "duplicate", View: "appearances", Tab: "faces")).Rows.Single().Resolution == "ambiguous", "duplicate basenames were arbitrarily resolved");
        Check(catalogue.Search(new("fixture", Query: "missing", View: "appearances")).Rows.Single().PreviewStatus == "unresolved_model", "unresolved reference disappeared");
        Check(catalogue.GetRequired("asset:" + orphan.Path).Row.EmbeddedFace, "combined body/head was not retained");
        var first = catalogue.Search(new("fixture", SourceGroup: "4_riding"));
        var next = catalogue.Search(new("fixture", SourceGroup: "4_riding", PageStart: 72));
        Check(first.TotalMatches == 80 && first.Rows.Count == 72 && next.Rows.Count == 8
            && !first.Rows.Select(r => r.Key).Intersect(next.Rows.Select(r => r.Key)).Any(), "paging/filter counts failed");
        Check(snapshot.Coverage.Any(r => r.Path == body && r.Resolution == "excluded"), "overlay candidate was not accounted for");
        Check(snapshot.Coverage.Count(r => r.Key.StartsWith("coverage:")) == inventory.Count(e => e.Path.StartsWith("character/", StringComparison.OrdinalIgnoreCase)
            && e.Extension is ".pac" or ".app_xml" or ".prefab" or ".prefabdata_xml"), "physical candidate coverage is incomplete");
        Check(catalogue.Search(new("fixture", Role: "unclassified")).Rows.Any(), "unclassified candidates are inaccessible");
        var defaultBodies = catalogue.Search(new("fixture"));
        Check(defaultBodies.Rows.All(row => row.Role != "unclassified"), "default body browsing includes unclassified candidates");
        Check(defaultBodies.Facets.Any(facet => facet.Field == "role" && facet.Value == "unclassified"), "unclassified filter disappeared");
        var assets = snapshot.Records.Where(record => record.Row.View == "assets").ToArray();
        Check(assets.All(record => record.Row.ModelCount == 1 && Path.GetExtension(record.Row.Path).ToLowerInvariant() is ".pac" or ".pam" or ".pamlod"),
            "reference-only descriptors were advertised as unique model assets");
        Check(!assets.Any(record => record.Row.Path == boots.Path || record.Row.Path == bag.Path),
            "appearance membership relabeled equipment as body assets");
        Check(!assets.Any(record => record.Row.Path == wagon.Path || record.Row.Path == boat.Path),
            "vehicle models were advertised as character bodies");
        Check(!snapshot.Records.Any(record => record.Row.Path == wagonAppearance)
            && snapshot.Coverage.Any(row => row.Path == wagonAppearance && row.Resolution == "excluded"),
            "vehicle-only appearance was advertised as a body or lost from coverage");
        Check(catalogue.GetRequired("asset:" + fur.Path).Row.Role == "hair", "spline fur submesh was labeled as a body");
        Check(catalogue.GetRequired("asset:" + creature.Path).Row.Role is "body" or "whole_character", "actual creature body was lost");
        foreach (var view in new[] { "assets", "appearances" })
        {
            var faces = catalogue.Search(new("fixture", View: view, Tab: "faces"));
            Check(faces.Rows.Count > 0 && faces.Rows.All(row => row.Role == "head" && !row.EmbeddedFace),
                $"{view}: default Faces includes a whole body, embedded head or secondary component");
            Check(!faces.Rows.Any(row => row.InternalName.Contains("_tear") || row.InternalName.EndsWith("_eye.pac")),
                $"{view}: a terminal facial-detail token was classified as a head");
            var humanoids = catalogue.Search(new("fixture", View: view, SourceGroup: "humanoid"));
            Check(humanoids.Rows.Count > 0 && humanoids.Rows.All(row => row.SourceGroup is "1_pc" or "3_npc"),
                $"{view}: humanoid filter includes creatures or mounts");
            Check(humanoids.Facets.Any(facet => facet.Field == "source_group" && facet.Value == "2_mon")
                && humanoids.Facets.Any(facet => facet.Field == "source_group" && facet.Value == "humanoid" && facet.Count > 0),
                $"{view}: type filters lost humanoid counts or access to creatures");
            Check(catalogue.Search(new("fixture", View: view, SourceGroup: "2_mon")).Rows.Count > 0,
                $"{view}: explicit creature browsing became inaccessible");
        }
        Check(catalogue.Search(new("fixture", Tab: "faces", Role: "hair")).Rows.Any(row => row.Path == fur.Path),
            "explicit hair filter lost the secondary component");
        var facialDetails = catalogue.Search(new("fixture", Tab: "faces", Role: "facial_detail"));
        Check(facialDetails.Rows.Any(row => row.Path == tears.Path) && facialDetails.Rows.Any(row => row.Path == eyes.Path),
            "tear/eye meshes disappeared instead of remaining available as facial details");
        var creatureDetail = catalogue.GetRequired("appearance:" + creatureAppearance + "#body");
        Check(creatureDetail.Components.SelectMany(component => component.ModelEntryIds).Contains(boots.EntryId)
            && creatureDetail.RelatedIds.Contains(bag.EntryId), "appearance assembly lost its equipment dependencies");
        Check(snapshot.Coverage.Any(row => row.Path.EndsWith("cd_ani_cd_alchemy_bottle_03.prefab")), "excluded descriptor disappeared from coverage");
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        try { Build(cancelled.Token); throw new InvalidOperationException("cancelled build published"); }
        catch (OperationCanceledException) { }
        BinaryPrimitives.WriteUInt32LittleEndian(link.AsSpan(17), 0xDEADBEEF);
        var missingLink = new ArchiveCharacterCatalog(Build()).Search(new("fixture", Query: "البطل", View: "appearances", Tab: "all"));
        Check(missingLink.Rows.Single().Key == "appearance-link:1/0" && missingLink.Rows.Single().Resolution == "unresolved",
            "unresolved character ownership disappeared instead of remaining searchable");
        // A highest-priority incomplete table pair cannot borrow a lower source's header.
        Add(table + "characterinfo.staticinfobody", name, "0036");
        inventory[^1] = inventory[^1] with { SourcePamt = Path.Combine(fixture.Root, "0036", "1.pamt") };
        var incomplete = Build();
        Check(incomplete.Warnings.Any(w => w.Contains("Incomplete characterinfo")), "incomplete source pair was silently mixed");
    }

    public static async Task CacheAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAssociatedAssetsAsync();
        var native = new NativeArchiveCore();
        using var sessions = new ArchiveSessionManager(native, new ArchiveCacheStore(fixture.OutputRoot));
        var session = await sessions.OpenAsync(new(fixture.Root), CancellationToken.None);
        var service = new ArchiveCharacterCatalogService(sessions, native);
        using var cancel = new CancellationTokenSource();
        try
        {
            await service.BuildAsync(new(session.SessionId), update => {
                if (update.CurrentItem == "Character catalogue ready") cancel.Cancel();
                return Task.CompletedTask;
            }, cancel.Token);
            throw new InvalidOperationException("publication cancellation was ignored");
        }
        catch (OperationCanceledException) { }
        Check(!Directory.EnumerateFiles(sessions.GetRequired(session.SessionId).GenerationPath, "character-catalog*").Any(), "cancelled catalogue cache leaked");
        var cold = await service.BuildAsync(new(session.SessionId), null, CancellationToken.None);
        var warm = await service.BuildAsync(new(session.SessionId), null, CancellationToken.None);
        Check(!cold.UsedCache && warm.UsedCache && warm.CandidateCount == cold.CandidateCount, "warm catalogue cache was not reused");
        var refreshed = await sessions.RefreshAsync(new(fixture.Root), CancellationToken.None);
        var fresh = await service.BuildAsync(new(refreshed.SessionId), null, CancellationToken.None);
        Check(!fresh.UsedCache, "refresh reused stale catalogue generation");
    }
}

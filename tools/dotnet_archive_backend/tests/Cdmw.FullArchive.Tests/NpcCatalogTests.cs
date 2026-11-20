using System.Buffers.Binary;
using System.Text;
using Cdmw.FullArchive.Contracts;
using Cdmw.FullArchive.Core;

namespace Cdmw.FullArchive.Tests;

internal static class NpcCatalogTests
{
    private static void Check(bool condition, string message)
    { if (!condition) throw new InvalidOperationException(message); }

    private static byte[] U32(uint value) => BitConverter.GetBytes(value);
    private static byte[] Str(string value) => U32((uint)value.Length).Concat(Encoding.ASCII.GetBytes(value)).ToArray();
    private static readonly byte[] Unset = Enumerable.Repeat((byte)0xFF, 8).ToArray();

    // Same layout as the installed game's character .prefab files: a reflected type
    // header, then per model: label, flags, path, a u32 whose low byte is printable,
    // more fields, and the label again.
    internal static byte[] Prefab(params (string? Label, string Path)[] models)
    {
        var output = new List<byte> { 0xFF, 0xFF };
        output.AddRange(U32(4));
        output.AddRange(Str("SceneObject"));
        output.AddRange(Str("_attachedSocketName"));
        output.AddRange(Str("IndexedStringA"));
        output.AddRange(new byte[160]);
        foreach (var (label, path) in models)
        {
            if (label is not null) output.AddRange(Str(label));
            output.AddRange(new byte[] { 1, 1, 0, 1, 3, 0, 0 });
            output.AddRange(Unset);
            output.AddRange(U32(0x6FA));
            output.AddRange(U32(0));
            output.AddRange(Str(path));
            output.AddRange(U32(0x55)); // "U": printable, as on the installed game
            output.AddRange(new byte[] { 1, 1, 0, 0, 2, 0, 0 });
            output.AddRange(Unset);
            output.AddRange(U32(0x766));
            output.AddRange(U32(0));
            output.AddRange(U32(4));
            output.AddRange(new byte[] { 0xCD, 0xCC, 0xCC, 0x3D });
            if (label is not null) output.AddRange(Str(label));
            output.AddRange(new byte[] { 0xAB, 0, 0, 0 });
        }
        output.Add(1);
        return output.ToArray();
    }

    public static Task PrefabModelsAsync()
    {
        var two = ArchivePrefabModels.Read(Prefab(
            ("Upperbody", "character/model/3_npc/1_nhm/armor_south/9_upperbody/cd_nhm_00_so_ub_10335.pac"),
            ("Cloak", "character/model/1_pc/1_phm/armor/19_cloak/cd_phm_00_cloak_00_0446.pac")));
        Check(two.Length == 2 && two[0].Slot == "Upperbody" && two[1].Slot == "Cloak"
            && two[0].ModelPath.EndsWith("cd_nhm_00_so_ub_10335.pac") && two[1].ModelPath.EndsWith("cd_phm_00_cloak_00_0446.pac"),
            "prefab labels or paths were not read; a printable byte after a path must not join it");
        var unlabelled = ArchivePrefabModels.Read(Prefab((null, "character/model/1_pc/1_phm/armor/12_foot/cd_phm_00_foot_0054_01.pac")));
        Check(unlabelled.Single().Slot == "Foot", "folder fallback did not name the slot");
        var unknown = ArchivePrefabModels.Read(Prefab((null, "character/model/2_mon/thing/thing_0001.pac")));
        Check(unknown.Single().Slot == "Unknown", "a slot was guessed without a label or folder");
        var twelve = ArchivePrefabModels.Read(Prefab(Enumerable.Range(0, 12)
            .Select(index => ((string?)(index % 2 == 0 ? "Helm" : "Upperbody_Acc"), $"character/model/2_mon/orc/cd_orc_acc_{index:0000}.pac")).ToArray()));
        Check(twelve.Length == 12 && twelve.Select(model => model.Slot).Distinct().Count() == 2
            && twelve[11].Slot == "Upperbody_Acc", "a twelve-model prefab lost models or labels");
        Check(ArchivePrefabModels.Read(Prefab()).Length == 0, "an empty prefab invented a model");
        return Task.CompletedTask;
    }

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
        ArchiveEntryDto Xml(string path, string text) => Add(path, Encoding.UTF8.GetBytes(text));
        const string upper = "character/model/3_npc/1_nhm/armor_south/9_upperbody/cd_nhm_00_so_ub_10335.pac";
        const string cloak = "character/model/1_pc/1_phm/armor/19_cloak/cd_phm_00_cloak_00_0446.pac";
        const string foot = "character/model/1_pc/1_phm/armor/12_foot/cd_phm_00_foot_0054_01.pac";
        var upperEntry = Add(upper, [1]);
        var cloakEntry = Add(cloak, [2]);
        var footEntry = Add(foot, [3]);
        var body = Add("character/model/1_pc/1_phm/nude/hero_body_0001.pac", [4]);
        var head = Add("character/model/1_pc/1_phm/head/hero_head_0001.pac", [5]);
        var hair = Add("character/model/1_pc/1_phm/hair/hero_hair_0001.pac", [6]);
        var upperPrefab = Add("character/bin__/prefab/3_npc/01_nhm/south_armor/cd_nhm_so_ub_10335.prefab",
            Prefab(("Upperbody", upper), ("Cloak", cloak)));
        Add("character/bin__/prefab/1_pc/01_phm/armor/12_foot/cd_phm_00_foot_0054_01_index09.prefab", Prefab((null, foot)));
        Add("character/bin__/prefab/4_riding/tack/horse_tack_part_hide.prefab", Prefab());
        const string appearance = "character/appearance/3_npc/cd_npc_south/cd_nhm_south/hero.app_xml";
        const string alternate = "character/appearance/3_npc/cd_npc_south/cd_nhm_south/hero_alt.app_xml";
        const string orphan = "character/appearance/2_mon/orphan.app_xml";
        var appearanceEntry = Xml(appearance, "﻿<Appearance><Customization CustomizationFile=\"none\"/>"
            + "<Nude><Prefab Name=\"hero_body_0001\"/></Nude><Head><Prefab Name=\"hero_head_0001\"/></Head>"
            + "<Hair><Prefab Name=\"hero_hair_0001\"/></Hair>"
            + "<Armor><Prefab Name=\"cd_nhm_so_ub_10335\" Preview=\"1\"/><Prefab Name=\"cd_nhm_so_ub_51220\"/>"
            + "<Prefab Name=\"horse_tack_part_hide\"/></Armor><AudioInfo Name=\"ignored\"/></Appearance>");
        Xml(alternate, "<Appearance><Armor><Prefab Name=\"cd_phm_00_foot_0054_01_index09\"/></Armor></Appearance>");
        Xml(orphan, "<Appearance><Armor><Prefab Name=\"cd_nhm_so_ub_10335\"/></Armor></Appearance>");
        Xml("character/appearance/3_npc/broken.app_xml", "<Appearance><Armor>");

        const string table = "gamedata/binarystaticinfo__/bin/";
        static string Key(uint id) => (((ulong)id << 32) | 0x30).ToString();
        byte[] CharacterRow(uint id, string internalName) => U32(id).Concat(Str(internalName))
            .Concat(new byte[] { 0, 3, 0x30, 0, 0, 0 }).Concat(U32(1)).Concat(Str(Key(id))).ToArray();
        var characters = new[] { (1u, "Hero_Internal"), (2u, "Guard_Internal"), (3u, "Ghost_Internal") };
        var characterBody = new List<byte>();
        var characterHeader = new List<byte>(new byte[] { (byte)characters.Length, 0 });
        foreach (var (id, internalName) in characters)
        {
            characterHeader.AddRange(U32(id)); characterHeader.AddRange(U32((uint)characterBody.Count));
            characterBody.AddRange(CharacterRow(id, internalName));
        }
        Add(table + "characterinfo.staticinfobody", characterBody.ToArray(), "0036");
        Add(table + "characterinfo.staticinfoheader", characterHeader.ToArray(), "0036");
        var links = new[] { (1u, 0, appearance), (1u, 1, alternate), (2u, 0, appearance), (3u, 0, "character/appearance/3_npc/not_installed.app_xml") };
        var linkBody = new List<byte>();
        var linkHeader = new List<byte>(new byte[] { (byte)links.Length, 0 });
        foreach (var (id, variant, path) in links)
        {
            linkHeader.AddRange(U32(id)); linkHeader.AddRange(U32((uint)variant)); linkHeader.AddRange(U32((uint)linkBody.Count));
            var record = new byte[29];
            BinaryPrimitives.WriteUInt32LittleEndian(record, id);
            BinaryPrimitives.WriteInt32LittleEndian(record.AsSpan(4), variant);
            BinaryPrimitives.WriteUInt32LittleEndian(record.AsSpan(17), ArchiveNameIndexBuilder.ModelNameHash(path));
            BinaryPrimitives.WriteUInt32LittleEndian(record.AsSpan(25), id);
            linkBody.AddRange(record);
        }
        Add(table + "characterappearanceindexinfo.staticinfobody", linkBody.ToArray(), "0036");
        Add(table + "characterappearanceindexinfo.staticinfoheader", linkHeader.ToArray(), "0036");
        byte[] Loc(params (uint Id, string Value)[] rows) => rows.SelectMany(row => Str(Key(row.Id))
            .Concat(U32((uint)Encoding.UTF8.GetByteCount(row.Value))).Concat(Encoding.UTF8.GetBytes(row.Value))).ToArray();
        Add("gamedata/stringtable/binary__/eng/character.paloc", Loc((1, "Hero"), (2, "Hero Guard"), (3, "Ghost")), "0036");
        Add("gamedata/stringtable/binary__/ara/character.paloc", Loc((1, "البطل")), "0036");

        NpcCatalogSnapshot Build(CancellationToken token = default) => ArchiveNpcCatalogBuilder.Build(
            fixture.Root, "fixture-generation", inventory, entry => bytes[entry.EntryId], token);
        var snapshot = Build();
        var catalog = new ArchiveNpcCatalog(snapshot);
        var stats = snapshot.Statistics;
        Check(stats.AppearanceCount == 4 && stats.UnparsedAppearanceCount == 1 && stats.ArmorAppearanceCount == 3 && stats.ArmorEntryCount == 5,
            $"appearance counts are wrong: {stats}");
        Check(stats.DistinctPrefabCount == 4 && stats.ResolvedPrefabCount == 3 && stats.MissingPrefabCount == 1 && stats.EmptyPrefabCount == 1,
            $"prefab counts are wrong: {stats}");
        Check(stats.ModelPathCount == 3 && stats.UnresolvedLinkCount == 1, $"model or link counts are wrong: {stats}");

        var hero = catalog.GetRequired("npc:1");
        Check(hero.Row.DisplayName == "Hero" && hero.Row.InternalName == "Hero_Internal" && hero.Row.Kind == "npc"
            && hero.Row.VariantCount == 2 && hero.Row.HasArmor, "character row lost its name, kind or variants");
        Check(hero.Outfits[0].Variant == 0 && hero.Outfits[0].AppearancePath == appearance && hero.Outfits[1].Variant == 1,
            "variants were not ordered by the game's variant number");
        var pieces = hero.Outfits[0].Pieces;
        Check(pieces.TakeWhile(piece => piece.Section == "armor").Count() == 4 && pieces[0].Slot == "Upperbody"
            && pieces[0].ModelEntryId == upperEntry.EntryId && pieces[0].PrefabEntryId == upperPrefab.EntryId
            && pieces[0].Preview == "1" && pieces[1].Slot == "Cloak" && pieces[1].ModelEntryId == cloakEntry.EntryId,
            "armour pieces lost their slot, model, prefab or Preview value, or are not listed first");
        Check(pieces.Any(piece => piece.PrefabName == "cd_nhm_so_ub_51220" && piece.Resolution == "missing_prefab" && piece.ModelEntryId < 0),
            "a prefab with no file was dropped instead of shown as unresolved");
        Check(pieces.Any(piece => piece.PrefabName == "horse_tack_part_hide" && piece.Resolution == "no_model"),
            "a prefab that lists no model was dropped");
        Check(pieces.Single(piece => piece.Section == "body").ModelEntryId == body.EntryId
            && pieces.Single(piece => piece.Section == "head").ModelEntryId == head.EntryId
            && pieces.Single(piece => piece.Section == "hair").ModelEntryId == hair.EntryId,
            "body, head or hair pieces are missing");
        Check(!pieces.Any(piece => piece.PrefabName == "ignored"), "AudioInfo was read as a worn piece");
        Check(hero.Row.PieceCount == 5, $"piece count counts unresolved rows: {hero.Row.PieceCount}");
        Check(hero.Outfits[1].Pieces.Single().Slot == "Foot" && hero.Outfits[1].Pieces.Single().ModelEntryId == footEntry.EntryId,
            "an unlabelled model lost its folder slot");
        Check(hero.Outfits[0].AppearanceEntryId == appearanceEntry.EntryId, "appearance entry ID lost");

        var ghost = catalog.GetRequired("npc:3");
        Check(ghost.Row.Resolution == "unresolved" && ghost.Outfits.Single().AppearancePath == ""
            && ghost.Outfits.Single().Evidence.Single().Contains("no unique installed match"),
            "a link whose hash matches no file was not kept as an unresolved row");
        var orphanRow = catalog.GetRequired("appearance:" + orphan);
        Check(orphanRow.Row.CharacterId == 0 && orphanRow.Row.Kind == "creature" && orphanRow.Row.InternalName == "orphan",
            "an appearance with no owner has no row");
        Check(catalog.GetRequired("appearance:character/appearance/3_npc/broken.app_xml").Row.Resolution == "unresolved",
            "an unreadable appearance was not reported");

        // Search ranking.
        var byId = catalog.Search(new("fixture", Query: "1"));
        Check(byId.TotalMatches == 1 && byId.Rows.Single().Key == "npc:1", "digits did not match the character ID exactly");
        var byName = catalog.Search(new("fixture", Query: "Hero"));
        Check(byName.Rows[0].Key == "npc:1" && byName.Rows[1].Key == "npc:2", "exact English name did not rank first");
        Check(catalog.Search(new("fixture", Query: "البطل")).Rows.Single().Key == "npc:1", "other-language names are not searchable");
        Check(catalog.Search(new("fixture", Query: "guard_internal")).Rows.Single().Key == "npc:2", "internal names are not searchable");
        var byPiece = catalog.Search(new("fixture", Query: "cd_phm_00_cloak_00_0446.pac"));
        Check(byPiece.Rows.Select(row => row.Key).Order().SequenceEqual(new[] { "appearance:" + orphan, "npc:1", "npc:2" }),
            "searching a piece did not return its wearers");
        Check(catalog.Search(new("fixture", Kind: "creature")).Rows.Single().Key == "appearance:" + orphan, "kind filter failed");
        Check(catalog.Search(new("fixture", HasArmor: true)).Rows.All(row => row.HasArmor), "armour filter failed");
        Check(catalog.Search(new("fixture", PageSize: 1000)).PageSize == ArchiveNpcCatalog.MaximumPageSize, "page size is not capped");

        var wearers = catalog.Wearers("fixture", cloak, 200);
        Check(wearers.TotalCount == 3 && wearers.Wearers.All(wearer => wearer.Slot == "Cloak"), "Worn by on the cloak is wrong");
        Check(catalog.Wearers("fixture", "cd_phm_00_cloak_00_0446.pac", 200).TotalCount == 3, "a bare model file name found no wearers");
        Check(catalog.Wearers("fixture", "cd_nhm_so_ub_10335", 1).Truncated, "prefab wearers were not capped");

        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        try { Build(cancelled.Token); throw new InvalidOperationException("cancelled NPC build published"); }
        catch (OperationCanceledException) { }
    }

    public static async Task CacheAsync()
    {
        await using var fixture = await SyntheticArchiveFixture.CreateAssociatedAssetsAsync();
        var native = new NativeArchiveCore();
        using var sessions = new ArchiveSessionManager(native, new ArchiveCacheStore(fixture.OutputRoot));
        var session = await sessions.OpenAsync(new(fixture.Root), CancellationToken.None);
        var service = new ArchiveNpcCatalogService(sessions, native);
        using var cancel = new CancellationTokenSource();
        try
        {
            await service.BuildAsync(new(session.SessionId), update => {
                if (update.CurrentItem == "NPC catalogue ready") cancel.Cancel();
                return Task.CompletedTask;
            }, cancel.Token);
            throw new InvalidOperationException("NPC publication cancellation was ignored");
        }
        catch (OperationCanceledException) { }
        var generation = sessions.GetRequired(session.SessionId).GenerationPath;
        Check(!Directory.EnumerateFiles(generation, "npc-catalog*").Any(), "cancelled NPC cache leaked");
        var cold = await service.BuildAsync(new(session.SessionId), null, CancellationToken.None);
        Check(!cold.UsedCache && File.Exists(Path.Combine(generation, $"npc-catalog-v{ArchiveNpcCatalogBuilder.Version}.json")),
            "NPC catalogue cache was not written");
        var warm = await service.BuildAsync(new(session.SessionId), null, CancellationToken.None);
        Check(warm.UsedCache && warm.NpcCount == cold.NpcCount, "published NPC catalogue was not reused");
        var refreshed = await sessions.RefreshAsync(new(fixture.Root), CancellationToken.None);
        var reread = await service.BuildAsync(new(refreshed.SessionId), null, CancellationToken.None);
        Check(reread.Statistics.AppearanceCount == cold.Statistics.AppearanceCount, "a refreshed session lost the NPC catalogue");
        var search = await service.SearchAsync(new(refreshed.SessionId, Query: ""), null, CancellationToken.None);
        Check(search.SessionId == refreshed.SessionId, "search answered for another session");
        try { await service.OutfitAsync(new(refreshed.SessionId, "npc:999999"), null, CancellationToken.None); throw new InvalidOperationException("unknown key answered"); }
        catch (KeyNotFoundException) { }
    }
}

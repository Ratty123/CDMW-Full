using System.Xml;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

// NPC Finder catalogue: character -> appearance file -> body, head, hair and armour
// pieces. Armour follows <Armor><Prefab Name=".."/> to the binary .prefab and the
// models it lists. Reads the same inputs as the character catalogue and leaves it alone.
public static class ArchiveNpcCatalogBuilder
{
    public const int Version = 1;
    private static readonly HashSet<string> Extensions = new(StringComparer.OrdinalIgnoreCase) {
        ".pac", ".pam", ".pamlod", ".app_xml", ".prefab", ".prefabdata_xml", ".pac_xml", ".pam_xml", ".pamlod_xml", ".pami", ".xml" };

    /// <summary>The file types <see cref="Build"/> keeps from its inventory.</summary>
    internal static IReadOnlyCollection<string> InventoryExtensions => Extensions;

    public static NpcCatalogSnapshot Build(
        string packageRoot, string signature, IEnumerable<ArchiveEntryDto> inventory,
        Func<ArchiveEntryDto, byte[]> read, CancellationToken token,
        Action<int, int, string>? progress = null)
    {
        var sources = new ArchiveItemSources(packageRoot);
        var entries = new Dictionary<string, ArchiveEntryDto>(StringComparer.OrdinalIgnoreCase);
        var seen = 0;
        foreach (var entry in inventory)
        {
            if ((seen++ & 0x1FFF) == 0) { token.ThrowIfCancellationRequested(); progress?.Invoke(seen, 0, "Reading character archive inventory"); }
            sources.Offer(entry);
            if (!entry.Path.StartsWith("character/", StringComparison.OrdinalIgnoreCase) || !Extensions.Contains(entry.Extension)) continue;
            if (!sources.Accepts(entry)) continue;
            var path = ArchiveCharacterReferences.Normalize(entry.Path);
            if (!entries.TryGetValue(path, out var previous) || sources.Order(entry).CompareTo(sources.Order(previous)) > 0)
                entries[path] = entry;
        }
        byte[] Decode(ArchiveEntryDto entry)
        {
            token.ThrowIfCancellationRequested();
            if (entry.OriginalSize > 128 * 1024 * 1024 || entry.StoredSize > 128 * 1024 * 1024)
                throw new InvalidDataException($"Character metadata exceeds 128 MiB: {entry.Path}");
            var bytes = read(entry);
            token.ThrowIfCancellationRequested();
            return bytes;
        }
        var warnings = new List<string>();
        var apps = entries.Values.Where(static entry => entry.Extension.Equals(".app_xml", StringComparison.OrdinalIgnoreCase))
            .OrderBy(static entry => entry.Path, StringComparer.OrdinalIgnoreCase).ToArray();
        var unresolvedLinks = new List<CharacterUnresolvedNameLink>();
        var names = ArchiveCharacterNames.Read(sources, apps, Decode, warnings, unresolvedLinks, token);
        var resolver = new ArchiveCharacterReferences(entries, Decode, token);
        var prefabs = new ArchiveNpcPrefabResolver(entries, Decode);

        var unparsed = 0;
        var armorApps = 0;
        var armorEntries = 0;
        var outfits = new Dictionary<string, NpcOutfit>(StringComparer.Ordinal);
        for (var index = 0; index < apps.Length; index++)
        {
            token.ThrowIfCancellationRequested();
            if ((index & 0x3F) == 0) progress?.Invoke(index, apps.Length, "Reading appearance files");
            var app = apps[index];
            var evidence = new List<string>();
            var pieces = new List<NpcPiece>();
            var resolution = "resolved";
            try
            {
                var text = TextDecoding.Decode(Decode(app));
                var gear = ArchiveCharacterReferences.GearNodes(text, evidence);
                var armor = gear.Where(static node => node.Section == "armor").ToArray();
                if (armor.Length > 0) armorApps++;
                armorEntries += armor.Length;
                foreach (var node in gear)
                    pieces.AddRange(prefabs.Pieces(node.Section, node.Name, node.Preview));
                foreach (var node in ArchiveCharacterReferences.AppearanceNodes(text, evidence, out _))
                {
                    var resolved = resolver.Resolve(node.Name, node.Role);
                    var section = node.Role is "body" or "head" or "hair" ? node.Role : node.Role is "beard" ? "hair" : "head";
                    if (resolved.Models.Length == 0)
                    {
                        pieces.Add(new(section, node.Role, node.Name, -1, "", -1, "", "", "unresolved", []));
                        continue;
                    }
                    foreach (var model in resolved.Models)
                    {
                        var entry = prefabs.ById(model);
                        if (entry is null) continue;
                        pieces.Add(new(section, node.Role, node.Name, -1, "", entry.EntryId, entry.Path, "", resolved.Resolution, []));
                    }
                }
            }
            catch (Exception error) when (error is IOException or XmlException or InvalidDataException or ArgumentException)
            {
                unparsed++;
                resolution = "unresolved";
                evidence.Add($"Appearance could not be read: {error.Message}");
            }
            if (resolution == "resolved" && pieces.Any(static piece => piece.Resolution != "resolved")) resolution = "partial";
            if (pieces.Count == 0 && resolution == "resolved") resolution = "empty";
            outfits[ArchiveCharacterReferences.Normalize(app.Path)] = new(-1, app.Path, app.EntryId, resolution,
                Order(pieces), evidence.Distinct().ToArray());
        }

        // One row per character ID, with every appearance it links to as a variant.
        var characters = new Dictionary<uint, (CharacterNameLink Link, List<(int Variant, string Path)> Variants)>();
        foreach (var (path, links) in names)
        foreach (var link in links)
        {
            if (!characters.TryGetValue(link.Owner.CharacterId, out var value))
                characters[link.Owner.CharacterId] = value = (link, []);
            value.Variants.Add((link.Variant, ArchiveCharacterReferences.Normalize(path)));
        }
        var searchById = names.Values.SelectMany(static links => links)
            .GroupBy(static link => link.Owner.CharacterId)
            .ToDictionary(static group => group.Key, static group => group.SelectMany(static link => link.SearchNames).ToArray());
        var missing = unresolvedLinks.GroupBy(static link => link.Link.Owner.CharacterId).ToDictionary(static group => group.Key, static group => group.ToArray());
        foreach (var (id, links) in missing)
            if (!characters.ContainsKey(id)) characters[id] = (links[0].Link, []);

        var records = new List<NpcCatalogRecord>();
        var owned = new HashSet<string>(StringComparer.Ordinal);
        foreach (var (id, (link, variants)) in characters.OrderBy(static pair => pair.Key))
        {
            token.ThrowIfCancellationRequested();
            var list = variants.OrderBy(static variant => variant.Variant < 0 ? int.MaxValue : variant.Variant)
                .ThenBy(static variant => variant.Path, StringComparer.Ordinal)
                .Where(variant => outfits.ContainsKey(variant.Path))
                .Select(variant => { owned.Add(variant.Path); return outfits[variant.Path] with { Variant = variant.Variant }; })
                .DistinctBy(static outfit => outfit.AppearancePath).ToList();
            foreach (var gap in missing.GetValueOrDefault(id) ?? [])
                list.Add(new(gap.Variant, "", -1, "unresolved", [], [gap.Link.Owner.Evidence]));
            var owner = link.Owner;
            var primary = list.FirstOrDefault(static outfit => outfit.AppearanceEntryId >= 0);
            var path = primary?.AppearancePath ?? "";
            var row = new NpcCatalogRow("npc:" + id.ToString(System.Globalization.CultureInfo.InvariantCulture), id,
                owner.DisplayName, owner.InternalName, Kind(path), ArchiveCharacterReferences.SourceGroup(path),
                list.Count, primary is null ? 0 : PieceCount(primary), RowResolution(list), path,
                list.Any(static outfit => outfit.Pieces.Any(static piece => piece.Section == "armor")));
            var searchNames = searchById.GetValueOrDefault(id) ?? [];
            records.Add(new(row, searchNames.Concat(link.SearchNames).Distinct(StringComparer.OrdinalIgnoreCase).ToArray(), [], list.ToArray()));
        }
        // Appearance files that no character links to still get a row, so nothing is unreachable.
        foreach (var (path, outfit) in outfits.OrderBy(static pair => pair.Key, StringComparer.Ordinal))
        {
            if (owned.Contains(path)) continue;
            var name = Path.GetFileNameWithoutExtension(outfit.AppearancePath);
            var row = new NpcCatalogRow("appearance:" + path, 0, "", name, Kind(path), ArchiveCharacterReferences.SourceGroup(path),
                1, PieceCount(outfit), outfit.Resolution, outfit.AppearancePath,
                outfit.Pieces.Any(static piece => piece.Section == "armor"));
            records.Add(new(row, [name], [], [outfit]));
        }
        var statistics = new NpcCatalogStatistics(apps.Length, unparsed, armorApps, armorEntries,
            prefabs.DistinctCount, prefabs.ResolvedCount, prefabs.MissingCount, prefabs.EmptyCount, prefabs.ModelPathCount,
            unresolvedLinks.Count);
        progress?.Invoke(apps.Length, apps.Length, "NPC catalogue ready");
        return new(Version, signature, records.ToArray(), statistics, warnings.Distinct().ToArray());
    }

    internal static string Kind(string path) => ArchiveCharacterReferences.SourceGroup(path) switch
    {
        "1_pc" => "player",
        "2_mon" => "creature",
        "3_npc" => "npc",
        "4_riding" => "mount",
        _ => "other",
    };

    private static int PieceCount(NpcOutfit outfit) => outfit.Pieces.Count(static piece => piece.ModelEntryId >= 0);

    private static string RowResolution(IReadOnlyCollection<NpcOutfit> outfits)
    {
        if (outfits.Count == 0 || outfits.All(static outfit => outfit.Resolution == "unresolved")) return "unresolved";
        return outfits.All(static outfit => outfit.Resolution is "resolved" or "empty") ? "resolved" : "partial";
    }

    private static readonly string[] SectionOrder = ["armor", "body", "head", "hair"];

    private static NpcPiece[] Order(List<NpcPiece> pieces) => pieces
        .Select(static (piece, index) => (piece, index))
        .OrderBy(static pair => Array.IndexOf(SectionOrder, pair.piece.Section) is var rank and >= 0 ? rank : SectionOrder.Length)
        .ThenBy(static pair => pair.index)
        .Select(static pair => pair.piece)
        .DistinctBy(static piece => (piece.Section, piece.PrefabName, piece.ModelEntryId, piece.ModelPath))
        .ToArray();
}

// Resolves an armour prefab name to its .prefab file and the models it lists.
// Results are cached per prefab: about 5,000 prefabs serve 13,000 armour entries.
internal sealed class ArchiveNpcPrefabResolver(
    IReadOnlyDictionary<string, ArchiveEntryDto> entries, Func<ArchiveEntryDto, byte[]> decode)
{
    private readonly Dictionary<string, ArchiveEntryDto[]> _prefabs = entries.Values
        .Where(static entry => entry.Extension.Equals(".prefab", StringComparison.OrdinalIgnoreCase))
        .GroupBy(static entry => Path.GetFileNameWithoutExtension(entry.Name), StringComparer.OrdinalIgnoreCase)
        .ToDictionary(static group => group.Key, static group => group.ToArray(), StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, ArchiveEntryDto[]> _models = entries.Values
        .Where(ArchiveCharacterReferences.IsModel)
        .GroupBy(static entry => entry.Name, StringComparer.OrdinalIgnoreCase)
        .ToDictionary(static group => group.Key, static group => group.ToArray(), StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<long, ArchiveEntryDto> _byId = entries.Values.ToDictionary(static entry => entry.EntryId);
    private readonly Dictionary<string, NpcPiece[]> _cache = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _modelPaths = new(StringComparer.OrdinalIgnoreCase);

    public int DistinctCount => _cache.Count;
    public int ResolvedCount { get; private set; }
    public int MissingCount { get; private set; }
    public int EmptyCount { get; private set; }
    public int ModelPathCount => _modelPaths.Count;

    public ArchiveEntryDto? ById(long id) => _byId.GetValueOrDefault(id);

    public IEnumerable<NpcPiece> Pieces(string section, string name, string preview)
    {
        var stem = Path.GetFileNameWithoutExtension(ArchiveCharacterReferences.Normalize(name));
        if (!_cache.TryGetValue(stem, out var cached)) _cache[stem] = cached = Load(stem);
        return cached.Select(piece => piece with { Section = section, PrefabName = name, Preview = preview });
    }

    private NpcPiece[] Load(string stem)
    {
        var candidates = _prefabs.GetValueOrDefault(stem) ?? [];
        if (candidates.Length == 0)
        {
            MissingCount++;
            return [new("", "Unknown", stem, -1, "", -1, "", "", "missing_prefab", [])];
        }
        // Prefer the character prefab folder when the name exists elsewhere too.
        var prefab = candidates.OrderBy(static entry => entry.Path.Contains("/bin__/prefab/", StringComparison.OrdinalIgnoreCase) ? 0 : 1)
            .ThenBy(static entry => entry.Path, StringComparer.OrdinalIgnoreCase).First();
        var ambiguous = candidates.Length > 1;
        (string Slot, string ModelPath)[] models;
        try { models = prefab.OriginalSize > 16 * 1024 * 1024 ? [] : ArchivePrefabModels.Read(decode(prefab)); }
        catch (Exception error) when (error is IOException or InvalidDataException or ArgumentException)
        {
            MissingCount++;
            return [new("", "Unknown", stem, prefab.EntryId, prefab.Path, -1, "", "", "unreadable_prefab", [])];
        }
        ResolvedCount++;
        if (models.Length == 0)
        {
            EmptyCount++;
            return [new("", "None", stem, prefab.EntryId, prefab.Path, -1, "", "", "no_model", [])];
        }
        var result = new List<NpcPiece>();
        foreach (var (slot, modelPath) in models)
        {
            _modelPaths.Add(modelPath);
            var model = ResolveModel(modelPath, out var multiple);
            var resolution = model is null ? "missing_model" : ambiguous || multiple ? "ambiguous" : "resolved";
            result.Add(new("", slot, stem, prefab.EntryId, prefab.Path, model?.EntryId ?? -1, model?.Path ?? modelPath, "", resolution, []));
        }
        return result.ToArray();
    }

    private ArchiveEntryDto? ResolveModel(string modelPath, out bool ambiguous)
    {
        ambiguous = false;
        var normalized = ArchiveCharacterReferences.Normalize(modelPath);
        if (entries.TryGetValue(normalized, out var exact)) return exact;
        if (entries.TryGetValue("character/" + normalized, out exact)) return exact;
        var found = _models.GetValueOrDefault(Path.GetFileName(normalized)) ?? [];
        if (normalized.Contains('/'))
        {
            var suffix = found.Where(entry => ArchiveCharacterReferences.Normalize(entry.Path).EndsWith("/" + normalized, StringComparison.Ordinal)).ToArray();
            if (suffix.Length > 0) found = suffix;
        }
        ambiguous = found.Length > 1;
        return found.OrderBy(static entry => entry.Path, StringComparer.OrdinalIgnoreCase).FirstOrDefault();
    }
}

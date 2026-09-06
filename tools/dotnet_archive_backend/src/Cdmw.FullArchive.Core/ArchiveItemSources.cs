using System.Buffers.Binary;
using System.Text;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

// Same source policy as cdmw.core.item_sources. Only metadata candidates are retained.
internal sealed class ArchiveItemSources
{
    private const string Legacy = "gamedata/binary__/client/bin/";
    private const string Current = "gamedata/binarystaticinfo__/bin/";
    private const string LocalizationRoot = "gamedata/stringtable/binary__/";
    private readonly Dictionary<string, List<ArchiveEntryDto>> _candidates = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, int> _mounts = new(StringComparer.OrdinalIgnoreCase);
    private readonly bool _hasMountTable;

    public ArchiveItemSources(string packageRoot)
    {
        var path = Path.Combine(packageRoot, "meta", "0.papgt");
        if (!File.Exists(path)) return;
        _hasMountTable = true;
        if (new FileInfo(path).Length > 1024 * 1024) throw new InvalidDataException("Archive mount table is unexpectedly large.");
        var bytes = File.ReadAllBytes(path);
        if (bytes.Length < 16 || BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(4))
            != ArchiveNameIndexBuilder.HashLittle(bytes.AsSpan(12), 0xC5EDE))
            throw new InvalidDataException("Archive mount table checksum is invalid.");
        for (var count = 0; 12 + count * 12 + 4 <= bytes.Length; count++)
        {
            var sizeAt = 12 + count * 12;
            var size = BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(sizeAt));
            if ((long)sizeAt + 4 + size != bytes.Length) continue;
            for (var index = 0; index < count; index++)
            {
                var offset = BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(12 + index * 12 + 4));
                if (offset >= size) throw new InvalidDataException("Archive mount name offset is invalid.");
                var start = checked(sizeAt + 4 + (int)offset);
                var end = Array.IndexOf(bytes, (byte)0, start);
                if (end < 0) throw new InvalidDataException("Archive mount name is not terminated.");
                var name = Encoding.ASCII.GetString(bytes, start, end - start);
                _mounts[Path.Combine(packageRoot, name).Replace('\\', '/').ToLowerInvariant()] = count - index;
            }
            return;
        }
        throw new InvalidDataException("Archive mount table layout is invalid.");
    }

    public bool Accepts(ArchiveEntryDto entry) => !ObsoletePackages.Contains(Package(entry))
        && (!_hasMountTable || _mounts.ContainsKey(Package(entry)));

    public (int Mount, (int, int, int, int, string) Fallback) Order(ArchiveEntryDto entry) =>
        (_mounts.GetValueOrDefault(Package(entry)), Priority(entry));
    public ArchiveEntryDto? ItemInfo { get; private set; }
    public ArchiveEntryDto? ItemInfoHeader { get; private set; }
    public ArchiveEntryDto? StringInfo { get; private set; }
    public ArchiveEntryDto? StringInfoHeader { get; private set; }
    public ArchiveEntryDto? EquipTypeInfo { get; private set; }
    public ArchiveEntryDto? EquipTypeInfoHeader { get; private set; }
    public ArchiveEntryDto? PartPrefabDyeSlotInfo { get; private set; }
    public Dictionary<string, ArchiveEntryDto> Localizations { get; } = new(StringComparer.OrdinalIgnoreCase);
    public HashSet<string> ObsoletePackages { get; } = new(StringComparer.OrdinalIgnoreCase);
    public HashSet<string> ExistingPacNames { get; } = new(StringComparer.OrdinalIgnoreCase);

    internal static string Package(ArchiveEntryDto entry) =>
        Path.GetDirectoryName(entry.SourcePamt)?.Replace('\\', '/').ToLowerInvariant() ?? "";

    internal static (int Tier, int Package, int Table, int Paz, string Path) Priority(ArchiveEntryDto entry)
    {
        var package = Path.GetFileName(Path.GetDirectoryName(entry.SourcePamt)) ?? "";
        var numeric = int.TryParse(package, out var number);
        var tier = package.StartsWith("dmm", StringComparison.OrdinalIgnoreCase) ? 3 : numeric ? 1 : 2;
        var table = int.TryParse(Path.GetFileNameWithoutExtension(entry.SourcePamt), out var value) ? value : -1;
        return (tier, numeric ? number : -1, table, entry.PazIndex, entry.SourcePamt.ToLowerInvariant());
    }

    public void Offer(ArchiveEntryDto entry)
    {
        var path = entry.Path.Replace('\\', '/').Trim('/').ToLowerInvariant();
        if (!path.StartsWith(Legacy) && !path.StartsWith(Current) && !path.StartsWith(LocalizationRoot)) return;
        if (!_candidates.TryGetValue(path, out var entries)) _candidates[path] = entries = [];
        entries.Add(entry);
    }

    private (ArchiveEntryDto? Body, ArchiveEntryDto? Header) Pair(string stem, bool current)
    {
        var prefix = (current ? Current : Legacy) + stem;
        var bodyPath = prefix + (current ? ".staticinfobody" : ".pabgb");
        var headerPath = prefix + (current ? ".staticinfoheader" : ".pabgh");
        var bodies = _candidates.GetValueOrDefault(bodyPath) ?? [];
        var headers = _candidates.GetValueOrDefault(headerPath) ?? [];
        var selected = bodies.Concat(headers).Where(Accepts).OrderByDescending(Order).FirstOrDefault();
        if (selected is null) return (null, null);
        var body = bodies.FirstOrDefault(e => string.Equals(e.SourcePamt, selected.SourcePamt, StringComparison.OrdinalIgnoreCase));
        var header = headers.FirstOrDefault(e => string.Equals(e.SourcePamt, selected.SourcePamt, StringComparison.OrdinalIgnoreCase));
        if (body is not null && header is not null) return (body, header);
        if (!current && headers.Count == 0) return (null, null);
        throw new InvalidDataException($"Incomplete {stem} table pair in {selected.SourcePamt}.");
    }

    public void Finish()
    {
        var current = new[] { Current + "iteminfo.staticinfobody", Current + "iteminfo.staticinfoheader" }
            .Any(path => (_candidates.GetValueOrDefault(path) ?? []).Any(Accepts));
        if (current && _candidates.TryGetValue(Legacy + "iteminfo.pabgb", out var old))
        {
            var modern = _candidates.GetValueOrDefault(Current + "iteminfo.staticinfobody") ?? [];
            var currentPackages = modern.Select(Package).ToHashSet(StringComparer.OrdinalIgnoreCase);
            foreach (var entry in old)
                if (!currentPackages.Contains(Package(entry))) ObsoletePackages.Add(Package(entry));
        }
        (ItemInfo, ItemInfoHeader) = Pair("iteminfo", current);
        (StringInfo, StringInfoHeader) = Pair("stringinfo", current);
        (EquipTypeInfo, EquipTypeInfoHeader) = Pair("equiptypeinfo", current);
        if (!current && EquipTypeInfo is null) (EquipTypeInfo, EquipTypeInfoHeader) = Pair("equiptypeinfo", true);
        PartPrefabDyeSlotInfo = Pair("partprefabdyeslotinfo", current).Body;
        // Older callers can provide payload-only fixtures; current tables always need their directory.
        if (!current && ItemInfo is null)
            ItemInfo = _candidates.GetValueOrDefault(Legacy + "iteminfo.pabgb")?.Where(Accepts).OrderByDescending(Order).FirstOrDefault();
        if (!current && StringInfo is null)
            StringInfo = _candidates.GetValueOrDefault(Legacy + "stringinfo.pabgb")?.Where(Accepts).OrderByDescending(Order).FirstOrDefault();
        foreach (var (path, options) in _candidates)
        {
            if (!path.StartsWith(LocalizationRoot)) continue;
            var relative = path[LocalizationRoot.Length..];
            string language;
            if (current)
            {
                var parts = relative.Split('/');
                if (parts.Length != 2 || parts[1] != "item.paloc") continue;
                language = parts[0];
            }
            else
            {
                if (!relative.StartsWith("localizationstring_") || !relative.EndsWith(".paloc")) continue;
                language = relative["localizationstring_".Length..^6];
            }
            var selected = options.Where(Accepts).OrderByDescending(Order).FirstOrDefault();
            if (selected is not null) Localizations[language] = selected;
        }
    }
}

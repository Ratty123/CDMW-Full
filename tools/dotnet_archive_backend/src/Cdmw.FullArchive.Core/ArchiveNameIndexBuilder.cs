using System.Buffers.Binary;
using System.Text;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

internal static class ArchiveNameIndexBuilder
{
    private const uint NameHashSeed = 0xC5EDE;
    private const int MaximumSourceBytes = 1024 * 1024 * 1024;
    private static readonly byte[] ItemInfoMarker =
    [
        0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x07, 0x70, 0x00, 0x00, 0x00,
    ];

    private static readonly (string Language, string TableName)[] LocalizationTables =
    [
        ("kor", "localizationstring_kor"),
        ("eng", "localizationstring_eng"),
        ("jpn", "localizationstring_jpn"),
        ("rus", "localizationstring_rus"),
        ("tur", "localizationstring_tur"),
        ("spa-es", "localizationstring_spa-es"),
        ("spa-mx", "localizationstring_spa-mx"),
        ("fre", "localizationstring_fre"),
        ("ger", "localizationstring_ger"),
        ("ita", "localizationstring_ita"),
        ("pol", "localizationstring_pol"),
        ("por-br", "localizationstring_por-br"),
        ("zho-tw", "localizationstring_zho-tw"),
        ("zho-cn", "localizationstring_zho-cn"),
    ];

    private static readonly string[] ModelHashSuffixes =
    [
        "", "_l", "_r", "_u", "_s", "_t", "_c", "_d",
        "_index01", "_index02", "_index03",
        "_index01_l", "_index01_r", "_index02_l", "_index02_r",
        "_index03_l", "_index03_r", "_sub01", "_sub02", "_sub03",
    ];

    private static readonly string[] VariantSuffixes =
    [
        "_index01_l", "_index01_r", "_index02_l", "_index02_r", "_index03_l", "_index03_r",
        "_index01", "_index02", "_index03", "_sub01", "_sub02", "_sub03",
        "_l", "_r", "_u", "_s", "_t", "_c", "_d",
    ];

    private static readonly (string Internal, string Model)[] CompatibleItemModelTokens =
    [
        ("onehandsword", "01_sword"), ("twohandsword", "02_sword"),
        ("twohandspear", "02_spear"), ("halberd", "02_alebard"),
        ("alebard", "02_alebard"), ("hammer", "02_hammer"),
        ("spear", "spear"), ("shield", "03_shield"), ("backpack", "bag"),
        ("ring", "ring"), ("earring", "earring"), ("necklace", "necklace"),
        ("helm", "hel"), ("helmet", "hel"), ("armor", "ub"),
        ("cloak", "cloak"), ("glove", "hand"), ("boots", "foot"),
        ("saddle", "horse_ub"),
    ];

    public static ArchiveNameIndex Build(
        ArchiveSession session,
        NativeArchiveCore native,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        var sources = FindSources(session, cancellationToken, progress);
        if (sources.ItemInfo is null)
        {
            Publish(progress, new ProgressUpdate(session.Index.EntryCount, session.Index.EntryCount, "names_unavailable"));
            return ArchiveNameIndex.Unavailable("iteminfo.pabgb was not found in archive package 0008.");
        }

        var stringHashes = sources.StringInfo is null
            ? new Dictionary<uint, string>()
            : ParseStringInfo(DecodeSource(native, sources.StringInfo, cancellationToken), cancellationToken);
        var records = ParseItemInfo(
            DecodeSource(native, sources.ItemInfo, cancellationToken),
            stringHashes,
            cancellationToken);
        if (records.Count == 0)
        {
            Publish(progress, new ProgressUpdate(session.Index.EntryCount, session.Index.EntryCount, "names_unavailable"));
            return ArchiveNameIndex.Unavailable("iteminfo.pabgb contained no supported item-name records.");
        }

        var wantedLocalizationIds = records
            .Select(static record => record.LocalizationId)
            .Where(static value => value.Length > 0)
            .ToHashSet(StringComparer.Ordinal);
        if (wantedLocalizationIds.Count == 0 || sources.Localization.Count == 0)
        {
            Publish(progress, new ProgressUpdate(session.Index.EntryCount, session.Index.EntryCount, "names_unavailable"));
            return ArchiveNameIndex.Unavailable("Archive item records do not have a usable localization table.");
        }

        var localized = new Dictionary<string, Dictionary<string, string>>(StringComparer.OrdinalIgnoreCase);
        foreach (var (language, entry) in sources.Localization)
        {
            cancellationToken.ThrowIfCancellationRequested();
            localized[language] = ParseLocalization(
                DecodeSource(native, entry, cancellationToken),
                wantedLocalizationIds,
                cancellationToken);
        }
        if (localized.Values.All(static table => table.Count == 0))
        {
            Publish(progress, new ProgressUpdate(session.Index.EntryCount, session.Index.EntryCount, "names_unavailable"));
            return ArchiveNameIndex.Unavailable("Archive localization tables contained no names referenced by iteminfo.pabgb.");
        }

        foreach (var record in records)
        {
            record.DisplayName = ResolveDisplayName(record.LocalizationId, localized);
        }

        var wantedModelHashes = records
            .SelectMany(static record => record.PrefabHashes)
            .ToHashSet();
        var resolvedModels = ResolveModelHashes(session, wantedModelHashes, cancellationToken, progress);
        var exact = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var related = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var record in records)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (record.DisplayName.Length == 0)
            {
                continue;
            }
            foreach (var hash in record.PrefabHashes)
            {
                if (resolvedModels.TryGetValue(hash, out var model))
                {
                    AddDisplayName(exact, NormalizeModelStem(model), record.DisplayName);
                }
            }
            foreach (var model in record.RelatedModelStems)
            {
                AddDisplayName(related, StripModelVariantSuffix(model), record.DisplayName);
            }
        }

        Publish(progress, new ProgressUpdate(session.Index.EntryCount, session.Index.EntryCount, "names_complete"));
        return ArchiveNameIndex.FromMappings(exact, related);
    }

    private static NameSources FindSources(
        ArchiveSession session,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        var result = new NameSources();
        var total = session.Index.EntryCount;
        Publish(progress, new ProgressUpdate(0, total, "names_scan"));
        for (long entryId = 0; entryId < total; entryId++)
        {
            if ((entryId & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                Publish(progress, new ProgressUpdate(entryId, total, "names_scan"));
            }
            var entry = session.ReadEntry(entryId);
            var package = PackageGroup(entry.SourcePamt);
            var path = entry.Path.Replace('\\', '/');
            var basename = Path.GetFileName(path);
            if (package.Equals("0008", StringComparison.OrdinalIgnoreCase))
            {
                if (result.ItemInfo is null && path.Contains("iteminfo.pabgb", StringComparison.OrdinalIgnoreCase))
                {
                    result.ItemInfo = entry;
                }
                else if (result.StringInfo is null && basename.Equals("stringinfo.pabgb", StringComparison.OrdinalIgnoreCase))
                {
                    result.StringInfo = entry;
                }
            }
            else if (package.Equals("0020", StringComparison.OrdinalIgnoreCase) &&
                path.Contains("localizationstring_", StringComparison.OrdinalIgnoreCase))
            {
                foreach (var (language, tableName) in LocalizationTables)
                {
                    if (path.Contains(tableName, StringComparison.OrdinalIgnoreCase))
                    {
                        result.Localization.TryAdd(language, entry);
                        break;
                    }
                }
            }
        }
        return result;
    }

    private static byte[] DecodeSource(
        NativeArchiveCore native,
        ArchiveEntryDto entry,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (entry.OriginalSize < 0 || entry.OriginalSize > MaximumSourceBytes)
        {
            throw new InvalidDataException($"Archive name source '{entry.Path}' exceeds the bounded decode limit.");
        }
        var decoded = native.Decode(entry);
        cancellationToken.ThrowIfCancellationRequested();
        return decoded.Bytes;
    }

    private static Dictionary<string, string> ParseLocalization(
        byte[] data,
        IReadOnlySet<string> wantedIds,
        CancellationToken cancellationToken)
    {
        var rows = new Dictionary<string, string>(StringComparer.Ordinal);
        var position = 0;
        while (position + 8 < data.Length)
        {
            if ((position & 0xFFFFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
            }
            var idLength = ReadUInt32(data, position);
            if (idLength is >= 6 and <= 20 && idLength <= int.MaxValue &&
                position + 4L + idLength <= data.Length)
            {
                var idBytes = data.AsSpan(position + 4, (int)idLength);
                if (IsAsciiDigits(idBytes))
                {
                    var id = Encoding.ASCII.GetString(idBytes);
                    var textPosition = checked(position + 4 + (int)idLength);
                    if (textPosition + 4 < data.Length)
                    {
                        var textLength = ReadUInt32(data, textPosition);
                        if (textLength is > 0 and < 50_000 && textLength <= int.MaxValue &&
                            textPosition + 4L + textLength <= data.Length)
                        {
                            if (wantedIds.Contains(id))
                            {
                                rows[id] = Encoding.UTF8.GetString(
                                    data,
                                    textPosition + 4,
                                    (int)textLength);
                            }
                            position = checked(textPosition + 4 + (int)textLength);
                            continue;
                        }
                    }
                }
            }
            position++;
        }
        return rows;
    }

    private static Dictionary<uint, string> ParseStringInfo(byte[] data, CancellationToken cancellationToken)
    {
        var hashes = new Dictionary<uint, string>();
        var position = 0;
        while (position + 8 < data.Length)
        {
            if ((position & 0xFFFFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
            }
            var stringLength = ReadUInt32(data, position);
            if (stringLength is >= 3 and <= 180 && stringLength <= int.MaxValue &&
                position + 8L + stringLength <= data.Length)
            {
                var text = Encoding.UTF8.GetString(data, position + 4, (int)stringLength).TrimEnd('\0');
                const string prefix = "itemicon_prefab_";
                if (text.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                {
                    var modelStem = NormalizeModelStem(text[prefix.Length..]);
                    if (modelStem.StartsWith("cd_", StringComparison.OrdinalIgnoreCase))
                    {
                        hashes[ReadUInt32(data, checked(position + 4 + (int)stringLength))] = modelStem;
                        hashes[HashLittle(Encoding.UTF8.GetBytes(text), NameHashSeed)] = modelStem;
                        hashes[HashLittle(Encoding.UTF8.GetBytes(modelStem), NameHashSeed)] = modelStem;
                    }
                }
                position = checked(position + 8 + (int)stringLength);
                continue;
            }
            position++;
        }
        return hashes;
    }

    private static List<ItemRecord> ParseItemInfo(
        byte[] data,
        IReadOnlyDictionary<uint, string> stringInfoHashes,
        CancellationToken cancellationToken)
    {
        var records = new List<ItemRecord>();
        var seenIds = new HashSet<uint>();
        var searchStart = 0;
        while (searchStart + ItemInfoMarker.Length < data.Length)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var relative = data.AsSpan(searchStart).IndexOf(ItemInfoMarker);
            if (relative < 0)
            {
                break;
            }
            var position = checked(searchStart + relative);
            searchStart = checked(position + ItemInfoMarker.Length);
            var nameStart = position;
            while (nameStart > 0 && data[nameStart - 1] is >= 0x21 and <= 0x7E)
            {
                nameStart--;
                if (position - nameStart > 150)
                {
                    break;
                }
            }
            if (position - nameStart < 3 || nameStart < 8)
            {
                continue;
            }
            var nameBytes = data.AsSpan(nameStart, position - nameStart);
            if (!IsInternalItemName(nameBytes))
            {
                continue;
            }
            var nameLength = ReadUInt32(data, nameStart - 4);
            var itemId = ReadUInt32(data, nameStart - 8);
            if ((nameLength != nameBytes.Length && nameLength != nameBytes.Length + 1) ||
                itemId is < 100 or > 100_000_000 || !seenIds.Add(itemId))
            {
                continue;
            }

            var internalName = Encoding.ASCII.GetString(nameBytes);
            var localizationId = string.Empty;
            var localizationOffset = position + 18;
            if (localizationOffset + 4 < data.Length)
            {
                var localizationLength = ReadUInt32(data, localizationOffset);
                if (localizationLength is > 5 and < 25 && localizationLength <= int.MaxValue &&
                    localizationOffset + 4L + localizationLength <= data.Length)
                {
                    var localizationBytes = data.AsSpan(localizationOffset + 4, (int)localizationLength);
                    if (IsAsciiDigits(localizationBytes))
                    {
                        localizationId = Encoding.ASCII.GetString(localizationBytes);
                    }
                }
            }

            var prefabHashes = new List<uint>();
            var hashSearchEnd = Math.Min(data.Length, position + 800);
            for (var scan = position + 14; scan + 15 < hashSearchEnd; scan++)
            {
                if (data[scan] is not (0x0E or 0x0F or 0x10))
                {
                    continue;
                }
                var firstCount = ReadUInt32(data, scan + 3);
                var secondCount = ReadUInt32(data, scan + 7);
                if (firstCount is not (> 0 and <= 5) || secondCount is not (> 0 and <= 5) ||
                    scan + 11L + secondCount * 4L > data.Length)
                {
                    continue;
                }
                for (var hashIndex = 0; hashIndex < secondCount; hashIndex++)
                {
                    var value = ReadUInt32(data, checked(scan + 11 + (int)hashIndex * 4));
                    if (value != 0)
                    {
                        prefabHashes.Add(value);
                    }
                }
                if (prefabHashes.Count > 0)
                {
                    break;
                }
            }

            var relatedModels = new List<string>();
            if (stringInfoHashes.Count > 0)
            {
                var nextRelative = data.AsSpan(searchStart).IndexOf(ItemInfoMarker);
                var nextPosition = nextRelative < 0 ? position + 2500 : searchStart + nextRelative;
                var iconSearchEnd = Math.Min(data.Length, Math.Min(nextPosition, position + 2500));
                for (var scan = position; scan + 4 <= iconSearchEnd; scan++)
                {
                    var value = ReadUInt32(data, scan);
                    if (stringInfoHashes.TryGetValue(value, out var modelStem) &&
                        ItemModelReferenceIsCompatible(internalName, modelStem) &&
                        !relatedModels.Contains(modelStem, StringComparer.OrdinalIgnoreCase))
                    {
                        relatedModels.Add(modelStem);
                    }
                }
            }
            records.Add(new ItemRecord(localizationId, internalName, prefabHashes, relatedModels));
        }
        return records;
    }

    private static Dictionary<uint, string> ResolveModelHashes(
        ArchiveSession session,
        IReadOnlySet<uint> wantedHashes,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress)
    {
        var resolved = new Dictionary<uint, string>();
        if (wantedHashes.Count == 0)
        {
            return resolved;
        }
        var total = session.Index.EntryCount;
        Publish(progress, new ProgressUpdate(0, total, "names_resolve_models"));
        for (long entryId = 0; entryId < total && resolved.Count < wantedHashes.Count; entryId++)
        {
            if ((entryId & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                Publish(progress, new ProgressUpdate(entryId, total, "names_resolve_models"));
            }
            var entry = session.ReadEntry(entryId);
            if (!PackageGroup(entry.SourcePamt).Equals("0009", StringComparison.OrdinalIgnoreCase) ||
                entry.Extension is not (".prefab" or ".pac" or ".pact"))
            {
                continue;
            }
            var stem = Path.GetFileNameWithoutExtension(entry.Path).ToLowerInvariant();
            foreach (var candidate in ModelCandidateBases(stem))
            {
                foreach (var suffix in ModelHashSuffixes)
                {
                    var model = candidate + suffix;
                    var hash = HashLittle(Encoding.ASCII.GetBytes(model), NameHashSeed);
                    if (wantedHashes.Contains(hash))
                    {
                        resolved.TryAdd(hash, model);
                    }
                }
            }
        }
        return resolved;
    }

    private static string ResolveDisplayName(
        string localizationId,
        IReadOnlyDictionary<string, Dictionary<string, string>> localized)
    {
        if (localizationId.Length == 0)
        {
            return string.Empty;
        }
        if (localized.TryGetValue("eng", out var english) &&
            english.TryGetValue(localizationId, out var englishName) &&
            !string.IsNullOrWhiteSpace(englishName))
        {
            return englishName.Trim();
        }
        foreach (var (language, _) in LocalizationTables)
        {
            if (localized.TryGetValue(language, out var table) &&
                table.TryGetValue(localizationId, out var name) &&
                !string.IsNullOrWhiteSpace(name))
            {
                return name.Trim();
            }
        }
        return string.Empty;
    }

    private static void AddDisplayName(Dictionary<string, string> map, string key, string value)
    {
        key = key.Trim().ToLowerInvariant();
        value = value.Trim();
        if (key.Length == 0 || value.Length == 0)
        {
            return;
        }
        if (!map.TryGetValue(key, out var existing))
        {
            map[key] = value;
        }
        else if (!existing.Split(" / ", StringSplitOptions.None).Contains(value, StringComparer.OrdinalIgnoreCase))
        {
            map[key] = $"{existing} / {value}";
        }
    }

    private static string PackageGroup(string pamtPath) =>
        Path.GetFileName(Path.GetDirectoryName(pamtPath)) ?? string.Empty;

    private static string NormalizeModelStem(string value)
    {
        var basename = Path.GetFileName(value.Replace('\\', '/')).ToLowerInvariant();
        return Path.GetExtension(basename) is ".pac" or ".prefab" or ".pact"
            ? Path.GetFileNameWithoutExtension(basename)
            : basename;
    }

    private static IEnumerable<string> ModelCandidateBases(string stem)
    {
        yield return stem;
        var stripped = StripModelVariantSuffix(stem);
        if (!stripped.Equals(stem, StringComparison.OrdinalIgnoreCase))
        {
            yield return stripped;
        }
    }

    private static string StripModelVariantSuffix(string stem)
    {
        var normalized = stem.Trim().ToLowerInvariant();
        while (normalized.Length > 0)
        {
            var prior = normalized;
            foreach (var suffix in VariantSuffixes)
            {
                if (normalized.Length > suffix.Length && normalized.EndsWith(suffix, StringComparison.Ordinal))
                {
                    normalized = normalized[..^suffix.Length];
                    break;
                }
            }
            if (normalized.Equals(prior, StringComparison.Ordinal))
            {
                break;
            }
        }
        if (normalized.Length >= 2 && char.IsAsciiDigit(normalized[^2]) && char.IsAsciiLetter(normalized[^1]))
        {
            normalized = normalized[..^1];
        }
        return normalized;
    }

    private static bool ItemModelReferenceIsCompatible(string internalName, string modelStem) =>
        CompatibleItemModelTokens.Any(pair =>
            internalName.Contains(pair.Internal, StringComparison.OrdinalIgnoreCase) &&
            modelStem.Contains(pair.Model, StringComparison.OrdinalIgnoreCase));

    private static bool IsInternalItemName(ReadOnlySpan<byte> value)
    {
        if (value.IsEmpty || !IsAsciiLetter(value[0]))
        {
            return false;
        }
        foreach (var character in value)
        {
            if (!IsAsciiLetter(character) && !char.IsAsciiDigit((char)character) && character != (byte)'_')
            {
                return false;
            }
        }
        return true;
    }

    private static bool IsAsciiLetter(byte value) =>
        value is >= (byte)'A' and <= (byte)'Z' or >= (byte)'a' and <= (byte)'z';

    private static bool IsAsciiDigits(ReadOnlySpan<byte> value)
    {
        foreach (var character in value)
        {
            if (character is < (byte)'0' or > (byte)'9')
            {
                return false;
            }
        }
        return true;
    }

    private static uint ReadUInt32(byte[] data, int offset) =>
        BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset, sizeof(uint)));

    private static uint HashLittle(ReadOnlySpan<byte> data, uint initialValue)
    {
        unchecked
        {
            var a = 0xDEADBEEFu + (uint)data.Length + initialValue;
            var b = a;
            var c = a;
            var offset = 0;
            var remaining = data.Length;
            while (remaining > 12)
            {
                a += ReadPartialUInt32(data, offset);
                b += ReadPartialUInt32(data, offset + 4);
                c += ReadPartialUInt32(data, offset + 8);
                Mix(ref a, ref b, ref c);
                offset += 12;
                remaining -= 12;
            }
            if (remaining >= 9) c += ReadPartialUInt32(data, offset + 8);
            if (remaining >= 5) b += ReadPartialUInt32(data, offset + 4);
            if (remaining >= 1) a += ReadPartialUInt32(data, offset);
            if (remaining == 0) return c;
            Final(ref a, ref b, ref c);
            return c;
        }
    }

    private static uint ReadPartialUInt32(ReadOnlySpan<byte> data, int offset)
    {
        uint value = 0;
        for (var index = 0; index < 4 && offset + index < data.Length; index++)
        {
            value |= (uint)data[offset + index] << (8 * index);
        }
        return value;
    }

    private static void Mix(ref uint a, ref uint b, ref uint c)
    {
        unchecked
        {
            a -= c; a ^= RotateLeft(c, 4); c += b;
            b -= a; b ^= RotateLeft(a, 6); a += c;
            c -= b; c ^= RotateLeft(b, 8); b += a;
            a -= c; a ^= RotateLeft(c, 16); c += b;
            b -= a; b ^= RotateLeft(a, 19); a += c;
            c -= b; c ^= RotateLeft(b, 4); b += a;
        }
    }

    private static void Final(ref uint a, ref uint b, ref uint c)
    {
        unchecked
        {
            c = (c ^ b) - RotateLeft(b, 14);
            a = (a ^ c) - RotateLeft(c, 11);
            b = (b ^ a) - RotateLeft(a, 25);
            c = (c ^ b) - RotateLeft(b, 16);
            a = (a ^ c) - RotateLeft(c, 4);
            b = (b ^ a) - RotateLeft(a, 14);
            c = (c ^ b) - RotateLeft(b, 24);
        }
    }

    private static uint RotateLeft(uint value, int shift) => (value << shift) | (value >> (32 - shift));

    private static void Publish(Func<ProgressUpdate, Task>? progress, ProgressUpdate update) =>
        progress?.Invoke(update).GetAwaiter().GetResult();

    private sealed class NameSources
    {
        public ArchiveEntryDto? ItemInfo { get; set; }
        public ArchiveEntryDto? StringInfo { get; set; }
        public Dictionary<string, ArchiveEntryDto> Localization { get; } = new(StringComparer.OrdinalIgnoreCase);
    }

    private sealed class ItemRecord(
        string localizationId,
        string internalName,
        List<uint> prefabHashes,
        List<string> relatedModelStems)
    {
        public string LocalizationId { get; } = localizationId;
        public string InternalName { get; } = internalName;
        public List<uint> PrefabHashes { get; } = prefabHashes;
        public List<string> RelatedModelStems { get; } = relatedModelStems;
        public string DisplayName { get; set; } = string.Empty;
    }
}

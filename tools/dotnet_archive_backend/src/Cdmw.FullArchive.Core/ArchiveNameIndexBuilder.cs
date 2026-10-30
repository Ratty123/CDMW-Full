using System.Buffers.Binary;
using System.Text;
using System.Text.RegularExpressions;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

internal static class ArchiveNameIndexBuilder
{
    private const uint NameHashSeed = 0xC5EDE;
    private const int MaximumSourceBytes = 1024 * 1024 * 1024;
    private const int LocalizationScanBytes = 160;
    private const int PrefabScanBytes = 800;
    private const int MaximumPrefabListCount = 32;
    private const int MaximumPrefabHashes = 128;
    private const int MaximumRelatedModelCandidates = 64;
    private const int MaximumPrefabDependencyPaths = 32;
    private const int MaximumPrefabSourceBytes = 16 * 1024 * 1024;
    private static readonly int[] PabghCountWidths = [1, 2, 4];

    // Composite keys are real: `characterappearanceindexinfo` uses 8 bytes and
    // `aieventtableinfo` uses 12, so a reader allowing only 1/2/4 drops them.
    private static readonly int[] PabghKeyWidths = [1, 2, 4, 8, 12];

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
        "", "_in", "_l", "_r", "_u", "_s", "_t", "_c", "_d",
        "_index01", "_index02", "_index03",
        "_index01_l", "_index01_r", "_index02_l", "_index02_r",
        "_index03_l", "_index03_r", "_sub01", "_sub02", "_sub03",
    ];

    private static readonly string[] VariantSuffixes =
    [
        "_index01_l", "_index01_r", "_index02_l", "_index02_r", "_index03_l", "_index03_r",
        "_index01", "_index02", "_index03", "_sub01", "_sub02", "_sub03",
        "_in", "_l", "_r", "_u", "_s", "_t", "_c", "_d",
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
        ("saddle", "horse_ub"), ("horsearmor", "horse_ub"), ("barding", "horse_ub"),
        ("dagger", "dagger"), ("rapier", "rapier"), ("axe", "axe"), ("mace", "mace"),
        ("bow", "bow"), ("crossbow", "crossbow"), ("pistol", "pistol"), ("musket", "musket"),
        ("cannon", "cannon"), ("wand", "wand"), ("gauntlet", "hand"), ("bracer", "hand"),
        ("shoe", "foot"), ("sandal", "foot"), ("greave", "foot"), ("pants", "lb"),
        ("trouser", "lb"), ("skirt", "lb"), ("cape", "cloak"), ("veil", "mask"),
        ("pendant", "necklace"), ("amulet", "necklace"),
    ];
    private static readonly string[] ItemIconPrefixes =
    [
        "itemicon_prefab_", "itemicon_", "icon_prefab_", "icon_",
    ];
    private static readonly Regex PrefabModelPathPattern = new(
        "(?<path>(?:character|object|vehicle|environment|effect)[/\\\\][A-Za-z0-9_./\\\\-]+\\.(?:pamlod|pami|pac|pam|prefab))",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);
    private static readonly HashSet<string> GenericItemModelTokens = new(StringComparer.OrdinalIgnoreCase)
    {
        "abyss", "armor", "armour", "character", "common", "customize", "default", "equip", "equipment",
        "hand", "icon", "index", "item", "material", "model", "mysterm", "normal", "prefab", "related",
        "reward", "standard", "sub", "texture", "weapon",
    };

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
        var itemInfoData = DecodeSource(native, sources.ItemInfo, cancellationToken);
        // The row directory gives every record an exact boundary. Without the
        // companion the marker scan below finds fewer rows, so fall back to it
        // only when the `.pabgh` is absent or does not describe this payload.
        var records = sources.ItemInfoHeader is null
            ? null
            : ParseItemInfoRows(
                itemInfoData,
                DecodeSource(native, sources.ItemInfoHeader, cancellationToken),
                stringHashes,
                cancellationToken);
        records ??= ParseItemInfo(itemInfoData, stringHashes, cancellationToken);
        if (records.Count == 0)
        {
            Publish(progress, new ProgressUpdate(session.Index.EntryCount, session.Index.EntryCount, "names_unavailable"));
            return ArchiveNameIndex.Unavailable("iteminfo.pabgb contained no supported item-name records.");
        }

        var wantedLocalizationIds = records
            .SelectMany(static record => record.LocalizationIds)
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
            record.DisplayName = ResolveDisplayName(record.LocalizationIds, localized);
            record.RelatedModelStems.RemoveAll(
                model => !ItemModelReferenceIsCompatible(record.InternalName, record.DisplayName, model));
        }

        var wantedModelHashes = records
            .SelectMany(static record => record.PrefabHashes)
            .ToHashSet();
        var resolvedModels = ResolveModelHashes(session, wantedModelHashes, cancellationToken, progress);
        var prefabCandidates = records
            .SelectMany(record => record.PrefabHashes
                .Select(hash => resolvedModels.GetValueOrDefault(hash) ?? string.Empty)
                .Concat(record.RelatedModelStems))
            .Where(static value => value.Length > 0)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var prefabModelPaths = ResolvePrefabModelPaths(
            session,
            native,
            prefabCandidates,
            cancellationToken,
            progress);
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
            var recordCandidates = record.PrefabHashes
                .Select(hash => resolvedModels.GetValueOrDefault(hash) ?? string.Empty)
                .Concat(record.RelatedModelStems)
                .Where(static value => value.Length > 0)
                .Distinct(StringComparer.OrdinalIgnoreCase);
            foreach (var candidate in recordCandidates)
            {
                if (!prefabModelPaths.TryGetValue(NormalizeModelStem(candidate), out var modelPaths)) continue;
                foreach (var modelPath in modelPaths)
                {
                    AddDisplayName(exact, NormalizeModelStem(modelPath), record.DisplayName);
                }
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
        var sources = new ArchiveItemSources(session.PackageRoot);
        var total = session.Index.EntryCount;
        for (long entryId = 0; entryId < total; entryId++)
        {
            if ((entryId & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                Publish(progress, new ProgressUpdate(entryId, total, "names_scan"));
            }
            sources.Offer(session.ReadEntry(entryId));
        }
        sources.Finish();
        var result = new NameSources { ItemInfo = sources.ItemInfo, ItemInfoHeader = sources.ItemInfoHeader, StringInfo = sources.StringInfo };
        foreach (var pair in sources.Localizations) result.Localization[pair.Key] = pair.Value;
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

    internal static Dictionary<string, string> ParseLocalization(
        byte[] data,
        IReadOnlySet<string> wantedIds,
        CancellationToken cancellationToken)
    {
        data = DecodeLocalizationContainer(data, cancellationToken);
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

    private static byte[] DecodeLocalizationContainer(byte[] data, CancellationToken cancellationToken)
    {
        if (!data.AsSpan().StartsWith("paloc"u8)) return data;
        const int headerSize = 512, maximumPayload = 256 * 1024 * 1024;
        if (data.Length < headerSize) throw new InvalidDataException("PALOC container header is truncated");
        if (ReadUInt32(data, 5) != 0) throw new InvalidDataException("Unsupported PALOC container version");
        if (ReadUInt32(data, 9) != data.Length - headerSize) throw new InvalidDataException("PALOC compressed size does not match its bytes");
        var size = ReadUInt32(data, 13);
        if (size < 4 || size > maximumPayload) throw new InvalidDataException("PALOC uncompressed size is out of bounds");
        var output = new byte[(int)size];
        var input = headerSize;
        var written = 0;
        int Length(int length)
        {
            if (length != 15) return length;
            byte extension;
            do
            {
                if (input == data.Length) throw new InvalidDataException("PALOC LZ4 length is truncated");
                extension = data[input++];
                if (length > maximumPayload - extension) throw new InvalidDataException("PALOC LZ4 length is out of bounds");
                length += extension;
            } while (extension == 255);
            return length;
        }
        while (input < data.Length)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var token = data[input++];
            var literals = Length(token >> 4);
            if (literals > data.Length - input || literals > output.Length - written)
                throw new InvalidDataException("PALOC LZ4 literal run is outside its buffer");
            data.AsSpan(input, literals).CopyTo(output.AsSpan(written));
            input += literals;
            written += literals;
            if (input == data.Length) break;
            if (data.Length - input < 2) throw new InvalidDataException("PALOC LZ4 match offset is truncated");
            var offset = data[input] | data[input + 1] << 8;
            input += 2;
            if (offset == 0 || offset > written) throw new InvalidDataException("PALOC LZ4 match offset is invalid");
            var matched = Length(token & 15) + 4;
            if (matched > output.Length - written) throw new InvalidDataException("PALOC LZ4 match run is outside its output buffer");
            for (var index = 0; index < matched; index++)
            {
                if ((index & 0xFFFF) == 0) cancellationToken.ThrowIfCancellationRequested();
                output[written + index] = output[written - offset + index];
            }
            written += matched;
        }
        if (written != output.Length) throw new InvalidDataException("PALOC decoded size does not match its payload");
        return output;
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
                var prefix = ItemIconPrefixes.FirstOrDefault(
                    value => text.StartsWith(value, StringComparison.OrdinalIgnoreCase));
                if (prefix is not null)
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

    /// <summary>One `.pabgh` row: a primary key and where the matching `.pabgb` row starts.</summary>
    internal readonly record struct PabghDirectoryRow(byte[] Key, uint Offset, int KeyOffset = 0);
    internal enum TableKeyLayout { Inline, Named, PrefixFourZeros }

    /// <summary>
    /// Resolve the header's count and key widths against the row payload.
    /// Both are variable width, so they are found by search and confirmed against the
    /// payload: every row repeats its own key inline. A one-row table fits several
    /// widths arithmetically, and that inline check is the only thing separating them.
    /// </summary>
    internal static List<PabghDirectoryRow>? ResolvePabghDirectory(byte[] header, byte[] payload,
        TableKeyLayout layout = TableKeyLayout.Inline)
    {
        foreach (var countWidth in PabghCountWidths)
        {
            if (header.Length < countWidth)
            {
                continue;
            }
            long count = 0;
            for (var i = 0; i < countWidth; i++)
            {
                count |= (long)header[i] << (8 * i);
            }
            if (count <= 0)
            {
                continue;
            }
            var remainder = header.Length - countWidth;
            if (remainder % count != 0)
            {
                continue;
            }
            var rowSize = remainder / count;
            if (rowSize < 5)
            {
                continue;
            }
            var keyWidth = (int)(rowSize - 4);
            if (Array.IndexOf(PabghKeyWidths, keyWidth) < 0)
            {
                continue;
            }
            var rows = new List<PabghDirectoryRow>((int)count);
            var cursor = (long)countWidth;
            long previous = -1;
            var usable = true;
            for (long index = 0; index < count; index++)
            {
                var key = new byte[keyWidth];
                Array.Copy(header, checked((int)cursor), key, 0, keyWidth);
                var offset = ReadUInt32(header, checked((int)(cursor + keyWidth)));
                if (offset <= previous)
                {
                    usable = false;
                    break;
                }
                previous = offset;
                rows.Add(new PabghDirectoryRow(key, offset));
                cursor += rowSize;
            }
            if (!usable || rows.Count == 0 || rows[0].Offset != 0 || rows[^1].Offset >= payload.Length)
            {
                continue;
            }
            var inlineKeysMatch = true;
            for (var index = 0; index < rows.Count; index++)
            {
                var row = rows[index];
                var start = checked((int)row.Offset);
                var end = index + 1 < rows.Count ? checked((int)rows[index + 1].Offset) : payload.Length;
                if (start + keyWidth > end) { inlineKeysMatch = false; break; }
                var inlineMatch = payload.AsSpan(start, keyWidth).SequenceEqual(row.Key);
                if (layout == TableKeyLayout.Named && inlineMatch)
                {
                    inlineMatch = keyWidth == 4 && start + 8 <= end;
                    if (inlineMatch)
                    {
                        var length = ReadUInt32(payload, start + 4);
                        inlineMatch = length is > 0 and <= 256 && start + 8L + length <= end;
                    }
                }
                if (inlineMatch) continue;
                var keyOffset = 0;
                if (layout == TableKeyLayout.Named && keyWidth == 4 && start + 8 <= end)
                {
                    var length = ReadUInt32(payload, start);
                    if (length is 0 or > 256 || start + 8L + length > end) { inlineKeysMatch = false; break; }
                    keyOffset = 4 + (int)length;
                }
                else if (layout == TableKeyLayout.PrefixFourZeros && start + 4 + keyWidth <= end
                    && ReadUInt32(payload, start) == 0) keyOffset = 4;
                if (keyOffset == 0 || !payload.AsSpan(start + keyOffset, keyWidth).SequenceEqual(row.Key))
                {
                    inlineKeysMatch = false;
                    break;
                }
                rows[index] = row with { KeyOffset = keyOffset };
            }
            if (inlineKeysMatch)
            {
                return rows;
            }
        }
        return null;
    }

    /// <summary>
    /// Read a localization key out of an inline `07 7x 00 00 00` sub-record. The shape
    /// is `tag, u32 repeat-key, u32 length, ascii`.
    /// </summary>
    internal static string ReadItemInfoSubRecordKey(byte[] data, int rowStart, int rowEnd, byte tagSecond)
    {
        Span<byte> tag = [0x07, tagSecond, 0x00, 0x00, 0x00];
        var span = data.AsSpan(rowStart, rowEnd - rowStart);
        var relative = span.IndexOf(tag);
        if (relative < 0)
        {
            return string.Empty;
        }
        var at = checked(rowStart + relative + tag.Length);
        if (at + 8 > rowEnd)
        {
            return string.Empty;
        }
        var length = ReadUInt32(data, at + 4);
        if (length is 0 or > 64 || at + 8 + length > rowEnd)
        {
            return string.Empty;
        }
        var raw = data.AsSpan(at + 8, checked((int)length));
        var nul = raw.IndexOf((byte)0);
        return Encoding.ASCII.GetString(nul < 0 ? raw : raw[..nul]);
    }

    /// <summary>The row's own name field, which follows the repeated primary key.</summary>
    internal static string ReadItemInfoRowInternalName(byte[] data, int rowStart, int rowEnd, bool nameFirst = false)
    {
        if (rowStart + 8 > rowEnd)
        {
            return string.Empty;
        }
        var at = rowStart + (nameFirst ? 0 : 4);
        var length = ReadUInt32(data, at);
        if (length is 0 or > 256 || rowStart + 8 + length > rowEnd)
        {
            return string.Empty;
        }
        var raw = data.AsSpan(at + 4, checked((int)length));
        var nul = raw.IndexOf((byte)0);
        return Encoding.ASCII.GetString(nul < 0 ? raw : raw[..nul]);
    }

    /// <summary>
    /// Read item rows using the `.pabgh` row directory for exact boundaries. Recall is
    /// the row count, where the marker scan below recovers 4,142 of the 6,508 shipped rows.
    /// </summary>
    private static List<ItemRecord>? ParseItemInfoRows(
        byte[] data,
        byte[] header,
        IReadOnlyDictionary<uint, string> stringInfoHashes,
        CancellationToken cancellationToken)
    {
        var directory = ResolvePabghDirectory(header, data, TableKeyLayout.Named);
        if (directory is null)
        {
            return null;
        }
        var records = new List<ItemRecord>(directory.Count);
        var seenIds = new HashSet<uint>();
        for (var index = 0; index < directory.Count; index++)
        {
            if ((index & 0x3FF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
            }
            var rowStart = checked((int)directory[index].Offset);
            var rowEnd = index + 1 < directory.Count ? checked((int)directory[index + 1].Offset) : data.Length;
            if (rowStart >= rowEnd || rowEnd > data.Length)
            {
                continue;
            }
            var itemId = ReadUInt32(data, rowStart + directory[index].KeyOffset);
            if (!seenIds.Add(itemId))
            {
                continue;
            }
            var internalName = ReadItemInfoRowInternalName(data, rowStart, rowEnd, directory[index].KeyOffset != 0);
            var nameKey = ReadItemInfoSubRecordKey(data, rowStart, rowEnd, 0x70);
            var localizationIds = nameKey.Length == 0 ? new List<string>() : [nameKey];

            var prefabHashes = new List<uint>();
            var seenPrefabHashes = new HashSet<uint>();
            var hashScan = rowStart;
            while (hashScan + 15 < rowEnd && prefabHashes.Count < MaximumPrefabHashes)
            {
                if (data[hashScan] is not (0x0E or 0x0F or 0x10))
                {
                    hashScan++;
                    continue;
                }
                var firstCount = ReadUInt32(data, hashScan + 3);
                var secondCount = ReadUInt32(data, hashScan + 7);
                var listEnd = hashScan + 11L + secondCount * 4L;
                if (firstCount is not (> 0 and <= MaximumPrefabListCount) ||
                    secondCount is not (> 0 and <= MaximumPrefabListCount) || listEnd > rowEnd)
                {
                    hashScan++;
                    continue;
                }
                for (var hashIndex = 0; hashIndex < secondCount; hashIndex++)
                {
                    var value = ReadUInt32(data, checked(hashScan + 11 + (int)hashIndex * 4));
                    if (value != 0 && seenPrefabHashes.Add(value))
                    {
                        prefabHashes.Add(value);
                    }
                }
                hashScan = checked((int)listEnd);
            }

            var relatedModels = new List<string>();
            if (stringInfoHashes.Count > 0)
            {
                for (var scan = rowStart; scan + 4 <= rowEnd && relatedModels.Count < MaximumRelatedModelCandidates; scan++)
                {
                    var value = ReadUInt32(data, scan);
                    if (stringInfoHashes.TryGetValue(value, out var modelStem) &&
                        !relatedModels.Contains(modelStem, StringComparer.OrdinalIgnoreCase))
                    {
                        relatedModels.Add(modelStem);
                    }
                }
            }
            records.Add(new ItemRecord(localizationIds, internalName, prefabHashes, relatedModels));
        }
        return records;
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
            var nextRelative = data.AsSpan(searchStart).IndexOf(ItemInfoMarker);
            var nextPosition = nextRelative < 0 ? data.Length : searchStart + nextRelative;
            var localizationIds = LocalizationIdCandidates(data, position, nextPosition);

            var prefabHashes = new List<uint>();
            var seenPrefabHashes = new HashSet<uint>();
            var hashSearchEnd = Math.Min(nextPosition, position + PrefabScanBytes);
            var hashScan = position + ItemInfoMarker.Length;
            while (hashScan + 15 < hashSearchEnd && prefabHashes.Count < MaximumPrefabHashes)
            {
                if (data[hashScan] is not (0x0E or 0x0F or 0x10))
                {
                    hashScan++;
                    continue;
                }
                var firstCount = ReadUInt32(data, hashScan + 3);
                var secondCount = ReadUInt32(data, hashScan + 7);
                var listEnd = hashScan + 11L + secondCount * 4L;
                if (firstCount is not (> 0 and <= MaximumPrefabListCount) ||
                    secondCount is not (> 0 and <= MaximumPrefabListCount) || listEnd > hashSearchEnd)
                {
                    hashScan++;
                    continue;
                }
                for (var hashIndex = 0; hashIndex < secondCount; hashIndex++)
                {
                    var value = ReadUInt32(data, checked(hashScan + 11 + (int)hashIndex * 4));
                    if (value != 0 && seenPrefabHashes.Add(value))
                    {
                        prefabHashes.Add(value);
                    }
                }
                hashScan = checked((int)listEnd);
            }

            var relatedModels = new List<string>();
            if (stringInfoHashes.Count > 0)
            {
                var iconSearchEnd = Math.Min(data.Length, Math.Min(nextPosition, position + 2500));
                for (var scan = position; scan + 4 <= iconSearchEnd && relatedModels.Count < MaximumRelatedModelCandidates; scan++)
                {
                    var value = ReadUInt32(data, scan);
                    if (stringInfoHashes.TryGetValue(value, out var modelStem) &&
                        !relatedModels.Contains(modelStem, StringComparer.OrdinalIgnoreCase))
                    {
                        relatedModels.Add(modelStem);
                    }
                }
            }
            records.Add(new ItemRecord(localizationIds, internalName, prefabHashes, relatedModels));
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

    internal static Dictionary<string, string[]> ResolvePrefabModelPaths(
        ArchiveSession session,
        NativeArchiveCore native,
        IEnumerable<string> candidateStems,
        CancellationToken cancellationToken,
        Func<ProgressUpdate, Task>? progress,
        bool exactStems = false,
        ArchiveItemSources? sources = null)
    {
        var candidateKeys = candidateStems
            .Select(NormalizeModelStem)
            .Where(static value => value.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (candidateKeys.Length == 0) return new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase);

        var ownersByPrefabName = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
        foreach (var candidate in candidateKeys)
        {
            foreach (var prefabStem in exactStems ? new[] { candidate } : PrefabCandidateStems(candidate))
            {
                var basename = prefabStem + ".prefab";
                if (!ownersByPrefabName.TryGetValue(basename, out var owners))
                {
                    owners = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                    ownersByPrefabName[basename] = owners;
                }
                owners.Add(candidate);
            }
        }

        var matches = new List<(ArchiveEntryDto Entry, HashSet<string> Owners)>();
        var assets = new Dictionary<string, ArchiveEntryDto>(StringComparer.OrdinalIgnoreCase);
        var total = session.Index.EntryCount;
        Publish(progress, new ProgressUpdate(0, total, "names_prefab_scan"));
        for (long entryId = 0; entryId < total; entryId++)
        {
            if ((entryId & 0x1FFF) == 0)
            {
                cancellationToken.ThrowIfCancellationRequested();
                Publish(progress, new ProgressUpdate(entryId, total, "names_prefab_scan"));
            }
            var entry = session.Index.ReadEntry(entryId, session.Id);
            if (entry.Extension is ".pac" or ".pam" or ".pamlod" or ".prefab" or ".pami"
                && (sources is null || sources.Accepts(entry)))
            {
                var path = entry.Path.Replace('\\', '/');
                if (!assets.TryGetValue(path, out var previous)
                    || (sources is null ? ArchiveItemSources.Priority(entry).CompareTo(ArchiveItemSources.Priority(previous))
                                        : sources.Order(entry).CompareTo(sources.Order(previous))) > 0)
                    assets[path] = entry;
            }
            if (entry.Extension != ".prefab" || (sources is not null && !sources.Accepts(entry))) continue;
            var basename = Path.GetFileName(entry.Path);
            if (ownersByPrefabName.TryGetValue(basename, out var owners))
            {
                matches.Add((entry, owners));
            }
        }

        matches = matches.GroupBy(row => row.Entry.Path, StringComparer.OrdinalIgnoreCase)
            .Select(group => sources is null
                ? group.MaxBy(row => ArchiveItemSources.Priority(row.Entry))
                : group.MaxBy(row => sources.Order(row.Entry))).ToList();
        var resolved = candidateKeys.ToDictionary(
            static candidate => candidate,
            static _ => new HashSet<string>(StringComparer.OrdinalIgnoreCase),
            StringComparer.OrdinalIgnoreCase);
        var byName = assets.Values.GroupBy(static entry => entry.Name, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(static group => group.Key, static group => group.ToArray(), StringComparer.OrdinalIgnoreCase);
        var references = new Dictionary<long, string[]>();
        for (var index = 0; index < matches.Count; index++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if ((index & 0x3F) == 0)
            {
                Publish(progress, new ProgressUpdate(index, matches.Count, "names_prefab_decode"));
            }
            var (entry, owners) = matches[index];
            var modelPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var pending = new Queue<ArchiveEntryDto>();
            var visited = new HashSet<long>();
            pending.Enqueue(entry);
            while (pending.TryDequeue(out var dependency) && visited.Count < MaximumPrefabDependencyPaths)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (!visited.Add(dependency.EntryId)) continue;
                if (dependency.Extension is ".pac" or ".pam" or ".pamlod")
                {
                    modelPaths.Add(dependency.Path.Replace('\\', '/'));
                    continue;
                }
                if (dependency.OriginalSize is <= 0 or > MaximumPrefabSourceBytes) continue;
                if (!references.TryGetValue(dependency.EntryId, out var paths))
                {
                    try { paths = ExtractPrefabModelPaths(native.Decode(dependency).Bytes); }
                    catch (Exception exception) when (exception is IOException or InvalidDataException or NativeArchiveException or UnauthorizedAccessException)
                    { paths = []; }
                    references[dependency.EntryId] = paths;
                }
                foreach (var path in paths)
                {
                    if (assets.TryGetValue(path, out var target)) pending.Enqueue(target);
                    else if (byName.TryGetValue(Path.GetFileName(path), out var named) && named.Length == 1)
                        pending.Enqueue(named[0]);
                }
            }
            foreach (var owner in owners)
            {
                resolved[owner].UnionWith(modelPaths);
            }
        }
        Publish(progress, new ProgressUpdate(matches.Count, matches.Count, "names_prefab_decode"));
        return resolved.ToDictionary(
            static pair => pair.Key,
            static pair => pair.Value.OrderBy(static value => value, StringComparer.OrdinalIgnoreCase).ToArray(),
            StringComparer.OrdinalIgnoreCase);
    }

    private static IEnumerable<string> PrefabCandidateStems(string stem)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var modelStem in ModelCandidateBases(NormalizeModelStem(stem)))
        {
            if (seen.Add(modelStem)) yield return modelStem;
            if (!modelStem.EndsWith("_v", StringComparison.OrdinalIgnoreCase) && seen.Add(modelStem + "_v"))
            {
                yield return modelStem + "_v";
            }
        }
    }

    private static string[] ExtractPrefabModelPaths(byte[] bytes)
    {
        if (bytes.Length == 0) return [];
        var text = Encoding.UTF8.GetString(bytes);
        var paths = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (Match match in PrefabModelPathPattern.Matches(text))
        {
            var path = match.Groups["path"].Value.Replace('\\', '/').Trim();
            if (path.Length == 0 || !seen.Add(path)) continue;
            paths.Add(path);
            if (paths.Count >= MaximumPrefabDependencyPaths) break;
        }
        return [.. paths];
    }

    private static List<string> LocalizationIdCandidates(byte[] data, int markerOffset, int recordEnd)
    {
        var expected = markerOffset + 18;
        var scanStart = markerOffset + ItemInfoMarker.Length;
        var scanEnd = Math.Min(recordEnd, markerOffset + LocalizationScanBytes);
        var candidates = new List<string>();
        var seen = new HashSet<string>(StringComparer.Ordinal);

        void AddAt(int offset)
        {
            if (offset < scanStart || offset + 4 > scanEnd)
            {
                return;
            }
            var length = ReadUInt32(data, offset);
            if (length is not (> 5 and < 25) || length > int.MaxValue || offset + 4L + length > scanEnd)
            {
                return;
            }
            var value = data.AsSpan(offset + 4, (int)length);
            if (IsAsciiDigits(value))
            {
                var text = Encoding.ASCII.GetString(value);
                if (seen.Add(text))
                {
                    candidates.Add(text);
                }
            }
        }

        AddAt(expected);
        var maximumDistance = Math.Max(expected - scanStart, scanEnd - expected);
        for (var distance = 1; distance <= maximumDistance; distance++)
        {
            AddAt(expected - distance);
            AddAt(expected + distance);
        }
        return candidates;
    }

    private static string ResolveDisplayName(
        IReadOnlyList<string> localizationIds,
        IReadOnlyDictionary<string, Dictionary<string, string>> localized)
    {
        foreach (var localizationId in localizationIds)
        {
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
        }
        return string.Empty;
    }

    internal static void AddDisplayName(Dictionary<string, string> map, string key, string value)
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

    internal static string NormalizeModelStem(string value)
    {
        var basename = Path.GetFileName(value.Replace('\\', '/')).ToLowerInvariant();
        return Path.GetExtension(basename) is ".pac" or ".pam" or ".pamlod" or ".prefab" or ".pact"
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

    private static bool ItemModelReferenceIsCompatible(string internalName, string displayName, string modelStem)
    {
        var itemText = $"{internalName} {displayName}";
        if (CompatibleItemModelTokens.Any(pair =>
            itemText.Contains(pair.Internal, StringComparison.OrdinalIgnoreCase) &&
            modelStem.Contains(pair.Model, StringComparison.OrdinalIgnoreCase)))
        {
            return true;
        }
        var itemTokens = ItemModelSemanticTokens(itemText);
        var modelTokens = ItemModelSemanticTokens(modelStem);
        if (itemTokens.Overlaps(modelTokens))
        {
            return true;
        }
        return itemTokens.Any(itemToken => modelTokens.Any(modelToken =>
            Math.Min(itemToken.Length, modelToken.Length) >= 6 &&
            (itemToken.Contains(modelToken, StringComparison.Ordinal) ||
             modelToken.Contains(itemToken, StringComparison.Ordinal))));
    }

    private static HashSet<string> ItemModelSemanticTokens(string value)
    {
        var tokens = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var current = new StringBuilder();

        void Flush()
        {
            if (current.Length >= 4)
            {
                var token = current.ToString().ToLowerInvariant();
                if (!token.All(char.IsAsciiDigit) && !GenericItemModelTokens.Contains(token))
                {
                    tokens.Add(token);
                }
            }
            current.Clear();
        }

        char previous = '\0';
        foreach (var character in value)
        {
            if (!char.IsAsciiLetterOrDigit(character))
            {
                Flush();
                previous = '\0';
                continue;
            }
            if (current.Length > 0 && character >= 'A' && character <= 'Z' &&
                ((previous >= 'a' && previous <= 'z') || char.IsAsciiDigit(previous)))
            {
                Flush();
            }
            current.Append(char.ToLowerInvariant(character));
            previous = character;
        }
        Flush();
        return tokens;
    }

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

    internal static uint ModelNameHash(string stem) => HashLittle(Encoding.UTF8.GetBytes(stem), NameHashSeed);

    internal static uint HashLittle(ReadOnlySpan<byte> data, uint initialValue)
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

        /// <summary>The `.pabgh` companion that says where each `.pabgb` row starts and stops.</summary>
        public ArchiveEntryDto? ItemInfoHeader { get; set; }

        public ArchiveEntryDto? StringInfo { get; set; }
        public Dictionary<string, ArchiveEntryDto> Localization { get; } = new(StringComparer.OrdinalIgnoreCase);
    }

    private sealed class ItemRecord(
        List<string> localizationIds,
        string internalName,
        List<uint> prefabHashes,
        List<string> relatedModelStems)
    {
        public List<string> LocalizationIds { get; } = localizationIds;
        public string InternalName { get; } = internalName;
        public List<uint> PrefabHashes { get; } = prefabHashes;
        public List<string> RelatedModelStems { get; } = relatedModelStems;
        public string DisplayName { get; set; } = string.Empty;
    }
}

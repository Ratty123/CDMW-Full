using System.Buffers.Binary;
using System.Globalization;
using Cdmw.FullArchive.Contracts;

namespace Cdmw.FullArchive.Core;

internal sealed record CharacterNameLink(CharacterCatalogOwner Owner, string[] SearchNames);
internal sealed record CharacterUnresolvedNameLink(CharacterNameLink Link, int Variant, uint Hash, ArchiveEntryDto Table, long HeaderId);

internal static class ArchiveCharacterNames
{
    public static Dictionary<string, List<CharacterNameLink>> Read(
        ArchiveItemSources sources, IEnumerable<ArchiveEntryDto> appearances,
        Func<ArchiveEntryDto, byte[]> decode, List<string> warnings, List<CharacterUnresolvedNameLink> unresolved, CancellationToken token)
    {
        var owners = new Dictionary<string, List<CharacterNameLink>>(StringComparer.OrdinalIgnoreCase);
        try
        {
            var characters = sources.TablePair("characterinfo");
            var links = sources.TablePair("characterappearanceindexinfo");
            if (characters.Body is null || characters.Header is null || links.Body is null || links.Header is null)
            {
                warnings.Add("Character naming tables are incomplete or absent; internal appearance names remain searchable.");
                return owners;
            }
            var characterBytes = decode(characters.Body);
            var characterRows = ArchiveNameIndexBuilder.ResolvePabghDirectory(decode(characters.Header), characterBytes)
                ?? throw new InvalidDataException("CharacterInfo row directory is unsupported.");
            var names = new Dictionary<uint, (string Name, string NameKey)>();
            for (var i = 0; i < characterRows.Count; i++)
            {
                token.ThrowIfCancellationRequested();
                var row = characterRows[i];
                if (row.Key.Length != 4) continue;
                var id = BinaryPrimitives.ReadUInt32LittleEndian(row.Key);
                var start = checked((int)row.Offset);
                var end = i + 1 < characterRows.Count ? checked((int)characterRows[i + 1].Offset) : characterBytes.Length;
                var key = (((ulong)id << 32) | 0x30).ToString(CultureInfo.InvariantCulture);
                // CharacterInfo uses a 03/30 sub-record. Confirm the actual key bytes
                // inside this row before joining the localization namespace.
                var keyBytes = System.Text.Encoding.ASCII.GetBytes(key);
                if (characterBytes.AsSpan(start, end - start).IndexOf(keyBytes) < 0) key = "";
                names[id] = (ArchiveNameIndexBuilder.ReadItemInfoRowInternalName(characterBytes, start, end), key);
            }
            var wanted = names.Values.Select(static row => row.NameKey).Where(static value => value.Length > 0)
                .ToHashSet(StringComparer.Ordinal);
            var localized = new Dictionary<string, Dictionary<string, string>>(StringComparer.OrdinalIgnoreCase);
            foreach (var (language, entry) in sources.DomainLocalizations("character"))
            {
                token.ThrowIfCancellationRequested();
                localized[language] = ArchiveNameIndexBuilder.ParseLocalization(decode(entry), wanted, token);
            }
            var hashes = appearances.GroupBy(static entry => ArchiveNameIndexBuilder.ModelNameHash(entry.Path.ToLowerInvariant()))
                .ToDictionary(static group => group.Key, static group => group.ToArray());
            var linkBytes = decode(links.Body);
            var rows = ArchiveNameIndexBuilder.ResolvePabghDirectory(decode(links.Header), linkBytes)
                ?? throw new InvalidDataException("CharacterAppearanceIndexInfo row directory is unsupported.");
            var unmatched = 0;
            for (var i = 0; i < rows.Count; i++)
            {
                token.ThrowIfCancellationRequested();
                var row = rows[i];
                var start = checked((int)row.Offset);
                var end = i + 1 < rows.Count ? checked((int)rows[i + 1].Offset) : linkBytes.Length;
                if (row.Key.Length != 8) { unmatched++; continue; }
                var id = BinaryPrimitives.ReadUInt32LittleEndian(row.Key);
                // Verified installed layout: 8-byte (character ID, variant) key,
                // 29-byte record, full lower-case app path hash at +17 and repeated
                // character ID at +25. Never use basename hashes or guessed offsets.
                if (end - start != 29
                    || BinaryPrimitives.ReadUInt32LittleEndian(linkBytes.AsSpan(start + 25)) != id
                    || !names.TryGetValue(id, out var name)) { unmatched++; continue; }
                var hash = BinaryPrimitives.ReadUInt32LittleEndian(linkBytes.AsSpan(start + 17));
                var display = localized.GetValueOrDefault("eng")?.GetValueOrDefault(name.NameKey) ?? "";
                var evidence = $"CharacterAppearanceIndexInfo {id}/{BinaryPrimitives.ReadInt32LittleEndian(row.Key.AsSpan(4))}: full appearance path hash; CharacterInfo name field 0x30.";
                var link = new CharacterNameLink(new(id, name.Name, display, evidence),
                    localized.Values.Select(table => table.GetValueOrDefault(name.NameKey) ?? "")
                        .Append(name.Name).Append(id.ToString(CultureInfo.InvariantCulture))
                        .Where(static value => !string.IsNullOrWhiteSpace(value)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray());
                if (!hashes.TryGetValue(hash, out var matches) || matches.Length != 1)
                {
                    unmatched++;
                    var reason = $"CharacterAppearanceIndexInfo {id}/{BinaryPrimitives.ReadInt32LittleEndian(row.Key.AsSpan(4))}: appearance hash 0x{hash:x8} has no unique installed match. Character identity is known; appearance ownership is unresolved.";
                    unresolved.Add(new(link with { Owner = link.Owner with { Evidence = reason } },
                        BinaryPrimitives.ReadInt32LittleEndian(row.Key.AsSpan(4)), hash, links.Body, links.Header.EntryId));
                    continue;
                }
                var path = matches[0].Path.ToLowerInvariant();
                if (!owners.TryGetValue(path, out var list)) owners[path] = list = [];
                if (!list.Any(existing => existing.Owner.CharacterId == id)) list.Add(link);
            }
            if (unmatched > 0) warnings.Add($"{unmatched} character appearance link record(s) could not be resolved to one installed appearance; ownership was not guessed.");
        }
        catch (Exception error) when (error is InvalidDataException or IOException or ArgumentException or OverflowException)
        {
            warnings.Add($"Character names unavailable: {error.Message}");
        }
        return owners;
    }
}

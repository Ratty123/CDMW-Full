using System.Buffers.Binary;
using System.Text;
using System.Text.RegularExpressions;

namespace Cdmw.FullArchive.Core;

// Reads the models a binary character .prefab lists, each with its slot label
// (Upperbody, Lowerbody, Helm, Cloak, Foot, Hand, ...).
//
// Verified on the installed game (cd_nhm_so_ub_10335.prefab and others): strings
// are a u32 little-endian length followed by ASCII with no terminator. Each model
// is a record: label, flags, the model path, more fields, then the label again.
// The u32 after a path often has a printable low byte, so paths are read by their
// own length prefix, never by scanning for printable runs.
internal static class ArchivePrefabModels
{
    private const int MaximumModels = 64;
    private const int MaximumStringLength = 1024;
    private const int LabelWindow = 96;
    private static readonly string[] ModelExtensions = [".pac", ".pam", ".pamlod"];

    public static (string Slot, string ModelPath)[] Read(byte[] bytes)
    {
        var strings = Strings(bytes);
        var result = new List<(string, string)>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        for (var index = 0; index < strings.Count; index++)
        {
            var (start, value) = strings[index];
            if (!IsModelPath(value) || !seen.Add(value)) continue;
            result.Add((Label(strings, index, start, start + value.Length) ?? FolderSlot(value), value));
            if (result.Count >= MaximumModels) break;
        }
        return result.ToArray();
    }

    // Every u32-length-prefixed printable ASCII string, by the offset of its first character.
    internal static List<(int Start, string Value)> Strings(byte[] bytes)
    {
        var result = new List<(int, string)>();
        var index = 0;
        while (index + 4 < bytes.Length)
        {
            var length = BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(index));
            if (length is > 0 and <= MaximumStringLength && index + 4 + length <= bytes.Length
                && IsPrintable(bytes.AsSpan(index + 4, (int)length)))
            {
                result.Add((index + 4, Encoding.ASCII.GetString(bytes, index + 4, (int)length)));
                index += 4 + (int)length;
                continue;
            }
            index++;
        }
        return result;
    }

    // The nearest label-like string before the path, else the nearest after it.
    private static string? Label(List<(int Start, string Value)> strings, int index, int start, int end)
    {
        for (var before = index - 1; before >= 0; before--)
        {
            var (offset, value) = strings[before];
            if (start - (offset + value.Length) > LabelWindow) break;
            if (IsModelPath(value)) break;
            if (IsLabel(value)) return value;
        }
        for (var after = index + 1; after < strings.Count; after++)
        {
            var (offset, value) = strings[after];
            if (offset - end > LabelWindow) break;
            if (IsModelPath(value)) break;
            if (IsLabel(value)) return value;
        }
        return null;
    }

    private static bool IsPrintable(ReadOnlySpan<byte> value)
    {
        foreach (var character in value)
            if (character is < 0x20 or > 0x7E) return false;
        return true;
    }

    internal static bool IsModelPath(string value) =>
        value.Contains('/') && ModelExtensions.Any(extension => value.EndsWith(extension, StringComparison.OrdinalIgnoreCase));

    internal static bool IsLabel(string value) =>
        value.Length is > 0 and <= 64 && char.IsAsciiLetter(value[0])
        && value.All(static character => char.IsAsciiLetterOrDigit(character) || character == '_');

    internal static string FolderSlot(string path)
    {
        foreach (var part in ArchiveCharacterReferences.Normalize(path).Split('/').Reverse())
        {
            var match = Regex.Match(part, @"^\d+_(?<name>[a-z]+)$");
            if (!match.Success) continue;
            var slot = match.Groups["name"].Value switch
            {
                "upperbody" => "Upperbody",
                "lowerbody" => "Lowerbody",
                "hand" => "Hand",
                "foot" => "Foot",
                "hel" or "helm" => "Helm",
                "cloak" => "Cloak",
                _ => null,
            };
            if (slot is not null) return slot;
        }
        return "Unknown";
    }
}

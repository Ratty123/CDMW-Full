using System.Buffers.Binary;
using System.Globalization;
using System.Text;

namespace Cdmw.Archive.Content;

internal sealed record ExtractedString(string Value, int Offset, string Encoding);

internal static class ArchiveContentBinary
{
    private const int MaximumStrings = 512;
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);

    public static IReadOnlyList<ExtractedString> ExtractStrings(ReadOnlySpan<byte> data, int minimumLength = 4)
    {
        var values = new List<ExtractedString>();
        ExtractAscii(data, minimumLength, values);
        if (values.Count < MaximumStrings)
        {
            ExtractUtf16(data, minimumLength, values);
        }
        return values
            .OrderBy(value => value.Offset)
            .ThenBy(value => value.Encoding, StringComparer.Ordinal)
            .Take(MaximumStrings)
            .ToArray();
    }

    public static IReadOnlyList<ArchiveContentReference> ExtractReferences(
        IEnumerable<ExtractedString> strings)
    {
        var references = new List<ArchiveContentReference>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var item in strings)
        {
            foreach (var token in Tokenize(item.Value))
            {
                var normalized = token.Trim('"', '\'', '(', ')', '[', ']', '{', '}', ',', ';');
                if (normalized.Length < 5 || !LooksLikeReference(normalized) || !seen.Add(normalized))
                {
                    continue;
                }
                references.Add(new ArchiveContentReference(
                    normalized.Replace('\\', '/'),
                    "asset_path",
                    "heuristic",
                    item.Offset,
                    $"{item.Encoding} printable string"));
                if (references.Count >= 256) return references;
            }
        }
        return references;
    }

    public static string HeaderHex(ReadOnlySpan<byte> data, int maximumBytes = 64) =>
        Convert.ToHexString(data[..Math.Min(data.Length, maximumBytes)]).ToLowerInvariant();

    public static string HeaderAscii(ReadOnlySpan<byte> data, int maximumBytes = 16)
    {
        var length = Math.Min(data.Length, maximumBytes);
        var chars = new char[length];
        for (var index = 0; index < length; index++)
        {
            var value = data[index];
            chars[index] = value is >= 32 and <= 126 ? (char)value : '.';
        }
        return new string(chars);
    }

    public static string DecodeText(ReadOnlySpan<byte> data, out string encoding)
    {
        if (data.StartsWith(new byte[] { 0xEF, 0xBB, 0xBF }))
        {
            encoding = "UTF-8 BOM";
            return Encoding.UTF8.GetString(data[3..]);
        }
        if (data.StartsWith(new byte[] { 0xFF, 0xFE }))
        {
            encoding = "UTF-16 LE";
            return Encoding.Unicode.GetString(data[2..]);
        }
        if (data.StartsWith(new byte[] { 0xFE, 0xFF }))
        {
            encoding = "UTF-16 BE";
            return Encoding.BigEndianUnicode.GetString(data[2..]);
        }
        try
        {
            encoding = "UTF-8";
            return StrictUtf8.GetString(data);
        }
        catch (DecoderFallbackException)
        {
            encoding = "Windows-1252 compatible";
            return Encoding.Latin1.GetString(data);
        }
    }

    public static uint ReadUInt32(ReadOnlySpan<byte> data, int offset)
    {
        Require(data, offset, sizeof(uint));
        return BinaryPrimitives.ReadUInt32LittleEndian(data[offset..]);
    }

    public static ushort ReadUInt16(ReadOnlySpan<byte> data, int offset)
    {
        Require(data, offset, sizeof(ushort));
        return BinaryPrimitives.ReadUInt16LittleEndian(data[offset..]);
    }

    public static float ReadSingle(ReadOnlySpan<byte> data, int offset)
    {
        var bits = ReadUInt32(data, offset);
        return BitConverter.Int32BitsToSingle(unchecked((int)bits));
    }

    public static string FormatSingle(float value) =>
        value.ToString("0.######", CultureInfo.InvariantCulture);

    public static ArchiveContentSection BuildStringSection(IReadOnlyList<ExtractedString> strings)
    {
        var lines = strings.Take(160)
            .Select(value => $"0x{value.Offset:X8} [{value.Encoding}] {value.Value}")
            .ToArray();
        return new ArchiveContentSection(
            $"Printable strings ({strings.Count:N0})",
            Array.Empty<ArchiveContentField>(),
            lines);
    }

    private static void ExtractAscii(
        ReadOnlySpan<byte> data,
        int minimumLength,
        ICollection<ExtractedString> output)
    {
        var start = -1;
        for (var index = 0; index <= data.Length; index++)
        {
            var printable = index < data.Length && data[index] is >= 32 and <= 126;
            if (printable && start < 0) start = index;
            if (printable || start < 0) continue;
            if (index - start >= minimumLength)
            {
                output.Add(new ExtractedString(Encoding.ASCII.GetString(data[start..index]), start, "ASCII"));
                if (output.Count >= MaximumStrings) return;
            }
            start = -1;
        }
    }

    private static void ExtractUtf16(
        ReadOnlySpan<byte> data,
        int minimumLength,
        ICollection<ExtractedString> output)
    {
        for (var parity = 0; parity < 2; parity++)
        {
            var start = -1;
            for (var index = parity; index + 1 <= data.Length; index += 2)
            {
                var printable = index + 1 < data.Length && data[index] is >= 32 and <= 126 && data[index + 1] == 0;
                if (printable && start < 0) start = index;
                if (printable) continue;
                if (start >= 0 && (index - start) / 2 >= minimumLength)
                {
                    output.Add(new ExtractedString(Encoding.Unicode.GetString(data[start..index]), start, "UTF-16 LE"));
                    if (output.Count >= MaximumStrings) return;
                }
                start = -1;
            }
        }
    }

    private static IEnumerable<string> Tokenize(string value) =>
        value.Split([' ', '\t', '\r', '\n', '|'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    private static bool LooksLikeReference(string value)
    {
        var dot = value.LastIndexOf('.');
        if (dot <= 0 || dot == value.Length - 1) return false;
        var suffix = value[dot..];
        if (ArchiveContentRegistry.Find(suffix) is not null) return true;
        return value.Contains('/') || value.Contains('\\');
    }

    private static void Require(ReadOnlySpan<byte> data, int offset, int size)
    {
        if (offset < 0 || size < 0 || offset > data.Length - size)
        {
            throw new InvalidDataException($"Read at 0x{offset:X} exceeds the analyzed payload ({data.Length:N0} bytes)." );
        }
    }
}

using System.Text;

namespace Cdmw.FullArchive.Core;

public static class TextDecoding
{
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);
    private static readonly byte[] Utf8Bom = [0xEF, 0xBB, 0xBF];
    private static readonly byte[] Utf16LittleEndianBom = [0xFF, 0xFE];
    private static readonly byte[] Utf16BigEndianBom = [0xFE, 0xFF];
    private static readonly byte[] Utf32LittleEndianBom = [0xFF, 0xFE, 0x00, 0x00];
    private static readonly byte[] Utf32BigEndianBom = [0x00, 0x00, 0xFE, 0xFF];

    public static string Decode(byte[] bytes)
    {
        ArgumentNullException.ThrowIfNull(bytes);
        if (bytes.AsSpan().StartsWith(Utf8Bom)) return Encoding.UTF8.GetString(bytes, 3, bytes.Length - 3);
        if (bytes.AsSpan().StartsWith(Utf32LittleEndianBom)) return Encoding.UTF32.GetString(bytes, 4, bytes.Length - 4);
        if (bytes.AsSpan().StartsWith(Utf32BigEndianBom)) return new UTF32Encoding(true, true).GetString(bytes, 4, bytes.Length - 4);
        if (bytes.AsSpan().StartsWith(Utf16LittleEndianBom)) return Encoding.Unicode.GetString(bytes, 2, bytes.Length - 2);
        if (bytes.AsSpan().StartsWith(Utf16BigEndianBom)) return Encoding.BigEndianUnicode.GetString(bytes, 2, bytes.Length - 2);

        var inferred = InferUtf16(bytes);
        if (inferred is not null) return inferred.GetString(bytes);
        try
        {
            return StrictUtf8.GetString(bytes);
        }
        catch (DecoderFallbackException)
        {
            return Encoding.Latin1.GetString(bytes);
        }
    }

    public static bool LooksTextual(byte[] bytes)
    {
        ArgumentNullException.ThrowIfNull(bytes);
        if (bytes.Length == 0) return true;
        if (HasTextBom(bytes) || InferUtf16(bytes) is not null) return true;
        var sampleLength = Math.Min(bytes.Length, 4096);
        var printable = 0;
        for (var index = 0; index < sampleLength; index++)
        {
            var value = bytes[index];
            if (value == 0) return false;
            if (value is 9 or 10 or 13 || value >= 0x20) printable++;
        }
        return printable >= sampleLength * 0.85;
    }

    private static bool HasTextBom(byte[] bytes) =>
        bytes.AsSpan().StartsWith(Utf8Bom) ||
        bytes.AsSpan().StartsWith(Utf16LittleEndianBom) ||
        bytes.AsSpan().StartsWith(Utf16BigEndianBom) ||
        bytes.AsSpan().StartsWith(Utf32BigEndianBom);

    private static Encoding? InferUtf16(byte[] bytes)
    {
        var sampleLength = Math.Min(bytes.Length - bytes.Length % 2, 4096);
        if (sampleLength < 8) return null;
        var evenNuls = 0;
        var oddNuls = 0;
        for (var index = 0; index < sampleLength; index += 2)
        {
            if (bytes[index] == 0) evenNuls++;
            if (bytes[index + 1] == 0) oddNuls++;
        }
        var pairs = sampleLength / 2;
        if (oddNuls >= pairs * 0.3 && evenNuls <= pairs * 0.05) return Encoding.Unicode;
        if (evenNuls >= pairs * 0.3 && oddNuls <= pairs * 0.05) return Encoding.BigEndianUnicode;
        return null;
    }
}

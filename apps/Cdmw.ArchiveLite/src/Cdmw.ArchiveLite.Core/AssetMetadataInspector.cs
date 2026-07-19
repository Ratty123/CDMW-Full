using System.Buffers.Binary;
using System.Text;

namespace Cdmw.ArchiveLite.Core;

public static class AssetMetadataInspector
{
    private static readonly byte[] PngSignature = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];

    public static string Enrich(string archiveMetadata, string extension, ReadOnlySpan<byte> bytes)
    {
        var details = Describe(extension, bytes);
        return string.IsNullOrWhiteSpace(details)
            ? archiveMetadata
            : string.Join(Environment.NewLine, archiveMetadata, string.Empty, details);
    }

    public static string Describe(string extension, ReadOnlySpan<byte> bytes)
    {
        var normalized = (extension ?? string.Empty).Trim().ToLowerInvariant();
        return normalized switch
        {
            ".dds" => DescribeDds(bytes),
            ".png" => DescribePng(bytes),
            ".tga" => DescribeTga(bytes),
            ".wav" or ".wem" => DescribeRiffWave(bytes),
            ".ogg" => DescribeOgg(bytes),
            ".hkx" or ".hkt" => DescribeHkx(bytes),
            _ => string.Empty,
        };
    }

    private static string DescribeDds(ReadOnlySpan<byte> bytes)
    {
        if (bytes.Length < 128 || !bytes[..4].SequenceEqual("DDS "u8) || ReadU32(bytes, 4) != 124)
        {
            return string.Empty;
        }

        var height = ReadU32(bytes, 12);
        var width = ReadU32(bytes, 16);
        var pitchOrLinearSize = ReadU32(bytes, 20);
        var depth = Math.Max(1u, ReadU32(bytes, 24));
        var mipCount = Math.Max(1u, ReadU32(bytes, 28));
        var pixelFlags = ReadU32(bytes, 80);
        var fourCc = FourCc(ReadU32(bytes, 84));
        var rgbBits = ReadU32(bytes, 88);
        var caps2 = ReadU32(bytes, 112);
        var isDx10 = fourCc == "DX10" && bytes.Length >= 148;
        var dxgi = isDx10 ? ReadU32(bytes, 128) : 0;
        var resourceDimension = isDx10 ? ReadU32(bytes, 132) : 3;
        var miscFlag = isDx10 ? ReadU32(bytes, 136) : 0;
        var arraySize = isDx10 ? Math.Max(1u, ReadU32(bytes, 140)) : 1;
        var alphaMode = isDx10 ? ReadU32(bytes, 144) & 0x7 : 0;
        var format = isDx10 ? DxgiFormatName(dxgi) : LegacyDdsFormat(fourCc, pixelFlags, rgbBits);
        var isCube = (isDx10 && (miscFlag & 0x4) != 0) || (caps2 & 0x200) != 0;
        var textureKind = isCube
            ? arraySize > 1 ? $"cube array ({arraySize} cube(s))" : "cube map"
            : resourceDimension switch
            {
                2 => arraySize > 1 ? $"1D array ({arraySize} slices)" : "1D texture",
                4 => "3D volume",
                _ => arraySize > 1 ? $"2D array ({arraySize} slices)" : "2D texture",
            };
        var compression = CompressionName(format);
        var colorSpace = format.Contains("SRGB", StringComparison.OrdinalIgnoreCase) ? "sRGB" : "linear / unspecified";
        var blockBytes = BlockByteSize(format);
        var dataOffset = isDx10 ? 148 : 128;
        var payloadBytes = Math.Max(0, bytes.Length - dataOffset);

        var lines = new List<string>
        {
            "Format details: DirectDraw Surface (DDS)",
            $"Dimensions: {width:N0} × {height:N0}" + (resourceDimension == 4 ? $" × {depth:N0}" : string.Empty),
            $"Texture kind: {textureKind}",
            $"Pixel format: {format}",
            $"Compression: {compression}",
            $"Mip levels: {mipCount:N0}",
            $"Color space: {colorSpace}",
            $"Pixel payload: {payloadBytes:N0} bytes (starts at byte {dataOffset})",
        };
        if (pitchOrLinearSize > 0)
        {
            lines.Add($"Declared pitch / top-level size: {pitchOrLinearSize:N0} bytes");
        }
        if (blockBytes > 0)
        {
            lines.Add($"Compression block: 4 × 4 pixels, {blockBytes} bytes");
        }
        if (isDx10)
        {
            lines.Add($"DX10 header: DXGI {dxgi}, alpha {AlphaModeName(alphaMode)}");
        }
        else if ((pixelFlags & 0x40) != 0)
        {
            lines.Add($"RGB masks: R=0x{ReadU32(bytes, 92):X8}, G=0x{ReadU32(bytes, 96):X8}, B=0x{ReadU32(bytes, 100):X8}, A=0x{ReadU32(bytes, 104):X8}");
        }
        return string.Join(Environment.NewLine, lines);
    }

    private static string DescribePng(ReadOnlySpan<byte> bytes)
    {
        if (bytes.Length < 29 || !bytes[..8].SequenceEqual(PngSignature))
        {
            return string.Empty;
        }
        var width = BinaryPrimitives.ReadUInt32BigEndian(bytes[16..20]);
        var height = BinaryPrimitives.ReadUInt32BigEndian(bytes[20..24]);
        var bitDepth = bytes[24];
        var colorType = bytes[25] switch
        {
            0 => "grayscale",
            2 => "RGB",
            3 => "indexed color",
            4 => "grayscale + alpha",
            6 => "RGBA",
            _ => $"unknown ({bytes[25]})",
        };
        return string.Join(Environment.NewLine,
            "Format details: Portable Network Graphics (PNG)",
            $"Dimensions: {width:N0} × {height:N0}",
            $"Color: {colorType}, {bitDepth}-bit samples",
            $"Interlaced: {(bytes[28] == 1 ? "yes (Adam7)" : "no")}");
    }

    private static string DescribeTga(ReadOnlySpan<byte> bytes)
    {
        if (bytes.Length < 18)
        {
            return string.Empty;
        }
        var imageType = bytes[2];
        var width = BinaryPrimitives.ReadUInt16LittleEndian(bytes[12..14]);
        var height = BinaryPrimitives.ReadUInt16LittleEndian(bytes[14..16]);
        if (width == 0 || height == 0 || imageType is not (1 or 2 or 3 or 9 or 10 or 11))
        {
            return string.Empty;
        }
        var typeName = imageType switch
        {
            1 => "color-mapped",
            2 => "true-color",
            3 => "grayscale",
            9 => "RLE color-mapped",
            10 => "RLE true-color",
            11 => "RLE grayscale",
            _ => "unknown",
        };
        return string.Join(Environment.NewLine,
            "Format details: Truevision TGA",
            $"Dimensions: {width:N0} × {height:N0}",
            $"Encoding: {typeName}",
            $"Pixel depth: {bytes[16]} bits",
            $"Origin: {((bytes[17] & 0x20) != 0 ? "top-left" : "bottom-left")}");
    }

    private static string DescribeRiffWave(ReadOnlySpan<byte> bytes)
    {
        if (bytes.Length < 12 || !bytes[..4].SequenceEqual("RIFF"u8) || !bytes[8..12].SequenceEqual("WAVE"u8))
        {
            return string.Empty;
        }
        ushort format = 0;
        ushort channels = 0;
        uint sampleRate = 0;
        uint averageBytes = 0;
        ushort bits = 0;
        uint dataSize = 0;
        for (var offset = 12; offset + 8 <= bytes.Length;)
        {
            var chunkSize = ReadU32(bytes, offset + 4);
            var content = offset + 8;
            if (bytes.Slice(offset, 4).SequenceEqual("fmt "u8) && chunkSize >= 16 && content + 16 <= bytes.Length)
            {
                format = BinaryPrimitives.ReadUInt16LittleEndian(bytes.Slice(content, 2));
                channels = BinaryPrimitives.ReadUInt16LittleEndian(bytes.Slice(content + 2, 2));
                sampleRate = ReadU32(bytes, content + 4);
                averageBytes = ReadU32(bytes, content + 8);
                bits = BinaryPrimitives.ReadUInt16LittleEndian(bytes.Slice(content + 14, 2));
            }
            else if (bytes.Slice(offset, 4).SequenceEqual("data"u8))
            {
                dataSize = chunkSize;
            }
            var advance = 8L + chunkSize + (chunkSize & 1);
            if (advance <= 0 || offset + advance > bytes.Length)
            {
                break;
            }
            offset += (int)advance;
        }
        var duration = averageBytes > 0 ? TimeSpan.FromSeconds((double)dataSize / averageBytes) : TimeSpan.Zero;
        var codec = format switch
        {
            1 => "PCM",
            2 => "Microsoft ADPCM",
            3 => "IEEE float",
            0x11 => "IMA ADPCM",
            0xFFFF => "Wwise / Vorbis",
            _ => $"format 0x{format:X4}",
        };
        var lines = new List<string>
        {
            "Format details: RIFF / WAVE",
            $"Codec: {codec}",
            $"Channels: {channels:N0}",
            $"Sample rate: {sampleRate:N0} Hz",
        };
        if (bits > 0) lines.Add($"Bit depth: {bits} bits");
        if (duration > TimeSpan.Zero) lines.Add($"Duration: {duration.ToString(@"hh\:mm\:ss\.fff")}");
        return string.Join(Environment.NewLine, lines);
    }

    private static string DescribeOgg(ReadOnlySpan<byte> bytes)
    {
        if (bytes.Length < 32 || !bytes[..4].SequenceEqual("OggS"u8))
        {
            return string.Empty;
        }
        var probe = Encoding.ASCII.GetString(bytes[..Math.Min(bytes.Length, 256)]);
        var codec = probe.Contains("OpusHead", StringComparison.Ordinal) ? "Opus"
            : probe.Contains("vorbis", StringComparison.OrdinalIgnoreCase) ? "Vorbis"
            : "unknown Ogg codec";
        return string.Join(Environment.NewLine,
            "Format details: Ogg container",
            $"Codec: {codec}",
            $"Stream serial: 0x{ReadU32(bytes, 14):X8}");
    }

    private static string DescribeHkx(ReadOnlySpan<byte> bytes)
    {
        if (bytes.Length < 16)
        {
            return string.Empty;
        }
        var tag0 = bytes.IndexOf("TAG0"u8);
        var sdkv = bytes.IndexOf("SDKV"u8);
        if (tag0 < 0 && sdkv < 0)
        {
            return string.Empty;
        }
        var sdk = "unknown";
        if (sdkv >= 0)
        {
            var start = sdkv + 4;
            var length = 0;
            while (start + length < bytes.Length && length < 32 && bytes[start + length] is >= (byte)'0' and <= (byte)'9') length++;
            if (length > 0) sdk = Encoding.ASCII.GetString(bytes.Slice(start, length));
        }
        var sections = new List<string>();
        foreach (var marker in new[] { "DATA", "TYPE", "TST1", "TNA1", "ITEM", "PTCH", "INDX" })
        {
            if (bytes.IndexOf(Encoding.ASCII.GetBytes(marker)) >= 0) sections.Add(marker);
        }
        return string.Join(Environment.NewLine,
            "Format details: Havok tagfile (HKX)",
            $"SDK version: {sdk}",
            $"Tagfile marker: {(tag0 >= 0 ? $"byte {tag0:N0}" : "not found")}",
            $"Sections: {(sections.Count > 0 ? string.Join(", ", sections) : "not identified")}");
    }

    private static uint ReadU32(ReadOnlySpan<byte> bytes, int offset) =>
        offset >= 0 && offset + 4 <= bytes.Length
            ? BinaryPrimitives.ReadUInt32LittleEndian(bytes.Slice(offset, 4))
            : 0;

    private static string FourCc(uint value) => new([
        (char)(value & 0xFF),
        (char)((value >> 8) & 0xFF),
        (char)((value >> 16) & 0xFF),
        (char)((value >> 24) & 0xFF),
    ]);

    private static string LegacyDdsFormat(string fourCc, uint flags, uint bits)
    {
        var cleaned = new string(fourCc.Where(character => character is >= ' ' and <= '~').ToArray()).Trim();
        if (!string.IsNullOrWhiteSpace(cleaned) && cleaned != "\0\0\0\0") return cleaned;
        if ((flags & 0x40) != 0) return (flags & 0x1) != 0 ? $"RGBA{bits}" : $"RGB{bits}";
        if ((flags & 0x2) != 0) return $"Luminance {bits}-bit";
        return "legacy / unknown";
    }

    private static string DxgiFormatName(uint format) => format switch
    {
        28 => "R8G8B8A8_UNORM",
        29 => "R8G8B8A8_UNORM_SRGB",
        71 => "BC1_UNORM",
        72 => "BC1_UNORM_SRGB",
        74 => "BC2_UNORM",
        75 => "BC2_UNORM_SRGB",
        77 => "BC3_UNORM",
        78 => "BC3_UNORM_SRGB",
        80 => "BC4_UNORM",
        81 => "BC4_SNORM",
        83 => "BC5_UNORM",
        84 => "BC5_SNORM",
        87 => "B8G8R8A8_UNORM",
        91 => "B8G8R8A8_UNORM_SRGB",
        95 => "BC6H_UF16",
        96 => "BC6H_SF16",
        98 => "BC7_UNORM",
        99 => "BC7_UNORM_SRGB",
        _ => $"DXGI_FORMAT_{format}",
    };

    private static string CompressionName(string format)
    {
        if (format.StartsWith("BC1", StringComparison.OrdinalIgnoreCase) || format == "DXT1") return "BC1 / DXT1";
        if (format.StartsWith("BC2", StringComparison.OrdinalIgnoreCase) || format == "DXT3") return "BC2 / DXT3";
        if (format.StartsWith("BC3", StringComparison.OrdinalIgnoreCase) || format == "DXT5") return "BC3 / DXT5";
        if (format.StartsWith("BC4", StringComparison.OrdinalIgnoreCase) || format is "ATI1" or "BC4U" or "BC4S") return "BC4";
        if (format.StartsWith("BC5", StringComparison.OrdinalIgnoreCase) || format is "ATI2" or "BC5U" or "BC5S") return "BC5";
        if (format.StartsWith("BC6", StringComparison.OrdinalIgnoreCase)) return "BC6H";
        if (format.StartsWith("BC7", StringComparison.OrdinalIgnoreCase)) return "BC7";
        return "uncompressed / format-defined";
    }

    private static int BlockByteSize(string format) =>
        format.StartsWith("BC1", StringComparison.OrdinalIgnoreCase) || format.StartsWith("BC4", StringComparison.OrdinalIgnoreCase) || format is "DXT1" or "ATI1" or "BC4U" or "BC4S"
            ? 8
            : format.StartsWith("BC", StringComparison.OrdinalIgnoreCase) || format is "DXT3" or "DXT5" or "ATI2" or "BC5U" or "BC5S"
                ? 16
                : 0;

    private static string AlphaModeName(uint mode) => mode switch
    {
        1 => "straight",
        2 => "premultiplied",
        3 => "opaque",
        4 => "custom",
        _ => "unknown",
    };
}

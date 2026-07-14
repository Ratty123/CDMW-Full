namespace Cdmw.MeshEditorExperiment;

internal sealed partial class NetTextureSet
{
    private const uint DdsCaps2Cubemap = 0x00000200;
    private const uint DdsCaps2Volume = 0x00200000;
    private const int D3D10ResourceDimensionTexture2D = 3;
    private const uint D3D11ResourceMiscTextureCube = 0x4;

    private static (NetDdsNativeTextureData? Data, string FormatKey, bool SourceSrgb, string FallbackReason)
        BuildNativeDdsTextureData(
            int width,
            int height,
            int mipCount,
            string legacyFourCc,
            int dxgiFormat,
            int rgbBitCount,
            uint rMask,
            uint gMask,
            uint bMask,
            uint aMask,
            uint caps2,
            int resourceDimension,
            uint miscFlag,
            int arraySize,
            byte[] data)
    {
        if (width <= 0 || height <= 0 || width > 32768 || height > 32768)
        {
            return (null, string.Empty, false, "invalid_dimensions");
        }
        var maximumMipCount = 1 + (int)Math.Floor(Math.Log2(Math.Max(width, height)));
        if (mipCount <= 0 || mipCount > maximumMipCount)
        {
            return (null, string.Empty, false, "invalid_mip_count");
        }
        if ((caps2 & (DdsCaps2Cubemap | DdsCaps2Volume)) != 0)
        {
            return (null, string.Empty, false, "non_2d_legacy_dds");
        }
        if (dxgiFormat != 0
            && (resourceDimension != D3D10ResourceDimensionTexture2D
                || arraySize != 1
                || (miscFlag & D3D11ResourceMiscTextureCube) != 0))
        {
            return (null, string.Empty, false, "non_2d_or_array_dx10_dds");
        }

        var (formatKey, bytesPerPixel, blockBytes, sourceSrgb) = NativeDdsFormat(
            legacyFourCc,
            dxgiFormat,
            rgbBitCount,
            rMask,
            gMask,
            bMask,
            aMask);
        if (string.IsNullOrWhiteSpace(formatKey))
        {
            return (null, string.Empty, sourceSrgb, "unsupported_native_dxgi_format");
        }

        var subresources = new List<NetDdsSubresource>(mipCount);
        long offset = 0;
        var mipWidth = width;
        var mipHeight = height;
        for (var mip = 0; mip < mipCount; mip++)
        {
            long rowPitch;
            long slicePitch;
            if (blockBytes > 0)
            {
                rowPitch = Math.Max(1, (mipWidth + 3) / 4) * blockBytes;
                slicePitch = rowPitch * Math.Max(1, (mipHeight + 3) / 4);
            }
            else
            {
                rowPitch = checked((long)mipWidth * bytesPerPixel);
                slicePitch = checked(rowPitch * mipHeight);
            }
            if (rowPitch <= 0 || slicePitch <= 0 || rowPitch > uint.MaxValue || slicePitch > uint.MaxValue)
            {
                return (null, formatKey, sourceSrgb, "native_subresource_size_overflow");
            }
            if (offset + slicePitch > data.LongLength || offset > int.MaxValue)
            {
                return (null, formatKey, sourceSrgb, "truncated_mip_chain");
            }
            subresources.Add(new NetDdsSubresource(
                (int)offset,
                (int)rowPitch,
                (int)slicePitch,
                mipWidth,
                mipHeight));
            offset += slicePitch;
            mipWidth = Math.Max(1, mipWidth / 2);
            mipHeight = Math.Max(1, mipHeight / 2);
        }
        if (offset <= 0 || offset > int.MaxValue)
        {
            return (null, formatKey, sourceSrgb, "native_payload_size_overflow");
        }
        var nativeBytes = data.AsSpan(0, (int)offset).ToArray();
        return (
            new NetDdsNativeTextureData(
                width,
                height,
                mipCount,
                formatKey,
                sourceSrgb,
                nativeBytes,
                subresources),
            formatKey,
            sourceSrgb,
            string.Empty);
    }

    private static (string FormatKey, int BytesPerPixel, int BlockBytes, bool SourceSrgb) NativeDdsFormat(
        string legacyFourCc,
        int dxgiFormat,
        int rgbBitCount,
        uint rMask,
        uint gMask,
        uint bMask,
        uint aMask)
    {
        if (dxgiFormat != 0)
        {
            return dxgiFormat switch
            {
                10 => ("RGBA16_FLOAT", 8, 0, false),
                28 => ("RGBA8", 4, 0, false),
                29 => ("RGBA8", 4, 0, true),
                49 => ("RG8", 2, 0, false),
                56 => ("R16", 2, 0, false),
                61 => ("R8", 1, 0, false),
                70 or 71 => ("BC1", 0, 8, false),
                72 => ("BC1", 0, 8, true),
                73 or 74 => ("BC2", 0, 16, false),
                75 => ("BC2", 0, 16, true),
                76 or 77 => ("BC3", 0, 16, false),
                78 => ("BC3", 0, 16, true),
                79 or 80 => ("BC4_UNORM", 0, 8, false),
                81 => ("BC4_SNORM", 0, 8, false),
                82 or 83 => ("BC5_UNORM", 0, 16, false),
                84 => ("BC5_SNORM", 0, 16, false),
                87 => ("BGRA8", 4, 0, false),
                88 => ("BGRX8", 4, 0, false),
                91 => ("BGRA8", 4, 0, true),
                93 => ("BGRX8", 4, 0, true),
                94 or 95 => ("BC6H_UF16", 0, 16, false),
                96 => ("BC6H_SF16", 0, 16, false),
                97 or 98 => ("BC7", 0, 16, false),
                99 => ("BC7", 0, 16, true),
                _ => (string.Empty, 0, 0, false),
            };
        }

        var fourCc = (legacyFourCc ?? string.Empty).Trim().ToUpperInvariant();
        var compressed = fourCc switch
        {
            "DXT1" => ("BC1", 8),
            "DXT3" => ("BC2", 16),
            "DXT5" => ("BC3", 16),
            "ATI1" or "BC4U" => ("BC4_UNORM", 8),
            "BC4S" => ("BC4_SNORM", 8),
            "ATI2" or "BC5U" => ("BC5_UNORM", 16),
            "BC5S" => ("BC5_SNORM", 16),
            _ => (string.Empty, 0),
        };
        if (!string.IsNullOrWhiteSpace(compressed.Item1))
        {
            return (compressed.Item1, 0, compressed.Item2, false);
        }
        if (rgbBitCount == 32)
        {
            if (rMask == 0x00FF0000 && gMask == 0x0000FF00 && bMask == 0x000000FF
                && aMask is 0xFF000000 or 0)
            {
                return (aMask == 0 ? "BGRX8" : "BGRA8", 4, 0, false);
            }
            if (rMask == 0x000000FF && gMask == 0x0000FF00 && bMask == 0x00FF0000
                && aMask is 0xFF000000 or 0)
            {
                return ("RGBA8", 4, 0, false);
            }
        }
        return (string.Empty, 0, 0, false);
    }
}

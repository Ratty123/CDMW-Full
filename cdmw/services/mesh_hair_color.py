"""DDS colour editing for declared hair base maps on the existing command worker."""

from pathlib import Path
import tempfile

import numpy as np
from PIL import Image

from cdmw.core.dds_native import inspect_dds_native
from cdmw.core.texture_native import decode_dds_preview_with_directxtex, encode_dds_with_directxtex
from cdmw.domain.cancellation import raise_if_cancelled


def recolor_hair_dds(data, color, stop_event):
    """Keep the original header and authored mip chain; change RGB only.

    BC2/BC3 alpha blocks are copied byte-for-byte. Other formats retain the
    decoded alpha through their normal DDS encoder, like Texture Editor.
    """
    info = inspect_dds_native(data)
    color_format = (info.compressed_family in {"bc1", "bc2", "bc3", "bc7"}
        or info.format_name in {"R8G8B8A8_UNORM", "R8G8B8A8_UNORM_SRGB", "B8G8R8A8_UNORM",
                               "B8G8R8A8_UNORM_SRGB", "B8G8R8X8_UNORM", "B8G8R8X8_UNORM_SRGB"})
    if info.reason or not info.mip_levels or not color_format:
        raise ValueError("This hair color DDS cannot be recolored; use Texture Editor for its format.")
    if len(data) != info.mip_levels[-1].offset + info.mip_levels[-1].byte_count:
        raise ValueError("Hair recoloring requires a single complete 2D DDS mip chain.")
    result = bytearray(data)
    target = np.asarray(color, dtype=np.float32)
    reference_luminance = None
    with tempfile.TemporaryDirectory(prefix="cdmw_hair_color_") as directory:
        root = Path(directory)
        source = root / "source.dds"
        source.write_bytes(data)
        for mip in info.mip_levels:
            png, encoded = root / f"color-{mip.level}.png", root / f"color-{mip.level}.dds"
            raise_if_cancelled(stop_event, "Hair recoloring cancelled")
            if not decode_dds_preview_with_directxtex(source, png, max_dimension=0,
                    requested_mip=mip.level, stop_event=stop_event):
                raise ValueError("The native DDS decoder could not read the hair color texture.")
            with Image.open(png) as image:
                pixels = np.array(image.convert("RGBA"))
            if pixels.shape[:2] != (mip.height, mip.width):
                raise ValueError(f"Hair DDS mip {mip.level}: decoder returned {pixels.shape[1]}x{pixels.shape[0]}, expected {mip.width}x{mip.height}.")
            # Retain strand shading while letting dark hair become light too.
            luminance = pixels[:, :, :3].astype(np.float32) @ np.array([.2126, .7152, .0722], dtype=np.float32)
            if reference_luminance is None:
                visible = luminance[pixels[:, :, 3] > 0]
                reference_luminance = max(float(np.percentile(visible, 90)) if visible.size else 255., 1.)
            shade = np.minimum(luminance / reference_luminance, 1.)
            pixels[:, :, :3] = (target * shade[:, :, None] * 255.).round().astype(np.uint8)
            Image.fromarray(pixels).save(png)
            if not encode_dds_with_directxtex(png, encoded, dds_format=info.format_name,
                    width=mip.width, height=mip.height, mip_count=1, stop_event=stop_event):
                raise ValueError("The native DDS encoder could not write the hair color texture.")
            encoded_data = encoded.read_bytes()
            encoded_info = inspect_dds_native(encoded_data)
            if (encoded_info.reason or encoded_info.format_name != info.format_name
                    or len(encoded_info.mip_levels) != 1
                    or encoded_info.mip_levels[0].byte_count != mip.byte_count):
                raise ValueError("Hair recoloring changed the DDS pixel layout.")
            block = bytearray(encoded_data[encoded_info.data_offset:])
            if len(block) != mip.byte_count:
                raise ValueError("Hair recoloring produced an incomplete mip.")
            if info.compressed_family in {"bc2", "bc3"}:
                for offset in range(0, len(block), 16):
                    block[offset:offset + 8] = data[mip.offset + offset:mip.offset + offset + 8]
            result[mip.offset:mip.offset + mip.byte_count] = block
    raise_if_cancelled(stop_event, "Hair recoloring cancelled")
    return bytes(result)

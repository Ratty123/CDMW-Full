"""Bake an explicit imported Glow colour into the selected surface regions."""

from pathlib import Path
from tempfile import TemporaryDirectory

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.new_item_planning import NewItemPlanError


def glow_surface_regions(source, wrapper_name, selected):
    """Normalized atlas cells (including gutters), or the complete base image."""
    if wrapper_name.casefold() in selected or (source is not None and source.name.casefold() in selected):
        return ((0.0, 0.0, 1.0, 1.0),)
    atlas = getattr(source, "atlas_section", None)
    return tuple((rect.x, rect.y, rect.width, rect.height) for rect in getattr(atlas, "atlas_rects", ())
                 if rect.source_material_name.casefold() in selected)


def recolour_glow_pixels(image, colour, regions):
    """Replace hue in linear space, retaining value, alpha and unselected pixels.

    The Rust material shader applies the same max-channel value times the chosen
    linear RGB. Multiplying RGB directly would turn a cyan surface black for red.
    Atlas Y is bottom-up, while the image rows are top-down.
    """
    import numpy as np
    from PIL import Image

    pixels = np.array(image.convert("RGBA"), dtype=np.uint8)
    tint = np.asarray(colour, dtype=np.float32)
    tint = np.where(tint <= 0.04045, tint / 12.92, ((tint + 0.055) / 1.055) ** 2.4)
    # sRGB is monotonic: decode max(R,G,B), not three full float images.
    # A 256-value lookup keeps large texture edits bounded to byte arrays.
    value = np.arange(256, dtype=np.float32)[:, None] / 255.0
    linear = np.where(value <= 0.04045, value / 12.92, ((value + 0.055) / 1.055) ** 2.4)
    coloured = linear * tint
    srgb = np.where(coloured <= 0.0031308, coloured * 12.92, 1.055 * coloured ** (1.0 / 2.4) - 0.055)
    lookup = np.rint(np.clip(srgb, 0.0, 1.0) * 255).astype(np.uint8)
    height, width = pixels.shape[:2]
    for x, y, w, h in regions:
        left, right = round(x * width), round((x + w) * width)
        top, bottom = round((1.0 - y - h) * height), round((1.0 - y) * height)
        region = pixels[top:bottom, left:right, :3]
        region[:] = lookup[region.max(axis=2)]
    return Image.fromarray(pixels)


def encode_glow_surface(payload, colour_hex, regions, *, part_name, stop_event=None):
    from PIL import Image
    from cdmw.core.texture_native import ensure_directxtex_dds_preview_png, encode_dds_with_directxtex
    from cdmw.domain.textures.output import max_mips_for_size

    raise_if_cancelled(stop_event)
    colour = tuple(int(colour_hex[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    with TemporaryDirectory(prefix="cdmw_glow_surface_") as directory:
        root = Path(directory)
        source = root / "source.dds"
        source.write_bytes(payload)
        decoded = ensure_directxtex_dds_preview_png(source, max_dimension=0, slot_kind="base",
                                                   srgb="off", stop_event=stop_event)
        if decoded is None:
            raise NewItemPlanError(f"{part_name}: cannot decode the base colour for Glow.")
        with Image.open(decoded) as image:
            pixels = recolour_glow_pixels(image, colour, regions)
        png, dds = root / "base.png", root / "base.dds"
        pixels.save(png)
        report = encode_dds_with_directxtex(png, dds, dds_format="BC7_UNORM",
            width=pixels.width, height=pixels.height, mip_count=max_mips_for_size(*pixels.size),
            source_color_policy="ignore_srgb_metadata", stop_event=stop_event)
        pixels.close()
        raise_if_cancelled(stop_event)
        if not report or not dds.is_file() or not dds.stat().st_size:
            raise NewItemPlanError(f"{part_name}: could not encode the base colour for Glow.")
        return dds.read_bytes()

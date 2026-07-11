"""Material-atlas layout, gutter, and output-path helpers."""

from __future__ import annotations

import math

from .material_sidecar_patching import _normalize_texture_path
from .static_mesh_output_plan import _MATERIAL_ATLAS_UV_INSET_FRACTION


_SRGB_TEXTURE_SLOTS = frozenset(
    {
        "albedo",
        "base",
        "base_color",
        "diffuse",
        "emissive",
        "sheen",
        "sheen_color",
        "specular_color",
        "specular_glossiness",
    }
)


def material_texture_slot_mode(slot_kind: str) -> str:
    normalized = str(slot_kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in _SRGB_TEXTURE_SLOTS:
        return "srgb"
    if "normal" in normalized:
        return "normal"
    return "linear"


def atlas_tile_layout(source_extent: int, max_cell_extent: int, padding: int) -> tuple[int, int, int]:
    minimum_gutter = max(1, int(padding or 0))
    if max_cell_extent <= minimum_gutter * 2:
        return 0, 0, 0
    fraction = _MATERIAL_ATLAS_UV_INSET_FRACTION
    minimum_content = math.ceil(minimum_gutter * (1.0 - 2.0 * fraction) / fraction)
    maximum_content = min(
        max_cell_extent - minimum_gutter * 2,
        math.floor(max_cell_extent * (1.0 - 2.0 * fraction)),
    )
    if maximum_content < minimum_content:
        return 0, 0, 0
    content_extent = min(max(int(source_extent), minimum_content), maximum_content)
    fractional_gutter = math.ceil(
        (fraction * content_extent) / (1.0 - 2.0 * fraction)
    )
    gutter = max(minimum_gutter, fractional_gutter)
    return content_extent + gutter * 2, max(1, content_extent), gutter


def paste_atlas_tile_with_gutter(
    atlas: object,
    tile: object,
    *,
    origin: tuple[int, int],
    gutter: tuple[int, int],
) -> None:
    from PIL import Image

    x, y = origin
    gutter_x, gutter_y = gutter
    width, height = tile.size
    content_x, content_y = x + gutter_x, y + gutter_y
    atlas.paste(tile, (content_x, content_y))
    if gutter_y:
        atlas.paste(tile.crop((0, 0, width, 1)).resize((width, gutter_y)), (content_x, y))
        atlas.paste(tile.crop((0, height - 1, width, height)).resize((width, gutter_y)), (content_x, content_y + height))
    if gutter_x:
        atlas.paste(tile.crop((0, 0, 1, height)).resize((gutter_x, height)), (x, content_y))
        atlas.paste(tile.crop((width - 1, 0, width, height)).resize((gutter_x, height)), (content_x + width, content_y))
    for corner_x, corner_y, pixel_x, pixel_y in (
        (x, y, 0, 0),
        (content_x + width, y, width - 1, 0),
        (x, content_y + height, 0, height - 1),
        (content_x + width, content_y + height, width - 1, height - 1),
    ):
        atlas.paste(Image.new("RGBA", (gutter_x, gutter_y), tile.getpixel((pixel_x, pixel_y))), (corner_x, corner_y))


def resize_atlas_tile(image: object, target_size: tuple[int, int], slot_kind: str) -> object:
    """Resize color, normal, and data tiles in their authored numeric space."""
    from PIL import Image

    mode = material_texture_slot_mode(slot_kind)
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    rgba = image.convert("RGBA")
    if mode == "linear":
        return rgba.resize(target_size, resampling)

    import numpy as np

    source = np.asarray(rgba, dtype=np.float32) / 255.0

    def resized_channel(channel: object) -> object:
        plane = Image.fromarray(np.asarray(channel, dtype=np.float32), mode="F")
        try:
            return np.asarray(plane.resize(target_size, resampling), dtype=np.float32)
        finally:
            plane.close()

    alpha = resized_channel(source[..., 3])
    if mode == "normal":
        vector = source[..., :3] * 2.0 - 1.0
        resized = np.stack([resized_channel(vector[..., index]) for index in range(3)], axis=-1)
        lengths = np.linalg.norm(resized, axis=-1, keepdims=True)
        fallback = np.zeros_like(resized)
        fallback[..., 2] = 1.0
        resized = np.where(lengths > 1.0e-8, resized / np.maximum(lengths, 1.0e-8), fallback)
        rgb = resized * 0.5 + 0.5
    else:
        rgb = source[..., :3]
        linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        linear = np.stack([resized_channel(linear[..., index]) for index in range(3)], axis=-1)
        rgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * np.maximum(linear, 0.0) ** (1.0 / 2.4) - 0.055)
    output = np.concatenate((rgb, alpha[..., None]), axis=-1)
    return Image.fromarray(np.clip(np.rint(output * 255.0), 0, 255).astype(np.uint8), mode="RGBA")


def source_driven_atlas_texture_output_path(
    texture_parent: str,
    texture_prefix: str,
    target_name: str,
    slot_kind: str,
    emitted_paths: set[str],
) -> str:
    from .material_source_driven import _sanitize_texture_component

    parent = str(texture_parent or "character/texture").replace("\\", "/").strip("/")
    prefix = _sanitize_texture_component(texture_prefix) or "static_replacement"
    target = _sanitize_texture_component(target_name) or "runtime_slot"
    role = _sanitize_texture_component(slot_kind) or "role"
    role_suffix = {"normal": "_n", "height": "_disp", "material_mask": "_ma", "detail_mask": "_mg", "emissive": "_emi"}.get(role, "")
    stem = f"{prefix}_{target}_baked_{role}"
    candidate = f"{parent}/{stem}{role_suffix}.dds" if parent else f"{stem}{role_suffix}.dds"
    index = 2
    while _normalize_texture_path(candidate) in emitted_paths:
        name = f"{stem}_{index}{role_suffix}.dds"
        candidate = f"{parent}/{name}" if parent else name
        index += 1
    emitted_paths.add(_normalize_texture_path(candidate))
    return candidate


__all__ = [
    "atlas_tile_layout",
    "material_texture_slot_mode",
    "paste_atlas_tile_with_gutter",
    "resize_atlas_tile",
    "source_driven_atlas_texture_output_path",
]

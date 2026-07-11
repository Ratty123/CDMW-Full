"""Bounded glTF texture sampling, chart rasterization, and atomic PNG output."""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from cdmw.core.common import raise_if_cancelled

from .material_atlas import material_texture_slot_mode, resize_atlas_tile
from .mesh_parser import SubMesh


GLTF_UV_BAKE_MAX_DIMENSION = 4096
_GLTF_UV_BAKE_MAX_SOURCE_DIMENSION = 8192
_GLTF_UV_BAKE_MAX_SOURCE_PIXELS = 4096 * 4096
_GLTF_UV_BAKE_MAX_DOWNSCALE_PIXELS = 8 * 1024 * 1024
_GLTF_UV_BAKE_MAX_SOURCE_BYTES = 256 * 1024 * 1024
_GLTF_UV_BAKE_MAX_HASH_BYTES = 512 * 1024 * 1024
_GLTF_UV_BAKE_MAX_PNG_BYTES = 128 * 1024 * 1024
_GLTF_UV_BAKE_GUTTER = 8
_GLTF_WRAP_REPEAT = 10497
_GLTF_WRAP_CLAMP = 33071
_GLTF_WRAP_MIRROR = 33648
_GLTF_MIP_FILTERS = {9984, 9985, 9986, 9987}
_GLTF_FILTER_NAMES = {
    9728: "nearest",
    9729: "linear",
    9984: "nearest_mipmap_nearest",
    9985: "linear_mipmap_nearest",
    9986: "nearest_mipmap_linear",
    9987: "linear_mipmap_linear",
}


@dataclass(slots=True)
class GltfRasterSource:
    pixels: object
    width: int
    height: int
    source_width: int
    source_height: int
    source_sha256: str
    mode: str
    downscaled: bool
    mipmaps: tuple[object, ...] = ()


@dataclass(slots=True)
class GltfRasterResult:
    image: object
    covered_pixels: int
    dilation_pixels: int
    filter_mode: str


def _slot_mode(slot_kind: str) -> str:
    return material_texture_slot_mode(slot_kind)


def _file_sha256(
    path: Path,
    *,
    stop_event: object = None,
    max_bytes: int = _GLTF_UV_BAKE_MAX_HASH_BYTES,
) -> str:
    size = path.stat().st_size
    if size < 0 or size > max_bytes:
        raise ValueError(f"glTF UV bake refuses to hash {path.name}: {size:,} bytes exceeds {max_bytes:,}.")
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while True:
            raise_if_cancelled(stop_event, "glTF UV bake cancelled during file hashing.")
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"glTF UV bake refuses to hash growing file {path.name} beyond {max_bytes:,} bytes.")
            digest.update(chunk)
    raise_if_cancelled(stop_event, "glTF UV bake cancelled during file hashing.")
    return digest.hexdigest()


def load_gltf_raster_source(
    path: str | Path,
    slot_kind: str,
    *,
    stop_event: object = None,
) -> GltfRasterSource:
    from PIL import Image
    import numpy as np

    raise_if_cancelled(stop_event, "glTF UV bake cancelled before texture decode.")
    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise ValueError(f"glTF UV bake source texture is missing: {source_path}")
    source_hash = _file_sha256(
        source_path,
        stop_event=stop_event,
        max_bytes=_GLTF_UV_BAKE_MAX_SOURCE_BYTES,
    )
    with Image.open(source_path) as opened:
        width, height = int(opened.width), int(opened.height)
        if width <= 0 or height <= 0:
            raise ValueError(f"glTF UV bake texture has invalid dimensions: {source_path}")
        if (
            width > _GLTF_UV_BAKE_MAX_SOURCE_DIMENSION
            or height > _GLTF_UV_BAKE_MAX_SOURCE_DIMENSION
            or width * height > _GLTF_UV_BAKE_MAX_SOURCE_PIXELS
        ):
            raise ValueError(
                f"glTF UV bake texture {source_path.name} exceeds the safe source ceiling "
                f"({_GLTF_UV_BAKE_MAX_SOURCE_DIMENSION}px/{_GLTF_UV_BAKE_MAX_SOURCE_PIXELS:,} pixels)."
            )
        if max(width, height) > GLTF_UV_BAKE_MAX_DIMENSION and width * height > _GLTF_UV_BAKE_MAX_DOWNSCALE_PIXELS:
            raise ValueError(
                f"glTF UV bake texture {source_path.name} is too large for bounded semantic downscaling "
                f"({width}x{height}; maximum {_GLTF_UV_BAKE_MAX_DOWNSCALE_PIXELS:,} source pixels above 4096)."
            )
        image = opened.convert("RGBA")
    source_width, source_height = width, height
    scale = min(1.0, GLTF_UV_BAKE_MAX_DIMENSION / max(width, height))
    downscaled = scale < 1.0
    if downscaled:
        target = (max(1, round(width * scale)), max(1, round(height * scale)))
        resized = resize_atlas_tile(image, target, slot_kind)
        image.close()
        image = resized
        width, height = target
    encoded = np.asarray(image, dtype=np.float32) / 255.0
    image.close()
    mode = _slot_mode(slot_kind)
    if mode == "srgb":
        encoded[..., :3] = np.where(
            encoded[..., :3] <= 0.04045,
            encoded[..., :3] / 12.92,
            ((encoded[..., :3] + 0.055) / 1.055) ** 2.4,
        )
    elif mode == "normal":
        encoded[..., :3] = encoded[..., :3] * 2.0 - 1.0
    raise_if_cancelled(stop_event, "glTF UV bake cancelled after texture decode.")
    return GltfRasterSource(
        pixels=encoded,
        width=width,
        height=height,
        source_width=source_width,
        source_height=source_height,
        source_sha256=source_hash,
        mode=mode,
        downscaled=downscaled,
    )


def _downsample_mip(pixels: object, mode: str) -> object:
    import numpy as np

    source = np.asarray(pixels, dtype=np.float32)
    height, width = source.shape[:2]
    target = (max(1, width // 2), max(1, height // 2))
    if height % 2 == 0 and width % 2 == 0:
        output = (
            source[0::2, 0::2]
            + source[0::2, 1::2]
            + source[1::2, 0::2]
            + source[1::2, 1::2]
        ) * 0.25
    else:
        from PIL import Image

        resampling = getattr(Image, "Resampling", Image).BOX
        channels = []
        for channel_index in range(source.shape[2]):
            plane = Image.fromarray(source[..., channel_index], mode="F")
            try:
                channels.append(np.asarray(plane.resize(target, resampling), dtype=np.float32))
            finally:
                plane.close()
        output = np.stack(channels, axis=-1)
    if mode == "normal":
        lengths = np.linalg.norm(output[..., :3], axis=-1, keepdims=True)
        fallback = np.zeros_like(output[..., :3])
        fallback[..., 2] = 1.0
        output[..., :3] = np.where(
            lengths > 1.0e-8,
            output[..., :3] / np.maximum(lengths, 1.0e-8),
            fallback,
        )
    return np.asarray(output, dtype=np.float32)


def _build_mip_pyramid(pixels: object, mode: str, *, stop_event: object = None) -> tuple[object, ...]:
    import numpy as np

    base = np.asarray(pixels, dtype=np.float32)
    levels: list[object] = [base]
    while max(base.shape[:2]) > 1:
        raise_if_cancelled(stop_event, "glTF UV bake cancelled during mip generation.")
        base = _downsample_mip(base, mode)
        levels.append(base)
    return tuple(levels)


def _address_indices(indices: object, size: int, wrap: int) -> object:
    import numpy as np

    values = np.asarray(indices, dtype=np.int64)
    if wrap == _GLTF_WRAP_CLAMP:
        return np.clip(values, 0, size - 1)
    if wrap == _GLTF_WRAP_REPEAT:
        return np.mod(values, size)
    if wrap == _GLTF_WRAP_MIRROR:
        period = max(1, size * 2)
        mirrored = np.mod(values, period)
        return np.where(mirrored < size, mirrored, period - 1 - mirrored)
    raise ValueError(f"Unsupported glTF sampler wrap mode: {wrap}")


def _filter_mode(min_filter: int, mag_filter: int, *, minifying: bool) -> str:
    selected = min_filter if minifying else mag_filter
    if selected < 0:
        selected = 9987 if minifying else 9729
    mode = _GLTF_FILTER_NAMES.get(selected)
    if mode is not None and (minifying or selected in {9728, 9729}):
        return mode
    raise ValueError(f"Unsupported glTF sampler filter: min={min_filter}, mag={mag_filter}")


def _triangle_lod(destination_uvs: object, source_uvs: object, width: int, height: int) -> float:
    import numpy as np

    destination = np.asarray(destination_uvs, dtype=np.float64)
    source = np.asarray(source_uvs, dtype=np.float64)
    destination_edges = np.stack((destination[1] - destination[0], destination[2] - destination[0]), axis=1)
    determinant = float(np.linalg.det(destination_edges))
    if abs(determinant) <= 1.0e-14:
        return 0.0
    source_edges = np.stack((source[1] - source[0], source[2] - source[0]), axis=1)
    jacobian = source_edges @ np.linalg.inv(destination_edges)
    pixel_scale = np.diag((float(width), float(height))) @ jacobian @ np.diag((1.0 / width, 1.0 / height))
    footprint = max(float(np.linalg.svd(pixel_scale, compute_uv=False)[0]), 1.0e-12)
    return max(0.0, math.log2(footprint))


def _triangle_is_minifying(destination_uvs: object, source_uvs: object, width: int, height: int) -> bool:
    return _triangle_lod(destination_uvs, source_uvs, width, height) > 1.0e-6


def _sample_texture_level(
    pixels: object,
    u: object,
    v: object,
    *,
    wrap_s: int,
    wrap_t: int,
    texel_filter: str,
) -> object:
    import numpy as np

    source = np.asarray(pixels, dtype=np.float32)
    height, width = source.shape[:2]
    u_values = np.asarray(u, dtype=np.float64)
    v_values = np.asarray(v, dtype=np.float64)
    if texel_filter == "nearest":
        x = _address_indices(np.floor(u_values * width).astype(np.int64), width, wrap_s)
        y = _address_indices(np.floor(v_values * height).astype(np.int64), height, wrap_t)
        return source[y, x]
    if texel_filter != "linear":
        raise ValueError(f"Unsupported glTF texel filter: {texel_filter}")
    x_value = u_values * width - 0.5
    y_value = v_values * height - 0.5
    x0 = np.floor(x_value).astype(np.int64)
    y0 = np.floor(y_value).astype(np.int64)
    fx = (x_value - x0)[..., None]
    fy = (y_value - y0)[..., None]
    x1, y1 = x0 + 1, y0 + 1
    x0 = _address_indices(x0, width, wrap_s)
    x1 = _address_indices(x1, width, wrap_s)
    y0 = _address_indices(y0, height, wrap_t)
    y1 = _address_indices(y1, height, wrap_t)
    top = source[y0, x0] * (1.0 - fx) + source[y0, x1] * fx
    bottom = source[y1, x0] * (1.0 - fx) + source[y1, x1] * fx
    return top * (1.0 - fy) + bottom * fy


def sample_gltf_texture(
    pixels: object,
    u: object,
    v: object,
    *,
    wrap_s: int,
    wrap_t: int,
    filter_mode: str,
    mipmaps: Sequence[object] = (),
    lod: float = 0.0,
) -> object:
    levels = tuple(mipmaps or (pixels,))
    if not levels:
        raise ValueError("glTF texture sampling received no mip levels.")
    texel_filter = "linear" if filter_mode.startswith("linear") else "nearest"
    if "_mipmap_" not in filter_mode:
        return _sample_texture_level(
            levels[0], u, v, wrap_s=wrap_s, wrap_t=wrap_t, texel_filter=texel_filter
        )
    clamped_lod = max(0.0, min(float(lod), float(len(levels) - 1)))
    if filter_mode.endswith("_mipmap_nearest"):
        level = min(len(levels) - 1, int(math.floor(clamped_lod + 0.5)))
        return _sample_texture_level(
            levels[level], u, v, wrap_s=wrap_s, wrap_t=wrap_t, texel_filter=texel_filter
        )
    if not filter_mode.endswith("_mipmap_linear"):
        raise ValueError(f"Unsupported glTF sampler filter mode: {filter_mode}")
    low = min(len(levels) - 1, int(math.floor(clamped_lod)))
    high = min(len(levels) - 1, low + 1)
    fraction = clamped_lod - low
    low_samples = _sample_texture_level(
        levels[low], u, v, wrap_s=wrap_s, wrap_t=wrap_t, texel_filter=texel_filter
    )
    if high == low or fraction <= 0.0:
        return low_samples
    high_samples = _sample_texture_level(
        levels[high], u, v, wrap_s=wrap_s, wrap_t=wrap_t, texel_filter=texel_filter
    )
    return low_samples * (1.0 - fraction) + high_samples * fraction


def _normalize_rows(values: object, *, fallback_z: bool = False) -> object:
    import numpy as np

    rows = np.asarray(values, dtype=np.float64)
    lengths = np.linalg.norm(rows, axis=-1, keepdims=True)
    fallback = np.zeros_like(rows)
    if fallback_z:
        fallback[..., 2] = 1.0
    return np.where(lengths > 1.0e-12, rows / np.maximum(lengths, 1.0e-12), fallback)


def _triangle_tangent_basis(positions: object, uvs: object) -> tuple[object, object]:
    import numpy as np

    points = np.asarray(positions, dtype=np.float64)
    coords = np.asarray(uvs, dtype=np.float64)
    edge1, edge2 = points[1] - points[0], points[2] - points[0]
    duv1, duv2 = coords[1] - coords[0], coords[2] - coords[0]
    determinant = duv1[0] * duv2[1] - duv1[1] * duv2[0]
    if abs(float(determinant)) <= 1.0e-12:
        raise ValueError("glTF normal bake encountered a degenerate source UV triangle.")
    reciprocal = 1.0 / determinant
    tangent = (edge1 * duv2[1] - edge2 * duv1[1]) * reciprocal
    bitangent = (edge2 * duv1[0] - edge1 * duv2[0]) * reciprocal
    return tangent, bitangent


def _reorient_normal_samples(
    samples: object,
    weights: object,
    positions: object,
    normals: object,
    source_uvs: object,
    source_tangents: object,
    source_signs: object,
    destination_tangents: object,
    destination_signs: object,
    normal_scale: float,
) -> object:
    import numpy as np

    barycentric = np.asarray(weights, dtype=np.float64)
    normal = _normalize_rows(barycentric @ np.asarray(normals, dtype=np.float64), fallback_z=True)
    if source_tangents is None or source_signs is None:
        source_tangent, source_bitangent = _triangle_tangent_basis(positions, source_uvs)
        source_tangent = np.broadcast_to(source_tangent, normal.shape)
        source_sign = np.sign(
            np.sum(np.cross(normal, source_tangent) * source_bitangent, axis=-1, keepdims=True)
        )
    else:
        source_tangent = barycentric @ np.asarray(source_tangents, dtype=np.float64)
        source_sign = np.sign(barycentric @ np.asarray(source_signs, dtype=np.float64))[:, None]
    source_tangent = _normalize_rows(
        source_tangent - normal * np.sum(normal * source_tangent, axis=-1, keepdims=True)
    )
    source_sign = np.where(source_sign == 0.0, 1.0, source_sign)
    source_bitangent_rows = np.cross(normal, source_tangent) * source_sign
    destination_tangent = barycentric @ np.asarray(destination_tangents, dtype=np.float64)
    destination_tangent = _normalize_rows(
        destination_tangent - normal * np.sum(normal * destination_tangent, axis=-1, keepdims=True)
    )
    destination_sign = np.sign(barycentric @ np.asarray(destination_signs, dtype=np.float64))[:, None]
    destination_sign = np.where(destination_sign == 0.0, 1.0, destination_sign)
    destination_bitangent = np.cross(normal, destination_tangent) * destination_sign
    tangent_normal = _normalize_rows(np.asarray(samples, dtype=np.float64)[..., :3], fallback_z=True)
    tangent_normal[..., :2] *= float(normal_scale)
    tangent_normal = _normalize_rows(tangent_normal, fallback_z=True)
    object_normal = (
        source_tangent * tangent_normal[..., 0:1]
        + source_bitangent_rows * tangent_normal[..., 1:2]
        + normal * tangent_normal[..., 2:3]
    )
    output = np.stack(
        (
            np.sum(object_normal * destination_tangent, axis=-1),
            np.sum(object_normal * destination_bitangent, axis=-1),
            np.sum(object_normal * normal, axis=-1),
        ),
        axis=-1,
    )
    result = np.asarray(samples, dtype=np.float64).copy()
    result[..., :3] = _normalize_rows(output, fallback_z=True)
    return result


def _dilate_pixels(
    pixels: object,
    coverage: object,
    distance: int,
    *,
    stop_event: object = None,
) -> tuple[object, object]:
    import numpy as np

    output = np.asarray(pixels)
    mask = np.asarray(coverage, dtype=bool).copy()
    for _iteration in range(max(0, int(distance))):
        raise_if_cancelled(stop_event, "glTF UV bake cancelled during gutter dilation.")
        next_mask = mask.copy()
        for dy, dx in ((-1, 0), (0, -1), (0, 1), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            raise_if_cancelled(stop_event, "glTF UV bake cancelled during gutter dilation.")
            source_y = slice(max(0, -dy), mask.shape[0] - max(0, dy))
            source_x = slice(max(0, -dx), mask.shape[1] - max(0, dx))
            target_y = slice(max(0, dy), mask.shape[0] - max(0, -dy))
            target_x = slice(max(0, dx), mask.shape[1] - max(0, -dx))
            candidates = mask[source_y, source_x] & ~next_mask[target_y, target_x]
            output[target_y, target_x][candidates] = output[source_y, source_x][candidates]
            next_mask[target_y, target_x][candidates] = True
        mask = next_mask
    return output, mask


def _encode_raster_pixels(pixels: object, mode: str, *, stop_event: object = None) -> object:
    import numpy as np

    source = np.asarray(pixels, dtype=np.float32)
    output = np.empty(source.shape, dtype=np.uint8)
    for row_start in range(0, source.shape[0], 64):
        raise_if_cancelled(stop_event, "glTF UV bake cancelled during raster encoding.")
        row_end = min(source.shape[0], row_start + 64)
        rows = source[row_start:row_end].copy()
        if mode == "srgb":
            linear = np.maximum(rows[..., :3], 0.0)
            rows[..., :3] = np.where(
                linear <= 0.0031308,
                linear * 12.92,
                1.055 * linear ** (1.0 / 2.4) - 0.055,
            )
        elif mode == "normal":
            rows[..., :3] = _normalize_rows(rows[..., :3], fallback_z=True) * 0.5 + 0.5
        output[row_start:row_end] = np.clip(np.rint(rows * 255.0), 0, 255).astype(np.uint8)
    return output


def _prepare_raster_source(source: GltfRasterSource, min_filter: int, *, stop_event: object) -> object:
    import numpy as np

    pixels = np.asarray(source.pixels)
    if (
        source.width <= 0
        or source.height <= 0
        or source.width > GLTF_UV_BAKE_MAX_DIMENSION
        or source.height > GLTF_UV_BAKE_MAX_DIMENSION
        or source.width * source.height > _GLTF_UV_BAKE_MAX_SOURCE_PIXELS
        or pixels.ndim != 3
        or pixels.shape != (source.height, source.width, 4)
    ):
        raise ValueError("glTF UV bake received invalid or unsafe raster source dimensions.")
    source.pixels = pixels
    if (min_filter < 0 or min_filter in _GLTF_MIP_FILTERS) and not source.mipmaps:
        source.mipmaps = _build_mip_pyramid(pixels, source.mode, stop_event=stop_event)
    return pixels


def rasterize_gltf_slot(
    submesh: SubMesh,
    source_uvs: Sequence[Sequence[float]],
    transform: Sequence[float],
    source: GltfRasterSource,
    *,
    wrap_s: int,
    wrap_t: int,
    min_filter: int,
    mag_filter: int,
    normal_scale: float = 1.0,
    source_tangents: Sequence[Sequence[float]] = (),
    source_tangent_signs: Sequence[float] = (),
    release_source: bool = False,
    stop_event: object = None,
) -> GltfRasterResult:
    from PIL import Image
    import numpy as np

    vertex_count = len(submesh.vertices)
    if len(submesh.uvs) != vertex_count or len(source_uvs) != vertex_count:
        raise ValueError("glTF UV bake lost vertex-aligned source or destination UVs.")
    if source.mode == "normal" and (
        len(submesh.normals) != vertex_count
        or len(submesh.tangents) != vertex_count
        or len(tuple(getattr(submesh, "tangent_signs", ()) or ())) != vertex_count
    ):
        raise ValueError("glTF normal bake requires complete native MikkTSpace destination tangents.")
    if source.mode == "normal" and bool(source_tangents or source_tangent_signs) and (
        len(source_tangents) != vertex_count or len(source_tangent_signs) != vertex_count
    ):
        raise ValueError("glTF normal bake received an incomplete source tangent frame.")
    source_pixels = _prepare_raster_source(source, min_filter, stop_event=stop_event)
    used_filters: set[str] = set()
    output = np.zeros((source.height, source.width, 4), dtype=np.float32)
    if source.mode == "normal":
        output[..., 2] = 1.0
        output[..., 3] = 1.0
    coverage = np.zeros((source.height, source.width), dtype=bool)
    destination_uvs = np.asarray(submesh.uvs, dtype=np.float64)
    source_rows = np.asarray(source_uvs, dtype=np.float64)
    positions = np.asarray(submesh.vertices, dtype=np.float64)
    normals = np.asarray(submesh.normals, dtype=np.float64) if submesh.normals else None
    tangents = np.asarray(submesh.tangents, dtype=np.float64) if submesh.tangents else None
    signs = np.asarray(tuple(getattr(submesh, "tangent_signs", ()) or ()), dtype=np.float64)
    source_tangent_rows = np.asarray(source_tangents, dtype=np.float64) if source_tangents else None
    source_sign_rows = np.asarray(source_tangent_signs, dtype=np.float64) if source_tangent_signs else None
    offset_u, offset_v, scale_u, scale_v, rotation = tuple(float(value) for value in transform[:5])
    cosine, sine = math.cos(rotation), math.sin(rotation)
    for face_index, face in enumerate(submesh.faces):
        if face_index % 64 == 0:
            raise_if_cancelled(stop_event, "glTF UV bake cancelled during rasterization.")
        indices = np.asarray(face, dtype=np.int64)
        if len(indices) != 3 or int(indices.min()) < 0 or int(indices.max()) >= vertex_count:
            raise ValueError("glTF UV bake encountered an invalid destination face.")
        triangle_uv = destination_uvs[indices]
        pixel_x = triangle_uv[:, 0] * source.width - 0.5
        pixel_y = (1.0 - triangle_uv[:, 1]) * source.height - 0.5
        min_x = max(0, int(math.floor(float(pixel_x.min()))))
        max_x = min(source.width - 1, int(math.ceil(float(pixel_x.max()))))
        min_y = max(0, int(math.floor(float(pixel_y.min()))))
        max_y = min(source.height - 1, int(math.ceil(float(pixel_y.max()))))
        denominator = (
            (triangle_uv[1, 1] - triangle_uv[2, 1]) * (triangle_uv[0, 0] - triangle_uv[2, 0])
            + (triangle_uv[2, 0] - triangle_uv[1, 0]) * (triangle_uv[0, 1] - triangle_uv[2, 1])
        )
        if abs(float(denominator)) <= 1.0e-14:
            continue
        source_triangle = source_rows[indices]
        transformed_triangle = np.empty_like(source_triangle)
        transformed_triangle[:, 0] = offset_u + cosine * (source_triangle[:, 0] * scale_u) - sine * (source_triangle[:, 1] * scale_v)
        transformed_triangle[:, 1] = offset_v + sine * (source_triangle[:, 0] * scale_u) + cosine * (source_triangle[:, 1] * scale_v)
        lod = _triangle_lod(triangle_uv, transformed_triangle, source.width, source.height)
        filter_mode = _filter_mode(
            min_filter,
            mag_filter,
            minifying=lod > 1.0e-6,
        )
        used_filters.add(filter_mode)
        for row_start in range(min_y, max_y + 1, 64):
            raise_if_cancelled(stop_event, "glTF UV bake cancelled during rasterization.")
            row_end = min(max_y + 1, row_start + 64)
            x_grid, y_grid = np.meshgrid(
                (np.arange(min_x, max_x + 1) + 0.5) / source.width,
                1.0 - (np.arange(row_start, row_end) + 0.5) / source.height,
            )
            weight0 = ((triangle_uv[1, 1] - triangle_uv[2, 1]) * (x_grid - triangle_uv[2, 0]) + (triangle_uv[2, 0] - triangle_uv[1, 0]) * (y_grid - triangle_uv[2, 1])) / denominator
            weight1 = ((triangle_uv[2, 1] - triangle_uv[0, 1]) * (x_grid - triangle_uv[2, 0]) + (triangle_uv[0, 0] - triangle_uv[2, 0]) * (y_grid - triangle_uv[2, 1])) / denominator
            weights = np.stack((weight0, weight1, 1.0 - weight0 - weight1), axis=-1)
            inside = np.all(weights >= -1.0e-8, axis=-1)
            if not inside.any():
                continue
            source_sample_uv = weights @ transformed_triangle
            samples = sample_gltf_texture(
                source.pixels,
                source_sample_uv[..., 0],
                source_sample_uv[..., 1],
                wrap_s=wrap_s,
                wrap_t=wrap_t,
                filter_mode=filter_mode,
                mipmaps=source.mipmaps,
                lod=lod,
            )
            if source.mode == "normal":
                samples = _reorient_normal_samples(
                    samples.reshape(-1, 4),
                    weights.reshape(-1, 3),
                    positions[indices],
                    normals[indices],
                    source_triangle,
                    source_tangent_rows[indices] if source_tangent_rows is not None else None,
                    source_sign_rows[indices] if source_sign_rows is not None else None,
                    tangents[indices],
                    signs[indices],
                    normal_scale,
                ).reshape(samples.shape)
            region = output[row_start:row_end, min_x : max_x + 1]
            region[inside] = samples[inside]
            coverage[row_start:row_end, min_x : max_x + 1][inside] = True
    if not coverage.any():
        raise ValueError("glTF UV bake produced no covered destination pixels.")
    if release_source:
        source.pixels = None
        source.mipmaps = ()
        source_pixels = None
    output, _dilated = _dilate_pixels(
        output,
        coverage,
        _GLTF_UV_BAKE_GUTTER,
        stop_event=stop_event,
    )
    encoded = _encode_raster_pixels(output, source.mode, stop_event=stop_event)
    return GltfRasterResult(
        image=Image.fromarray(encoded, mode="RGBA"),
        covered_pixels=int(coverage.sum()),
        dilation_pixels=_GLTF_UV_BAKE_GUTTER,
        filter_mode="mixed" if len(used_filters) > 1 else next(iter(used_filters), "linear"),
    )


def _write_png_chunk(stream: object, chunk_type: bytes, payload: bytes) -> None:
    stream.write(struct.pack(">I", len(payload)))
    stream.write(chunk_type)
    stream.write(payload)
    stream.write(struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF))


def _write_cancellable_png(image: object, path: Path, *, stop_event: object = None) -> None:
    import numpy as np

    if getattr(image, "mode", "") != "RGBA":
        raise ValueError("glTF UV bake publication requires an RGBA raster.")
    width, height = (int(value) for value in image.size)
    if (
        width <= 0
        or height <= 0
        or width > GLTF_UV_BAKE_MAX_DIMENSION
        or height > GLTF_UV_BAKE_MAX_DIMENSION
        or width * height > _GLTF_UV_BAKE_MAX_SOURCE_PIXELS
    ):
        raise ValueError("glTF UV bake refuses to publish unsafe PNG dimensions.")
    pixels = np.asarray(image, dtype=np.uint8)
    if pixels.shape != (height, width, 4):
        raise ValueError("glTF UV bake publication received an invalid RGBA raster.")
    compressor = zlib.compressobj(level=9)
    with path.open("wb") as stream:
        stream.write(b"\x89PNG\r\n\x1a\n")
        _write_png_chunk(stream, b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        for row_index in range(height):
            if row_index % 16 == 0:
                raise_if_cancelled(stop_event, "glTF UV bake cancelled during PNG encoding.")
            encoded = compressor.compress(b"\0" + pixels[row_index].tobytes())
            if encoded:
                _write_png_chunk(stream, b"IDAT", encoded)
                if stream.tell() > _GLTF_UV_BAKE_MAX_PNG_BYTES:
                    raise ValueError("glTF UV bake PNG exceeds the safe output byte ceiling.")
        encoded = compressor.flush()
        if encoded:
            _write_png_chunk(stream, b"IDAT", encoded)
        _write_png_chunk(stream, b"IEND", b"")
        if stream.tell() > _GLTF_UV_BAKE_MAX_PNG_BYTES:
            raise ValueError("glTF UV bake PNG exceeds the safe output byte ceiling.")
        stream.flush()
        os.fsync(stream.fileno())
    raise_if_cancelled(stop_event, "glTF UV bake cancelled during PNG encoding.")


def publish_gltf_raster_png(
    result: GltfRasterResult,
    source_path: Path,
    slot_key: str,
    provenance: Mapping[str, object],
    *,
    stop_event: object = None,
) -> tuple[Path, dict[str, object]]:
    raise_if_cancelled(stop_event, "glTF UV bake cancelled before output publication.")
    canonical = json.dumps(provenance, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    provenance_hash = hashlib.sha256(canonical).hexdigest()
    source_hash = _file_sha256(source_path, stop_event=stop_event)
    root = Path(tempfile.gettempdir()) / "cdmw_gltf_uv_bakes" / source_hash[:24]
    root.mkdir(parents=True, exist_ok=True)
    safe_slot = "".join(character if character.isalnum() else "_" for character in slot_key).strip("_") or "texture"
    output_path = root / f"{safe_slot}_{provenance_hash[:24]}.png"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output_path.stem}.", suffix=".tmp", dir=root)
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        _write_cancellable_png(result.image, temporary_path, stop_event=stop_event)
        output_hash = _file_sha256(
            temporary_path,
            stop_event=stop_event,
            max_bytes=_GLTF_UV_BAKE_MAX_PNG_BYTES,
        )
        raise_if_cancelled(stop_event, "glTF UV bake cancelled before atomic publication.")
        if not output_path.is_file() or _file_sha256(
            output_path,
            stop_event=stop_event,
            max_bytes=_GLTF_UV_BAKE_MAX_PNG_BYTES,
        ) != output_hash:
            os.replace(temporary_path, output_path)
        else:
            temporary_path.unlink(missing_ok=True)
    finally:
        temporary_path.unlink(missing_ok=True)
        result.image.close()
    return output_path, {
        "provenance_sha256": provenance_hash,
        "output_sha256": output_hash,
        "output_path": output_path.as_posix(),
        "covered_pixels": result.covered_pixels,
        "dilation_pixels": result.dilation_pixels,
        "filter": result.filter_mode,
    }


__all__ = [
    "GLTF_UV_BAKE_MAX_DIMENSION",
    "GltfRasterResult",
    "GltfRasterSource",
    "load_gltf_raster_source",
    "publish_gltf_raster_png",
    "rasterize_gltf_slot",
    "sample_gltf_texture",
]

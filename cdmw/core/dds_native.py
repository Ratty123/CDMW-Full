from __future__ import annotations

from dataclasses import dataclass
import struct
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

from cdmw.core.dds_resource_limits import (
    DDS_MAX_PAYLOAD_BYTES,
    checked_dds_mip_byte_counts,
    validate_dds_dimensions,
)


DDS_MAGIC = b"DDS "
DDS_HEADER_SIZE = 124
DDS_PIXELFORMAT_SIZE = 32
DDS_FOURCC = 0x00000004
DDS_RGB = 0x00000040
DDS_LUMINANCE = 0x00020000
DDS_ALPHA_PIXELS = 0x00000001


@dataclass(frozen=True)
class DdsMipLevel:
    level: int
    width: int
    height: int
    offset: int
    byte_count: int


@dataclass(frozen=True)
class DdsNativeInfo:
    width: int
    height: int
    mip_count: int
    format_name: str
    dxgi_format: int = 0
    fourcc: str = ""
    block_width: int = 4
    block_height: int = 4
    bytes_per_block: int = 0
    data_offset: int = 128
    mip_levels: Tuple[DdsMipLevel, ...] = ()
    supported_compressed: bool = False
    supported_uncompressed: bool = False
    compressed_family: str = ""
    srgb: bool = False
    has_alpha: bool = False
    reason: str = ""


_DXGI_COMPRESSED_FORMATS: Dict[int, Tuple[str, str, int, bool, bool]] = {
    70: ("BC1_UNORM", "bc1", 8, False, True),
    71: ("BC1_UNORM_SRGB", "bc1", 8, True, True),
    72: ("BC2_UNORM", "bc2", 16, False, True),
    73: ("BC2_UNORM_SRGB", "bc2", 16, True, True),
    74: ("BC3_UNORM", "bc3", 16, False, True),
    75: ("BC3_UNORM_SRGB", "bc3", 16, True, True),
    76: ("BC4_UNORM", "bc4", 8, False, False),
    77: ("BC4_SNORM", "bc4", 8, False, False),
    80: ("BC5_UNORM", "bc5", 16, False, False),
    83: ("BC5_SNORM", "bc5", 16, False, False),
    94: ("BC6H_UF16", "bc6h", 16, False, False),
    95: ("BC6H_SF16", "bc6h", 16, False, False),
    98: ("BC7_UNORM", "bc7", 16, False, True),
    99: ("BC7_UNORM_SRGB", "bc7", 16, True, True),
}

_DXGI_UNCOMPRESSED_FORMATS: Dict[int, Tuple[str, str, int, bool, bool]] = {
    28: ("R8G8B8A8_UNORM", "rgba8", 4, False, True),
    29: ("R8G8B8A8_UNORM_SRGB", "rgba8", 4, True, True),
    56: ("R16_UNORM", "r16", 2, False, False),
    49: ("R8G8_UNORM", "rg8", 2, False, False),
    61: ("R8_UNORM", "r8", 1, False, False),
    87: ("B8G8R8A8_UNORM", "bgra8", 4, False, True),
    88: ("B8G8R8X8_UNORM", "bgrx8", 4, False, False),
    91: ("B8G8R8A8_UNORM_SRGB", "bgra8", 4, True, True),
    93: ("B8G8R8X8_UNORM_SRGB", "bgrx8", 4, True, False),
}

_FOURCC_COMPRESSED_FORMATS: Dict[bytes, Tuple[str, str, int, bool, bool]] = {
    b"DXT1": ("BC1_UNORM", "bc1", 8, False, True),
    b"DXT2": ("BC2_UNORM", "bc2", 16, False, True),
    b"DXT3": ("BC2_UNORM", "bc2", 16, False, True),
    b"DXT4": ("BC3_UNORM", "bc3", 16, False, True),
    b"DXT5": ("BC3_UNORM", "bc3", 16, False, True),
    b"ATI1": ("BC4_UNORM", "bc4", 8, False, False),
    b"BC4U": ("BC4_UNORM", "bc4", 8, False, False),
    b"BC4S": ("BC4_SNORM", "bc4", 8, False, False),
    b"ATI2": ("BC5_UNORM", "bc5", 16, False, False),
    b"BC5U": ("BC5_UNORM", "bc5", 16, False, False),
    b"BC5S": ("BC5_SNORM", "bc5", 16, False, False),
}


def _read_u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError("DDS header is truncated")
    return struct.unpack_from("<I", data, offset)[0]


def _build_mip_layout(
    *,
    width: int,
    height: int,
    mip_count: int,
    data_offset: int,
    bytes_per_block: int,
    payload_size: int,
    block_width: int = 4,
    block_height: int = 4,
) -> Tuple[DdsMipLevel, ...]:
    byte_counts = checked_dds_mip_byte_counts(
        width,
        height,
        mip_count,
        bytes_per_block,
        block_width=block_width,
        block_height=block_height,
        max_bytes=DDS_MAX_PAYLOAD_BYTES,
    )
    if int(data_offset) + sum(byte_counts) > int(payload_size):
        return ()
    levels = []
    offset = int(data_offset)
    level_width = int(width)
    level_height = int(height)
    for level, byte_count in enumerate(byte_counts):
        levels.append(
            DdsMipLevel(
                level=level,
                width=level_width,
                height=level_height,
                offset=offset,
                byte_count=byte_count,
            )
        )
        offset += byte_count
        level_width = max(1, level_width // 2)
        level_height = max(1, level_height // 2)
    return tuple(levels)


def inspect_dds_native(data: bytes, *, payload_size: Optional[int] = None) -> DdsNativeInfo:
    total_size = len(data) if payload_size is None else max(0, int(payload_size))
    if len(data) < 128 or data[:4] != DDS_MAGIC:
        return DdsNativeInfo(0, 0, 0, "", reason="not a DDS file or header is truncated")
    header_size = _read_u32(data, 4)
    if header_size != DDS_HEADER_SIZE:
        return DdsNativeInfo(0, 0, 0, "", reason=f"unsupported DDS header size: {header_size}")
    height = _read_u32(data, 12)
    width = _read_u32(data, 16)
    mip_count = max(1, _read_u32(data, 28))
    try:
        width, height, mip_count = validate_dds_dimensions(width, height, mip_count)
    except ValueError as exc:
        return DdsNativeInfo(width, height, mip_count, "", reason=str(exc))
    pixel_format_offset = 76
    pixel_format_size = _read_u32(data, pixel_format_offset)
    if pixel_format_size != DDS_PIXELFORMAT_SIZE:
        return DdsNativeInfo(width, height, mip_count, "", reason=f"unsupported DDS pixel format size: {pixel_format_size}")
    pf_flags = _read_u32(data, pixel_format_offset + 4)
    fourcc_bytes = data[pixel_format_offset + 8 : pixel_format_offset + 12]
    rgb_bit_count = _read_u32(data, pixel_format_offset + 12)
    red_mask = _read_u32(data, pixel_format_offset + 16)
    green_mask = _read_u32(data, pixel_format_offset + 20)
    blue_mask = _read_u32(data, pixel_format_offset + 24)
    alpha_mask = _read_u32(data, pixel_format_offset + 28)
    data_offset = 128
    dxgi_format = 0
    format_tuple: Optional[Tuple[str, str, int, bool, bool]] = None
    is_compressed = True
    fourcc = ""
    if pf_flags & DDS_FOURCC:
        fourcc = fourcc_bytes.decode("ascii", errors="replace").rstrip("\0")
        if fourcc_bytes == b"DX10":
            if len(data) < 148:
                return DdsNativeInfo(width, height, mip_count, "DX10", fourcc="DX10", reason="DDS DX10 header is truncated")
            dxgi_format = _read_u32(data, 128)
            data_offset = 148
            format_tuple = _DXGI_COMPRESSED_FORMATS.get(dxgi_format)
            if format_tuple is None:
                format_tuple = _DXGI_UNCOMPRESSED_FORMATS.get(dxgi_format)
                is_compressed = False
        else:
            format_tuple = _FOURCC_COMPRESSED_FORMATS.get(fourcc_bytes)
    elif pf_flags & DDS_LUMINANCE:
        if rgb_bit_count == 8 and red_mask == 0x000000FF:
            dxgi_format = 61
        elif rgb_bit_count == 16 and red_mask == 0x0000FFFF:
            dxgi_format = 56
        if dxgi_format:
            format_tuple = _DXGI_UNCOMPRESSED_FORMATS.get(dxgi_format)
            is_compressed = False
    elif pf_flags & DDS_RGB:
        masks = (red_mask, green_mask, blue_mask, alpha_mask)
        if rgb_bit_count == 32 and masks == (0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000):
            dxgi_format = 28
        elif rgb_bit_count == 32 and masks[:3] == (0x00FF0000, 0x0000FF00, 0x000000FF):
            dxgi_format = 87
        if dxgi_format:
            format_tuple = _DXGI_UNCOMPRESSED_FORMATS.get(dxgi_format)
            is_compressed = False
    if format_tuple is None:
        name = f"DXGI_{dxgi_format}" if dxgi_format else (fourcc or "uncompressed_or_unknown")
        return DdsNativeInfo(
            width,
            height,
            mip_count,
            name,
            dxgi_format=dxgi_format,
            fourcc=fourcc,
            data_offset=data_offset,
            reason="DDS format is not a supported 2D texture format",
        )
    format_name, family, bytes_per_block, srgb, default_alpha = format_tuple
    block_width = 4 if is_compressed else 1
    block_height = 4 if is_compressed else 1
    has_alpha = default_alpha or bool(pf_flags & DDS_ALPHA_PIXELS)
    try:
        levels = _build_mip_layout(
            width=width,
            height=height,
            mip_count=mip_count,
            data_offset=data_offset,
            bytes_per_block=bytes_per_block,
            payload_size=total_size,
            block_width=block_width,
            block_height=block_height,
        )
    except ValueError as exc:
        return DdsNativeInfo(
            width,
            height,
            mip_count,
            format_name,
            dxgi_format=dxgi_format,
            fourcc=fourcc,
            block_width=block_width,
            block_height=block_height,
            bytes_per_block=bytes_per_block,
            data_offset=data_offset,
            compressed_family=family,
            srgb=srgb,
            has_alpha=has_alpha,
            reason=str(exc),
        )
    if not levels:
        return DdsNativeInfo(
            width,
            height,
            mip_count,
            format_name,
            dxgi_format=dxgi_format,
            fourcc=fourcc,
            block_width=block_width,
            block_height=block_height,
            bytes_per_block=bytes_per_block,
            data_offset=data_offset,
            compressed_family=family,
            srgb=srgb,
            has_alpha=has_alpha,
            reason="DDS payload is missing or truncated",
        )
    return DdsNativeInfo(
        width,
        height,
        mip_count,
        format_name,
        dxgi_format=dxgi_format,
        fourcc=fourcc,
        block_width=block_width,
        block_height=block_height,
        bytes_per_block=bytes_per_block,
        data_offset=data_offset,
        mip_levels=levels,
        supported_compressed=is_compressed,
        supported_uncompressed=not is_compressed,
        compressed_family=family,
        srgb=srgb,
        has_alpha=has_alpha,
    )


def inspect_dds_native_path(path: Path) -> DdsNativeInfo:
    source = Path(path)
    payload_size = int(source.stat().st_size)
    with source.open("rb") as handle:
        header = handle.read(148)
    return inspect_dds_native(header, payload_size=payload_size)


def dds_native_report_dict(path: Path, info: DdsNativeInfo, *, backend: str = "dds_native_header") -> Dict[str, object]:
    return {
        "backend": backend,
        "status": "inspected" if info.width > 0 else "error",
        "source_path": str(Path(path)),
        "format": info.format_name,
        "dxgi_format": info.dxgi_format,
        "fourcc": info.fourcc,
        "width": info.width,
        "height": info.height,
        "mip_count": info.mip_count,
        "supported_compressed": info.supported_compressed,
        "supported_uncompressed": info.supported_uncompressed,
        "direct_upload_candidate": bool(info.supported_compressed or info.supported_uncompressed),
        "compressed_family": info.compressed_family,
        "srgb": info.srgb,
        "has_alpha": info.has_alpha,
        "data_offset": info.data_offset,
        "mip_levels": [
            {
                "level": level.level,
                "width": level.width,
                "height": level.height,
                "offset": level.offset,
                "byte_count": level.byte_count,
            }
            for level in info.mip_levels
        ],
        "reason": info.reason,
    }


def dds_source_path_from_report(report: Mapping[str, object]) -> str:
    source = str(report.get("source_path") or report.get("dds_source_path") or "").strip()
    return source


__all__ = [
    "DdsMipLevel",
    "DdsNativeInfo",
    "dds_native_report_dict",
    "dds_source_path_from_report",
    "inspect_dds_native",
    "inspect_dds_native_path",
]

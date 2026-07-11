from __future__ import annotations

from typing import Tuple


DDS_MAX_DIMENSION = 16_384
DDS_MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
DDS_MAX_DECODED_BYTES = 512 * 1024 * 1024


def validate_dds_dimensions(width: int, height: int, mip_count: int = 1) -> Tuple[int, int, int]:
    checked_width = int(width)
    checked_height = int(height)
    checked_mips = max(1, int(mip_count))
    if checked_width <= 0 or checked_height <= 0:
        raise ValueError(f"DDS dimensions must be positive: {checked_width}x{checked_height}.")
    if checked_width > DDS_MAX_DIMENSION or checked_height > DDS_MAX_DIMENSION:
        raise ValueError(
            f"DDS dimensions {checked_width}x{checked_height} exceed the {DDS_MAX_DIMENSION}px resource limit."
        )
    max_mips = max(checked_width, checked_height).bit_length()
    if checked_mips > max_mips:
        raise ValueError(
            f"DDS mip count {checked_mips} exceeds the maximum {max_mips} for "
            f"{checked_width}x{checked_height}."
        )
    return checked_width, checked_height, checked_mips


def checked_allocation_size(
    *factors: int,
    max_bytes: int = DDS_MAX_PAYLOAD_BYTES,
    label: str = "DDS payload",
) -> int:
    limit = int(max_bytes)
    if limit <= 0:
        raise ValueError(f"{label} limit must be positive.")
    total = 1
    for raw_factor in factors:
        factor = int(raw_factor)
        if factor <= 0:
            raise ValueError(f"{label} size factors must be positive.")
        if total > limit // factor:
            raise ValueError(f"{label} exceeds the {limit:,}-byte resource limit.")
        total *= factor
    return total


def checked_dds_surface_byte_count(
    width: int,
    height: int,
    bytes_per_unit: int,
    *,
    block_width: int = 1,
    block_height: int = 1,
    max_bytes: int = DDS_MAX_PAYLOAD_BYTES,
    label: str = "DDS payload",
) -> int:
    checked_width, checked_height, _ = validate_dds_dimensions(width, height)
    checked_block_width = int(block_width)
    checked_block_height = int(block_height)
    if checked_block_width <= 0 or checked_block_height <= 0:
        raise ValueError("DDS block dimensions must be positive.")
    units_wide = (checked_width + checked_block_width - 1) // checked_block_width
    units_high = (checked_height + checked_block_height - 1) // checked_block_height
    return checked_allocation_size(
        units_wide,
        units_high,
        int(bytes_per_unit),
        max_bytes=max_bytes,
        label=label,
    )


def checked_dds_mip_byte_counts(
    width: int,
    height: int,
    mip_count: int,
    bytes_per_unit: int,
    *,
    block_width: int = 1,
    block_height: int = 1,
    max_bytes: int = DDS_MAX_PAYLOAD_BYTES,
    label: str = "DDS payload",
) -> Tuple[int, ...]:
    level_width, level_height, checked_mips = validate_dds_dimensions(width, height, mip_count)
    limit = int(max_bytes)
    total = 0
    counts = []
    for _level in range(checked_mips):
        byte_count = checked_dds_surface_byte_count(
            level_width,
            level_height,
            bytes_per_unit,
            block_width=block_width,
            block_height=block_height,
            max_bytes=limit,
            label=label,
        )
        if byte_count > limit - total:
            raise ValueError(f"{label} exceeds the {limit:,}-byte resource limit.")
        counts.append(byte_count)
        total += byte_count
        level_width = max(1, level_width // 2)
        level_height = max(1, level_height // 2)
    return tuple(counts)


__all__ = [
    "DDS_MAX_DECODED_BYTES",
    "DDS_MAX_DIMENSION",
    "DDS_MAX_PAYLOAD_BYTES",
    "checked_allocation_size",
    "checked_dds_mip_byte_counts",
    "checked_dds_surface_byte_count",
    "validate_dds_dimensions",
]

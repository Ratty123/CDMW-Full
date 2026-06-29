"""Read-only PABC skeleton variation parser."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Mapping

from .skeleton_parser import PAR_MAGIC

PABC_RECORD_OFFSET = 0x14
PABC_RECORD_STRIDE = 196
PABC_FLOAT_COUNT = 48


@dataclass(frozen=True, slots=True)
class SkeletonVariationRecord:
    index: int
    offset: int
    bone_hash: int
    bone_index: int = -1
    bone_name: str = ""
    matrix_blocks: tuple[tuple[float, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class SkeletonVariation:
    path: str = ""
    record_count: int = 0
    records: tuple[SkeletonVariationRecord, ...] = ()
    record_offset: int = PABC_RECORD_OFFSET
    record_stride: int = PABC_RECORD_STRIDE
    tail_size: int = 0
    parser_mode: str = "pabc_hash_bound_matrix_blocks"
    confidence: str = ""

    @property
    def matched_record_count(self) -> int:
        return sum(1 for record in self.records if record.bone_index >= 0)


def parse_pabc_skeleton_variation(data: bytes, filename: str = "", *, skeleton: object | None = None) -> SkeletonVariation:
    """Parse PABC records proven by real samples as bone-hash plus 48 floats."""

    if len(data) < PABC_RECORD_OFFSET or data[:4] != PAR_MAGIC:
        raise ValueError(f"Not a valid PABC/PAR file: {data[:4]!r}")
    record_count = struct.unpack_from("<I", data, 0x10)[0]
    if record_count <= 0:
        return SkeletonVariation(path=filename, record_count=0, confidence="empty")
    table_end = PABC_RECORD_OFFSET + record_count * PABC_RECORD_STRIDE
    if table_end > len(data):
        raise ValueError(
            f"PABC record table exceeds file size: count={record_count} stride={PABC_RECORD_STRIDE} size={len(data)}"
        )

    bone_lookup = _bone_hash_lookup(skeleton)
    records: list[SkeletonVariationRecord] = []
    for index in range(record_count):
        offset = PABC_RECORD_OFFSET + index * PABC_RECORD_STRIDE
        bone_hash = struct.unpack_from("<I", data, offset)[0]
        floats = struct.unpack_from(f"<{PABC_FLOAT_COUNT}f", data, offset + 4)
        bone_index, bone_name = bone_lookup.get(bone_hash, (-1, ""))
        records.append(
            SkeletonVariationRecord(
                index=index,
                offset=offset,
                bone_hash=bone_hash,
                bone_index=bone_index,
                bone_name=bone_name,
                matrix_blocks=(
                    tuple(floats[0:16]),
                    tuple(floats[16:32]),
                    tuple(floats[32:48]),
                ),
            )
        )

    matched = sum(1 for record in records if record.bone_index >= 0)
    confidence = "bone_hash_table_stride_196"
    if bone_lookup and matched == record_count:
        confidence = "all_records_match_pab_bone_hashes"
    elif bone_lookup and matched > 0:
        confidence = "partial_records_match_pab_bone_hashes"
    return SkeletonVariation(
        path=filename,
        record_count=record_count,
        records=tuple(records),
        tail_size=max(0, len(data) - table_end),
        confidence=confidence,
    )


def _bone_hash_lookup(skeleton: object | None) -> Mapping[int, tuple[int, str]]:
    if skeleton is None:
        return {}
    result: dict[int, tuple[int, str]] = {}
    for bone in tuple(getattr(skeleton, "bones", ()) or ()):
        try:
            bone_hash = int(getattr(bone, "name_hash", 0) or 0)
            bone_index = int(getattr(bone, "index", -1))
        except (TypeError, ValueError, OverflowError):
            continue
        if bone_hash:
            result[bone_hash] = (bone_index, str(getattr(bone, "name", "") or ""))
    return result


__all__ = [
    "PABC_FLOAT_COUNT",
    "PABC_RECORD_OFFSET",
    "PABC_RECORD_STRIDE",
    "SkeletonVariation",
    "SkeletonVariationRecord",
    "parse_pabc_skeleton_variation",
]

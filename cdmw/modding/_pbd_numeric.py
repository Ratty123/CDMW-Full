"""Numeric conversions shared by the decoded PBD preparation paths."""

import math
import struct


FLOAT32_MAX = 3.4028234663852886e38


def f32(value: float) -> float:
    """Round to finite float32, rejecting unsupported non-finite calculations."""
    try:
        result = struct.unpack("<f", struct.pack("<f", value))[0]
    except OverflowError as exc:
        raise ValueError("PBD calculation exceeds finite float32 range.") from exc
    if not math.isfinite(result):
        raise ValueError("PBD calculation exceeds finite float32 range.")
    return result


def round_pbd_half(value: float) -> float:
    """Round through build 1.0.0.2944's CPU packer at 0x140E18CB0.

    Its preliminary subnormal shift drops bits before round-to-even; overflow
    encodes 0x7fff rather than IEEE infinity. Non-finite packed results are not
    accepted as simulation values by the reference implementation.
    """
    bits = struct.unpack("<I", struct.pack("<f", f32(value)))[0]
    sign = (bits >> 16) & 0x8000
    magnitude = bits & 0x7FFFFFFF
    if magnitude > 0x47FFEFFF:
        packed = sign | 0x7FFF
    else:
        if magnitude < 0x38800000:
            shift = 113 - (magnitude >> 23)
            magnitude = 0 if shift > 31 else ((magnitude & 0x7FFFFF) | 0x800000) >> shift
        else:
            magnitude = (magnitude + 0xC8000000) & 0xFFFFFFFF
        packed = sign | (((magnitude + 0xFFF + ((magnitude >> 13) & 1)) >> 13) & 0x7FFF)
    result = struct.unpack("<e", struct.pack("<H", packed))[0]
    if not math.isfinite(result):
        raise ValueError("PBD value packs to a non-finite half; its runtime result is not established.")
    return result

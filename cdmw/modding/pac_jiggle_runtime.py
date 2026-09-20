"""Decoded CPU jiggle-state handoff for build 1.0.0.2944.

These pure reference stages consume an explicit 0x220-byte runtime record, not a
PAC vertex or an attached game process. They preserve fields they do not own.
Platform motion, allocation, character/profile ownership and call scheduling
remain caller inputs. See the modding README for the native evidence chain.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence

_NO_SLOT = 0xFFFFFFFF


def _state(record: bytes) -> bytes:
    if not isinstance(record, (bytes, bytearray, memoryview)) or len(record) != 0x220:
        raise ValueError("Jiggle runtime state must contain exactly 0x220 bytes.")
    return bytes(record)


def _u32(value: int) -> int:
    if type(value) is not int or not 0 <= value <= _NO_SLOT:
        raise ValueError("Jiggle runtime indices must be unsigned 32-bit integers.")
    return value


def _f32(value: float) -> float:
    try:
        result = struct.unpack('<f', struct.pack('<f', float(value)))[0]
    except (OverflowError, TypeError, ValueError, struct.error) as exc:
        raise ValueError("Jiggle runtime values must fit finite float32 storage.") from exc
    if not math.isfinite(result):
        raise ValueError("Jiggle runtime values must fit finite float32 storage.")
    return result


def advance_jiggle_hit_window(record: bytes, delta_time: float) -> bytes:
    """Advance the CPU hit timer and shader flag bits 0/1, preserving other bytes.

    A positive timer is reduced but remains active for this update, even when it
    reaches/passes zero. The NEXT update clears it. Bit 1 reflects a nonempty
    bone-mask table; bit 0 reflects the hit window. Mode 3 therefore suppresses
    profile-mask lookup in the downstream shader until the hit window expires.
    """
    source = _state(record)
    dt = _f32(delta_time)
    if dt < 0:
        raise ValueError("Jiggle runtime delta time must not be negative.")
    remaining = _f32(struct.unpack_from('<f', source, 0x10C)[0])
    count = struct.unpack_from('<I', source, 0x158)[0]
    if count > 32:
        raise ValueError("Jiggle runtime mask count exceeds its 32-entry shader record.")
    result = bytearray(source)
    active = source[0x110] != 0
    if active:
        if remaining > 0:
            struct.pack_into('<f', result, 0x10C, _f32(remaining - dt))
        else:
            struct.pack_into('<f', result, 0x10C, 0.0)
            result[0x110] = 0
            active = False
    flags = struct.unpack_from('<I', source, 0x154)[0]
    flags = (flags & 0xFFFFFFFC) | int(active) | (2 if count else 0)
    struct.pack_into('<I', result, 0x154, flags)
    return bytes(result)


def refresh_jiggle_runtime_resources(
    record: bytes, *, shader_data_index: int, state_buffer_offset: int,
    command_offset: int, profile_settings: Sequence[float],
    hit_settings: Sequence[float], runtime_overrides: Sequence[float] | None = None,
) -> bytes:
    """Refresh changed resource slots and the CPU-selected settings block.

    Settings must already be resolved by the caller's descriptor lookup, including
    missing-name fallback. Hit settings win while byte 0x110 is nonzero. A runtime
    override replaces its corresponding float only when strictly positive.
    Unchanged slots skip the lookup/copy, just as the CPU branch does.
    """
    source = _state(record)
    new_slots = tuple(_u32(value) for value in (shader_data_index, state_buffer_offset, command_offset))
    offsets = (0x21C, 0x120, 0x10)
    old_slots = tuple(struct.unpack_from('<I', source, offset)[0] for offset in offsets)
    if old_slots == new_slots:
        return source
    selected = hit_settings if source[0x110] else profile_settings
    if len(selected) != 8 or runtime_overrides is not None and len(runtime_overrides) != 8:
        raise ValueError("Jiggle runtime settings need eight floats per block.")
    values = [_f32(value) for value in selected]
    if runtime_overrides is not None:
        for index, value in enumerate(runtime_overrides):
            override = _f32(value)
            if override > 0:
                values[index] = override
    result = bytearray(source)
    struct.pack_into('<8f', result, 0x134, *values)
    struct.pack_into('<I', result, 0x130, old_slots[1])
    for offset, value in zip(offsets, new_slots, strict=True):
        struct.pack_into('<I', result, offset, value)
    return bytes(result)


def jiggle_runtime_shader_upload(record: bytes) -> tuple[int, bytes] | None:
    """Return the exact 264-byte shader slice only for an assigned upload slot."""
    source = _state(record)
    index = struct.unpack_from('<I', source, 0x21C)[0]
    return None if index == _NO_SLOT else (index, source[0x114:0x21C])


def jiggle_runtime_can_release(record: bytes, *, empty_profile_id: int) -> bool:
    """Decoded release predicate after platform/timer/resource updates.

    The empty interned profile identifier is explicit. This predicate alone does
    not update platform transforms, dispose allocations or decide shader dispatch.
    """
    source = _state(record)
    if source[0x108] or source[0x110]:
        return False
    if struct.unpack_from('<I', source, 0x14)[0] != _u32(empty_profile_id):
        return False
    return all(struct.unpack_from('<I', source, offset)[0] == _NO_SLOT
               for offset in (0x21C, 0x10, 0x130, 0x120))

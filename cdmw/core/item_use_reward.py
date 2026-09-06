"""The ItemUseInfo DropSet-reference variant and its ItemInfo consumer list.

The common use header and nine-byte condition references are kept unchanged.
Inline reward variants are refused until their complete boundaries are decoded.
"""
from dataclasses import dataclass
import struct
from cdmw.core.new_item_record import Cursor, RecordError, text_bytes


@dataclass(frozen=True, slots=True)
class ItemUseReward:
    key: int
    name: str
    use_header: bytes
    conditions: tuple[bytes, ...]
    reward_key: int
    tail: bytes


def parse_item_use_reward(raw):
    reader = Cursor(raw)
    key, name = reader.unpack("I"), reader.text()
    if reader.take(1) != b"\0":
        raise RecordError("Blocked item use")
    header = reader.take(19)
    if header[0] != 2:
        raise RecordError("This item-use variant does not grant a reward set")
    conditions = tuple(reader.take(9) for _ in range(reader.count()))
    if reader.take(1) != b"\1":
        raise RecordError("Inline item-use rewards are not decoded")
    reward = reader.unpack("I")
    tail = reader.take(7)
    if tail[:2] != b"\0\x0e" or tail[-1] not in (0, 1):
        raise RecordError("Unsupported item-use reward metadata")
    reader.finish()
    return ItemUseReward(key, name, header, conditions, reward, tail)


def encode_item_use_reward(row):
    result = (struct.pack("<I", row.key) + text_bytes(row.name) + b"\0" + row.use_header
              + struct.pack("<I", len(row.conditions)) + b"".join(row.conditions)
              + b"\1" + struct.pack("<I", row.reward_key) + row.tail)
    if parse_item_use_reward(result) != row:
        raise RecordError("Edited item-use reward did not round-trip")
    return result


def item_use_references(row, known_keys):
    """Return the bounded, nonempty ItemInfo use-list or reject its shape."""
    offset = row.prefix_end + 12
    stop = row.stat_block_offset if row.stat_block_offset is not None else len(row.raw)
    if offset + 4 > stop:
        raise RecordError("ItemInfo use-list boundary is not proven")
    count = struct.unpack_from("<I", row.raw, offset)[0]
    if not 1 <= count <= 128 or offset + 4 + count * 4 > stop:
        raise RecordError("ItemInfo has no supported nonempty use list")
    keys = struct.unpack_from(f"<{count}I", row.raw, offset + 4)
    if any(key not in known_keys for key in keys):
        raise RecordError("ItemInfo use-list references are not proven")
    return offset, keys


def replace_item_use_reference(row, known_keys, index, old_key, new_key):
    offset, keys = item_use_references(row, known_keys)
    if not 0 <= index < len(keys) or keys[index] != old_key:
        raise RecordError("The selected reward consumer has changed")
    result = bytearray(row.raw)
    struct.pack_into("<I", result, offset + 4 + 4 * index, new_key)
    return bytes(result)

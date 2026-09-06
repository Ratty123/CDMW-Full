"""Item-producing DropSet records with proven entry boundaries.

Non-item result types and unfamiliar entry variants are deliberately rejected.
The source's roll policy and derived cache bytes are preserved. Raw weights are
not presented as percentages: their interpretation depends on that roll policy.
"""
from dataclasses import dataclass, replace
import struct

from cdmw.core.new_item_record import Cursor, RecordError, text_bytes


@dataclass(frozen=True, slots=True)
class ItemReward:
    item_key: int
    weight: int
    sub_weight: int
    minimum: int
    maximum: int
    enhancement: int = -1
    # Four fixed references in DropInfoData. Keep their stored order; the
    # player/owner scope and tag interpretation are not authoring controls.
    condition_references: tuple[int, int, int, int] = (0, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class ItemRewardSet:
    key: int
    name: str
    policy: bytes
    entries: tuple[ItemReward, ...]
    cache: bytes
    total_weight: int
    skip_weight: int
    original_string: str

    def with_entries(self, entries, *, key=None, name=None):
        entries = tuple(entries)
        # Current conditional rows use an empty diagnostic source string.
        # Do not invent source-language condition expressions when cloning them.
        conditional = any(any(r.condition_references) for r in entries)
        if conditional and self.original_string:
            raise RecordError("Conditional reward source expressions are not decoded")
        source = "" if conditional else ";".join(f"Item({r.item_key},{r.enhancement},{r.minimum},{r.maximum})" for r in entries) + ";"
        return replace(self, key=self.key if key is None else key, name=self.name if name is None else name,
                       entries=entries, total_weight=sum(r.weight for r in entries), original_string=source)


def parse_item_reward_set(raw):
    reader = Cursor(raw)
    key, name = reader.unpack("I"), reader.text()
    if reader.take(1) != b"\0":
        raise RecordError("Blocked reward definition")
    policy = reader.take(13)
    entries = []
    for _ in range(reader.count()):
        if reader.unpack("B") != 1:
            raise RecordError("Reward result type is not a supported item result")
        item, result_type = reader.unpack("QB")
        if result_type != 0:
            raise RecordError(f"Non-item reward result type {result_type} is not decoded")
        conditions = reader.unpack("IIII")
        weight, sub, low, high, level, cached_item = reader.unpack("QQQQhI")
        if item != cached_item or not item or low > high or level < -1:
            raise RecordError("Item reward reference or range is not decoded")
        entries.append(ItemReward(item, weight, sub, low, high, level, conditions))
    cache = reader.take(10)
    if cache not in (bytes(10), b"\xff\xff" + bytes(8)):
        raise RecordError("Extended reward cache is not decoded")
    total, skip = reader.unpack("QQ")
    original = reader.text()
    if reader.take(1) != b"\0":
        raise RecordError("Reward-level condition is not decoded")
    reader.finish()
    return ItemRewardSet(key, name, policy, tuple(entries), cache, total, skip, original)


def encode_item_reward_set(row):
    if len(row.policy) != 13 or len(row.cache) != 10:
        raise RecordError("Invalid reward policy or cache")
    out = bytearray(struct.pack("<I", row.key) + text_bytes(row.name) + b"\0" + row.policy)
    out += struct.pack("<I", len(row.entries))
    for entry in row.entries:
        if not 0 < entry.item_key <= 0xffffffff or not 0 <= entry.minimum <= entry.maximum <= 0xffffffffffffffff:
            raise RecordError("Invalid item reward quantity or identity")
        if len(entry.condition_references) != 4 or any(not 0 <= key <= 0xffffffff for key in entry.condition_references):
            raise RecordError("Invalid reward condition references")
        out += b"\1" + struct.pack("<QBIIII", entry.item_key, 0, *entry.condition_references)
        out += struct.pack("<QQQQhI", entry.weight, entry.sub_weight, entry.minimum, entry.maximum,
                           entry.enhancement, entry.item_key)
    out += row.cache + struct.pack("<QQ", row.total_weight, row.skip_weight) + text_bytes(row.original_string) + b"\0"
    result = bytes(out)
    if parse_item_reward_set(result) != row:
        raise RecordError("Edited reward did not round-trip")
    return result

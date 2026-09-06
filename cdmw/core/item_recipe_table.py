"""Bounded MultiChange authoring: fixed/group ingredients and DropSet outputs.

Presentation fields and elemental-status labels retain their exact localization
references. Nonempty elemental-material/condition arrays remain unsupported.
"""
from dataclasses import dataclass
import struct

from cdmw.core.new_item_record import Cursor, RecordError, text_bytes


@dataclass(frozen=True, slots=True)
class RecipeIngredient:
    item_key: int
    character_key: int = 0
    gimmick_key: int = 0
    quantity: int = 1
    coupon_quantity: int = 0
    enhancement: int = 0


@dataclass(frozen=True, slots=True)
class RecipeGroupIngredient:
    group_key: int
    quantity: int
    enhancement: int = 0


@dataclass(frozen=True, slots=True)
class RecipeElementalStatus:
    key: int
    label: bytes


@dataclass(frozen=True, slots=True)
class ItemRecipe:
    key: int
    name: str
    tool_key: int
    consume_type: int
    elemental_statuses: tuple[RecipeElementalStatus, ...]
    knowledge_key: int
    craft_tag: str
    flags: bytes
    ingredients: tuple[RecipeIngredient, ...]
    group_ingredients: tuple[RecipeGroupIngredient, ...]
    description: bytes
    presentation: bytes
    reward_keys: tuple[int, ...]
    additional_reward_keys: tuple[int, ...] = ()


def _local_string(reader):
    """A LocalStringInfo reference: nine-byte identity and counted UTF-8 text."""
    start = reader.pos
    identity = reader.take(9)
    if identity[:2] not in (b"\x0d\xd0", b"\x0d\xd2", b"\0\0"):
        raise RecordError("Unsupported recipe localization identity")
    if identity[:2] == b"\0\0" and identity != bytes(9):
        raise RecordError("Unsupported empty recipe localization identity")
    reader.text()
    return reader.raw[start:reader.pos]


def _presentation(reader):
    # Two LocalStringInfo values surround three fixed StringInfo references.
    # The last localized value is nonempty on the three infinite-stat recipes;
    # the third reference is nonzero on large serving recipe variants.
    start = reader.pos
    _local_string(reader)
    reader.take(12)
    _local_string(reader)
    return reader.raw[start:reader.pos]


def parse_item_recipe(raw):
    reader = Cursor(raw)
    key, name = reader.unpack("I"), reader.text()
    if reader.take(1) != b"\0":
        raise RecordError("Blocked recipe")
    tool, consume = reader.unpack("HB")
    elemental = tuple(RecipeElementalStatus(reader.unpack("I"), _local_string(reader))
                      for _ in range(reader.count()))
    knowledge = reader.unpack("I")
    tag = reader.text()
    flags = reader.take(5)
    if any(flag not in (0, 1) for flag in flags):
        raise RecordError("Unsupported recipe flags")
    ingredients = tuple(RecipeIngredient(*reader.unpack("IIIQQH")) for _ in range(reader.count()))
    groups = tuple(RecipeGroupIngredient(*reader.unpack("HQH")) for _ in range(reader.count()))
    if reader.count() or reader.count():
        raise RecordError("Recipe elemental-state or condition arrays are not decoded")
    description = _local_string(reader)
    presentation = _presentation(reader)
    rewards = tuple(reader.unpack("I") for _ in range(reader.count()))
    additional = tuple(reader.unpack("I") for _ in range(reader.count()))
    reader.finish()
    return ItemRecipe(key, name, tool, consume, elemental, knowledge, tag, flags, ingredients,
                      groups, description, presentation, rewards, additional)


def encode_item_recipe(row):
    out = bytearray(struct.pack("<I", row.key) + text_bytes(row.name) + b"\0")
    out += struct.pack("<HBI", row.tool_key, row.consume_type, len(row.elemental_statuses))
    for status in row.elemental_statuses:
        out += struct.pack("<I", status.key) + status.label
    out += struct.pack("<I", row.knowledge_key)
    out += text_bytes(row.craft_tag) + row.flags + struct.pack("<I", len(row.ingredients))
    for ingredient in row.ingredients:
        out += struct.pack("<IIIQQH", ingredient.item_key, ingredient.character_key, ingredient.gimmick_key,
                           ingredient.quantity, ingredient.coupon_quantity, ingredient.enhancement)
    out += struct.pack("<I", len(row.group_ingredients))
    for ingredient in row.group_ingredients:
        out += struct.pack("<HQH", ingredient.group_key, ingredient.quantity, ingredient.enhancement)
    out += bytes(8) + row.description + row.presentation
    for keys in (row.reward_keys, row.additional_reward_keys):
        out += struct.pack("<I", len(keys)) + b"".join(struct.pack("<I", key) for key in keys)
    result = bytes(out)
    if parse_item_recipe(result) != row:
        raise RecordError("Edited recipe did not round-trip")
    return result

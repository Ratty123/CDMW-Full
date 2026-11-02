"""Closed reads and constrained in-place edits for compact static data tables.

Every table listed in the compact schema decodes through
`cdmw.core.compact_static.read_compact_layout`; this module turns a header/body
pair into keyed records with their top-level fields, and edits only the
fixed-width fields named in `EDITABLE_FIELDS`. An edit keeps every byte length,
so the row directory is unchanged, and each edited row is decoded again with the
closed schema before the result is returned. Nested members (a value inside a
list element, such as one drop entry's chance) are addressed by their path,
for example `("_list", 3, "_percent")`, and editable when `EDITABLE_MEMBERS`
names their owner and member. Units and gameplay meaning are not inferred: a
field is editable because its storage width is proven on every shipped row,
not because its effect in game is known.
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from cdmw.core._compact_static_schema import READERS, TABLE_READERS
from cdmw.core.compact_static import read_compact_layout
from cdmw.core.new_item_record import Cursor, RecordError
from cdmw.core.structured_binary_editor import parse_pabgh_table

# Reader roots that are not whole tables.
_NON_TABLE_KINDS = frozenset({"stockdata"})
# Tables renamed by the October 2026 data update; old archives keep the old stem.
LEGACY_TABLE_STEMS = MappingProxyType({"skillinfo": "skill", "reserveslotinfo": "reserveslot"})

DECODED_TABLES = frozenset(kind for kind in TABLE_READERS if kind not in _NON_TABLE_KINDS)


class StaticTableError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FieldRule:
    """A fixed-width top-level field that may be rewritten in place."""

    kind: str  # "uint", "bool" or "float32"
    width: int
    minimum: float
    maximum: float
    note: str


def _uint(width, minimum, maximum, note):
    return FieldRule("uint", width, minimum, maximum, note)


# Widths are the serializer's reads, proven on every decoded shipped row
# (1.0.0.3479 base and DLC). Bounds keep values inside the storage type and
# away from sentinels; they are not gameplay limits.
EDITABLE_FIELDS: Mapping[str, Mapping[str, FieldRule]] = MappingProxyType({
    "inventory": MappingProxyType({
        "_defaultSlotCount": _uint(2, 1, 65535, "Slots a new save starts with (shipped 1-300)."),
        "_maxSlotCount": _uint(2, 1, 65535, "Slot ceiling the bag can grow to (shipped 3-1,400)."),
    }),
    "skill": MappingProxyType({
        "_maxLevel": _uint(4, 1, 1000, "Highest learnable level (shipped 1-30)."),
        "_cooltime": _uint(4, 0, 1_000_000, "Raw cooldown value; units unknown (shipped 0-20)."),
        "_allowSkillWithLowResource": FieldRule("bool", 1, 0, 1, "Allow use without enough resource."),
    }),
    "wantedinfo": MappingProxyType({
        "_increasePrice": _uint(8, 0, 1_000_000_000_000, "Bounty increase per offence (shipped 30-1,500)."),
    }),
    "mercenaryinfo": MappingProxyType({
        "_defaultLimitHireCount": _uint(4, 0, 0xFFFFFFFF, "Default hire limit; 4294967295 on uncapped rows."),
        "_maxLimitHireCount": _uint(4, 0, 0xFFFFFFFF, "Hire limit ceiling; 4294967295 on every shipped row."),
        "_defaultLimitSummonCount": _uint(4, 0, 0xFFFFFFFF, "Default summon limit (shipped 1-50)."),
    }),
    "characterinfo": MappingProxyType({
        "_characterScale": FieldRule("float32", 4, 0.01, 1000.0, "Model scale (shipped 0.06-300)."),
        "_callMercenaryCoolTime": _uint(8, 0, 1_000_000_000, "Raw companion call cooldown (shipped 0-9,000)."),
    }),
    "gameplayvariableinfo": MappingProxyType({
        "_initialVariable": FieldRule("bool", 1, 0, 1, "Initial state of the global gameplay switch."),
    }),
})


# Nested members by (owning class, member). Each width holds at every occurrence in
# every decoded shipped row; ranges stay inside the shipped values' scale.
_PERCENT = "Chance in millionths: 1,000,000 is every time (shipped {})."
EDITABLE_MEMBERS: Mapping[str, Mapping[tuple[str, str], FieldRule]] = MappingProxyType({
    "dropsetinfo": MappingProxyType({
        ("DropInfoData", "_percent"): _uint(8, 0, 1_000_000, _PERCENT.format("100-1,000,000; 17,065 of 21,709 at 1,000,000")),
        ("DropInfoData", "_minValue"): _uint(8, 0, 1_000_000, "Smallest quantity dropped (shipped mostly 1-5)."),
        ("DropInfoData", "_maxValue"): _uint(8, 0, 1_000_000, "Largest quantity dropped (shipped mostly 1-5)."),
    }),
    "characterinfo": MappingProxyType({
        ("CharacterEquipmentData", "_deadDropPercent"): _uint(8, 0, 1_000_000, _PERCENT.format("0-1,000,000, mostly 30,000")),
        ("CharacterEquipmentData", "_throwDropPercent"): _uint(8, 0, 1_000_000, _PERCENT.format("0-1,000,000, mostly 30,000")),
        ("CharacterLevelData", "_experience"): _uint(8, 0, 1_000_000_000, "Raw experience value of this level (shipped 0-500)."),
    }),
})


def editable_kinds() -> frozenset[str]:
    return frozenset(EDITABLE_FIELDS) | frozenset(EDITABLE_MEMBERS)


@dataclass(frozen=True, slots=True)
class StaticMember:
    """One editable nested value: `target` is its path ending in the member name."""

    owner: str
    target: tuple
    start: int
    end: int
    value: int
    rule: FieldRule


@dataclass(frozen=True, slots=True)
class StaticField:
    name: str
    shape: str  # "u8", "u16", "u32", "u64", "bytes<N>", "text" or "nested"
    start: int
    end: int
    value: object


@dataclass(frozen=True, slots=True)
class StaticRecord:
    key: int
    name: str
    start: int
    end: int
    fields: tuple[StaticField, ...]
    members: tuple[StaticMember, ...] = ()

    def field(self, name: str) -> StaticField:
        for field in self.fields:
            if field.name == name:
                return field
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class StaticTable:
    kind: str
    records: tuple[StaticRecord, ...]
    refused: tuple[tuple[int, str], ...]
    row_count: int


@dataclass(frozen=True, slots=True)
class StaticFieldChange:
    key: int
    field: str | tuple
    before: object
    after: object


@dataclass(frozen=True, slots=True)
class TableFieldEdit:
    """One requested value: a whitelisted field or nested member of one row of one table."""

    table: str
    key: int
    target: str | tuple
    value: int | float


@dataclass(frozen=True, slots=True)
class StaticTableEdit:
    kind: str
    header: bytes
    body: bytes
    changes: tuple[StaticFieldChange, ...]


# A table file stem: the table name, optionally a DLC layer suffix. Nothing else, so a
# stem can never carry a path component into an output file name.
_STEM = re.compile(r"[a-z0-9_]+(\.dlc_[0-9]+)?")


def table_kind_for_stem(stem: str) -> str | None:
    """The schema table for a file stem such as `skill` or `skill.dlc_01`."""

    text = str(stem or "").casefold()
    if not _STEM.fullmatch(text):
        return None
    base = text.split(".", 1)[0]
    base = LEGACY_TABLE_STEMS.get(base, base)
    return base if base in DECODED_TABLES else None


def require_table_kind(stem: str) -> str:
    kind = table_kind_for_stem(stem)
    if kind is None:
        raise StaticTableError(f"{stem} has no closed record schema.")
    return kind


def require_same_archive(header_index, body_index) -> None:
    """A pair's halves come from one archive index; DLC layers replace whole pairs."""

    if str(header_index).casefold() != str(body_index).casefold():
        raise StaticTableError("A static table's header and body must come from the same archive.")


def _resolved_shape(op):
    while op[0] == "call" or (op[0] == "seq" and len(op) == 2):
        op = READERS[op[1]] if op[0] == "call" else op[1]
    return op


def root_ops(kind):
    """The table root's operations, stepping through a root that only calls another reader."""
    op = READERS[TABLE_READERS[kind]]
    while op[0] == "seq" and len(op) == 2 and op[1][0] == "call":
        op = READERS[op[1][1]]
    return op[1:] if op[0] == "seq" else (op,)


def _top_level_shapes(kind):
    """Each top-level member's consecutive reads; some members are two or more reads."""
    shapes = {}
    for op in root_ops(kind):
        if op[0] == "field":
            shapes.setdefault(op[2], []).append(_resolved_shape(op[3]))
    return shapes


def _text(data):
    """A u32 length and UTF-8 text whose span the closed schema already bounded."""
    cursor = Cursor(data)
    return cursor.take(cursor.count(limit=len(data))).decode("utf-8")


def _field_value(parts, data):
    if len(parts) > 1:
        widths = [part[1] if part[0] == "raw" else None for part in parts]
        if None in widths or sum(widths) != len(data) or any(w not in (1, 2, 4, 8) for w in widths):
            return "nested", len(data)
        values, at = [], 0
        for width in widths:
            values.append(int.from_bytes(data[at:at + width], "little"))
            at += width
        return "+".join(f"u{w * 8}" for w in widths), tuple(values)
    shape = parts[0]
    if shape[0] == "raw" and len(data) in (1, 2, 4, 8):
        return f"u{len(data) * 8}", int.from_bytes(data, "little")
    if shape[0] == "raw":
        return f"bytes<{len(data)}>", data.hex()
    if shape[0] == "text":
        return "text", _text(data)
    return "nested", len(data)


def decode_record(kind: str, raw: bytes, *, start: int = 0, key_width: int = 4) -> StaticRecord:
    if kind not in DECODED_TABLES:
        raise StaticTableError(f"{kind} has no closed record schema.")
    layout = read_compact_layout(raw, kind)
    shapes = _top_level_shapes(kind)
    fields = []
    for name, span in layout.fields.items():
        shape_name, value = _field_value(shapes.get(name, [("nested",)]), raw[span.start:span.end])
        fields.append(StaticField(name, shape_name, start + span.start, start + span.end, value))
    fields.sort(key=lambda field: field.start)
    name = _text(layout.data("_stringKey")) if "_stringKey" in layout.fields else ""
    rules = EDITABLE_MEMBERS.get(kind, {})
    members = tuple(
        StaticMember(m.owner, tuple(m.path) + (m.name,), start + m.span.start, start + m.span.end,
                     int.from_bytes(raw[m.span.start:m.span.end], "little"), rules[(m.owner, m.name)])
        for m in layout.members if (m.owner, m.name) in rules and m.span.size == rules[(m.owner, m.name)].width)
    return StaticRecord(layout.integer("_key", width=key_width), name, start, start + len(raw), tuple(fields), members)


def decode_static_table(kind: str, header: bytes, body: bytes) -> StaticTable:
    """Decode every row; rows the closed schema refuses are reported, not guessed."""

    if kind not in DECODED_TABLES:
        raise StaticTableError(f"{kind} has no closed record schema.")
    table = parse_pabgh_table(bytes(header), payload=bytes(body))
    records, refused = [], []
    spans = table.row_spans(len(body))
    for directory, start, end in spans:
        try:
            record = decode_record(kind, body[start:end], start=start, key_width=table.key_width)
            # Composite-key tables keep only the leading u32 in row_id.
            if record.key != int.from_bytes(directory.key or directory.row_id.to_bytes(table.key_width, "little"), "little"):
                raise RecordError("The row's inline key differs from its directory key.")
        except (RecordError, StaticTableError, UnicodeDecodeError) as exc:
            refused.append((directory.row_id, str(exc)))
            continue
        records.append(record)
    return StaticTable(kind, tuple(records), tuple(refused), len(spans))


def _encode(rule: FieldRule, value) -> tuple[bytes, object]:
    if rule.kind == "float32":
        number = float(value)
        if not math.isfinite(number) or not rule.minimum <= number <= rule.maximum:
            raise StaticTableError(f"{number} is outside {rule.minimum}-{rule.maximum}.")
        return struct.pack("<f", number), struct.unpack("<f", struct.pack("<f", number))[0]
    if isinstance(value, bool):
        value = int(value)
    if not isinstance(value, int):
        raise StaticTableError(f"{value!r} is not an integer.")
    if not rule.minimum <= value <= rule.maximum:
        raise StaticTableError(f"{value} is outside {int(rule.minimum)}-{int(rule.maximum)}.")
    return value.to_bytes(rule.width, "little"), value


def _current(rule: FieldRule, data: bytes):
    if rule.kind == "float32":
        return struct.unpack("<f", data)[0]
    return int.from_bytes(data, "little")


def _member_target(kind, layout, target, member_rules, key):
    found = [m for m in layout.members if tuple(m.path) + (m.name,) == tuple(target)]
    if len(found) != 1:
        raise StaticTableError(f"{kind} row {key} has {len(found)} values at {target}; exactly one is required.")
    member = found[0]
    rule = member_rules.get((member.owner, member.name))
    if rule is None:
        raise StaticTableError(f"{kind} {member.owner}.{member.name} is not an editable field.")
    if member.span.size != rule.width:
        raise StaticTableError(f"{kind} {member.owner}.{member.name} does not have the proven {rule.width}-byte width.")
    return rule, member.span


def apply_field_edits(
    kind: str,
    header: bytes,
    body: bytes,
    edits: Mapping[tuple[int, str], object],
) -> StaticTableEdit:
    """Rewrite whitelisted fixed-width fields in place and prove nothing else moved."""

    rules = EDITABLE_FIELDS.get(kind, {})
    member_rules = EDITABLE_MEMBERS.get(kind, {})
    if not rules and not member_rules:
        raise StaticTableError(f"{kind} has no editable fields.")
    if not edits:
        raise StaticTableError("No edits were requested.")
    table = parse_pabgh_table(bytes(header), payload=bytes(body))
    spans, keys, ambiguous = {}, {}, set()
    for directory, start, end in table.row_spans(len(body)):
        if directory.row_id in spans:
            ambiguous.add(directory.row_id)
        spans[directory.row_id] = (start, end)
        keys[directory.row_id] = directory.key or directory.row_id.to_bytes(table.key_width, "little")
    edited = bytearray(body)
    changes, rows = [], {}
    for (key, field), value in sorted(edits.items(), key=lambda item: (item[0][0], str(item[0][1]))):
        rule = rules.get(field) if isinstance(field, str) else None
        if rule is None and not isinstance(field, tuple):
            raise StaticTableError(f"{kind}.{field} is not an editable field.")
        if key not in spans:
            raise StaticTableError(f"{kind} has no row with key {key}.")
        if key in ambiguous:
            raise StaticTableError(f"{kind} lists key {key} more than once.")
        start, end = spans[key]
        layout = read_compact_layout(bytes(body[start:end]), kind)
        if layout.data("_key") != keys[key]:
            raise StaticTableError(f"{kind} row {key} carries a different inline key; the header does not match the body.")
        if isinstance(field, tuple):
            rule, span = _member_target(kind, layout, field, member_rules, key)
        else:
            span = layout.fields.get(field)
            if span is None or span.size != rule.width:
                raise StaticTableError(f"{kind}.{field} does not have the proven {rule.width}-byte width in row {key}.")
        payload, stored = _encode(rule, value)
        before = _current(rule, layout.raw[span.start:span.end])
        edited[start + span.start:start + span.end] = payload
        rows.setdefault(key, []).append((start + span.start, start + span.end))
        changes.append(StaticFieldChange(key, field, before, stored))
    if kind == "inventory":
        for key in rows:
            start, end = spans[key]
            layout = read_compact_layout(bytes(edited[start:end]), kind)
            if layout.integer("_defaultSlotCount", width=2) > layout.integer("_maxSlotCount", width=2):
                raise StaticTableError(f"Inventory {key}: default slots exceed the maximum.")
    for key, ranges in rows.items():
        start, end = spans[key]
        read_compact_layout(bytes(edited[start:end]), kind)
        for position in range(start, end):
            if edited[position] != body[position] and not any(lo <= position < hi for lo, hi in ranges):
                raise StaticTableError(f"Edit of row {key} changed bytes outside its fields.")
    return StaticTableEdit(kind, bytes(header), bytes(edited), tuple(changes))


__all__ = [
    "DECODED_TABLES",
    "EDITABLE_FIELDS",
    "EDITABLE_MEMBERS",
    "StaticMember",
    "editable_kinds",
    "FieldRule",
    "LEGACY_TABLE_STEMS",
    "StaticField",
    "StaticFieldChange",
    "StaticRecord",
    "StaticTable",
    "StaticTableEdit",
    "StaticTableError",
    "TableFieldEdit",
    "apply_field_edits",
    "decode_record",
    "decode_static_table",
    "require_same_archive",
    "require_table_kind",
    "root_ops",
    "table_kind_for_stem",
]

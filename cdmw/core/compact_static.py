"""Bounded, address-free layouts for the DLC static-table serialization."""
from types import MappingProxyType

from cdmw.core._compact_static_schema import READERS, TABLE_READERS
from cdmw.core.new_item_record import Cursor, RecordError


# (record bytes, walk steps). Faction and quest rows carry whole relation and
# stage graphs (largest shipped rows about 204 KiB and 1.5 MiB); deep condition
# trees and gimmick scripts need more steps or bytes than an item row.
_RECORD_LIMITS = {
    "faction": (1 << 20, 4_000_000),
    "questinfo": (4 << 20, 16_000_000),
    "conditioninfo": (65536, 1_000_000),
    "gimmickinfo": (1 << 20, 4_000_000),
    "gimmickgroupinfo": (1 << 20, 4_000_000),
    "factionnodespawninfo": (1 << 20, 4_000_000),
}
_DEFAULT_LIMITS = (65536, 200000)
# Condition logic nests AND/OR/NOT nodes; each level costs about four walk levels
# and the deepest shipped condition needs about 300.
_DEPTH_LIMIT = 400

# 1.0.0.3527 inserts two UTF-8 strings after _filterType. The executable hashes
# the socket name after reading its length and bytes; the wire value is text.
# Keep the earlier grammar for old packages and require exactly one complete walk.
# The two corrected spelling labels in that executable retain their existing API names.
_ITEMINFO_BASE = READERS[TABLE_READERS["iteminfo"]]
_SOUND_INSERT = next(i + 1 for i, op in enumerate(_ITEMINFO_BASE)
                     if isinstance(op, tuple) and op[:3] == ("field", "ItemInfo", "_filterType"))
_ITEMINFO_3527 = (
    *_ITEMINFO_BASE[:_SOUND_INSERT],
    ("field", "ItemInfo", "_soundNameOnMaxCharged", ("text",)),
    ("field", "ItemInfo", "_soundSocketNameOnMaxCharged", ("text",)),
    *_ITEMINFO_BASE[_SOUND_INSERT:],
)
_DROPSET_BASE = READERS[TABLE_READERS["dropsetinfo"]]
_VEHICLE_INSERT = next(i + 1 for i, op in enumerate(_DROPSET_BASE)
                       if isinstance(op, tuple) and op[:3] == ("field", "DropSetInfo", "_isEqualPercent"))
_DROPSET_3663 = (
    *_DROPSET_BASE[:_VEHICLE_INSERT],
    ("field", "DropSetInfo", "_isToVehicle", ("raw", 1)),
    *_DROPSET_BASE[_VEHICLE_INSERT:],
)


def read_compact_layout(raw, kind="iteminfo"):
    programs = (("pre-3527", _ITEMINFO_BASE), ("3527", _ITEMINFO_3527)) if kind == "iteminfo" else ((kind, None),)
    candidates, errors, failures = [], [], []
    for label, program in programs:
        drop_seen = set()
        for enchant_width in (2, 3):
            # A row without DropInfoData has identical layouts. Do not walk it twice.
            if enchant_width == 3 and not drop_seen and kind != "dropsetinfo":
                break
            try:
                selected = _DROPSET_3663 if kind == "dropsetinfo" and enchant_width == 3 else program
                layout = _read_compact_layout(raw, kind, selected, enchant_width=enchant_width, drop_seen=drop_seen)
                if layout not in candidates:
                    candidates.append(layout)
            except (RecordError, UnicodeError) as exc:
                errors.append(f"{label}: {exc}")
                failures.append(exc)
    if len(candidates) != 1:
        if kind != "iteminfo":
            if not candidates:
                raise failures[0]
            raise RecordError("Unsupported or ambiguous compact static layout.")
        detail = "; ".join(errors) if not candidates else "both known layouts match"
        raise RecordError(f"Unsupported or ambiguous compact ItemInfo layout ({detail}).")
    return candidates[0]


def _read_compact_layout(raw, kind, program=None, *, enchant_width=2, drop_seen=None):
    from cdmw.core.item_layout import ItemLayout, Member, Span

    size_limit, step_limit = _RECORD_LIMITS.get(kind, _DEFAULT_LIMITS)
    if kind not in TABLE_READERS or not isinstance(raw, (bytes, bytearray)) or not 1 <= len(raw) <= size_limit:
        raise RecordError("Unsupported compact static record.")
    cursor = Cursor(raw)
    fields, members = {}, []
    steps = 0

    def walk(op, path=(), depth=0):
        nonlocal steps
        steps += 1
        if depth > _DEPTH_LIMIT or steps > step_limit:
            raise RecordError("Compact static record exceeds the layout limit.")
        code = op[0]
        if code == 'unsupported':
            raise RecordError('This compact static variant has not been qualified.')
        if code == "raw":
            cursor.take(op[1])
        elif code == "text":
            # Gimmick tables embed state-handler XML longer than the 4 KiB item-text bound.
            cursor.take(cursor.count(limit=size_limit)).decode("utf-8")
        elif code == "seq":
            for child in op[1:]:
                walk(child, path, depth + 1)
        elif code == "call":
            walk(READERS[op[1]], path, depth + 1)
        elif code in ("optional", "presence"):
            present = cursor.unpack("B")
            if present not in (0, 1):
                raise RecordError("Invalid compact static presence flag.")
            if present:
                walk(READERS[op[1]] if code == "optional" else op[1], path, depth + 1)
        elif code in ("array", "repeat"):
            count = int.from_bytes(cursor.take(op[1]), "little") if code == "array" else op[1]
            if not 0 <= count <= 65536:
                raise RecordError(f"Compact static list exceeds the supported bound at {path}.")
            for index in range(count):
                walk(op[2], path + (index,), depth + 1)
        elif code == "field":
            _, owner, name, child = op
            if owner == "DropInfoData" and name == "_enchantLevel":
                # Build 1.0.0.3663 reads a further opaque byte after the i16
                # enchantment level, before the result-specific reference.
                # It shares the executable's enchantment field/error label.
                child = ("raw", enchant_width)
                if drop_seen is not None:
                    drop_seen.add(True)
            start = cursor.pos
            try:
                walk(child, path + (name,), depth + 1)
            except (RecordError, UnicodeError) as exc:
                if kind == "iteminfo" and not path:
                    raise RecordError(f"ItemInfo.{name} at row offset 0x{start:X}: {exc}") from exc
                raise
            span = Span(start, cursor.pos)
            if not path:
                previous = fields.get(name)
                if previous is not None:
                    if previous.end != start:
                        raise RecordError("Ambiguous compact static field.")
                    span = Span(previous.start, cursor.pos)
                fields[name] = span
            else:
                members.append(Member(owner, name, path, span))
        elif code in ("variant", "tagged"):
            tag = int.from_bytes(cursor.take(op[1]), "little")
            if tag not in op[-1]:
                raise RecordError("Unsupported compact static discriminant.")
            if code == "tagged":
                walk(op[2], path, depth + 1)
            walk(op[-1][tag], path, depth + 1)
        else:
            raise RecordError("Unknown compact static layout operation.")

    walk(program if program is not None else READERS[TABLE_READERS[kind]])
    cursor.finish()
    return ItemLayout(bytes(raw), kind, "compact", MappingProxyType(fields), tuple(members), ())


def _field_shape(kind, field):
    def find(op):
        if op[0] == "field":
            return op[3] if op[2] == field else None
        if op[0] in ("seq", "repeat"):
            for child in op[1:]:
                if isinstance(child, tuple):
                    found = find(child)
                    if found is not None:
                        return found
        return None

    op = find(READERS[TABLE_READERS[kind]])
    if op is None and kind == "iteminfo":
        op = find(_ITEMINFO_3527)
    if op is None:
        raise RecordError("This compact static generation has no such field.")
    while op[0] == "call" or op[0] == "seq" and len(op) == 2:
        op = READERS[op[1]] if op[0] == "call" else op[1]
    return op


def field_payload(layout, field):
    """Return the declared field payload, or None for an absent optional value."""
    data = layout.data(field)
    if layout.generation == "compact" and _field_shape(layout.kind, field)[0] in ("optional", "presence"):
        return data[1:] if data[0] else None
    return data


def field_bytes(layout, field, payload):
    """Wrap an edited payload with the presence byte required by this field."""
    if layout.generation == "compact" and _field_shape(layout.kind, field)[0] in ("optional", "presence"):
        return b"\0" if payload is None else b"\1" + bytes(payload)
    if payload is None:
        raise RecordError("A required static field cannot be absent.")
    return bytes(payload)

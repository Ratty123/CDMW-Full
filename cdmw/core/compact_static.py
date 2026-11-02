"""Bounded, address-free layouts for the DLC static-table serialization."""
from types import MappingProxyType

from cdmw.core._compact_static_schema import READERS, TABLE_READERS
from cdmw.core.new_item_record import Cursor, RecordError


# (record bytes, walk steps). Faction and quest rows carry whole relation and
# stage graphs; the largest shipped rows are about 204 KiB.
_RECORD_LIMITS = {"faction": (1 << 20, 4_000_000), "questinfo": (1 << 20, 4_000_000)}
_DEFAULT_LIMITS = (65536, 200000)


def read_compact_layout(raw, kind="iteminfo"):
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
        if depth > 40 or steps > step_limit:
            raise RecordError("Compact static record exceeds the layout limit.")
        code = op[0]
        if code == 'unsupported':
            raise RecordError('This compact static variant has not been qualified.')
        if code == "raw":
            cursor.take(op[1])
        elif code == "text":
            cursor.text()
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
            start = cursor.pos
            walk(child, path + (name,), depth + 1)
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

    walk(READERS[TABLE_READERS[kind]])
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

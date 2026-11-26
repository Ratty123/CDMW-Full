"""Bounded primitives for the optional New Item static-table codecs."""
import struct


class RecordError(ValueError):
    pass


class Cursor:
    def __init__(self, raw):
        self.raw, self.pos = bytes(raw), 0

    def take(self, count):
        if count < 0 or self.pos + count > len(self.raw):
            raise RecordError("Truncated static record")
        result = self.raw[self.pos:self.pos + count]
        self.pos += count
        return result

    def unpack(self, fmt):
        values = struct.unpack("<" + fmt, self.take(struct.calcsize("<" + fmt)))
        return values[0] if len(values) == 1 else values

    def count(self, limit=4096):
        value = self.unpack("I")
        if value > limit:
            raise RecordError("Static record list exceeds the supported bound")
        return value

    def text(self):
        return self.take(self.count()).decode("utf-8")

    def finish(self):
        if self.pos != len(self.raw):
            raise RecordError("Unproven static record boundary")


def text_bytes(value):
    raw = value.encode("utf-8")
    if len(raw) > 4096:
        raise RecordError("Static record string exceeds the supported bound")
    return struct.pack("<I", len(raw)) + raw


def named_prefix(raw, width=4, *, key=None, name=None, key_layout=None):
    """Read a qualified static row identity header, returning (key, name, blocked, generation, cursor)."""
    raw_bytes = bytes(raw)

    def try_generation(generation):
        reader = Cursor(raw_bytes)
        if generation == "indexed":
            own = int.from_bytes(reader.take(width), "little")
            _static_index = reader.unpack("I")
            blocked = reader.unpack("B")
            row_name = "" if name is None else str(name)
        elif generation == "compact":
            row_name, own = reader.text(), int.from_bytes(reader.take(width), "little")
            blocked = reader.unpack("B")
        else:
            own, row_name = int.from_bytes(reader.take(width), "little"), reader.text()
            blocked = reader.unpack("B")
        if (not row_name or row_name.isprintable()) and blocked in (0, 1) and (key is None or own == key):
            return (own, row_name, blocked, generation, reader)
        return None

    if key_layout == "indexed":
        order = ("indexed",)
    elif key_layout == "named":
        order = ("compact",)
    elif key_layout == "prefix":
        order = ("legacy",)
    else:
        order = ("legacy", "compact")

    matches = []
    for generation in order:
        try:
            hit = try_generation(generation)
            if hit is not None:
                matches.append(hit)
        except (RecordError, UnicodeError):
            pass
    if not matches and key_layout is None:
        try:
            hit = try_generation("indexed")
            if hit is not None:
                matches.append(hit)
        except (RecordError, UnicodeError):
            pass
    if len(matches) != 1:
        raise RecordError("Unknown or ambiguous static record identity.")
    return matches[0]

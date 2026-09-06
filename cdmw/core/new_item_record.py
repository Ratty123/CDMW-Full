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

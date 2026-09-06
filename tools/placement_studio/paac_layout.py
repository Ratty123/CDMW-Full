"""Bounds-checked reader for the installed player action-chart layout.

Array widths and the DWORD event offsets follow the chart reader, independently
checked against complete installed files. This is not the commonactioninfo layout.
Unknown variable sections fail explicitly; byte-pattern recovery cannot validate
event timing. No writer is provided.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct


class ChartError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TimedReference:
    begin: float
    end: float
    word_offset: int
    sequence: int
    condition: int


@dataclass(frozen=True, slots=True)
class ActionRecord:
    index: int
    duration: float
    clip_index: int
    blend_index: int
    events: tuple[TimedReference, ...]


class Reader:
    def __init__(self, data):
        self.data = memoryview(data)
        self.pos = 0

    def take(self, size):
        if size < 0 or size > len(self.data) - self.pos:
            raise ChartError(f'Truncated chart section at {self.pos}: {size} bytes')
        start = self.pos
        self.pos += size
        return self.data[start:self.pos]

    def value(self, code):
        return struct.unpack('<' + code, self.take(struct.calcsize('<' + code)))[0]

    def array(self, width, count_code='I'):
        return self.take(self.value(count_code) * width)

    def strings(self):
        result = []
        for _ in range(self.value('H')):
            raw = bytes(self.take(self.value('B')))
            if not raw or raw[-1] != 0 or b'\0' in raw[:-1]:
                raise ChartError('Invalid chart string boundary')
            try:
                result.append(raw[:-1].decode('utf-8'))
            except UnicodeError as error:
                raise ChartError('Invalid chart string encoding') from error
        return tuple(result)

    def timed(self):
        result = []
        for index in range(self.value('B')):
            ref = TimedReference(*struct.unpack('<ffIII', self.take(20)))
            if not math.isfinite(ref.begin) or not math.isfinite(ref.end):
                raise ChartError('Non-finite event time')
            if ref.sequence != index:
                raise ChartError('Invalid event sequence index')
            result.append(ref)
        return tuple(result)


def read_layout(data, *, cancelled=lambda: False):
    reader = Reader(data)
    count = reader.value('I')
    if count > (len(data) - 4) // 166:
        raise ChartError('Invalid chart action count')
    actions = []
    for index in range(count):
        if cancelled():
            raise RuntimeError('Chart inspection cancelled')
        header = reader.take(156)
        duration = struct.unpack_from('<f', header, 4)[0]
        if not math.isfinite(duration) or duration < 0:
            raise ChartError('Invalid chart action duration')
        size = 0
        for offset, width in zip(range(0x68, 0x90, 4), (12, 16, 104, 148, 24, 36, 12, 96, 12, 12)):
            start, items, _flags = struct.unpack_from('<HBB', header, offset)
            if start != size:
                raise ChartError('Invalid chart action array offset')
            size += items * width
        if struct.unpack_from('<I', header, 140)[0] != size:
            raise ChartError('Invalid chart action array length')
        reader.take(size)
        reader.array(1)  # Local condition bytecode.
        reader.array(2)  # Local condition index map.
        events = reader.timed()
        if reader.value('B'):
            raise ChartError('Action tail records are unsupported')
        actions.append(ActionRecord(index, duration, struct.unpack_from('<H', header, 144)[0],
                                    struct.unpack_from('<H', header, 150)[0], events))
    for width in (8, 4, 4):
        reader.array(width)
    tables = tuple(reader.strings() for _ in range(10))
    reader.take(18)
    reader.strings()
    if any(struct.unpack('<10H', reader.take(20))):
        raise ChartError('Structured chart condition tables are unsupported')
    header = reader.take(10)
    for count, width in ((header[0], 4), (header[2], 40), (header[4], 2),
                         (struct.unpack_from('<H', header, 6)[0], 276),
                         (struct.unpack_from('<H', header, 8)[0], 12)):
        reader.take(count * width)
    reader.array(1)
    reader.array(2)
    for width in (52, 8, 28):
        reader.array(width)
    reader.array(28, 'H')
    reader.array(8)
    initial_blob = reader.array(1)
    initial_events = reader.timed()
    event_blob = reader.array(1)
    final_events = reader.timed()
    if reader.pos != len(data):
        raise ChartError('Unconsumed chart bytes')
    return tuple(actions), tables, event_blob, initial_blob, initial_events, final_events

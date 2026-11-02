"""Decoded attachment events, kept distinct from the runtime action graph.

Kind 62 is ModelAttachmentSocket in game 2.04.03 (it was 60 before that update;
`cdmw.core.action_chart_binary.FRAME_EVENT_KINDS` holds the full list). The event
starts with a 12-byte header and its 20-byte payload uses table 7 for parts and
table 6 for sockets. Modes 0/1 select the
descriptor's In/Out frames; mode 2 names explicit frames. Conditional events,
blended socket motion and equipment-slot lookups are retained but not simulated.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import struct

from cdmw.core.action_chart_binary import FRAME_EVENT_HEADER_SIZE, MODEL_ATTACHMENT_SOCKET_KIND

from .paac_layout import ChartError, read_layout


@dataclass(frozen=True, slots=True)
class SocketEvent:
    seconds: float
    sequence: int
    part: str
    mode: int
    parent: str
    child: str
    blend_time: float
    all_parts: bool
    limitations: tuple[str, ...] = ()

    def state(self, descriptor):
        if self.mode == 2:
            return self.parent, self.child
        return ((descriptor.in_socket, descriptor.in_child_socket) if self.mode == 0 else
                (descriptor.out_socket, descriptor.out_child_socket))


@dataclass(frozen=True, slots=True)
class ActionEvents:
    index: int
    clip: str
    blendspace: str
    duration: float
    sockets: tuple[SocketEvent, ...]
    other_types: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ChartEvents:
    path: str
    sha256: str
    actions: tuple[ActionEvents, ...]
    limitations: tuple[str, ...] = ()


def table_value(tables, table, index):
    if index == 0xffff:
        return ''
    if index >= len(tables[table]):
        raise ChartError(f'Chart table {table} index {index} is out of range')
    return tables[table][index]


def socket_event(blob, ref, tables):
    # The reference is a DWORD offset, not a byte offset or an opcode.
    offset = ref.word_offset * 4
    if offset + FRAME_EVENT_HEADER_SIZE > len(blob):
        raise ChartError('Event payload offset is out of range')
    kind, condition_count, condition_offset, flags = struct.unpack_from('<4H', blob, offset)
    if kind != MODEL_ATTACHMENT_SOCKET_KIND:
        return kind, None
    if offset + FRAME_EVENT_HEADER_SIZE + 20 > len(blob):
        raise ChartError('Truncated attachment event')
    blend, _equip_type, part, parent, child, mode, all_parts, disabled, _slot = struct.unpack_from(
        '<fIHHHBBBb', blob, offset + FRAME_EVENT_HEADER_SIZE)
    if not math.isfinite(blend) or blend < 0 or mode > 2 or all_parts > 1 or disabled > 1:
        raise ChartError('Invalid attachment event value')
    notes = []
    # Shipped instances carry 0x0001FFFF here; the low half is the condition slot.
    if condition_count or condition_offset or ref.condition & 0xffff != 0xffff:
        notes.append('Event conditions are not simulated')
    if flags & 0xff not in (2, 3):
        notes.append('Event execution flags are unsupported')
    if ref.end != -1 or ref.begin < 0:
        notes.append('Event interval is unsupported')
    if blend:
        notes.append('Socket blend interpolation is not simulated')
    if disabled:
        notes.append('Event uses an unsupported execution branch')
    if part == 0xffff and not all_parts:
        notes.append('Equipment-slot lookup is unresolved')
    if all_parts and mode != 0:
        notes.append('All-parts mode is unsupported')
    if mode == 2 and (parent == 0xffff or child == 0xffff):
        notes.append('Explicit socket pair is incomplete')
    return kind, SocketEvent(ref.begin, ref.sequence, table_value(tables, 7, part), mode,
        table_value(tables, 6, parent), table_value(tables, 6, child), blend, bool(all_parts), tuple(notes))


def decode(data, *, path='', cancelled=lambda: False):
    from .relationships import resource_path
    records, tables, blob, initial_blob, initial_refs, final_refs = read_layout(data, cancelled=cancelled)
    actions, notes = [], []
    if initial_blob or initial_refs or final_refs:
        notes.append('Global chart events are not simulated')
    for record in records:
        if cancelled():
            raise RuntimeError('Chart inspection cancelled')
        sockets, other = [], set()
        for ref in record.events:
            kind, event = socket_event(blob, ref, tables)
            if event is not None:
                sockets.append(event)
            else:
                other.add(kind)
        clip = table_value(tables, 1, record.clip_index)
        blend = table_value(tables, 5, record.blend_index)
        actions.append(ActionEvents(record.index, resource_path(clip) if clip else '',
            resource_path(blend) if blend else '', record.duration,
            tuple(sorted(sockets, key=lambda e: (e.seconds, e.sequence))), tuple(sorted(other))))
    return ChartEvents(path, hashlib.sha256(data).hexdigest(), tuple(actions), tuple(notes))

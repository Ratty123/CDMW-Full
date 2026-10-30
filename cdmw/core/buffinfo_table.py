"""Bounded equipment BuffInfo level maps.

The supported discriminators were measured against all twenty BuffInfo definitions
referenced by current equipment. Each value has a fixed header, a counted description
and a discriminator-sized body. The body is preserved, never authored here. ItemInfo
selects a signed level in this map; zero is the unmodified level. No percentage/unit
conversion is inferred from a buff's name.
"""
from dataclasses import dataclass
import struct


class BuffInfoError(ValueError):
    pass


# Total bytes of one level record, excluding its counted description's UTF-8 bytes.
_LEVEL_SIZES = {2: 120, 3: 120, 5: 141, 12: 136, 14: 120, 17: 108, 79: 116, 104: 113, 105: 120}


@dataclass(frozen=True, slots=True)
class BuffLevel:
    level: int
    kind: int
    description: str
    raw: bytes


@dataclass(frozen=True, slots=True)
class EquipmentBuff:
    key: int
    name: str
    blocked: bool
    levels: tuple[BuffLevel, ...]
    minimum: int
    maximum: int
    calculation: int
    prefix: bytes
    tail: bytes

    def supports(self, parameter: int) -> bool:
        return self.minimum <= parameter <= self.maximum and (parameter == 0 or any(level.level == parameter for level in self.levels))


def parse_equipment_buff(raw: bytes) -> EquipmentBuff:
    data = bytes(raw)
    from cdmw.core.new_item_record import named_prefix,Cursor
    if named_prefix(raw)[3] == 'compact':
        from cdmw.core.compact_static import read_compact_layout
        layout = read_compact_layout(raw,'buffinfo')
        groups = {}
        for member in layout.members:
            if member.path[:1] == ('_buffDataList',):
                groups.setdefault(member.path[1],{})[(member.owner,member.name)] = member.span
        levels = []
        for group in groups.values():
            level_span,data_span = group[('BuffLevel','_level')],group[('BuffLevel','_data')]
            value = raw[data_span.start:data_span.end]
            if len(value)<2 or value[0]!=0:
                raise BuffInfoError('Empty equipment buff definition.')
            description_span = group[('BuffData','_description')]
            description = Cursor(raw[description_span.start:description_span.end]).text()
            levels.append(BuffLevel(int.from_bytes(raw[level_span.start:level_span.end],'little',signed=True),
                value[1],description,raw[level_span.start:data_span.end]))
        block = layout.fields['_buffDataList']
        result = EquipmentBuff(layout.integer('_key',width=4),Cursor(layout.data('_stringKey')).text(),
            bool(layout.integer('_isBlocked',width=1)),tuple(levels),
            int.from_bytes(layout.data('_minLevel'),'little',signed=True),int.from_bytes(layout.data('_maxLevel'),'little',signed=True),
            layout.integer('_buffLevelCalculateType',width=1),raw[:block.start+4],raw[block.end:])
        expected = {level for level in range(result.minimum,result.maximum+1) if level} if 0 <= result.maximum-result.minimum <= 1024 else None
        # Compact equipment uses calculation type 1 and can apply several buff
        # definitions at the same level. Each complete level remains selectable.
        if result.calculation != 1 or expected != {level.level for level in levels}:
            raise BuffInfoError(f'Unsupported compact BuffInfo level map: {result.name}')
        return result
    if len(data) < 40:
        raise BuffInfoError("BuffInfo row is truncated")
    key, length = struct.unpack_from("<II", data)
    p = 8 + length
    if p + 5 > len(data):
        raise BuffInfoError("BuffInfo name is truncated")
    name = data[8:p].decode("utf-8")
    blocked = data[p]
    count = struct.unpack_from("<I", data, p + 1)[0]
    if blocked not in (0, 1) or not 1 <= count <= 1024:
        raise BuffInfoError(f"Unsupported BuffInfo header: {name}")
    prefix = data[:p + 5]
    p += 5
    levels = []
    for _ in range(count):
        if p + 44 > len(data):
            raise BuffInfoError(f"Truncated buff level: {name}")
        level = struct.unpack_from("<i", data, p)[0]
        kind = struct.unpack_from("<I", data, p + 5)[0]
        size = _LEVEL_SIZES.get(kind)
        text_length = struct.unpack_from("<I", data, p + 40)[0]
        if size is None or data[p + 4] != 0 or text_length > 4096 or p + size + text_length > len(data):
            raise BuffInfoError(f"Unsupported buff level layout {kind}: {name}")
        description = data[p + 44:p + 44 + text_length].decode("utf-8")
        levels.append(BuffLevel(level, kind, description, data[p:p + size + text_length]))
        p += size + text_length
    tail = data[p:]
    # This equipment shape has no sequencer path and no elemental-status payload.
    if len(tail) != 27 or tail[21:] != bytes(6) or tail[12] not in (0, 1):
        raise BuffInfoError(f"Unsupported BuffInfo trailer: {name}")
    minimum, maximum, calculation = struct.unpack_from("<iiI", tail)
    expected = tuple(level for level in range(minimum, maximum + 1) if level != 0) if maximum - minimum <= 1024 else ()
    if calculation != 0 or tuple(level.level for level in levels) != expected:
        raise BuffInfoError(f"Unsupported BuffInfo level map: {name}")
    return EquipmentBuff(key, name, bool(blocked), tuple(levels), minimum, maximum, calculation, prefix, tail)


def encode_equipment_buff(buff: EquipmentBuff) -> bytes:
    return buff.prefix + b"".join(level.raw for level in buff.levels) + buff.tail

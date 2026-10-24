"""Typed regeneration, level-stat and passive edits on complete ItemInfo layouts."""
from dataclasses import dataclass
import struct

from cdmw.core.item_layout import Span, read_item_layout, replace_layout_fields
from cdmw.core.iteminfo_settings import _level_path
from cdmw.core.new_item_record import Cursor, RecordError
from cdmw.domain.new_item.item_stats import STAT_FIELDS, PassiveSkill, encode_stat_settings


@dataclass(frozen=True)
class ItemStat:
    kind: str
    level: int
    key: int
    value: int
    span: Span


def item_stat_entries(layout):
    levels = {_level_path(member.path): int.from_bytes(layout.raw[member.span.start:member.span.end], 'little')
              for member in layout.members if (member.owner, member.name) == ('EnchantData', '_level')}
    kinds = {field: kind for kind, field in STAT_FIELDS.items()}
    result = []
    for member in layout.members:
        if member.owner != 'EnchantStatData' or member.name not in kinds or '_enchantDataList' not in member.path:
            continue
        kind = kinds[member.name]
        # The level-stat count is a separate member; its elements are captured
        # under suffixed labels. Read those key/parameter pairs below instead.
        if kind == 'level_stat':
            continue
        cursor = Cursor(layout.raw[member.span.start:member.span.end])
        for _ in range(cursor.count(256)):
            key = cursor.unpack('I')
            start = member.span.start + cursor.pos
            value = cursor.unpack('q')
            result.append(ItemStat(kind, levels[_level_path(member.path)], key, value, Span(start, start + 8)))
        cursor.finish()
    level_keys = {}
    for member in layout.members:
        if member.owner != 'EnchantStatData' or '_enchantDataList' not in member.path:
            continue
        if member.name == '_statList_DataDefinedStaticLevel[0]':
            level_keys[member.path] = int.from_bytes(layout.raw[member.span.start:member.span.end], 'little')
        elif member.name == '_statList_DataDefinedStaticLevel[1]':
            if member.span.size != 1 or member.path not in level_keys:
                raise RecordError('Unqualified level-stat parameter.')
            result.append(ItemStat('level_stat', levels[_level_path(member.path)], level_keys.pop(member.path),
                                   layout.raw[member.span.start], member.span))
    if level_keys:
        raise RecordError('Incomplete level-stat entry.')
    return tuple(result)


def equipment_passive_skills(layout):
    cursor = Cursor(layout.data('_equipPassiveSkillList'))
    result = tuple(PassiveSkill(cursor.unpack('I'), cursor.unpack('I')) for _ in range(cursor.count(128)))
    cursor.finish()
    return result


def stat_list_spans(layout):
    """Declared list spans and their actual enhancement levels, including empty lists."""
    levels = {_level_path(member.path): int.from_bytes(layout.raw[member.span.start:member.span.end], 'little')
              for member in layout.members if (member.owner, member.name) == ('EnchantData', '_level')}
    kinds = {field: kind for kind, field in STAT_FIELDS.items()}
    result = []
    for member in layout.members:
        if member.owner != 'EnchantStatData' or member.name not in kinds or '_enchantDataList' not in member.path:
            continue
        kind, span = kinds[member.name], member.span
        if kind == 'level_stat':
            count = int.from_bytes(layout.raw[span.start:span.end], 'little')
            span = Span(span.start, span.end + 5 * count)
        result.append((kind, levels[_level_path(member.path)], span))
    return tuple(result)


def read_item_stats(raw):
    layout = read_item_layout(raw)
    return item_stat_entries(layout), equipment_passive_skills(layout)


def set_item_stats(raw, settings):
    encode_stat_settings(settings)
    layout = read_item_layout(raw)
    if settings.passive_skills is not None:
        data = struct.pack('<I', len(settings.passive_skills)) + b''.join(
            struct.pack('<II', skill.skill_key, skill.level) for skill in settings.passive_skills)
        layout = replace_layout_fields(layout, {'_equipPassiveSkillList': data})
    spans = stat_list_spans(layout)
    changed = {}
    for edit in settings.statistics:
        matches = [span for kind, level, span in spans if (kind, level) == (edit.kind, edit.level)]
        if len(matches) != 1:
            raise RecordError('The selected item stat is missing or ambiguous.')
        span = matches[0]
        fmt = 'B' if edit.kind == 'level_stat' else 'q'
        if span not in changed:
            cursor = Cursor(layout.raw[span.start:span.end])
            changed[span] = [(cursor.unpack('I'), cursor.unpack(fmt)) for _ in range(cursor.count(256))]
            cursor.finish()
        entries = changed[span]
        positions = [index for index, (key, _value) in enumerate(entries) if key == edit.key]
        if len(positions) > 1 or not positions and edit.value is None:
            raise RecordError('The selected item stat is missing or ambiguous.')
        if edit.value is None:
            entries.pop(positions[0])
        elif positions:
            entries[positions[0]] = (edit.key, edit.value)
        else:
            entries.append((edit.key, edit.value))
        if len(entries) > 256:
            raise RecordError('Item stat list exceeds the supported bound.')
    enchant = layout.fields['_enchantDataList']
    output = bytearray(layout.data('_enchantDataList'))
    for span, entries in sorted(changed.items(), key=lambda pair:pair[0].start, reverse=True):
        kind = next(kind for kind, _level, candidate in spans if candidate == span)
        fmt = '<IB' if kind == 'level_stat' else '<Iq'
        data = struct.pack('<I', len(entries)) + b''.join(struct.pack(fmt, *entry) for entry in entries)
        output[span.start - enchant.start:span.end - enchant.start] = data
    final = replace_layout_fields(layout, {'_enchantDataList': bytes(output)}) if changed else layout
    for field in layout.fields:
        if field != '_enchantDataList' and final.data(field) != layout.data(field):
            raise RecordError('Item stats changed an unassigned field.')
    values = {(row.kind, row.level, row.key): row.value for row in item_stat_entries(final)}
    if any(values.get((edit.kind, edit.level, edit.key)) != edit.value for edit in settings.statistics):
        raise RecordError('Item stat overrides did not round-trip.')
    return final.raw

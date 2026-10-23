"""Typed extended ItemInfo settings and full-width quantities on complete layouts."""
from dataclasses import dataclass
import struct

from cdmw.core.item_layout import read_item_layout, replace_layout_fields, counted_integers, Span
from cdmw.core.new_item_record import Cursor, RecordError
from cdmw.domain.new_item.item_settings import (ItemSettings, RepairEntry, encode_settings, POLICY_FIELDS, SCALAR_FIELDS)


@dataclass(frozen=True)
class ItemQuantity:
    kind: str
    key: int
    value: int
    level: int | None
    span: Span


def _level_path(path):
    for index, component in enumerate(path):
        if component == '_enchantDataList':
            return path[index + 2]
    return None


def item_quantities(layout):
    quantities = []
    levels = { _level_path(member.path): int.from_bytes(layout.raw[member.span.start:member.span.end], 'little')
               for member in layout.members if member.owner == 'EnchantData' and member.name == '_level' }
    price_fields = [('_priceList', layout.fields['_priceList'], None)]
    for member in layout.members:
        if member.owner == 'EnchantData' and member.name == '_buyPriceList':
            price_fields.append(('_buyPriceList', member.span, levels[_level_path(member.path)]))
        elif (member.owner == 'EnchantStatData' and member.name == '_statList_DataDefinedStatic'
                and '_enchantDataList' in member.path):
            cursor = Cursor(layout.raw[member.span.start:member.span.end])
            for _ in range(cursor.count(256)):
                key = cursor.unpack('I')
                start = member.span.start + cursor.pos
                value = cursor.unpack('q')
                quantities.append(ItemQuantity('stat', key, value, levels[_level_path(member.path)], Span(start, start + 8)))
            cursor.finish()
    for field, span, level in price_fields:
        cursor = Cursor(layout.raw[span.start:span.end])
        for _ in range(cursor.count(128)):
            key = cursor.unpack('I')
            start = span.start + cursor.pos
            value = cursor.unpack('Q')
            cursor.take(4)  # PriceFloor._symNo is preserved, not a high amount word.
            wrapper = cursor.unpack('I')
            if wrapper != key or key == 0:
                raise RecordError('Unqualified price item wrapper.')
            quantities.append(ItemQuantity('price' if field == '_priceList' else 'buy_price', key, value, level, Span(start, start + 8)))
        cursor.finish()
    return tuple(quantities)


def read_item_settings(raw):
    layout = read_item_layout(raw)
    values = {}
    for name, field in POLICY_FIELDS.items():
        value = layout.integer(field, width=1)
        if value not in (0, 1):
            raise RecordError('Unknown ItemInfo policy flag value.')
        values[name] = bool(value)
    for name, (field, width) in SCALAR_FIELDS.items():
        values[name] = layout.integer(field, width=width)
    cursor = Cursor(layout.data('_repairDataList'))
    repairs = tuple(RepairEntry(cursor.unpack('I'), cursor.unpack('H'), cursor.unpack('B'), cursor.unpack('Q'))
                    for _ in range(cursor.count(128)))
    cursor.finish()
    values.update(repairs=repairs, use_actions=counted_integers(layout, '_itemUseInfoList'),
                  cooldowns=struct.unpack('<3Q', layout.data('_cooltime')),
                  maximum_charges=struct.unpack('<3I', layout.data('_maxChargedUseableCount')))
    return ItemSettings(**values), item_quantities(layout)


def set_item_settings(raw, settings):
    encode_settings(settings)  # Closed shape and strict integer/boolean validation.
    layout = read_item_layout(raw)
    changes = {}
    for name, field in POLICY_FIELDS.items():
        value = getattr(settings, name)
        if value is not None:
            changes[field] = bytes([int(value)])
    for name, (field, width) in SCALAR_FIELDS.items():
        value = getattr(settings, name)
        if value is not None:
            changes[field] = value.to_bytes(width, 'little')
    if settings.repairs is not None:
        changes['_repairDataList'] = struct.pack('<I', len(settings.repairs)) + b''.join(
            struct.pack('<IHBQ', row.resource_item, row.repair_value, row.repair_style, row.resource_count)
            for row in settings.repairs)
    if settings.use_actions is not None:
        changes['_itemUseInfoList'] = struct.pack('<I', len(settings.use_actions)) + b''.join(
            struct.pack('<I', key) for key in settings.use_actions)
    for name, field, fmt in (('cooldowns', '_cooltime', '<3Q'), ('maximum_charges', '_maxChargedUseableCount', '<3I')):
        value = getattr(settings, name)
        if value is not None:
            changes[field] = struct.pack(fmt, *value)
    if changes:
        layout = replace_layout_fields(layout, changes)
    output = bytearray(layout.raw)
    available = item_quantities(layout)
    for edit in settings.quantities:
        matches = [value for value in available if (value.kind, value.level, value.key) == (edit.kind, edit.level, edit.key)]
        if len(matches) != 1:
            raise RecordError('The selected full-width quantity is missing or ambiguous.')
        span = matches[0].span
        output[span.start:span.end] = edit.value.to_bytes(8, 'little', signed=edit.kind == 'stat')
    final = read_item_layout(bytes(output), generation=layout.generation)
    actual = {(value.kind, value.level, value.key): value.value for value in item_quantities(final)}
    if any(actual.get((edit.kind, edit.level, edit.key)) != edit.value for edit in settings.quantities):
        raise RecordError('The full-width quantity edit did not round-trip.')
    return final.raw

"""Typed ItemInfo views and lossless edits for compact DLC records."""
import struct

from cdmw.core.compact_static import field_bytes, field_payload
from cdmw.core.new_item_record import Cursor, RecordError


def parse_compact_item(layout):
    from cdmw.core.iteminfo_row import EnchantLevel, ItemInfoRow, OccupiedSlot, PriceEntry, StatValue

    def text(field, *, local=False):
        cursor = Cursor(field_payload(layout, field) or bytes(13 if local else 4))
        if local:
            cursor.take(9)
        result = cursor.text()
        cursor.finish()
        return result

    def prices(span):
        cursor = Cursor(layout.raw[span.start:span.end])
        result = []
        for _ in range(cursor.count()):
            key = cursor.unpack('I')
            offset = span.start + cursor.pos
            low, high, symbol, again = cursor.unpack('IIII')
            if key != again:
                raise RecordError('Unqualified compact price identity.')
            result.append(PriceEntry(key, low, offset, (high, symbol)))
        cursor.finish()
        return tuple(result)

    occupied = Cursor(field_payload(layout, '_occupiedEquipSlotDataList') or bytes(4))
    slots = tuple(OccupiedSlot(occupied.unpack('I'), tuple(occupied.take(occupied.count())))
                  for _ in range(occupied.count()))
    occupied.finish()
    drop = field_payload(layout, '_dropDefaultData')
    sockets, materials, flags = (), (), (0, 0)
    if drop is not None:
        cursor = Cursor(drop)
        cursor.take(2)
        sockets = tuple(cursor.unpack('I') for _ in range(cursor.count()))
        materials = tuple(cursor.unpack('III') for _ in range(cursor.count()))
        tag = cursor.unpack('B')
        if tag in (0, 3, 9):
            cursor.take(4)
        flags = cursor.unpack('BB')
        cursor.finish()
    groups = {}
    for member in layout.members:
        if member.path[:1] == ('_enchantDataList',):
            groups.setdefault(member.path[1], {})[(member.owner, member.name)] = member.span
    levels = []
    for group in groups.values():
        def member(owner, name):
            return group[(owner, name)]

        level_span = member('EnchantData', '_level')
        level = int.from_bytes(layout.raw[level_span.start:level_span.end], 'little')
        stats_span = member('EnchantStatData', '_statList_DataDefinedStatic')
        cursor = Cursor(layout.raw[stats_span.start:stats_span.end])
        stats = []
        for _ in range(cursor.count()):
            key = cursor.unpack('I')
            offset = stats_span.start + cursor.pos
            low, high = cursor.unpack('ii')
            stats.append(StatValue(key, low, offset, high))
        cursor.finish()
        ls = member('EnchantStatData', '_statList_DataDefinedStaticLevel')
        cursor = Cursor(layout.raw[ls.start:ls.end])
        level_entries = tuple(cursor.take(5) for _ in range(cursor.count()))
        cursor.finish()
        buffs = member('EnchantData', '_equipBuffs')
        cursor = Cursor(layout.raw[buffs.start:buffs.end])
        buff_entries = tuple(cursor.unpack('II') for _ in range(cursor.count()))
        cursor.finish()
        passive = member('EnchantData', '_equipPassiveBuffs')
        effect = member('EnchantData', '_itemEffectInfo')
        levels.append(EnchantLevel(level, tuple(stats), prices(member('EnchantData', '_buyPriceList')),
            level_span.start, effect.end, tuple(int.from_bytes(v[:4], 'little') for v in level_entries),
            tuple(v[0] for v in buff_entries), layout.raw[level_span.end:stats_span.start], level_entries,
            tuple(v[1] for v in buff_entries), int.from_bytes(layout.raw[effect.start:effect.end], 'little'),
            passive_buffs=layout.raw[passive.start:passive.end]))
    start, end = layout.fields['_dropDefaultData'].start, layout.fields['_priceList'].end
    return ItemInfoRow(raw=layout.raw, key=layout.integer('_key', width=4), string_key=text('_stringKey'),
        is_blocked=layout.integer('_isBlocked', width=1), max_stack_count=layout.integer('_maxStackCount', width=8),
        name_key=text('_itemName', local=True), equip_type_key=layout.integer('_equipTypeInfo', width=4),
        occupied_slots=slots, prefix_end=layout.fields['_occupiedEquipSlotDataList'].end,
        desc_key=text('_itemDesc', local=True), desc_offset=layout.fields['_itemDesc'].start,
        item_type=layout.integer('_itemType', width=1), item_type_offset=layout.fields['_itemType'].start,
        memo=text('_itemMemo'), socket_items=sockets, add_socket_materials=materials,
        stat_block_offset=start, enchant_levels=tuple(levels), enchant_count=len(levels),
        price_list=prices(layout.fields['_priceList']), stat_block_end=end, stat_block_flags=flags,
        category_info=layout.integer('_categoryInfo', width=2), category_info_offset=layout.fields['_categoryInfo'].start,
        layout_generation='compact', stack_count_offset=layout.fields['_maxStackCount'].start)


def encode_compact_stat_block(row, *, levels=None, price_list=None, socket_items=None, add_socket_materials=None):
    from cdmw.core.item_layout import read_item_layout, replace_layout_fields
    from cdmw.core.iteminfo_row import _encode_price_entry

    layout = read_item_layout(row.raw, generation='compact')
    changes = {}
    sockets = tuple(row.socket_items if socket_items is None else socket_items)
    materials = tuple(row.add_socket_materials if add_socket_materials is None else add_socket_materials)
    if sockets != row.socket_items or materials != row.add_socket_materials:
        if len(sockets) > 8 or len(materials) > 8 or any(not 0 < v <= 0xffffffff for v in sockets):
            raise RecordError('Invalid compact socket list.')
        drop = field_payload(layout, '_dropDefaultData') or bytes(10) + b'\x12\0\0'
        cursor = Cursor(drop)
        cursor.take(2)
        cursor.take(4 * cursor.count())
        cursor.take(12 * cursor.count())
        default = drop[cursor.pos:-2]
        body = drop[:2] + struct.pack('<I', len(sockets)) + b''.join(struct.pack('<I', v) for v in sockets)
        body += struct.pack('<I', len(materials)) + b''.join(struct.pack('<III', *v) for v in materials)
        body += default + bytes((len(sockets), int(bool(materials))))
        changes['_dropDefaultData'] = field_bytes(layout, '_dropDefaultData', body)
    if levels is not None and tuple(levels) != row.enchant_levels:
        levels = tuple(levels)
        if len(levels) > 40 or [v.level for v in levels] != list(range(len(levels))):
            raise RecordError('Invalid compact enhancement ladder.')
        parts = []
        for level in levels:
            header = bytes(8) if level.header_bytes == bytes(6) else level.header_bytes
            data = struct.pack('<H', level.level) + header
            data += struct.pack('<I', len(level.stats)) + b''.join(struct.pack('<Iii', v.status_key, v.value, v.extra) for v in level.stats)
            if len(level.level_stat_keys) != len(level.level_stat_entries) or any(len(v) != 5 for v in level.level_stat_entries):
                raise RecordError('Invalid compact level-stat list.')
            data += struct.pack('<I', len(level.level_stat_entries)) + b''.join(level.level_stat_entries)
            data += struct.pack('<I', len(level.buy_prices)) + b''.join(_encode_price_entry(v) for v in level.buy_prices)
            if len(level.equip_buffs) != len(level.equip_buff_extras):
                raise RecordError('Invalid compact equipment buff list.')
            data += struct.pack('<I', len(level.equip_buffs)) + b''.join(struct.pack('<II', *v) for v in zip(level.equip_buffs, level.equip_buff_extras))
            data += level.passive_buffs + struct.pack('<I', level.tail)
            parts.append(data)
        changes['_enchantDataList'] = field_bytes(layout, '_enchantDataList', struct.pack('<I', len(parts)) + b''.join(parts))
    if price_list is not None and tuple(price_list) != row.price_list:
        changes['_priceList'] = struct.pack('<I', len(price_list)) + b''.join(_encode_price_entry(v) for v in price_list)
    if changes:
        layout = replace_layout_fields(layout, changes)
    return layout.raw[layout.fields['_dropDefaultData'].start:layout.fields['_priceList'].end]

"""Lossless shop edits on declared compact StoreInfo and StockData fields."""
import struct

from cdmw.core.compact_static import read_compact_layout, field_payload, field_bytes
from cdmw.core.item_layout import replace_layout_fields
from cdmw.core.new_item_record import Cursor, RecordError


def drop_item(drop):
    """The item a stock entry's drop data sells (byte 8 is the result type, 0 an item), else 0."""
    if not drop:
        return 0
    if len(drop) < 9:
        raise RecordError('Compact shop drop data is truncated.')
    item = int.from_bytes(drop[:8], 'little') if drop[8] == 0 else 0
    if item and (len(drop) != 63 or int.from_bytes(drop[-4:], 'little') != item):
        raise RecordError('Compact shop item identity is inconsistent.')
    return item


def parse_compact_store(raw, key=None):
    from cdmw.core.storeinfo_table import StoreRow, StockEntry
    layout = read_compact_layout(raw, 'storeinfo')
    own = layout.integer('_key', width=2)
    if key is not None and key != own:
        raise RecordError('Compact store identity differs from its directory.')
    name = Cursor(layout.data('_stringKey')).text()
    groups = {}
    for member in layout.members:
        if member.owner == 'StockData' and member.path[:1] == ('_stockDataList',):
            groups.setdefault(member.path[1], []).append(member)
    entries = []
    for members in groups.values():
        start, end = min(m.span.start for m in members), max(m.span.end for m in members)
        entry_raw = raw[start:end]
        entry = read_compact_layout(entry_raw, 'stockdata')
        def number(field, width=4, signed=False):
            return int.from_bytes(entry.data(field), 'little', signed=signed)
        drop = field_payload(entry, '_dropInfoData')
        item = drop_item(drop)
        if number('_storeInfo', 2) != own:
            raise RecordError('Compact stock entry names another store.')
        flags = b''.join(entry.data(f) for f in ('_refillByResetStore','_isStockSellable','_isStockBuyable','_isRestoreItem')) + b'\0'
        orders = Cursor(entry.data('_orderCountDataList'))
        records = tuple(orders.take(12) for _ in range(orders.count()))
        orders.finish()
        entries.append(StockEntry(own, number('_minPricePercent',8), number('_maxPricePercent',8),
            number('_maxRefillCount'), number('_lowPriceThresholdCount',signed=True), number('_stockIndex'),
            number('_orderIndex'), number('_importantSaveIndex',signed=True), flags, item,
            drop or b'', entry.data('_playerConditionInfo') + entry.data('_targetConditionInfo'),
            field_payload(entry,'_conditionOption'), records, start, end,
            entry.data('_maxRefillCondition'), compact_raw=entry_raw))
    stock = layout.fields['_stockDataList']
    return StoreRow(raw, own, name, raw[:stock.start], layout.integer('_buyableStockCount',width=4),
        layout.integer('_sellableStockCount',width=4), layout.integer('_storeType',width=1), tuple(entries),
        raw[stock.end:], stock.start, 'compact')


def encode_compact_stock(entry):
    layout = read_compact_layout(entry.compact_raw, 'stockdata')
    changes = {field: struct.pack(fmt, value) for field,fmt,value in (
        ('_storeInfo','<H',entry.store_key), ('_minPricePercent','<Q',entry.min_price_percent),
        ('_maxPricePercent','<Q',entry.max_price_percent), ('_maxRefillCount','<I',entry.count),
        ('_lowPriceThresholdCount','<i',entry.threshold), ('_stockIndex','<I',entry.stock_index),
        ('_orderIndex','<I',entry.order_index), ('_importantSaveIndex','<i',entry.important_save_index))}
    if len(entry.flags) != 5 or entry.flags[-1] != 0 or len(entry.after_bytes) != 8:
        raise RecordError('Invalid compact stock flags or conditions.')
    changes.update({field:bytes([value]) for field,value in zip(
        ('_refillByResetStore','_isStockSellable','_isStockBuyable','_isRestoreItem'),entry.flags)})
    drop = bytearray(entry.drop_bytes)
    if entry.item_key:
        if len(drop) != 63 or drop[8] != 0:
            raise RecordError('This shop result is not an editable item.')
        struct.pack_into('<Q',drop,0,entry.item_key)
        struct.pack_into('<I',drop,len(drop)-4,entry.item_key)
    changes['_dropInfoData'] = field_bytes(layout,'_dropInfoData',bytes(drop) if drop else None)
    changes['_conditionOption'] = field_bytes(layout,'_conditionOption',entry.option_block)
    changes['_playerConditionInfo'], changes['_targetConditionInfo'] = entry.after_bytes[:4],entry.after_bytes[4:]
    changes['_maxRefillCondition'] = entry.condition_data
    changes['_orderCountDataList'] = struct.pack('<I',len(entry.order_records)) + b''.join(entry.order_records)
    return replace_layout_fields(layout, changes).raw


def encode_compact_store(row):
    layout = read_compact_layout(row.raw,'storeinfo')
    changes = {'_buyableStockCount':struct.pack('<I',row.buyable_count),
        '_sellableStockCount':struct.pack('<I',row.sellable_count), '_storeType':bytes([row.store_type]),
        '_stockDataList':struct.pack('<I',len(row.entries))+b''.join(encode_compact_stock(v) for v in row.entries)}
    return replace_layout_fields(layout, changes).raw

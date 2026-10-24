"""Bounded ItemInfo values for DMM's snake-case V3 intent vocabulary.

Only changed, completely decoded fields are emitted. Unchanged opaque fields stay
on the donor. Names follow the public V3 schema at dmm-parser 2e3b7a59c49f;
this module neither imports that parser nor claims manager/runtime validation.
"""
from cdmw.core.item_layout import read_item_layout
from cdmw.core.new_item_record import Cursor, RecordError


def record(reader, fields):
    return {name: reader.unpack(fmt) for name, fmt in fields}


def array(reader, read):
    return [read(reader) for _ in range(reader.count())]


def local_string(reader):
    return dict(category=reader.unpack('B'), index=reader.unpack('Q'), default=reader.text())


def price(reader):
    return dict(key=reader.unpack('I'), price=record(reader,
        (('price', 'Q'), ('sym_no', 'I'), ('item_info_wrapper', 'I'))))


def enchant(reader):
    level = reader.unpack('H')
    stats = {name: array(reader, lambda r: record(r, (('stat', 'I'), ('change_mb', fmt))))
             for name, fmt in (('max_stat_list', 'q'), ('regen_stat_list', 'q'),
                               ('stat_list_static', 'q'), ('stat_list_static_level', 'b'))}
    return dict(level=level, enchant_stat_data=stats, buy_price_list=array(reader, price),
                equip_buffs=array(reader, lambda r: record(r, (('buff', 'I'), ('level', 'I')))),
                unk_u32_112=reader.unpack('I'))


def drop_default(reader):
    result = dict(drop_enchant_level=reader.unpack('H'),
                  socket_item_list=array(reader, lambda r: r.unpack('I')),
                  add_socket_material_item_list=array(reader,
                      lambda r: record(r, (('item', 'I'), ('value', 'Q')))))
    kind = reader.unpack('B')
    if kind not in (0, 3, 9, 14, 15, 16, 17, 18, 255):
        raise RecordError('DMM V3: unsupported default sub-item variant.')
    result['default_sub_item'] = dict(type_id=kind, value=reader.unpack('I') if kind in (0, 3, 9) else None)
    result.update(socket_valid_count=reader.unpack('B'), use_socket=reader.unpack('B'))
    return result


# Explicit aliases avoid guessing names from reflection spelling (including its
# historical typos). Widths and signedness must match DMM's JSON writer.
_SCALARS = {
    '_maxStackCount': ('max_stack_count', 'Q'),
    '_equipableLevel': ('equipable_level', 'I'),
    '_itemTier': ('item_tier', 'B'),
    '_maxEndurance': ('max_endurance', 'H'),
    '_isBlockedStoreSell': ('is_blocked_store_sell', 'B'),
    '_discardable': ('discardable', 'B'),
    '_isImportantItem': ('is_important_item', 'B'),
    '_isDestoryWhenBroken': ('is_destroy_when_broken', 'B'),
    '_isPreservedOnExtract': ('is_preserved_on_extract', 'B'),
    '_canDisassemble': ('can_disassemble', 'B'),
    '_isExtractAbleItem': ('is_extract_able_item', 'B'),
    '_extractAdditionalDropSetInfo': ('extract_additional_drop_set_info', 'I'),
    '_minimumExtractEnchantLevel': ('minimum_extract_enchant_level', 'H'),
    '_itemChargeType': ('item_charge_type', 'B'),
    '_sharedCoolTimeGroupNameHash': ('shared_cool_time_group_name_hash', 'I'),
}
_LISTS = {'_multiChangeInfoList': 'multi_change_info_list', '_itemUseInfoList': 'item_use_info_list'}


def item_patches(source, final):
    """Every changed byte belongs to a typed field, or the export refuses."""
    before, after = read_item_layout(source), read_item_layout(final)
    if before.generation != after.generation or set(before.fields) != set(after.fields):
        raise RecordError('DMM V3: incompatible ItemInfo layouts.')
    patches = []
    for field in after.fields:
        if field == '_key' or before.data(field) == after.data(field):
            continue
        reader = Cursor(after.data(field))
        if field in _SCALARS:
            path, fmt = _SCALARS[field]
            value = reader.unpack(fmt)
        elif field in _LISTS:
            path, value = _LISTS[field], array(reader, lambda r: r.unpack('I'))
        elif field == '_stringKey':
            path, value = 'string_key', reader.text()
        elif field in ('_itemName', '_itemDesc'):
            path, value = {'_itemName': 'item_name', '_itemDesc': 'item_desc'}[field], local_string(reader)
        elif field == '_enchantDataList':
            path, value = 'enchant_data_list', array(reader, enchant)
        elif field == '_priceList':
            path, value = 'price_list', array(reader, price)
        elif field == '_dropDefaultData':
            path, value = 'drop_default_data', drop_default(reader)
        elif field == '_equipPassiveSkillList':
            path = 'equip_passive_skill_list'
            value = array(reader, lambda r: record(r, (('skill', 'I'), ('level', 'I'))))
            if len(value) > 4:
                raise RecordError('DMM V3: at most four equipment passive skills are supported.')
        elif field == '_repairDataList':
            path = 'repair_data_list'
            value = array(reader, lambda r: record(r, (('resource_item_info', 'I'), ('repair_value', 'H'),
                                                       ('repair_style', 'B'), ('resource_item_count', 'Q'))))
        elif field in ('_cooltime', '_maxChargedUseableCount'):
            path, fmt = ('cooltime', 'q') if field == '_cooltime' else ('max_charged_useable_count', 'I')
            value = record(reader, tuple((name, fmt) for name in ('a', 'b', 'c')))
        else:
            raise RecordError(f'DMM V3 cannot represent the changed ItemInfo field {field}. Use the existing export.')
        reader.finish()
        patches.append(dict(path=path, new=value))
    # Inherited over-cap lists also exceed the manager guide's supported scope.
    passive = Cursor(after.data('_equipPassiveSkillList'))
    if passive.count() > 4:
        raise RecordError('DMM V3: at most four equipment passive skills are supported.')
    return patches


def stock_value(raw):
    """Decode all bytes of one current StockData entry; only item variants."""
    reader = Cursor(raw)
    result = record(reader, (('lookup_a', 'H'), ('raw_a', 'Q'), ('raw_b', 'Q'), ('raw_c', 'I'),
        ('low_price_threshold_count_116', 'I'), ('raw_d', 'I'), ('raw_e', 'I'), ('order_index_113', 'I'),
        ('flag_a', 'B'), ('flag_b', 'B'), ('flag_c', 'B'), ('is_restore_item', 'B')))
    if reader.unpack('B') != 1:
        raise RecordError('DMM V3: shop stock requires a present item value.')
    value = record(reader, (('raw_q', 'Q'), ('disc', 'B'), ('lookup_a', 'I'), ('lookup_b', 'I'),
        ('lookup_c', 'I'), ('raw_a', 'I'), ('raw_b', 'Q'), ('raw_d', 'Q'), ('raw_e', 'Q'),
        ('raw_f', 'Q'), ('raw_g', 'H')))
    if value['disc'] != 0:
        raise RecordError('DMM V3: only item shop stock is supported.')
    value['payload'] = dict(type='Disc0', body=reader.unpack('I'))
    result.update(value=value, lookup_b=reader.unpack('I'), lookup_c=reader.unpack('I'))
    present = reader.unpack('B')
    if present not in (0, 1):
        raise RecordError('DMM V3: unknown shop stock condition.')
    result['sub_data'] = record(reader, (('lookup_a', 'I'), ('flag', 'B'),
        ('lookup_b', 'I'), ('lookup_c', 'I'))) if present else None
    result['max_refill_condition_201'] = reader.unpack('Q')
    result['effect_list'] = array(reader, lambda r: record(r, (('lookup', 'I'), ('raw', 'Q'))))
    reader.finish()
    return result

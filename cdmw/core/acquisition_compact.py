"""Compact crafting and item reward edits, retaining unassigned source fields."""
import struct

from cdmw.core.compact_static import read_compact_layout
from cdmw.core.item_layout import counted_integers, replace_layout_fields
from cdmw.core.new_item_record import Cursor, RecordError, text_bytes

RECIPE_FLAGS = ('_isWithSealedItem', '_isFromItemInfo', '_isAllowMaterialItemSelfSame',
                '_isMaterialItemOnlySameItemNo', '_isApplyEnchantLevel')


def parse_compact_recipe(raw, *, name="", key_layout=None):
    from cdmw.core.item_recipe_table import ItemRecipe, RecipeIngredient, RecipeGroupIngredient, RecipeElementalStatus, _local_string
    layout = read_compact_layout(raw, 'multichangeinfo', key_layout=key_layout)
    if layout.integer('_isBlocked', width=1):
        raise RecordError('Blocked recipe')
    cursor = Cursor(layout.data('_fixedMaterialDataList'))
    ingredients = []
    for _ in range(cursor.count()):
        item, gimmick, character, count, coupon, level = cursor.unpack('IIIQQH')
        ingredients.append(RecipeIngredient(item, character, gimmick, count, coupon, level))
    cursor.finish()
    cursor = Cursor(layout.data('_recipeItemGroupInfoList'))
    groups = tuple(RecipeGroupIngredient(*cursor.unpack('HQH')) for _ in range(cursor.count()))
    cursor.finish()
    # Conditions (a condition key/inlined condition and its localized refusal message) and
    # elemental material states are validated and retained unchanged.
    if '_staticInfoIndex' in layout.fields:
        for member in layout.members:
            if member.owner == 'FailMessageInfoData' and member.name == '_nakMessage':
                member_cursor = Cursor(raw[member.span.start:member.span.end])
                _local_string(member_cursor)
                member_cursor.finish()
    else:
        cursor = Cursor(layout.data('_conditionList'))
        for _ in range(cursor.count()):
            cursor.unpack('I')
            _local_string(cursor)
        cursor.finish()
    cursor = Cursor(layout.data('_elementalMaterialStateList'))
    for _ in range(cursor.count()):
        cursor.text()
    cursor.finish()
    elemental = layout.integer('_elementalStatusInfo', width=4)
    presentation = layout.data('_description') + b''.join(layout.data(f) for f in
        ('_groupStringInfo','_subGroupStringInfo','_enchantRecipeDesc')) + layout.data('_complteDescription')
    resolved_name = Cursor(layout.data('_stringKey')).text() if '_stringKey' in layout.fields else str(name or '')
    return ItemRecipe(layout.integer('_key',width=4), resolved_name,
        layout.integer('_craftToolInfo',width=2),layout.integer('_itemConsumeType',width=1),
        (RecipeElementalStatus(elemental,bytes(13)),) if elemental else (),
        layout.integer('_needKnowledgeInfo',width=4),Cursor(layout.data('_craftTagName')).text(),
        b''.join(layout.data(f) for f in RECIPE_FLAGS),tuple(ingredients),groups,layout.data('_name'),presentation,
        counted_integers(layout,'_resultDropInfoList'),counted_integers(layout,'_additionalDropInfoList'),raw)


def encode_compact_recipe(row):
    layout = read_compact_layout(row.compact_raw, 'multichangeinfo')
    indexed = '_staticInfoIndex' in layout.fields
    key_layout = 'indexed' if indexed else None
    source = parse_compact_recipe(row.compact_raw, name=row.name, key_layout=key_layout)
    if row == source:
        return row.compact_raw
    if len(row.elemental_statuses)>1 or any(v.label != bytes(13) for v in row.elemental_statuses):
        raise RecordError('Compact recipes carry one elemental status reference without a label.')
    changes = {'_key':struct.pack('<I',row.key),
        '_craftToolInfo':struct.pack('<H',row.tool_key),'_itemConsumeType':bytes([row.consume_type]),
        '_elementalStatusInfo':struct.pack('<I',row.elemental_statuses[0].key if row.elemental_statuses else 0),
        '_needKnowledgeInfo':struct.pack('<I',row.knowledge_key),'_craftTagName':text_bytes(row.craft_tag),
        '_name':row.description}
    if '_stringKey' in layout.fields:
        changes['_stringKey'] = text_bytes(row.name)
    if len(row.flags)!=5 or any(v not in (0,1) for v in row.flags):
        raise RecordError('Unsupported recipe flags')
    changes.update({field:bytes([value]) for field,value in zip(RECIPE_FLAGS,row.flags)})
    changes['_fixedMaterialDataList'] = struct.pack('<I',len(row.ingredients)) + b''.join(
        struct.pack('<IIIQQH',v.item_key,v.gimmick_key,v.character_key,v.quantity,v.coupon_quantity,v.enhancement) for v in row.ingredients)
    changes['_recipeItemGroupInfoList'] = struct.pack('<I',len(row.group_ingredients)) + b''.join(
        struct.pack('<HQH',v.group_key,v.quantity,v.enhancement) for v in row.group_ingredients)
    for field,keys in (('_resultDropInfoList',row.reward_keys),('_additionalDropInfoList',row.additional_reward_keys)):
        changes[field] = struct.pack('<I',len(keys)) + b''.join(struct.pack('<I',v) for v in keys)
    cursor = Cursor(row.presentation)
    cursor.take(9); cursor.text()
    changes['_description'] = row.presentation[:cursor.pos]
    for field in ('_groupStringInfo','_subGroupStringInfo','_enchantRecipeDesc'):
        changes[field] = cursor.take(4)
    start = cursor.pos
    cursor.take(9); cursor.text(); cursor.finish()
    changes['_complteDescription'] = row.presentation[start:]
    result = replace_layout_fields(layout,changes).raw
    if parse_compact_recipe(result, name=row.name, key_layout=key_layout) != row:
        raise RecordError('Edited compact recipe did not round-trip.')
    return result


REWARD_POLICY = (('_isEqualPercent',1),('_dropRollType',1),('_neeSlotCount',2),
                 ('_dropTagNameHash',4),('_dropRollCount',4))


def parse_compact_reward(raw, *, name="", key_layout=None):
    from cdmw.core.item_reward_table import ItemReward, ItemRewardSet
    layout = read_compact_layout(raw, 'dropsetinfo', key_layout=key_layout)
    if layout.integer('_isBlocked',width=1):
        raise RecordError('Blocked reward definition')
    indexed = '_staticInfoIndex' in layout.fields
    cursor = Cursor(layout.data('_list'))
    by_index = {}
    for member in layout.members:
        if member.owner == 'DropInfoData' and member.path[:1] == ('_list',):
            by_index.setdefault(member.path[1], {})[member.name] = member.span
    entries = []
    for index in range(cursor.count()):
        entry_members = by_index[index]
        if cursor.unpack('B') != 1:
            raise RecordError('Reward result type is not a supported item result')
        item,kind = cursor.unpack('QB')
        if kind != 0:
            raise RecordError(f'Non-item reward result type {kind} is not decoded')
        if indexed:
            c1, c2, c3 = (entry_members['_ownerConditionInfo'], entry_members['_playerConditionInfo'],
                          entry_members['_gimmickCachedTargetConditionInfo'])
            cond_bytes = raw[c1.start:c1.end] + raw[c2.start:c2.end] + raw[c3.start:c3.end]
            macro_span = entry_members['_dropTagNameHash']
            macro = int.from_bytes(raw[macro_span.start:macro_span.end], 'little')
            conditions = (
                int(raw[c1.start:c1.end] != b'\0'),
                int(raw[c2.start:c2.end] != b'\0'),
                int(raw[c3.start:c3.end] != b'\0'),
                macro,
            )
            cursor.take(len(cond_bytes) + 4)
        else:
            cond_bytes = b''
            conditions = cursor.unpack('IIII')
        weight,sub,low,high,level = cursor.unpack('QQQQh')
        extra = cursor.take(entry_members['_enchantLevel'].size - 2)
        again = cursor.unpack('I')
        if item != again or not item or low>high or level < -1:
            raise RecordError('Item reward reference or range is not decoded')
        entries.append(ItemReward(item,weight,sub,low,high,level,conditions,extra,cond_bytes))
    cursor.finish()
    resolved_name = Cursor(layout.data('_stringKey')).text() if '_stringKey' in layout.fields else str(name or '')
    return ItemRewardSet(layout.integer('_key',width=4),resolved_name,
        b''.join(layout.data(field) for field,_ in REWARD_POLICY),tuple(entries),layout.data('_needWeight'),
        layout.integer('_totalDropRate',width=8),layout.integer('_rollDiceSkipRate',width=8),
        Cursor(layout.data('_originalString')).text(),raw)


def encode_compact_reward(row):
    layout = read_compact_layout(row.compact_raw, 'dropsetinfo')
    indexed = '_staticInfoIndex' in layout.fields
    key_layout = 'indexed' if indexed else None
    source = parse_compact_reward(row.compact_raw, name=row.name, key_layout=key_layout)
    if row == source:
        return row.compact_raw
    policy = Cursor(row.policy)
    changes = {field:policy.take(width) for field,width in REWARD_POLICY}
    policy.finish()
    entries = []
    source_widths = {len(value.compact_enchant_extra) for value in source.entries}
    for value in row.entries:
        if indexed:
            if value.compact_enchant_extra or len(value.condition_references) != 4:
                raise RecordError('Invalid 3840 reward condition or enchantment payload')
            if not 0 < value.item_key <= 0xffffffff or not 0 <= value.minimum <= value.maximum <= 0xffffffffffffffff:
                raise RecordError('Invalid item reward quantity or identity')
            cond_bytes = value.compact_condition_bytes or b'\0\0\0'
            entries.append(b'\1' + struct.pack('<QB', value.item_key, 0) + cond_bytes
                           + struct.pack('<IQQQQhI', value.condition_references[3], value.weight, value.sub_weight,
                                         value.minimum, value.maximum, value.enhancement, value.item_key))
        else:
            if len(value.compact_enchant_extra) not in (0, 1) or source_widths and len(value.compact_enchant_extra) not in source_widths:
                raise RecordError('Item reward enchantment layout differs from its source')
            if not 0 < value.item_key <= 0xffffffff or not 0 <= value.minimum <= value.maximum <= 0xffffffffffffffff:
                raise RecordError('Invalid item reward quantity or identity')
            entries.append(b'\1'+struct.pack('<QBIIIIQQQQh',value.item_key,0,*value.condition_references,
                value.weight,value.sub_weight,value.minimum,value.maximum,value.enhancement)
                + value.compact_enchant_extra + struct.pack('<I',value.item_key))
    changes.update({'_key':struct.pack('<I',row.key),
        '_list':struct.pack('<I',len(entries))+b''.join(entries), '_needWeight':row.cache,
        '_totalDropRate':struct.pack('<Q',row.total_weight),'_rollDiceSkipRate':struct.pack('<Q',row.skip_weight),
        '_originalString':text_bytes(row.original_string)})
    if '_stringKey' in layout.fields:
        changes['_stringKey'] = text_bytes(row.name)
    result = replace_layout_fields(layout,changes).raw
    if parse_compact_reward(result, name=row.name, key_layout=key_layout) != row:
        raise RecordError('Edited compact reward did not round-trip.')
    return result

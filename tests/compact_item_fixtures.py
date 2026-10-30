"""Owned DLC wire fixtures. Field order and payloads are independent of the reader.

No extracted game bytes are used. Older fixture values are transcribed into the
new wire order, with explicit presence flags and reordered nested records.
"""
import struct

from cdmw.core.item_layout import read_item_layout
from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.core.stringinfo_table import stringinfo_key
from tests.item_layout_fixtures import full_item, counted

ORDER = '''_stringKey _key _isBlocked _maxEndurance _maxStackCount _isRewardLootDrop
_lostItemRecoveryType _isEditableGrime _isDyeable _discardable _useAveragePrice
_isHousingOnly _isDestoryWhenBroken _discardAttachTerrain _isBlockedStoreSell
_enableEquipInCloneActor _isLogoutAtUseItem _isPreservedOnExtract
_isHasItemUseDataInventoryBuff _isPreorderItem _isTowerShieldItem _isShieldItem
_hideFromInventoryOnPopItem _isSaveGameDataAtUseItem _enableAlertSystemToUI _isWild
_isEditorUsable _useMapIconAlert _isExtractAbleItem _useImmediately _applyMaxStackCap
_isAllGimmickSealable _isRegisterTradeMarket _canDisassemble _deleteByGimmickUnlock
_useDropSetTarget _itemType _knowledgeObtainType _itemTier _usableAlertType
_itemChargeType _applyDropStatType _lookDetailMissionInfo _lookDetailGameAdviceInfoWrapper
_convertItemInfoByDropNPC _unpackedItemInfo _itemEffectInfo _brokenItemPrefixString
_equipTypeInfo _materialMatchInfo _mapIconPath _packedItemInfo _gimmickInfo
_destroyEffecInfo _extractAdditionalDropSetInfo _minimumExtractEnchantLevel
_categoryInfo _gimmickUnlockMessageLocalStringInfo _knowledgeInfo _maxDropResultSubItemCount
_equipAbleHash _defaultSubItem _discardOffsetY _stageInfo _materialKey
_sharedCoolTimeGroupNameHash _equipableLevel _maxChargedUseableCount _itemName
_itemDesc _itemDesc2 _itemMemo _filterType _defaultTexturePath _emojiTextureID
_occupiedEquipSlotDataList _itemTagList _itemUseInfoList _itemIconList _equipPassiveSkillList
_gimmickTagList _sealableItemInfoList _sealableCharacterInfoList _sealableGimmickInfoList
_sealableGimmickTagList _sealableTribeInfoList _sealableMoneyInfoList
_transmutationMaterialGimmickList _transmutationMaterialItemList
_transmutationMaterialItemGroupList _multiChangeInfoList _reserveSlotTargetDataList
_dropDefaultData _enchantDataList _priceList _dockingChildData
_changeCharacterDockingChildDataList _inventoryChangeData _fixedPageDataList
_dynamicPageDataList _inspectDataList _inspectAction _cooltime _sharpnessData
_hackableCharacterGroupInfoList _itemGroupInfoList _patternDescriptionDataList
_itemBundleDataList _moneyTypeDefine _factionManagementData _respawnTimeSeconds
_repairDataList _prefabDataList _itemPushInventoryContentsType'''.split()
OPTIONAL = '''_itemDesc2 _occupiedEquipSlotDataList _itemTagList _itemUseInfoList
_equipPassiveSkillList _gimmickTagList _sealableItemInfoList _sealableCharacterInfoList
_sealableGimmickInfoList _sealableGimmickTagList _sealableTribeInfoList _sealableMoneyInfoList
_transmutationMaterialGimmickList _transmutationMaterialItemList
_transmutationMaterialItemGroupList _multiChangeInfoList _reserveSlotTargetDataList
_dropDefaultData _enchantDataList _fixedPageDataList _dynamicPageDataList _inspectDataList
_inspectAction _cooltime _sharpnessData _hackableCharacterGroupInfoList
_patternDescriptionDataList _itemBundleDataList _factionManagementData _repairDataList'''.split()


def text(value):
    raw = value.encode()
    return struct.pack('<I', len(raw)) + raw


def table(rows, width=4):
    body, header = b'', struct.pack('<H', len(rows))
    for key, raw in rows:
        header += key.to_bytes(width, 'little') + struct.pack('<I', len(body))
        body += raw
    return body, header


def item(raw=None, *, fields=None, stems=None, absent=()):
    legacy = read_item_layout(full_item(raw, stems=stems), generation='current')
    data = {name: legacy.data(name) for name in legacy.fields}
    row = parse_iteminfo_row(legacy.raw, structured=True)
    levels = []
    for level in row.enchant_levels:
        value = struct.pack('<H', level.level) + bytes(8)
        value += struct.pack('<I', len(level.stats)) + b''.join(
            struct.pack('<Iii', s.status_key, s.value, s.extra) for s in level.stats)
        value += counted(())
        value += struct.pack('<I', len(level.buy_prices)) + b''.join(
            struct.pack('<IIIII', p.item_key, p.price, *p.reserved, p.item_key) for p in level.buy_prices)
        value += struct.pack('<I', len(level.equip_buffs)) + b''.join(
            struct.pack('<II', k, v) for k, v in zip(level.equip_buffs, level.equip_buff_extras))
        value += bytes(4) + struct.pack('<I', level.tail)
        levels.append(value)
    data.update(_enchantDataList=struct.pack('<I', len(levels)) + b''.join(levels),
        _lostItemRecoveryType=b'\2', _defaultSubItem=b'\x12', _changeCharacterDockingChildDataList=b'\0',
        _defaultTexturePath=struct.pack('<I',0xeac5e173), _emojiTextureID=struct.pack('<I',0xeac5e173),
        _mapIconPath=struct.pack('<I',0xeac5e173),
        _factionManagementData=bytes(17), _itemPushInventoryContentsType=bytes(24))
    data['_dropDefaultData'] = data['_dropDefaultData'][:-3] + b'\x12' + data['_dropDefaultData'][-2:]
    for name in OPTIONAL:
        data[name] = b'\0' if name in absent else b'\1' + data[name]
    if fields:
        data.update(fields)
    return b''.join(data[name] for name in ORDER)


def drop(item_key, *, level=0):
    return b'\1' + struct.pack('<QBIIIIQQQQhI', item_key, 0, 0, 0, 0, 0, 1000000, 0, 1, 1, level, item_key)


def stock(store_key, item_key, index=0):
    return (struct.pack('<HQQIiIiI', store_key, 1000000, 1000000, 1, -1, index, -1, index)
            + b'\1\1\1\0' + drop(item_key) + bytes(8) + b'\0' + bytes(8) + bytes(4))


def store(key, name, items):
    return (text(name) + struct.pack('<H', key) + bytes(10) + bytes(24) + bytes(4)
            + struct.pack('<Q', 1000000) + bytes(4) + struct.pack('<I', len(items))
            + b''.join(stock(key, value, i) for i, value in enumerate(items)) + bytes(8))


def group(key, name, items):
    return text(name) + struct.pack('<H', key) + bytes(6) + bytes(2) + bytes(4) + bytes(13) + bytes(4) + counted(items) + bytes(4)


def recipe(key, name, item_key, reward_key, level=0):
    return (text(name) + struct.pack('<I', key) + b'\0\0\1\1\0\3\1' + bytes(20)
            + struct.pack('<H', 28001) + bytes(8) + struct.pack('<IIIIQQH', 1, item_key, 0, 0, 1, 0, level)
            + bytes(8) + bytes(39) + counted((reward_key,)) + bytes(4))


def reward(key, item_key, level=1):
    return text('OwnedReward') + struct.pack('<I', key) + bytes(13) + struct.pack('<I', 1) + drop(item_key, level=level) + bytes(8) + struct.pack('<Q', 1000000) + bytes(16)


def files():
    from tests.test_new_item_provenance import current_files
    from tests.test_new_item_service import TEMPLATE, STEM, ICON_STRING, MC_ROW_0, MC_ROW_1
    from cdmw.core.structured_binary_editor import parse_pabgh_table
    from cdmw.core.storeinfo_table import parse_store_table
    from cdmw.core.itemgroupinfo_table import parse_item_group_table
    result = current_files()
    from dataclasses import replace
    from cdmw.core.pappt_format import parse_pappt, encode_pappt
    path = 'character/bin__/partprefabtable.pappt'
    pappt = parse_pappt(result[path])
    socket_path = 'character/sockets/compact_test.sockets.xml'
    result[path] = encode_pappt(replace(pappt, records=tuple(replace(r, sockets_path=socket_path) for r in pappt.records)))
    result[socket_path] = b'<Sockets/>'
    from tests.test_pac_xml_standard_material import HEAD, TAIL, wrapper, STANDARD_SHADER
    for path in tuple(result):
        if path.endswith('.pac_xml'):
            result[path] = (HEAD + wrapper(STEM, STANDARD_SHADER, '') + TAIL).encode()
    root = 'gamedata/binarystaticinfo__/bin/'
    def rows(kind):
        body, head = result[root+kind+'.staticinfobody'], result[root+kind+'.staticinfoheader']
        return [(r.row_id, body[s:e]) for r, s, e in parse_pabgh_table(head, payload=body).row_spans(len(body))]
    def put(kind, values, width=4):
        result[root+kind+'.staticinfobody'], result[root+kind+'.staticinfoheader'] = table(values, width)
    converted = []
    for key, raw in rows('iteminfo'):
        stems = (STEM+'_r', 'cd_phm_01_sword_0168_r_in_index01', STEM+'_l') if key == TEMPLATE else ()
        fields = {'_itemIconList': struct.pack('<III', 1, stringinfo_key(ICON_STRING), 0) + bytes(6),
                  '_multiChangeInfoList': b'\1' + counted((MC_ROW_0, MC_ROW_1))} if key == TEMPLATE else None
        converted.append((key, item(raw, stems=stems, fields=fields)))
    put('iteminfo', converted)
    put('stringinfo', [(key, bytes(4)+raw[:4]+raw[8:]) for key, raw in rows('stringinfo')])
    stores = parse_store_table(result[root+'storeinfo.staticinfobody'], result[root+'storeinfo.staticinfoheader'], layout='current')
    put('storeinfo', [(s.key, store(s.key, s.name, [e.item_key for e in s.entries])) for s in stores], 2)
    groups = parse_item_group_table(result[root+'itemgroupinfo.staticinfobody'], result[root+'itemgroupinfo.staticinfoheader'])
    put('itemgroupinfo', [(g.key, group(g.key, g.name, g.members)) for g in groups], 2)
    put('multichangeinfo', [(key, recipe(key, 'Owned_'+str(level), TEMPLATE, 880000+level, level)) for level, key in enumerate((MC_ROW_0, MC_ROW_1))])
    put('dropsetinfo', [(880000+i, reward(880000+i, TEMPLATE, i+1)) for i in range(2)])
    for kind in ('itemuseinfo', 'knowledgeinfo'):
        values = []
        for key, raw in rows(kind):
            length = int.from_bytes(raw[4:8], 'little')
            values.append((key, raw[4:8+length]+raw[:4]+raw[8+length:]))
        put(kind, values)
    put('crafttoolinfo', [(28001, text('Enchant')+struct.pack('<H', 28001)+b'\0')], 2)
    for kind in ('statusinfo','equiptypeinfo'):
        put(kind, [(key,text(raw[8:8+int.from_bytes(raw[4:8],'little')].rstrip(b'\0').decode())+struct.pack('<I',key)+b'\0')
                   for key,raw in rows(kind)])
    categories = sorted({parse_iteminfo_row(raw,structured=True).category_info for _,raw in converted})
    put('categoryinfo', [(key,text('Category_'+str(key))+struct.pack('<H',key)+b'\0') for key in categories if key],2)
    return result

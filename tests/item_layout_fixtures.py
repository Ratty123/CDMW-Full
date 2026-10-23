"""Owned complete ItemInfo records with independently constructed field payloads."""
import struct

from cdmw.core._item_layout_schema import ITEMINFO_FIELDS
from cdmw.core.archive_format import hashlittle
from cdmw.core.iteminfo_row import parse_iteminfo_row
from tests.test_iteminfo_row import build_row


_BYTE_FIELDS = '''_isBlocked _useMapIconAlert _itemType _knowledgeObtainType _useImmediately
_applyMaxStackCap _useDropSetTarget _isAllGimmickSealable _deleteByGimmickUnlock _canDisassemble
_isRegisterTradeMarket _isEditorUsable _discardable _isDyeable _isEditableGrime _isDestoryWhenBroken
_isHousingOnly _isExtractAbleItem _quickSlotIndex _itemTier _isImportantItem _isRewardLootDrop
_applyDropStatType _dockingChildData _inventoryChangeData _itemChargeType _usableAlertType
_discardAttachTerrain _hideFromInventoryOnPopItem _isShieldItem _isTowerShieldItem _isWild
_enableAlertSystemToUI _isSaveGameDataAtUseItem _isLogoutAtUseItem _moneyTypeDefine
_enableEquipInCloneActor _isBlockedStoreSell _isPreorderItem _isHasItemUseDataInventoryBuff
_isPreservedOnExtract _useAveragePrice'''.split()


def counted(values, fmt='I'):
    return struct.pack('<I', len(values)) + b''.join(struct.pack('<' + fmt, value) for value in values)


def full_item(raw=None, *, current=True, fields=None, stems=None):
    row = parse_iteminfo_row(build_row() if raw is None else raw)
    data = {name: bytes(4) for name in ITEMINFO_FIELDS}
    data.update({name: bytes(1) for name in _BYTE_FIELDS})
    data.update({name: bytes(2) for name in ('_categoryInfo', '_minimumExtractEnchantLevel', '_maxEndurance')})
    data.update({name: bytes(13) for name in ('_itemName', '_itemDesc', '_itemDesc2')})
    data.update(_maxStackCount=struct.pack('<Q', row.max_stack_count), _respawnTimeSeconds=bytes(8),
                _maxChargedUseableCount=bytes(12), _defaultSubItem=b'\x11',
                _factionManagementData=bytes(13 if current else 9),
                _inspectAction=bytes(16 if current else 12), _sharpnessData=bytes(20),
                _itemPushInventoryContentsType=bytes(20 if current else 18), _cooltime=bytes(24))
    def text(value):
        payload = value.encode('utf-8')
        return struct.pack('<I', len(payload)) + payload
    data['_key'] = struct.pack('<I', row.key)
    data['_stringKey'] = text(row.string_key)
    data['_itemName'] = b'\x07\x70\0\0\0' + struct.pack('<I', row.key) + text(row.name_key)
    data['_itemDesc'] = b'\x07\x71\0\0\0' + struct.pack('<I', row.key) + text(row.desc_key or 'description')
    data['_equipTypeInfo'] = struct.pack('<I', row.equip_type_key)
    data['_categoryInfo'] = struct.pack('<H', row.category_info or 0)
    data['_itemMemo'] = text(row.memo or '')
    data['_itemTier'] = b'\x03'
    data['_maxEndurance'] = struct.pack('<H', 430)
    if row.stat_block_offset is not None:
        marker = row.stat_block_offset + 8 + 4 * len(row.socket_items) + 12 * len(row.add_socket_materials)
        price = row.stat_block_end - 4 - 20 * len(row.price_list)
        data['_dropDefaultData'] = b'\0\0' + row.raw[row.stat_block_offset:marker] + bytes([18 if current else 17, len(row.socket_items), int(bool(row.add_socket_materials))])
        data['_enchantDataList'] = row.raw[marker + 3:price]
        data['_priceList'] = row.raw[price:row.stat_block_end]
    else:
        data['_dropDefaultData'] = b'\0\0' + bytes(8) + b'\x11\0\0'
    if stems is not None:
        names = [hashlittle(stem.encode(), 0xC5EDE) for stem in stems]
        prefab = struct.pack('<3f', 1, 1, 1) + counted(names) + bytes(12) + bytes(7)
        data['_prefabDataList'] = struct.pack('<I', 1) + prefab
    if fields:
        data.update(fields)
    return b''.join(data[name] for name in ITEMINFO_FIELDS)


def use_action(key=1000031, kind=9, payload=b'', *, conditions=()):
    name = b'OwnedTestUse'
    # Kind, four flags, reserve-slot ref, use-text ref, two flags, equip hash,
    # then the condition refs. This is independent of the grammar interpreter.
    common = bytes(18) + struct.pack('<I', len(conditions)) + b''.join(conditions)
    return struct.pack('<II', key, len(name)) + name + b'\0' + bytes([kind]) + common + payload

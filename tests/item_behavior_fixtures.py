"""Independently packed nonempty values for every remaining ItemInfo family."""
import struct

from tests.item_layout_fixtures import counted


def text(value):
    raw = value.encode('utf-8')
    return struct.pack('<I', len(raw))+raw


def local(key=(1001295 << 32) | 0x77):
    return struct.pack('<BQ', 7, key)+text(str(key))


def behavior_fields(current=True):
    page = text('ui/texture/left.dds')+text('ui/texture/right.dds')+struct.pack('<II', 600001, 600002)
    inspection = struct.pack('<IIII',1001295,700001,900001,0xffffffff)+text('socket')
    inspection += struct.pack('<IIBI',900001,7654,1,600001)+local()+struct.pack('<IBII',789,255,654,0)
    inspection += struct.pack('<BIBBII',1,600002,1,0,500001,500002)
    docking = b'\1'+struct.pack('<III',700001,900001,1001295)+text('parent')+text('child')
    docking += struct.pack('<4IHI',1,2,3,4,65535,0xffffffff)+bytes([1,0,1,255,0,1])+struct.pack('<I',400001)
    docking += bytes([1,255,1,0,1,0])+text('dock_slot')+b'\1'+struct.pack('<4I',5,6,7,8)+text('root_bone')
    unit = struct.pack('<I',42)+text('UI_Money')+struct.pack('<III',0xffffffff,111,222)+local()+local()
    prefab = struct.pack('<3f',1.25,0.5,-2.0)+counted((111,112))+counted((113,114))
    prefab += counted((65535,0),'H')+counted((115,116))+struct.pack('<IBBB',117,1,0,255)
    return {
        '_itemType':b'\xff','_categoryInfo':struct.pack('<H',65535),'_equipTypeInfo':struct.pack('<I',0xffffffff),
        '_materialKey':struct.pack('<I',123),'_materialMatchInfo':struct.pack('<I',456),
        '_itemGroupInfoList':counted((17001,65535),'H'),'_hackableCharacterGroupInfoList':counted((4,5),'H'),
        '_stageInfo':struct.pack('<I',300001),'_lookDetailGameAdviceInfoWrapper':struct.pack('<I',300002),
        '_lookDetailMissionInfo':struct.pack('<I',300003),'_brokenItemPrefixString':struct.pack('<I',333),
        '_itemMemo':text('Owned memo'),'_filterType':text('Owned filter'),
        '_defaultTexturePath':text('ui/texture/default.dds'),'_emojiTextureID':text('Emoji_Owned'),
        '_applyDropStatType':b'\xff',
        '_dropDefaultData':struct.pack('<H',65535)+counted((1001295,))+struct.pack('<IIQ',1,1001295,(1<<64)-1)
            +struct.pack('<BI',3,900001)+b'\1\1',
        '_defaultSubItem':struct.pack('<BI',9,700001),'_discardOffsetY':struct.pack('<I',0xffffffff),
        '_discardAttachTerrain':b'\1','_fixedPageDataList':struct.pack('<I',1)+page,
        '_dynamicPageDataList':struct.pack('<I',2)+page+page,
        '_inspectDataList':struct.pack('<I',1)+inspection,
        '_inspectAction':struct.pack('<I',123)+(struct.pack('<I',456) if current else b'')+text('catcher')+text('target'),
        '_dockingChildData':docking,'_inventoryChangeData':b'\1'+struct.pack('<BIIIH',255,400001,400002,400003,65535),
        '_moneyTypeDefine':b'\1'+struct.pack('<QI',(1<<64)-1,1)+unit,
        '_itemIconList':struct.pack('<IIIB',1,111,222,1)+counted((333,444))+b'\0',
        '_prefabDataList':struct.pack('<I',1)+prefab,
    }

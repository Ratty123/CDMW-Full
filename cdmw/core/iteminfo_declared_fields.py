"""Closed named root fields shared by stock-item authoring and composition."""
from cdmw.core.item_layout import read_item_layout, replace_layout_fields
from cdmw.core.iteminfo_behavior import read_value, write_value
from cdmw.core.iteminfo_definition import read_definition_fields, set_definition_fields
from cdmw.core.new_item_record import Cursor, RecordError
from cdmw.domain.new_item import item_inventory as inventory, item_settings as settings, item_definition as definition
from cdmw.domain.new_item.item_behavior import BEHAVIOR_FIELDS, LOCAL, array, record, sequence, validate_value


PRICE=record(item='u32',amount='u64',symbol='u32',wrapper='u32')
# Signed stat counters are handled explicitly below; descriptors never come from a package.
ENCHANT=record(level='u16',maximum=sequence(record(stat='u32',value='i64')),
    regeneration=sequence(record(stat='u32',value='i64')),static=sequence(record(stat='u32',value='i64')),
    parameters=sequence(record(stat='u32',value='u8')),prices=sequence(PRICE),
    buffs=sequence(record(buff='u32',level='u32')),effect='u32')

FIELDS={('behavior',name):(field,shape) for name,(field,shape,_section) in BEHAVIOR_FIELDS.items()}
FIELDS.update({('properties',name):(field,shape) for name,field,shape in (
    ('item_tier','_itemTier','u8'),('required_level','_equipableLevel','u32'),('max_durability','_maxEndurance','u16'))})
FIELDS.update({('text',name):(field,LOCAL) for name,field in (
    ('name','_itemName'),('description','_itemDesc'),('secondary_description','_itemDesc2'))})
FIELDS.update({('settings',name):(field,'bool') for name,field in settings.POLICY_FIELDS.items()})
FIELDS.update({('settings',name):(field,'u'+str(width*8)) for name,(field,width) in settings.SCALAR_FIELDS.items()})
FIELDS.update({('settings','repairs'):('_repairDataList',sequence(record(resource_item='u32',repair_value='u16',repair_style='u8',resource_count='u64'),128)),
    ('settings','use_actions'):('_itemUseInfoList',sequence('u32',128)),
    ('settings','cooldowns'):('_cooltime',array('u64',3)),
    ('settings','maximum_charges'):('_maxChargedUseableCount',array('u32',3)),
    ('stats','passive_skills'):('_equipPassiveSkillList',sequence(record(skill_key='u32',level='u32'),128)),
    ('progression','enchantments'):('_enchantDataList',sequence(ENCHANT,40)),
    ('progression','prices'):('_priceList',sequence(PRICE,128))})
FIELDS.update({('inventory',name):(field,'bool') for name,field in inventory.BOOLEAN_FIELDS.items()})
FIELDS.update({('inventory',name):(field,'u'+str(width*8)) for name,(field,width,_minimum,_maximum) in inventory.INTEGER_FIELDS.items()})
FIELDS.update({('inventory',name):(field,sequence('u32')) for name,field in inventory.LIST_FIELDS.items()})
FIELDS.update({('inventory','reserve_slots'):('_reserveSlotTargetDataList',sequence(record(slot_key='u32',condition_key='u32'))),
    ('inventory','material_groups'):('_transmutationMaterialItemGroupList',sequence(record(group_key='u16',value='u32')))})
DEFINITION_ROOTS={name:row[0] for group in (definition.FLAGS,definition.NUMBERS,definition.COLLECTIONS) for name,row in group.items()}


def field_root(selector):
    if selector[0]=='definition' and selector[1] in DEFINITION_ROOTS: return DEFINITION_ROOTS[selector[1]]
    if selector not in FIELDS: raise RecordError('Unsupported declared ItemInfo field selector.')
    return FIELDS[selector][0]


def validate_field_value(selector,value):
    field_root(selector)
    if selector[0]=='definition':
        definition.decode_definition_settings({'fields':{selector[1]:value},'secondary_description':None})
    else:
        validate_value(FIELDS[selector][1],value)
        family,name=selector
        if family=='behavior':
            from cdmw.domain.new_item.item_behavior import decode_behavior_settings
            decode_behavior_settings({'fields':{name:value}})
        elif family=='inventory':
            inventory.decode_inventory_settings(dict.fromkeys(inventory.INVENTORY_FIELDS) | {name:value})
        elif family=='settings':
            settings.decode_settings(dict.fromkeys(settings.SETTINGS_FIELDS) | {'quantities':[],name:value})
        elif family=='stats':
            from cdmw.domain.new_item.item_stats import decode_stat_settings
            decode_stat_settings({'statistics':[],'passive_skills':value})
        elif family=='progression':
            def unique(rows,key):
                if len({row[key] for row in rows})!=len(rows): raise RecordError('Duplicate progression selector.')
            def prices(rows):
                unique(rows,'item')
                if any(row['item']==0 or row['wrapper']!=row['item'] for row in rows):
                    raise RecordError('Unqualified price item wrapper.')
            if name=='prices': prices(value)
            else:
                unique(value,'level')
                for level in value:
                    for group in ('maximum','regeneration','static','parameters'):
                        unique(level[group],'stat')
                        if any(row['stat']==0 for row in level[group]): raise RecordError('A stat requires a StatusInfo key.')
                    unique(level['buffs'],'buff'); prices(level['prices'])
                    if any(row['buff']==0 for row in level['buffs']): raise RecordError('A buff requires a BuffInfo key.')


def read_field(raw,selector):
    validate_root=field_root(selector)
    if selector[0]=='definition': return read_definition_fields(raw)[selector[1]]
    layout=read_item_layout(raw); cursor=Cursor(layout.data(validate_root))
    value=read_value(cursor,FIELDS[selector][1],generation=layout.generation,owner=selector[1]); cursor.finish()
    return value


def write_field(raw,selector,value):
    validate_field_value(selector,value)
    if selector[0]=='definition': return set_definition_fields(raw,{selector[1]:value})
    layout=read_item_layout(raw); field,shape=FIELDS[selector]
    data=write_value(shape,value,generation=layout.generation,owner=selector[1])
    return replace_layout_fields(layout,{field:data}).raw

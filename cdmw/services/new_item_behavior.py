"""Source-qualified references/resources for remaining ItemInfo behavior fields."""
from dataclasses import dataclass
import json

from cdmw.core.iteminfo_behavior import read_behavior_fields, set_behavior_fields
from cdmw.core.new_item_record import Cursor, RecordError
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.item_behavior import BEHAVIOR_FIELDS
from cdmw.services.new_item_definition import (load_definition_index, _qualified_reference,
    _localization_reference, resolve_map_icon, REFERENCE_TABLES)
from cdmw.services.new_item_settings import _rows


BEHAVIOR_TABLES = {'categoryinfo': 2, 'equiptypeinfo': 4, 'charactergroupinfo': 2,
                   'itemgroupinfo': 2, 'stageinfo': 4, 'gameadviceinfo': 4, 'missioninfo': 4, 'conditioninfo': 4}


@dataclass(frozen=True)
class BehaviorIndex:
    choices: dict
    observed: dict
    unavailable: tuple
    localizations: dict


def named_reference(snapshot, table, key, *, stop_event=None):
    raise_if_cancelled(stop_event)
    if not key: return
    if table in REFERENCE_TABLES or table == 'iteminfo':
        return _qualified_reference(snapshot, table, key, stop_event=stop_event)
    width = BEHAVIOR_TABLES[table]
    raw = _rows(snapshot, table, key_width=width, stop_event=stop_event).get(key)
    if raw is None: raise RecordError(f'Missing {table} dependency {key}.')
    cursor = Cursor(raw); cursor.take(width); cursor.text()
    if cursor.unpack('B') != 0: raise RecordError(f'Blocked {table} dependency {key}.')


def load_behavior_index(snapshot, *, stop_event=None):
    raise_if_cancelled(stop_event)
    cached = snapshot._authoring_indexes.get('item-behavior')
    if cached is not None: return cached
    parent = load_definition_index(snapshot, stop_event=stop_event)
    choices = dict(parent.choices); unavailable = list(parent.unavailable)
    for table,width in BEHAVIOR_TABLES.items():
        raise_if_cancelled(stop_event)
        if snapshot.sources is None or table not in snapshot.sources.tables:
            choices[table] = (); unavailable.append(table); continue
        named = []
        for key,raw in _rows(snapshot, table, key_width=width, stop_event=stop_event).items():
            raise_if_cancelled(stop_event)
            try:
                cursor = Cursor(raw); cursor.take(width); name = cursor.text()
                if cursor.unpack('B') == 0: named.append((key,name))
            except (ValueError,UnicodeError): continue
        choices[table] = tuple(sorted(named))
    observed = {name:[] for name in BEHAVIOR_FIELDS}
    seen = {name:set() for name in BEHAVIOR_FIELDS}
    localizations = dict(parent.localizations)
    english = snapshot.english.index()
    def collect_text(value):
        if isinstance(value,dict):
            if set(value)=={'category','key','text_key'} and value['text_key'] in english:
                localizations.setdefault(value['text_key'],dict(value))
            else:
                for child in value.values(): collect_text(child)
        elif isinstance(value,list):
            for child in value: collect_text(child)
    for row in snapshot.rows.values():
        raise_if_cancelled(stop_event)
        if row.is_blocked: continue
        try: values = read_behavior_fields(row.raw)
        except (ValueError,UnicodeError): continue
        for name,value in values.items():
            identity = json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            if identity not in seen[name]: observed[name].append(value); seen[name].add(identity)
            collect_text(value)
    choices['stringinfo'] = tuple(sorted(snapshot.stringinfo_texts.items()))
    # The .dds listing, not a sort of every resident entry (79 s on 2026-10-26).
    choices['texture'] = tuple((path,path) for path in sorted(snapshot.entry_paths_with_extensions(('.dds',))))
    result = BehaviorIndex(choices,observed,tuple(sorted(set(unavailable))),localizations)
    raise_if_cancelled(stop_event)
    snapshot._authoring_indexes['item-behavior'] = result
    return result


def string_reference(snapshot, key, *, stop_event=None):
    raise_if_cancelled(stop_event)
    if not key: return ''
    value = snapshot.stringinfo_texts.get(key)
    if not value or stringinfo_key(value) != key: raise RecordError('Unqualified behavior StringInfo reference.')
    return value


def texture_reference(snapshot, value, *, stop_event=None):
    raise_if_cancelled(stop_event)
    if not value: return
    if value.lower().endswith('.dds'):
        from cdmw.services.independent_item_package import virtual_path
        from cdmw.core.pathc_format import validate_dds_payload
        path = virtual_path(value.replace('\\','/').lower())
        if not snapshot.has_entry(path): raise RecordError(f'Missing behavior texture dependency {path}.')
        validate_dds_payload(snapshot.payload(path))
    else:
        resolve_map_icon(snapshot,stringinfo_key(value),stop_event=stop_event)


def _subitem(snapshot, value, stop_event):
    table = {3:'characterinfo',9:'gimmickinfo'}.get(value['type'])
    if table: named_reference(snapshot,table,value['value'],stop_event=stop_event)


def validate_behavior_dependencies(raw, snapshot, *, stop_event=None):
    values = read_behavior_fields(raw)
    def ref(table,key): named_reference(snapshot,table,key,stop_event=stop_event)
    for field,table in (('category','categoryinfo'),('equipment_type','equiptypeinfo'),('stage','stageinfo'),
                        ('advice','gameadviceinfo'),('mission','missioninfo')):
        ref(table,values[field])
    for field,table in (('item_groups','itemgroupinfo'),('hackable_character_groups','charactergroupinfo')):
        for key in values[field]: ref(table,key)
    for field in ('default_texture','emoji_texture'):
        texture_reference(snapshot,values[field],stop_event=stop_event)
    for field in ('fixed_pages','dynamic_pages'):
        for page in values[field]:
            for side in ('left','right'):
                texture_reference(snapshot,page[side+'_texture'],stop_event=stop_event)
                ref('knowledgeinfo',page[side+'_knowledge'])
    for row in values['inspections']:
        for field,table in (('item','iteminfo'),('gimmick','gimmickinfo'),('character','characterinfo'),
            ('speak_character','characterinfo'),('reward_knowledge','knowledgeinfo'),('page_knowledge','knowledgeinfo'),
            ('effect','effectinfo'),('complete_effect','effectinfo')):
            ref(table,row[field])
        _localization_reference(snapshot,row['description'],stop_event=stop_event)
    _subitem(snapshot,values['default_subitem'],stop_event)
    drop = values['drop_defaults']; _subitem(snapshot,drop['subitem'],stop_event)
    for key in drop['socket_items']: ref('iteminfo',key)
    for slot in drop['socket_materials']: ref('iteminfo',slot['item'])
    if drop['valid_sockets'] > len(drop['socket_items']): raise RecordError('Drop socket count exceeds the declared item list.')
    docking = values['docking']
    if docking is not None:
        for field,table in (('gimmick','gimmickinfo'),('character','characterinfo'),('item','iteminfo'),('npc_only','conditioninfo')):
            ref(table,docking[field])
    change = values['inventory_change']
    if change is not None:
        for field in ('player_condition','target_condition','event_condition'): ref('conditioninfo',change[field])
    money = values['money']
    if money is not None:
        for unit in money['units']:
            for field in ('icon','money_icon'): resolve_map_icon(snapshot,unit[field],stop_event=stop_event)
            for field in ('name','description'): _localization_reference(snapshot,unit[field],stop_event=stop_event)
    for icon in values['icons']:
        for field in ('icon','highlight_icon'): resolve_map_icon(snapshot,icon[field],stop_event=stop_event)
    for prefab in values['prefabs']:
        raise_if_cancelled(stop_event)
        for key in prefab['prefabs']:
            name = string_reference(snapshot,key,stop_event=stop_event)
            part = snapshot.pappt.index().get(name)
            if part is None: raise RecordError('Behavior prefab has no qualified PAPPT binding.')
            if not snapshot.has_entry(part.prefab_path): raise RecordError('Missing behavior prefab dependency.')
            snapshot.payload(part.prefab_path)
        for key in prefab['animations']:
            from cdmw.services.independent_item_package import virtual_path
            path = virtual_path(string_reference(snapshot,key,stop_event=stop_event).replace('\\','/').lower())
            if not snapshot.has_entry(path): raise RecordError('Missing behavior animation dependency.')
            if not snapshot.payload(path): raise RecordError('Empty behavior animation dependency.')
        for key in (*prefab['tribe_genders'],prefab['docking_switch']): string_reference(snapshot,key,stop_event=stop_event)
    raise_if_cancelled(stop_event)


def apply_behavior(raw, settings, snapshot, *, stop_event=None):
    output = set_behavior_fields(raw,dict(settings.fields))
    from cdmw.services.iteminfo_dependency_graph import validate_item_graph
    validate_item_graph(output,snapshot,stop_event=stop_event)
    return output

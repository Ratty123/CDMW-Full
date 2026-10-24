"""Bounded traversal of declared ItemInfo references and borrowed resources.

Only established reference fields are followed. Opaque auxiliary payloads keep
their complete table/resource witnesses and are reported as partial closure.
"""
from dataclasses import dataclass
from hashlib import sha256
import xml.etree.ElementTree as ET

from cdmw.core.iteminfo_behavior import read_behavior_fields
from cdmw.core.iteminfo_declared_fields import read_field
from cdmw.core.iteminfo_definition import read_definition_fields
from cdmw.core.iteminfo_inventory import read_item_inventory
from cdmw.core.iteminfo_settings import read_item_settings
from cdmw.core.new_item_record import RecordError
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.item_definition import SEAL_TARGETS


MAX_ITEMS = 1024
MAX_RESOURCES = 4096
MAX_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True)
class ItemDependencyGraph:
    item_keys: frozenset
    resources: tuple
    unresolved: tuple


def item_references(raw):
    """Actual complete-field references, never a search for integer byte patterns."""
    behavior=read_behavior_fields(raw); definition=read_definition_fields(raw)
    inventory=read_item_inventory(raw); settings,_=read_item_settings(raw)
    result=set(behavior['drop_defaults']['socket_items'])
    result.update(row['item'] for row in behavior['drop_defaults']['socket_materials'])
    result.update(row['item'] for row in behavior['inspections'])
    if behavior['docking'] is not None: result.add(behavior['docking']['item'])
    result.update(definition[name] for name in ('packed_item','unpacked_item','drop_npc_item'))
    for name in ('sealable_items','sealable_characters','sealable_gimmicks','sealable_tags','sealable_tribes'):
        for target in definition[name]:
            result.add(target['item'])
            if SEAL_TARGETS[target['target_type']]=='iteminfo': result.add(target['target'])
    for name in ('costs','prices'): result.update(row['item'] for row in definition['faction'][name])
    result.update(inventory.material_items)
    result.update(row.resource_item for row in settings.repairs)
    result.update(row['item'] for row in read_field(raw,('progression','prices')))
    for level in read_field(raw,('progression','enchantments')):
        result.update(row['item'] for row in level['prices'])
    return result-{0}


def validate_item_graph(raw, snapshot, *, stop_event=None):
    """Qualify outgoing item references recursively; preserve unknown boundaries."""
    from cdmw.services.new_item_behavior import validate_behavior_dependencies, string_reference
    from cdmw.services.new_item_definition import validate_definition_dependencies
    from cdmw.services.new_item_settings import (validate_inventory_dependencies, validate_stat_dependencies,
        validate_settings_dependencies, validate_reward, load_use_action, _reference)
    from cdmw.services.independent_item_package import virtual_path
    from cdmw.core.item_layout import read_item_layout

    raise_if_cancelled(stop_event)
    cache_key=('declared-item-graph',sha256(raw).hexdigest())
    cached=snapshot._authoring_indexes.get(cache_key)
    if cached is not None: return cached
    root=read_item_layout(raw).integer('_key')
    pending=[(root,raw)]; visited=set(); resources=set(); unresolved=set()
    while pending:
        raise_if_cancelled(stop_event)
        key,data=pending.pop()
        if key in visited: continue
        visited.add(key)
        if len(visited)>MAX_ITEMS: raise RecordError('The declared item dependency graph exceeds its item limit.')
        try: read_item_layout(data)
        except ValueError:
            # Older source adapters may retain a row with an opaque tail. The
            # whole row remains protected; it cannot establish parsed closure.
            if key==root: raise
            unresolved.add(f'ItemInfo {key}: retained source row has an opaque layout.')
            row=snapshot.rows[key]
            outgoing=set(row.socket_items)
            outgoing.update(value for value,_count,_extra in row.add_socket_materials)
            outgoing.update(value.item_key for value in row.price_list)
            outgoing.update(value.item_key for level in row.enchant_levels for value in level.buy_prices)
        else:
            validate_behavior_dependencies(data,snapshot,stop_event=stop_event)
            validate_definition_dependencies(data,snapshot,stop_event=stop_event)
            validate_inventory_dependencies(data,snapshot,stop_event=stop_event)
            validate_stat_dependencies(data,snapshot,stop_event=stop_event)
            settings,_=read_item_settings(data)
            validate_settings_dependencies(settings,snapshot,stop_event=stop_event)
            outgoing=item_references(data)
            rewards=[]
            if settings.extraction_reward: rewards.append(settings.extraction_reward)
            for action_key in settings.use_actions:
                action=load_use_action(snapshot,action_key,stop_event=stop_event)
                if action.kind==2:
                    from cdmw.core.item_use_reward import parse_item_use_reward
                    rewards.append(parse_item_use_reward(action.layout.raw).reward_key)
            for reward_key in rewards:
                reward=validate_reward(snapshot,reward_key,stop_event=stop_event)
                outgoing.update(entry.item_key for entry in reward.entries)
            for level in read_field(data,('progression','enchantments')):
                for buff in level['buffs']: _reference(snapshot,'buffinfo',buff['buff'],stop_event=stop_event)
                if level['effect']: _reference(snapshot,'effectinfo',level['effect'],stop_event=stop_event)
            behavior=read_behavior_fields(data)
            for prefab in behavior['prefabs']:
                for symbol in prefab['prefabs']:
                    part=snapshot.pappt.index()[string_reference(snapshot,symbol,stop_event=stop_event)]
                    resources.add(part.prefab_path)
                    if part.sockets_path: resources.add(part.sockets_path)
                resources.update(string_reference(snapshot,symbol,stop_event=stop_event) for symbol in prefab['animations'])
            for name in ('default_texture','emoji_texture'):
                value=behavior[name]
                if value and value.lower().endswith('.dds'): resources.add(value)
            for name in ('fixed_pages','dynamic_pages'):
                for page in behavior[name]:
                    resources.update(page[side+'_texture'] for side in ('left','right')
                                     if page[side+'_texture'].lower().endswith('.dds'))
            # These tables are qualified and pinned by the direct validators;
            # their arbitrary game-condition/effect payloads are not decoded.
            unresolved.add('Auxiliary table payloads and runtime conditions remain exact-source dependencies; their complete outgoing graph is unverified.')
        for target in sorted(outgoing):
            raise_if_cancelled(stop_event)
            row=snapshot.rows.get(target)
            if row is None or row.is_blocked: raise RecordError(f'Missing or blocked nested ItemInfo dependency {target}.')
            _reference(snapshot,'iteminfo',target,stop_event=stop_event)
            if target not in visited: pending.append((target,row.raw))
        if len(visited)+len({key for key,_data in pending})>MAX_ITEMS:
            raise RecordError('The declared item dependency graph exceeds its item limit.')

    todo=list(resources); checked=set(); total=0
    while todo:
        raise_if_cancelled(stop_event)
        path=virtual_path(todo.pop().replace('\\','/').lower())
        if path in checked: continue
        checked.add(path)
        if len(checked)>MAX_RESOURCES: raise RecordError('The declared resource graph exceeds its resource limit.')
        if not snapshot.has_entry(path): raise RecordError(f'Missing nested resource dependency {path}.')
        data=snapshot.payload(path); total+=len(data)
        if total>MAX_BYTES: raise RecordError('The declared resource graph exceeds its byte limit.')
        children=[]
        if path.endswith('.prefab'):
            from cdmw.core.prefab_binary import decode_prefab_binary
            document=decode_prefab_binary(data)
            if not document.walk_complete or document.inferred_objects or document.blob_offset+document.blob_length!=len(data):
                raise RecordError('The borrowed prefab reference layout is incomplete.')
            children.extend(value.text for value in document.resource_strings())
        elif path.endswith('.pac'):
            from cdmw.services.new_item_variants import xml_path
            sidecar=xml_path(path)
            if snapshot.has_entry(sidecar): children.append(sidecar)
            unresolved.add(f'Implicit skeleton, animation and physics lookup remains unverified: {path}')
        elif path.endswith('.pac_xml'):
            if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper(): raise RecordError('Unsupported model XML declaration.')
            try: tree=ET.fromstring('<Model>'+data.decode('utf-8-sig')+'</Model>')
            except (UnicodeError,ET.ParseError) as exc: raise RecordError('Unsupported borrowed model XML.') from exc
            for node in tree.iter():
                if node.tag.startswith('ResourceReferencePath'):
                    if set(node.attrib)-{'Name','_path'}: raise RecordError('Unknown borrowed model resource boundary.')
                    if node.attrib.get('_path'): children.append(node.attrib['_path'])
        elif path.endswith('.dds'):
            from cdmw.core.pathc_format import validate_dds_payload
            validate_dds_payload(data)
        elif path.endswith(('.pae','.paem','.parg','.pasg')):
            from cdmw.core.effect_binary import decode_effect_binary
            from cdmw.core.effect_edit import emitter_paths_of,preset_names_of,preset_path
            document=decode_effect_binary(data)
            if not document.walk_complete: raise RecordError('The borrowed effect reference layout is incomplete.')
            children.extend((*document.resources(),*emitter_paths_of(document),
                *(node.type_name.lstrip('/') for node in document.root.walk() if node.type_name.lower().endswith('.paem')),
                *(preset_path(kind,name) for kind,name in preset_names_of(document))))
        else: unresolved.add(f'Borrowed resource outgoing references remain unverified: {path}')
        for child in children:
            if child.endswith('.effect') and '/' not in child: child='effect/binary__/releasebin/'+child.split('.')[0]+'.pae'
            if child: todo.append(child)
    result=ItemDependencyGraph(frozenset(visited),tuple(sorted(checked)),tuple(sorted(unresolved)))
    raise_if_cancelled(stop_event)
    if unresolved: snapshot.provenance.record_reference_closure(False)
    snapshot._authoring_indexes[cache_key]=result
    return result

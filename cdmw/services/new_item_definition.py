"""Source-qualified ItemInfo definition references and secondary localization."""
from dataclasses import dataclass
import xml.etree.ElementTree as ET

from cdmw.core.item_layout import read_item_layout, replace_layout_fields
from cdmw.core.iteminfo_definition import read_definition_fields, set_definition_fields, decode_local_string, encode_local_string
from cdmw.core.new_item_record import Cursor, RecordError
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.item_definition import NUMBERS, SEAL_TARGETS, encode_definition_settings
from cdmw.services.new_item_settings import _rows, _reference


@dataclass(frozen=True)
class SecondaryDescriptionPlan:
    source_key: str
    key: str
    texts: dict


@dataclass(frozen=True)
class DefinitionIndex:
    choices: dict
    compatibility_hashes: frozenset
    slot_indexes: dict
    descriptions: tuple
    map_icons: tuple
    unavailable: tuple
    localizations: dict


REFERENCE_TABLES = {'knowledgeinfo': 4, 'effectinfo': 4, 'gimmickinfo': 4, 'localstringinfo': 4,
                    'characterinfo': 4, 'tribeinfo': 4, 'patterndescriptioninfo': 4, 'crafttoolinfo': 2}


def _qualified_reference(snapshot, table, key, *, stop_event=None):
    raise_if_cancelled(stop_event)
    if not key:
        return
    if table == 'iteminfo':
        item = snapshot.rows.get(key)
        if item is None or item.is_blocked:
            raise RecordError(f'Missing or blocked item definition dependency {key}.')
        _reference(snapshot, table, key, stop_event=stop_event)
        return
    raw = _rows(snapshot, table, stop_event=stop_event, key_width=REFERENCE_TABLES[table]).get(key)
    if raw is None:
        raise RecordError(f'Missing {table} dependency {key}.')
    cursor = Cursor(raw)
    cursor.take(REFERENCE_TABLES[table])
    cursor.text()
    if cursor.unpack('B') != 0:
        raise RecordError(f'Blocked {table} dependency {key}.')


def load_definition_index(snapshot, *, stop_event=None):
    raise_if_cancelled(stop_event)
    cached = snapshot._authoring_indexes.get('item-definition')
    if cached is not None:
        return cached
    english = snapshot.english.index()
    items = []
    for key, row in snapshot.rows.items():
        raise_if_cancelled(stop_event)
        if not row.is_blocked:
            items.append((key, english[row.name_key].text if row.name_key in english else row.string_key))
    choices = {'iteminfo': tuple(sorted(items)), 'statusinfo': tuple(sorted(snapshot.status_names.items()))}
    available = snapshot.sources.tables if snapshot.sources else {}
    unavailable = []
    for table, width in REFERENCE_TABLES.items():
        raise_if_cancelled(stop_event)
        if table not in available:
            choices[table] = ()
            unavailable.append(table)
            continue
        named = []
        for key, raw in _rows(snapshot, table, key_width=width, stop_event=stop_event).items():
            raise_if_cancelled(stop_event)
            try:
                cursor = Cursor(raw)
                cursor.take(width)
                name = cursor.text()
                if cursor.unpack('B') == 0:
                    named.append((key, name))
            except (ValueError, UnicodeError):
                continue
        choices[table] = tuple(sorted(named))
    compatibility, slots, descriptions, map_icons, localizations = set(), {}, [], set(), {}
    for key, row in snapshot.rows.items():
        raise_if_cancelled(stop_event)
        if row.is_blocked:
            continue
        try:
            layout = read_item_layout(row.raw)
            values = read_definition_fields(row.raw)
            compatibility.add(values['compatibility_hash'])
            for slot in values['occupied_slots']:
                slots.setdefault(slot['name_hash'], set()).update(slot['indexes'])
            if values['map_icon']:
                map_icons.add(values['map_icon'])
            description = decode_local_string(layout.data('_itemDesc2'))
            if (description['key'] >> 32 == key and description['text_key'] == str(description['key'])
                    and description['key'] & 0xffffffff not in (0, 0x70, 0x71) and description['text_key'] in english):
                descriptions.append((key, row.string_key))
            references = [decode_local_string(layout.data(field)) for field in ('_itemName', '_itemDesc', '_itemDesc2')]
            references.extend(parameter for pattern in values['pattern_descriptions'] for parameter in pattern['parameters'])
            for value in references:
                text_key = value['text_key']
                if text_key in english:
                    localizations.setdefault(text_key, {name: value[name] for name in ('category', 'key', 'text_key')})
        except (ValueError, UnicodeError):
            continue
    result = DefinitionIndex(choices, frozenset(compatibility), {key: frozenset(value) for key, value in slots.items()},
                             tuple(descriptions), tuple(sorted(map_icons)), tuple(unavailable), localizations)
    raise_if_cancelled(stop_event)
    snapshot._authoring_indexes['item-definition'] = result
    return result


def _localization_reference(snapshot, value, *, stop_event=None):
    key = value['text_key']
    if not key and value['key'] == 0:
        return
    if value['key'] and key != str(value['key']):
        raise RecordError('A numeric localization reference disagrees with its text key.')
    for language in snapshot.languages:
        raise_if_cancelled(stop_event)
        cache_key = ('definition-localization-counts', language)
        counts = snapshot._authoring_indexes.get(cache_key)
        if counts is None:
            counts = {}
            for entry in snapshot.paloc_table(language).entries:
                raise_if_cancelled(stop_event)
                counts[entry.key] = counts.get(entry.key, 0) + 1
            raise_if_cancelled(stop_event)
            snapshot._authoring_indexes[cache_key] = counts
        if counts.get(key) != 1:
            raise RecordError(f'Missing or ambiguous {language} localization dependency {key}.')


def resolve_map_icon(snapshot, key, *, stop_event=None):
    if not key:
        return None
    cache = snapshot._authoring_indexes.get(('definition-map-icon', key))
    if cache is not None:
        raise_if_cancelled(stop_event)
        return cache
    name = snapshot.stringinfo_texts.get(key)
    if not name or stringinfo_key(name) != key:
        raise RecordError('Map icon has no qualified StringInfo binding.')
    bindings, total, files = [], 0, 0
    for path in snapshot.entries:
        raise_if_cancelled(stop_event)
        if not path.startswith('ui/xml/texture/') or not path.endswith('.xml'):
            continue
        files += 1
        if files > 2048:
            raise RecordError('UI texture registry scan exceeds its bound.')
        raw = snapshot.payload(path)
        total += len(raw)
        if total > 64 * 1024 * 1024:
            raise RecordError('UI texture registry data exceeds its bound.')
        # Both ordinary XML documents and the game's flat Texture entries occur.
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise RecordError('Unsupported UI texture registry declaration.')
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            try:
                root = ET.fromstring(b'<Textures>' + raw + b'</Textures>')
            except ET.ParseError as exc:
                raise RecordError('Unsupported UI texture registry XML.') from exc
        for texture in root.iter('Texture'):
            raise_if_cancelled(stop_event)
            if texture.get('Name', '').casefold() != name.casefold():
                continue
            if (texture.get('Filename') is not None and texture.get('FileName') is not None
                    and texture.get('Filename').casefold() != texture.get('FileName').casefold()):
                raise RecordError('Map icon registry has conflicting filename attributes.')
            filename = texture.get('Filename', texture.get('FileName', '')).replace('\\', '/').lstrip('/').lower()
            from cdmw.services.independent_item_package import virtual_path
            filename = virtual_path(filename)
            if not filename.endswith('.dds') or not snapshot.has_entry(filename):
                raise RecordError('Map icon texture is missing or unsupported.')
            signature = tuple(sorted((attribute.lower(), value.lower() if attribute.lower() in ('name', 'filename') else value)
                                     for attribute, value in texture.attrib.items()))
            bindings.append((path, filename, signature))
    if not bindings or len({binding[1:] for binding in bindings}) != 1:
        raise RecordError('Map icon texture binding is missing or ambiguous.')
    filename = bindings[0][1]
    from cdmw.core.pathc_format import validate_dds_payload
    validate_dds_payload(snapshot.payload(filename))
    result = (name, filename, tuple(sorted({binding[0] for binding in bindings})))
    raise_if_cancelled(stop_event)
    snapshot._authoring_indexes[('definition-map-icon', key)] = result
    return result


def validate_definition_dependencies(raw, snapshot, *, stop_event=None):
    values = read_definition_fields(raw)
    for name, (_field, _width, _section, table) in NUMBERS.items():
        if table:
            _qualified_reference(snapshot, table, values[name], stop_event=stop_event)
    resolve_map_icon(snapshot, values['map_icon'], stop_event=stop_event)
    for bundle in values['bundles']:
        _qualified_reference(snapshot, 'gimmickinfo', bundle['gimmick'], stop_event=stop_event)
    sharpness = values['sharpness']
    _qualified_reference(snapshot, 'crafttoolinfo', sharpness['craft_tool'], stop_event=stop_event)
    for family in ('maximum', 'regeneration', 'static', 'parameters'):
        for stat in sharpness[family]:
            raise_if_cancelled(stop_event)
            _reference(snapshot, 'statusinfo', stat['stat'], stop_event=stop_event)
    index = load_definition_index(snapshot, stop_event=stop_event)
    if values['compatibility_hash'] and values['compatibility_hash'] not in index.compatibility_hashes:
        raise RecordError('Equipment compatibility hash has no source definition.')
    for slot in values['occupied_slots']:
        if slot['name_hash'] not in index.slot_indexes or set(slot['indexes']) - index.slot_indexes[slot['name_hash']]:
            raise RecordError('Equipment slot or index has no source definition.')
    for pattern in values['pattern_descriptions']:
        _qualified_reference(snapshot, 'patterndescriptioninfo', pattern['pattern'], stop_event=stop_event)
        for parameter in pattern['parameters']:
            _localization_reference(snapshot, parameter, stop_event=stop_event)
    for name in ('sealable_items', 'sealable_characters', 'sealable_gimmicks', 'sealable_tags', 'sealable_tribes'):
        for target in values[name]:
            _qualified_reference(snapshot, 'iteminfo', target['item'], stop_event=stop_event)
            table = SEAL_TARGETS[target['target_type']]
            if table not in (None, 'tag'):
                _qualified_reference(snapshot, table, target['target'], stop_event=stop_event)
    for name in ('costs', 'prices'):
        for entry in values['faction'][name]:
            _qualified_reference(snapshot, 'iteminfo', entry['item'], stop_event=stop_event)


def apply_definition(raw, settings, snapshot, item_key, template_key, *, stop_event=None):
    encode_definition_settings(settings)
    if settings.fields:
        raw = set_definition_fields(raw, dict(settings.fields))
    plan = None
    text = settings.secondary_description
    if text is None:
        inherited = decode_local_string(read_item_layout(raw).data('_itemDesc2'))
        _localization_reference(snapshot, inherited, stop_event=stop_event)
    if text is not None:
        layout = read_item_layout(raw)
        if not text['texts']:
            raw = replace_layout_fields(layout, {'_itemDesc2': bytes(13)}).raw
        else:
            source_key = text['source_item'] or template_key
            _qualified_reference(snapshot, 'iteminfo', source_key, stop_event=stop_event)
            source = decode_local_string(read_item_layout(snapshot.rows[source_key].raw).data('_itemDesc2'))
            if (source['key'] >> 32 != source_key or source['text_key'] != str(source['key'])
                    or source['key'] & 0xffffffff in (0, 0x70, 0x71)):
                raise RecordError('Choose a source item with an independent numeric secondary description.')
            if set(text['texts']) - set(snapshot.languages):
                raise RecordError('A secondary description language is unavailable in this source.')
            _localization_reference(snapshot, source, stop_event=stop_event)
            new_key = (item_key << 32) | (source['key'] & 0xffffffff)
            value = dict(source, key=new_key, text_key=str(new_key))
            raw = replace_layout_fields(layout, {'_itemDesc2': encode_local_string(value)}).raw
            plan = SecondaryDescriptionPlan(source['text_key'], str(new_key), dict(text['texts']))
    validate_definition_dependencies(raw, snapshot, stop_event=stop_event)
    return raw, plan

"""Compose declared ItemInfo field operations after validating every active layer."""
import struct
from cdmw.domain.archives.overlay_merge import _table, OverlayConflict
from cdmw.domain.new_item.iteminfo_operations import compile_assignments, compose_assignments


def item_pair(values):
    bodies = [path for path in values if path.rsplit('/', 1)[-1] in ('iteminfo.pabgb', 'iteminfo.staticinfobody')]
    if len(bodies) != 1:
        raise OverlayConflict('Typed ItemInfo edits require exactly one recognized table pair.')
    body = bodies[0]
    head = body.rsplit('.', 1)[0] + ('.pabgh' if body.endswith('.pabgb') else '.staticinfoheader')
    if head not in values:
        raise OverlayConflict('Typed ItemInfo edits require the matching table header.')
    return body, head


def rows_of(body, header):
    table, records = _table(body, header)
    if (table.key_width, table.header_size) != (4, 2):
        raise OverlayConflict('Typed ItemInfo edits require the verified u32-key, u16-count table directory.')
    return {int.from_bytes(key, 'little'): raw for key, raw in records}


def replace_rows(body, header, replacements):
    records = _table(body, header)[1]
    if set(replacements) - {int.from_bytes(key, 'little') for key, _ in records}:
        raise OverlayConflict('Typed ItemInfo edits cannot add or delete a record.')
    result = []
    for key, raw in records:
        replacement = replacements.get(int.from_bytes(key, 'little'), raw)
        if len(replacement) != len(raw):
            raise OverlayConflict('Typed ItemInfo edits cannot change a record layout.')
        result.append(replacement)
    return b''.join(result)


def replace_rows_with_header(body,header,replacements):
    """Replace complete records and rebuild offsets, retaining every key/order."""
    table,records=_table(body,header)
    if (table.key_width,table.header_size)!=(4,2):
        raise OverlayConflict('Declared ItemInfo edits require the verified table directory.')
    keys={int.from_bytes(key,'little') for key,_raw in records}
    if set(replacements)-keys: raise OverlayConflict('Declared ItemInfo edits cannot add or delete records.')
    payload=bytearray(); offsets={}
    for key,raw in records:
        replacement=replacements.get(int.from_bytes(key,'little'),raw)
        if not isinstance(replacement,bytes) or not replacement.startswith(key):
            raise OverlayConflict('Declared ItemInfo edits cannot change record identities.')
        offsets[key]=len(payload); payload.extend(replacement)
    directory=header[:2]+b''.join(row.key+struct.pack('<I',offsets[row.key]) for row in table.rows)
    result=bytes(payload)
    actual_table,actual_records=_table(result,directory)
    if [row.key for row in actual_table.rows]!=[row.key for row in table.rows]:
        raise OverlayConflict('Declared ItemInfo edits changed the directory identities.')
    if any(after!=(replacements.get(int.from_bytes(key,'little'),before))
           for (key,before),(_key,after) in zip(records,actual_records)):
        raise OverlayConflict('Declared ItemInfo edits changed an unassigned record.')
    return result,directory


def operation_contributions(layer):
    value = layer.get('independent_operations', [])
    if not isinstance(value, list) or len(value) > 128:
        raise OverlayConflict('Invalid typed ItemInfo contribution inventory.')
    result = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {'owner', 'operations'}:
            raise OverlayConflict('Invalid typed ItemInfo contribution.')
        result.append((row['owner'], row['operations']))
    return result


def prepare_fields(layers, baseline, *, stop_event=None):
    selected = [(layer, changes) for layer, changes in layers if layer['active'] and layer.get('independent_operations')]
    if not selected:
        return {}, None
    body, header = item_pair(baseline)
    source = rows_of(baseline[body], baseline[header])
    compiled = compile_assignments([row for layer, _ in selected for row in operation_contributions(layer)], source, stop_event=stop_event)
    normalized = {}
    for layer, changes in selected:
        before = rows_of(changes[body]['before'], changes[header]['before'])
        own = compile_assignments(operation_contributions(layer), before, stop_event=stop_event)
        expected = compose_assignments(before, own, stop_event=stop_event)
        touched = {item.operation.record for item in own}
        after = rows_of(changes[body]['after'], changes[header]['after'])
        if any(after.get(key) != expected[key] for key in touched):
            raise OverlayConflict(f'{layer["label"]}: the field-operation journal differs from its declared intent.')
        values = dict(changes)
        payload,directory=replace_rows_with_header(changes[body]['after'],changes[header]['after'],{key:before[key] for key in touched})
        values[body]=dict(changes[body],after=payload)
        values[header]=dict(changes[header],after=directory)
        normalized[layer['id']] = values
    return normalized, (body, header, source, compiled)


def finish_fields(current, prepared, *, stop_event=None):
    if prepared is None:
        return current
    body, header, source, compiled = prepared
    present = rows_of(current[body], current[header])
    touched = {item.operation.record for item in compiled}
    for key in touched:
        if present.get(key) != source[key]:
            raise OverlayConflict(f'ItemInfo record {key}: an untyped overlay changes a row required by typed field operations.')
    changed = compose_assignments(source, compiled, stop_event=stop_event)
    result = dict(current)
    result[body],result[header]=replace_rows_with_header(current[body],current[header],{key:changed[key] for key in touched})
    return result


def required_field_files(layers, current):
    if not any(layer['active'] and layer.get('independent_operations') for layer, _ in layers):
        return set()
    # Readers resolve a body and header from the same provider. Even an unchanged
    # directory belongs beside its edited body; this also represents no-op owners.
    return set(item_pair(current))

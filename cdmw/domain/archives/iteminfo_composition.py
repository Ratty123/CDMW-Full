"""Compose declared ItemInfo field operations after validating every active layer."""
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
        values[body] = dict(changes[body], after=replace_rows(changes[body]['after'], changes[header]['after'],
                                                           {key: before[key] for key in touched}))
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
    result[body] = replace_rows(current[body], current[header], {key: changed[key] for key in touched})
    return result


def required_field_files(layers, current):
    if not any(layer['active'] and layer.get('independent_operations') for layer, _ in layers):
        return set()
    # Readers resolve a body and header from the same provider. Even an unchanged
    # directory belongs beside its edited body; this also represents no-op owners.
    return set(item_pair(current))

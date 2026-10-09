"""Lower field intent through the existing journal and whole-file compositor."""
from cdmw.domain.archives.iteminfo_composition import rows_of, replace_rows
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.iteminfo_operations import compile_assignments, compose_assignments
from cdmw.services.independent_mod_package import package_operations
from cdmw.services.independent_item_package import digest


def lower_field_operations(package, snapshot, changes, *, stop_event=None):
    contributions = package_operations(package)
    if not contributions:
        return changes
    pair = snapshot.iteminfo
    body, header = pair.payload_entry.path.lower(), pair.header_entry.path.lower()
    original = {path: snapshot.payload(path) for path in (body, header)}
    if any(package.dependencies.get(path) != digest(data) for path, data in original.items()):
        raise IndependentItemError('Typed ItemInfo edits require exact table-body and header dependencies.')
    rows = rows_of(original[body], original[header])
    compiled = compile_assignments([(row['owner'], row['operations']) for row in contributions], rows, stop_event=stop_event)
    changed = compose_assignments(rows, compiled, stop_event=stop_event)
    touched = {item.operation.record for item in compiled}
    result = dict(changes)
    for path, entry in ((body, pair.payload_entry), (header, pair.header_entry)):
        result.setdefault(path, {'before': original[path], 'after': original[path], 'flags': entry.flags, 'meta': False})
    result[body] = dict(result[body], after=replace_rows(result[body]['after'], result[header]['after'], {key: changed[key] for key in touched}))
    return result


def from_iteminfo_operations(snapshot, identity, title, operations, *, release='1', stop_event=None):
    """Author a data-only field package against a verified shipped snapshot."""
    from pathlib import Path
    from cdmw.services.independent_item_package import FORMAT
    from cdmw.services.independent_mod_package import read_v2
    pair = snapshot.iteminfo
    dependencies = {}
    for entry in (pair.payload_entry, pair.header_entry):
        directory = Path(entry.pamt_path).parent.name
        if len(directory) != 4 or not directory.isascii() or not directory.isdigit() or int(directory) >= 36:
            raise IndependentItemError('Field packages must be authored against shipped game tables.')
        dependencies[entry.path.lower()] = digest(snapshot.payload(entry.path))
    package = read_v2({'format': FORMAT, 'version': 2, 'identity': identity, 'title': title, 'release': release,
        'requires': {'item.fields': 1}, 'modules': [{'id': 'edits', 'type': 'item.fields', 'version': 1,
            'required': True, 'data': {'operations': list(operations)}}],
        'dependencies': dependencies, 'blobs': {}, 'provenance': None, 'metadata': {}}, {})
    lower_field_operations(package, snapshot, {}, stop_event=stop_event)
    snapshot.provenance.capture().validate(stop_event)
    return package

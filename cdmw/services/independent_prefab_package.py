"""Witnessed existing-prefab replacement; the module adds no files, item IDs or registry edits.

A prefab names the meshes, skeletons and sockets an object is assembled from, so
an edited copy changes what the game builds without adding anything to it. The
module pins the shipped prefab (base game or DLC) it replaces by hash and refuses
when the game's copy differs, when the replacement no longer decodes as far as
its source, or when it points at a file that neither this game nor the same
package's own item provides. In a package with an owned item, the edit can
therefore point an existing prefab at that item's new mesh.

Ownership rows share the existing-texture channel: one final-bytes requirement
per path and owner, so two packages that want different bytes for one prefab
refuse instead of silently choosing a winner.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.independent import (
    IndependentItemError,
    IndependentItemPackage,
)

MAX_PREFAB_REPLACEMENTS = 128
MAX_PREFAB_BYTES = 16 * 1024 * 1024
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_ROW_FIELDS = {'path', 'source_sha256', 'source_size', 'replacement'}


def validated_prefab(data, *, source=None, stop_event=None):
    """Decode the replacement; with a source, require the walk to reach as far."""
    from cdmw.core.prefab_binary import decode_prefab_binary
    if not isinstance(data, bytes) or not data or len(data) > MAX_PREFAB_BYTES:
        raise IndependentItemError('A prefab replacement exceeds the package size limit.')
    raise_if_cancelled(stop_event)
    try:
        document = decode_prefab_binary(data)
    except (ValueError, IndexError, KeyError, struct.error) as exc:
        raise IndependentItemError(f'The prefab replacement could not be decoded: {exc}') from exc
    if source is not None and source.walk_complete and not document.walk_complete:
        raise IndependentItemError(f'The prefab replacement no longer decodes completely: {document.walk_note}')
    return document


def prefab_modules(package):
    if isinstance(package, IndependentItemPackage):
        return ()
    return tuple(module for module in package.manifest['modules'] if module['type'] == 'prefab.replace')


def prefab_resource_keys(package):
    return {row['replacement'] for module in prefab_modules(package)
            for row in module['data']['replacements']}


def read_prefab_modules(meta, blobs, *, stop_event=None):
    """Validate closed module fields and the resources they actually own."""
    from cdmw.services.independent_item_package import MAX_TOTAL, virtual_path
    modules = [module for module in meta['modules'] if module['type'] == 'prefab.replace']
    if not modules:
        return set()
    # Textures and prefabs share one ownership inventory with a single limit.
    count = sum(len(module['data']['replacements']) for module in meta['modules']
                if module['type'] == 'texture.replace' and isinstance(module['data'], dict)
                and isinstance(module['data'].get('replacements'), list))
    paths, used, checked = set(), set(), set()
    logical_size = 0
    for module in modules:
        data = module['data']
        if (not isinstance(data, dict) or set(data) != {'replacements'}
                or not isinstance(data['replacements'], list) or not data['replacements']):
            raise IndependentItemError('Invalid existing-prefab replacement module.')
        for row in data['replacements']:
            raise_if_cancelled(stop_event)
            if not isinstance(row, dict) or set(row) != _ROW_FIELDS:
                raise IndependentItemError('Invalid existing-prefab replacement fields.')
            path = virtual_path(row['path'])
            if not path.endswith('.prefab') or path in paths:
                raise IndependentItemError(f'A duplicate or non-prefab replacement target is unsupported: {path}.')
            paths.add(path)
            if len(paths) + count > MAX_PREFAB_REPLACEMENTS:
                raise IndependentItemError('The replacement count limit is exhausted.')
            if any(not isinstance(row[key], str) or not _HASH.fullmatch(row[key])
                   for key in ('source_sha256', 'replacement')):
                raise IndependentItemError('Invalid prefab source or replacement digest.')
            if type(row['source_size']) is not int or not 1 <= row['source_size'] <= MAX_PREFAB_BYTES:
                raise IndependentItemError('Invalid witnessed prefab source size.')
            if meta['dependencies'].get(path) != row['source_sha256']:
                raise IndependentItemError('A prefab replacement requires its exact source dependency.')
            key = row['replacement']
            if key == row['source_sha256']:
                raise IndependentItemError(f'The prefab replacement is identical to the game copy: {path}.')
            if key not in blobs:
                raise IndependentItemError('A required prefab replacement resource is missing.')
            used.add(key)
            logical_size += len(blobs[key])
            if logical_size > MAX_TOTAL:
                raise IndependentItemError('The logical prefab replacement size limit is exhausted.')
            if key not in checked:
                validated_prefab(blobs[key], stop_event=stop_event)
                checked.add(key)
    return used


def package_prefab_requirements(package):
    return [{'owner': f'{package.identity}/{module["id"]}', 'path': row['path'], 'sha256': row['replacement']}
            for module in prefab_modules(package) for row in module['data']['replacements']]


def _source_prefab(snapshot, path, stop_event):
    from cdmw.services.independent_item_package import _is_dlc_folder, digest, shipped_group
    if not snapshot.has_entry(path):
        raise IndependentItemError(f'The prefab target is not an existing shipped resource: {path}.')
    entry = snapshot.entry(path)
    root = Path(snapshot.iteminfo.payload_entry.pamt_path).resolve().parent.parent
    archive = Path(entry.pamt_path).resolve()
    # Shipped groups only, base or DLC (`dlc/dlc_01/0036`): a numbered base group
    # past the game's own is another mod's.
    folder = archive.parent.parent
    if not shipped_group(archive) or not (folder == root or (_is_dlc_folder(folder) and folder.parent.parent == root)):
        raise IndependentItemError(f'Prefab replacement requires a witnessed shipped target: {path}.')
    original = snapshot.payload(path)
    return entry, original, validated_prefab(original, stop_event=stop_event), digest(original)


def _new_references(source, replacement):
    before = {item.text.lower() for item in source.resource_strings()}
    return sorted({item.text.lower() for item in replacement.resource_strings()} - before)


def lower_prefab_operations(package, snapshot, changes, *, stop_event=None):
    modules = prefab_modules(package)
    if not modules:
        return changes
    result = dict(changes)
    for module in modules:
        for row in module['data']['replacements']:
            raise_if_cancelled(stop_event)
            path = row['path']
            entry, original, source, checksum = _source_prefab(snapshot, path, stop_event)
            if checksum != row['source_sha256'] or len(original) != row['source_size']:
                raise IndependentItemError(f'The game copy of this prefab has changed since the package was made: {path}. '
                                           'Edit it again in the Prefab Inspector on this game.')
            replacement = package.blobs[row['replacement']]
            document = validated_prefab(replacement, source=source, stop_event=stop_event)
            # `result` already holds the owned item's additions when the package has one.
            missing = [ref for ref in _new_references(source, document) if not snapshot.has_entry(ref)
                       and not (ref in result and result[ref]['before'] is None and result[ref]['after'] is not None)]
            if missing:
                shown = ', '.join(missing[:4]) + (f' and {len(missing) - 4} more' if len(missing) > 4 else '')
                raise IndependentItemError(f'The edited prefab {path} points at files that neither this game nor the package contains: {shown}.')
            change = {'before': original, 'after': replacement, 'flags': entry.flags, 'meta': False}
            if path in result and result[path] != change:
                raise IndependentItemError(f'The package contains contradictory writes to its prefab target: {path}.')
            result[path] = change
    return result


def with_prefab_replacements(package, snapshot, replacements, *, release, stop_event=None):
    """The same package (identity and modules kept) with these prefabs replaced too.

    A v1 item package is migrated to v2 first. Rows for a prefab the package
    already replaces are updated in place. The caller validates the result
    against the game, because whether a new mesh path exists can depend on the
    package's own item.
    """
    from copy import deepcopy
    from itertools import chain, count

    from cdmw.services.independent_item_package import digest, virtual_path
    from cdmw.services.independent_mod_package import migrate_v1, read_v2
    if not isinstance(replacements, dict) or not replacements:
        raise IndependentItemError('Select at least one prefab replacement.')
    if isinstance(package, IndependentItemPackage):
        package = migrate_v1(package, release=release)
    manifest = deepcopy(package.manifest)
    blobs = dict(package.blobs)
    modules = manifest['modules']
    module = next((item for item in modules if item['type'] == 'prefab.replace'), None)
    if module is None:
        taken = {item['id'] for item in modules}
        symbol = next(name for name in chain(('prefabs',), (f'prefabs-{n}' for n in count(2))) if name not in taken)
        module = {'id': symbol, 'type': 'prefab.replace', 'version': 1, 'required': True, 'data': {'replacements': []}}
        modules.append(module)
    manifest['requires']['prefab.replace'] = 1
    # A v1-lowering record claims the package is exactly its v1 source, which the
    # added dependency makes untrue; the identity and the item module are kept.
    manifest['provenance'] = None
    rows = {row['path']: row for row in module['data']['replacements']}
    previous = {row['replacement'] for row in rows.values()}
    for path, replacement in replacements.items():
        raise_if_cancelled(stop_event)
        path = virtual_path(path)
        if not path.endswith('.prefab'):
            raise IndependentItemError('Prefab replacement targets must be existing .prefab paths.')
        if not isinstance(replacement, (bytes, bytearray)) or len(replacement) > MAX_PREFAB_BYTES:
            raise IndependentItemError('A prefab replacement must be bounded prefab bytes.')
        _entry, original, _source, checksum = _source_prefab(snapshot, path, stop_event)
        if manifest['dependencies'].get(path, checksum) != checksum:
            raise IndependentItemError(f'The package was made against a different copy of {path} than this game has. '
                                       'Update the package on this game first.')
        replacement = bytes(replacement)
        key = digest(replacement)
        blobs[key] = replacement
        manifest['dependencies'][path] = checksum
        rows[path] = {'path': path, 'source_sha256': checksum, 'source_size': len(original), 'replacement': key}
    module['data']['replacements'] = list(rows.values())
    # Drop replacement bytes nothing refers to any more; a texture row may share them.
    kept = {row['replacement'] for row in rows.values()} | {
        row['replacement'] for item in modules if item['type'] == 'texture.replace'
        for row in item['data']['replacements']}
    for key in previous - kept:
        blobs.pop(key, None)
    manifest['blobs'] = {key: len(data) for key, data in sorted(blobs.items())}
    manifest['release'] = release
    return read_v2(manifest, blobs, stop_event=stop_event)


def next_release(release):
    """Bump a trailing number (`3` -> `4`, `1.2` -> `1.3`), else append `.1`."""
    match = re.fullmatch(r'(.*?)(\d+)', release)
    return (f'{match[1]}{int(match[2]) + 1}' if match else f'{release}.1')[:64]


def from_prefab_replacements(snapshot, identity, replacements, *, title='Prefab replacements',
                             release='1', stop_event=None):
    """Author against the witnessed baseline; the caller retains its source guard."""
    from cdmw.services.independent_item_package import FORMAT, digest, virtual_path
    from cdmw.services.independent_mod_package import read_v2
    if not isinstance(replacements, dict) or not 1 <= len(replacements) <= MAX_PREFAB_REPLACEMENTS:
        raise IndependentItemError('Select between one and 128 existing prefab replacements.')
    rows, blobs, dependencies = [], {}, {}
    for path, replacement in replacements.items():
        raise_if_cancelled(stop_event)
        path = virtual_path(path)
        if not path.endswith('.prefab'):
            raise IndependentItemError('Prefab replacement targets must be existing .prefab paths.')
        if not isinstance(replacement, (bytes, bytearray)) or len(replacement) > MAX_PREFAB_BYTES:
            raise IndependentItemError('A prefab replacement must be bounded prefab bytes.')
        _entry, original, _source, checksum = _source_prefab(snapshot, path, stop_event)
        replacement = bytes(replacement)
        key = digest(replacement)
        blobs[key] = replacement
        dependencies[path] = checksum
        rows.append({'path': path, 'source_sha256': checksum, 'source_size': len(original), 'replacement': key})
    package = read_v2({'format': FORMAT, 'version': 2, 'identity': identity, 'title': title,
        'release': release, 'requires': {'prefab.replace': 1},
        'modules': [{'id': 'prefabs', 'type': 'prefab.replace', 'version': 1, 'required': True,
                     'data': {'replacements': rows}}],
        'dependencies': dependencies, 'blobs': {key: len(data) for key, data in sorted(blobs.items())},
        'provenance': None, 'metadata': {}}, blobs, stop_event=stop_event)
    lower_prefab_operations(package, snapshot, {}, stop_event=stop_event)
    snapshot.provenance.capture().validate(stop_event)
    return package

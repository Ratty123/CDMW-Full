"""Read the overlay index and journals an older CDMW's overlay installs left.

Live item work (Send to DMM, combining item packages, mod updates) reads an old
install's state through these so it composes on top of it.

CDMW no longer installs into the game (decision 39). The install code moved to
tests/support; Browse Archives' Remove What an Older CDMW Installed... takes an
old install out. Nothing here writes.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import time
import uuid
import zipfile

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, parse_papgt, read_papgt_directories
from cdmw.domain.archives.overlay_merge import (
    OverlayConflict, legacy_texture_baseline, merge_overlay_files, owned_item_references,
)
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.archive_overlay_install import (
    is_cdmw_overlay_directory,
    overlay_baseline_files,
    overlay_directory_name,
)

INDEX_PATH = '.cdmw/overlays.json'
_FORMAT = 'cdmw_owned_overlays_v1'
_FORMAT_WITH_CONTEXTS = 'cdmw_owned_overlays_v2'
_JOURNAL_FORMAT = 'cdmw_overlay_changes_v1'
_MAX_STATE_BYTES = 4 * 1024 * 1024
_MAX_JOURNAL_BYTES = 2 * 1024 * 1024 * 1024


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _json(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def _relative(raw):
    path = str(raw).replace('\\', '/')
    parts = PurePosixPath(path)
    if not path or parts.is_absolute() or any(p in ('', '.', '..') for p in path.split('/')) or ':' in path or '\0' in path:
        raise ValueError(f'Invalid overlay path: {path!r}')
    return parts.as_posix().lower()


def _target(root, relative):
    path = (root / _relative(relative)).resolve()
    if root not in path.parents:
        raise ValueError('Overlay path escapes the game folder.')
    return path


def _directory(name):
    value = str(name)
    if len(value) != 4 or not value.isascii() or not value.isdigit() or not 36 <= int(value) <= 9999:
        raise ValueError('Overlay folder must be a number from 0036 to 9999.')
    return value


def _read(entry):
    value = read_archive_entry_data(entry)
    return bytes(value[0] if isinstance(value, tuple) else value)


def _stamp(path):
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def _load_index(root):
    path = _target(root, INDEX_PATH)
    if not path.exists():
        return None
    if path.stat().st_size > _MAX_STATE_BYTES:
        raise ValueError('The overlay inventory is too large to read safely.')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate overlay inventory key.')
            value[key] = item
        return value
    state = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)
    if (not isinstance(state, dict) or state.get('format') not in (_FORMAT, _FORMAT_WITH_CONTEXTS)
            or not isinstance(state.get('layers'), list)):
        raise ValueError('Unsupported overlay inventory. Restore its backup before changing overlays.')
    from cdmw.domain.new_item.compilation_storage import read_compilation, validate_contexts
    contexts = None
    if state['format'] == _FORMAT_WITH_CONTEXTS:
        contexts = validate_contexts(state.get('compilation_contexts'))
    elif 'compilation_contexts' in state:
        raise ValueError('Shared compilation contexts require the supported overlay inventory version.')
    _directory(state.get('directory'))
    ids = set()
    for layer in state['layers']:
        identity = str(layer.get('id', ''))
        if identity in ids or len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity):
            raise ValueError('Invalid overlay identity in the inventory.')
        ids.add(identity)
        if not isinstance(layer.get('active'), bool) or not isinstance(layer.get('label'), str):
            raise ValueError('Invalid overlay entry in the inventory.')
        if 'disabled' in layer and (not isinstance(layer['disabled'], bool) or (layer['disabled'] and layer['active'])):
            raise ValueError('Invalid disabled overlay state.')
        overlay_journal_path(layer)
        if not isinstance(layer.get('item_keys'), list) or any(not isinstance(k, int) or k <= 0 for k in layer['item_keys']):
            raise ValueError('Invalid owned item identity in the inventory.')
        if not isinstance(layer.get('dependencies'), list) or any(not isinstance(d, str) for d in layer['dependencies']):
            raise ValueError('Invalid overlay dependency list.')
        if 'independent_compilation' in layer:
            read_compilation(layer['independent_compilation'], contexts)
    if any(set(layer['dependencies']) - ids for layer in state['layers']):
        raise ValueError('An overlay dependency is missing from the inventory.')
    return state


def _mounted_owned(root):
    mount = _target(root, 'meta/0.papgt')
    records = read_papgt_directories(mount.read_bytes())
    owned = []
    for record in records:
        name = str(record.name)
        if name.isascii() and name.isdigit() and len(name) == 4 and int(name) >= 36 and is_cdmw_overlay_directory(_target(root, name)):
            owned.append(record)
    return records, owned


def _validate_published(root, state, stop_event=None):
    for relative, expected in state.get('published', {}).items():
        raise_if_cancelled(stop_event, 'Overlay verification cancelled.')
        path = _target(root, relative)
        changed = path.exists() if expected is None else not path.is_file() or _digest(path.read_bytes()) != expected
        if changed:
            raise OverlayConflict(
                f'{relative} changed after an older CDMW installed overlays into this game. '
                'Use Browse Archives > Remove What an Older CDMW Installed... to take that install out, then try again.'
            )
    for relative, expected in state.get('sources', {}).items():
        path = _target(root, relative)
        if not path.is_file() or _stamp(path) != expected:
            raise OverlayConflict(f'The source archive {relative} changed. Existing overlay baselines need review before removal.')
    records, owned = _mounted_owned(root)
    active = any(layer['active'] for layer in state['layers'])
    if active:
        match = next((record for record in owned if record.name == state['directory']), None)
        if match is None or match.flags != PAPGT_DEFAULT_FLAGS:
            raise OverlayConflict('The managed overlay is no longer mounted as prepared.')
        pamt = _target(root, state['directory'] + '/0.pamt')
        if int.from_bytes(pamt.read_bytes()[:4], 'little') != match.pamt_checksum:
            raise OverlayConflict('The managed overlay checksum differs from the mount list.')
        managed_paths = {str(entry.path).lower() for entry in parse_archive_pamt(pamt)}
        for record in records:
            if record.name == state['directory']:
                break
            raise_if_cancelled(stop_event)
            for other in sorted(_target(root, str(record.name)).glob('*.pamt')):
                overlap = managed_paths.intersection(str(entry.path).lower() for entry in parse_archive_pamt(other))
                if overlap:
                    path = sorted(overlap)[0]
                    raise OverlayConflict(f'Overlay conflict in {path}; overlapping file edits cannot be separated safely.')
    if any(record.name != state['directory'] for record in owned):
        raise OverlayConflict('Another CDMW archive group was installed outside this inventory. '
                              'Use Browse Archives > Remove What an Older CDMW Installed... to take the old installs out.')


def _pack_changes(changes):
    stream, records, blobs = io.BytesIO(), [], {}
    for path, change in changes.items():
        record = {'path': _relative(path), 'flags': int(change['flags']), 'meta': bool(change.get('meta'))}
        for side in ('before', 'after'):
            payload = change[side]
            checksum = _digest(payload) if payload is not None else None
            record[side] = checksum
            if payload is not None:
                blobs[checksum] = payload
        records.append(record)
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        archive.writestr('changes.json', _json({'format': _JOURNAL_FORMAT, 'files': records}))
        for checksum, payload in blobs.items():
            archive.writestr('payloads/' + checksum, payload)
    return stream.getvalue()


def _read_journal(root, layer, pending):
    relative = overlay_journal_path(layer)
    path = _target(root, relative)
    if relative in pending:
        raw = pending[relative]
    else:
        if not path.is_file() or path.stat().st_size > _MAX_JOURNAL_BYTES:
            raise ValueError(f"The journal for {layer['label']} is missing or too large.")
        raw = path.read_bytes()
    if _digest(raw) != layer['sha256']:
        raise ValueError(f"The journal for {layer['label']} changed. Restore its backup before changing overlays.")
    return raw


def overlay_journal_path(layer):
    """An optional versioned journal leaves pre-rebuild history immutable."""
    relative = _relative(layer.get('journal') or '.cdmw/overlays/' + layer['id'] + '.zip')
    if not relative.startswith('.cdmw/overlays/') or not relative.endswith('.zip'):
        raise ValueError('Invalid overlay journal location.')
    return relative


def _unpack_changes(root, layer, pending, stop_event, *, metadata_only=False):
    """Read verified journal records, optionally retaining only payload digests."""
    raw = _read_journal(root, layer, pending)
    changes = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if archive.getinfo('changes.json').file_size > _MAX_STATE_BYTES:
            raise ValueError('Overlay journal metadata is too large.')
        meta = json.loads(archive.read('changes.json'))
        if meta.get('format') != _JOURNAL_FORMAT or not isinstance(meta.get('files'), list):
            raise ValueError('Unsupported overlay journal.')
        total = 0
        for record in meta['files']:
            raise_if_cancelled(stop_event, 'Overlay journal loading cancelled.')
            path = _relative(record['path'])
            if path in changes or path.startswith('.cdmw/') or path == 'meta/0.papgt':
                raise ValueError('Invalid or repeated overlay journal path.')
            is_meta = bool(record['meta'])
            if is_meta != (path == 'meta/0.pathc'):
                raise ValueError('Unsupported overlay metadata target.')
            change = {'flags': int(record['flags']), 'meta': is_meta}
            if not 0 <= change['flags'] <= 255:
                raise ValueError('Invalid archive storage flags.')
            for side in ('before', 'after'):
                checksum = record[side]
                if checksum is None:
                    change[side] = None
                    continue
                if len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
                    raise ValueError('Invalid overlay payload checksum.')
                info = archive.getinfo('payloads/' + checksum)
                total += info.file_size
                if info.file_size > _MAX_JOURNAL_BYTES or total > 4 * _MAX_JOURNAL_BYTES:
                    raise ValueError('Overlay journal payloads exceed the supported size.')
                if metadata_only:
                    # The complete journal digest and metadata/member bounds still
                    # apply. Mutation callers retain full payload verification.
                    change[side] = checksum
                    continue
                value = archive.read(info)
                if _digest(value) != checksum:
                    raise ValueError('Overlay journal payload failed its checksum.')
                change[side] = value
            changes[path] = change
    return changes


def _add_layer(state, pending, label, changes, *, item_keys=(), dependencies=(), legacy=False, target_game=None):
    identity = uuid.uuid4().hex
    payload = _pack_changes(changes)
    pending['.cdmw/overlays/' + identity + '.zip'] = payload
    layer = {'id': identity, 'label': label, 'item_keys': list(item_keys), 'dependencies': list(dependencies),
        'active': True, 'created_at': time.time(), 'legacy': bool(legacy), 'file_count': len(changes), 'sha256': _digest(payload)}
    if target_game is not None:
        layer['target_game'] = dict(target_game)
    state['layers'].append(layer)
    return layer


def _remember_source(root, state, entry):
    for source in (Path(entry.pamt_path), Path(entry.paz_file)):
        source = source.resolve()
        if root not in source.parents:
            raise ValueError('An overlay source archive is outside the selected game folder.')
        relative = source.relative_to(root).as_posix()
        if relative.split('/')[0] != state['directory']:
            state['sources'].setdefault(relative, _stamp(source))


def _added_item_keys(changes):
    from cdmw.core.structured_binary_editor import parse_pabgh_table
    for path, change in changes.items():
        if path.rsplit('/', 1)[-1] not in ('iteminfo.staticinfobody', 'iteminfo.pabgb'):
            continue
        head = path.replace('.staticinfobody', '.staticinfoheader').replace('.pabgb', '.pabgh')
        if head not in changes:
            return ()
        def keys(side):
            body, header = change[side], changes[head][side]
            return set() if body is None or header is None else {r.row_id for r in parse_pabgh_table(header, payload=body).rows}
        return tuple(sorted(keys('after') - keys('before')))
    return ()


def _state_for_edit(root, directory_name, stop_event, *, retirement=None):
    state = _load_index(root)
    pending = {}
    if retirement is not None:
        _old_state, inventory, mount = _retirement_state(root)
        if (inventory != retirement.inventory_data or mount != retirement.mount_data
                or root != retirement.package_root):
            raise OverlayConflict('The overlay state changed after preparation. Refresh and prepare again.')
        identity = retirement.retirement_id
        if len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity):
            raise ValueError('Invalid retired overlay history identity.')
        relative = '.cdmw/retired-overlays/' + identity + '.json'
        if _target(root, relative).exists():
            raise OverlayConflict('The retired overlay history already exists. Refresh and prepare again.')
        pending[relative] = inventory
        state = None
    if state is not None and any(layer['active'] or layer.get('disabled', False) for layer in state['layers']):
        _validate_published(root, state, stop_event)
        if directory_name is not None and _directory(directory_name) != state['directory']:
            raise ValueError(f"Managed installs share archive {state['directory']}. Choose Auto or that folder so their shared tables stay composed.")
        return state, {}
    records, owned = _mounted_owned(root)
    if state is not None and (owned or is_cdmw_overlay_directory(_target(root, state['directory']))):
        relative = state['directory']
        raise OverlayConflict(f'{relative} changed after an older CDMW installed overlays into this game. '
                              'Use Browse Archives > Remove What an Older CDMW Installed... to take that install out, then try again.')
    # With no installed layers, begin a fresh baseline from today's mounted files.
    # Old journals stay on disk and the replaced inventory is included in backup.
    if len(owned) > 1:
        raise OverlayConflict('Several archive groups an older CDMW installed are in this game. '
                              'Use Browse Archives > Remove What an Older CDMW Installed... to take them out.')
    existing = owned[0].name if owned else None
    name = _directory(directory_name or existing or overlay_directory_name(root))
    if existing and name != existing:
        raise ValueError(f'Choose Auto or {existing} to retain and manage the existing overlay.')
    directory = _target(root, name)
    if retirement is not None and directory.exists():
        raise OverlayConflict('Automatic recovery keeps the old overlay folders. Choose Auto or an unused folder for the new install.')
    if directory.exists() and not is_cdmw_overlay_directory(directory):
        raise ValueError(f'Archive {name} is not owned by CDMW.')
    if any(r.name == name for r in records) and not existing:
        raise ValueError(f'Archive {name} is reserved by the mount list.')
    state = {'format': _FORMAT, 'directory': name, 'layers': [], 'sources': {}, 'published': {}}
    if existing:
        if owned[0].flags != PAPGT_DEFAULT_FLAGS or int.from_bytes((directory / '0.pamt').read_bytes()[:4], 'little') != owned[0].pamt_checksum:
            raise OverlayConflict('The existing overlay differs from its mount-list checksum. Restore its backup before changing it.')
        # An older installer recorded no individual ownership. Adopt that complete
        # archive as one visible bundle, using the mounted underlay as its baseline.
        entry_map = {str(e.path).lower(): e for e in parse_archive_pamt(directory / '0.pamt')}
        underlay = {}
        for record in records:
            if record.name == existing:
                continue
            # PAPGT can reserve absent mod directories. Read the existing package
            # tables in mount order, as the source catalogue does.
            for pamt in sorted(_target(root, str(record.name)).glob('*.pamt')):
                raise_if_cancelled(stop_event, 'Existing overlay inspection cancelled.')
                for entry in parse_archive_pamt(pamt):
                    path = str(entry.path).lower()
                    if path in entry_map:
                        underlay.setdefault(path, entry)
        changes = {}
        for path, entry in entry_map.items():
            raise_if_cancelled(stop_event, 'Existing overlay inspection cancelled.')
            source = underlay.get(path)
            if source is not None:
                _remember_source(root, state, source)
            changes[path] = {'before': _read(source) if source is not None else None, 'after': _read(entry), 'flags': int(entry.flags), 'meta': False}
        for relative, baseline in overlay_baseline_files(root).items():
            if relative != 'meta/0.pathc':
                raise ValueError('The earlier overlay has unsupported metadata; its backup needs review.')
            current = _target(root, relative).read_bytes()
            before = legacy_texture_baseline(baseline.read_bytes(), current,
                {path: (change['before'], change['after']) for path, change in changes.items() if path.endswith('.dds')})
            changes[relative] = {'before': before, 'after': current, 'flags': 0, 'meta': True}
        _add_layer(state, pending, f'Existing overlay {existing}', changes, item_keys=_added_item_keys(changes), legacy=True)
    return state, pending


def _observe_state(root):
    paths = (INDEX_PATH, '.cdmw/independent-items.json', '.cdmw/virtual-loader/profile.json', 'meta/0.papgt', 'meta/0.pathc')
    return tuple((relative, path.read_bytes() if path.is_file() else None)
                 for relative in paths for path in (_target(root, relative),))


def _verify_observed_state(root, observed, phase, error_type=OverlayConflict):
    for relative, expected in observed:
        path = _target(root, relative)
        actual = path.read_bytes() if path.is_file() else None
        if actual != expected or (expected is None and path.exists()):
            raise error_type(f'{relative} changed {phase}. Refresh and prepare again.')


def _retirement_state(root):
    state = _load_index(root)
    if state is None or not any(layer['active'] for layer in state['layers']):
        raise ValueError('No saved overlay set is available to retire. Refresh the list.')
    inventory = _target(root, INDEX_PATH).read_bytes()
    if json.loads(inventory) != state:
        raise OverlayConflict('The overlay inventory changed. Refresh and prepare again.')
    mount = _target(root, 'meta/0.papgt').read_bytes()
    records = parse_papgt(mount)
    if any(record.name == state['directory'] for record in records):
        raise OverlayConflict('Start fresh is only available when the saved overlay folder is not mounted. Use normal removal for mounted overlays.')
    if any(is_cdmw_overlay_directory(_target(root, str(record.name))) for record in records):
        raise OverlayConflict('Another CDMW overlay folder is mounted. Review it before starting a fresh set.')
    return state, inventory, mount


def compose_layer_payloads(layers, baseline, *, stop_event=None, on_log=None):
    """Pure composition shared by archive installation and virtual snapshots."""
    current = dict(baseline)
    from cdmw.domain.archives.iteminfo_composition import prepare_fields, finish_fields
    from cdmw.domain.archives.texture_composition import prepare_textures, finish_textures
    textures = prepare_textures(layers, stop_event=stop_event)
    normalized, fields = prepare_fields(layers, baseline, stop_event=stop_event)
    active = [layer for layer, _ in layers if layer['active']]
    inactive = {layer['id'] for layer, _ in layers if not layer['active']}
    active_items = {key for layer in active for key in layer['item_keys']}
    removed_items = {key for layer, _ in layers if not layer['active'] for key in layer['item_keys']} - active_items
    for layer, changes in layers:
        raise_if_cancelled(stop_event, 'Overlay composition cancelled.')
        if not layer['active']:
            continue
        if (inactive.intersection(layer['dependencies'])
                or (removed_items and removed_items.intersection(owned_item_references(changes)))):
            raise OverlayConflict(f"{layer['label']} uses an item or asset from the selected overlay. Remove the dependent overlay first.")
        if on_log:
            on_log(f"Composing {layer['label']}...")
        changes = normalized.get(layer['id'], changes)
        current = merge_overlay_files({p: c['before'] for p, c in changes.items()}, {p: c['after'] for p, c in changes.items()}, current)
    current = finish_fields(current, fields, stop_event=stop_event)
    return finish_textures(current, textures, stop_event=stop_event), active



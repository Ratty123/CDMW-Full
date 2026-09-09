"""Inventory, compose and remove individually owned CDMW overlay installs.

One mounted archive holds the composed result. An immutable journal per install
retains its before/after payloads, so shared tables can be rebuilt in either removal
order. Removed journal entries remain as the baseline and recovery history.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import time
import uuid
import zipfile

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, parse_papgt, papgt_with_directory, serialize_papgt
from cdmw.domain.archives.overlay_merge import (
    OverlayConflict, legacy_texture_baseline, merge_overlay_files, owned_item_references,
)
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.archive_overlay_install import (
    OVERLAY_OWNER_BYTES, OVERLAY_OWNER_MARKER, OverlayInstallResult,
    is_cdmw_overlay_directory, overlay_baseline_files, overlay_directory_name, _processed_payload,
)

INDEX_PATH = '.cdmw/overlays.json'
_FORMAT = 'cdmw_owned_overlays_v1'
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
    state = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(state, dict) or state.get('format') != _FORMAT or not isinstance(state.get('layers'), list):
        raise ValueError('Unsupported overlay inventory. Restore its backup before changing overlays.')
    _directory(state.get('directory'))
    ids = set()
    for layer in state['layers']:
        identity = str(layer.get('id', ''))
        if identity in ids or len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity):
            raise ValueError('Invalid overlay identity in the inventory.')
        ids.add(identity)
        if not isinstance(layer.get('active'), bool) or not isinstance(layer.get('label'), str):
            raise ValueError('Invalid overlay entry in the inventory.')
        if not isinstance(layer.get('item_keys'), list) or any(not isinstance(k, int) or k <= 0 for k in layer['item_keys']):
            raise ValueError('Invalid owned item identity in the inventory.')
        if not isinstance(layer.get('dependencies'), list) or any(not isinstance(d, str) for d in layer['dependencies']):
            raise ValueError('Invalid overlay dependency list.')
    if any(set(layer['dependencies']) - ids for layer in state['layers']):
        raise ValueError('An overlay dependency is missing from the inventory.')
    return state


def _mounted_owned(root):
    mount = _target(root, 'meta/0.papgt')
    records = parse_papgt(mount.read_bytes())
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
            raise OverlayConflict(f'{relative} changed outside the overlay manager. Restore or refresh the install before changing overlays.')
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
        raise OverlayConflict('Another CDMW archive group was installed outside this inventory. Remove or consolidate it before changing managed overlays.')


@dataclass(frozen=True)
class InstalledOverlay:
    id: str
    label: str
    item_keys: tuple[int, ...]
    directory: str
    file_count: int
    created_at: float
    legacy: bool = False


def list_installed_overlays(package_root, *, stop_event=None):
    root = Path(package_root).resolve()
    raise_if_cancelled(stop_event)
    state = _load_index(root)
    if state is not None:
        return tuple(InstalledOverlay(layer['id'], layer['label'], tuple(layer['item_keys']), state['directory'],
            int(layer['file_count']), float(layer['created_at']), bool(layer.get('legacy')))
            for layer in state['layers'] if layer['active'])
    _records, owned = _mounted_owned(root)
    result = []
    for record in owned:
        raise_if_cancelled(stop_event)
        pamt = _target(root, record.name + '/0.pamt')
        result.append(InstalledOverlay('legacy:' + record.name, f'Existing overlay {record.name}', (), record.name,
            len(parse_archive_pamt(pamt)), pamt.stat().st_mtime, True))
    return tuple(result)


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


def _unpack_changes(root, layer, pending, stop_event):
    relative = '.cdmw/overlays/' + layer['id'] + '.zip'
    path = _target(root, relative)
    if relative in pending:
        raw = pending[relative]
    else:
        if not path.is_file() or path.stat().st_size > _MAX_JOURNAL_BYTES:
            raise ValueError(f"The journal for {layer['label']} is missing or too large.")
        raw = path.read_bytes()
    if _digest(raw) != layer['sha256']:
        raise ValueError(f"The journal for {layer['label']} changed. Restore its backup before changing overlays.")
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
                value = archive.read(info)
                if _digest(value) != checksum:
                    raise ValueError('Overlay journal payload failed its checksum.')
                change[side] = value
            changes[path] = change
    return changes


def _add_layer(state, pending, label, changes, *, item_keys=(), dependencies=(), legacy=False):
    identity = uuid.uuid4().hex
    payload = _pack_changes(changes)
    pending['.cdmw/overlays/' + identity + '.zip'] = payload
    layer = {'id': identity, 'label': label, 'item_keys': list(item_keys), 'dependencies': list(dependencies),
        'active': True, 'created_at': time.time(), 'legacy': bool(legacy), 'file_count': len(changes), 'sha256': _digest(payload)}
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


def _uses_owned_assets(plan, changes, owned_changes):
    """Check the new runtime bindings, excluding inherited whole-table contents."""
    import re

    bindings = []
    for path, change in changes.items():
        if path != 'ui/xml/texture/cd_item_icon.xml' and path.endswith(('.prefab', '.pac_xml', '.xml', '.pae', '.paem', '.parg', '.pasg')):
            if change['after'] != change['before']:
                bindings.append(change['after'].lower())
    # Unchanged template variants and unedited effects can be referenced without
    # writing a new prefab/effect file for them.
    for variant in plan.manifest.get('variants', ()):
        if variant.get('appearance') == 'template':
            bindings.append(str(variant.get('model_path', '')).lower().encode())
            bindings.append(str(variant.get('prefab_path', '')).lower().encode())
    for effect in plan.manifest.get('effects', ()):
        bindings.append(str(effect.get('path', '')).lower().encode())
    for path, change in owned_changes.items():
        if change['before'] is not None or change['after'] is None or path in changes:
            continue
        if path.endswith(('.staticinfobody', '.staticinfoheader', '.pabgb', '.pabgh', '.pappt', '.paloc')):
            continue
        token = PurePosixPath(path).name
        if token.endswith(('.pae', '.paem', '.parg', '.pasg')):
            token = token.rsplit('.', 1)[0]
        pattern = re.compile(re.escape(token.encode()) + rb'(?![a-z0-9_])')
        if any(pattern.search(data) or token.encode('utf-16-le') in data for data in bindings):
            return True
    return False


def _state_for_edit(root, directory_name, stop_event):
    state = _load_index(root)
    if state is not None and any(layer['active'] for layer in state['layers']):
        _validate_published(root, state, stop_event)
        if directory_name is not None and _directory(directory_name) != state['directory']:
            raise ValueError(f"Managed installs share archive {state['directory']}. Choose Auto or that folder so their shared tables stay composed.")
        return state, {}
    records, owned = _mounted_owned(root)
    if state is not None and (owned or is_cdmw_overlay_directory(_target(root, state['directory']))):
        relative = state['directory']
        raise OverlayConflict(f'{relative} changed outside the overlay manager. Restore or refresh the install before changing overlays.')
    # With no installed layers, begin a fresh baseline from today's mounted files.
    # Old journals stay on disk and the replaced inventory is included in backup.
    if len(owned) > 1:
        raise OverlayConflict('Multiple earlier CDMW archive groups need consolidation before individual item management can begin.')
    existing = owned[0].name if owned else None
    name = _directory(directory_name or existing or overlay_directory_name(root))
    if existing and name != existing:
        raise ValueError(f'Choose Auto or {existing} to retain and manage the existing overlay.')
    directory = _target(root, name)
    if directory.exists() and not is_cdmw_overlay_directory(directory):
        raise ValueError(f'Archive {name} is not owned by CDMW.')
    if any(r.name == name for r in records) and not existing:
        raise ValueError(f'Archive {name} is reserved by the mount list.')
    state = {'format': _FORMAT, 'directory': name, 'layers': [], 'sources': {}, 'published': {}}
    pending = {}
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


@dataclass(frozen=True)
class OverlayChangePreparation:
    package_root: Path
    directory_name: str
    label: str
    removed_id: str | None
    remaining_labels: tuple[str, ...]
    writes: tuple[tuple[str, bytes], ...]
    deletes: tuple[str, ...]
    before: tuple[tuple[str, bytes | None], ...]
    source_stamps: tuple[tuple[str, tuple], ...]
    paths: tuple[str, ...]
    pamt_checksum: int
    payload_bytes: int
    carried_forward: int


@dataclass(frozen=True)
class OverlayRemovalResult:
    directory: Path
    label: str
    remaining: int
    backup_dir: Path
    removed_overlay_id: str


def _compose(root, state, pending, label, removed_id, stop_event, on_log):
    layers = []
    baseline, flags, meta_paths = {}, {}, set()
    for layer in state['layers']:
        changes = _unpack_changes(root, layer, pending, stop_event)
        layers.append((layer, changes))
        for path, change in changes.items():
            baseline.setdefault(path, change['before'])
            flags[path] = change['flags']
            if change['meta']:
                meta_paths.add(path)
    current = dict(baseline)
    active = [layer for layer in state['layers'] if layer['active']]
    inactive = {layer['id'] for layer in state['layers'] if not layer['active']}
    active_items = {key for layer in active for key in layer['item_keys']}
    removed_items = {key for layer in state['layers'] if not layer['active'] for key in layer['item_keys']} - active_items
    for layer, changes in layers:
        raise_if_cancelled(stop_event, 'Overlay composition cancelled.')
        if not layer['active']:
            continue
        if (inactive.intersection(layer['dependencies'])
                or (removed_items and removed_items.intersection(owned_item_references(changes)))):
            raise OverlayConflict(f"{layer['label']} uses an item or asset from the selected overlay. Remove the dependent overlay first.")
        if on_log:
            on_log(f"Composing {layer['label']}...")
        current = merge_overlay_files({p: c['before'] for p, c in changes.items()}, {p: c['after'] for p, c in changes.items()}, current)
    archive = []
    for path, payload in current.items():
        raise_if_cancelled(stop_event, 'Overlay archive preparation cancelled.')
        if path in meta_paths or payload is None or payload == baseline[path]:
            continue
        archive.append(OverlayFile(path, _processed_payload(payload, compression_type=flags[path] & 15,
            encrypted=bool(flags[path] >> 4), basename=path.rsplit('/', 1)[-1]), len(payload), flags[path]))
    name = state['directory']
    mount = _target(root, 'meta/0.papgt').read_bytes()
    writes = dict(pending)
    deletes = []
    if archive:
        built = build_overlay_archive(archive, stop_event=stop_event, on_log=on_log)
        writes.update({name + '/0.pamt': built.pamt_bytes, name + '/0.paz': built.paz_bytes, name + '/' + OVERLAY_OWNER_MARKER: OVERLAY_OWNER_BYTES})
        writes['meta/0.papgt'] = papgt_with_directory(mount, name, built.pamt_checksum, flags=PAPGT_DEFAULT_FLAGS, first=True)
        checksum, payload_bytes = built.pamt_checksum, len(built.paz_bytes)
    else:
        if active:
            raise OverlayConflict('An active overlay composed no archive changes.')
        writes['meta/0.papgt'] = serialize_papgt([r for r in parse_papgt(mount) if r.name != name], header=mount[:12])
        deletes.extend((name + '/0.pamt', name + '/0.paz', name + '/' + OVERLAY_OWNER_MARKER))
        checksum = payload_bytes = 0
    for path in meta_paths:
        if current[path] is None:
            deletes.append(path)
        else:
            writes[path] = current[path]
    state['published'] = {p: _digest(v) for p, v in writes.items() if p.startswith(name + '/') or p in meta_paths}
    state['published'].update({p: None for p in deletes})
    writes[INDEX_PATH] = _json(state)
    paths = tuple(sorted(e.path for e in archive))
    before = tuple((path, _target(root, path).read_bytes() if _target(root, path).is_file() else None) for path in dict.fromkeys((*writes, *deletes)))
    return OverlayChangePreparation(root, name, label, removed_id, tuple(layer['label'] for layer in active),
        tuple(writes.items()), tuple(deletes), before, tuple((p, tuple(s)) for p, s in state['sources'].items()), paths,
        checksum, payload_bytes, sum(layer['file_count'] for layer in active[:-1]) if removed_id is None else len(paths))


def prepare_item_overlay(plan, package_root, *, directory_name=None, stop_event=None, on_log=None):
    root = Path(package_root).resolve()
    if plan.source_revision is not None:
        plan.source_revision.validate(stop_event)
    state, pending = _state_for_edit(root, directory_name, stop_event)
    mounted_path = _target(root, state['directory'] + '/0.pamt')
    mounted_entries = {str(entry.path).lower(): entry for entry in parse_archive_pamt(mounted_path)} if mounted_path.is_file() else {}
    changes = {}
    for request in plan.patches:
        raise_if_cancelled(stop_event, 'Overlay change capture cancelled.')
        path = _relative(request.entry.path)
        _remember_source(root, state, request.entry)
        before = _read(request.entry)
        if path in mounted_entries and before != _read(mounted_entries[path]):
            # A higher-priority external mod can replace a shared table without
            # touching our archive. Do not hide its rows when remounting ours first.
            raise OverlayConflict(f'Overlay conflict in {path}; overlapping file edits cannot be separated safely.')
        changes[path] = {'before': before, 'after': bytes(request.payload_data), 'flags': int(request.entry.flags), 'meta': False}
    for addition in plan.additions:
        path = _relative(addition.path)
        if path in changes:
            raise OverlayConflict(f'{path} is both added and replaced.')
        changes[path] = {'before': None, 'after': bytes(addition.payload_data), 'flags': int(addition.flags), 'meta': False}
    for write in plan.meta_files:
        path = _relative(write.path)
        if path != 'meta/0.pathc':
            raise ValueError('Only the texture registry is supported as overlay metadata.')
        changes[path] = {'before': _target(root, path).read_bytes(), 'after': bytes(write.payload_data), 'flags': 0, 'meta': True}
    if not changes:
        raise ValueError('The overlay plan changes nothing.')
    item_keys = _added_item_keys(changes)
    known_items = set(item_keys) | {int(plan.spec.item_key)}
    references = owned_item_references(changes) | {int(plan.spec.template_key)}
    dependencies = []
    for layer in state['layers']:
        if not layer['active']:
            continue
        if known_items.intersection(layer['item_keys']):
            raise OverlayConflict(f"Item identity conflicts with {layer['label']}. Build a new plan from the current installed tables.")
        if references.intersection(layer['item_keys']) or _uses_owned_assets(
            plan, changes, _unpack_changes(root, layer, pending, stop_event)
        ):
            dependencies.append(layer['id'])
    _add_layer(state, pending, plan.spec.display_names.get('eng') or plan.spec.internal_name, changes,
        item_keys=tuple(sorted(known_items)), dependencies=dependencies)
    return _compose(root, state, pending, plan.spec.internal_name, None, stop_event, on_log)


def prepare_overlay_removal(package_root, overlay_id, *, stop_event=None, on_log=None):
    root = Path(package_root).resolve()
    state, pending = _state_for_edit(root, None, stop_event)
    identity = str(overlay_id)
    selected = next((layer for layer in state['layers'] if layer['active'] and
        (layer['id'] == identity or (identity == 'legacy:' + state['directory'] and layer.get('legacy')))), None)
    if selected is None:
        raise ValueError('The selected overlay is no longer installed. Refresh the list.')
    selected['active'] = False
    return _compose(root, state, pending, selected['label'], selected['id'], stop_event, on_log)


def _verify_backup(backup_dir, expected):
    manifest = Path(backup_dir) / 'backup_manifest.json'
    if not manifest.is_file() or manifest.stat().st_size > _MAX_STATE_BYTES:
        raise ValueError('The overlay backup manifest is missing or invalid.')
    items = json.loads(manifest.read_text(encoding='utf-8')).get('files', [])
    files = {}
    for item in items:
        original, kept = Path(item['original_path']).resolve(), Path(item['backup_path']).resolve()
        if Path(backup_dir).resolve() not in kept.parents or not kept.is_file() or original in files:
            raise ValueError('The overlay backup contains an invalid file entry.')
        files[original] = kept
    if set(files) != set(expected) or any(files[path].read_bytes() != payload for path, payload in expected.items()):
        raise ValueError('The overlay backup did not preserve every confirmed original file.')


def apply_overlay_change(preparation, *, confirmed, backup, restore_backup, game_running=None, stop_event=None, on_log=None):
    if not isinstance(preparation, OverlayChangePreparation):
        raise TypeError('Overlay changes require a prepared change.')
    if not confirmed:
        raise PermissionError('Overlay changes require explicit confirmation.')
    if not callable(backup) or not callable(restore_backup):
        raise ValueError('The overlay change needs backup and restore services.')
    if game_running is None:
        from cdmw.services.new_item_service import game_is_running
        game_running = game_is_running
    if game_running():
        raise RuntimeError('Close Crimson Desert before changing overlays.')
    root = preparation.package_root.resolve()
    name = _directory(preparation.directory_name)
    allowed = {INDEX_PATH, 'meta/0.papgt', 'meta/0.pathc', name + '/0.pamt', name + '/0.paz', name + '/' + OVERLAY_OWNER_MARKER}
    import re
    for relative in (*dict(preparation.writes), *preparation.deletes):
        if relative not in allowed and not re.fullmatch(r'\.cdmw/overlays/[0-9a-f]{32}\.zip', relative):
            raise ValueError('A prepared overlay change targets a file outside its ownership.')
    if set(dict(preparation.before)) != set(dict(preparation.writes)) | set(preparation.deletes):
        raise ValueError('Prepared overlay targets do not match their original files.')
    if set(preparation.deletes) - {name + '/0.pamt', name + '/0.paz', name + '/' + OVERLAY_OWNER_MARKER, 'meta/0.pathc'}:
        raise ValueError('A prepared overlay removal names an unowned file.')
    originals = {}
    for relative, expected in preparation.before:
        path = _target(root, relative)
        actual = path.read_bytes() if path.is_file() else None
        if actual != expected or (expected is None and path.exists()):
            raise OverlayConflict(f'{relative} changed after preparation. Refresh and prepare again.')
        if expected is not None:
            originals[path] = expected
    for relative, expected in preparation.source_stamps:
        path = _target(root, relative)
        if not path.is_file() or tuple(_stamp(path)) != expected:
            raise OverlayConflict(f'The source archive {relative} changed after preparation.')
    raise_if_cancelled(stop_event, 'Overlay change cancelled before backup.')
    backup_dir = Path(backup(tuple(sorted(originals)), f'Overlay: {preparation.label}'))
    _verify_backup(backup_dir, originals)
    if game_running():
        raise RuntimeError('Crimson Desert started during backup. Close it before changing overlays.')
    for relative, expected in preparation.before:
        path = _target(root, relative)
        actual = path.read_bytes() if path.is_file() else None
        if actual != expected or (expected is None and path.exists()):
            raise OverlayConflict(f'{relative} changed after preparation. Refresh and prepare again.')
    for relative, expected in preparation.source_stamps:
        path = _target(root, relative)
        if not path.is_file() or tuple(_stamp(path)) != expected:
            raise OverlayConflict(f'The source archive {relative} changed after preparation.')
    writes = dict(preparation.writes)
    try:
        for relative, payload in preparation.writes:
            if relative == 'meta/0.papgt':
                continue
            raise_if_cancelled(stop_event, 'Overlay change cancelled; restoring the backup.')
            atomic_write_bytes(_target(root, relative), payload)
            if _target(root, relative).read_bytes() != payload:
                raise RuntimeError(f'Staged overlay bytes differ from the preparation: {relative}')
        # Validate the staged archive through the actual index reader before
        # publishing the mount list. No cancellation inside final publication.
        if preparation.paths:
            pamt = _target(root, preparation.directory_name + '/0.pamt')
            actual = tuple(sorted(str(e.path).lower() for e in parse_archive_pamt(pamt)))
            if actual != preparation.paths:
                raise RuntimeError('Staged overlay paths differ from the prepared archive.')
        raise_if_cancelled(stop_event, 'Overlay change cancelled before publication.')
        atomic_write_bytes(_target(root, 'meta/0.papgt'), writes['meta/0.papgt'])
        for relative in preparation.deletes:
            _target(root, relative).unlink(missing_ok=True)
    except BaseException as error:
        try:
            restore_backup(backup_dir)
            for relative, previous in preparation.before:
                if previous is None:
                    _target(root, relative).unlink(missing_ok=True)
            for path, expected in originals.items():
                if not path.is_file() or path.read_bytes() != expected:
                    raise RuntimeError(f'Rollback did not restore {path.name}.')
        except Exception as rollback_error:
            raise RuntimeError(f'Overlay change failed; recovery requires backup {backup_dir}: {rollback_error}') from error
        raise
    directory = _target(root, preparation.directory_name)
    if not preparation.paths:
        try:
            directory.rmdir()
        except OSError:
            pass
    if on_log:
        on_log(f"Overlay {'removed' if preparation.removed_id else 'installed'}: {preparation.label}. {len(preparation.remaining_labels)} installed. Backup: {backup_dir}")
    if preparation.removed_id:
        return OverlayRemovalResult(directory, preparation.label, len(preparation.remaining_labels), backup_dir, preparation.removed_id)
    return OverlayInstallResult(directory, preparation.pamt_checksum, len(preparation.paths), preparation.payload_bytes,
        preparation.carried_forward, backup_dir, preparation.paths)

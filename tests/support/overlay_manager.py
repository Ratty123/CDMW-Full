"""Retired install code from cdmw.services.archive_overlay_manager, kept for tests only (decision 39)."""

# CDMW never installs into the game. Tests use this on owned game folders made in the
# test, to build the state the live code reads. Names the app still has are read from
# cdmw.services.archive_overlay_manager at call time (``_live``), so patching them there reaches this code.

from __future__ import annotations

from dataclasses import dataclass, replace
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
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, parse_papgt, papgt_with_directory, read_papgt_directories, serialize_papgt
from cdmw.domain.archives.overlay_merge import (
    OverlayConflict, legacy_texture_baseline, merge_overlay_files, owned_item_references,
)
from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.services.application_shutdown_service import archive_write_scope
from cdmw.services.installation_lane import serialized_installation
from tests.support.overlay_recovery import OverlayTargetRecovery, payload_digest
from tests.support.overlay_install import (
    OVERLAY_OWNER_BYTES, OVERLAY_OWNER_MARKER, OverlayInstallResult,
    is_cdmw_overlay_directory, overlay_baseline_files, overlay_directory_name, _processed_payload,
)

import cdmw.services.archive_overlay_manager as _live


def __getattr__(name):
    return getattr(_live, name)


def _inventory_bytes(state):
    return (json.dumps(state, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')


def _check_inventory_capacity(data):
    if len(data) > _live._MAX_STATE_BYTES:
        raise OverlayConflict(f'The composed overlay history exceeds the supported size (at least {len(data):,} bytes; limit {_live._MAX_STATE_BYTES:,} bytes); this change cannot be published.')


def _share_compilation_contexts(state, stop_event):
    from cdmw.domain.new_item.compilation_storage import REFERENCE_FORMAT, read_compilation, store_compilation
    contexts = dict(state.get('compilation_contexts', {}))
    for layer in state['layers']:
        raise_if_cancelled(stop_event, 'Overlay composition cancelled.')
        if 'independent_compilation' not in layer:
            continue
        record = layer['independent_compilation']
        if isinstance(record, dict) and record.get('format') == REFERENCE_FORMAT:
            read_compilation(record, contexts)
        else:
            layer['independent_compilation'] = store_compilation(record, contexts)
    if contexts or state['format'] == _live._FORMAT_WITH_CONTEXTS:
        state['format'] = _live._FORMAT_WITH_CONTEXTS
        state['compilation_contexts'] = contexts


@dataclass(frozen=True)
class InstalledOverlay:
    id: str
    label: str
    item_keys: tuple[int, ...]
    directory: str
    file_count: int
    created_at: float
    legacy: bool = False
    game_build: str = 'Unknown'
    compatibility_status: str = 'unknown'
    enabled: bool = True
    health: str = 'mounted'
    issue: str = ''
    dependencies: tuple[str, ...] = ()


def list_installed_overlays(package_root, *, stop_event=None):
    root = Path(package_root).resolve()
    raise_if_cancelled(stop_event)
    state = _live._load_index(root)
    if state is not None:
        from cdmw.core.mod_compatibility import build_label, build_status, game_identity
        current_game = game_identity(root, stop_event)
        sources_changed = any((not _live._target(root, relative).is_file() or _live._stamp(_live._target(root, relative)) != stamp for relative, stamp in state.get('sources', {}).items()))
        records = read_papgt_directories(_live._target(root, 'meta/0.papgt').read_bytes())
        mounted = any((record.name == state['directory'] for record in records))
        expected_mount = any((layer['active'] for layer in state['layers']))
        health = 'mounted' if mounted else 'unmounted' if expected_mount else 'disabled'
        issue = 'The saved overlay is not mounted by the game.' if expected_mount and (not mounted) else ''
        try:
            _live._validate_published(root, state, stop_event)
        except (ValueError, OSError) as error:
            issue = (issue + '\n' if issue else '') + str(error)
            if mounted:
                health = 'missing' if any((not _live._target(root, path).is_file() for path, value in state.get('published', {}).items() if value is not None)) else 'changed'
        return tuple((InstalledOverlay(layer['id'], layer['label'], tuple(layer['item_keys']), state['directory'], int(layer['file_count']), float(layer['created_at']), bool(layer.get('legacy')), build_label(layer.get('target_game')), 'unmounted' if not mounted and layer['active'] else 'changed' if sources_changed else build_status(layer.get('target_game'), current_game), layer['active'], health if layer['active'] else 'disabled', issue, tuple((other['label'] for other in state['layers'] if other['id'] in layer['dependencies']))) for layer in state['layers'] if layer['active'] or layer.get('disabled', False)))
    _records, owned = _live._mounted_owned(root)
    result = []
    for record in owned:
        raise_if_cancelled(stop_event)
        pamt = _live._target(root, record.name + '/0.pamt')
        result.append(InstalledOverlay('legacy:' + record.name, f'Existing overlay {record.name}', (), record.name, len(parse_archive_pamt(pamt)), pamt.stat().st_mtime, True))
    return tuple(result)


def _uses_owned_assets(plan, changes, owned_changes):
    """Check the new runtime bindings, excluding inherited whole-table contents."""
    import re
    bindings = []
    for path, change in changes.items():
        if path != 'ui/xml/texture/cd_item_icon.xml' and path.endswith(('.prefab', '.pac_xml', '.xml', '.pae', '.paem', '.parg', '.pasg')):
            if change['after'] != change['before']:
                bindings.append(change['after'].lower())
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
        pattern = re.compile(re.escape(token.encode()) + b'(?![a-z0-9_])')
        if any((pattern.search(data) or token.encode('utf-16-le') in data for data in bindings)):
            return True
    return False


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
    action: str = 'remove'
    observed_state: tuple[tuple[str, bytes | None], ...] = ()
    source_directories: tuple[tuple[str, tuple[str, ...]], ...] = ()
    source_revisions: tuple[object, ...] = ()
    source_checksums: tuple[tuple[Path, str], ...] = ()


def _pin_preparation(prepared, observed, *, error_type=OverlayConflict):
    """Tie composition and publication to the state read before planning began."""
    _live._verify_observed_state(prepared.package_root, observed, 'during preparation', error_type)
    before = dict(prepared.before)
    if any((path in before and before[path] != expected for path, expected in observed)):
        raise error_type('The installed state changed during preparation. Refresh and prepare again.')
    return replace(prepared, observed_state=observed)


@dataclass(frozen=True)
class OverlayRemovalResult:
    directory: Path
    label: str
    remaining: int
    backup_dir: Path
    removed_overlay_id: str
    action: str = 'remove'


@dataclass(frozen=True)
class OverlayRetirementPreparation:
    package_root: Path
    directory_name: str
    labels: tuple[str, ...]
    inventory_data: bytes
    mount_data: bytes
    retirement_id: str


@dataclass(frozen=True)
class OverlayRetirementResult:
    directory: Path
    labels: tuple[str, ...]
    backup_dir: Path
    retired_inventory: Path


def prepare_overlay_retirement(package_root, *, stop_event=None):
    """Retire only an unmounted inventory, preserving current game data and old payloads."""
    raise_if_cancelled(stop_event)
    root = Path(package_root).resolve()
    state, inventory, mount = _live._retirement_state(root)
    return OverlayRetirementPreparation(root, state['directory'], tuple((layer['label'] for layer in state['layers'] if layer['active'])), inventory, mount, uuid.uuid4().hex)


@archive_write_scope()
@serialized_installation(lambda preparation, **_kwargs: getattr(preparation, 'package_root', None))
def apply_overlay_retirement(preparation, *, confirmed, backup, restore_backup, game_running=None, stop_event=None, on_log=None):
    if not confirmed:
        raise PermissionError('Starting a fresh overlay set requires explicit confirmation.')
    if not callable(backup) or not callable(restore_backup):
        raise ValueError('Starting a fresh overlay set needs backup and restore services.')
    if game_running is None:
        from cdmw.services.new_item_service import game_is_running
        game_running = game_is_running
    root = preparation.package_root.resolve()
    identity = preparation.retirement_id
    if len(identity) != 32 or any((c not in '0123456789abcdef' for c in identity)):
        raise ValueError('Invalid retired overlay history identity.')
    inventory = _live._target(root, _live.INDEX_PATH)
    retired = _live._target(root, '.cdmw/retired-overlays/' + identity + '.json')

    def verify_current():
        raise_if_cancelled(stop_event, 'Starting a fresh overlay set cancelled.')
        if game_running():
            raise RuntimeError('Close Crimson Desert before changing overlays.')
        state, current, mount = _live._retirement_state(root)
        labels = tuple((layer['label'] for layer in state['layers'] if layer['active']))
        if current != preparation.inventory_data or mount != preparation.mount_data or state['directory'] != preparation.directory_name or (labels != preparation.labels):
            raise OverlayConflict('The overlay state changed after preparation. Refresh and prepare again.')
        if retired.exists():
            raise OverlayConflict('The retired overlay history already exists. Refresh and prepare again.')
    verify_current()
    backup_dir = Path(backup((inventory,), 'Retire unmounted overlays: ' + ', '.join(preparation.labels)))
    _verify_backup(backup_dir, {inventory: preparation.inventory_data})
    verify_current()
    recovery = OverlayTargetRecovery(root, {inventory: payload_digest(preparation.inventory_data), retired: None}, backup_dir=backup_dir, restore_backup=restore_backup, stop_event=stop_event)
    try:
        retired.parent.mkdir(parents=True, exist_ok=True)
        recovery.mutate({inventory: None, retired: payload_digest(preparation.inventory_data)}, lambda: inventory.rename(retired))
        if inventory.exists() or retired.read_bytes() != preparation.inventory_data:
            raise RuntimeError('Retired overlay history did not match the reviewed inventory.')
        recovery.committed()
    except BaseException as error:
        try:
            recovery.rollback()
        except Exception as rollback_error:
            raise RuntimeError(f'Overlay retirement failed; recovery requires backup {backup_dir}: {rollback_error}') from error
        raise
    if on_log:
        on_log(f'Retired {len(preparation.labels)} unmounted overlay(s). History: {retired}. Backup: {backup_dir}')
    return OverlayRetirementResult(_live._target(root, preparation.directory_name), preparation.labels, backup_dir, retired)


def _compose(root, state, pending, label, removed_id, stop_event, on_log, *, decoded=None, independent_context=None):
    raise_if_cancelled(stop_event, 'Overlay composition cancelled.')
    _share_compilation_contexts(state, stop_event)
    _check_inventory_capacity(_inventory_bytes({**state, 'sources': {}, 'published': {}}))
    layers = []
    source_directories = ()
    source_revisions = ()
    baseline, flags, meta_paths = ({}, {}, set())
    for layer in state['layers']:
        raise_if_cancelled(stop_event, 'Overlay composition cancelled.')
        changes = decoded.pop(layer['id'], None) if decoded is not None else None
        if changes is None:
            changes = _live._unpack_changes(root, layer, pending, stop_event)
        else:
            _live._read_journal(root, layer, pending)
        layers.append((layer, changes))
        for path, change in changes.items():
            baseline.setdefault(path, change['before'])
            flags[path] = change['flags']
            if change['meta']:
                meta_paths.add(path)
    if any((layer.get('independent_identity') for layer, _ in layers)):
        from cdmw.services.independent_item_compatibility import compose_underlay
        baseline, source_directories, source_revisions = compose_underlay(root, state, pending, layers, baseline, stop_event=stop_event, on_log=on_log, context=independent_context)
    current, active = _live.compose_layer_payloads(layers, baseline, stop_event=stop_event, on_log=on_log)
    from cdmw.domain.archives.iteminfo_composition import required_field_files
    from cdmw.domain.archives.texture_composition import required_texture_files
    required = required_field_files(layers, current) | required_texture_files(layers)
    archive_paths = []
    for path, payload in current.items():
        raise_if_cancelled(stop_event, 'Overlay archive preparation cancelled.')
        if path in meta_paths or payload is None or (payload == baseline[path] and path not in required):
            continue
        archive_paths.append(path)
    if not archive_paths and active:
        raise OverlayConflict('An active overlay composed no archive changes.')
    name = state['directory']
    archive_targets = (name + '/0.pamt', name + '/0.paz', name + '/' + OVERLAY_OWNER_MARKER)
    checksum_placeholder = '0' * 64
    published = {p: checksum_placeholder for p in pending if p.startswith(name + '/') or p in meta_paths}
    published.update({p: checksum_placeholder if archive_paths else None for p in archive_targets})
    published.update({p: checksum_placeholder if current[p] is not None else None for p in meta_paths})
    _check_inventory_capacity(_inventory_bytes({**state, 'published': published}))
    archive = []
    for path in archive_paths:
        raise_if_cancelled(stop_event, 'Overlay archive preparation cancelled.')
        payload = current[path]
        archive.append(OverlayFile(path, _processed_payload(payload, compression_type=flags[path] & 15, encrypted=bool(flags[path] >> 4), basename=path.rsplit('/', 1)[-1]), len(payload), flags[path]))
    mount = _live._target(root, 'meta/0.papgt').read_bytes()
    writes = dict(pending)
    deletes = []
    if archive:
        built = build_overlay_archive(archive, stop_event=stop_event, on_log=on_log)
        writes.update(zip(archive_targets, (built.pamt_bytes, built.paz_bytes, OVERLAY_OWNER_BYTES)))
        writes['meta/0.papgt'] = papgt_with_directory(mount, name, built.pamt_checksum, flags=PAPGT_DEFAULT_FLAGS, first=True)
        checksum, payload_bytes = (built.pamt_checksum, len(built.paz_bytes))
    else:
        writes['meta/0.papgt'] = serialize_papgt([r for r in parse_papgt(mount) if r.name != name], header=mount[:12])
        deletes.extend(archive_targets)
        checksum = payload_bytes = 0
    for path in meta_paths:
        if current[path] is None:
            deletes.append(path)
        else:
            writes[path] = current[path]
    state['published'] = {p: _live._digest(v) for p, v in writes.items() if p.startswith(name + '/') or p in meta_paths}
    state['published'].update({p: None for p in deletes})
    writes[_live.INDEX_PATH] = _inventory_bytes(state)
    _check_inventory_capacity(writes[_live.INDEX_PATH])
    paths = tuple(sorted((e.path for e in archive)))
    del layers, baseline, current, archive, archive_paths
    before = tuple(((path, _live._target(root, path).read_bytes() if _live._target(root, path).is_file() else None) for path in dict.fromkeys((*writes, *deletes))))
    return OverlayChangePreparation(root, name, label, removed_id, tuple((layer['label'] for layer in active)), tuple(writes.items()), tuple(deletes), before, tuple(((p, tuple(s)) for p, s in state['sources'].items())), paths, checksum, payload_bytes, sum((layer['file_count'] for layer in active[:-1])) if removed_id is None else len(paths), source_directories=source_directories, source_revisions=source_revisions, source_checksums=_source_checksums(source_revisions, stop_event))


def prepare_item_overlay(plan, package_root, *, directory_name=None, stop_event=None, on_log=None, retirement=None):
    root = Path(package_root).resolve()
    observed = _live._observe_state(root)
    if on_log:
        on_log('Validating the plan archive sources...')
    if plan.source_revision is not None:
        plan.source_revision.validate(stop_event)
    if on_log:
        on_log('Checking installed overlay state...')
    state, pending = _live._state_for_edit(root, directory_name, stop_event, retirement=retirement)
    mounted_path = _live._target(root, state['directory'] + '/0.pamt')
    mounted_entries = {str(entry.path).lower(): entry for entry in parse_archive_pamt(mounted_path)} if mounted_path.is_file() else {}
    changes = {}
    for request in plan.patches:
        raise_if_cancelled(stop_event, 'Overlay change capture cancelled.')
        path = _live._relative(request.entry.path)
        _live._remember_source(root, state, request.entry)
        before = _live._read(request.entry)
        if path in mounted_entries and before != _live._read(mounted_entries[path]):
            raise OverlayConflict(f'Overlay conflict in {path}; overlapping file edits cannot be separated safely.')
        changes[path] = {'before': before, 'after': bytes(request.payload_data), 'flags': int(request.entry.flags), 'meta': False}
    for addition in plan.additions:
        path = _live._relative(addition.path)
        if path in changes:
            raise OverlayConflict(f'{path} is both added and replaced.')
        changes[path] = {'before': None, 'after': bytes(addition.payload_data), 'flags': int(addition.flags), 'meta': False}
    for write in plan.meta_files:
        path = _live._relative(write.path)
        if path != 'meta/0.pathc':
            raise ValueError('Only the texture registry is supported as overlay metadata.')
        changes[path] = {'before': _live._target(root, path).read_bytes(), 'after': bytes(write.payload_data), 'flags': 0, 'meta': True}
    if not changes:
        raise ValueError('The overlay plan changes nothing.')
    item_keys = _live._added_item_keys(changes)
    known_items = set(item_keys) | {int(plan.spec.item_key)}
    if _live._target(root, '.cdmw/independent-items.json').exists():
        from cdmw.services.independent_item_install import load_registry
        registry = load_registry(root)
        if any((known_items.intersection(row['values'].get('iteminfo', {}).values()) for row in registry['items'].values())):
            raise OverlayConflict('This item identity is reserved by an independent package. Rebuild with a different identity or update that package through Independent items.')
    references = owned_item_references(changes) | {int(plan.spec.template_key)}
    dependencies = []
    decoded = {}
    if on_log:
        on_log('Checking dependencies against installed overlays...')
    for layer in state['layers']:
        if not layer['active'] and (not layer.get('disabled', False)):
            continue
        if known_items.intersection(layer['item_keys']):
            raise OverlayConflict(f"Item identity conflicts with {layer['label']}. Build a new plan from the current installed tables.")
        if not layer['active']:
            continue
        if references.intersection(layer['item_keys']):
            dependencies.append(layer['id'])
            continue
        decoded[layer['id']] = _live._unpack_changes(root, layer, pending, stop_event)
        if _uses_owned_assets(plan, changes, decoded[layer['id']]):
            dependencies.append(layer['id'])
    from cdmw.core.mod_compatibility import game_identity
    if on_log:
        on_log('Preparing overlay history...')
    _live._add_layer(state, pending, plan.spec.display_names.get('eng') or plan.spec.internal_name, changes, item_keys=tuple(sorted(known_items)), dependencies=dependencies, target_game=game_identity(root, stop_event))
    prepared = _compose(root, state, pending, plan.spec.internal_name, None, stop_event, on_log, decoded=decoded)
    if retirement is not None:
        before = dict(prepared.before)
        archived = '.cdmw/retired-overlays/' + retirement.retirement_id + '.json'
        if before[_live.INDEX_PATH] != retirement.inventory_data or before['meta/0.papgt'] != retirement.mount_data or before[archived] is not None:
            raise OverlayConflict('The overlay state changed after preparation. Refresh and prepare again.')
    return _pin_preparation(prepared, observed)


def prepare_overlay_removal(package_root, overlay_id, *, stop_event=None, on_log=None):
    return _prepare_overlay_selection(package_root, overlay_id, None, stop_event=stop_event, on_log=on_log)


def _prepare_overlay_selection(package_root, overlay_ids, enabled, *, stop_event=None, on_log=None):
    root = Path(package_root).resolve()
    observed = _live._observe_state(root)
    state, pending = _live._state_for_edit(root, None, stop_event)
    identities = tuple(dict.fromkeys((overlay_ids,) if isinstance(overlay_ids, str) else overlay_ids))
    if not identities:
        raise ValueError('Select at least one installed overlay.')
    selected = []
    for identity in identities:
        layer = next((layer for layer in state['layers'] if (layer['active'] or layer.get('disabled', False)) and (layer['id'] == identity or (identity == 'legacy:' + state['directory'] and layer.get('legacy')))), None)
        if layer is None:
            raise ValueError('The selected overlay is no longer installed. Refresh the list.')
        selected.append(layer)
    for layer in selected:
        layer['active'] = bool(enabled)
        if enabled is None:
            layer.pop('disabled', None)
        else:
            layer['disabled'] = not enabled
    result = _pin_preparation(_compose(root, state, pending, '\n'.join((layer['label'] for layer in selected)), selected[0]['id'], stop_event, on_log), observed)
    return replace(result, action='remove' if enabled is None else 'enable' if enabled else 'disable')


def prepare_overlay_enabled(package_root, overlay_id, enabled, *, stop_event=None, on_log=None):
    """Review a reversible enable/disable using the same composition and transaction as removal."""
    return _prepare_overlay_selection(package_root, overlay_id, bool(enabled), stop_event=stop_event, on_log=on_log)


def _file_matches_bytes(path, expected):
    """Exact comparison with bounded temporary reads, including empty/absent files."""
    if expected is None:
        return not path.exists()
    if not path.is_file():
        return False
    offset, view = (0, memoryview(expected))
    chunk = bytearray(min(1024 * 1024, len(expected) + 1))
    with path.open('rb') as source:
        while (size := source.readinto(chunk)):
            if (chunk if size == len(chunk) else chunk[:size]) != view[offset:offset + size]:
                return False
            offset += size
    return offset == len(expected)


def _verify_backup(backup_dir, expected):
    manifest = Path(backup_dir) / 'backup_manifest.json'
    if not manifest.is_file() or manifest.stat().st_size > _live._MAX_STATE_BYTES:
        raise ValueError('The overlay backup manifest is missing or invalid.')
    items = json.loads(manifest.read_text(encoding='utf-8')).get('files', [])
    files = {}
    for item in items:
        original, kept = (Path(item['original_path']).resolve(), Path(item['backup_path']).resolve())
        if Path(backup_dir).resolve() not in kept.parents or not kept.is_file() or original in files:
            raise ValueError('The overlay backup contains an invalid file entry.')
        files[original] = kept
    if set(files) != set(expected) or any((not _file_matches_bytes(files[path], payload) for path, payload in expected.items())):
        raise ValueError('The overlay backup did not preserve every confirmed original file.')


def _verify_source_directories(root, preparation):
    for relative, expected in preparation.source_directories:
        directory = _live._target(root, relative)
        if tuple(sorted((path.name for path in directory.glob('*.pamt')))) != expected:
            raise OverlayConflict(f'The source archive folder {relative} changed after preparation. Scan again.')


def _read_source_checksum(path, stop_event):
    checksum = hashlib.sha256()
    with path.open('rb') as source:
        while (chunk := source.read(1024 * 1024)):
            raise_if_cancelled(stop_event, 'Source verification cancelled.')
            checksum.update(chunk)
    return checksum.hexdigest()


def _source_checksums(revisions, stop_event):
    paths = set()
    indexes = {}
    for revision in revisions:
        source = getattr(revision, 'source_revision', revision)
        paths.update((path for path, stamp in source.files if stamp is not None and path.suffix.lower() != '.paz'))
        for path, checksum in source.indexes:
            if indexes.setdefault(path, checksum) != checksum:
                raise OverlayConflict(f'Source index has conflicting parsed revisions: {path}.')
    checksums = []
    for path in sorted(paths):
        checksum = _read_source_checksum(path, stop_event)
        if path in indexes and checksum != indexes[path]:
            raise OverlayConflict(f'Source index changed since parsing: {path}.')
        checksums.append((path, checksum))
    return tuple(checksums)


def _verify_source_content(preparation, stop_event):
    try:
        for revision in preparation.source_revisions:
            revision.validate(stop_event)
        for path, checksum in preparation.source_checksums:
            if _read_source_checksum(path, stop_event) != checksum:
                raise OverlayConflict(f'The source file {path} changed after preparation.')
    except RunCancelled:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise OverlayConflict(f'Source dependencies changed or cannot be verified after preparation: {exc}') from exc


@archive_write_scope()
@serialized_installation(lambda preparation, **_kwargs: getattr(preparation, 'package_root', None))
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
    name = _live._directory(preparation.directory_name)
    allowed = {_live.INDEX_PATH, '.cdmw/independent-items.json', 'meta/0.papgt', 'meta/0.pathc', name + '/0.pamt', name + '/0.paz', name + '/' + OVERLAY_OWNER_MARKER}
    import re
    for relative in (*dict(preparation.writes), *preparation.deletes):
        if relative not in allowed and (not re.fullmatch('\\.cdmw/(?:overlays/[0-9a-f]{32}\\.zip|retired-overlays/[0-9a-f]{32}\\.json|independent-items/[0-9a-f]{32}-[0-9a-f]{64}\\.cditem)', relative)):
            raise ValueError('A prepared overlay change targets a file outside its ownership.')
    if set(dict(preparation.before)) != set(dict(preparation.writes)) | set(preparation.deletes):
        raise ValueError('Prepared overlay targets do not match their original files.')
    if set(preparation.deletes) - {name + '/0.pamt', name + '/0.paz', name + '/' + OVERLAY_OWNER_MARKER, 'meta/0.pathc'}:
        raise ValueError('A prepared overlay removal names an unowned file.')
    for relative, payload in preparation.writes:
        if relative == _live.INDEX_PATH:
            _check_inventory_capacity(payload)
    originals = {}
    _verify_source_directories(root, preparation)
    _live._verify_observed_state(root, preparation.observed_state, 'after preparation')
    for relative, expected in preparation.before:
        path = _live._target(root, relative)
        if not _file_matches_bytes(path, expected):
            raise OverlayConflict(f'{relative} changed after preparation. Refresh and prepare again.')
        if expected is not None:
            originals[path] = expected
    for relative, expected in preparation.source_stamps:
        path = _live._target(root, relative)
        if not path.is_file() or tuple(_live._stamp(path)) != expected:
            raise OverlayConflict(f'The source archive {relative} changed after preparation.')
    _verify_source_content(preparation, stop_event)
    raise_if_cancelled(stop_event, 'Overlay change cancelled before backup.')
    backup_dir = Path(backup(tuple(sorted(originals)), f'Overlay: {preparation.label}'))
    _verify_backup(backup_dir, originals)
    if game_running():
        raise RuntimeError('Crimson Desert started during backup. Close it before changing overlays.')
    _verify_source_directories(root, preparation)
    _live._verify_observed_state(root, preparation.observed_state, 'after preparation')
    for relative, expected in preparation.before:
        path = _live._target(root, relative)
        if not _file_matches_bytes(path, expected):
            raise OverlayConflict(f'{relative} changed after preparation. Refresh and prepare again.')
    for relative, expected in preparation.source_stamps:
        path = _live._target(root, relative)
        if not path.is_file() or tuple(_live._stamp(path)) != expected:
            raise OverlayConflict(f'The source archive {relative} changed after preparation.')
    writes = dict(preparation.writes)
    _verify_source_content(preparation, stop_event)
    recovery = OverlayTargetRecovery(root, {_live._target(root, relative): payload_digest(previous) for relative, previous in preparation.before}, backup_dir=backup_dir, restore_backup=restore_backup, stop_event=stop_event)
    try:
        for relative, payload in preparation.writes:
            if relative == 'meta/0.papgt':
                continue
            raise_if_cancelled(stop_event, 'Overlay change cancelled.')
            path = _live._target(root, relative)
            recovery.write(path, payload, atomic_write_bytes)
            if not _file_matches_bytes(path, payload):
                raise RuntimeError(f'Staged overlay bytes differ from the preparation: {relative}')
        if preparation.paths:
            pamt = _live._target(root, preparation.directory_name + '/0.pamt')
            actual = tuple(sorted((str(e.path).lower() for e in parse_archive_pamt(pamt))))
            if actual != preparation.paths:
                raise RuntimeError('Staged overlay paths differ from the prepared archive.')
        raise_if_cancelled(stop_event, 'Overlay change cancelled before publication.')
        mount_path, mount_payload = (_live._target(root, 'meta/0.papgt'), writes['meta/0.papgt'])
        recovery.write(mount_path, mount_payload, atomic_write_bytes)
        for relative in preparation.deletes:
            recovery.unlink(_live._target(root, relative))
        recovery.committed()
    except BaseException as error:
        try:
            recovery.rollback()
        except Exception as rollback_error:
            raise RuntimeError(f'Overlay change failed; recovery requires backup {backup_dir}: {rollback_error}') from error
        raise
    directory = _live._target(root, preparation.directory_name)
    if not preparation.paths:
        try:
            directory.rmdir()
        except OSError:
            pass
    if on_log:
        on_log(f"Overlay {(preparation.action if preparation.removed_id else 'installed')}: {preparation.label}. {len(preparation.remaining_labels)} enabled. Backup: {backup_dir}")
    if preparation.removed_id:
        return OverlayRemovalResult(directory, preparation.label, len(preparation.remaining_labels), backup_dir, preparation.removed_id, preparation.action)
    return OverlayInstallResult(directory, preparation.pamt_checksum, len(preparation.paths), preparation.payload_bytes, preparation.carried_forward, backup_dir, preparation.paths)


# A test that patches a name the app still has (``monkeypatch.setattr(this_module,
# "resolve_items", ...)``) means the live function: the code above reads it from
# ``_live`` at call time, so the patch is forwarded there. pytest undoes a patch of
# a name it did not find in this module's own namespace by deleting it; that puts
# the live module's original value back.
_LIVE_ORIGINALS = {}


class _ForwardLiveNames(type(_live)):
    def __setattr__(self, name, value):
        shared = name in self.__dict__ and hasattr(_live, name) and self.__dict__[name] is getattr(_live, name)
        if shared or (name not in self.__dict__ and hasattr(_live, name)):
            # Also a name both modules import from the same place: patch both bindings.
            _LIVE_ORIGINALS.setdefault(name, getattr(_live, name))
            setattr(_live, name, value)
            if not shared:
                return
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if name not in self.__dict__ and hasattr(_live, name):
            if name in _LIVE_ORIGINALS:  # a second undo of the same name has nothing left to restore
                setattr(_live, name, _LIVE_ORIGINALS.pop(name))
        else:
            super().__delattr__(name)


import sys as _sys  # noqa: E402

_sys.modules[__name__].__class__ = _ForwardLiveNames

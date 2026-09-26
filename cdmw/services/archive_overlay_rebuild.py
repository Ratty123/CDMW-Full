"""Rebase owned changes onto today's mounted underlay without flattening install history."""
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.mod_compatibility import game_identity
from cdmw.core.papgt_format import parse_papgt, papgt_with_directory, serialize_papgt
from cdmw.domain.archives.overlay_merge import OverlayConflict, legacy_texture_baseline, merge_overlay_files
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services import archive_overlay_manager as owner
from cdmw.services.archive_overlay_install import OVERLAY_OWNER_MARKER, is_cdmw_overlay_directory


def prepare_overlay_rebuild(package_root, *, stop_event=None, on_log=None):
    root = Path(package_root).resolve()
    inventory = (root / owner.INDEX_PATH).read_bytes()
    state = owner._load_index(root)
    if state is None or not any(row['active'] or row.get('disabled') for row in state['layers']):
        raise ValueError('No installed overlay history is available to rebuild.')
    name = state['directory']
    mount = (root / 'meta/0.papgt').read_bytes()
    records = parse_papgt(mount)
    mounted = any(str(record.name) == name for record in records)
    observed = {owner.INDEX_PATH: inventory, 'meta/0.papgt': mount}
    # A missing/unmounted CDMW group is recoverable from journals. An occupied
    # or edited group is not permission to replace someone else's work.
    directory = root / name
    if directory.exists() and not is_cdmw_overlay_directory(directory):
        raise OverlayConflict(f'Archive {name} is no longer owned by CDMW. Restore or move it before rebuilding.')
    for path, expected in state.get('published', {}).items():
        if not path.startswith(name + '/'):
            continue
        target = owner._target(root, path)
        observed[path] = target.read_bytes() if target.is_file() else None
        if target.is_file() and owner._digest(observed[path]) != expected:
            raise OverlayConflict(f'{path} changed outside CDMW. Restore its backup before rebuilding.')
        if mounted and expected is not None and not target.is_file():
            raise OverlayConflict(f'{path} is missing from a mounted group. Restore its backup before rebuilding.')
    allowed = {'0.pamt', '0.paz', OVERLAY_OWNER_MARKER}
    if directory.exists() and any(path.name not in allowed for path in directory.iterdir()):
        raise OverlayConflict(f'Archive {name} contains unrecorded files. Rebuilding would hide their ownership.')

    layers, baseline, old_current, stamps = [], {}, {}, {}
    version = root / 'meta/0.paver'
    if version.is_file():
        stamps['meta/0.paver'] = owner._stamp(version)
    for layer in state['layers']:
        raise_if_cancelled(stop_event)
        journal = owner.overlay_journal_path(layer)
        stamps[journal] = owner._stamp(root / journal)
        changes = owner._unpack_changes(root, layer, {}, stop_event)
        layers.append((layer, changes))
        for path, change in changes.items():
            baseline.setdefault(path, change['before'])
    old_current.update(baseline)
    for layer, changes in layers:
        if layer['active']:
            old_current = merge_overlay_files({p: c['before'] for p, c in changes.items()},
                {p: c['after'] for p, c in changes.items()}, old_current)

    sources = {}
    state['sources'] = {}
    for record in records:
        if str(record.name) == name:
            continue
        group = owner._target(root, str(record.name))
        if is_cdmw_overlay_directory(group):
            raise OverlayConflict('Another CDMW archive group must be reviewed before rebuilding this set.')
        for pamt in sorted(group.glob('*.pamt')):
            raise_if_cancelled(stop_event)
            relative = pamt.relative_to(root).as_posix()
            stamps[relative] = owner._stamp(pamt)
            for entry in parse_archive_pamt(pamt):
                path = str(entry.path).lower()
                if path in baseline:
                    sources.setdefault(path, entry)
    current = {}
    for path in baseline:
        raise_if_cancelled(stop_event)
        if path == 'meta/0.pathc':
            target = root / path
            live = target.read_bytes() if target.is_file() else None
            observed[path] = live
            if live is not None and baseline[path] is not None:
                live = legacy_texture_baseline(baseline[path], live,
                    {p: (baseline[p], value) for p, value in old_current.items() if p.endswith('.dds')})
            current[path] = live
        else:
            entry = sources.get(path)
            if entry is not None:
                owner._remember_source(root, state, entry)
            current[path] = owner._read(entry) if entry is not None else None
    live_keys = set(owner._added_item_keys({path: {'before': None, 'after': value}
                                          for path, value in current.items()}))
    owned_keys = {key for layer in state['layers'] if layer['active'] or layer.get('disabled')
                  for key in layer['item_keys']}
    overlap = live_keys.intersection(owned_keys)
    if overlap:
        raise OverlayConflict('The current game or another mod already supplies owned item IDs: '
                              + ', '.join(map(str, sorted(overlap))) + '. Review those conflicts before rebuilding.')
    identity = game_identity(root, stop_event)
    pending = {'.cdmw/retired-overlays/' + uuid4().hex + '.json': inventory}
    for layer, changes in layers:
        raise_if_cancelled(stop_event)
        if on_log:
            on_log(f"Comparing owned changes: {layer['label']}…")
        before = {path: current[path] for path in changes}
        if layer['active'] or layer.get('disabled'):
            after = merge_overlay_files({p: c['before'] for p, c in changes.items()},
                {p: c['after'] for p, c in changes.items()}, current)
        else:
            after = current  # Removed history remains visible only in the archived inventory.
        rebased = {path: {**change, 'before': before[path], 'after': after[path]}
                   for path, change in changes.items()}
        data = owner._pack_changes(rebased)
        layer['journal'] = '.cdmw/overlays/' + uuid4().hex + '.zip'
        layer['sha256'], layer['target_game'] = owner._digest(data), identity
        pending[layer['journal']] = data
        if layer['active']:
            current = after
    prepared = owner._compose(root, state, pending, 'Installed overlays', 'rebuild', stop_event, on_log)
    before = dict(prepared.before)
    if any(before.get(path) != value for path, value in observed.items()):
        raise OverlayConflict('The installed set changed during comparison. Refresh and compare again.')
    stamps.update(dict(prepared.source_stamps))
    for path, stamp in stamps.items():
        if owner._stamp(root / path) != list(stamp):
            raise OverlayConflict(f'{path} changed during comparison. Compare again.')
    writes = dict(prepared.writes)
    if prepared.paths:
        # Ordinary replacement retains mount position. A reviewed rebase must
        # put the newly composed shared tables ahead of the sources it merged.
        underlay_mount = serialize_papgt([record for record in records if str(record.name) != name], header=mount[:12])
        writes['meta/0.papgt'] = papgt_with_directory(underlay_mount, name, prepared.pamt_checksum, first=True)
    return replace(prepared, action='rebuild', writes=tuple(writes.items()),
                   source_stamps=tuple((p, tuple(s)) for p, s in stamps.items()))

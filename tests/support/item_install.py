"""Retired install code from cdmw.services.independent_item_install, kept for tests only (decision 39)."""

# CDMW never installs into the game. Tests use this on owned game folders made in the
# test, to build the state the live code reads. Names the app still has are read from
# cdmw.services.independent_item_install at call time (``_live``), so patching them there reaches this code.

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from itertools import chain
import json
from pathlib import Path
import re
from cdmw import constants
from cdmw.core.archive_format import calculate_pa_checksum, parse_archive_pamt
from tests.support.fixture_writes import atomic_binary_writer, atomic_write_bytes
from cdmw.core.papgt_format import read_papgt_directories
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.archives.overlay_merge import _table
from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.domain.new_item.allocation import DEFAULT_ITEM_KEY_RANGE
from cdmw.domain.new_item.compilation import compiler_stamp, validate_compiler_stamp
from cdmw.domain.new_item.compilation_storage import read_compilation
from cdmw.services.independent_mod_package import has_legacy_item, package_operations, package_logical_size
from cdmw.services.independent_texture_package import lower_texture_operations, package_texture_requirements
from cdmw.domain.new_item.independent import IdentityBindings, IndependentItemError, IndependentItemInstallPlan, package_id
from cdmw.domain.new_item.rules import has_errors
import tests.support.overlay_manager as overlays
from cdmw.services.independent_item_package import (
    MAX_MANIFEST, MAX_TOTAL, PackageReadCache, canonical, dependency_refusal, digest, dlc_content, package_bytes, package_metadata, pinned_digests, read_package, stock_snapshot, unpack_recipe, virtual_path,
)
from cdmw.services.new_item_planning import build_plan
from cdmw.services.new_item_service import NewItemService
from cdmw.services.application_shutdown_service import archive_write_scope
from cdmw.services.installation_lane import serialized_installation
from tests.support.overlay_recovery import OverlayTargetRecovery, payload_digest
from cdmw.services.independent_item_compatibility import (
    external_mods, reserved_external_keys, check_package_dependencies,
)

import cdmw.services.independent_item_install as _live


def __getattr__(name):
    return getattr(_live, name)


def retained_package_recovery(root, state, *, stop_event=None, on_log=None):
    """Keep generic overlay recovery within each installed package's contract."""
    root = Path(root).resolve()
    observed = {_live.REGISTRY_PATH: overlays._target(root, _live.REGISTRY_PATH).read_bytes()}
    registry = _live.load_registry(root)
    snapshot = stock_snapshot(root, stop_event=stop_event, on_log=on_log)
    external = external_mods(root, state, stop_event=stop_event, snapshot=snapshot)
    for layer in state['layers']:
        identity = layer.get('independent_identity')
        if not identity or not (layer['active'] or layer.get('disabled')):
            continue
        row = registry['items'][identity]
        relative = f".cdmw/independent-items/{identity}-{row['digest']}.cditem"
        path = overlays._target(root, relative)
        if path.stat().st_size > MAX_TOTAL + MAX_MANIFEST:
            raise IndependentItemError('The retained recovery package exceeds the supported size.')
        data = path.read_bytes()
        package = read_package(data, stop_event=stop_event)
        if package.identity != identity or package.digest != row['digest']:
            raise IndependentItemError('The retained recovery package has changed outside CDMW.')
        _live._check_dependencies(package, snapshot, stop_event)
        changes = overlays._unpack_changes(root, layer, {}, stop_event)
        check_package_dependencies(package, snapshot, external, changes, stop_event=stop_event)
        observed[relative] = data
    revision = snapshot.provenance.capture()
    revision.validate(stop_event)
    stamps = _live._game_source_stamps(root, revision)
    external.validate(stop_event)
    for path, stamp in external.tracker.capture().files:
        if path.suffix in ('.pamt', '.paz'):
            stamps[path.relative_to(root).as_posix()] = list(stamp)
    return (observed, stamps)


def prepare_install(sources, root, *, folders=(), rebuild=False, stop_event=None, on_log=None, read_entry=None):
    result = _live.resolve_items(sources, root, folders=folders, rebuild=rebuild, stop_event=stop_event, on_log=on_log, read_entry=read_entry)
    root, state, pending, decoded, registry = (result.root, result.state, result.pending, result.decoded, result.registry)
    from cdmw.services.independent_item_compilation import contribution_record
    locks = {package.identity: contribution_record(package, changes, result) for package, changes in result.contributions}
    for package, changes in result.contributions:
        row = registry['items'][package.identity]
        layer = overlays._add_layer(state, pending, package.title, changes, item_keys=tuple(row['values'].get('iteminfo', {}).values()))
        layer.update(independent_identity=package.identity, independent_digest=package.digest, independent_bindings=row['binding_hash'], independent_compiler=compiler_stamp(), independent_compilation=locks[package.identity], independent_operations=package_operations(package), independent_textures=package_texture_requirements(package))
        row['layer'] = layer['id']
        decoded[layer['id']] = changes
    if canonical(registry) == result.registry_before and (not result.external.paths):
        return IndependentItemInstallPlan(None, result.rows, ('All selected items are already installed.',))
    _live._validate_registry(registry)
    pending[_live.REGISTRY_PATH] = canonical(registry)
    preparation = overlays._compose(root, state, pending, 'Independent items', None, stop_event, on_log, decoded=decoded, independent_context=(result.external, result.baseline))
    preparation = overlays._pin_preparation(preparation, result.observed, error_type=IndependentItemError)
    if all((dict(preparation.before).get(path) == value for path, value in preparation.writes)) and (not preparation.deletes):
        return IndependentItemInstallPlan(None, result.rows, ('All selected items are already installed.',))
    return IndependentItemInstallPlan(preparation, result.rows, (*tuple((f'{status}: {title}' + (f' (item {key})' if key is not None else ' (existing game data)') for _, title, key, status in result.rows)), *result.summary))


def prepare_rebuild(identity, root, *, stop_event=None, on_log=None):
    """Recompile a retained physical package, preserving its reserved identities."""
    root = Path(root).resolve()
    observed = overlays._observe_state(root)
    registry = _live.load_registry(root)
    row = registry['items'].get(package_id(identity))
    state = overlays._load_index(root)
    layer = next((item for item in (state or {}).get('layers', ()) if row and item['id'] == row['layer'] and item['active']), None)
    if layer is None:
        raise IndependentItemError('Select an installed physical item to rebuild.')
    raise_if_cancelled(stop_event)
    relative = f".cdmw/independent-items/{identity}-{row['digest']}.cditem"
    path = overlays._target(root, relative)
    if not path.is_file() or path.stat().st_size > MAX_TOTAL + MAX_MANIFEST:
        raise IndependentItemError('The retained rebuild package is missing or too large.')
    data = path.read_bytes()
    package = read_package(data, stop_event=stop_event)
    if package.identity != identity or package.digest != row['digest']:
        raise IndependentItemError('The retained rebuild package has changed outside CDMW.')
    result = prepare_install([data], root, rebuild=True, stop_event=stop_event, on_log=on_log)
    preparation = overlays._pin_preparation(result.preparation, observed, error_type=IndependentItemError)
    summary = (*result.summary, 'Recompiled from the retained package with the current compiler. Existing item IDs and asset reservations are preserved.')
    return replace(result, preparation=preparation, summary=summary)


def prepare_remove(identity, root, *, stop_event=None, on_log=None):
    path = overlays._target(Path(root).resolve(), _live.REGISTRY_PATH)
    observed = path.read_bytes()
    registry = _live.load_registry(root)
    identities = (identity,) if isinstance(identity, str) else tuple(identity)
    rows = [registry['items'].get(package_id(key)) for key in identities]
    if not rows or any((row is None or row['layer'] is None for row in rows)):
        raise IndependentItemError('This item is not installed.')
    result = overlays.prepare_overlay_removal(root, tuple((row['layer'] for row in rows)), stop_event=stop_event, on_log=on_log)
    data = canonical(registry)
    if path.read_bytes() != observed:
        raise IndependentItemError('The identity profile changed during preparation. Refresh and prepare again.')
    return replace(result, writes=(*result.writes, (_live.REGISTRY_PATH, data)), before=(*result.before, (_live.REGISTRY_PATH, observed)))


@dataclass(frozen=True)
class IdentityDeletionResult:
    identity: str
    title: str
    backup_dir: Path
    identities: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdentityDeletionPreparation:
    package_root: Path
    identity: str
    title: str
    game_id: int | None
    writes: tuple[tuple[str, bytes], ...]
    observed_state: tuple[tuple[str, bytes | None], ...]
    items: tuple[tuple[str, str, int | None], ...] = ()


def prepare_identity_deletion(identity, root, *, stop_event=None):
    """Forget a removed reservation without changing archives or their baselines."""
    raise_if_cancelled(stop_event)
    root = Path(root).resolve()
    identities = tuple(dict.fromkeys((package_id(key) for key in ((identity,) if isinstance(identity, str) else identity))))
    if not identities:
        raise IndependentItemError('Select at least one saved identity.')
    observed = overlays._observe_state(root)
    registry = _live.load_registry(root)
    rows = [registry['items'].get(key) for key in identities]
    if any((row is None for row in rows)):
        raise IndependentItemError('This saved identity no longer exists. Refresh the list.')
    state = overlays._load_index(root)
    from cdmw.services.virtual_loader_state import active_identities, load_profile
    if set(identities).intersection(active_identities(root)) or any((layer.get('independent_identity') in identities and (layer['active'] or layer.get('disabled')) for layer in (state or {}).get('layers', ()))):
        raise IndependentItemError('Remove this item from Mods and apply the changes before deleting its saved identity.')
    for key in identities:
        del registry['items'][key]
    writes = {_live.REGISTRY_PATH: canonical(_live._validate_registry(registry))}
    if state is not None:
        changed = False
        for layer in state['layers']:
            raise_if_cancelled(stop_event)
            if layer.get('independent_identity') in identities:
                for key in ('independent_identity', 'independent_digest', 'independent_bindings', 'independent_compiler', 'independent_compilation', 'independent_operations', 'independent_textures'):
                    layer.pop(key, None)
                changed = True
            elif 'independent_compilation' in layer:
                inputs = read_compilation(layer['independent_compilation'], state.get('compilation_contexts'))['inputs']
                if set(identities).intersection(inputs.get('links', {}).get('providers', {})):
                    if layer['active'] or layer.get('disabled'):
                        raise IndependentItemError('Another installed item retains this identity in its compilation. Rebuild or remove that item before deleting this identity.')
                    layer.pop('independent_compilation')
                    layer.pop('independent_compiler', None)
                    changed = True
        if changed:
            writes[overlays.INDEX_PATH] = overlays._inventory_bytes(state)
            overlays._check_inventory_capacity(writes[overlays.INDEX_PATH])
    load_profile(root, registry=registry)
    overlays._verify_observed_state(root, observed, 'during preparation', IndependentItemError)
    raise_if_cancelled(stop_event)
    items = tuple(((key, row['title'], row['values'].get('iteminfo', {}).get('item')) for key, row in zip(identities, rows)))
    return IdentityDeletionPreparation(root, identities[0], '\n'.join((row['title'] for row in rows)), items[0][2] if len(items) == 1 else None, tuple(writes.items()), observed, items)


@archive_write_scope()
@serialized_installation(lambda preparation, **_kwargs: getattr(preparation, 'package_root', None))
def apply_identity_deletion(preparation, *, confirmed, mutations, game_running=None, stop_event=None, on_log=None):
    """Back up and publish only the reviewed local identity/ownership ledgers."""
    if not isinstance(preparation, IdentityDeletionPreparation):
        raise TypeError('Identity deletion requires a prepared change.')
    if not confirmed:
        raise PermissionError('Identity deletion requires explicit confirmation.')
    if game_running is None:
        from cdmw.services.new_item_service import game_is_running
        game_running = game_is_running

    def validate():
        raise_if_cancelled(stop_event)
        if game_running():
            raise RuntimeError('Close Crimson Desert before deleting saved identities.')
        current = prepare_identity_deletion(tuple((row[0] for row in preparation.items)) or (preparation.identity,), preparation.package_root, stop_event=stop_event)
        if current != preparation:
            raise IndependentItemError('The saved identities or installation changed. Refresh and review the deletion again.')
    validate()
    root = preparation.package_root
    observed = dict(preparation.observed_state)
    originals = {overlays._target(root, path): observed[path] for path, _ in preparation.writes}
    backup_dir = Path(mutations.backup_files(tuple(originals), description='Delete saved item identity: ' + preparation.title, on_log=on_log))
    overlays._verify_backup(backup_dir, originals)
    validate()
    recovery = OverlayTargetRecovery(root, {path: payload_digest(data) for path, data in originals.items()}, backup_dir=backup_dir, restore_backup=mutations.restore_backup, stop_event=stop_event)
    try:
        for relative, data in preparation.writes:
            recovery.write(overlays._target(root, relative), data, atomic_write_bytes)
        _live.load_registry(root)
        recovery.committed()
    except BaseException as error:
        try:
            recovery.rollback()
        except Exception as rollback_error:
            raise RuntimeError(f'Identity deletion failed; recovery requires backup {backup_dir}: {rollback_error}') from error
        raise
    if on_log:
        on_log(f'Deleted saved identity: {preparation.title}. Backup: {backup_dir}')
    return IdentityDeletionResult(preparation.identity, preparation.title, backup_dir, tuple((row[0] for row in preparation.items)) or (preparation.identity,))


def prepare_profile_import(source, root, *, stop_event=None, on_log=None):
    root = Path(root).resolve()
    observed_state = overlays._observe_state(root)
    incoming = _live._read_registry(Path(source))
    registry = _live.load_registry(root)
    if incoming['format'] == _live.MOD_PROFILE_FORMAT:
        registry['format'] = _live.MOD_PROFILE_FORMAT
    for identity, row in incoming['items'].items():
        raise_if_cancelled(stop_event)
        prior = registry['items'].get(identity)
        if prior:
            if any((prior[field] != row[field] for field in ('values', 'stem', 'paths'))):
                raise IndependentItemError('This profile would change a retained item identity. Existing save identities cannot be renumbered.')
        else:
            registry['items'][identity] = dict(row, layer=None)
    _live._validate_registry(registry)
    state, pending = overlays._state_for_edit(root, None, stop_event)
    for layer in state['layers']:
        if not (layer['active'] or layer.get('disabled')) or layer.get('independent_identity') in registry['items']:
            continue
        added = _live._added_keys(overlays._unpack_changes(root, layer, pending, stop_event))
        for row in registry['items'].values():
            if any((set(values.values()) & added.get(name, set()) for name, values in row['values'].items())):
                raise IndependentItemError('An installed overlay occupies an identity in the incoming profile.')
    pending[_live.REGISTRY_PATH] = canonical(registry)
    preparation = overlays._compose(root, state, pending, 'Import independent item identities', None, stop_event, on_log)
    return overlays._pin_preparation(preparation, observed_state, error_type=IndependentItemError)


def export_profile(root, destination, *, stop_event=None):
    """Write the identity registry as a ``.cdprofile`` (Item identities > Export, removed)."""
    from copy import deepcopy
    from tests.support.fixture_writes import atomic_binary_writer
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.domain.new_item.independent import IndependentItemError as _IndependentItemError
    from cdmw.services.independent_item_package import canonical as _canonical
    raise_if_cancelled(stop_event)
    value = deepcopy(_live.load_registry(root))
    for row in value['items'].values():
        row['layer'] = None
    destination = Path(destination).resolve()
    if destination.suffix.lower() != '.cdprofile':
        raise _IndependentItemError('Identity profiles use the .cdprofile extension.')
    data = _canonical(value)
    raise_if_cancelled(stop_event)
    with atomic_binary_writer(destination) as handle:
        handle.write(data)
        raise_if_cancelled(stop_event)
    return destination


def inventory(root):
    root = Path(root).resolve()
    registry = _live.load_registry(root)
    state = overlays._load_index(root)
    layers = {layer['id']: layer for layer in (state or {}).get('layers', ())}
    from cdmw.services.virtual_loader_state import active_identities
    virtual = active_identities(root)
    return tuple((identity, row['title'], row['values'].get('iteminfo', {}).get('item'),
                  'Virtual profile' if identity in virtual else 'Installed' if layers.get(row['layer'], {}).get('active') else
                  'Disabled' if layers.get(row['layer'], {}).get('disabled') else 'Removed / reserved')
                 for identity, row in registry['items'].items())


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

"""Install-local identity reservations and reviewed composition of portable items.

Preparation is read-only. Publication uses the existing overlay transaction,
including its game-closed check, backup verification, rollback and write lane.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
from itertools import chain
import json
from pathlib import Path
import re

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.atomic_file import atomic_binary_writer, atomic_write_bytes
from cdmw.core.papgt_format import parse_papgt
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.archives.overlay_merge import _table
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.allocation import DEFAULT_ITEM_KEY_RANGE
from cdmw.domain.new_item.compilation import compiler_stamp, validate_compiler_stamp
from cdmw.domain.new_item.compilation_storage import read_compilation
from cdmw.services.independent_mod_package import has_legacy_item, package_operations, package_logical_size
from cdmw.services.independent_texture_package import lower_texture_operations, package_texture_requirements
from cdmw.domain.new_item.independent import IdentityBindings, IndependentItemError, IndependentItemInstallPlan, package_id
from cdmw.domain.new_item.rules import has_errors
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_package import (
    MAX_MANIFEST, MAX_TOTAL, canonical, digest, package_bytes, package_metadata, read_package, stock_snapshot, unpack_recipe, virtual_path,
)
from cdmw.services.new_item_planning import build_plan
from cdmw.services.new_item_service import NewItemService
from cdmw.services.application_shutdown_service import archive_write_scope
from cdmw.services.installation_lane import serialized_installation
from cdmw.services.overlay_target_recovery import OverlayTargetRecovery, payload_digest
from cdmw.services.independent_item_compatibility import (
    external_mods, reserved_external_keys, check_package_dependencies,
)

REGISTRY_PATH = '.cdmw/independent-items.json'
PROFILE_FORMAT = 'cdmw_independent_identity_profile_v1'
MOD_PROFILE_FORMAT = 'cdmw_mod_identity_profile_v2'
NAMESPACES = {'iteminfo', 'multichangeinfo', 'dropsetinfo', 'effect'}


def _empty():
    return {'format': PROFILE_FORMAT, 'items': {}}


def _binding_hash(identity, row):
    return digest(canonical({'identity': identity, **{key: row[key] for key in ('values', 'stem', 'paths')}}))


def _validate_registry(value):
    if not isinstance(value, dict) or set(value) != {'format', 'items'} or value['format'] not in (PROFILE_FORMAT, MOD_PROFILE_FORMAT) or not isinstance(value['items'], dict):
        raise IndependentItemError('Unsupported independent item identity profile.')
    occupied = {name: set() for name in NAMESPACES}
    stems, paths = set(), set()
    for identity, row in value['items'].items():
        package_id(identity)
        if not isinstance(row, dict) or set(row) != {'title', 'digest', 'values', 'stem', 'paths', 'layer', 'binding_hash'}:
            raise IndependentItemError('Invalid independent item reservation.')
        if not isinstance(row['title'], str) or not 1 <= len(row['title']) <= 256 or not isinstance(row['digest'], str) or not re.fullmatch('[0-9a-f]{64}', row['digest']):
            raise IndependentItemError('Invalid independent item metadata.')
        if row['layer'] is not None:
            package_id(row['layer'])
        if not isinstance(row['values'], dict) or set(row['values']) - NAMESPACES:
            raise IndependentItemError('Unsupported identity namespace.')
        if 'item' not in row['values'].get('iteminfo', {}):
            if value['format'] != MOD_PROFILE_FORMAT or row['values'] or row['stem'] or row['paths']:
                raise IndependentItemError('The item identity reservation is missing.')
        for namespace, symbols in row['values'].items():
            if not isinstance(symbols, dict) or any(not isinstance(s, str) or not s or len(s) > 128 for s in symbols):
                raise IndependentItemError('Invalid symbolic identity.')
            for key in symbols.values():
                if type(key) is not int or key not in DEFAULT_ITEM_KEY_RANGE or key in occupied[namespace]:
                    raise IndependentItemError('Conflicting or out-of-range identity reservations.')
                occupied[namespace].add(key)
        stem = row['stem']
        if not isinstance(stem, str) or stem and (not re.fullmatch('[a-z0-9_]{1,128}', stem) or stem in stems):
            raise IndependentItemError('Conflicting or invalid model identity.')
        if stem:
            stems.add(stem)
        if not isinstance(row['paths'], list) or len(row['paths']) > 4096 or len(set(row['paths'])) != len(row['paths']):
            raise IndependentItemError('Invalid asset reservations.')
        for path in row['paths']:
            virtual_path(path)
            if path in paths:
                raise IndependentItemError('Conflicting asset reservations.')
            paths.add(path)
        if row['binding_hash'] != _binding_hash(identity, row):
            raise IndependentItemError('An item identity mapping failed its checksum. Restore the matching identity backup before continuing.')
    if len(canonical(value)) > MAX_MANIFEST:
        raise IndependentItemError('The identity profile exceeds the supported size.')
    return value


def _read_registry(path):
    if path.stat().st_size > MAX_MANIFEST:
        raise IndependentItemError('The identity profile exceeds the supported size.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise IndependentItemError('Duplicate identity profile key.')
            result[key] = value
        return result
    try:
        return _validate_registry(json.loads(path.read_bytes(), object_pairs_hook=unique))
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise IndependentItemError(f'Cannot read identity profile: {exc}') from exc


def load_registry(root):
    root = Path(root).resolve()
    path = overlays._target(root, REGISTRY_PATH)
    state = overlays._load_index(root)
    registry = _read_registry(path) if path.is_file() else _empty()
    for layer in (state or {}).get('layers', ()):
        identity = layer.get('independent_identity')
        if identity:
            if 'independent_compiler' in layer:
                validate_compiler_stamp(layer['independent_compiler'])
            if 'independent_compilation' in layer:
                inputs = read_compilation(layer['independent_compilation'], state.get('compilation_contexts'))['inputs']
                locked = inputs['packages']
                if (inputs['scope'] != 'archive-contribution' or len(locked) != 1
                        or locked[0]['identity'] != identity or locked[0]['content'] != layer.get('independent_digest')
                        or inputs['compiler'] != layer.get('independent_compiler')
                        or inputs['allocations'].get(identity) != layer.get('independent_bindings')):
                    raise IndependentItemError('The installed compilation record disagrees with its ownership layer.')
                if 'links' in inputs:
                    from cdmw.domain.new_item.package_links import validate_link_bindings
                    validate_link_bindings(inputs['links'], registry['items'])
            row = registry['items'].get(identity)
            if row is None:
                raise IndependentItemError('An independent item reservation is missing. Restore the matching identity backup before continuing.')
            if (layer['active'] or layer.get('disabled') or row['layer'] == layer['id']) and (
                    row['layer'] != layer['id'] or row['digest'] != layer.get('independent_digest')
                    or row['binding_hash'] != layer.get('independent_bindings')):
                raise IndependentItemError('Independent item ownership and identity mappings disagree. Restore their matching backup before continuing.')
    from cdmw.services.virtual_loader_state import load_profile
    load_profile(root, registry=registry)
    return registry


def inventory(root):
    root = Path(root).resolve()
    registry = load_registry(root)
    state = overlays._load_index(root)
    layers = {layer['id']: layer for layer in (state or {}).get('layers', ())}
    from cdmw.services.virtual_loader_state import active_identities
    virtual = active_identities(root)
    return tuple((identity, row['title'], row['values'].get('iteminfo', {}).get('item'),
                  'Virtual profile' if identity in virtual else 'Installed' if layers.get(row['layer'], {}).get('active') else
                  'Disabled' if layers.get(row['layer'], {}).get('disabled') else 'Removed / reserved')
                 for identity, row in registry['items'].items())


def _added_keys(changes):
    result = {name: set() for name in NAMESPACES}
    for path, change in changes.items():
        name = path.rsplit('/', 1)[-1].split('.')[0]
        if name not in result or not path.endswith(('.staticinfobody', '.pabgb')):
            continue
        header = path.replace('.staticinfobody', '.staticinfoheader').replace('.pabgb', '.pabgh')
        if header not in changes:
            raise IndependentItemError('An installed table has no matching directory.')
        def keys(side):
            body, head = change[side], changes[header][side]
            return {int.from_bytes(key, 'little') for key, _ in _table(body, head)[1]} if body is not None and head is not None else set()
        result[name].update(keys('after') - keys('before'))
    return result


def _game_source_stamps(root, revision):
    # The transaction rewrites mount/texture metadata; its before-values own
    # those checks. Only immutable game inputs belong in persistent stamps.
    return {path.relative_to(root).as_posix(): list(stamp) for path, stamp in revision.files
            if stamp is not None and (path.suffix in ('.pamt', '.paz') or path == root / 'meta/0.paver')}


def _capture(plan, snapshot, root, state, pathc_before):
    changes = {}
    for path, stamp in _game_source_stamps(root, plan.source_revision).items():
        state['sources'].setdefault(path, stamp)
    for request in plan.patches:
        path = request.entry.path.lower()
        overlays._remember_source(root, state, request.entry)
        changes[path] = {'before': snapshot.payload(path), 'after': bytes(request.payload_data), 'flags': int(request.entry.flags), 'meta': False}
    for request in plan.additions:
        changes[request.path.lower()] = {'before': None, 'after': bytes(request.payload_data), 'flags': int(request.flags), 'meta': False}
    for write in plan.meta_files:
        changes[write.path] = {'before': pathc_before, 'after': bytes(write.payload_data), 'flags': 0, 'meta': True}
    return changes


def _external_paths(root, state, stop_event=None):
    paths = set()
    for record in parse_papgt(overlays._target(root, 'meta/0.papgt').read_bytes()):
        raise_if_cancelled(stop_event)
        name = record.name
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise IndependentItemError(f'Unsupported mounted archive folder for independent items: {name!r}.')
        shipped = len(name) == 4 and name.isascii() and name.isdigit() and int(name) < 36
        if shipped or name == state['directory']:
            continue
        for pamt in sorted(overlays._target(root, name).glob('*.pamt')):
            raise_if_cancelled(stop_event)
            paths.update(entry.path.lower() for entry in parse_archive_pamt(pamt))
    return paths


def _check_dependencies(package, snapshot, stop_event):
    for path, checksum in package.dependencies.items():
        raise_if_cancelled(stop_event)
        if not snapshot.has_entry(path) or digest(snapshot.payload(path)) != checksum:
            raise IndependentItemError(f'{package.title}: incompatible game dependency {path}. Use the matching game version or an updated package.')


def retained_package_recovery(root, state, *, stop_event=None, on_log=None):
    """Keep generic overlay recovery within each installed package's contract."""
    root = Path(root).resolve()
    observed = {REGISTRY_PATH: overlays._target(root, REGISTRY_PATH).read_bytes()}
    registry = load_registry(root)
    snapshot = stock_snapshot(root, stop_event=stop_event, on_log=on_log)
    external = external_mods(root, state, stop_event=stop_event, snapshot=snapshot)
    for layer in state['layers']:
        identity = layer.get('independent_identity')
        if not identity or not (layer['active'] or layer.get('disabled')):
            continue
        row = registry['items'][identity]
        relative = f'.cdmw/independent-items/{identity}-{row["digest"]}.cditem'
        path = overlays._target(root, relative)
        if path.stat().st_size > MAX_TOTAL + MAX_MANIFEST:
            raise IndependentItemError('The retained recovery package exceeds the supported size.')
        data = path.read_bytes()
        package = read_package(data, stop_event=stop_event)
        if package.identity != identity or package.digest != row['digest']:
            raise IndependentItemError('The retained recovery package has changed outside CDMW.')
        _check_dependencies(package, snapshot, stop_event)
        changes = overlays._unpack_changes(root, layer, {}, stop_event)
        check_package_dependencies(package, snapshot, external, changes, stop_event=stop_event)
        observed[relative] = data
    revision = snapshot.provenance.capture()
    revision.validate(stop_event)
    stamps = _game_source_stamps(root, revision)
    external.validate(stop_event)
    for path, stamp in external.tracker.capture().files:
        if path.suffix in ('.pamt', '.paz'):
            stamps[path.relative_to(root).as_posix()] = list(stamp)
    return observed, stamps


@dataclass
class ResolvedItemSet:
    root: Path
    observed: tuple
    state: dict
    pending: dict
    decoded: dict
    registry: dict
    registry_before: bytes
    baseline: object
    external: object
    rows: tuple
    contributions: tuple
    revisions: tuple
    summary: tuple
    links: dict | None = None


class _AssetHashes:
    """One lazy collision index per preparation, never a cross-request cache."""

    def __init__(self, paths):
        self._initial = paths
        self._hashes = {}
        self._reserved = set()

    def check(self, additions, reservations, stop_event=None):
        if not additions:
            return
        from cdmw.core.pathc_format import pathc_checksum

        def reserve(paths):
            for index, path in enumerate(paths):
                if index % 256 == 0:
                    raise_if_cancelled(stop_event, 'Independent item preparation cancelled.')
                checksum = pathc_checksum(path)
                previous = self._hashes.setdefault(checksum, path)
                if previous != path:
                    # Retain ambiguity instead of choosing whichever path was last.
                    self._hashes[checksum] = None

        if self._initial is not None:
            paths = []
            for index, path in enumerate(self._initial):
                if index % 256 == 0:
                    raise_if_cancelled(stop_event, 'Independent item preparation cancelled.')
                paths.append(path)
            hashes = None
            if len(paths) >= 4096:
                from cdmw.core.archive_accelerator import path_checksums_native
                hashes = path_checksums_native(paths, stop_event=stop_event)
            if hashes is None:
                reserve(paths)
            else:
                for index, (path, checksum) in enumerate(zip(paths, hashes)):
                    if index % 256 == 0:
                        raise_if_cancelled(stop_event, 'Independent item preparation cancelled.')
                    previous = self._hashes.setdefault(checksum, path)
                    if previous != path:
                        self._hashes[checksum] = None
            self._initial = None
        reserve(reservations - self._reserved)
        self._reserved.update(reservations)
        for path in sorted(additions):
            raise_if_cancelled(stop_event, 'Independent item preparation cancelled.')
            checksum = pathc_checksum(path)
            if checksum in self._hashes and self._hashes[checksum] != path:
                raise IndependentItemError(f'An asset hash collides with another resource: {path}.')
            self._hashes[checksum] = path
        self._reserved.update(additions)


def _semantic_inputs(sources, folders=(), *, stop_event=None):
    """Admit opaque exports before treating any selected input as game bytes."""
    from cdmw.core.mod_compatibility import read_semantic_export
    expanded, ordinary, exports = [], [], []
    retained_bytes = 0

    def add_export(semantic):
        nonlocal retained_bytes
        retained_bytes += (sum(len(raw) for raw in semantic.packages)
                           + sum(len(data) for _, data, _ in semantic.files)
                           + sum(len(data) for data in semantic.originals.values() if data is not None)
                           + len(canonical(semantic.bindings)) + len(canonical(semantic.witnesses)))
        if retained_bytes > MAX_TOTAL or len(expanded) + len(semantic.packages) > 128:
            raise IndependentItemError('The selected semantic exports exceed the package or comparison size limit.')
        exports.append(semantic)
        expanded.extend(semantic.packages)

    for source in sources:
        raise_if_cancelled(stop_event)
        semantic = read_semantic_export(source, stop_event=stop_event) if isinstance(source, (str, Path)) else None
        if semantic is None:
            expanded.append(source)
        else:
            add_export(semantic)
    for folder in folders:
        raise_if_cancelled(stop_event)
        semantic = read_semantic_export(folder, stop_event=stop_event)
        if semantic is None:
            ordinary.append(folder)
        else:
            add_export(semantic)
    return tuple(expanded), tuple(ordinary), tuple(exports)


def _semantic_bindings(registry, exports):
    """Import exact reservations; relocating compiled identities is unsupported."""
    for semantic in exports:
        incoming = semantic.bindings
        if incoming['format'] == MOD_PROFILE_FORMAT:
            registry['format'] = MOD_PROFILE_FORMAT
        for identity, row in incoming['items'].items():
            previous = registry['items'].get(identity)
            if previous is not None:
                if any(previous[field] != row[field] for field in ('values', 'stem', 'paths')):
                    raise IndependentItemError(f'{identity}: semantic export bindings differ from retained identities; relocation is unsupported.')
            else:
                registry['items'][identity] = deepcopy(row)
    _validate_registry(registry)


def resolve_items(sources, root, *, target='archive', folders=(), rebuild=False, stop_event=None, on_log=None, read_entry=None, on_progress=None):
    """Resolve recipes without publishing archives, identities, or ownership.

    Contributions have no overlay IDs. The selected deployment backend owns
    publication and its own ownership representation.
    """
    if target not in ('archive', 'virtual'):
        raise ValueError('Unknown item deployment target.')
    def progress(value, detail):
        raise_if_cancelled(stop_event, 'Independent item preparation cancelled.')
        if on_progress:
            on_progress(value, 100, detail)
    progress(0, 'Checking item packages…')
    root = Path(root).resolve()
    sources, folders, semantic_exports = _semantic_inputs(sources, folders, stop_event=stop_event)
    observed_state = overlays._observe_state(root)
    def current_bytes(relative):
        path = overlays._target(root, relative)
        return path.read_bytes() if path.is_file() else None
    if (not sources and target == 'archive') or len(sources) > 128:
        raise IndependentItemError('Select between one and 128 item packages.')
    packages = {}
    shared_blobs = {}
    total_size = 0
    for source in sources:
        package = read_package(source, stop_event=stop_event)
        old = packages.get(package.identity)
        if old and old.digest != package.digest:
            raise IndependentItemError('A batch contains two different versions of the same item. Select one version.')
        if old is None:
            total_size += package_logical_size(package)
            if total_size > MAX_TOTAL:
                raise IndependentItemError('The selected packages exceed the batch size limit. Import a smaller batch.')
        # Every package has already passed its own checksum/size validation.
        # Reuse only equal immutable bytes within this preparation; identities,
        # blob mappings, logical budgets and installed asset paths remain separate.
        package = replace(package, blobs={key: shared_blobs[key]
            if key in shared_blobs and shared_blobs[key] == data else data
            for key, data in package.blobs.items()})
        shared_blobs.update(package.blobs)
        packages[package.identity] = package
    registry = load_registry(root)
    from cdmw.services.virtual_loader_state import active_identities
    virtual_items = active_identities(root)
    if target == 'archive' and set(packages) & virtual_items:
        raise IndependentItemError('Remove the item from the virtual profile before installing it into archives.')
    registry_before = canonical(registry)
    retained_identities = set(registry['items'])
    _semantic_bindings(registry, semantic_exports)
    state, pending = overlays._state_for_edit(root, None, stop_event)
    from cdmw.domain.new_item.package_links import resolve_package_graph, bind_package_graph
    from cdmw.services.independent_mod_package import retained_active_packages
    retained = retained_active_packages(root, state['layers'], pending, exclude=packages, stop_event=stop_event) if target == 'archive' else ()
    package_graph = resolve_package_graph(chain(packages.values(), retained), stop_event=stop_event)
    decoded = {layer['id']: overlays._unpack_changes(root, layer, pending, stop_event) for layer in state['layers']}
    service = NewItemService()
    progress(7, 'Reading game data…')
    snapshot = stock_snapshot(root, service=service, read_entry=read_entry, stop_event=stop_event, on_log=on_log,
                              overlay_changes=decoded.values())
    for semantic in semantic_exports:
        semantic.validate_source(snapshot, root, stop_event=stop_event)
    pathc_path = overlays._target(root, 'meta/0.pathc')
    pathc_before = pathc_path.read_bytes() if pathc_path.is_file() else None
    for changes in decoded.values():
        if 'meta/0.pathc' in changes:
            pathc_before = changes['meta/0.pathc']['before']
            break
    baseline = snapshot
    baseline_dependencies = snapshot.provenance.capture().payloads
    # Inspect all mounted external files, irrespective of priority. Adding our
    # composed table must never silently hide a manager's replacement.
    # Keep the existing name/layout validation and public error type.
    _external_paths(root, state, stop_event)
    progress(22, 'Comparing external mods…')
    external = external_mods(root, state, folders=folders, read_entry=read_entry, stop_event=stop_event, snapshot=snapshot)
    for semantic in semantic_exports:
        # Retain the digest of the parsed container through final publication.
        if semantic.source is not None:
            external.tracker.pin_index(semantic.source, semantic.artifact_digest, stop_event)
            if semantic.folder is not None:
                from cdmw.services.mod_merge_service import _inventory
                external.inventories.append((semantic.folder, _inventory(semantic.folder, stop_event)))
    if target == 'virtual' and any(row.status == 'Unknown' for row in external.findings):
        raise IndependentItemError('; '.join(row.detail for row in external.findings))
    external_paths = external.paths
    asset_hashes = _AssetHashes(chain(baseline.entries, external_paths))
    external_keys = reserved_external_keys(external, snapshot, stop_event=stop_event)
    compatibility = []
    rows = []
    contributions = []
    compiled = {}
    revisions = []
    for item_index, (identity, package) in enumerate(packages.items()):
        progress(30 + 70 * item_index // max(1, len(packages)),
                 f'Preparing {item_index + 1} of {len(packages)}: {package.title}')
        raise_if_cancelled(stop_event, 'Independent item preparation cancelled.')
        snapshot = baseline.discovery_view()
        for dependency in baseline_dependencies:
            snapshot.payload(dependency.entry.path)
        prior = registry['items'].get(identity)
        previous_layer = next((layer for layer in state['layers'] if prior and layer['id'] == prior['layer']), None)
        if target == 'virtual' and previous_layer and (previous_layer['active'] or previous_layer.get('disabled')):
            raise IndependentItemError(f'{package.title}: remove the installed contribution before using this item in a virtual profile. Its identity will be retained.')
        _check_dependencies(package, snapshot, stop_event)
        if previous_layer and previous_layer['active'] and prior['digest'] == package.digest and not rebuild:
            if previous_layer.get('independent_compiler') != compiler_stamp() or 'independent_compilation' not in previous_layer:
                raise IndependentItemError(f'{package.title}: the installed compiler is different or unrecorded. Use Rebuild selected item to regenerate it while retaining its IDs.')
            check_package_dependencies(package, snapshot, external, decoded[previous_layer['id']], stop_event=stop_event)
            compiled[identity] = (package, decoded[previous_layer['id']])
            rows.append((identity, package.title, prior['values'].get('iteminfo', {}).get('item'), 'Already installed'))
            continue
        if previous_layer:
            if any(layer['active'] and previous_layer['id'] in layer['dependencies'] for layer in state['layers']):
                raise IndependentItemError('Another installed overlay depends on this item. Remove that dependent overlay before updating it.')
            previous_layer.update(active=False, disabled=False)
        reserved = {name: set(external_keys[name]) for name in NAMESPACES}
        reserved_paths = set()
        stems = {Path(path).stem for path in external_paths if path.endswith(('.pac', '.prefab'))}
        for other_id, other in registry['items'].items():
            if other_id == identity:
                continue
            for name, values in other['values'].items():
                reserved[name].update(values.values())
            reserved_paths.update(other['paths'])
            if other['stem']:
                stems.add(other['stem'])
        for layer in state['layers']:
            if layer is previous_layer or layer.get('independent_identity') == identity:
                continue
            if layer['active'] or layer.get('disabled'):
                changes = decoded[layer['id']]
                for name, keys in _added_keys(changes).items():
                    reserved[name].update(keys)
                reserved_paths.update(path for path, change in changes.items() if change['before'] is None)
                for path, change in changes.items():
                    if change['before'] is None:
                        stem = Path(path).stem
                        if path.endswith(('.pac', '.prefab')):
                            stems.add(stem)
                        for match in re.finditer(r'_n([0-9]{5})(?:[a-z0-9]*)(?:\.|$)', path):
                            reserved['effect'].add(1_900_000 + int(match.group(1)))
        bindings = IdentityBindings(identity, deepcopy(prior['values']) if prior else {}, reserved,
                                    prior['stem'] if prior else '', tuple(prior['paths']) if prior else ())
        key, changes, added_paths = None, {}, set()
        if has_legacy_item(package):
            spec, model, variants, icon_data = unpack_recipe(package)
            key = bindings.allocate('iteminfo', 'item', snapshot.rows)
            allocated = service.allocate(replace(spec, item_key=key, internal_name='CDI_' + identity, stem=bindings.stem or None),
                                         snapshot, reserved_keys=reserved['iteminfo'], reserved_stems=stems)
            if allocated.stem:
                if allocated.stem in stems:
                    raise IndependentItemError('The reserved model identity is occupied.')
                bindings.stem = allocated.stem
            issues = service.validate(allocated, snapshot)
            if has_errors(issues):
                raise IndependentItemError('; '.join(issue.message for issue in issues if issue.is_error))
            icon = None
            if icon_data is not None:
                from cdmw.core.item_icon_addition import NewItemIcon, icon_target_path
                from cdmw.services.new_item_planning import planned_icon_string
                name = planned_icon_string(allocated, snapshot)
                icon = NewItemIcon(name, stringinfo_key(name), icon_target_path(name), icon_data, None, None)
            plan = build_plan(allocated, snapshot, model=model, variant_models=variants, icon=icon,
                              reserved_item_keys=reserved['iteminfo'], identity_bindings=bindings,
                              capture_independent=True, stop_event=stop_event, on_log=on_log)
            # A prepared recipe must not acquire an undeclared dependency at install.
            if any(row.entry.path.lower() not in package.dependencies for row in plan.source_revision.payloads):
                raise IndependentItemError('The package has an incomplete game dependency graph.')
            plan.source_revision.validate(stop_event)
            revisions.append(plan.source_revision)
            added_paths = {virtual_path(request.path.lower()) for request in plan.additions}
            changes = _capture(plan, snapshot, root, state, pathc_before)
        elif prior and prior['values']:
            raise IndependentItemError('An existing item package cannot discard its owned objects by becoming a record-edit package.')
        else:
            registry['format'] = MOD_PROFILE_FORMAT
        from cdmw.services.independent_item_operations import lower_field_operations
        changes = lower_field_operations(package, snapshot, changes, stop_event=stop_event)
        changes = lower_texture_operations(package, snapshot, changes, stop_event=stop_event)
        if package_texture_requirements(package):
            revisions.append(snapshot.provenance.capture())
        if added_paths & (reserved_paths | external_paths):
            raise IndependentItemError('An owned asset name is already reserved by another item or mod. The package cannot be installed without changing its identity.')
        progress(30 + (70 * item_index + 45) // max(1, len(packages)), 'Checking asset identity collisions…')
        asset_hashes.check(added_paths, reserved_paths, stop_event)
        if any(path.endswith('.dds') for path in added_paths) and snapshot.pathc is None:
            raise IndependentItemError('This game has no verified texture registry for the new icon or textures.')
        findings = check_package_dependencies(package, snapshot, external, changes, stop_event=stop_event)
        compatibility.extend(f'{", ".join(finding.mods)}: {finding.path}: {finding.detail}' for finding in findings)
        contributions.append((package, changes))
        compiled[identity] = (package, changes)
        bindings.paths = tuple(sorted(set(bindings.paths) | added_paths))
        registry['items'][identity] = {'title': package.title, 'digest': package.digest, 'values': bindings.values,
                                      'stem': bindings.stem, 'paths': list(bindings.paths), 'layer': None}
        row = registry['items'][identity]
        row['binding_hash'] = _binding_hash(identity, row)
        cache_path = f'.cdmw/independent-items/{identity}-{package.digest}.cditem'
        cached = current_bytes(cache_path)
        if cached is not None:
            existing = read_package(cached, stop_event=stop_event)
            if existing.identity != identity or existing.digest != package.digest:
                raise IndependentItemError('The retained recovery package has changed outside CDMW.')
        pending[cache_path] = cached if cached is not None else package_bytes(package, stop_event=stop_event)
        known = identity in retained_identities
        status = 'Rebuild' if rebuild and known and prior['digest'] == package.digest else 'Update' if known else 'Install'
        rows.append((identity, package.title, key, status))
    _validate_registry(registry)
    links = bind_package_graph(package_graph, registry['items'])
    if semantic_exports:
        from cdmw.services.independent_item_compatibility import validate_semantic_recomposition
        validate_semantic_recomposition(semantic_exports, compiled, registry, stop_event=stop_event)
    progress(100, 'Item identities and dependencies verified.')
    return ResolvedItemSet(root, observed_state, state, pending, decoded, registry, registry_before,
        baseline, external, tuple(rows), tuple(contributions), tuple(revisions), tuple(dict.fromkeys(compatibility)), links)


def prepare_install(sources, root, *, folders=(), rebuild=False, stop_event=None, on_log=None, read_entry=None):
    result = resolve_items(sources, root, folders=folders, rebuild=rebuild, stop_event=stop_event, on_log=on_log, read_entry=read_entry)
    root, state, pending, decoded, registry = result.root, result.state, result.pending, result.decoded, result.registry
    from cdmw.services.independent_item_compilation import contribution_record
    locks = {package.identity: contribution_record(package, changes, result) for package, changes in result.contributions}
    for package, changes in result.contributions:
        row = registry['items'][package.identity]
        layer = overlays._add_layer(state, pending, package.title, changes, item_keys=tuple(row['values'].get('iteminfo', {}).values()))
        layer.update(independent_identity=package.identity, independent_digest=package.digest,
                     independent_bindings=row['binding_hash'], independent_compiler=compiler_stamp(),
                     independent_compilation=locks[package.identity], independent_operations=package_operations(package),
                     independent_textures=package_texture_requirements(package))
        row['layer'] = layer['id']
        decoded[layer['id']] = changes
    if canonical(registry) == result.registry_before and not result.external.paths:
        return IndependentItemInstallPlan(None, result.rows, ('All selected items are already installed.',))
    _validate_registry(registry)
    pending[REGISTRY_PATH] = canonical(registry)
    preparation = overlays._compose(root, state, pending, 'Independent items', None, stop_event, on_log,
                                    decoded=decoded, independent_context=(result.external, result.baseline))
    preparation = overlays._pin_preparation(preparation, result.observed, error_type=IndependentItemError)
    if all(dict(preparation.before).get(path) == value for path, value in preparation.writes) and not preparation.deletes:
        return IndependentItemInstallPlan(None, result.rows, ('All selected items are already installed.',))
    return IndependentItemInstallPlan(preparation, result.rows,
        (*tuple(f'{status}: {title}' + (f' (item {key})' if key is not None else ' (existing game data)') for _, title, key, status in result.rows), *result.summary))


def prepare_rebuild(identity, root, *, stop_event=None, on_log=None):
    """Recompile a retained physical package, preserving its reserved identities."""
    root = Path(root).resolve()
    observed = overlays._observe_state(root)
    registry = load_registry(root)
    row = registry['items'].get(package_id(identity))
    state = overlays._load_index(root)
    layer = next((item for item in (state or {}).get('layers', ())
                  if row and item['id'] == row['layer'] and item['active']), None)
    if layer is None:
        raise IndependentItemError('Select an installed physical item to rebuild.')
    raise_if_cancelled(stop_event)
    relative = f'.cdmw/independent-items/{identity}-{row["digest"]}.cditem'
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
    path = overlays._target(Path(root).resolve(), REGISTRY_PATH)
    observed = path.read_bytes()
    registry = load_registry(root)
    identities = (identity,) if isinstance(identity, str) else tuple(identity)
    rows = [registry['items'].get(package_id(key)) for key in identities]
    if not rows or any(row is None or row['layer'] is None for row in rows):
        raise IndependentItemError('This item is not installed.')
    result = overlays.prepare_overlay_removal(root, tuple(row['layer'] for row in rows), stop_event=stop_event, on_log=on_log)
    # The registry is deliberately retained, including retired auxiliary keys.
    # Include it unchanged in the verified backup and stale-preparation boundary.
    data = canonical(registry)
    if path.read_bytes() != observed:
        raise IndependentItemError('The identity profile changed during preparation. Refresh and prepare again.')
    return replace(result, writes=(*result.writes, (REGISTRY_PATH, data)),
                   before=(*result.before, (REGISTRY_PATH, observed)))


def export_profile(root, destination, *, stop_event=None):
    raise_if_cancelled(stop_event)
    value = deepcopy(load_registry(root))
    for row in value['items'].values():
        row['layer'] = None
    destination = Path(destination).resolve()
    if destination.suffix.lower() != '.cdprofile':
        raise IndependentItemError('Identity profiles use the .cdprofile extension.')
    data = canonical(value)
    raise_if_cancelled(stop_event)
    with atomic_binary_writer(destination) as handle:
        handle.write(data)
        raise_if_cancelled(stop_event)
    return destination


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
    identities = tuple(dict.fromkeys(package_id(key) for key in ((identity,) if isinstance(identity, str) else identity)))
    if not identities:
        raise IndependentItemError('Select at least one saved identity.')
    observed = overlays._observe_state(root)
    registry = load_registry(root)
    rows = [registry['items'].get(key) for key in identities]
    if any(row is None for row in rows):
        raise IndependentItemError('This saved identity no longer exists. Refresh the list.')
    state = overlays._load_index(root)
    from cdmw.services.virtual_loader_state import active_identities, load_profile
    if set(identities).intersection(active_identities(root)) or any(
            layer.get('independent_identity') in identities and (layer['active'] or layer.get('disabled'))
            for layer in (state or {}).get('layers', ())):
        raise IndependentItemError('Remove this item from Mods and apply the changes before deleting its saved identity.')
    for key in identities:
        del registry['items'][key]
    writes = {REGISTRY_PATH: canonical(_validate_registry(registry))}
    if state is not None:
        changed = False
        for layer in state['layers']:
            raise_if_cancelled(stop_event)
            if layer.get('independent_identity') in identities:
                # Keep the immutable payload journal and baseline/dependency history.
                # Detach the removed package's reservation and compilation metadata.
                for key in ('independent_identity', 'independent_digest', 'independent_bindings',
                            'independent_compiler', 'independent_compilation',
                            'independent_operations', 'independent_textures'):
                    layer.pop(key, None)
                changed = True
            elif 'independent_compilation' in layer:
                inputs = read_compilation(layer['independent_compilation'], state.get('compilation_contexts'))['inputs']
                if set(identities).intersection(inputs.get('links', {}).get('providers', {})):
                    if layer['active'] or layer.get('disabled'):
                        raise IndependentItemError('Another installed item retains this identity in its compilation. Rebuild or remove that item before deleting this identity.')
                    # Retired compilation graphs cannot retain a live binding to an
                    # explicitly forgotten identity. Other reservations stay intact.
                    layer.pop('independent_compilation')
                    layer.pop('independent_compiler', None)
                    changed = True
        if changed:
            writes[overlays.INDEX_PATH] = overlays._inventory_bytes(state)
            overlays._check_inventory_capacity(writes[overlays.INDEX_PATH])
    load_profile(root, registry=registry)
    overlays._verify_observed_state(root, observed, 'during preparation', IndependentItemError)
    raise_if_cancelled(stop_event)
    items = tuple((key, row['title'], row['values'].get('iteminfo', {}).get('item')) for key, row in zip(identities, rows))
    return IdentityDeletionPreparation(root, identities[0], '\n'.join(row['title'] for row in rows),
                                       items[0][2] if len(items) == 1 else None, tuple(writes.items()), observed, items)


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
        current = prepare_identity_deletion(tuple(row[0] for row in preparation.items) or (preparation.identity,),
                                            preparation.package_root, stop_event=stop_event)
        if current != preparation:
            raise IndependentItemError('The saved identities or installation changed. Refresh and review the deletion again.')

    validate()
    root = preparation.package_root
    observed = dict(preparation.observed_state)
    originals = {overlays._target(root, path): observed[path] for path, _ in preparation.writes}
    backup_dir = Path(mutations.backup_files(tuple(originals),
        description='Delete saved item identity: ' + preparation.title, on_log=on_log))
    overlays._verify_backup(backup_dir, originals)
    validate()
    recovery = OverlayTargetRecovery(root, {path: payload_digest(data) for path, data in originals.items()},
        backup_dir=backup_dir, restore_backup=mutations.restore_backup, stop_event=stop_event)
    try:
        # Once publication starts, finish both ledgers and verify them as a unit.
        for relative, data in preparation.writes:
            recovery.write(overlays._target(root, relative), data, atomic_write_bytes)
        load_registry(root)
        recovery.committed()
    except BaseException as error:
        try:
            recovery.rollback()
        except Exception as rollback_error:
            raise RuntimeError(f'Identity deletion failed; recovery requires backup {backup_dir}: {rollback_error}') from error
        raise
    if on_log:
        on_log(f'Deleted saved identity: {preparation.title}. Backup: {backup_dir}')
    return IdentityDeletionResult(preparation.identity, preparation.title, backup_dir,
                                  tuple(row[0] for row in preparation.items) or (preparation.identity,))


def prepare_profile_import(source, root, *, stop_event=None, on_log=None):
    root = Path(root).resolve()
    observed_state = overlays._observe_state(root)
    incoming = _read_registry(Path(source))
    registry = load_registry(root)
    if incoming['format'] == MOD_PROFILE_FORMAT:
        registry['format'] = MOD_PROFILE_FORMAT
    for identity, row in incoming['items'].items():
        raise_if_cancelled(stop_event)
        prior = registry['items'].get(identity)
        if prior:
            if any(prior[field] != row[field] for field in ('values', 'stem', 'paths')):
                raise IndependentItemError('This profile would change a retained item identity. Existing save identities cannot be renumbered.')
        else:
            registry['items'][identity] = dict(row, layer=None)
    _validate_registry(registry)
    state, pending = overlays._state_for_edit(root, None, stop_event)
    # Reservations must also agree with non-package overlays already installed.
    for layer in state['layers']:
        if not (layer['active'] or layer.get('disabled')) or layer.get('independent_identity') in registry['items']:
            continue
        added = _added_keys(overlays._unpack_changes(root, layer, pending, stop_event))
        for row in registry['items'].values():
            if any(set(values.values()) & added.get(name, set()) for name, values in row['values'].items()):
                raise IndependentItemError('An installed overlay occupies an identity in the incoming profile.')
    pending[REGISTRY_PATH] = canonical(registry)
    preparation = overlays._compose(root, state, pending, 'Import independent item identities', None, stop_event, on_log)
    return overlays._pin_preparation(preparation, observed_state, error_type=IndependentItemError)

"""Read-only comparison of independent items with mounted and prospective mods.

Foreign files remain foreign: composition uses their current contents as the
underlay, while journals continue to own only CDMW's additions. A second,
different replacement of one file is ambiguous without its original baseline.
"""
from dataclasses import dataclass, field
from pathlib import Path
import re

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.papgt_format import parse_papgt
from cdmw.domain.archives.overlay_merge import OverlayConflict, _table, merge_overlay_files, owned_item_references
from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.services.independent_item_package import MAX_BLOB, MAX_TOTAL, digest, unpack_recipe, virtual_path
from cdmw.services.mod_merge_service import _group, _inventory
from cdmw.services.new_item_provenance import SourceTracker


@dataclass(frozen=True)
class CompatibilityFinding:
    status: str
    mods: tuple[str, ...]
    path: str
    detail: str


@dataclass(frozen=True)
class ExternalModRevision:
    """Publication guards without the comparison's large parsed working set."""
    root: Path
    source_revision: object
    archives: tuple
    inventories: tuple

    def validate(self, stop_event=None):
        self.source_revision.validate(stop_event)
        for name, expected in self.archives:
            raise_if_cancelled(stop_event)
            if tuple(sorted(path.name for path in (self.root / name).glob('*.pamt'))) != expected:
                raise OverlayConflict(f'Archive folder changed: {name}. Scan again.')
        for folder, inventory in self.inventories:
            if _inventory(folder, stop_event) != inventory:
                raise OverlayConflict(f'Mod folder changed: {folder}. Scan again.')


@dataclass
class ExternalMods:
    root: Path
    directory: str
    tracker: SourceTracker
    providers: dict = field(default_factory=dict)
    inventories: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    cache: dict = field(default_factory=dict)
    total: int = 0
    archives: dict = field(default_factory=dict)
    snapshot: object = None
    merged: dict = field(default_factory=dict)

    @property
    def paths(self):
        return set(self.providers)

    def payload(self, path, stop_event=None):
        """Return one unambiguous version; never silently choose a load-order winner."""
        if path in self.merged:
            return self.merged[path]
        versions = {}
        for label, source in self.providers.get(path, ()):
            raise_if_cancelled(stop_event, 'Mod comparison cancelled.')
            key = (label, source.entry.identity if source.entry is not None else source.path)
            if key not in self.cache:
                if source.entry is not None:
                    if source.entry.orig_size > MAX_BLOB:
                        raise OverlayConflict(f'{label}: resource exceeds comparison size limit: {path}.')
                    value = self.tracker.read(source.entry)
                else:
                    self.tracker.pin_file(source.path)
                    if source.path.stat().st_size > MAX_BLOB:
                        raise OverlayConflict(f'{label}: resource exceeds comparison size limit: {path}.')
                    value = source.path.read_bytes()
                    self.tracker.pin_file(source.path)
                if len(value) > MAX_BLOB:
                    raise OverlayConflict(f'{label}: resource exceeds comparison size limit: {path}.')
                self.total += len(value)
                if self.total > MAX_TOTAL:
                    raise OverlayConflict('Mod comparison exceeds its memory limit. Compare fewer mods.')
                self.cache[key] = value
            versions.setdefault(self.cache[key], []).append(label)
        if len(versions) > 1:
            combined = self._additive_table(path, stop_event)
            if combined is not None:
                self.merged.update(combined)
                return combined[path]
            names = ', '.join(label for label, _ in self.providers[path])
            raise OverlayConflict(f'{names}: different replacements of {path}; their original baselines are required. Use Merge to compare recorded mod baselines.')
        return next(iter(versions), None)

    def _additive_table(self, path, stop_event):
        """Infer additions only when every shipped row is byte-identical and present."""
        paths = _group(path)
        if self.snapshot is None or len(paths) != 2 or not all(self.snapshot.has_entry(p) for p in paths):
            return None
        original = {p: self.snapshot.payload(p) for p in paths}
        layout, records = _table(original[paths[0]], original[paths[1]])
        baseline = dict(records)
        participants = self.labels(paths)
        current = dict(original)
        for label in participants:
            raise_if_cancelled(stop_event)
            values = {}
            for p in paths:
                sources = [source for owner, source in self.providers.get(p, ()) if owner == label]
                if len(sources) != 1:
                    return None
                source = sources[0]
                key = (label, source.entry.identity if source.entry is not None else source.path)
                if key not in self.cache:
                    # Read only this provider, without recursively resolving its peers.
                    single = ExternalMods(self.root, self.directory, self.tracker, {p: [(label, source)]})
                    self.cache[key] = single.payload(p, stop_event)
                    self.total += single.total
                    if self.total > MAX_TOTAL:
                        raise OverlayConflict('Mod comparison exceeds its memory limit. Compare fewer mods.')
                values[p] = self.cache[key]
            table, records = _table(values[paths[0]], values[paths[1]])
            present = dict(records)
            if ((table.key_width, table.header_size) != (layout.key_width, layout.header_size)
                    or any(present.get(key) != data for key, data in baseline.items())):
                return None
            current = merge_overlay_files(original, values, current)
        return current

    def labels(self, paths):
        return tuple(dict.fromkeys(label for path in paths for label, _ in self.providers.get(path, ())))

    def validate(self, stop_event=None):
        self.capture().validate(stop_event)

    def capture(self):
        return ExternalModRevision(self.root, self.tracker.capture(), tuple(self.archives.items()), tuple(self.inventories))

    def remember(self, state):
        from cdmw.services.archive_overlay_manager import _stamp
        for path, stamp in self.tracker.capture().files:
            if path.is_relative_to(self.root) and path.suffix in ('.pamt', '.paz'):
                relative = path.relative_to(self.root).as_posix()
                if stamp is None or _stamp(path) != list(stamp):
                    raise OverlayConflict(f'{relative} changed during comparison. Scan again.')
                state['sources'][relative] = list(stamp)


def external_mods(root, state, *, folders=(), read_entry=None, stop_event=None, snapshot=None):
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.services.new_item_mod_base import ModFolderPayload, mod_folder_payloads
    from cdmw.services.archive_overlay_manager import _target
    root = Path(root).resolve()
    result = ExternalMods(root, state['directory'], SourceTracker(read_entry or (lambda entry: read_archive_entry_data(entry)[0])))
    result.snapshot = snapshot
    mount = _target(root, 'meta/0.papgt')
    result.tracker.pin_file(mount)
    records = parse_papgt(mount.read_bytes())
    result.tracker.pin_file(mount)
    for record in records:
        raise_if_cancelled(stop_event)
        name = record.name
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise OverlayConflict(f'Unsupported mounted archive folder for independent items: {name!r}.')
        shipped = len(name) == 4 and name.isascii() and name.isdigit() and int(name) < 36
        if shipped or name == result.directory:
            continue
        group = _target(root, name)
        if group.is_dir():
            result.inventories.append((group, _inventory(group, stop_event)))
        pamts = sorted(group.glob('*.pamt'))
        result.archives[name] = tuple(path.name for path in pamts)
        for pamt in pamts:
            result.tracker.pin_file(pamt)
            for entry in parse_archive_pamt(pamt):
                path = virtual_path(entry.path.lower())
                if not Path(entry.paz_file).resolve().is_relative_to(group):
                    raise OverlayConflict(f'Archive resource escapes its mod folder: {name}.')
                result.providers.setdefault(path, []).append((name, ModFolderPayload(entry=entry)))
            result.tracker.pin_file(pamt)
    for raw in folders:
        folder = Path(raw).resolve()
        if folder.is_relative_to(root) or root.is_relative_to(folder):
            raise OverlayConflict('Select an external mod folder separate from the game installation.')
        inventory = _inventory(folder, stop_event)
        result.inventories.append((folder, inventory))
        label = str(folder)
        payloads = mod_folder_payloads(folder, stop_event=stop_event)
        for path, source in payloads.items():
            if path.startswith(('.cdmw/', '.cdloader/')):
                continue
            if source.entry is not None and (not Path(source.entry.pamt_path).resolve().is_relative_to(folder)
                                             or not Path(source.entry.paz_file).resolve().is_relative_to(folder)):
                raise OverlayConflict(f'Archive resource escapes its mod folder: {label}.')
            result.providers.setdefault(virtual_path(path), []).append((label, source))
        # Executable mods and patch instruction formats are not final file payloads.
        unknown = [name for name, *_ in inventory if Path(name).suffix.lower() in ('.asi', '.dll', '.json', '.zip', '.rar', '.7z', '.cditem')
                   and Path(name).name.lower() not in ('manifest.json', 'modinfo.json', 'new-item.json', 'cdmw-compatibility.json', 'cdmw-baseline.zip')]
        if unknown or not payloads:
            result.findings.append(CompatibilityFinding('Unknown', (label,), '',
                'This folder contains runtime code, patch instructions or no supported file payloads. Its effects cannot be certified by a file scan.'))
    return result


def reserved_external_keys(external, snapshot, *, stop_event=None):
    """Reserve observed numeric identities even when the external archive loses priority."""
    reserved = {name: set() for name in ('iteminfo', 'multichangeinfo', 'dropsetinfo', 'effect')}
    for paths in sorted({_group(path) for path in external.paths if len(_group(path)) == 2}):
        name = paths[0].rsplit('/', 1)[-1].split('.')[0]
        if name not in reserved:
            continue
        data = _external_table(external, paths, snapshot, stop_event)
        reserved[name].update(int.from_bytes(key, 'little') for key, _ in _table(data[paths[0]], data[paths[1]])[1])
    return reserved


def _external_table(external, paths, snapshot, stop_event):
    data = {p: external.payload(p, stop_event) for p in paths}
    # Resolving the second half can compose both halves. Do not retain an
    # earlier uncomposed body when only the providers' directories differed.
    data.update({p: external.merged[p] for p in paths if p in external.merged})
    for path in paths:
        other = next(p for p in paths if p != path)
        for label, source in external.providers.get(path, ()):
            if any(owner == label for owner, _ in external.providers.get(other, ())):
                continue
            key = (label, source.entry.identity if source.entry is not None else source.path)
            if not snapshot.has_entry(path) or external.cache[key] != snapshot.payload(path):
                raise OverlayConflict('Both table files are required to verify a changed table.')
        if data[path] is None:
            if not snapshot.has_entry(path):
                raise OverlayConflict(f'{paths[0]}: incomplete external table.')
            data[path] = snapshot.payload(path)
    return data


def _required_keys(package, snapshot, changes):
    """Protect complete referenced item/equipment/stat records, including transitive perks."""
    from cdmw.core.iteminfo_row import parse_iteminfo_row
    from cdmw.services.independent_mod_package import has_legacy_item
    if not has_legacy_item(package):
        return {'iteminfo': set(), 'equiptypeinfo': set(), 'statusinfo': set()}
    spec, *_ = unpack_recipe(package)
    required = {'iteminfo': set(), 'equiptypeinfo': set(), 'statusinfo': set()}
    pending = {int(spec.template_key)} | owned_item_references(changes)
    added_rows = []
    for path, change in changes.items():
        if path.rsplit('/', 1)[-1] not in ('iteminfo.staticinfobody', 'iteminfo.pabgb'):
            continue
        head = _group(path)[1]
        old = dict(_table(change['before'], changes[head]['before'])[1])
        added_rows.extend(parse_iteminfo_row(raw) for key, raw in _table(change['after'], changes[head]['after'])[1]
                          if key not in old)
    rows = list(added_rows)
    while pending:
        key = pending.pop()
        if key in required['iteminfo'] or key not in snapshot.rows:
            continue
        required['iteminfo'].add(key)
        row = snapshot.rows[key]
        rows.append(row)
        pending.update(row.socket_items)
        pending.update(key for key, _count, _extra in row.add_socket_materials)
        pending.update(price.item_key for price in row.price_list)
        pending.update(price.item_key for level in row.enchant_levels for price in level.buy_prices)
    for row in rows:
        if row.equip_type_key:
            required['equiptypeinfo'].add(row.equip_type_key)
        for level in row.enchant_levels:
            required['statusinfo'].update(stat.status_key for stat in level.stats)
            required['statusinfo'].update(level.level_stat_keys)
    return required


def check_package_dependencies(package, snapshot, external, changes, *, stop_event=None):
    """Keep the package's game version contract; narrow only verified external overlaps."""
    for path, change in changes.items():
        paths = _group(path)
        if len(paths) != 2 or path != paths[0] or not external.paths.intersection(paths):
            continue
        body, head = paths
        old = dict(_table(change['before'], changes[head]['before'])[1])
        owned = set(dict(_table(change['after'], changes[head]['after'])[1])) - set(old)
        if not owned:
            continue
        current = _external_table(external, paths, snapshot, stop_event)
        overlap = owned.intersection(key for key, _ in _table(current[body], current[head])[1])
        if overlap:
            raise OverlayConflict(f'{package.title}; {", ".join(external.labels(paths))}; {body}: '
                f'owned record {int.from_bytes(sorted(overlap)[0], "little")} is also supplied by another mod.')
        if body.rsplit('/', 1)[-1] in ('iteminfo.staticinfobody', 'iteminfo.pabgb'):
            from cdmw.core.iteminfo_row import parse_iteminfo_row
            names = {parse_iteminfo_row(raw).string_key.casefold() for _, raw in _table(current[body], current[head])[1]}
            for key, raw in _table(change['after'], changes[head]['after'])[1]:
                if key in owned and parse_iteminfo_row(raw).string_key.casefold() in names:
                    raise OverlayConflict(f'{package.title}; {", ".join(external.labels(paths))}; {body}: '
                        f'owned record {int.from_bytes(key, "little")} is also supplied by another mod.')
    required = _required_keys(package, snapshot, changes)
    done = set()
    findings = []
    for path, checksum in package.dependencies.items():
        raise_if_cancelled(stop_event)
        if not snapshot.has_entry(path) or digest(snapshot.payload(path)) != checksum:
            raise OverlayConflict(f'{package.title}: incompatible game dependency {path}. Use the matching game version or an updated package.')
        if path in done or path not in external.paths:
            continue
        paths = _group(path)
        labels = external.labels(paths)
        try:
            current = (_external_table(external, paths, snapshot, stop_event) if len(paths) == 2 else
                       {path: external.payload(path, stop_event)})
            original = {p: snapshot.payload(p) for p in paths}
            if current == original:
                detail = 'Identical game data; no conflicting changes.'
            elif len(paths) == 2:
                body, head = paths
                old_table, old = _table(original[body], original[head])
                new_table, new = _table(current[body], current[head])
                if (old_table.key_width, old_table.header_size) != (new_table.key_width, new_table.header_size):
                    raise OverlayConflict('Table layout changed.')
                name = body.rsplit('/', 1)[-1].split('.')[0]
                protected = required.get(name)
                if name in ('storeinfo', 'itemgroupinfo') and body in changes:
                    # The structured merger checks existing stock/members and additions.
                    protected = set()
                present = dict(new)
                for key, raw in old:
                    number = int.from_bytes(key, 'little')
                    if (protected is None or number in protected) and present.get(key) != raw:
                        raise OverlayConflict(f'Required {name} record {number} was changed or removed.')
                detail = 'Separate records can coexist; shared output will preserve this mod.'
            else:
                # Non-table dependencies keep their complete resource contract.
                # Additive localisation/prefab records are handled below by comparison.
                _check_collection_additions(path, original[path], current[path])
                detail = 'Existing dependency records are unchanged; additions can coexist.'
            findings.append(CompatibilityFinding('Compatible', labels, paths[0], detail))
        except RunCancelled:
            raise
        except (ValueError, RuntimeError, KeyError, IndexError) as error:
            raise OverlayConflict(f'{package.title}; {", ".join(labels)}; {paths[0]}: {error}') from error
        done.update(paths)
    return findings


def _check_collection_additions(path, before, after):
    if path.endswith('.paloc'):
        from cdmw.core.paloc_format import parse_paloc
        old, new = (parse_paloc(data).index() for data in (before, after))
    elif path.endswith('.pappt'):
        from cdmw.core.pappt_format import parse_pappt
        b, a = map(parse_pappt, (before, after))
        if (b.reserved, b.tag_prefix, b.head_records) != (a.reserved, a.tag_prefix, a.head_records):
            raise OverlayConflict('Required prefab metadata changed.')
        old, new = b.index(), a.index()
    else:
        raise OverlayConflict('A required resource changed; its reference boundary is not supported for merging.')
    for key, value in old.items():
        if new.get(key) != value:
            raise OverlayConflict(f'Required record {key} was changed or removed.')


def foreign_underlay(external, baseline, snapshot, *, stop_event=None):
    result = dict(baseline)
    for path in baseline:
        raise_if_cancelled(stop_event)
        if path == 'meta/0.pathc':
            continue
        # Rebased journals may include an older foreign underlay. Always observe
        # today's shipped/mounted source so removing a mod cannot resurrect it.
        result[path] = snapshot.payload(path) if snapshot.has_entry(path) else None
        if path not in external.paths:
            continue
        if baseline[path] is None:
            raise OverlayConflict(f'{", ".join(external.labels((path,)))}: an owned asset is already supplied by another mod: {path}.')
        paths = _group(path)
        if len(paths) == 2:
            result[path] = _external_table(external, paths, snapshot, stop_event)[path]
        else:
            result[path] = external.payload(path, stop_event)
    return result


def compose_underlay(root, state, pending, layers, baseline, *, stop_event=None, on_log=None, context=None):
    """Called by the existing overlay composer, including removal and recovery."""
    from cdmw.services.independent_item_package import stock_snapshot, read_package
    external, snapshot = context if context is not None else (
        external_mods(root, state, stop_event=stop_event),
        stock_snapshot(root, stop_event=stop_event, overlay_changes=(changes for _, changes in layers)))
    external.snapshot = snapshot
    protected, operations = {}, []
    for layer, changes in layers:
        identity = layer.get('independent_identity')
        if not identity or not (layer['active'] or layer.get('disabled')):
            continue
        path = f'.cdmw/independent-items/{identity}-{layer["independent_digest"]}.cditem'
        source = pending[path] if path in pending else Path(root) / path
        package = read_package(source, stop_event=stop_event)
        if package.identity != identity or package.digest != layer['independent_digest']:
            raise OverlayConflict('The retained independent package does not match its ownership history.')
        from cdmw.services.independent_mod_package import package_operations
        declared = package_operations(package)
        if layer.get('independent_operations', []) != declared:
            raise OverlayConflict('The retained package field operations disagree with its ownership layer.')
        if layer['active']:
            operations.extend((row['owner'], row['operations']) for row in declared)
            for key in _required_keys(package, snapshot, changes)['iteminfo']:
                protected.setdefault(key, []).append(package.identity)
        findings = check_package_dependencies(package, snapshot, external, changes, stop_event=stop_event)
        if on_log:
            for finding in findings:
                on_log(f'{package.title}: {", ".join(finding.mods)}: {finding.path}: {finding.detail}')
    if operations:
        from cdmw.domain.new_item.iteminfo_operations import compile_assignments
        compile_assignments(operations, {key: row.raw for key, row in snapshot.rows.items()}, protected=protected, stop_event=stop_event)
    current = foreign_underlay(external, baseline, snapshot, stop_event=stop_event)
    revision = snapshot.provenance.capture()
    revision.validate(stop_event)
    from cdmw.services.independent_item_install import _game_source_stamps
    state['sources'].update(_game_source_stamps(Path(root), revision))
    external.validate(stop_event)
    external.remember(state)
    return current, tuple(external.archives.items()), (revision, external.capture())


@dataclass(frozen=True)
class IndependentCompatibilityReport:
    root: Path
    findings: tuple[CompatibilityFinding, ...]
    folders: tuple[Path, ...] = ()

    @property
    def compatible(self):
        return not any(row.status in ('Conflict', 'Unknown') for row in self.findings)

    def text(self):
        lines = ['Compatible shared files can be composed.' if self.compatible else 'Review the conflicts or unsupported data before merging.']
        for row in self.findings:
            names = ', '.join(row.mods)
            lines.append('')
            if row.status == 'Compatible':
                lines.append(f'Compatible: {names}')
            elif row.status == 'Conflict':
                lines.append(f'Conflict: {names}')
            elif row.status == 'Unknown':
                lines.append(f'Unknown: {names}')
            elif row.status == 'Merge available':
                lines.append(f'Merge available: {names}')
            else:
                lines.append(f'No overlap: {names}')
            lines.extend((row.path, row.detail))
        lines.extend(('', 'This compares file data and recorded dependencies. Runtime plugins and in-game behaviour are not verified.'))
        return '\n'.join(lines)


def scan_independent_conflicts(root, *, folders=(), stop_event=None, on_log=None, _export=False):
    """Scan every mounted external provider, optionally adding an uninstalled folder."""
    from cdmw.services import archive_overlay_manager as overlays
    from cdmw.services.independent_item_install import load_registry
    from cdmw.services.independent_item_package import read_package, stock_snapshot
    root, folders = Path(root).resolve(), tuple(Path(p).resolve() for p in folders)
    observed = overlays._observe_state(root)
    state = overlays._load_index(root)
    if state is None or not any(layer.get('independent_identity') and layer['active'] for layer in state['layers']):
        return IndependentCompatibilityReport(root, (CompatibilityFinding('Unknown', (), '', 'Install an independent item before comparing other mods.'),), folders)
    load_registry(root)  # Validate that the retained bindings still match ownership.
    layers = [(layer, overlays._unpack_changes(root, layer, {}, stop_event)) for layer in state['layers']]
    snapshot = stock_snapshot(root, overlay_changes=(changes for _, changes in layers), stop_event=stop_event, on_log=on_log)
    external = external_mods(root, state, folders=folders, stop_event=stop_event, snapshot=snapshot)
    findings = list(external.findings)
    if 'meta/0.pathc' in external.paths:
        registry = root / 'meta/0.pathc'
        if not registry.is_file() or external.payload('meta/0.pathc', stop_event) != registry.read_bytes():
            findings.append(CompatibilityFinding('Unknown', external.labels(('meta/0.pathc',)), 'meta/0.pathc',
                'This external texture registry needs recorded texture ownership. Use Merge with a supported exported package.'))
    baseline, flags = {}, {}
    for layer, changes in layers:
        for path, change in changes.items():
            baseline.setdefault(path, change['before'])
            flags[path] = change['flags']
        if not layer['active'] or not layer.get('independent_identity'):
            continue
        relative = f'.cdmw/independent-items/{layer["independent_identity"]}-{layer["independent_digest"]}.cditem'
        snapshot.provenance.pin_file(root / relative)
        package = read_package(root / relative, stop_event=stop_event)
        if package.identity != layer['independent_identity'] or package.digest != layer['independent_digest']:
            raise OverlayConflict('The retained independent package has changed outside CDMW.')
        try:
            findings.extend(check_package_dependencies(package, snapshot, external, changes, stop_event=stop_event))
        except RunCancelled:
            raise
        except (ValueError, RuntimeError) as error:
            findings.append(CompatibilityFinding('Conflict', (layer['label'],), '', str(error)))
    # Compare in groups to report multiple independent file conflicts in one scan.
    output = {}
    for paths in sorted({_group(path) for path in baseline}):
        raise_if_cancelled(stop_event)
        try:
            current = foreign_underlay(external, {p: baseline.get(p) for p in paths}, snapshot, stop_event=stop_event)
            for layer, changes in layers:
                if layer['active']:
                    selected = {p: changes[p] for p in paths if p in changes}
                    current = merge_overlay_files({p: c['before'] for p, c in selected.items()},
                                                  {p: c['after'] for p, c in selected.items()}, current)
            output.update(current)
            labels = external.labels(paths)
            if labels:
                findings.append(CompatibilityFinding('Merge available', labels, paths[0],
                    'CDMW can preserve the external data and add the installed items in one shared output.'))
        except RunCancelled:
            raise
        except (ValueError, RuntimeError, KeyError, IndexError) as error:
            findings.append(CompatibilityFinding('Conflict', external.labels(paths), paths[0], str(error)))
    touched = set(baseline)
    dependency_paths = {row.path for row in findings if row.path}
    for path in sorted(external.paths - touched):
        if path in dependency_paths or any(path in _group(p) for p in dependency_paths):
            continue
        if len(external.providers[path]) > 1:
            try:
                external.payload(path, stop_event)
            except RunCancelled:
                raise
            except (ValueError, RuntimeError) as error:
                findings.append(CompatibilityFinding('Conflict', external.labels((path,)), path, str(error)))
    if not findings:
        findings.append(CompatibilityFinding('No overlap', (), '', 'No external file overlaps with the installed independent items were found.'))
    snapshot.provenance.capture().validate(stop_event)
    external.validate(stop_event)
    overlays._verify_observed_state(root, observed, 'during comparison')
    report = IndependentCompatibilityReport(root, tuple(dict.fromkeys(findings)), folders)
    if not _export:
        return report
    if not report.compatible:
        raise OverlayConflict(report.text())
    # Build a portable merged copy through the existing exporter. This is an
    # explicit folder export, never a write to a foreign archive or source mod.
    from cdmw.services.mod_merge_service import ModMergePlan
    from cdmw.core.mod_compatibility import compatibility_from_payloads, game_identity, hash_file
    for path in sorted(external.paths):
        raise_if_cancelled(stop_event)
        if path == 'meta/0.papgt':
            continue
        if path.startswith('meta/') and path != 'meta/0.pathc':
            raise OverlayConflict(f'Unsupported metadata in merged output: {path}.')
        if path not in output:
            output[path] = external.payload(path, stop_event)
            source = external.providers[path][0][1]
            flags[path] = source.entry.flags if source.entry is not None else 0
    files = {p: data for p, data in output.items() if data is not None}
    # Preserve guards for both the loaded ownership journals and external inputs.
    for relative, _data in observed:
        snapshot.provenance.pin_file(root / relative)
    for layer, _ in layers:
        snapshot.provenance.pin_file(root / overlays.overlay_journal_path(layer))
    for source in external.tracker.capture().payloads:
        snapshot.provenance.read(source.entry)
    loose_hashes = []
    for path, _stamp in external.tracker.capture().files:
        snapshot.provenance.pin_file(path)
        if path.is_file():
            loose_hashes.append((path, hash_file(path, stop_event)))
    evidence = compatibility_from_payloads(files, {p: snapshot.payload(p) if snapshot.has_entry(p) else baseline.get(p) for p in files},
                                          target_game=game_identity(root, stop_event))
    plan = ModMergePlan(folders, root, tuple((p, data, flags.get(p, 0)) for p, data in sorted(files.items())), (), (),
        tuple({'item_key': key} for layer, _ in layers if layer['active'] for key in layer['item_keys']),
        tuple(p for p in files if p.endswith('.dds') and not snapshot.has_entry(p)), '', snapshot.provenance.capture(),
        tuple(external.inventories), tuple(loose_hashes), evidence)
    plan.validate(stop_event)
    overlays._verify_observed_state(root, observed, 'during comparison')
    return plan


def prepare_independent_mod_merge(root, *, folders=(), stop_event=None, on_log=None):
    return scan_independent_conflicts(root, folders=folders, stop_event=stop_event, on_log=on_log, _export=True)
